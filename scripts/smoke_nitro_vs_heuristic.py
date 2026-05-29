"""Phase N3 smoke — NitroPlayer vs 2x HeuristicPlayer at 3-max 15bb.

NOT a full SnG bench (that's N4 with blinds escalation + payouts). Just a
chip-EV sanity check: does NitroPlayer beat HeuristicPlayer in fixed-stack
3-max games at 15bb? Expected: yes (Heuristic isn't tuned for short stack).
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from poky.engine import Game
from poky.players.base import ActionEvent
from poky.players.heuristic import HeuristicPlayer
from poky.players.nitro_player import NitroPlayer

BIG_BLIND = 2


def run_match(hands: int, seed_base: int, chips: int = 30):
    """3-max, fixed-stack reset per hand, NitroPlayer cycles seats."""
    nitro = NitroPlayer(seed=42)
    h1 = HeuristicPlayer(seed=11)
    h2 = HeuristicPlayer(seed=22)
    payoffs_per_seed = defaultdict(list)
    for hand_idx in range(hands):
        nitro_seat = hand_idx % 3
        seats = [None, None, None]
        seats[nitro_seat] = nitro
        seats[(nitro_seat + 1) % 3] = h1
        seats[(nitro_seat + 2) % 3] = h2
        for p in seats:
            p.reset()
        game = Game(num_players=3, seed=seed_base + hand_idx,
                    chips_per_player=chips)
        obs, pid = game.reset()
        while not game.is_over():
            action = seats[pid].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            ev = ActionEvent(
                actor=pid, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seats:
                p.observe_action(ev)
            obs, pid = game.step(action)
        payoffs_per_seed[seed_base].append(game.payoffs()[nitro_seat])
    return payoffs_per_seed, nitro


def summarize(label, payoffs_per_seed, nitro):
    print(f"\n=== {label} ===")
    flat = []
    for seed, pl in payoffs_per_seed.items():
        chips_sum = sum(pl)
        bb100 = chips_sum / len(pl) / BIG_BLIND * 100
        flat.extend(pl)
        print(f"  seed {seed}: {chips_sum:+8.1f} chips  {bb100:+7.2f} bb/100  "
              f"({len(pl)} hands)")
    n = len(flat)
    mean = sum(flat) / n
    var = sum((x - mean) ** 2 for x in flat) / max(n - 1, 1)
    se = math.sqrt(var) / math.sqrt(n)
    se_bb = se / BIG_BLIND * 100
    mean_bb = mean / BIG_BLIND * 100
    ci95 = 1.96 * se_bb
    print(f"  >>> Mean = {mean_bb:+7.2f} bb/100 ±{ci95:.2f} IC95 (n={n})")

    stats = nitro.coverage_stats()
    print(f"  Nash hit rate: {stats['nash_hit_rate']*100:.1f}% "
          f"({stats['nash_hits']}/{stats['preflop_total']})")
    print(f"  Postflop decisions: {stats['postflop_decisions']}")
    print(f"  Scenarios:")
    for sc, c in sorted(stats['scenario_counts'].items(), key=lambda x: -x[1]):
        print(f"    {sc:35s}: {c}")
    print(f"  Action dist:")
    for a, c in sorted(stats['action_dist'].items(), key=lambda x: -x[1]):
        pct = c / sum(stats['action_dist'].values()) * 100
        print(f"    {a.name:15s}: {c:>5}  ({pct:5.1f}%)")


def run_self_play(hands: int, seed_base: int, chips: int = 30):
    """3 NitroPlayers self-play; expected: each ~ 0 bb/100 (zero-sum)."""
    p0 = NitroPlayer(seed=1)
    p1 = NitroPlayer(seed=2)
    p2 = NitroPlayer(seed=3)
    seats = [p0, p1, p2]
    payoffs = defaultdict(list)
    for hand_idx in range(hands):
        for p in seats:
            p.reset()
        game = Game(num_players=3, seed=seed_base + hand_idx,
                    chips_per_player=chips)
        obs, pid = game.reset()
        while not game.is_over():
            action = seats[pid].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            ev = ActionEvent(
                actor=pid, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seats:
                p.observe_action(ev)
            obs, pid = game.step(action)
        for s, payoff in enumerate(game.payoffs()):
            payoffs[s].append(payoff)
    return payoffs, p0


def main():
    print("NitroPlayer vs 2x HeuristicPlayer | 3-max | 15bb (chips=30, BB=2)")
    print("=" * 70)
    HANDS = 2000
    payoffs, nitro = run_match(hands=HANDS, seed_base=42, chips=30)
    summarize("NitroPlayer (cycled across seats) vs 2x HeuristicPlayer", payoffs, nitro)

    print("\n" + "=" * 70)
    print("Self-play sanity check: 3 NitroPlayers")
    print("=" * 70)
    sp_payoffs, sp_p0 = run_self_play(hands=HANDS, seed_base=42, chips=30)
    for seat, pl in sp_payoffs.items():
        chips_sum = sum(pl)
        bb100 = chips_sum / len(pl) / BIG_BLIND * 100
        n = len(pl)
        mean = sum(pl) / n
        var = sum((x - mean) ** 2 for x in pl) / max(n - 1, 1)
        se = math.sqrt(var) / math.sqrt(n) / BIG_BLIND * 100
        print(f"  seat {seat}: {bb100:+7.2f} bb/100 ±{1.96*se:.2f} IC95 ({n} hands)")
    print(f"  (each seat should be ~ 0 bb/100; positional biases possible)")


if __name__ == "__main__":
    main()
