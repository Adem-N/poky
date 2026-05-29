"""Unit tests for poky.nitro.ranges loader."""
import json

import pytest

from poky.nitro import ranges as ranges_mod
from poky.nitro.ranges import (
    available_stacks, closest_stack, get_strategy, load_table,
)


# ---- Empty cache (no tables on disk) -----------------------------------

def test_returns_none_when_no_tables(monkeypatch, tmp_path):
    """When the ranges dir is empty, loader returns None gracefully."""
    monkeypatch.setattr(ranges_mod, "RANGES_DIR", tmp_path)
    # Clear memoized state
    monkeypatch.setattr(ranges_mod, "_LOADED", {})
    assert available_stacks() == []
    assert closest_stack(10) is None
    assert get_strategy(10, "btn_push", "AA") is None


# ---- Synthetic table on disk -------------------------------------------

def _make_synthetic_table(path, stack_bb=10):
    data = {
        "stack_bb": stack_bb,
        "sb_bb": 0.5,
        "bb_bb": 1.0,
        "iterations": 50,
        "solver_version": "PushFoldSolver-synthetic",
        "aggregate_frequencies": {"btn_push": 0.30},
        "strategies": {
            "btn_push":               {"AA": 1.0, "32o": 0.0, "T9s": 0.6},
            "sb_call_vs_btn":         {"AA": 1.0, "32o": 0.0, "T9s": 0.0},
            "sb_push_after_btn_fold": {"AA": 1.0, "32o": 0.0, "T9s": 0.5},
            "bb_call_3way":           {"AA": 1.0, "32o": 0.0, "T9s": 0.0},
            "bb_call_vs_btn":         {"AA": 1.0, "32o": 0.0, "T9s": 0.2},
            "bb_call_vs_sb":          {"AA": 1.0, "32o": 0.0, "T9s": 0.4},
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def test_load_table_returns_data(monkeypatch, tmp_path):
    monkeypatch.setattr(ranges_mod, "RANGES_DIR", tmp_path)
    monkeypatch.setattr(ranges_mod, "_LOADED", {})
    _make_synthetic_table(tmp_path / "3max_nitro_10bb.json", stack_bb=10)
    table = load_table(10)
    assert table is not None
    assert table["stack_bb"] == 10
    assert "btn_push" in table["strategies"]


def test_closest_stack_picks_nearest(monkeypatch, tmp_path):
    monkeypatch.setattr(ranges_mod, "RANGES_DIR", tmp_path)
    monkeypatch.setattr(ranges_mod, "_LOADED", {})
    _make_synthetic_table(tmp_path / "3max_nitro_8bb.json", stack_bb=8)
    _make_synthetic_table(tmp_path / "3max_nitro_15bb.json", stack_bb=15)
    assert closest_stack(7) == 8       # 7 -> 8 is closer than 15
    assert closest_stack(10) == 8      # 10 -> 8 (dist 2) vs 15 (dist 5)
    assert closest_stack(13) == 15     # 13 -> 15 (dist 2) vs 8 (dist 5)


def test_get_strategy_fetches_freq(monkeypatch, tmp_path):
    monkeypatch.setattr(ranges_mod, "RANGES_DIR", tmp_path)
    monkeypatch.setattr(ranges_mod, "_LOADED", {})
    _make_synthetic_table(tmp_path / "3max_nitro_10bb.json", stack_bb=10)
    assert get_strategy(10, "btn_push", "AA") == 1.0
    assert get_strategy(10, "btn_push", "T9s") == 0.6
    assert get_strategy(10, "sb_call_vs_btn", "32o") == 0.0
    # Unknown hand returns None.
    assert get_strategy(10, "btn_push", "AAA") is None
    # Unknown scenario returns None.
    assert get_strategy(10, "fake_scenario", "AA") is None


def test_get_strategy_uses_closest_stack(monkeypatch, tmp_path):
    monkeypatch.setattr(ranges_mod, "RANGES_DIR", tmp_path)
    monkeypatch.setattr(ranges_mod, "_LOADED", {})
    _make_synthetic_table(tmp_path / "3max_nitro_15bb.json", stack_bb=15)
    # Stack 14 should round to 15.
    assert get_strategy(14, "btn_push", "AA") == 1.0
