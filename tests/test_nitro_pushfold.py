"""Unit tests for poky.nitro.pushfold solver.

Uses a small fake HU equity table for fast tests + one integration test
that exercises the real solver on a tiny iteration count.
"""
import random

import numpy as np
import pytest

from poky.abstraction.preflop import (
    NUM_PREFLOP_CLASSES, canonical_class, class_name,
)
from poky.nitro.equity_table import prior_distribution
from poky.nitro.pushfold import PushFoldSolver, Strategies


def _fake_hu_table() -> np.ndarray:
    """Fake HU equity: equity[i, j] = 0.5 + 0.4 * (j - i) / 168.

    Class 0 (AA) has equity ~0.9 vs class 168 (32o). Class i vs class i = 0.5.
    Anti-symmetric (sum = 1 across i,j swap).
    """
    n = NUM_PREFLOP_CLASSES
    i = np.arange(n).reshape(-1, 1)
    j = np.arange(n).reshape(1, -1)
    table = 0.5 + 0.4 * (j - i) / 168.0
    # Wait — if i < j (class i is "better"), equity of i should be HIGHER, not lower.
    # Class 0 (AA) vs class 168: AA equity should be near 1. j - i = 168 → 0.5 + 0.4 = 0.9.
    # But "i is better" means i wins. So eq[i=0, j=168] = 0.9 means class 0 has 90% equity. ✓
    # Actually no: with the formula eq[i, j] = 0.5 + 0.4 * (j - i) / 168:
    #   eq[0, 168] = 0.5 + 0.4 * (168 - 0) / 168 = 0.9 ✓ (AA wins 90% vs 32o)
    #   eq[168, 0] = 0.5 + 0.4 * (0 - 168) / 168 = 0.1 ✓ (32o wins 10% vs AA)
    # Good, anti-symmetric.
    return table.astype(np.float32)


def test_strategies_zeros_and_all_in():
    z = Strategies.zeros()
    assert np.all(z.btn_push == 0)
    a = Strategies.all_in()
    assert np.all(a.btn_push == 1)
    assert a.max_diff(z) == 1.0


def test_strategies_blend():
    z = Strategies.zeros()
    a = Strategies.all_in()
    half = z.blend(a, w_self=0.5)
    assert np.allclose(half.btn_push, 0.5)


def test_solver_initializes_and_one_iter_runs():
    """Smoke: solver runs 1 iteration without crashing."""
    table = _fake_hu_table()
    solver = PushFoldSolver(stack_bb=10, hu_eq_table=table, threeway_samples=10, seed=1)
    result = solver.solve(max_iter=3, tolerance=1e-6, verbose=False)
    assert isinstance(result, Strategies)
    # All strategies should be in [0, 1].
    for arr in (result.btn_push, result.sb_call_vs_btn,
                result.sb_push_after_btn_fold, result.bb_call_3way,
                result.bb_call_vs_btn, result.bb_call_vs_sb):
        assert np.all(arr >= 0) and np.all(arr <= 1)


def test_aa_pushes_at_all_stack_depths():
    """AA should be in the push range from any position at any stack depth
    we care about (6 to 15 BB) — it's the strongest hand."""
    table = _fake_hu_table()
    aa = canonical_class("HA", "DA")
    for stack in [6, 10, 15]:
        solver = PushFoldSolver(stack_bb=stack, hu_eq_table=table,
                                threeway_samples=10, seed=42)
        result = solver.solve(max_iter=20, tolerance=1e-3, verbose=False)
        assert result.btn_push[aa] >= 0.5, (
            f"AA on BTN should push at {stack}bb, got freq {result.btn_push[aa]}"
        )
        assert result.sb_push_after_btn_fold[aa] >= 0.5, (
            f"AA in SB (BTN folded) should push at {stack}bb, got freq "
            f"{result.sb_push_after_btn_fold[aa]}"
        )
        # AA should always call any all-in.
        assert result.sb_call_vs_btn[aa] >= 0.5
        assert result.bb_call_vs_btn[aa] >= 0.5
        assert result.bb_call_vs_sb[aa] >= 0.5
        assert result.bb_call_3way[aa] >= 0.5


def test_32o_folds_at_15bb():
    """The weakest offsuit hand should fold in most spots at deeper stacks."""
    table = _fake_hu_table()
    o32 = canonical_class("H3", "D2")
    solver = PushFoldSolver(stack_bb=15, hu_eq_table=table,
                            threeway_samples=10, seed=42)
    result = solver.solve(max_iter=30, tolerance=1e-3, verbose=False)
    # At 15bb, 32o should not call all-ins from SB or BB.
    assert result.sb_call_vs_btn[o32] < 0.5
    assert result.bb_call_vs_btn[o32] < 0.5
    assert result.bb_call_3way[o32] < 0.5


def test_btn_push_range_widens_as_stack_shrinks():
    """Push frequency on BTN should be wider at 6bb than at 15bb (fewer
    chips → bigger fold-equity vs SB/BB ranges → push wider)."""
    table = _fake_hu_table()
    prior = prior_distribution()
    pushed_widths = {}
    for stack in [6, 10, 15]:
        solver = PushFoldSolver(stack_bb=stack, hu_eq_table=table,
                                threeway_samples=10, seed=42)
        result = solver.solve(max_iter=30, tolerance=1e-3, verbose=False)
        # Aggregate push frequency weighted by combo prior.
        pushed_widths[stack] = float((result.btn_push * prior).sum())
    # Wider at 6bb than at 15bb.
    assert pushed_widths[6] >= pushed_widths[15], (
        f"Expected wider push at 6bb than 15bb, got {pushed_widths}"
    )
