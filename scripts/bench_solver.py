"""Phase Z3 bench — SolverOraclePlayer vs baselines on HU.

Runs two matches and prints a side-by-side comparison:
  1. SolverOraclePlayer vs HeuristicPlayer  (does the oracle still beat the
     baseline we already validated?)
  2. SolverOraclePlayer vs ExpertOnlyPlayer (does the oracle REGRESS vs our
     Tier 1+2 fallback? if yes -> the cache is making us worse)

Reports coverage diagnostics (cache hit rate, translation misses) so we know
whether the SolverOracle is actually consulting GTO or just running on
fallback Tier 2 the whole time.

Usage:
    python scripts/bench_solver.py
    python scripts/bench_solver.py --db data/solver_cache/hu_flop.sqlite \\
        --hands 2000 --seeds 7,13,21
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from poky.engine import Game
from poky.players.base import ActionEvent
from poky.players.expert_only import ExpertOnlyPlayer
from poky.players.heuristic import HeuristicPlayer
from poky.players.solver_oracle import SolverOraclePlayer
from poky.solver.cache_db import CacheDB


BIG_BLIND = 2
DEFAULT_DB = REPO_ROOT / "data" / "solver_cache" / "hu_flop.sqlite"


def run_hu_match(p_hero_factory, p_villain_factory, hands: int, seed_base: int,
                 chips_per_player: int = 200):
    """Plays HU; hero cycles seats every hand to neutralize positional bias."""
    hero = p_hero_factory()
    villain = p_villain_factory()
    payoffs = []
    for hand_idx in range(hands):
        hero_seat = hand_idx % 2
        seats = [None, None]
        seats[hero_seat] = hero
        seats[1 - hero_seat] = villain
        for p in seats:
            p.reset()
        game = Game(num_players=2, seed=seed_base + hand_idx,
                    chips_per_player=chips_per_player)
        obs, cur = game.reset()
        while not game.is_over():
            action = seats[cur].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            ev = ActionEvent(
                actor=cur, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seats:
                p.observe_action(ev)
            obs, cur = game.step(action)
        payoffs.append(game.payoffs()[hero_seat])
    return payoffs, hero


def summarize(label: str, payoffs_per_seed: dict, players_per_seed: dict):
    print(f"\n=== {label} ===")
    flat = []
    for seed, pl in sorted(payoffs_per_seed.items()):
        chips_sum = sum(pl)
        bb100 = chips_sum / len(pl) / BIG_BLIND * 100
        flat.extend(pl)
        print(f"  seed {seed:>4}: {chips_sum:+8.1f} chips  "
              f"{bb100:+7.2f} bb/100  ({len(pl)} mains)")
    n = len(flat)
    mean = sum(flat) / n
    var = sum((x - mean) ** 2 for x in flat) / max(n - 1, 1)
    se = math.sqrt(var) / math.sqrt(n)
    se_bb100 = se / BIG_BLIND * 100
    mean_bb100 = mean / BIG_BLIND * 100
    ci95 = 1.96 * se_bb100
    print(f"  >>> mean = {mean_bb100:+7.2f} bb/100  ±{ci95:.2f} IC95  (n={n})")

    # Coverage aggregation across all seeds (when hero is SolverOracle).
    total_pre = 0
    total_hits = 0
    total_misses = 0
    total_trans_misses = 0
    action_dist = defaultdict(int)
    has_oracle = False
    for p in players_per_seed.values():
        if isinstance(p, SolverOraclePlayer):
            has_oracle = True
            s = p.coverage_stats()
            total_pre += s["preflop_decisions"]
            total_hits += s["postflop_cache_hits"]
            total_misses += s["postflop_cache_misses"]
            total_trans_misses += s["postflop_translation_misses"]
            for a, c in s["action_dist"].items():
                action_dist[a] += c
    if has_oracle:
        total_post = total_hits + total_misses
        hit_rate = (total_hits / total_post * 100) if total_post else 0.0
        print(f"  cache: {total_hits} hits / {total_post} postflop "
              f"= {hit_rate:.1f}% hit rate")
        print(f"  preflop decisions: {total_pre} (delegated to ExpertOnly fallback)")
        if total_trans_misses:
            print(f"  translation misses (cache hit but no legal mapping): "
                  f"{total_trans_misses}")
        if action_dist:
            print(f"  action distribution:")
            for a, c in sorted(action_dist.items(), key=lambda x: -x[1]):
                pct = c / sum(action_dist.values()) * 100
                print(f"    {a.name:18s}: {c:6d}  ({pct:5.1f}%)")
    return mean_bb100, ci95, n


def bench_against(label, hero_factory, villain_factory, hands, seeds):
    payoffs_per_seed = {}
    players_per_seed = {}
    for i, seed in enumerate(seeds):
        payoffs, hero = run_hu_match(hero_factory, villain_factory,
                                     hands=hands, seed_base=seed)
        payoffs_per_seed[seed] = payoffs
        players_per_seed[seed] = hero
    return summarize(label, payoffs_per_seed, players_per_seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="path to solver cache SQLite file")
    ap.add_argument("--hands", type=int, default=2000)
    ap.add_argument("--seeds", default="7,13,21")
    ap.add_argument("--rng-seed", type=int, default=42)
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    if not Path(args.db).exists():
        print(f"WARN: cache db {args.db} does not exist — SolverOracle will "
              f"always fall back. Continuing anyway.")
    cache = CacheDB(args.db)
    print(f"Bench setup: HU @ 100bb  | {args.hands} hands × {len(seeds)} seeds "
          f"= {args.hands*len(seeds)} mains/match")
    print(f"Cache db: {args.db}")
    cache_stats = cache.stats()
    print(f"Cache size: {cache_stats['n_solutions']} solved spots")

    # 1. vs Heuristic
    bench_against(
        "SolverOracle vs HeuristicPlayer (HU)",
        lambda: SolverOraclePlayer(cache=cache, seed=args.rng_seed),
        lambda: HeuristicPlayer(seed=args.rng_seed + 1),
        hands=args.hands,
        seeds=seeds,
    )

    # 2. vs ExpertOnly (regression check)
    bench_against(
        "SolverOracle vs ExpertOnlyPlayer (regression check)",
        lambda: SolverOraclePlayer(cache=cache, seed=args.rng_seed),
        lambda: ExpertOnlyPlayer(seed=args.rng_seed + 1),
        hands=args.hands,
        seeds=seeds,
    )

    # 3. Baseline: ExpertOnly vs Heuristic, to confirm what we'd get without
    #    the solver layer (sanity check that our reference number is stable).
    bench_against(
        "ExpertOnly vs HeuristicPlayer (baseline reference)",
        lambda: ExpertOnlyPlayer(seed=args.rng_seed),
        lambda: HeuristicPlayer(seed=args.rng_seed + 1),
        hands=args.hands,
        seeds=seeds,
    )

    cache.close()


if __name__ == "__main__":
    main()
