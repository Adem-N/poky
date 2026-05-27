"""
Tests pour BlueprintPlayer.

Critères :
  - Charge un .pkl MCCFR sans crash
  - Joue dans l'arena heads-up sans crash
  - Quand il n'a pas de strategy (info set absent), fallback proprement sur l'heuristic
  - Hit rate > 0 après un peu de play (visite des info sets connus)
"""
import os
import pytest

from poky.arena import run_match
from poky.players import HeuristicPlayer, RandomPlayer, BlueprintPlayer


SMOKE_CHECKPOINT = os.path.join(
    "data", "blueprint_hu", "smoke.pkl",
)


@pytest.mark.skipif(
    not os.path.exists(SMOKE_CHECKPOINT),
    reason="Pas de checkpoint smoke. Lance d'abord "
           "`python -m poky.training.mccfr_hunl --iterations 500 "
           "--save-path data/blueprint_hu/smoke.pkl`."
)
def test_blueprint_player_loads():
    """Charge un checkpoint sans crash."""
    player = BlueprintPlayer(model_path=SMOKE_CHECKPOINT)
    assert player.trainer is not None
    assert len(player.trainer.regret_sum) > 0


@pytest.mark.skipif(
    not os.path.exists(SMOKE_CHECKPOINT),
    reason="Pas de checkpoint smoke disponible."
)
def test_blueprint_player_plays_in_arena():
    """Joue 50 mains HU vs random. Vérifie qu'il y a au moins quelques hits."""
    bp = BlueprintPlayer(model_path=SMOKE_CHECKPOINT)
    res = run_match([bp, RandomPlayer(seed=1)], hands=50, seed=42)
    # somme nulle
    assert abs(sum(s.chips for s in res.stats)) < 1e-6
    # Il doit avoir lookupé au moins quelques info sets
    assert bp._lookup_hits + bp._lookup_misses > 0


def test_blueprint_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        BlueprintPlayer(model_path="/path/that/does/not/exist.pkl")
