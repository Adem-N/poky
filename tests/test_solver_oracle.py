"""Unit + integration tests for SolverOraclePlayer + observation_to_spot."""
from __future__ import annotations

import random

import pytest

from poky.engine import Action, Game, Observation, PlayerStatus, Stage
from poky.players.solver_oracle import SolverOraclePlayer
from poky.solver.cache_db import CacheDB
from poky.solver.observation_to_spot import (
    card_rlcard_to_solver,
    observation_to_spot_key,
    translate_solver_action,
)
from poky.solver.spot_schema import SpotKey, SpotSolution


# ----- Card / SpotKey conversion ----------------------------------------

def test_card_conversion_swaps_and_lowercases():
    assert card_rlcard_to_solver("HQ") == "Qh"
    assert card_rlcard_to_solver("D4") == "4d"
    assert card_rlcard_to_solver("CT") == "Tc"
    assert card_rlcard_to_solver("SA") == "As"


def test_card_conversion_rejects_bad_format():
    with pytest.raises(ValueError):
        card_rlcard_to_solver("H")
    with pytest.raises(ValueError):
        card_rlcard_to_solver("XQ")


def _hu_obs(stage, community, **overrides):
    base = dict(
        player_id=1,                              # hero
        hole_cards=["HA", "HK"],
        community_cards=community,
        pot=6,
        my_committed=2,
        my_stack=97,
        all_committed=[2, 2],
        all_stacks=[98, 97],
        stage=stage,
        legal_actions=[Action.FOLD, Action.CHECK_CALL, Action.RAISE_HALF_POT,
                       Action.RAISE_POT, Action.ALL_IN],
        num_players=2,
        dealer_id=0,                              # rlcard HU quirk: dealer=BB
        small_blind=1,
        big_blind=2,
        player_statuses=[PlayerStatus.ALIVE, PlayerStatus.ALIVE],
    )
    base.update(overrides)
    return Observation(**base)


def test_spot_key_returns_none_for_preflop():
    obs = _hu_obs(Stage.PREFLOP, [])
    assert observation_to_spot_key(obs, is_pfa=True) is None


def test_spot_key_returns_none_for_wrong_player_count():
    obs = _hu_obs(Stage.FLOP, ["HA", "HK", "D7"], num_players=3,
                  all_committed=[2, 2, 2], all_stacks=[98, 98, 97],
                  player_statuses=[PlayerStatus.ALIVE] * 3)
    assert observation_to_spot_key(obs, is_pfa=True) is None


def test_spot_key_built_from_flop_obs():
    obs = _hu_obs(Stage.FLOP, ["HA", "HK", "D7"])
    key = observation_to_spot_key(obs, is_pfa=True)
    assert key is not None
    assert key.street == "flop"
    assert key.board == ("Ah", "Kh", "7d")
    assert key.pot_chips == 6
    assert key.effective_stack == 97


def test_spot_key_built_from_turn_and_river():
    turn_obs = _hu_obs(Stage.TURN, ["HA", "HK", "D7", "C2"])
    turn_key = observation_to_spot_key(turn_obs, is_pfa=True)
    assert turn_key.street == "turn"
    assert turn_key.board == ("Ah", "Kh", "7d", "2c")

    river_obs = _hu_obs(Stage.RIVER, ["HA", "HK", "D7", "C2", "SJ"])
    river_key = observation_to_spot_key(river_obs, is_pfa=True)
    assert river_key.street == "river"
    assert river_key.board == ("Ah", "Kh", "7d", "2c", "Js")


# ----- Solver action translation ----------------------------------------

def test_translate_fold_check_call_allin():
    obs = _hu_obs(Stage.FLOP, ["HA", "HK", "D7"])
    assert translate_solver_action("FOLD", obs=obs) == Action.FOLD
    assert translate_solver_action("CHECK", obs=obs) == Action.CHECK_CALL
    assert translate_solver_action("CALL", obs=obs) == Action.CHECK_CALL
    assert translate_solver_action("ALLIN", obs=obs) == Action.ALL_IN


def test_translate_bet_sizing_buckets():
    obs = _hu_obs(Stage.FLOP, ["HA", "HK", "D7"])
    # pot=6, to_call=0, so additional ratio = chips / 6
    # < 0.33 pot (chips < 2) -> CHECK_CALL
    assert translate_solver_action("BET 1", obs=obs) == Action.CHECK_CALL
    # 0.33 pot ratio (chips=2) -> RAISE_HALF_POT
    assert translate_solver_action("BET 2", obs=obs) == Action.RAISE_HALF_POT
    # 0.66 pot (chips=4) -> RAISE_POT bucket
    assert translate_solver_action("BET 4", obs=obs) == Action.RAISE_POT
    # very large -> ALL_IN
    assert translate_solver_action("BET 95", obs=obs) == Action.ALL_IN


def test_translate_returns_none_for_illegal_action():
    obs = _hu_obs(Stage.FLOP, ["HA", "HK", "D7"],
                  legal_actions=[Action.FOLD, Action.CHECK_CALL])
    # ALL_IN not legal, fallback to RAISE_POT also not legal -> None
    assert translate_solver_action("ALLIN", obs=obs) is None


# ----- SolverOraclePlayer end-to-end ------------------------------------

def _seed_spot_in_cache(db: CacheDB, board=("Ah", "Kh", "7d"), pot=6, stack=97,
                        ip_range="BTN_defend", oop_range="BB_open"):
    """Insert a fake but parseable cached SpotSolution for the given board.

    Default ranges match what `observation_to_spot_key` produces for a hero
    at player_id=1 dealer_id=0 (BTN in rlcard HU convention) with
    is_pfa=False (no preflop raise recorded -> hero defends).
    """
    key = SpotKey(
        street="flop",
        board=board,
        pot_chips=pot,
        effective_stack=stack,
        ip_range=ip_range,
        oop_range=oop_range,
    )
    sol = SpotSolution(
        spot_key=key,
        player_at_root=1,
        root_actions=["CHECK", "BET 3.0"],
        root_strategy={"AhKh": [0.2, 0.8]},
        aggregated_strategy=[("CHECK", 0.2), ("BET 3.0", 0.8)],
        iterations=100,
        exploitability=1.0,
        solved_at="2026-05-29T12:00:00+00:00",
        elapsed_sec=20.0,
        solver_version="TexasSolver-v0.2.0",
    )
    db.put(sol)
    return key


def test_oracle_falls_back_on_cache_miss(tmp_path):
    db = CacheDB(tmp_path / "empty.sqlite")
    player = SolverOraclePlayer(cache=db, seed=42)
    obs = _hu_obs(Stage.FLOP, ["DA", "DK", "C7"])     # board NOT in cache
    action = player.act(obs)
    assert action in obs.legal_actions
    stats = player.coverage_stats()
    assert stats["postflop_cache_hits"] == 0
    assert stats["postflop_cache_misses"] == 1
    db.close()


def test_oracle_hits_cached_spot(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    # Seed using the defaults that match _hu_obs(player_id=1, dealer_id=0)
    # with is_pfa=False -> hero is IP (BTN) defending.
    _seed_spot_in_cache(db, board=("Ah", "Kh", "7d"), pot=6, stack=97)

    obs = _hu_obs(Stage.FLOP, ["HA", "HK", "D7"])     # dealer_id=0 default
    player = SolverOraclePlayer(cache=db, seed=42)
    action = player.act(obs)
    assert action in obs.legal_actions
    stats = player.coverage_stats()
    assert stats["postflop_cache_hits"] == 1
    assert stats["postflop_cache_misses"] == 0
    db.close()


def test_oracle_preflop_delegates_to_fallback(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    player = SolverOraclePlayer(cache=db, seed=42)
    obs = _hu_obs(Stage.PREFLOP, [],
                  legal_actions=[Action.FOLD, Action.CHECK_CALL,
                                 Action.RAISE_POT, Action.ALL_IN])
    action = player.act(obs)
    assert action in obs.legal_actions
    stats = player.coverage_stats()
    assert stats["preflop_decisions"] == 1
    assert stats["postflop_total"] == 0
    db.close()


def test_oracle_runs_inside_real_arena(tmp_path):
    """End-to-end: SolverOraclePlayer can run a full HU hand without crashing."""
    db = CacheDB(tmp_path / "cache.sqlite")
    p0 = SolverOraclePlayer(cache=db, seed=42)
    p1 = SolverOraclePlayer(cache=db, seed=43)
    game = Game(num_players=2, seed=7, chips_per_player=100)
    obs, pid = game.reset()
    p0.reset()
    p1.reset()
    steps = 0
    while not game.is_over():
        bot = p0 if pid == 0 else p1
        action = bot.act(obs)
        assert action in obs.legal_actions
        obs, pid = game.step(action)
        steps += 1
        assert steps < 200
    payoffs = game.payoffs()
    assert len(payoffs) == 2
    assert abs(sum(payoffs)) < 1e-6
    db.close()
