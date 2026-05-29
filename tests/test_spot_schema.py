"""Unit tests for poky.solver.spot_schema."""
import pytest

from poky.solver.spot_schema import SpotKey, SpotSolution


def make_key(**overrides):
    base = dict(
        street="flop",
        board=("Ah", "Kh", "7d"),
        pot_chips=6,
        effective_stack=97,
        ip_range="AKs,KQs",
        oop_range="QQ,JTs",
    )
    base.update(overrides)
    return SpotKey(**base)


def test_spotkey_validates_street():
    with pytest.raises(ValueError):
        make_key(street="preflop")


def test_spotkey_validates_board_length():
    with pytest.raises(ValueError):
        make_key(street="turn", board=("Ah", "Kh", "7d"))  # missing turn card
    with pytest.raises(ValueError):
        make_key(street="flop", board=("Ah", "Kh"))


def test_spotkey_validates_card_format():
    with pytest.raises(ValueError):
        make_key(board=("A", "Kh", "7d"))               # rank only
    with pytest.raises(ValueError):
        make_key(board=("Ax", "Kh", "7d"))              # bad suit
    with pytest.raises(ValueError):
        make_key(board=("1h", "Kh", "7d"))              # bad rank


def test_spotkey_hash_stable_across_constructions():
    k1 = make_key()
    k2 = make_key()
    assert k1.hash_key() == k2.hash_key()


def test_spotkey_hash_changes_with_any_field():
    base = make_key()
    base_h = base.hash_key()
    assert make_key(pot_chips=7).hash_key() != base_h
    assert make_key(effective_stack=98).hash_key() != base_h
    assert make_key(ip_range="AKs").hash_key() != base_h
    assert make_key(board=("Ah", "Kh", "7c")).hash_key() != base_h


def test_spotsolution_roundtrip_via_dict():
    key = make_key()
    sol = SpotSolution(
        spot_key=key,
        player_at_root=1,
        root_actions=["CHECK", "BET 3.000000"],
        root_strategy={"AhKh": [0.2, 0.8], "AdKd": [0.3, 0.7]},
        aggregated_strategy=[("CHECK", 0.25), ("BET 3.000000", 0.75)],
        iterations=120,
        exploitability=0.45,
        solved_at="2026-05-29T11:00:00+00:00",
        elapsed_sec=18.3,
        solver_version="TexasSolver-v0.2.0",
        raw_path="",
    )
    d = sol.to_dict()
    rt = SpotSolution.from_dict(d)
    assert rt.spot_key.hash_key() == key.hash_key()
    assert rt.player_at_root == 1
    assert rt.root_actions == ["CHECK", "BET 3.000000"]
    assert rt.root_strategy["AhKh"] == [0.2, 0.8]
    assert rt.aggregated_strategy == [("CHECK", 0.25), ("BET 3.000000", 0.75)]
    assert rt.exploitability == pytest.approx(0.45)
