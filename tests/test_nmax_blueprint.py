"""Tests pour NMaxBlueprintPlayer (3-max)."""
import os
import pytest

from poky.arena import run_match
from poky.players import (
    HeuristicPlayer, RandomPlayer, NMaxBlueprintPlayer,
)


SMOKE_3MAX = os.path.join("data", "blueprint_3max", "smoke.pkl")


@pytest.mark.skipif(not os.path.exists(SMOKE_3MAX),
                    reason="Pas de smoke 3-max. Lance d'abord : "
                           "python -m poky.training.mccfr_nmax --num-players 3 "
                           "--iterations 200 --save-path " + SMOKE_3MAX)
def test_nmax_blueprint_loads():
    bp = NMaxBlueprintPlayer(model_path=SMOKE_3MAX)
    assert bp.trainer is not None
    assert bp.trainer.num_players == 3
    assert len(bp.trainer.regret_sum) > 0


@pytest.mark.skipif(not os.path.exists(SMOKE_3MAX), reason="No smoke.")
def test_nmax_blueprint_plays_3max():
    bp = NMaxBlueprintPlayer(model_path=SMOKE_3MAX)
    players = [bp, HeuristicPlayer(seed=1), RandomPlayer(seed=2)]
    res = run_match(players, hands=30, seed=42)
    assert abs(sum(s.chips for s in res.stats)) < 1e-6
    # Au moins quelques décisions ont été prises
    assert bp._lookup_hits + bp._lookup_misses > 0


def test_nmax_blueprint_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        NMaxBlueprintPlayer(model_path="/nope.pkl")
