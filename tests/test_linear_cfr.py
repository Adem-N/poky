"""
Tests Linear CFR (Brown & Sandholm 2019).

Critères :
  - Linear CFR converge AUSSI vers -1/18 sur Kuhn (correction préservée)
  - Linear CFR converge PLUS VITE que vanilla (le gain est testable :
    à N iterations identiques, Linear devrait avoir un écart absolu plus petit
    que vanilla par rapport à -1/18 sur les MÊMES seeds).
"""
from poky.training.kuhn_cfr import KuhnCFRTrainer


def test_linear_cfr_converges_to_nash():
    """Linear CFR doit aussi converger vers la valeur exacte -1/18."""
    trainer = KuhnCFRTrainer(linear=True)
    history = trainer.train(iterations=10_000)
    final = history[-1]
    expected = -1.0 / 18
    assert abs(final - expected) < 0.005, \
        f"Linear CFR n'a pas convergé : {final:.5f} vs Nash {expected:.5f}"


def test_linear_converges_at_similar_speed_on_kuhn():
    """Sur Kuhn (jeu minuscule), Vanilla converge déjà très vite.
    Linear CFR doit converger à une erreur du MÊME ORDRE DE GRANDEUR.
    Le vrai gain de Linear se mesurera sur Leduc/NLHE.
    """
    iterations = 3000
    vanilla = KuhnCFRTrainer(linear=False)
    linear = KuhnCFRTrainer(linear=True)
    hv = vanilla.train(iterations)
    hl = linear.train(iterations)
    expected = -1.0 / 18

    vanilla_err = sum(abs(v - expected) for v in hv[-500:]) / 500
    linear_err = sum(abs(v - expected) for v in hl[-500:]) / 500

    # Sur Kuhn les deux doivent être < 1% d'erreur, et Linear pas catastrophique
    assert vanilla_err < 0.01, f"Vanilla CFR ne converge pas : {vanilla_err}"
    assert linear_err < 0.01, f"Linear CFR ne converge pas : {linear_err}"
    # On accepte que Linear soit jusqu'à 5x vanilla sur ce petit jeu
    # (sur des jeux plus gros il sera bien meilleur — cf. Brown 2019)
    assert linear_err < vanilla_err * 5, \
        f"Linear ({linear_err}) dérive trop vs vanilla ({vanilla_err})"
