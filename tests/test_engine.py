"""Smoke tests sur le wrapper d'engine — verrouille l'API pour la suite."""
from poky.engine import Action, Game, Observation, Stage


def test_game_runs_to_completion():
    game = Game(num_players=3, seed=42)
    obs, pid = game.reset()
    assert isinstance(obs, Observation)
    assert obs.player_id == pid
    assert obs.num_players == 3
    assert len(obs.hole_cards) == 2
    assert obs.stage == Stage.PREFLOP
    assert Action.FOLD in obs.legal_actions

    steps = 0
    while not game.is_over():
        obs, pid = game.step(obs.legal_actions[0])  # tout le monde fold
        steps += 1
        assert steps < 100  # garde-fou anti-loop

    payoffs = game.payoffs()
    assert len(payoffs) == 3
    assert abs(sum(payoffs)) < 1e-6  # somme nulle


def test_seeded_runs_are_reproducible():
    g1 = Game(num_players=3, seed=123).reset()[0]
    g2 = Game(num_players=3, seed=123).reset()[0]
    assert g1.hole_cards == g2.hole_cards
    assert g1.all_committed == g2.all_committed


def test_legal_actions_only():
    game = Game(num_players=3, seed=7)
    obs, _ = game.reset()
    for a in obs.legal_actions:
        assert isinstance(a, Action)
