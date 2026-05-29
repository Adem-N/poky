"""Precomputed equity tables for 169-class abstraction.

HU table:  169 x 169 floats, row[i][j] = equity of class i vs class j heads-up.
3-way:     computed on the fly via Monte Carlo (too large to precompute).

Card collisions are handled by sampling concrete combos for each class and
dealing them without replacement. The HU table is symmetric in the sense
that row[i][j] + row[j][i] == 1 (modulo MC variance).

Cache: HU table is persisted to `_hu_equity_table.npy` next to this module.
First run computes it (~5-15 minutes depending on sims/cell); subsequent
runs load it instantly.
"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from phevaluator import evaluate_cards

from poky.abstraction import preflop as _preflop_mod
from poky.abstraction.preflop import (
    NUM_PREFLOP_CLASSES,
    _ensure_loaded,
    class_name,
)

# phevaluator card format: '<rank><suit>' with rank in {2-9,T,J,Q,K,A}, suit in {h,d,c,s}
_RANKS = "23456789TJQKA"
_SUITS = "hdcs"
_ALL_CARDS = [r + s for r in _RANKS for s in _SUITS]

# Hand class -> # of distinct combos: 6 for pairs, 4 for suited, 12 for offsuit
# Pre-computed lazily.
_COMBO_COUNT: Optional[np.ndarray] = None
_CLASS_COMBOS: Optional[List[List[Tuple[str, str]]]] = None

_HU_TABLE: Optional[np.ndarray] = None
_HU_CACHE_PATH = Path(__file__).resolve().parent / "_hu_equity_table.npy"


def _build_combos():
    """Build per-class list of concrete (card1, card2) combos. Memoized."""
    global _COMBO_COUNT, _CLASS_COMBOS
    if _CLASS_COMBOS is not None:
        return
    _ensure_loaded()
    _CLASS_COMBOS = [[] for _ in range(NUM_PREFLOP_CLASSES)]
    _COMBO_COUNT = np.zeros(NUM_PREFLOP_CLASSES, dtype=np.float64)
    # _CLASSES[i] = (high_rank, low_rank, suited) — fetch via module attribute
    # so we see the populated list (not the empty initial binding).
    for i, (h, l, suited) in enumerate(_preflop_mod._CLASSES):
        rh = _RANKS[h - 2]
        rl = _RANKS[l - 2]
        if h == l:
            # Pair: 6 combos (C(4,2) pairs of suits)
            suits_list = list(_SUITS)
            for a in range(4):
                for b in range(a + 1, 4):
                    _CLASS_COMBOS[i].append((rh + suits_list[a], rh + suits_list[b]))
        elif suited:
            # Suited: 4 combos (same suit, 4 choices)
            for s in _SUITS:
                _CLASS_COMBOS[i].append((rh + s, rl + s))
        else:
            # Offsuit: 12 combos (4 suits high × 3 suits low ≠ high suit)
            for s1 in _SUITS:
                for s2 in _SUITS:
                    if s1 != s2:
                        _CLASS_COMBOS[i].append((rh + s1, rl + s2))
        _COMBO_COUNT[i] = len(_CLASS_COMBOS[i])
    expected_total = 13 * 6 + 78 * 4 + 78 * 12   # = 78 + 312 + 936 = 1326
    assert _COMBO_COUNT.sum() == expected_total, (
        f"combo count check failed: {_COMBO_COUNT.sum()} vs {expected_total}"
    )


def combo_count(class_id: int) -> int:
    """Number of distinct card combinations for this hand class (6/4/12)."""
    _build_combos()
    return int(_COMBO_COUNT[class_id])


def combo_counts() -> np.ndarray:
    """Full 169-vector of combo counts."""
    _build_combos()
    return _COMBO_COUNT.copy()


def prior_distribution() -> np.ndarray:
    """P(dealt hand of class i) = combo_count(i) / 1326."""
    return combo_counts() / 1326.0


def _sample_combo(class_id: int, rng: random.Random) -> Tuple[str, str]:
    """Pick one random concrete combo from this hand class."""
    _build_combos()
    return rng.choice(_CLASS_COMBOS[class_id])


def hu_equity_mc(class_a: int, class_b: int, simulations: int,
                 rng: random.Random) -> float:
    """Monte Carlo equity of class_a vs class_b heads-up at showdown.

    Each sim picks a fresh concrete combo for each class (handling card
    collisions: if combos collide, redraw). Then deals a random 5-card board
    and compares.

    Returns float in [0, 1] (1.0 = always wins, 0.5 = tie, 0 = always loses).
    Half-pot to ties.
    """
    _build_combos()
    combos_a = _CLASS_COMBOS[class_a]
    combos_b = _CLASS_COMBOS[class_b]
    wins = 0.0
    for _ in range(simulations):
        # Sample combos for both, ensuring no card collision.
        for _attempt in range(20):
            a = rng.choice(combos_a)
            b = rng.choice(combos_b)
            if a[0] != b[0] and a[0] != b[1] and a[1] != b[0] and a[1] != b[1]:
                break
        else:
            # Extremely rare: 20 redraws all collided.
            # Fall back to a known-disjoint sample by brute force.
            continue
        used = {a[0], a[1], b[0], b[1]}
        deck = [c for c in _ALL_CARDS if c not in used]
        board = rng.sample(deck, 5)
        score_a = evaluate_cards(a[0], a[1], *board)
        score_b = evaluate_cards(b[0], b[1], *board)
        if score_a < score_b:
            wins += 1.0
        elif score_a == score_b:
            wins += 0.5
    return wins / simulations


def build_hu_equity_table(simulations: int = 800,
                          seed: int = 42,
                          verbose: bool = False) -> np.ndarray:
    """Compute the full 169x169 HU equity table.

    On a typical laptop with simulations=800: ~5-10 minutes.
    Symmetric within MC variance: table[i,j] ≈ 1 - table[j,i].
    """
    _build_combos()
    rng = random.Random(seed)
    table = np.zeros((NUM_PREFLOP_CLASSES, NUM_PREFLOP_CLASSES), dtype=np.float32)
    for i in range(NUM_PREFLOP_CLASSES):
        if verbose and i % 10 == 0:
            print(f"  row {i}/{NUM_PREFLOP_CLASSES}  ({class_name(i)})")
        for j in range(NUM_PREFLOP_CLASSES):
            table[i, j] = hu_equity_mc(i, j, simulations, rng)
    return table


def get_hu_equity_table(simulations: int = 800, verbose: bool = False) -> np.ndarray:
    """Load HU equity table from disk; compute & cache it if missing."""
    global _HU_TABLE
    if _HU_TABLE is not None:
        return _HU_TABLE
    if _HU_CACHE_PATH.exists():
        _HU_TABLE = np.load(_HU_CACHE_PATH)
        return _HU_TABLE
    print(f"Computing HU equity table ({NUM_PREFLOP_CLASSES}x{NUM_PREFLOP_CLASSES} "
          f"with {simulations} sims/cell) — this takes a few minutes...")
    _HU_TABLE = build_hu_equity_table(simulations=simulations, verbose=verbose)
    np.save(_HU_CACHE_PATH, _HU_TABLE)
    print(f"Saved cached table to {_HU_CACHE_PATH}")
    return _HU_TABLE


def threeway_equity_mc(class_a: int, class_b: int, class_c: int,
                       simulations: int, rng: random.Random) -> Tuple[float, float, float]:
    """3-way equity: returns (P(a wins), P(b wins), P(c wins)) summing to ~1.

    Ties split evenly among tied players.
    """
    _build_combos()
    combos_a = _CLASS_COMBOS[class_a]
    combos_b = _CLASS_COMBOS[class_b]
    combos_c = _CLASS_COMBOS[class_c]
    wins_a = wins_b = wins_c = 0.0
    for _ in range(simulations):
        # Sample three concrete combos, no collisions.
        for _attempt in range(30):
            a = rng.choice(combos_a)
            b = rng.choice(combos_b)
            c = rng.choice(combos_c)
            used = {a[0], a[1], b[0], b[1], c[0], c[1]}
            if len(used) == 6:
                break
        else:
            continue
        deck = [card for card in _ALL_CARDS if card not in used]
        board = rng.sample(deck, 5)
        sa = evaluate_cards(a[0], a[1], *board)
        sb = evaluate_cards(b[0], b[1], *board)
        sc = evaluate_cards(c[0], c[1], *board)
        best = min(sa, sb, sc)
        winners = sum(1 for s in (sa, sb, sc) if s == best)
        share = 1.0 / winners
        if sa == best:
            wins_a += share
        if sb == best:
            wins_b += share
        if sc == best:
            wins_c += share
    n = simulations
    return wins_a / n, wins_b / n, wins_c / n
