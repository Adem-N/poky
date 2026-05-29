"""Unit tests for poky.nitro.profile_db — persistent OpponentProfile store."""
import pytest

from poky.nitro.profile_db import ProfileDB
from poky.nitro.profiling import OpponentProfile


def _make_profile(opp_id="alice", n_hands=10, vpip=3) -> OpponentProfile:
    return OpponentProfile(
        opp_id=opp_id,
        n_hands_observed=n_hands,
        n_voluntary_actions=10,
        n_vpip=vpip,
        n_pfr=2,
        n_limp=1,
        showdown_hands=[0, 5, 42],
        last_seen="2026-05-29T12:00:00+00:00",
    )


def test_save_and_load_roundtrip(tmp_path):
    db = ProfileDB(tmp_path / "profiles.sqlite")
    p = _make_profile("alice")
    assert db.load("alice") is None
    db.save(p)
    got = db.load("alice")
    assert got is not None
    assert got.opp_id == "alice"
    assert got.n_vpip == 3
    assert got.showdown_hands == [0, 5, 42]
    db.close()


def test_load_missing_returns_none(tmp_path):
    db = ProfileDB(tmp_path / "profiles.sqlite")
    assert db.load("unknown_user") is None
    db.close()


def test_save_is_upsert(tmp_path):
    db = ProfileDB(tmp_path / "profiles.sqlite")
    p = _make_profile("alice", n_hands=10, vpip=3)
    db.save(p)
    # Modify and re-save
    p.n_hands_observed = 50
    p.n_vpip = 15
    db.save(p)
    got = db.load("alice")
    assert got.n_hands_observed == 50
    assert got.n_vpip == 15
    db.close()


def test_multiple_profiles(tmp_path):
    db = ProfileDB(tmp_path / "profiles.sqlite")
    db.save(_make_profile("alice"))
    db.save(_make_profile("bob"))
    db.save(_make_profile("charlie"))
    ids = db.list_ids()
    assert set(ids) == {"alice", "bob", "charlie"}
    db.close()


def test_stats_reflects_inserts(tmp_path):
    db = ProfileDB(tmp_path / "profiles.sqlite")
    assert db.stats()["n_profiles"] == 0
    db.save(_make_profile("alice", n_hands=10))
    db.save(_make_profile("bob", n_hands=25))
    s = db.stats()
    assert s["n_profiles"] == 2
    assert s["total_hands"] == 35
    assert s["max_hands_per_opp"] == 25
    db.close()


def test_iter_profiles_yields_all(tmp_path):
    db = ProfileDB(tmp_path / "profiles.sqlite")
    db.save(_make_profile("alice"))
    db.save(_make_profile("bob"))
    profiles = list(db.iter_profiles())
    assert {p.opp_id for p in profiles} == {"alice", "bob"}
    db.close()


def test_persistence_across_db_reopen(tmp_path):
    path = tmp_path / "profiles.sqlite"
    with ProfileDB(path) as db:
        db.save(_make_profile("alice", n_hands=42))
    # Re-open
    with ProfileDB(path) as db2:
        got = db2.load("alice")
        assert got is not None
        assert got.n_hands_observed == 42
