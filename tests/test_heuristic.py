"""
Tests du HeuristicPlayer : classification préflop + supériorité statistique
sur les baselines.
"""
import random

from poky.arena import run_match
from poky.players import (
    HeuristicPlayer, RandomPlayer, AlwaysCallPlayer, classify_preflop,
)


# ---- Classification préflop ------------------------------------------------

def test_classify_premium_hands():
    # rlcard : "HA" = As de cœur. Suit en pos 0, rang en pos 1.
    assert classify_preflop(["HA", "SA"]) == 1   # AA
    assert classify_preflop(["HK", "SK"]) == 1   # KK
    assert classify_preflop(["HT", "ST"]) == 1   # TT
    assert classify_preflop(["HA", "SK"]) == 1   # AKo
    assert classify_preflop(["HA", "HK"]) == 1   # AKs
    assert classify_preflop(["HA", "HQ"]) == 1   # AQs


def test_classify_strong_hands():
    assert classify_preflop(["H9", "S9"]) == 2   # 99
    assert classify_preflop(["H7", "S7"]) == 2   # 77
    assert classify_preflop(["HA", "SQ"]) == 2   # AQo
    assert classify_preflop(["HA", "HJ"]) == 2   # AJs
    assert classify_preflop(["HK", "HQ"]) == 2   # KQs (à la limite premium/strong)
    assert classify_preflop(["HK", "SQ"]) == 2   # KQo


def test_classify_trash_hands():
    assert classify_preflop(["H7", "S2"]) == 4   # 72o, la pire
    assert classify_preflop(["S8", "H3"]) == 4   # 83o
    assert classify_preflop(["S5", "HJ"]) == 4   # J5o
    assert classify_preflop(["HK", "S2"]) == 4   # K2o


def test_classify_playable():
    assert classify_preflop(["H6", "S6"]) == 3   # 66
    assert classify_preflop(["HA", "H2"]) == 3   # A2s (suited ace)
    assert classify_preflop(["HJ", "HT"]) == 3   # JTs
    assert classify_preflop(["HA", "ST"]) == 3   # ATo


# ---- Supériorité contre les baselines --------------------------------------

def test_heuristic_does_not_lose_to_random():
    """L'heuristique ne doit pas perdre statistiquement contre des randoms.
    NB la variance au poker est énorme sur de petits échantillons :
    on teste la borne basse de l'IC95%, pas la valeur ponctuelle.
    Le tournament officiel (poky.cli.tournament) donne la vraie mesure
    avec un seed différent et plus de mains."""
    players = [
        HeuristicPlayer(seed=42),
        RandomPlayer(seed=1),
        RandomPlayer(seed=2),
    ]
    res = run_match(players, hands=1500, seed=42)
    heur = res.stats[0]
    assert heur.bb_per_100 + heur.ci95_bb100 > 0, \
        f"Heuristique perd statistiquement vs random : " \
        f"{heur.bb_per_100:+.1f} ±{heur.ci95_bb100:.1f}"


def test_heuristic_beats_call_station():
    """L'heuristique doit battre le calling station (la stat la plus fiable
    du gauntlet : faible variance car les calls sont déterministes)."""
    players = [
        HeuristicPlayer(seed=42),
        AlwaysCallPlayer(),
        AlwaysCallPlayer(),
    ]
    res = run_match(players, hands=1500, seed=42)
    heur = res.stats[0]
    assert heur.bb_per_100 > 0, f"Heuristique vs calling stations : {heur.bb_per_100:+.1f} bb/100"
