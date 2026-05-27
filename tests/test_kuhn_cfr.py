"""
Tests de validation du CFR sur Kuhn poker.
Si ces tests passent, l'implémentation CFR est correcte.
"""
from poky.training.kuhn_cfr import KuhnCFRTrainer


def test_game_value_converges_to_minus_1_18():
    """Le théorème de Kuhn (1950) dit que la valeur du jeu pour J1
    à l'équilibre de Nash vaut exactement -1/18."""
    trainer = KuhnCFRTrainer()
    history = trainer.train(iterations=15_000)
    final_value = history[-1]
    expected = -1.0 / 18
    assert abs(final_value - expected) < 0.005, \
        f"Valeur de jeu {final_value:.5f}, attendue {expected:.5f}"


def test_pure_strategies_match_nash():
    """Vérifie les actions pures connues de l'équilibre :
       - J2 avec K : toujours bet/call
       - J1 avec Q : toujours check (initial)
       - J1 avec J : fold sur bet
    """
    trainer = KuhnCFRTrainer()
    trainer.train(iterations=15_000)
    strat = trainer.average_strategies()

    # J1 avec Q initial → check (action 'c' = index 0)
    assert strat["Q:"][0] > 0.95, f"J1 Q init devrait check : {strat['Q:']}"

    # J2 avec K après check de J1 → bet (action 'b' = index 1)
    assert strat["K:c"][1] > 0.95, f"J2 K vs check devrait bet : {strat['K:c']}"

    # J2 avec K après bet de J1 → call (action 'c' = index 1 dans fold/call)
    assert strat["K:b"][1] > 0.95, f"J2 K vs bet devrait call : {strat['K:b']}"

    # J1 avec J après check-bet → fold (action 'f' = index 0)
    assert strat["J:cb"][0] > 0.95, f"J1 J vs cb devrait fold : {strat['J:cb']}"


def test_mixed_strategies_match_nash_family():
    """L'équilibre de Kuhn est paramétré par α (bet J1 avec J) ∈ [0, 1/3].
    Les autres mix sont liés :
       - J1 bet K  = 3α
       - J2 bet J  = 1/3
       - J2 call Q = 1/3
    """
    trainer = KuhnCFRTrainer()
    trainer.train(iterations=15_000)
    strat = trainer.average_strategies()

    alpha = strat["J:"][1]  # J1 bet J
    assert 0.0 <= alpha <= 0.34, f"α = {alpha:.3f} hors [0, 1/3]"

    # J1 bet K devrait valoir ~3α
    bet_k = strat["K:"][1]
    assert abs(bet_k - 3 * alpha) < 0.10, \
        f"J1 bet K = {bet_k:.3f}, attendu ~3α = {3*alpha:.3f}"

    # J2 bet J doit valoir ~1/3
    bet_j_p2 = strat["J:c"][1]
    assert abs(bet_j_p2 - 1/3) < 0.05, f"J2 bet J = {bet_j_p2:.3f}, attendu 1/3"

    # J2 call Q vs bet doit valoir ~1/3
    call_q_p2 = strat["Q:b"][1]
    assert abs(call_q_p2 - 1/3) < 0.05, f"J2 call Q = {call_q_p2:.3f}, attendu 1/3"
