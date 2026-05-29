"""
Mesure l'impact de Phase X2 (postflop rules) en comparant ExpertOnly avec
et sans les nouvelles règles, à seeds identiques.

Sortie : delta bb/100 entre X2-on et X2-off.
"""
import argparse
import math

from poky.engine import Game
from poky.players.archetypes import (
    LooseAggressivePlayer, ManiacPlayer, TightAggressivePlayer,
    TightPassivePlayer,
)
from poky.players.base import ActionEvent
from poky.players.expert_only import ExpertOnlyPlayer
from poky.players.heuristic import HeuristicPlayer


BIG_BLIND = 2
CHIPS = 200    # 100bb


_OPPS = {
    "heuristic": HeuristicPlayer,
    "tag": TightAggressivePlayer,
    "lag": LooseAggressivePlayer,
    "nit": TightPassivePlayer,
    "maniac": ManiacPlayer,
}


def _make_opp(cls, seed):
    try:
        return cls(seed=seed)
    except TypeError:
        return cls()


def run(num_players, opp_name, hands, seeds, use_x2, expert_seed=42):
    opp_cls = _OPPS[opp_name]
    payoffs = []
    expert_final = None
    for i, seed in enumerate(seeds):
        opp_seed = expert_seed + 1 + i * 100
        expert = ExpertOnlyPlayer(seed=expert_seed,
                                   use_postflop_rules=use_x2)
        opps = [_make_opp(opp_cls, opp_seed + j) for j in range(num_players - 1)]
        for h in range(hands):
            expert_seat = h % num_players
            seats = list(opps)
            seats.insert(expert_seat, expert)
            for p in seats:
                p.reset()
            g = Game(num_players=num_players, seed=seed + h,
                     chips_per_player=CHIPS)
            obs, current = g.reset()
            while not g.is_over():
                a = seats[current].act(obs)
                if a not in obs.legal_actions:
                    a = obs.legal_actions[0]
                event = ActionEvent(
                    actor=current, action=a, stage=obs.stage,
                    to_call_before=obs.to_call,
                    all_committed_before=list(obs.all_committed),
                    big_blind=obs.big_blind,
                )
                for p in seats:
                    p.observe_action(event)
                obs, current = g.step(a)
            payoffs.append(g.payoffs()[expert_seat])
        expert.reset()
        expert_final = expert
    n = len(payoffs)
    mean = sum(payoffs) / n
    var = sum((p - mean) ** 2 for p in payoffs) / max(n - 1, 1)
    se = math.sqrt(var) / math.sqrt(n)
    mean_bb100 = mean / BIG_BLIND * 100
    ic95 = 1.96 * se / BIG_BLIND * 100
    # coverage postflop
    if expert_final and (expert_final.postflop_expert_hits +
                         expert_final.postflop_fallback_hits) > 0:
        cov_pf = expert_final.postflop_expert_hits / (
            expert_final.postflop_expert_hits + expert_final.postflop_fallback_hits)
    else:
        cov_pf = 0.0
    return mean_bb100, ic95, cov_pf, payoffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=2, choices=[2, 3, 6])
    ap.add_argument("--opp", type=str, default="heuristic",
                    choices=list(_OPPS.keys()))
    ap.add_argument("--hands", type=int, default=10000)
    ap.add_argument("--seeds", type=str, default="7,13,21,42,99")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    n = args.players
    tlabel = {2: "HU", 3: "3-max", 6: "6-max"}[n]
    print(f"X2 impact : ExpertOnly @ 100bb {tlabel} vs {args.opp.upper()} "
          f"- {args.hands} mains x {len(seeds)} seeds")
    print()

    # Baseline X1 only
    m_off, ic_off, cov_off, pay_off = run(n, args.opp, args.hands, seeds,
                                            use_x2=False)
    # X2 on
    m_on, ic_on, cov_on, pay_on = run(n, args.opp, args.hands, seeds,
                                       use_x2=True)

    # Paired t-test on per-hand diff (memes seeds → diff direct)
    diffs = [a - b for a, b in zip(pay_on, pay_off)]
    n_pairs = len(diffs)
    md = sum(diffs) / n_pairs
    vd = sum((d - md) ** 2 for d in diffs) / max(n_pairs - 1, 1)
    sed = math.sqrt(vd) / math.sqrt(n_pairs)
    delta_bb100 = md / BIG_BLIND * 100
    delta_ic = 1.96 * sed / BIG_BLIND * 100

    print(f"{'Variant':<18} {'Mean bb/100':>13} {'IC95':>10} {'Cov pf':>10}")
    print("-" * 60)
    print(f"{'X1 only (Tier 2)':<18} {m_off:+10.2f}    +/-{ic_off:6.2f}    "
          f"{cov_off*100:6.1f}%")
    print(f"{'X1 + X2':<18} {m_on:+10.2f}    +/-{ic_on:6.2f}    "
          f"{cov_on*100:6.1f}%")
    print("-" * 60)
    print(f"{'Delta (paired)':<18} {delta_bb100:+10.2f}    +/-{delta_ic:6.2f}")
    bound = delta_bb100 - delta_ic
    print(f"\nBound inf IC95 delta : {bound:+.2f} bb/100")
    if bound >= 2.0:
        print("OK : Phase X2 PASS (delta >= +2 bb/100)")
    elif delta_bb100 > 0:
        print("WARN : delta positif mais bound inf < +2. Sample insuffisant"
              " ou improvement marginal.")
    else:
        print("FAIL : Phase X2 ne passe pas (delta <= 0)")


if __name__ == "__main__":
    main()
