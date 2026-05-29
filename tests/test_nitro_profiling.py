"""Unit tests for poky.nitro.profiling."""
import pytest

from poky.engine import Action
from poky.nitro.profiling import (
    ARCHETYPE_LAG, ARCHETYPE_LIMPER, ARCHETYPE_MANIAC, ARCHETYPE_NIT,
    ARCHETYPE_STATION, ARCHETYPE_TAG, ARCHETYPE_UNKNOWN,
    OpponentProfile, SHOWDOWN_HISTORY_CAP, classify_archetype,
    mark_seen, record_showdown, update_profile,
)


# ---- OpponentProfile basics --------------------------------------------

def test_empty_profile_stats_are_zero():
    p = OpponentProfile(opp_id="x")
    assert p.vpip == 0.0
    assert p.pfr == 0.0
    assert p.limp_freq == 0.0
    assert p.push_short_freq == 0.0
    assert p.fold_to_aggr_freq == 0.0


def test_stats_compute_correctly_from_counters():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=10,
        n_vpip=4,
        n_pfr=3,
        n_limp=1,
        n_face_aggression=4,
        n_call_aggression=1,
        n_fold_aggression=3,
        n_opportunities_short=2,
        n_push_short=1,
    )
    assert p.vpip == 0.4
    assert p.pfr == 0.3
    assert p.limp_freq == 0.1
    assert p.fold_to_aggr_freq == 0.75
    assert p.call_to_aggr_freq == 0.25
    assert p.push_short_freq == 0.5


def test_to_dict_from_dict_roundtrip():
    p = OpponentProfile(
        opp_id="Pierre42",
        n_voluntary_actions=5,
        n_vpip=2,
        showdown_hands=[0, 5, 12],
        last_seen="2026-05-29T12:00:00+00:00",
    )
    d = p.to_dict()
    rt = OpponentProfile.from_dict(d)
    assert rt.opp_id == "Pierre42"
    assert rt.n_vpip == 2
    assert rt.showdown_hands == [0, 5, 12]
    assert rt.last_seen == "2026-05-29T12:00:00+00:00"


# ---- update_profile ---------------------------------------------------

def test_blind_post_does_not_count():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.CHECK_CALL,
                   prior_aggression=False, stack_bb=15, is_blind_post=True)
    assert p.n_voluntary_actions == 0
    assert p.n_vpip == 0


def test_postflop_actions_ignored():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=False, action=Action.RAISE_POT,
                   prior_aggression=True, stack_bb=10)
    assert p.n_voluntary_actions == 0


def test_preflop_fold_no_aggression_counts_voluntary_only():
    """Folding when you could have limped/raised — counts as voluntary action."""
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.FOLD,
                   prior_aggression=False, stack_bb=15)
    assert p.n_voluntary_actions == 1
    assert p.n_vpip == 0


def test_preflop_fold_to_aggression_counts_face_and_fold():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.FOLD,
                   prior_aggression=True, stack_bb=15)
    assert p.n_voluntary_actions == 1
    assert p.n_face_aggression == 1
    assert p.n_fold_aggression == 1
    assert p.fold_to_aggr_freq == 1.0


def test_open_limp_counts_vpip_and_limp():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.CHECK_CALL,
                   prior_aggression=False, stack_bb=15)
    assert p.n_vpip == 1
    assert p.n_limp == 1
    assert p.n_face_aggression == 0


def test_call_after_raise_counts_vpip_and_call_aggression():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.CHECK_CALL,
                   prior_aggression=True, stack_bb=15)
    assert p.n_vpip == 1
    assert p.n_face_aggression == 1
    assert p.n_call_aggression == 1
    assert p.n_limp == 0


def test_open_raise_counts_vpip_pfr_no_face():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.RAISE_POT,
                   prior_aggression=False, stack_bb=15)
    assert p.n_vpip == 1
    assert p.n_pfr == 1
    assert p.n_face_aggression == 0


def test_reraise_counts_face_aggression_and_reraise():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.ALL_IN,
                   prior_aggression=True, stack_bb=15)
    assert p.n_pfr == 1
    assert p.n_face_aggression == 1
    assert p.n_reraise == 1


def test_short_stack_push_increments_push_short():
    p = OpponentProfile(opp_id="x")
    # Stack = 10bb -> short, push
    update_profile(p, is_preflop=True, action=Action.ALL_IN,
                   prior_aggression=False, stack_bb=10)
    assert p.n_opportunities_short == 1
    assert p.n_push_short == 1
    assert p.push_short_freq == 1.0


def test_short_stack_fold_increments_opportunity_only():
    p = OpponentProfile(opp_id="x")
    update_profile(p, is_preflop=True, action=Action.FOLD,
                   prior_aggression=True, stack_bb=10)
    assert p.n_opportunities_short == 1
    assert p.n_push_short == 0


# ---- record_showdown --------------------------------------------------

def test_record_showdown_appends_and_caps():
    p = OpponentProfile(opp_id="x")
    for i in range(SHOWDOWN_HISTORY_CAP + 5):
        record_showdown(p, hand_class_id=i % 169)
    assert len(p.showdown_hands) == SHOWDOWN_HISTORY_CAP
    assert p.n_showdowns == SHOWDOWN_HISTORY_CAP + 5
    # Should keep MOST RECENT entries
    assert p.showdown_hands[-1] == (SHOWDOWN_HISTORY_CAP + 4) % 169


# ---- classify_archetype -----------------------------------------------

def test_classify_unknown_when_insufficient_data():
    p = OpponentProfile(opp_id="x", n_voluntary_actions=2, n_vpip=1)
    assert classify_archetype(p) == ARCHETYPE_UNKNOWN


def test_classify_maniac_after_3_short_pushes():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=3,
        n_vpip=3,
        n_pfr=3,
        n_opportunities_short=3,
        n_push_short=3,
    )
    assert classify_archetype(p) == ARCHETYPE_MANIAC


def test_classify_nit_via_low_vpip():
    """5+ voluntary actions, vpip < 15% (strict threshold)."""
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=10,
        n_vpip=1,         # 10%
        n_pfr=1,
    )
    assert classify_archetype(p) == ARCHETYPE_NIT


def test_classify_nit_via_high_fold_to_aggression():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=10,
        n_vpip=3,         # vpip 30%, not super tight
        n_pfr=1,
        n_face_aggression=5,
        n_fold_aggression=5,  # folds 100% to aggression
    )
    assert classify_archetype(p) == ARCHETYPE_NIT


def test_classify_station_via_low_fold_to_aggression():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=10,
        n_vpip=6,
        n_face_aggression=8,
        n_fold_aggression=1,  # folds 12.5% -> calls way too much
        n_call_aggression=7,
    )
    assert classify_archetype(p) == ARCHETYPE_STATION


def test_classify_limper():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=10,
        n_vpip=5,
        n_pfr=1,
        n_limp=4,         # 40% limp freq
    )
    assert classify_archetype(p) == ARCHETYPE_LIMPER


def test_classify_lag():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=12,
        n_vpip=6,         # 50%
        n_pfr=4,          # 33%
        n_limp=2,
    )
    assert classify_archetype(p) == ARCHETYPE_LAG


def test_classify_tag():
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=12,
        n_vpip=3,         # 25%
        n_pfr=2,          # 17%
    )
    assert classify_archetype(p) == ARCHETYPE_TAG


def test_classify_maniac_via_high_pfr_no_stack_tracking():
    """No stack info available; classification falls back on PFR signal."""
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=5,
        n_vpip=5,
        n_pfr=4,           # 80% pfr
    )
    assert classify_archetype(p) == ARCHETYPE_MANIAC


def test_classify_priority_maniac_over_other():
    """If both MANIAC and NIT triggers fire, MANIAC wins (more actionable)."""
    p = OpponentProfile(
        opp_id="x",
        n_voluntary_actions=10,
        n_vpip=2,
        n_pfr=2,
        n_opportunities_short=4,
        n_push_short=3,
    )
    assert classify_archetype(p) == ARCHETYPE_MANIAC
