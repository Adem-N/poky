"""Invokes the TexasSolver console binary and parses its JSON output.

Public API: `solve_spot(spot_key, ...)` returns a `SpotSolution`.

Internal layout:
  1. Build the DSL input file from SpotKey (no Python-side validation —
     trust SpotKey.__post_init__ to have validated)
  2. Write input + run binary in a per-call subdir under TMPDIR (parallel-safe)
  3. Parse JSON, walk to the root action_node, extract strategy
  4. Aggregate combo-level probabilities into per-action averages
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

from poky.solver.spot_schema import SpotKey, SpotSolution

DEFAULT_SOLVER_DIR = Path(__file__).resolve().parents[2] / "external" / "TexasSolver" / "TexasSolver-v0.2.0-Windows"
SOLVER_VERSION = "TexasSolver-v0.2.0"


class SolverError(Exception):
    """Raised when the solver binary fails or produces an unparseable output."""


def _format_input_dsl(spot: SpotKey, max_iter: int, accuracy: float, threads: int, output_filename: str) -> str:
    """Render the SpotKey into the solver's mini-DSL."""
    lines = [
        f"set_pot {spot.pot_chips}",
        f"set_effective_stack {spot.effective_stack}",
        f"set_board {','.join(spot.board)}",
        f"set_range_ip {spot.ip_range}",
        f"set_range_oop {spot.oop_range}",
    ]
    bet_menu = spot.bet_menu or _default_bet_menu()
    for pos, street, role, pct in bet_menu:
        lines.append(f"set_bet_sizes {pos},{street},{role},{pct}")
    lines.extend([
        f"set_allin_threshold {spot.allin_threshold}",
        "build_tree",
        f"set_thread_num {threads}",
        f"set_accuracy {accuracy}",
        f"set_max_iteration {max_iter}",
        "set_print_interval 10",
        "set_use_isomorphism 1",
        "start_solve",
        # dump_rounds=1 dumps flop strategies; raise to 2 for +turn if needed.
        "set_dump_rounds 1",
        f"dump_result {output_filename}",
    ])
    return "\n".join(lines) + "\n"


def _default_bet_menu() -> Tuple[Tuple[str, str, str, int], ...]:
    """Conservative default — 50% pot bets/raises everywhere, 60% raises.

    Matches sample_input.txt structure; v0.2.0 doesn't accept multi-size
    menus on a single line, so each role gets one canonical size.
    """
    out = []
    for pos in ("oop", "ip"):
        for street in ("flop", "turn", "river"):
            out.append((pos, street, "bet", 50))
            out.append((pos, street, "raise", 60))
    # OOP river donk option (sample-style).
    out.append(("oop", "river", "donk", 50))
    return tuple(out)


def _find_root_action_node(node: dict) -> Optional[dict]:
    """Descend the tree to the first action_node (skip chance_nodes)."""
    while node is not None:
        node_type = node.get("node_type")
        if node_type == "action_node":
            return node
        if "childrens" in node and node["childrens"]:
            node = next(iter(node["childrens"].values()))
        else:
            return None
    return None


def _aggregate(strategy: dict) -> Tuple[list, list]:
    """Return (root_actions, [(action, avg_prob), ...]).

    `strategy` is the inner dict: {"actions": [...], "strategy": {combo: [probs...]}}.
    """
    actions = list(strategy.get("actions", []))
    per_combo = strategy.get("strategy", {})
    if not actions or not per_combo:
        return actions, []
    avg = [0.0] * len(actions)
    for _, probs in per_combo.items():
        for i, p in enumerate(probs):
            avg[i] += float(p)
    n = len(per_combo)
    avg = [a / n for a in avg]
    return actions, list(zip(actions, avg))


def solve_spot(
    spot: SpotKey,
    *,
    max_iter: int = 200,
    accuracy: float = 0.5,
    threads: int = 6,
    solver_dir: Optional[Path] = None,
    keep_raw: bool = False,
    raw_dir: Optional[Path] = None,
    timeout_sec: int = 600,
) -> SpotSolution:
    """Solve one spot and return the parsed strategy at the root decision.

    `keep_raw`: if True, copy the solver's output_result.json to `raw_dir`
    and store its path in the returned SpotSolution.raw_path. Useful for
    deeper postflop analysis later. If False, the file is discarded.
    """
    solver_dir = solver_dir or DEFAULT_SOLVER_DIR
    solver_exe = solver_dir / "console_solver.exe"
    if not solver_exe.exists():
        raise SolverError(f"console_solver.exe not found at {solver_exe}")

    # Per-call subdir keeps parallel solves from clobbering each other's IO.
    # The binary writes dump_result relative to cwd, so we set cwd=tmpdir
    # AND symlink/copy the required resource dirs in. Simpler: keep cwd as
    # solver_dir (so resources/ ranges/ are reachable) and use unique
    # input/output filenames per call.
    stamp = f"{int(time.time()*1000)}_{os.getpid()}_{spot.hash_key()[:8]}"
    input_filename = f"_runner_in_{stamp}.txt"
    output_filename = f"_runner_out_{stamp}.json"
    input_path = solver_dir / input_filename
    output_path = solver_dir / output_filename

    try:
        input_path.write_text(
            _format_input_dsl(spot, max_iter, accuracy, threads, output_filename),
            encoding="utf-8",
        )

        t0 = time.time()
        try:
            result = subprocess.run(
                [str(solver_exe), "-i", input_filename],
                cwd=str(solver_dir),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as e:
            raise SolverError(f"solver timeout after {timeout_sec}s") from e
        elapsed = time.time() - t0

        if result.returncode != 0:
            tail = (result.stderr or "")[-400:]
            raise SolverError(
                f"solver exit={result.returncode}; stderr tail: {tail!r}"
            )
        if not output_path.exists():
            raise SolverError(f"solver produced no output file at {output_path}")
        if output_path.stat().st_size < 16:
            raise SolverError(
                f"solver output too small ({output_path.stat().st_size} bytes) — "
                f"likely empty tree (try set_dump_rounds >= 1)"
            )

        with output_path.open(encoding="utf-8") as f:
            data = json.load(f)
        root = _find_root_action_node(data)
        if root is None:
            raise SolverError("no action_node found in solver output tree")
        root_strategy_block = root.get("strategy") or {}
        root_actions, aggregated = _aggregate(root_strategy_block)
        raw_combos = root_strategy_block.get("strategy", {})

        # Exploitability is buried in solver stdout, not the JSON dump —
        # parse the last "Total exploitability X precent" line if present.
        exploitability = None
        for line in (result.stdout or "").splitlines()[::-1]:
            if "Total exploitability" in line:
                try:
                    parts = line.split()
                    # Format: "Total exploitability 0.5137036 precent"
                    exploitability = float(parts[2])
                except (ValueError, IndexError):
                    pass
                break

        # Extract iteration count too (last "Iter: N" line).
        iters = 0
        for line in (result.stdout or "").splitlines()[::-1]:
            if line.startswith("Iter:"):
                try:
                    iters = int(line.split()[1])
                except (ValueError, IndexError):
                    pass
                break

        raw_path_str = ""
        if keep_raw and raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            dest = raw_dir / f"{spot.hash_key()}.json"
            output_path.replace(dest)
            raw_path_str = str(dest)

        return SpotSolution(
            spot_key=spot,
            player_at_root=int(root.get("player", -1)),
            root_actions=root_actions,
            root_strategy={k: list(map(float, v)) for k, v in raw_combos.items()},
            aggregated_strategy=aggregated,
            iterations=iters,
            exploitability=exploitability,
            solved_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            elapsed_sec=elapsed,
            solver_version=SOLVER_VERSION,
            raw_path=raw_path_str,
        )

    finally:
        # Cleanup temp files (output is moved on keep_raw=True; otherwise delete).
        if input_path.exists():
            input_path.unlink(missing_ok=True)
        if output_path.exists() and not (keep_raw and raw_dir is not None):
            output_path.unlink(missing_ok=True)
