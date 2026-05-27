"""Sanity tests sur l'arène : somme nulle, reproductibilité, baseline trivial."""
from poky.arena import run_match
from poky.players import RandomPlayer, AlwaysCallPlayer


def test_zero_sum():
    players = [RandomPlayer(seed=1), AlwaysCallPlayer(), RandomPlayer(seed=2)]
    res = run_match(players, hands=100, seed=42)
    total = sum(s.chips for s in res.stats)
    assert abs(total) < 1e-6, f"Chips ne somment pas à zéro : {total}"


def test_reproducibility():
    p_a = [RandomPlayer(seed=1), AlwaysCallPlayer(), RandomPlayer(seed=2)]
    p_b = [RandomPlayer(seed=1), AlwaysCallPlayer(), RandomPlayer(seed=2)]
    res_a = run_match(p_a, hands=50, seed=99)
    res_b = run_match(p_b, hands=50, seed=99)
    for sa, sb in zip(res_a.stats, res_b.stats):
        assert sa.chips == sb.chips


def test_call_beats_random_long_run():
    """Sur beaucoup de mains, le calling station bat les bots random."""
    players = [RandomPlayer(seed=1), AlwaysCallPlayer(), RandomPlayer(seed=2)]
    res = run_match(players, hands=500, seed=42)
    # call est position 1 dans players
    call_chips = res.stats[1].chips
    assert call_chips > 0, f"Calling station devrait gagner contre randoms : {call_chips}"
