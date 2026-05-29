"""Phase N4 bench — run many Nitro SnGs to measure win rate of NitroPlayer.

Cycles NitroPlayer across the 3 seats every N SnGs to neutralize positional
bias from the deterministic dealer start. Reports:
  - Win rate (% 1st-place finishes) with IC95
  - Distribution across 1st/2nd/3rd
  - Average ROI in payout units
  - Coverage stats from NitroPlayer (Nash hit rate)

Usage:
    python scripts/bench_nitro.py
    python scripts/bench_nitro.py --sngs 500 --opp heuristic --payouts wta
    python scripts/bench_nitro.py --sngs 200 --opp random
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from poky.nitro.sng_runner import BlindLevel, SnGRunner
from poky.players.archetypes import (
    LooseAggressivePlayer, ManiacPlayer, TightAggressivePlayer,
    TightPassivePlayer,
)
from poky.players.call_player import AlwaysCallPlayer
from poky.players.heuristic import HeuristicPlayer
from poky.players.nitro_player import NitroPlayer
from poky.players.random_player import RandomPlayer


_OPP_FACTORIES = {
    "heuristic": HeuristicPlayer,
    "tag": TightAggressivePlayer,
    "lag": LooseAggressivePlayer,
    "nit": TightPassivePlayer,
    "maniac": ManiacPlayer,
    "random": RandomPlayer,
    "call": AlwaysCallPlayer,
}


_PAYOUT_PROFILES = {
    "wta":     [100, 0, 0],         # winner-take-all (default Nitro)
    "icm100x": [80, 12, 8],         # ICM 100x jackpot
    "nitro2x": [100, 0, 0],         # winner-take-all (2x multiplier)
}


def run_bench(num_sngs: int, opp_factory, payouts, starting_chips: int,
              seed_base: int, hands_per_level: int):
    """Run `num_sngs` SnGs cycling NitroPlayer across seats. Returns per-SnG
    list of (nitro_seat, finish_position, payout)."""
    results = []
    finish_count = [0, 0, 0]   # times finished 1st, 2nd, 3rd
    coverage_total = {"nash_hits": 0, "preflop_total": 0, "postflop": 0}
    total_hands = 0

    for sng_idx in range(num_sngs):
        nitro_seat = sng_idx % 3
        nitro = NitroPlayer(seed=42 + sng_idx)
        opps = [opp_factory() for _ in range(2)]
        players = [None, None, None]
        players[nitro_seat] = nitro
        opp_iter = iter(opps)
        for i in range(3):
            if players[i] is None:
                players[i] = next(opp_iter)

        runner = SnGRunner(
            starting_chips=starting_chips,
            hands_per_level=hands_per_level,
            payouts=payouts,
            max_hands=80,
        )
        result = runner.play(players, seed=seed_base + sng_idx)

        # Find Nitro's finish position
        nitro_pos = result.finish_order.index(nitro_seat)
        finish_count[nitro_pos] += 1
        results.append((nitro_seat, nitro_pos, result.payouts[nitro_seat]))
        total_hands += result.hands_played

        # Aggregate coverage
        s = nitro.coverage_stats()
        coverage_total["nash_hits"] += s["nash_hits"]
        coverage_total["preflop_total"] += s["preflop_total"]
        coverage_total["postflop"] += s["postflop_decisions"]

    return results, finish_count, coverage_total, total_hands


def summarize(label: str, results, finish_count, coverage_total, total_hands,
              payouts):
    n = len(results)
    win_rate = finish_count[0] / n
    second_rate = finish_count[1] / n
    third_rate = finish_count[2] / n
    # IC95 on win rate (binomial)
    se_win = math.sqrt(win_rate * (1 - win_rate) / n)
    ci95_win = 1.96 * se_win

    # Mean payout & IC95
    payouts_list = [r[2] for r in results]
    mean_payout = sum(payouts_list) / n
    var_payout = sum((x - mean_payout) ** 2 for x in payouts_list) / max(n - 1, 1)
    se_payout = math.sqrt(var_payout) / math.sqrt(n)

    # ROI calculation: assume buy-in = sum(payouts) / 3 (zero-sum tournament)
    buy_in = sum(payouts) / 3
    roi = (mean_payout - buy_in) / buy_in if buy_in > 0 else 0

    print(f"\n=== {label} ===")
    print(f"  SnGs played   : {n}")
    print(f"  Total hands   : {total_hands}  ({total_hands/n:.1f} hands/SnG avg)")
    print(f"  Win rate (1st): {win_rate*100:6.2f}% ±{ci95_win*100:.2f}  (baseline 33.33%)")
    print(f"  2nd place     : {second_rate*100:6.2f}%")
    print(f"  3rd place     : {third_rate*100:6.2f}%")
    print(f"  Mean payout   : {mean_payout:6.2f} ±{1.96*se_payout:.2f}  (buy-in = {buy_in:.2f})")
    print(f"  ROI           : {roi*100:+6.2f}%")
    nash_total = coverage_total["preflop_total"]
    nash_rate = coverage_total["nash_hits"] / nash_total if nash_total else 0
    print(f"  Nash coverage : {coverage_total['nash_hits']}/{nash_total} "
          f"= {nash_rate*100:.1f}% preflop hits")
    print(f"  Postflop dec. : {coverage_total['postflop']}")

    # Verdict
    threshold = 33.33   # baseline
    if win_rate * 100 > threshold + 1.96 * se_win * 100:
        verdict = "BEATS BASELINE (stat sig)"
    elif win_rate * 100 < threshold - 1.96 * se_win * 100:
        verdict = "WORSE THAN BASELINE (stat sig)"
    else:
        verdict = "in noise / inconclusive"
    print(f"  Verdict       : {verdict}")
    return win_rate, ci95_win


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sngs", type=int, default=200,
                    help="number of SnGs to run")
    ap.add_argument("--opp", default="heuristic",
                    choices=list(_OPP_FACTORIES.keys()),
                    help="archetype of the 2 opponents")
    ap.add_argument("--payouts", default="wta",
                    choices=list(_PAYOUT_PROFILES.keys()))
    ap.add_argument("--chips", type=int, default=300,
                    help="starting stack (chips). 300 with BB=20 = 15bb")
    ap.add_argument("--hands-per-level", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    opp_factory = _OPP_FACTORIES[args.opp]
    payouts = _PAYOUT_PROFILES[args.payouts]

    print(f"Bench: NitroPlayer vs 2x {args.opp.upper()} | "
          f"start={args.chips} chips | payouts={args.payouts} | "
          f"{args.sngs} SnGs")

    results, finish_count, coverage_total, total_hands = run_bench(
        num_sngs=args.sngs,
        opp_factory=opp_factory,
        payouts=payouts,
        starting_chips=args.chips,
        seed_base=args.seed,
        hands_per_level=args.hands_per_level,
    )
    summarize(
        f"NitroPlayer vs 2x {args.opp.upper()} ({args.payouts})",
        results, finish_count, coverage_total, total_hands, payouts,
    )


if __name__ == "__main__":
    main()
