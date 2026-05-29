"""Unit tests for poky.solver.cache_db."""
import pytest

from poky.solver.cache_db import CacheDB
from poky.solver.spot_schema import SpotKey, SpotSolution


def make_solution(pot=6) -> SpotSolution:
    key = SpotKey(
        street="flop",
        board=("Ah", "Kh", "7d"),
        pot_chips=pot,
        effective_stack=97,
        ip_range="AKs,KQs",
        oop_range="QQ,JTs",
    )
    return SpotSolution(
        spot_key=key,
        player_at_root=1,
        root_actions=["CHECK", "BET 3.0"],
        root_strategy={"AhKh": [0.1, 0.9]},
        aggregated_strategy=[("CHECK", 0.1), ("BET 3.0", 0.9)],
        iterations=80,
        exploitability=0.5,
        solved_at="2026-05-29T11:00:00+00:00",
        elapsed_sec=17.0,
        solver_version="TexasSolver-v0.2.0",
    )


def test_put_and_get_roundtrip(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    sol = make_solution()
    assert not db.exists(sol.spot_key)
    db.put(sol)
    assert db.exists(sol.spot_key)
    got = db.get(sol.spot_key)
    assert got is not None
    assert got.spot_key.hash_key() == sol.spot_key.hash_key()
    assert got.root_actions == sol.root_actions
    assert got.aggregated_strategy == sol.aggregated_strategy
    assert got.iterations == 80
    db.close()


def test_get_missing_returns_none(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    missing = SpotKey(
        street="flop",
        board=("2c", "3d", "4h"),
        pot_chips=10,
        effective_stack=100,
        ip_range="AA",
        oop_range="KK",
    )
    assert db.get(missing) is None
    assert not db.exists(missing)
    db.close()


def test_put_is_upsert(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    sol = make_solution()
    db.put(sol)
    # Re-put with different iterations — should overwrite, not error.
    sol.iterations = 999
    db.put(sol)
    got = db.get(sol.spot_key)
    assert got.iterations == 999
    db.close()


def test_stats_increments_with_inserts(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    assert db.stats()["n_solutions"] == 0
    db.put(make_solution(pot=6))
    db.put(make_solution(pot=7))
    db.put(make_solution(pot=8))
    s = db.stats()
    assert s["n_solutions"] == 3
    assert s["avg_iterations"] == 80
    db.close()


def test_iter_keys_yields_all(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    pots = [6, 8, 10]
    for p in pots:
        db.put(make_solution(pot=p))
    keys = list(db.iter_keys())
    assert sorted(k.pot_chips for k in keys) == pots
    db.close()


def test_context_manager_closes(tmp_path):
    path = tmp_path / "cache.sqlite"
    with CacheDB(path) as db:
        db.put(make_solution())
    # Re-open and verify persistence.
    with CacheDB(path) as db2:
        assert db2.stats()["n_solutions"] == 1
