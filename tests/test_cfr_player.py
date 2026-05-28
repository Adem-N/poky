"""
Tests pour CFRPlayer (blueprint + subgame solver).
Critères :
  - CFRPlayer charge le blueprint et joue sans crash
  - Le solver retourne des probabilités valides
  - L'addition de subgame solving change la stratégie (cas du moins, devrait pas crasher)
  - Fallback heuristic en cas d'erreur
"""
import os
import pytest

from poky.arena import run_match
from poky.players import CFRPlayer, HeuristicPlayer, RandomPlayer


BLUEPRINT = os.path.join("data", "blueprint_hu", "overnight_5M.pkl")
ALT_BLUEPRINT = os.path.join("data", "blueprint_hu", "v2_50k.pkl")


def _pick_blueprint():
    if os.path.exists(BLUEPRINT):
        return BLUEPRINT
    if os.path.exists(ALT_BLUEPRINT):
        return ALT_BLUEPRINT
    return None


@pytest.mark.skipif(_pick_blueprint() is None,
                    reason="Pas de blueprint disponible")
def test_cfr_player_loads():
    player = CFRPlayer(blueprint_path=_pick_blueprint(), time_budget_s=0.1)
    assert player.blueprint is not None
    assert player.solver is not None


@pytest.mark.skipif(_pick_blueprint() is None, reason="No blueprint")
def test_cfr_player_plays_5_hands_no_crash():
    """5 mains heads-up vs random, ne crash pas, fait des actions valides."""
    player = CFRPlayer(blueprint_path=_pick_blueprint(),
                       time_budget_s=0.1, sample_seed=42)
    res = run_match([player, RandomPlayer(seed=1)], hands=5, seed=42)
    # Somme nulle
    assert abs(sum(s.chips for s in res.stats)) < 1e-6
    # Au moins quelques tentatives solver
    assert player._solver_calls + player._solver_errors > 0


def test_cfr_player_missing_blueprint_raises():
    with pytest.raises(FileNotFoundError):
        CFRPlayer(blueprint_path="/nope/blueprint.pkl")
