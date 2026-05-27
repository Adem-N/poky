"""
Tests des archétypes — vérification que chaque profil joue effectivement
comme attendu et que le runner ne crashe pas avec eux.
"""
from poky.arena import run_match
from poky.players import (
    HeuristicPlayer, TightPassivePlayer, TightAggressivePlayer,
    LooseAggressivePlayer, ManiacPlayer, RandomPlayer,
)


def test_all_archetypes_run_without_crash():
    """Smoke test : chaque archétype doit jouer sans erreur."""
    for cls in (TightPassivePlayer, TightAggressivePlayer,
                LooseAggressivePlayer, ManiacPlayer):
        players = [cls(seed=1), RandomPlayer(seed=2), RandomPlayer(seed=3)]
        res = run_match(players, hands=50, seed=42)
        assert sum(s.chips for s in res.stats) == 0  # somme nulle


def test_maniac_loses_to_tight_passive():
    """Le maniac DOIT perdre face aux nits. C'est l'ordre du monde poker
    en règle : jeter ses chips n'importe comment vs des joueurs serrés = perte."""
    players = [
        ManiacPlayer(seed=1),
        TightPassivePlayer(seed=2),
        TightPassivePlayer(seed=3),
    ]
    res = run_match(players, hands=600, seed=42)
    maniac = res.stats[0]
    assert maniac.bb_per_100 < 0, \
        f"Maniac devrait perdre vs nits, gagne {maniac.bb_per_100:+.1f}"


def test_tag_does_not_lose_to_random():
    """TAG doit au minimum ne pas perdre contre des randoms (à variance près).
    Le seuil est bas car en 3-max les blinds forcées sont coûteuses pour un
    bot qui fold beaucoup."""
    players = [
        TightAggressivePlayer(seed=1),
        RandomPlayer(seed=2),
        RandomPlayer(seed=3),
    ]
    res = run_match(players, hands=1500, seed=42)
    tag = res.stats[0]
    # TAG doit être à l'IC95% au-dessus de -50 bb/100
    assert tag.bb_per_100 + tag.ci95_bb100 > 0, \
        f"TAG vs random : {tag.bb_per_100:+.1f} ± {tag.ci95_bb100:.1f} bb/100"


def test_heuristic_beats_each_archetype_individually():
    """L'heuristique actuelle doit battre chaque archétype 1-vs-2-mêmes.
    Si elle ne le fait pas, on a un problème à corriger."""
    archetypes = {
        "tight_passive": TightPassivePlayer,
        "tag": TightAggressivePlayer,
        "lag": LooseAggressivePlayer,
        "maniac": ManiacPlayer,
    }
    losses = []
    for name, cls in archetypes.items():
        players = [HeuristicPlayer(seed=10), cls(seed=20), cls(seed=21)]
        res = run_match(players, hands=400, seed=42)
        heur = res.stats[0]
        # Au minimum, l'heuristique doit ne PAS perdre statistiquement
        if heur.bb_per_100 + heur.ci95_bb100 < 0:
            losses.append((name, heur.bb_per_100, heur.ci95_bb100))
    assert not losses, f"Heuristique perd contre : {losses}"
