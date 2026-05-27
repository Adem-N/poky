"""Tests du module d'équité."""
import random

import pytest

from poky.equity import (
    evaluate7,
    monte_carlo_equity,
    rlcard_to_phev,
    hand_strength_label,
)


def test_card_conversion():
    assert rlcard_to_phev("HQ") == "Qh"
    assert rlcard_to_phev("D4") == "4d"
    assert rlcard_to_phev("ST") == "Ts"
    assert rlcard_to_phev("CA") == "Ac"
    with pytest.raises(ValueError):
        rlcard_to_phev("XX")
    with pytest.raises(ValueError):
        rlcard_to_phev("H")


def test_evaluate7_orders_known_hands():
    royal = evaluate7(["Ah", "Kh"], ["Qh", "Jh", "Th", "2c", "3d"])
    pair_aces = evaluate7(["Ah", "Ac"], ["Kh", "Jh", "Td", "2c", "3d"])
    high_card = evaluate7(["2h", "3c"], ["5h", "7h", "9d", "Jc", "Kc"])
    # Plus petit = meilleur
    assert royal < pair_aces < high_card
    assert royal == 1


def test_hand_strength_labels():
    assert hand_strength_label(1) == "Quinte flush royale ou similaire"
    assert "Paire" in hand_strength_label(5000)
    assert "haute" in hand_strength_label(7000)


def test_aces_vs_kings_preflop():
    """AA contre KK heads-up : AA gagne ~82% (équité connue)."""
    eq = monte_carlo_equity(
        hole_rlcard=["SA", "HA"],  # As pique + As cœur
        board_rlcard=[],
        num_opponents=1,
        simulations=3000,
        rng=random.Random(42),
    )
    # AA vs random : ~85%. AA vs KK spécifiquement c'est 82% mais on simule contre random hands ici.
    # Donc on attend ~84-86%.
    assert 0.82 < eq < 0.90, f"AA contre 1 adversaire random : {eq:.3f}"


def test_seven_two_off_is_terrible():
    """72o préflop heads-up : la pire main, ~31% équité."""
    eq = monte_carlo_equity(
        hole_rlcard=["S7", "H2"],
        board_rlcard=[],
        num_opponents=1,
        simulations=3000,
        rng=random.Random(42),
    )
    assert 0.28 < eq < 0.36, f"72o vs random : {eq:.3f}"


def test_equity_decreases_with_more_opponents():
    """Une même main de force moyenne vaut moins d'équité contre plus d'adversaires."""
    rng = random.Random(123)
    eq1 = monte_carlo_equity(["HA", "DK"], [], 1, simulations=1500, rng=rng)
    rng = random.Random(123)
    eq2 = monte_carlo_equity(["HA", "DK"], [], 2, simulations=1500, rng=rng)
    assert eq1 > eq2, f"eq(1opp)={eq1} should be > eq(2opp)={eq2}"


def test_flush_draw_on_flop():
    """A♥K♥ avec deux cœurs au flop : équité élevée par tirage couleur + overcards."""
    eq = monte_carlo_equity(
        hole_rlcard=["HA", "HK"],
        board_rlcard=["H7", "H2", "C3"],  # flop avec 2 cœurs
        num_opponents=1,
        simulations=2000,
        rng=random.Random(42),
    )
    # Tirage flush ~36% + overcards ~12% non-overlap ≈ 50%+ d'équité
    assert eq > 0.5
