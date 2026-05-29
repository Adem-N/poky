"""Nash equilibrium push/fold solver for 3-max NLHE short stack.

Game tree (preflop, action order BTN -> SB -> BB):
    BTN: PUSH or FOLD
      if BTN_push:
        SB: CALL or FOLD
          if SB_call:
            BB: CALL or FOLD       (3-way showdown if call)
          else (SB_fold):
            BB: CALL or FOLD       (HU vs BTN if call)
      else (BTN_fold):
        SB: PUSH or FOLD
          if SB_push:
            BB: CALL or FOLD       (HU vs SB if call)
          else (SB_fold):
            BB collects 0.5 BB (SB walks)

Six strategy vectors, each 169-long (per hand class, frequency of "aggressive" action):
    btn_push                 = P(BTN pushes | dealt hand h)
    sb_call_vs_btn           = P(SB calls   | BTN pushed,  dealt hand h)
    sb_push_after_btn_fold   = P(SB pushes  | BTN folded,  dealt hand h)
    bb_call_3way             = P(BB calls   | BTN pushed, SB called, dealt hand h)
    bb_call_vs_btn           = P(BB calls   | BTN pushed, SB folded, dealt hand h)
    bb_call_vs_sb            = P(BB calls   | BTN folded, SB pushed, dealt hand h)

Solver: iterated best response with strategy averaging (Fictitious Play).
Converges in ~50-200 iterations for 6 BB <= stack <= 15 BB.

Chip EV convention (S = effective stack in BB):
    BTN fold       -> EV = 0
    SB fold        -> EV = -0.5
    BB fold        -> EV = -1.0

    Winning outcomes (per perspective):
        Win blinds (everyone fold to BTN push):       BTN gets +1.5
        Win HU vs SB (BB folded):     BTN +(S+1)   / SB -S
        Win HU vs BB (SB folded):     BTN +(S+0.5) / BB -S
        Win 3-way:                    Winner +2S / Losers -S
        Win HU SB-vs-BB:              Winner +S / Loser -S
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from poky.abstraction.preflop import NUM_PREFLOP_CLASSES, class_name
from poky.nitro.equity_table import (
    combo_counts,
    get_hu_equity_table,
    prior_distribution,
    threeway_equity_mc,
)


@dataclass
class Strategies:
    """The six strategy vectors of the 3-max push/fold game."""
    btn_push: np.ndarray
    sb_call_vs_btn: np.ndarray
    sb_push_after_btn_fold: np.ndarray
    bb_call_3way: np.ndarray
    bb_call_vs_btn: np.ndarray
    bb_call_vs_sb: np.ndarray

    @classmethod
    def zeros(cls) -> "Strategies":
        z = lambda: np.zeros(NUM_PREFLOP_CLASSES, dtype=np.float64)
        return cls(z(), z(), z(), z(), z(), z())

    @classmethod
    def all_in(cls) -> "Strategies":
        o = lambda: np.ones(NUM_PREFLOP_CLASSES, dtype=np.float64)
        return cls(o(), o(), o(), o(), o(), o())

    def copy(self) -> "Strategies":
        return Strategies(
            self.btn_push.copy(),
            self.sb_call_vs_btn.copy(),
            self.sb_push_after_btn_fold.copy(),
            self.bb_call_3way.copy(),
            self.bb_call_vs_btn.copy(),
            self.bb_call_vs_sb.copy(),
        )

    def max_diff(self, other: "Strategies") -> float:
        return max(
            float(np.max(np.abs(self.btn_push - other.btn_push))),
            float(np.max(np.abs(self.sb_call_vs_btn - other.sb_call_vs_btn))),
            float(np.max(np.abs(self.sb_push_after_btn_fold - other.sb_push_after_btn_fold))),
            float(np.max(np.abs(self.bb_call_3way - other.bb_call_3way))),
            float(np.max(np.abs(self.bb_call_vs_btn - other.bb_call_vs_btn))),
            float(np.max(np.abs(self.bb_call_vs_sb - other.bb_call_vs_sb))),
        )

    def blend(self, other: "Strategies", w_self: float) -> "Strategies":
        """Convex combination: result = w_self * self + (1 - w_self) * other."""
        w = w_self
        u = 1 - w
        return Strategies(
            w * self.btn_push + u * other.btn_push,
            w * self.sb_call_vs_btn + u * other.sb_call_vs_btn,
            w * self.sb_push_after_btn_fold + u * other.sb_push_after_btn_fold,
            w * self.bb_call_3way + u * other.bb_call_3way,
            w * self.bb_call_vs_btn + u * other.bb_call_vs_btn,
            w * self.bb_call_vs_sb + u * other.bb_call_vs_sb,
        )

    def to_dict(self) -> dict:
        from poky.abstraction.preflop import class_name as cn
        out = {}
        for field_name in ("btn_push", "sb_call_vs_btn", "sb_push_after_btn_fold",
                           "bb_call_3way", "bb_call_vs_btn", "bb_call_vs_sb"):
            arr = getattr(self, field_name)
            out[field_name] = {cn(i): float(arr[i]) for i in range(NUM_PREFLOP_CLASSES)}
        return out


def _range_weights(strat: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """Unnormalized range weights = prior probability of each class * frequency in this range."""
    return prior * strat


def _hu_equity_vs_range(hu_table: np.ndarray, range_weights: np.ndarray) -> np.ndarray:
    """169-vector: for each class h, equity of h vs (range described by weights)."""
    total = range_weights.sum()
    if total <= 1e-12:
        return np.zeros(NUM_PREFLOP_CLASSES)
    # hu_table[i, j] = eq(class i vs class j); contract j-dim against weighted range.
    return (hu_table @ range_weights) / total


def _threeway_equity_vs_ranges(
    perspective: str,                # "btn" | "sb" | "bb" — whose hand h we vary
    sb_range_w: np.ndarray,          # weights for SB's range
    bb_range_w: np.ndarray,          # weights for BB's range
    btn_range_w: np.ndarray,         # weights for BTN's range
    samples_per_class: int,
    rng: random.Random,
) -> np.ndarray:
    """169-vector: for each class h, 3-way win probability of h against the
    sampled ranges of the other two players.

    Samples (samples_per_class) pairs (h_other1, h_other2) drawn from the
    correct joint distribution and averages 3-way equity.
    """
    # Decide which two range vectors to sample from for each "perspective":
    if perspective == "btn":
        sample_a_w = sb_range_w   # opponent 1 = SB
        sample_b_w = bb_range_w   # opponent 2 = BB
    elif perspective == "sb":
        sample_a_w = btn_range_w
        sample_b_w = bb_range_w
    elif perspective == "bb":
        sample_a_w = btn_range_w
        sample_b_w = sb_range_w
    else:
        raise ValueError(perspective)

    if sample_a_w.sum() <= 1e-12 or sample_b_w.sum() <= 1e-12:
        return np.zeros(NUM_PREFLOP_CLASSES)

    p_a = sample_a_w / sample_a_w.sum()
    p_b = sample_b_w / sample_b_w.sum()

    rng_np = np.random.default_rng(rng.randint(0, 2**31 - 1))
    sampled_a = rng_np.choice(NUM_PREFLOP_CLASSES, size=samples_per_class, p=p_a)
    sampled_b = rng_np.choice(NUM_PREFLOP_CLASSES, size=samples_per_class, p=p_b)

    eq_vec = np.zeros(NUM_PREFLOP_CLASSES)
    for h in range(NUM_PREFLOP_CLASSES):
        s = 0.0
        for k in range(samples_per_class):
            ha, hb = int(sampled_a[k]), int(sampled_b[k])
            # 3-way equity: order matters for the return tuple.
            ea, eb, ec = threeway_equity_mc(h, ha, hb, simulations=1, rng=rng)
            s += ea
        eq_vec[h] = s / samples_per_class
    return eq_vec


class PushFoldSolver:
    """Fictitious Play solver for 3-max push/fold Nash equilibrium."""

    def __init__(self, stack_bb: float, sb_bb: float = 0.5, bb_bb: float = 1.0,
                 hu_eq_table: Optional[np.ndarray] = None,
                 threeway_samples: int = 60,
                 seed: int = 42):
        if stack_bb <= bb_bb:
            raise ValueError(f"stack_bb ({stack_bb}) must be > bb ({bb_bb})")
        self.S = float(stack_bb)
        self.sb = float(sb_bb)
        self.bb = float(bb_bb)
        self.threeway_samples = threeway_samples
        self.rng = random.Random(seed)
        self.hu = hu_eq_table if hu_eq_table is not None else get_hu_equity_table()
        self.prior = prior_distribution()
        # Initialize with everyone open-jamming most hands — fast convergence.
        self.strats = Strategies.all_in()
        self.iterations_run = 0
        self.history: list = []

    def best_response(self, opp: Strategies) -> Strategies:
        """Compute the best-response strategies of every player to `opp`."""
        S = self.S
        prior = self.prior

        # Range weight vectors (probability that opp has each class AND chooses
        # to call/push with it).
        sb_call_w = _range_weights(opp.sb_call_vs_btn, prior)
        bb_call_3way_w = _range_weights(opp.bb_call_3way, prior)
        bb_call_vs_btn_w = _range_weights(opp.bb_call_vs_btn, prior)
        bb_call_vs_sb_w = _range_weights(opp.bb_call_vs_sb, prior)
        btn_push_w = _range_weights(opp.btn_push, prior)
        sb_push_w = _range_weights(opp.sb_push_after_btn_fold, prior)

        p_sb_call = sb_call_w.sum()
        p_bb_call_3w = bb_call_3way_w.sum()
        p_bb_call_vs_btn = bb_call_vs_btn_w.sum()
        p_bb_call_vs_sb = bb_call_vs_sb_w.sum()
        p_btn_push = btn_push_w.sum()
        p_sb_push = sb_push_w.sum()

        # HU equity vectors (vectorized).
        eq_btn_vs_sb_calls = _hu_equity_vs_range(self.hu, sb_call_w)
        eq_btn_vs_bb_calls = _hu_equity_vs_range(self.hu, bb_call_vs_btn_w)
        eq_sb_vs_btn_pushes = _hu_equity_vs_range(self.hu, btn_push_w)
        eq_sb_vs_bb_calls = _hu_equity_vs_range(self.hu, bb_call_vs_sb_w)
        eq_bb_vs_btn_pushes_hu = _hu_equity_vs_range(self.hu, btn_push_w)
        eq_bb_vs_sb_pushes = _hu_equity_vs_range(self.hu, sb_push_w)

        # 3-way equity vectors (MC sampling).
        eq_btn_3way = _threeway_equity_vs_ranges(
            "btn", sb_call_w, bb_call_3way_w, btn_push_w,
            self.threeway_samples, self.rng)
        eq_sb_3way = _threeway_equity_vs_ranges(
            "sb", sb_call_w, bb_call_3way_w, btn_push_w,
            self.threeway_samples, self.rng)
        eq_bb_3way = _threeway_equity_vs_ranges(
            "bb", sb_call_w, bb_call_3way_w, btn_push_w,
            self.threeway_samples, self.rng)

        # ---- BTN push EV ----
        ev_btn_push = (
            (1 - p_sb_call) * (1 - p_bb_call_vs_btn) * 1.5
            + (1 - p_sb_call) * p_bb_call_vs_btn * (
                eq_btn_vs_bb_calls * (S + 0.5) + (1 - eq_btn_vs_bb_calls) * (-S)
            )
            + p_sb_call * (1 - p_bb_call_3w) * (
                eq_btn_vs_sb_calls * (S + 1) + (1 - eq_btn_vs_sb_calls) * (-S)
            )
            + p_sb_call * p_bb_call_3w * (
                eq_btn_3way * (2 * S) + (1 - eq_btn_3way) * (-S)
            )
        )
        # EV(BTN fold) = 0
        br_btn = (ev_btn_push > 0).astype(np.float64)

        # ---- SB call (after BTN push) EV ----
        # Outcomes: BB folds (HU vs BTN) | BB calls (3-way)
        ev_sb_call = (
            (1 - p_bb_call_3w) * (
                eq_sb_vs_btn_pushes * (S + 1) + (1 - eq_sb_vs_btn_pushes) * (-S)
            )
            + p_bb_call_3w * (
                eq_sb_3way * (2 * S) + (1 - eq_sb_3way) * (-S)
            )
        )
        # EV(SB fold) = -0.5
        br_sb_call = (ev_sb_call > -0.5).astype(np.float64)

        # ---- SB push after BTN folded EV ----
        ev_sb_push = (
            (1 - p_bb_call_vs_sb) * 1.0          # SB collects BB walk
            + p_bb_call_vs_sb * (
                eq_sb_vs_bb_calls * S + (1 - eq_sb_vs_bb_calls) * (-S)
            )
        )
        # EV(SB fold after BTN fold) = -0.5
        br_sb_push = (ev_sb_push > -0.5).astype(np.float64)

        # ---- BB call 3-way (after BTN push, SB call) EV ----
        ev_bb_call_3w = eq_bb_3way * (2 * S) + (1 - eq_bb_3way) * (-S)
        # EV(BB fold) = -1
        br_bb_call_3w = (ev_bb_call_3w > -1.0).astype(np.float64)

        # ---- BB call vs BTN push (SB folded) EV ----
        ev_bb_call_vs_btn = (
            eq_bb_vs_btn_pushes_hu * (S + 0.5) + (1 - eq_bb_vs_btn_pushes_hu) * (-S)
        )
        br_bb_call_vs_btn = (ev_bb_call_vs_btn > -1.0).astype(np.float64)

        # ---- BB call vs SB push (BTN folded) EV ----
        ev_bb_call_vs_sb = (
            eq_bb_vs_sb_pushes * S + (1 - eq_bb_vs_sb_pushes) * (-S)
        )
        br_bb_call_vs_sb = (ev_bb_call_vs_sb > -1.0).astype(np.float64)

        return Strategies(
            btn_push=br_btn,
            sb_call_vs_btn=br_sb_call,
            sb_push_after_btn_fold=br_sb_push,
            bb_call_3way=br_bb_call_3w,
            bb_call_vs_btn=br_bb_call_vs_btn,
            bb_call_vs_sb=br_bb_call_vs_sb,
        )

    def solve(self, max_iter: int = 200, tolerance: float = 5e-3,
              verbose: bool = False) -> Strategies:
        """Iterate Fictitious Play until change between iters < tolerance."""
        avg = self.strats.copy()
        t0 = time.time()
        for t in range(1, max_iter + 1):
            br = self.best_response(avg)
            new_avg = avg.blend(br, w_self=t / (t + 1))
            diff = new_avg.max_diff(avg)
            avg = new_avg
            self.iterations_run = t
            self.history.append({"iter": t, "max_diff": diff})
            if verbose and (t <= 5 or t % 10 == 0):
                elapsed = time.time() - t0
                print(f"  iter {t:>3} | max_diff = {diff:.4f} | elapsed = {elapsed:.1f}s")
            if diff < tolerance and t >= 20:
                if verbose:
                    print(f"  CONVERGED at iter {t} (diff={diff:.4f} < {tolerance})")
                break
        self.strats = avg
        return avg

    def summary(self) -> str:
        """Pretty-print: top N hands per strategy that are pushed/called > 50%."""
        lines = [f"=== Push/Fold equilibrium, stack = {self.S}bb, "
                 f"{self.iterations_run} iters ==="]
        for field_name in ("btn_push", "sb_call_vs_btn", "sb_push_after_btn_fold",
                           "bb_call_3way", "bb_call_vs_btn", "bb_call_vs_sb"):
            arr = getattr(self.strats, field_name)
            agg = float((arr * self.prior).sum())
            top = [class_name(i) for i in range(NUM_PREFLOP_CLASSES) if arr[i] >= 0.5]
            lines.append(f"\n  {field_name}: {agg*100:.1f}% of hands  ({len(top)} classes >= 50%)")
            lines.append(f"    {', '.join(top[:30])}{'...' if len(top) > 30 else ''}")
        return "\n".join(lines)
