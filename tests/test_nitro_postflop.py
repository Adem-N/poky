"""Unit tests for poky.nitro.postflop SPR-based commit rules."""
import random

import pytest

from poky.engine import Action, PlayerStatus, Stage
from poky.engine.game import Observation
from poky.nitro.postflop import (
    _classify_hand, _classify_pair_strength, postflop_decision,
)


def _obs(stage=Stage.FLOP, hole=("HA", "HK"), community=("DA", "S7", "C2"),
         pot=20, my_stack=20, to_call=0, legal=None):
    """Build a test observation. `to_call` is set via all_committed so that
    max(all_committed) - my_committed == to_call."""
    if legal is None:
        legal = [Action.FOLD, Action.CHECK_CALL, Action.RAISE_POT, Action.ALL_IN]
    my_committed = 10
    other_committed = my_committed + to_call
    return Observation(
        player_id=0, hole_cards=list(hole), community_cards=list(community),
        pot=pot, my_committed=my_committed, my_stack=my_stack,
        all_committed=[my_committed, other_committed, 0],
        all_stacks=[my_stack, my_stack, 0],
        stage=stage, legal_actions=legal, num_players=3,
        dealer_id=0, small_blind=1, big_blind=2,
        player_statuses=[PlayerStatus.ALIVE] * 3,
    )


# ---- Hand classification ----------------------------------------------

def test_classify_set():
    """Hole AA on board A72: set of aces -> trips/set -> monster category."""
    cat = _classify_hand(["HA", "DA"], ["SA", "C7", "D2"])
    assert cat == "monster"


def test_classify_two_pair():
    """AK on A7K -> two pair."""
    cat = _classify_hand(["HA", "DK"], ["CA", "S7", "DK"])
    assert cat == "two_pair"


def test_classify_top_pair():
    """AQ on A72 -> top pair (aces)."""
    cat = _classify_hand(["HA", "DQ"], ["SA", "C7", "D2"])
    assert cat == "top_pair"


def test_classify_mid_pair():
    """A7 on K72 -> middle pair (sevens, board top = K)."""
    cat = _classify_hand(["HA", "D7"], ["SK", "C7", "H2"])
    assert cat == "mid_pair"


def test_classify_overpair_is_top_pair():
    """JJ on T82 -> overpair (better than top of board) -> top_pair category."""
    cat = _classify_hand(["HJ", "DJ"], ["ST", "C8", "D2"])
    assert cat == "top_pair"


def test_classify_under_pair():
    """66 on JT4 -> under pair to board -> mid_pair."""
    cat = _classify_hand(["H6", "D6"], ["SJ", "CT", "D4"])
    assert cat == "mid_pair"


def test_classify_high_card():
    """AK on T72 -> ace high -> high_card."""
    cat = _classify_hand(["HA", "DK"], ["ST", "C7", "D2"])
    assert cat == "high_card"


def test_classify_straight():
    """T9 on 8 7 6 -> straight."""
    cat = _classify_hand(["HT", "D9"], ["S8", "C7", "D6"])
    assert cat == "monster"


# ---- postflop_decision ------------------------------------------------

def test_decision_preflop_returns_none():
    """Preflop -> not our scope."""
    obs = _obs(stage=Stage.PREFLOP, community=[])
    assert postflop_decision(obs) is None


def test_decision_deep_spr_returns_none():
    """SPR > 5 -> let heuristic handle deep play."""
    obs = _obs(pot=4, my_stack=30)   # SPR 7.5
    assert postflop_decision(obs) is None


def test_monster_always_commits():
    """Set of aces on the flop -> push to commit regardless of SPR."""
    obs = _obs(hole=("HA", "DA"), community=("SA", "C7", "D2"),
               pot=20, my_stack=20)
    decision = postflop_decision(obs)
    assert decision in (Action.ALL_IN, Action.RAISE_POT,
                        Action.RAISE_HALF_POT, Action.CHECK_CALL)


def test_top_pair_low_spr_commits():
    """AQ on A72 with SPR 1.5 -> commit (top pair, threshold 3)."""
    obs = _obs(hole=("HA", "DQ"), community=("SA", "C7", "D2"),
               pot=20, my_stack=30)
    decision = postflop_decision(obs)
    assert decision in (Action.ALL_IN, Action.RAISE_POT,
                        Action.RAISE_HALF_POT, Action.CHECK_CALL)


def test_high_card_folds_to_bet():
    """T7 on K82 (high card) with bet to call -> fold."""
    obs = _obs(hole=("HT", "D7"), community=("SK", "C8", "D2"),
               pot=20, my_stack=20, to_call=10)
    decision = postflop_decision(obs)
    assert decision == Action.FOLD


def test_high_card_checks_when_free():
    """T7 on K82 high card, no bet to call -> check."""
    obs = _obs(hole=("HT", "D7"), community=("SK", "C8", "D2"),
               pot=20, my_stack=20, to_call=0)
    decision = postflop_decision(obs)
    assert decision == Action.CHECK_CALL


def test_two_pair_medium_spr_commits():
    """AK on AK7 with SPR 3 -> commit (two_pair threshold 4)."""
    obs = _obs(hole=("HA", "DK"), community=("CA", "DK", "S7"),
               pot=10, my_stack=30)
    decision = postflop_decision(obs)
    assert decision in (Action.ALL_IN, Action.RAISE_POT,
                        Action.RAISE_HALF_POT, Action.CHECK_CALL)


def test_mid_pair_high_spr_does_not_commit():
    """A7 on K72 (middle pair) with SPR 4 -> don't commit (threshold 1.5)."""
    obs = _obs(hole=("HA", "D7"), community=("SK", "C7", "H2"),
               pot=10, my_stack=40, to_call=20)
    decision = postflop_decision(obs)
    # Mid pair at SPR 4 facing bet -> fold (or check if no bet)
    assert decision == Action.FOLD
