"""Unit tests for poky.nitro.equity_table."""
import random

import numpy as np
import pytest

from poky.abstraction.preflop import NUM_PREFLOP_CLASSES, canonical_class
from poky.nitro.equity_table import (
    combo_count,
    combo_counts,
    hu_equity_mc,
    prior_distribution,
    threeway_equity_mc,
)


# ---- Combo counts ------------------------------------------------------

def test_combo_counts_sum_to_1326():
    counts = combo_counts()
    assert int(counts.sum()) == 1326   # C(52, 2)


def test_combo_count_per_type():
    # Pairs have 6 combos.
    aa = canonical_class("HA", "DA")
    assert combo_count(aa) == 6
    # Suited has 4 combos.
    aks = canonical_class("HA", "HK")
    assert combo_count(aks) == 4
    # Offsuit has 12 combos.
    ako = canonical_class("HA", "DK")
    assert combo_count(ako) == 12


def test_prior_sums_to_one():
    prior = prior_distribution()
    assert abs(prior.sum() - 1.0) < 1e-12


# ---- HU equity sanity --------------------------------------------------

def test_aa_vs_22_hu_equity_around_80():
    rng = random.Random(7)
    aa = canonical_class("HA", "DA")
    twos = canonical_class("H2", "D2")
    eq = hu_equity_mc(aa, twos, simulations=400, rng=rng)
    # Published: AA vs 22 ≈ 80.3% HU.
    assert 0.74 < eq < 0.86, f"AA vs 22 eq = {eq}, expected ~0.80"


def test_aa_vs_aa_hu_equity_is_05():
    rng = random.Random(7)
    aa = canonical_class("HA", "DA")
    eq = hu_equity_mc(aa, aa, simulations=400, rng=rng)
    # Same hand class -> equity ~0.5 (with some MC variance).
    assert 0.42 < eq < 0.58, f"AA vs AA eq = {eq}, expected ~0.5"


def test_32o_vs_aks_hu_equity_low():
    rng = random.Random(7)
    aks = canonical_class("HA", "HK")
    o32 = canonical_class("H3", "D2")
    eq = hu_equity_mc(o32, aks, simulations=400, rng=rng)
    # 32o vs AKs is one of the worst HU matchups.
    assert eq < 0.4, f"32o vs AKs eq = {eq}, expected very low"


# ---- 3-way equity sanity ----------------------------------------------

def test_threeway_equity_sums_to_one():
    rng = random.Random(11)
    aa = canonical_class("HA", "DA")
    kk = canonical_class("HK", "DK")
    qq = canonical_class("HQ", "DQ")
    ea, eb, ec = threeway_equity_mc(aa, kk, qq, simulations=400, rng=rng)
    assert abs((ea + eb + ec) - 1.0) < 0.02, (ea, eb, ec)


def test_threeway_aa_dominant():
    rng = random.Random(11)
    aa = canonical_class("HA", "DA")
    twos = canonical_class("H2", "D2")
    threes = canonical_class("H3", "D3")
    ea, eb, ec = threeway_equity_mc(aa, twos, threes, simulations=400, rng=rng)
    # AA should be the favorite in this spot — but only by a margin
    # (3-way reduces vs HU). Published: AA vs 22 vs 33 has AA at ~62%.
    assert ea > 0.55, f"AA equity in 3-way vs small pairs = {ea}, expected > 0.55"
