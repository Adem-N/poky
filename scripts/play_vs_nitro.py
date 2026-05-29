"""Test play: NitroPlayer vs 2x ProShortStackPlayer (representing "me" as
two skilled human opponents). Verbose mode prints every action for analysis.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from poky.nitro.sng_runner import BlindLevel, SnGRunner
from poky.players.nitro_player import NitroPlayer
from poky.players.pro_shortstack import ProShortStackPlayer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sngs", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    finish_counts = [0, 0, 0]
    total_hands = 0
    nitro_paid = 0.0
    pro_paid = 0.0
    payouts = [100, 0, 0]

    print(f"=== NitroPlayer vs 2x ProShortStackPlayer ({args.sngs} SnGs) ===\n")
    for sng_idx in range(args.sngs):
        nitro_seat = sng_idx % 3
        nitro = NitroPlayer(seed=args.seed + sng_idx)
        pros = [ProShortStackPlayer(seed=args.seed + 100 + sng_idx),
                ProShortStackPlayer(seed=args.seed + 200 + sng_idx)]
        players = [None, None, None]
        players[nitro_seat] = nitro
        pi = iter(pros)
        for i in range(3):
            if players[i] is None:
                players[i] = next(pi)

        runner = SnGRunner(starting_chips=300, hands_per_level=4,
                           payouts=payouts, max_hands=80)
        result = runner.play(players, seed=args.seed + sng_idx)
        nitro_pos = result.finish_order.index(nitro_seat)
        finish_counts[nitro_pos] += 1
        total_hands += result.hands_played
        nitro_paid += result.payouts[nitro_seat]
        for i in range(3):
            if i != nitro_seat:
                pro_paid += result.payouts[i]

    n = args.sngs
    print(f"\nResults over {n} SnGs:")
    print(f"  Nitro 1st:  {finish_counts[0]:>3} ({finish_counts[0]/n*100:5.1f}%)  baseline 33.33%")
    print(f"  Nitro 2nd:  {finish_counts[1]:>3} ({finish_counts[1]/n*100:5.1f}%)")
    print(f"  Nitro 3rd:  {finish_counts[2]:>3} ({finish_counts[2]/n*100:5.1f}%)")
    print(f"  Avg hands per SnG: {total_hands/n:.1f}")
    print(f"  Total payout to Nitro: {nitro_paid:.1f}")
    print(f"  Total payout to Pros (combined seats): {pro_paid:.1f}")
    print(f"  Nitro ROI: {(nitro_paid/n - sum(payouts)/3) / (sum(payouts)/3) * 100:+.1f}%")


if __name__ == "__main__":
    main()
