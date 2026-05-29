"""Loader for precomputed Nitro 3-max push/fold strategy tables.

Tables are produced by `scripts/build_pushfold_tables.py` and stored as
JSON under `data/expert_ranges/3max_nitro/3max_nitro_{N}bb.json` for
stack depths N in {6, 8, 10, 12, 15} (configurable).

Each file structure:
  {
    "stack_bb": 15,
    "sb_bb": 0.5,
    "bb_bb": 1.0,
    "iterations": 60,
    "solver_version": "PushFoldSolver-v0.1",
    "aggregate_frequencies": {
      "btn_push": 0.42,
      ...
    },
    "strategies": {
      "btn_push":              {"AA": 1.0, "AKs": 1.0, ..., "32o": 0.0},
      "sb_call_vs_btn":        {...},
      "sb_push_after_btn_fold":{...},
      "bb_call_3way":          {...},
      "bb_call_vs_btn":        {...},
      "bb_call_vs_sb":         {...}
    }
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RANGES_DIR = Path(__file__).resolve().parents[2] / "data" / "expert_ranges" / "3max_nitro"

_LOADED: Dict[int, Dict] = {}


def available_stacks() -> List[int]:
    """List of stack depths (in BB) that have a cached table on disk."""
    if not RANGES_DIR.exists():
        return []
    stacks = []
    for p in sorted(RANGES_DIR.glob("3max_nitro_*bb.json")):
        name = p.stem  # e.g. "3max_nitro_15bb"
        try:
            stack = int(name.split("_")[2].replace("bb", ""))
            stacks.append(stack)
        except (ValueError, IndexError):
            continue
    return sorted(stacks)


def load_table(stack_bb: int) -> Optional[Dict]:
    """Load the table for a specific stack depth. Memoized."""
    if stack_bb in _LOADED:
        return _LOADED[stack_bb]
    path = RANGES_DIR / f"3max_nitro_{stack_bb}bb.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    _LOADED[stack_bb] = data
    return data


def closest_stack(stack_bb: float) -> Optional[int]:
    """Return the closest available stack depth on disk (or None if no tables)."""
    avail = available_stacks()
    if not avail:
        return None
    return min(avail, key=lambda s: abs(s - stack_bb))


def get_strategy(stack_bb: float, scenario: str, hand_name: str) -> Optional[float]:
    """Lookup: at this stack depth, what's the frequency of the aggressive
    action (push/call) in this scenario for this hand?

    Args:
        stack_bb: effective stack at decision time
        scenario: one of {"btn_push", "sb_call_vs_btn", "sb_push_after_btn_fold",
                          "bb_call_3way", "bb_call_vs_btn", "bb_call_vs_sb"}
        hand_name: e.g. "AA", "AKs", "76o"

    Returns:
        Float in [0, 1], or None if no table available for this stack depth.
    """
    target = closest_stack(stack_bb)
    if target is None:
        return None
    table = load_table(target)
    if table is None:
        return None
    scenario_strats = table["strategies"].get(scenario, {})
    return scenario_strats.get(hand_name)
