"""Sanity tests pour Tier 2 postflop rules (Phase X2)."""
import random

from poky.engine import Action, Observation, PlayerStatus, Stage
from poky.expert.postflop_rules import (
    FlopTexture, cbet_flop_pfa, flop_texture, pro_postflop_strategy,
)


# ============ TEXTURE CLASSIFIER ============

def test_texture_returns_none_non_flop():
    """Pas 3 cartes → None (turn/river hors scope X2 v0.1)."""
    assert flop_texture([]) is None
    assert flop_texture(["HA", "HK"]) is None
    assert flop_texture(["HA", "HK", "HQ", "HJ"]) is None


def test_texture_dry_rainbow():
    """K72 rainbow → DRY (spread > 4, 3 suits différents, pas paired)."""
    assert flop_texture(["HK", "D7", "S2"]) == FlopTexture.DRY


def test_texture_dry_high_spread():
    """A82 rainbow → DRY."""
    assert flop_texture(["HA", "D8", "C2"]) == FlopTexture.DRY


def test_texture_paired():
    """KK7 → PAIRED."""
    assert flop_texture(["HK", "DK", "S7"]) == FlopTexture.PAIRED


def test_texture_paired_low():
    """772 → PAIRED."""
    assert flop_texture(["H7", "D7", "S2"]) == FlopTexture.PAIRED


def test_texture_monotone_wet():
    """Monotone → WET (flush draw)."""
    assert flop_texture(["HK", "H7", "H2"]) == FlopTexture.WET


def test_texture_twotone_connected_wet():
    """T98 two-tone (Th 9s 8h) → WET (str8 draw + flush draw)."""
    assert flop_texture(["HT", "S9", "H8"]) == FlopTexture.WET


def test_texture_twotone_disconnected_semi():
    """Ks 7c 2s two-tone mais spread 11 → SEMI (juste flush draw)."""
    assert flop_texture(["SK", "C7", "S2"]) == FlopTexture.SEMI


def test_texture_rainbow_connected_semi():
    """9h 8c 7d rainbow connecté → SEMI (str8 draws communs)."""
    assert flop_texture(["H9", "C8", "D7"]) == FlopTexture.SEMI


# ============ C-BET FLOP PFA ============

def _make_flop_obs(hole, board, num_players=2, dealer_id=0,
                   player_id=1, pot=10, my_committed=4,
                   all_committed=None, legal=None):
    """Construit une obs flop pour les tests."""
    if all_committed is None:
        all_committed = [my_committed] * num_players
    if legal is None:
        legal = [Action.FOLD, Action.CHECK_CALL,
                 Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN]
    return Observation(
        player_id=player_id,
        hole_cards=hole,
        community_cards=board,
        pot=pot,
        my_committed=my_committed,
        my_stack=100 - my_committed,
        all_committed=all_committed,
        all_stacks=[100 - c for c in all_committed],
        stage=Stage.FLOP,
        legal_actions=legal,
        num_players=num_players,
        dealer_id=dealer_id,
        small_blind=1,
        big_blind=2,
        player_statuses=[PlayerStatus.ALIVE] * num_players,
    )


def test_cbet_returns_none_if_to_call_positive():
    """Si quelqu'un a déjà bet sur le flop, on n'est plus dans un c-bet pur."""
    obs = _make_flop_obs(["HA", "DA"], ["HK", "D7", "S2"],
                          all_committed=[4, 10])  # opp bet 6
    rng = random.Random(42)
    assert cbet_flop_pfa(obs, rng) is None


def test_cbet_returns_none_no_legal_half_pot():
    """Si RAISE_HALF_POT pas légal (rare postflop) → None."""
    obs = _make_flop_obs(["HA", "DA"], ["HK", "D7", "S2"],
                          legal=[Action.FOLD, Action.CHECK_CALL, Action.ALL_IN])
    rng = random.Random(42)
    assert cbet_flop_pfa(obs, rng) is None


def test_cbet_dry_strong_hand_bets():
    """AA sur K72 rainbow (DRY, overpair) → c-bet quasi pur."""
    obs = _make_flop_obs(["HA", "DA"], ["HK", "D7", "S2"])
    rng = random.Random(42)
    strat = cbet_flop_pfa(obs, rng, mc_simulations=300)
    assert strat is not None
    actions = dict(strat)
    bet_freq = actions.get(Action.RAISE_HALF_POT, 0) + actions.get(Action.RAISE_POT, 0)
    assert bet_freq > 0.7   # forte fréquence de bet


def test_cbet_wet_weak_hand_checks_mostly():
    """22 sur T98 two-tone (WET, sous-paire vs straight+flush draws) → check majoritaire."""
    obs = _make_flop_obs(["H2", "D2"], ["HT", "S9", "H8"])
    rng = random.Random(42)
    strat = cbet_flop_pfa(obs, rng, mc_simulations=300)
    assert strat is not None
    actions = dict(strat)
    # WET + low equity → check 100% selon nos règles
    assert actions.get(Action.CHECK_CALL, 0) > 0.5


def test_cbet_dry_air_minimal_bluff():
    """7c2s sur AKQ rainbow (DRY, total air) → bluff très rare (~15%) car
    Heuristic defense est trop wide pour bluff profitable."""
    obs = _make_flop_obs(["C7", "S2"], ["HA", "DK", "CQ"])
    rng = random.Random(42)
    strat = cbet_flop_pfa(obs, rng, mc_simulations=300)
    assert strat is not None
    actions = dict(strat)
    bet_freq = sum(f for a, f in actions.items()
                   if a in (Action.RAISE_HALF_POT, Action.RAISE_POT))
    # v0.2 : bluff freq ≤ 20%
    assert bet_freq <= 0.25


# ============ TURN/RIVER hors scope ============

def test_pro_postflop_returns_none_on_turn():
    """Turn/River pas couvert en X2 v0.1 → fallback."""
    obs = _make_flop_obs(["HA", "DA"], ["HK", "D7", "S2", "C4"])
    obs.stage = Stage.TURN
    rng = random.Random(42)
    assert pro_postflop_strategy(obs, was_pfa=True, rng=rng) is None


def test_pro_postflop_returns_none_if_not_pfa():
    """Si on n'était pas PFA, pas de c-bet rules (defense vs c-bet hors X2 v0.1)."""
    obs = _make_flop_obs(["HA", "DA"], ["HK", "D7", "S2"])
    rng = random.Random(42)
    assert pro_postflop_strategy(obs, was_pfa=False, rng=rng) is None


def test_pro_postflop_pfa_flop_returns_strategy():
    """Cas nominal : PFA + flop → strategy non-None."""
    obs = _make_flop_obs(["HA", "DA"], ["HK", "D7", "S2"])
    rng = random.Random(42)
    strat = pro_postflop_strategy(obs, was_pfa=True, rng=rng)
    assert strat is not None
    assert sum(f for _, f in strat) > 0.99
