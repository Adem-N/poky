"""Phase Z2 batch — solve a list of SpotKeys and persist them to SQLite.

Resumable: skips keys already in the DB. Sequential for the MVP (parallelism
can be added later by spawning N copies of the binary, each in its own
subdir).

Initial spot list is a tiny representative HU-postflop set so we can
validate the end-to-end pipeline (generate → solve → cache → query) before
investing in the full 5000-spot batch.

Usage:
    python scripts/build_cache.py
    python scripts/build_cache.py --db path/to/custom.sqlite --max-iter 200
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# scripts/ are invoked as plain scripts (sys.path[0] = scripts/), so we
# need to add the repo root for `from poky...` to resolve.
sys.path.insert(0, str(REPO_ROOT))

from poky.solver.cache_db import CacheDB
from poky.solver.solver_runner import SolverError, solve_spot
from poky.solver.spot_schema import SpotKey
DEFAULT_DB_PATH = REPO_ROOT / "data" / "solver_cache" / "hu_flop.sqlite"


# Tiny representative HU SRP flop set. Keep ranges minimal (small combos)
# while we validate the pipeline — Z3 expansion will use real ranges.
# (BTN open vs BB defend, 100bb, 2.5bb open ≈ pot=6 chips, stack 97 left)
SPOTS: list[SpotKey] = [
    SpotKey(
        street="flop",
        board=("Ah", "Kh", "7d"),
        pot_chips=6,
        effective_stack=97,
        ip_range="AKs,KQs,QQ,JJ",
        oop_range="QQ,JTs,99,88",
    ),
    SpotKey(
        street="flop",
        board=("8d", "7c", "2s"),
        pot_chips=6,
        effective_stack=97,
        ip_range="AKs,AA,KK,QQ",
        oop_range="88,77,T9s,JTs",
    ),
    SpotKey(
        street="flop",
        board=("Qs", "8d", "7h"),
        pot_chips=6,
        effective_stack=97,
        ip_range="QJs,AKs,KQs,JJ",
        oop_range="99,T9s,87s,88",
    ),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--max-iter", type=int, default=100,
                    help="CFR iteration cap per spot (60-200 = 15s-1min/spot tiny ranges)")
    ap.add_argument("--accuracy", type=float, default=1.0,
                    help="solver target exploitability (%% of pot)")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--rebuild", action="store_true",
                    help="re-solve all spots even if already cached")
    args = ap.parse_args()

    db = CacheDB(args.db)
    print(f"=== build_cache | db={args.db} | spots={len(SPOTS)} ===")
    existing = sum(1 for s in SPOTS if db.exists(s))
    print(f"already cached: {existing}/{len(SPOTS)}  (rebuild={args.rebuild})")

    solved = 0
    failed = 0
    skipped = 0
    t0 = time.time()
    for i, spot in enumerate(SPOTS):
        if not args.rebuild and db.exists(spot):
            skipped += 1
            print(f"  [{i+1}/{len(SPOTS)}] SKIP (cached) board={','.join(spot.board)}")
            continue
        print(f"  [{i+1}/{len(SPOTS)}] solving board={','.join(spot.board)} "
              f"pot={spot.pot_chips} stack={spot.effective_stack}...")
        try:
            sol = solve_spot(spot, max_iter=args.max_iter, accuracy=args.accuracy,
                             threads=args.threads)
        except SolverError as e:
            failed += 1
            print(f"      FAILED: {e}")
            continue
        db.put(sol)
        solved += 1
        print(f"      OK ({sol.elapsed_sec:.1f}s, {sol.iterations} iters, "
              f"exploit={sol.exploitability})  player_at_root={sol.player_at_root}  "
              f"actions={sol.root_actions}")

    elapsed = time.time() - t0
    stats = db.stats()
    print(f"\n=== done ===")
    print(f"solved this run : {solved}")
    print(f"skipped (cached): {skipped}")
    print(f"failed          : {failed}")
    print(f"wall time       : {elapsed:.1f}s")
    print(f"\ncache stats:")
    for k, v in stats.items():
        print(f"  {k:20s}: {v}")
    db.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
