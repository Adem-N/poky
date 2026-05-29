"""Generate Nash push/fold strategy tables for 3-max NLHE at multiple stack depths.

First run computes the 169x169 HU equity table (~5-10 minutes, cached after).
Then solves Nash equilibrium per stack depth (~20-60s each).

Output: JSON tables under data/expert_ranges/3max_nitro/.

Usage:
    python scripts/build_pushfold_tables.py
    python scripts/build_pushfold_tables.py --stacks 6,8,10,12,15 --iters 80
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from poky.abstraction.preflop import NUM_PREFLOP_CLASSES, class_name
from poky.nitro.equity_table import get_hu_equity_table, prior_distribution
from poky.nitro.pushfold import PushFoldSolver


OUTPUT_DIR = REPO_ROOT / "data" / "expert_ranges" / "3max_nitro"


def solve_one_stack(stack_bb: int, hu_table, max_iter: int, threeway_samples: int,
                    tol: float, verbose: bool) -> dict:
    print(f"\n=== Stack {stack_bb}bb — solving Nash 3-max push/fold ===")
    solver = PushFoldSolver(
        stack_bb=stack_bb,
        hu_eq_table=hu_table,
        threeway_samples=threeway_samples,
        seed=42,
    )
    t0 = time.time()
    strats = solver.solve(max_iter=max_iter, tolerance=tol, verbose=verbose)
    elapsed = time.time() - t0
    print(f"  done in {elapsed:.1f}s after {solver.iterations_run} iters")
    prior = prior_distribution()
    # Aggregate stats
    fields = ("btn_push", "sb_call_vs_btn", "sb_push_after_btn_fold",
              "bb_call_3way", "bb_call_vs_btn", "bb_call_vs_sb")
    aggs = {}
    for f in fields:
        arr = getattr(strats, f)
        aggs[f] = float((arr * prior).sum())
    for f, val in aggs.items():
        print(f"  {f:30s}: {val*100:5.1f}% of hands")
    output = {
        "stack_bb": stack_bb,
        "sb_bb": 0.5,
        "bb_bb": 1.0,
        "iterations": solver.iterations_run,
        "solver_version": "PushFoldSolver-v0.1",
        "aggregate_frequencies": aggs,
        "strategies": strats.to_dict(),
    }
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stacks", default="6,8,10,12,15",
                    help="comma-separated list of stack depths in BB")
    ap.add_argument("--iters", type=int, default=80,
                    help="max FP iterations per stack")
    ap.add_argument("--samples", type=int, default=60,
                    help="3-way MC samples per equity vector per iter")
    ap.add_argument("--tol", type=float, default=5e-3)
    ap.add_argument("--hu-sims", type=int, default=800,
                    help="MC sims per cell when building HU equity table")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    stacks = [int(s) for s in args.stacks.split(",")]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading / building HU equity table ({args.hu_sims} sims/cell)...")
    t0 = time.time()
    hu_table = get_hu_equity_table(simulations=args.hu_sims, verbose=args.verbose)
    print(f"  HU table ready (shape {hu_table.shape}) in {time.time()-t0:.1f}s")

    for stack in stacks:
        result = solve_one_stack(
            stack_bb=stack,
            hu_table=hu_table,
            max_iter=args.iters,
            threeway_samples=args.samples,
            tol=args.tol,
            verbose=args.verbose,
        )
        path = OUTPUT_DIR / f"3max_nitro_{stack}bb.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"  saved -> {path}")

    print("\n=== ALL DONE ===")
    print(f"Tables written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
