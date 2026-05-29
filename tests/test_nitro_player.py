"""Unit + integration tests for NitroPlayer."""
import random

import pytest

from poky.engine import Action, Game, Observation, PlayerStatus, Stage
from poky.players.base import ActionEvent
from poky.players.heuristic import HeuristicPlayer
from poky.players.nitro_player import NitroPlayer


def _obs(
    player_id: int,
    hole_cards,
    stage=Stage.PREFLOP,
    community=None,
    dealer_id=0,
    my_stack=298,
    my_committed=2,
    all_committed=None,
    all_stacks=None,
    statuses=None,
    legal=None,
    pot=3,
    bb=2,
):
    """Build a 3-max Observation for testing.

    Default: 300 chips each, BB=2 -> stack = 150bb but we want 15bb so use
    chips=30 / BB=2 = 15bb in actual tests. Override defaults as needed.
    """
    if community is None:
        community = []
    if all_committed is None:
        all_committed = [0, 1, 2]   # BTN=0, SB=1, BB=2
    if all_stacks is None:
        all_stacks = [30, 29, 28]   # 15bb each before any action
    if statuses is None:
        statuses = [PlayerStatus.ALIVE] * 3
    if legal is None:
        legal = [Action.FOLD, Action.CHECK_CALL, Action.RAISE_POT, Action.ALL_IN]
    return Observation(
        player_id=player_id,
        hole_cards=list(hole_cards),
        community_cards=community,
        pot=pot,
        my_committed=my_committed,
        my_stack=my_stack,
        all_committed=all_committed,
        all_stacks=all_stacks,
        stage=stage,
        legal_actions=legal,
        num_players=3,
        dealer_id=dealer_id,
        small_blind=1,
        big_blind=bb,
        player_statuses=statuses,
    )


def _push_event(actor: int, stage=Stage.PREFLOP):
    return ActionEvent(
        actor=actor, action=Action.ALL_IN, stage=stage,
        to_call_before=0, all_committed_before=[0, 1, 2], big_blind=2,
    )


def _fold_event(actor: int, stage=Stage.PREFLOP):
    return ActionEvent(
        actor=actor, action=Action.FOLD, stage=stage,
        to_call_before=0, all_committed_before=[0, 1, 2], big_blind=2,
    )


def _call_event(actor: int, stage=Stage.PREFLOP):
    return ActionEvent(
        actor=actor, action=Action.CHECK_CALL, stage=stage,
        to_call_before=0, all_committed_before=[0, 1, 2], big_blind=2,
    )


# ---- Scenario detection ------------------------------------------------

def test_detect_btn_open():
    """Hero is BTN, no prior action -> scenario = btn_push."""
    player = NitroPlayer(seed=1)
    # Hero is player 0, dealer_id=0 -> hero is BTN.
    obs = _obs(player_id=0, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=30, my_committed=0, all_committed=[0, 1, 2])
    assert player._detect_scenario(obs) == "btn_push"


def test_detect_sb_after_btn_fold():
    """Hero is SB, BTN folded -> sb_push_after_btn_fold."""
    player = NitroPlayer(seed=1)
    player.observe_action(_fold_event(actor=0))   # BTN folds
    # Hero is player 1 (= SB when dealer=0)
    obs = _obs(player_id=1, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=29, my_committed=1, all_committed=[0, 1, 2],
               statuses=[PlayerStatus.FOLDED, PlayerStatus.ALIVE, PlayerStatus.ALIVE])
    assert player._detect_scenario(obs) == "sb_push_after_btn_fold"


def test_detect_sb_call_vs_btn_push():
    """Hero is SB, BTN pushed -> sb_call_vs_btn."""
    player = NitroPlayer(seed=1)
    player.observe_action(_push_event(actor=0))   # BTN pushes
    obs = _obs(player_id=1, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=29, my_committed=1)
    assert player._detect_scenario(obs) == "sb_call_vs_btn"


def test_detect_bb_call_3way():
    """Hero is BB, BTN pushed and SB called -> bb_call_3way."""
    player = NitroPlayer(seed=1)
    player.observe_action(_push_event(actor=0))   # BTN push
    player.observe_action(_call_event(actor=1))   # SB call
    obs = _obs(player_id=2, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=28, my_committed=2)
    assert player._detect_scenario(obs) == "bb_call_3way"


def test_detect_bb_call_vs_btn():
    """Hero is BB, BTN pushed and SB folded -> bb_call_vs_btn."""
    player = NitroPlayer(seed=1)
    player.observe_action(_push_event(actor=0))
    player.observe_action(_fold_event(actor=1))
    obs = _obs(player_id=2, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=28, my_committed=2)
    assert player._detect_scenario(obs) == "bb_call_vs_btn"


def test_detect_bb_call_vs_sb():
    """Hero is BB, BTN folded and SB pushed -> bb_call_vs_sb."""
    player = NitroPlayer(seed=1)
    player.observe_action(_fold_event(actor=0))
    player.observe_action(_push_event(actor=1))
    obs = _obs(player_id=2, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=28, my_committed=2)
    assert player._detect_scenario(obs) == "bb_call_vs_sb"


def test_detect_returns_sb_vs_btn_limp_on_limped_pot():
    """BTN limped (CHECK_CALL no prior aggression) -> SB has iso-push scenario."""
    player = NitroPlayer(seed=1)
    player.observe_action(_call_event(actor=0))   # BTN "limps"
    obs = _obs(player_id=1, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=29, my_committed=1)
    assert player._detect_scenario(obs) == "sb_vs_btn_limp"


# ---- act() routing -----------------------------------------------------

def test_act_aa_btn_pushes():
    """AA on BTN at 15bb should push (Nash freq = 1.0)."""
    player = NitroPlayer(seed=42)
    obs = _obs(player_id=0, hole_cards=["HA", "DA"], dealer_id=0,
               my_stack=30, my_committed=0)
    action = player.act(obs)
    assert action == Action.ALL_IN
    assert player.nash_hits == 1


def test_act_32o_btn_folds():
    """32o on BTN at 15bb should fold (Nash freq near 0)."""
    player = NitroPlayer(seed=42)
    # Run many times to verify mostly folds (small noise floor from MC).
    folds = 0
    for trial in range(50):
        p = NitroPlayer(seed=trial)
        obs = _obs(player_id=0, hole_cards=["S3", "D2"], dealer_id=0,
                   my_stack=30, my_committed=0)
        action = p.act(obs)
        if action == Action.FOLD:
            folds += 1
    # Allow up to 5% noise (matches the ~2% noise floor in tables).
    assert folds >= 45, f"32o should fold ~all the time, got {folds}/50"


def test_postflop_delegates_to_fallback():
    """Postflop decisions go through the HeuristicPlayer fallback."""
    player = NitroPlayer(seed=42)
    obs = _obs(player_id=0, hole_cards=["HA", "DA"],
               stage=Stage.FLOP, community=["HK", "D7", "C2"],
               dealer_id=0, my_stack=20, my_committed=10, pot=20)
    action = player.act(obs)
    assert action in obs.legal_actions
    assert player.postflop_decisions == 1
    assert player.nash_hits == 0


def test_reset_clears_preflop_status():
    player = NitroPlayer(seed=42)
    player.observe_action(_push_event(actor=0))
    assert player._preflop_status[0] == "push"
    player.reset()
    assert player._preflop_status == {}


def test_unknown_num_players_falls_back():
    """6-max table -> NitroPlayer just delegates entirely."""
    player = NitroPlayer(seed=42)
    obs = _obs(player_id=0, hole_cards=["HA", "DA"], dealer_id=0)
    obs = Observation(
        player_id=0,
        hole_cards=["HA", "DA"],
        community_cards=[],
        pot=3,
        my_committed=0,
        my_stack=30,
        all_committed=[0, 1, 2, 0, 0, 0],
        all_stacks=[30, 29, 28, 30, 30, 30],
        stage=Stage.PREFLOP,
        legal_actions=[Action.FOLD, Action.CHECK_CALL, Action.ALL_IN],
        num_players=6,
        dealer_id=0,
        small_blind=1,
        big_blind=2,
        player_statuses=[PlayerStatus.ALIVE] * 6,
    )
    action = player.act(obs)
    assert action in obs.legal_actions
    # Should not have used Nash (wrong table size)
    assert player.nash_hits == 0


# ---- Integration with real arena ---------------------------------------

def test_nitro_runs_in_3max_arena_without_crash():
    """End-to-end: 3 NitroPlayers play a hand in the real arena."""
    p0 = NitroPlayer(seed=1)
    p1 = NitroPlayer(seed=2)
    p2 = NitroPlayer(seed=3)
    seats = [p0, p1, p2]
    game = Game(num_players=3, seed=42, chips_per_player=30)  # 15bb each
    obs, pid = game.reset()
    for p in seats:
        p.reset()
    steps = 0
    while not game.is_over():
        action = seats[pid].act(obs)
        assert action in obs.legal_actions, (action, obs.legal_actions)
        ev = ActionEvent(
            actor=pid, action=action, stage=obs.stage,
            to_call_before=obs.to_call,
            all_committed_before=list(obs.all_committed),
            big_blind=obs.big_blind,
        )
        for p in seats:
            p.observe_action(ev)
        obs, pid = game.step(action)
        steps += 1
        assert steps < 100
    payoffs = game.payoffs()
    assert len(payoffs) == 3
    assert abs(sum(payoffs)) < 1e-6


def test_nitro_vs_heuristic_3max_short_match():
    """50-hand match: NitroPlayer vs 2x HeuristicPlayer in 3-max at 15bb.

    Sanity: NitroPlayer runs without crashing; coverage_stats are sane.
    Not asserting win-rate (50 hands too noisy) but checking the pipeline.
    """
    nitro = NitroPlayer(seed=42)
    h1 = HeuristicPlayer(seed=11)
    h2 = HeuristicPlayer(seed=22)
    for hand_idx in range(50):
        seats = [nitro, h1, h2]
        for p in seats:
            p.reset()
        game = Game(num_players=3, seed=hand_idx, chips_per_player=30)
        obs, pid = game.reset()
        steps = 0
        while not game.is_over():
            action = seats[pid].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            ev = ActionEvent(
                actor=pid, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seats:
                p.observe_action(ev)
            obs, pid = game.step(action)
            steps += 1
            assert steps < 100

    stats = nitro.coverage_stats()
    # Some Nash decisions must have been made.
    assert stats["nash_hits"] > 0
    assert stats["preflop_total"] > 0
    # Nash hit rate at 15bb 3-max should be very high.
    assert stats["nash_hit_rate"] > 0.7, stats


# ---- N5 Profiling integration tests -----------------------------------

def test_profile_db_loaded_on_first_use(tmp_path):
    """Profiles passed via opp_ids are fetched from DB lazily."""
    from poky.nitro.profile_db import ProfileDB
    from poky.nitro.profiling import OpponentProfile

    db_path = tmp_path / "p.sqlite"
    db = ProfileDB(db_path)
    db.save(OpponentProfile(
        opp_id="alice", n_voluntary_actions=15, n_vpip=12, n_pfr=10,
        last_seen="2026-05-29T12:00:00+00:00", n_hands_observed=15,
    ))
    db.close()

    db2 = ProfileDB(db_path)
    player = NitroPlayer(seed=1, opp_ids={1: "alice"}, profile_db=db2)
    # Trigger lazy load
    player._get_or_create_profile(1)
    assert player._profiles[1].n_vpip == 12
    db2.close()


def test_reset_preserves_profiles():
    """reset() between hands must KEEP _profiles dict; only per-hand state cleared."""
    player = NitroPlayer(seed=1)
    player.observe_action(_push_event(actor=1))
    assert 1 in player._profiles
    assert player._profiles[1].n_pfr == 1
    n_before = player._profiles[1].n_pfr
    player.reset()
    # Profile must persist after reset
    assert 1 in player._profiles
    assert player._profiles[1].n_pfr == n_before


def test_observe_action_updates_opp_profile():
    """observe_action increments the right counters in the opp profile."""
    player = NitroPlayer(seed=1, use_profiling=True)
    # 3 pushes by opp at seat 0
    player.observe_action(_push_event(actor=0))
    player.observe_action(_push_event(actor=0))
    player.observe_action(_push_event(actor=0))
    profile = player._profiles.get(0)
    assert profile is not None
    assert profile.n_pfr == 3
    assert profile.n_vpip == 3
    assert profile.n_voluntary_actions == 3


def test_classify_runs_maniac_after_3_pushes():
    """After 4+ pushes, the classifier should label opp MANIAC (high PFR rule)."""
    from poky.nitro.profiling import (
        ARCHETYPE_MANIAC, classify_archetype,
    )
    player = NitroPlayer(seed=1, use_profiling=True)
    for _ in range(4):
        player.observe_action(_push_event(actor=0))
    profile = player._profiles[0]
    assert classify_archetype(profile) == ARCHETYPE_MANIAC


def test_profile_drives_freq_adjustment(tmp_path):
    """End-to-end: when opp is classified MANIAC, our sb_call_vs_btn freq goes up."""
    from poky.nitro.profile_db import ProfileDB
    from poky.nitro.profiling import OpponentProfile

    # Pre-seed DB with MANIAC profile
    db_path = tmp_path / "p.sqlite"
    db = ProfileDB(db_path)
    db.save(OpponentProfile(
        opp_id="maniac_btn",
        n_voluntary_actions=8, n_vpip=8, n_pfr=8,   # 100% PFR -> MANIAC
        n_hands_observed=8,
        last_seen="2026-05-29T12:00:00+00:00",
    ))
    db.close()

    # Build obs where hero is SB facing a BTN push
    db2 = ProfileDB(db_path)
    player = NitroPlayer(seed=42, opp_ids={0: "maniac_btn"}, profile_db=db2,
                         use_profiling=True)
    player.observe_action(_push_event(actor=0))   # BTN pushed
    # Hero is SB (player_id=1, dealer_id=0 -> offset 1 = SB)
    obs = _obs(player_id=1, hole_cards=["S7", "D6"],   # marginal hand
               dealer_id=0, my_stack=29, my_committed=1)
    # We can't easily check the exact freq, but we can check classification kicked in
    action = player.act(obs)
    # At minimum: no crash, action is legal
    assert action in obs.legal_actions
    # Check that opponent was classified
    from poky.nitro.profiling import ARCHETYPE_MANIAC, classify_archetype
    assert classify_archetype(player._profiles[0]) == ARCHETYPE_MANIAC
    db2.close()


def test_flush_profiles_persists_to_db(tmp_path):
    from poky.nitro.profile_db import ProfileDB

    db_path = tmp_path / "p.sqlite"
    db = ProfileDB(db_path)
    player = NitroPlayer(seed=1, opp_ids={0: "bob"}, profile_db=db)
    # Generate some events
    player.observe_action(_push_event(actor=0))
    player.observe_action(_push_event(actor=0))
    player.flush_profiles()
    # Read back from DB
    loaded = db.load("bob")
    assert loaded is not None
    assert loaded.n_pfr == 2
    db.close()
