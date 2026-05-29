"""Phase Z1 smoke — verify TexasSolver console binary produces parseable GTO.

Solves 3 simple HU postflop spots and prints the action distribution for
hero's first decision, to confirm the I/O pipeline end-to-end before Z2.

Usage:
    python scripts/solver_smoke.py
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOLVER_DIR = REPO_ROOT / "external" / "TexasSolver" / "TexasSolver-v0.2.0-Windows"
SOLVER_EXE = SOLVER_DIR / "console_solver.exe"


# Three representative HU postflop spots — small ranges so each solves in ~30-60s.
# Note: TexasSolver v0.2.0 range parser is finicky. For smoke we use small
# explicit-combo ranges (mirroring `resources/text/commandline_sample_input.txt`).
# Real-world ranges with `X+` syntax need verification — see Z2 for full
# range expansion.
SPOTS = [
    {
        "name": "Toy IP=AKs,KQs vs OOP=QQ,JTs on AhKh7d",
        "pot": 6,
        "stack": 97,
        "board": "Ah,Kh,7d",
        "range_ip": "AKs,KQs",
        "range_oop": "QQ,JTs",
    },
    {
        "name": "Toy IP=AhKh,AhAd vs OOP=8c8d on 8d7c2s (set vs overpair)",
        "pot": 6,
        "stack": 97,
        "board": "8d,7c,2s",
        "range_ip": "AKs,AA",
        "range_oop": "88",
    },
    {
        "name": "Toy IP=QJs,AhKh vs OOP=99,T9s on Qs8d7h",
        "pot": 6,
        "stack": 97,
        "board": "Qs,8d,7h",
        "range_ip": "QJs,AKs",
        "range_oop": "99,T9s",
    },
]


def write_input_file(spot, output_json_path):
    """Build the TexasSolver DSL input for a single spot."""
    lines = [
        f"set_pot {spot['pot']}",
        f"set_effective_stack {spot['stack']}",
        f"set_board {spot['board']}",
        f"set_range_ip {spot['range_ip']}",
        f"set_range_oop {spot['range_oop']}",
        # Bet/raise menu: single size per role per street (v0.2.0 sample format).
        "set_bet_sizes oop,flop,bet,50",
        "set_bet_sizes oop,flop,raise,60",
        "set_bet_sizes ip,flop,bet,50",
        "set_bet_sizes ip,flop,raise,60",
        "set_bet_sizes oop,turn,bet,75",
        "set_bet_sizes oop,turn,raise,60",
        "set_bet_sizes ip,turn,bet,75",
        "set_bet_sizes ip,turn,raise,60",
        "set_bet_sizes oop,river,bet,75",
        "set_bet_sizes oop,river,donk,50",
        "set_bet_sizes oop,river,raise,60",
        "set_bet_sizes ip,river,bet,75",
        "set_bet_sizes ip,river,raise,60",
        "set_allin_threshold 0.67",
        "build_tree",
        "set_thread_num 6",
        "set_accuracy 1.0",
        "set_max_iteration 80",
        "set_print_interval 20",
        "set_use_isomorphism 1",
        "start_solve",
        # dump_rounds: 0=root only (often empty), 1=flop strategies, 2=+turn/river
        "set_dump_rounds 1",
        f"dump_result {output_json_path}",
    ]
    return "\n".join(lines) + "\n"


def parse_root_strategy(result):
    """Pull the root action distribution for IP/OOP — first action_node from JSON."""
    node = result
    while node.get("node_type") != "action_node":
        # Descend through chance_nodes (shouldn't happen at root for flop).
        if "childrens" in node and node["childrens"]:
            node = next(iter(node["childrens"].values()))
        else:
            return None
    return node.get("strategy"), node.get("player")


def summarize_strategy(strategy):
    """Aggregate per-combo strategy into average action frequencies."""
    actions = strategy["actions"]
    per_combo = strategy["strategy"]
    n = len(per_combo)
    if n == 0:
        return None
    avg = [0.0] * len(actions)
    for combo, probs in per_combo.items():
        for i, p in enumerate(probs):
            avg[i] += p
    avg = [a / n for a in avg]
    return list(zip(actions, avg))


def run_spot(spot, idx):
    print(f"\n===== Spot {idx+1}: {spot['name']} =====")
    print(f"  pot={spot['pot']}  stack={spot['stack']}  board={spot['board']}")

    if not SOLVER_EXE.exists():
        print(f"  ERROR: solver binary not found at {SOLVER_EXE}", file=sys.stderr)
        return False

    # Solver dumps relative to its cwd; use a temp filename to avoid collisions.
    out_name = f"smoke_spot_{idx}_{int(time.time())}.json"
    out_path = SOLVER_DIR / out_name

    input_dsl = write_input_file(spot, out_name)
    input_file = SOLVER_DIR / f"smoke_spot_{idx}.txt"
    input_file.write_text(input_dsl, encoding="utf-8")

    print(f"  solving (max 80 iters, target accuracy 1.0)...")
    t0 = time.time()
    # Run from solver dir so it finds resources/. Suppress its huge progress
    # output (lots of \r-based bars) but capture exit code.
    try:
        result = subprocess.run(
            [str(SOLVER_EXE), "-i", input_file.name],
            cwd=str(SOLVER_DIR),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 600s")
        return False
    elapsed = time.time() - t0
    print(f"  solver exit={result.returncode}  elapsed={elapsed:.1f}s")
    if result.returncode != 0:
        print(f"  STDERR (tail): {result.stderr[-500:]}")
        return False

    if not out_path.exists():
        print(f"  ERROR: output file {out_path} not produced")
        return False

    size_kb = out_path.stat().st_size / 1024
    print(f"  output JSON: {size_kb:.1f} KB")

    with out_path.open(encoding="utf-8") as f:
        data = json.load(f)

    root_strategy, player = parse_root_strategy(data)
    if root_strategy is None:
        print(f"  ERROR: no action_node at root")
        return False
    summary = summarize_strategy(root_strategy)
    pos = "OOP (BB)" if player == 0 else "IP (BTN)"
    print(f"  first decision: player={player} ({pos})")
    print(f"  average action frequencies across hero range:")
    for action, freq in summary:
        bar = "#" * int(freq * 40)
        print(f"    {action:20s} {freq*100:5.1f}%  {bar}")

    # Cleanup
    input_file.unlink(missing_ok=True)
    out_path.unlink(missing_ok=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None, help="run only spot N (0-based)")
    args = ap.parse_args()

    if not SOLVER_EXE.exists():
        print(f"FATAL: {SOLVER_EXE} not found.")
        print(f"Run the TexasSolver download (see docs/TEXASSOLVER_FORMAT.md).")
        sys.exit(1)

    spots = SPOTS if args.only is None else [SPOTS[args.only]]
    passes = 0
    for i, spot in enumerate(spots):
        idx = i if args.only is None else args.only
        if run_spot(spot, idx):
            passes += 1
    print(f"\n=== {passes}/{len(spots)} spots solved successfully ===")
    sys.exit(0 if passes == len(spots) else 1)


if __name__ == "__main__":
    main()
