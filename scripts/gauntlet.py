"""
Gauntlet : lance ExpertOnly contre tous les archetypes, sur les 3
tailles de table, a 100bb. Reporte un tableau de resultats permettant
de juger Phase X1 par rapport aux criteres docs/SUCCESS_CRITERIA.md.

Usage :
  python scripts/gauntlet.py --hands 10000 --seeds 7,13,21,42,99
  python scripts/gauntlet.py --quick     # 2000 mains x 3 seeds
"""
import argparse
import math
import sys

from poky.engine import Game
from poky.players.archetypes import (
    LooseAggressivePlayer, ManiacPlayer, TightAggressivePlayer,
    TightPassivePlayer,
)
from poky.players.base import ActionEvent
from poky.players.call_player import AlwaysCallPlayer
from poky.players.expert_only import ExpertOnlyPlayer
from poky.players.heuristic import HeuristicPlayer
from poky.players.random_player import RandomPlayer


BIG_BLIND = 2
CHIPS_PER_PLAYER = 200    # 100bb effectif


_OPPS = {
    "heuristic": HeuristicPlayer,
    "tag": TightAggressivePlayer,
    "lag": LooseAggressivePlayer,
    "nit": TightPassivePlayer,
    "maniac": ManiacPlayer,
    "random": RandomPlayer,
    "call": AlwaysCallPlayer,
}


# Criteres : (table_size, opp) -> (min_lower_bound_bb100, comment)
# Source : docs/SUCCESS_CRITERIA.md Phase X1
_CRITERIA = {
    "heuristic": (5.0, "exploit-tuner baseline"),
    "tag": (0.0, "joueur recreatif serieux"),
    "lag": (0.0, "joueur recreatif serieux"),
    "nit": (15.0, "trivial a exploiter"),
    "maniac": (30.0, "trivial a exploiter"),
    "random": (30.0, "garde-fou"),
    "call": (20.0, "garde-fou"),
}


def _make_opp(cls, seed):
    """AlwaysCallPlayer ne prend pas de seed (deterministe), les autres oui."""
    try:
        return cls(seed=seed)
    except TypeError:
        return cls()


def run_one(num_players, opp_name, hands, seeds, expert_seed=42):
    opp_cls = _OPPS[opp_name]
    all_payoffs = []
    expert_final = None
    for i, seed in enumerate(seeds):
        opp_seed = expert_seed + 1 + i * 100
        expert = ExpertOnlyPlayer(seed=expert_seed)
        opps = [_make_opp(opp_cls, opp_seed + j) for j in range(num_players - 1)]
        for h in range(hands):
            expert_seat = h % num_players
            seats = list(opps)
            seats.insert(expert_seat, expert)
            for p in seats:
                p.reset()
            g = Game(num_players=num_players, seed=seed + h,
                     chips_per_player=CHIPS_PER_PLAYER)
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
            all_payoffs.append(g.payoffs()[expert_seat])
        expert.reset()
        expert_final = expert

    n = len(all_payoffs)
    mean = sum(all_payoffs) / n
    var = sum((p - mean) ** 2 for p in all_payoffs) / max(n - 1, 1)
    se = math.sqrt(var) / math.sqrt(n)
    mean_bb100 = mean / BIG_BLIND * 100
    ic95 = 1.96 * se / BIG_BLIND * 100
    lower = mean_bb100 - ic95
    upper = mean_bb100 + ic95

    # Coverage
    if expert_final:
        total = expert_final.preflop_expert_hits + expert_final.preflop_fallback_hits
        cov = expert_final.preflop_expert_hits / max(total, 1)
    else:
        cov = 0.0

    return mean_bb100, ic95, lower, upper, n, cov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=10000)
    ap.add_argument("--seeds", type=str, default="7,13,21,42,99")
    ap.add_argument("--quick", action="store_true",
                    help="2000 mains x 3 seeds (rapide)")
    ap.add_argument("--tables", type=str, default="2,3,6",
                    help="Tailles de table a tester (csv)")
    ap.add_argument("--opps", type=str,
                    default="heuristic,tag,lag,nit,maniac,random,call")
    args = ap.parse_args()

    if args.quick:
        hands = 2000
        seeds = [7, 13, 42]
    else:
        hands = args.hands
        seeds = [int(s) for s in args.seeds.split(",")]
    tables = [int(t) for t in args.tables.split(",")]
    opps = args.opps.split(",")

    table_labels = {2: "HU", 3: "3-max", 6: "6-max"}

    print(f"\n{'='*80}")
    print(f"GAUNTLET ExpertOnly @ 100bb — {hands} mains x {len(seeds)} seeds "
          f"= {hands*len(seeds)} par cellule")
    print(f"{'='*80}\n")

    print(f"{'Table':<8} {'Opp':<10} {'Mean':>10} {'IC95':>10} "
          f"{'Bound inf':>10} {'Cov%':>8} {'Critere':>10} {'Status':>8}")
    print("-" * 80)

    failures = []
    for n in tables:
        for opp in opps:
            mean, ic95, lower, upper, sample, cov = run_one(
                n, opp, hands, seeds
            )
            crit, _ = _CRITERIA.get(opp, (None, None))
            crit_str = f">={crit:+.0f}" if crit is not None else "—"
            if crit is None:
                status = "—"
            else:
                status = "PASS" if lower >= crit else "FAIL"
                if status == "FAIL":
                    failures.append((table_labels[n], opp, lower, crit))
            print(f"{table_labels[n]:<8} {opp:<10} "
                  f"{mean:+8.2f}   +/-{ic95:6.2f}   "
                  f"{lower:+8.2f}   {cov*100:6.1f}%   "
                  f"{crit_str:>8}   {status:>6}")
        print()

    print("-" * 80)
    if failures:
        print(f"\nFAIL : {len(failures)} cellules echouent :")
        for t, opp, lower, crit in failures:
            print(f"   - {t} vs {opp} : bound inf {lower:+.2f} < critere {crit:+.0f}")
        sys.exit(1)
    else:
        print("\nOK : Toutes les cellules passent les criteres Phase X1.")


if __name__ == "__main__":
    main()
