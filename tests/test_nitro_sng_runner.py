"""Unit tests for poky.nitro.sng_runner — SnG arena."""
import pytest

from poky.nitro.sng_runner import (
    BlindLevel, DEFAULT_NITRO_SCHEDULE, SnGResult, SnGRunner,
)
from poky.players.heuristic import HeuristicPlayer
from poky.players.nitro_player import NitroPlayer
from poky.players.random_player import RandomPlayer


def test_blinds_schedule_escalates():
    runner = SnGRunner(hands_per_level=4)
    b0 = runner._blinds_at(0)
    b3 = runner._blinds_at(3)
    b4 = runner._blinds_at(4)
    assert (b0.sb, b0.bb) == (b3.sb, b3.bb)        # same level
    assert b4.bb > b0.bb                            # next level


def test_blinds_clamp_to_max_level():
    runner = SnGRunner(hands_per_level=1,
                       blind_schedule=[BlindLevel(1, 2), BlindLevel(5, 10)])
    assert runner._blinds_at(0).bb == 2
    assert runner._blinds_at(1).bb == 10
    # Past last level, clamps to last
    assert runner._blinds_at(100).bb == 10


def test_sng_plays_to_completion_with_random():
    """3 random players SnG runs to completion (1 winner + 2 eliminated)."""
    runner = SnGRunner(starting_chips=300, max_hands=50,
                       hands_per_level=2)
    players = [RandomPlayer(seed=1), RandomPlayer(seed=2), RandomPlayer(seed=3)]
    result = runner.play(players, seed=42)

    assert isinstance(result, SnGResult)
    assert len(result.finish_order) == 3
    assert set(result.finish_order) == {0, 1, 2}
    assert result.hands_played > 0
    # At least 2 players should be busted (one wins).
    busted = sum(1 for s in result.final_stacks if s <= 0)
    assert busted >= 2 or result.hands_played >= runner.max_hands


def test_sng_payouts_assigned_correctly():
    """The 1st place finisher gets payouts[0], etc."""
    payouts = [80, 12, 8]
    runner = SnGRunner(starting_chips=300, max_hands=30,
                       payouts=payouts, hands_per_level=2)
    players = [RandomPlayer(seed=7), RandomPlayer(seed=8), RandomPlayer(seed=9)]
    result = runner.play(players, seed=42)
    # Each seat's payout = payouts[finish_position]
    for pos, seat in enumerate(result.finish_order):
        assert result.payouts[seat] == payouts[pos]


def test_winner_take_all_payout_sum():
    """In WTA mode, all payout goes to 1st place."""
    runner = SnGRunner(starting_chips=300, max_hands=30,
                       payouts=[100, 0, 0], hands_per_level=2)
    players = [RandomPlayer(seed=1), RandomPlayer(seed=2), RandomPlayer(seed=3)]
    result = runner.play(players, seed=42)
    assert sum(result.payouts) == 100
    winner_seat = result.finish_order[0]
    assert result.payouts[winner_seat] == 100


def test_sng_with_nitro_player():
    """End-to-end: NitroPlayer plays a SnG with HeuristicPlayer opponents."""
    runner = SnGRunner(starting_chips=300, max_hands=50,
                       payouts=[100, 0, 0], hands_per_level=4)
    nitro = NitroPlayer(seed=42)
    h1 = HeuristicPlayer(seed=11)
    h2 = HeuristicPlayer(seed=22)
    result = runner.play([nitro, h1, h2], seed=42)
    assert isinstance(result, SnGResult)
    assert result.hands_played > 0
    # Either Nitro wins or finishes somewhere.
    assert nitro.coverage_stats()["preflop_total"] > 0
