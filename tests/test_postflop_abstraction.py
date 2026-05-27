"""
Tests des buckets postflop (Phase 1 du plan).

Critères :
  - 5 buckets par street (0..4)
  - AA sur board dry (2-3-7 rainbow) → bucket élevé
  - 72o sur board dangereux (K-Q-J de cœur, mais on a aucun cœur) → bucket bas
  - Déterminisme avec même seed
  - Pas de crash sur cas marginaux
"""
import random

import pytest

from poky.abstraction import (
    flop_bucket, turn_bucket, river_bucket, postflop_bucket,
    get_boundaries, NUM_POSTFLOP_BUCKETS,
)


def test_calibration_loads():
    """Charge / calcule les frontières. Vérifie la structure."""
    b = get_boundaries()
    assert set(b.keys()) == {"flop", "turn", "river"}
    for street, bnd in b.items():
        assert len(bnd) == NUM_POSTFLOP_BUCKETS - 1, \
            f"{street}: {len(bnd)} frontières, attendu {NUM_POSTFLOP_BUCKETS - 1}"
        # Frontières doivent être triées croissantes
        assert bnd == sorted(bnd)
        # Frontières dans [0, 1]
        assert all(0 <= x <= 1 for x in bnd)


def test_premium_dry_flop_high_bucket():
    """AA sur 2-3-7 rainbow → bucket haut (3 ou 4 sur 0-4)."""
    rng = random.Random(42)
    bucket = flop_bucket(
        hole=["HA", "DA"],
        board=["S2", "H3", "C7"],
        simulations=500, rng=rng,
    )
    assert bucket >= 3, f"AA sur 2-3-7 rainbow devrait être bucket ≥ 3, got {bucket}"


def test_trash_dangerous_flop_low_bucket():
    """72o sur K-Q-J ♥ (no flush draw for us) → bucket bas (0 ou 1)."""
    rng = random.Random(42)
    bucket = flop_bucket(
        hole=["S7", "C2"],         # 7♠ 2♣ — no hearts
        board=["HK", "HQ", "HJ"],  # 3 hearts straight on board
        simulations=500, rng=rng,
    )
    assert bucket <= 1, f"72o sur K-Q-J ♥ devrait être bucket ≤ 1, got {bucket}"


def test_river_set_high_bucket():
    """Set de 7 sur board sans flush ni straight évident."""
    rng = random.Random(42)
    bucket = river_bucket(
        hole=["S7", "H7"],
        board=["C7", "D2", "H5", "S9", "DJ"],
        simulations=500, rng=rng,
    )
    assert bucket >= 3, f"Set de 7 sur river safe devrait être bucket ≥ 3, got {bucket}"


def test_determinism_with_same_seed():
    """Mêmes inputs + même seed → même bucket."""
    b1 = flop_bucket(["HA", "DA"], ["S2", "H3", "C7"],
                     simulations=200, rng=random.Random(99))
    b2 = flop_bucket(["HA", "DA"], ["S2", "H3", "C7"],
                     simulations=200, rng=random.Random(99))
    assert b1 == b2


def test_postflop_bucket_dispatch():
    """postflop_bucket dispatch correctement selon len(board)."""
    rng = random.Random(7)
    f = postflop_bucket(["HA", "DA"], ["S2", "H3", "C7"], rng=rng)
    t = postflop_bucket(["HA", "DA"], ["S2", "H3", "C7", "D5"], rng=rng)
    r = postflop_bucket(["HA", "DA"], ["S2", "H3", "C7", "D5", "C9"], rng=rng)
    assert all(0 <= b < NUM_POSTFLOP_BUCKETS for b in (f, t, r))


def test_wrong_board_length_raises():
    """Mauvaise taille de board → erreur claire."""
    with pytest.raises(ValueError):
        flop_bucket(["HA", "DA"], ["S2", "H3"])  # only 2 cards
    with pytest.raises(ValueError):
        turn_bucket(["HA", "DA"], ["S2", "H3", "C7"])  # only 3
    with pytest.raises(ValueError):
        river_bucket(["HA", "DA"], ["S2", "H3", "C7", "D5"])  # only 4
    with pytest.raises(ValueError):
        postflop_bucket(["HA", "DA"], ["S2"])  # too few
