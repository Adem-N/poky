"""Loader and lookup for precomputed Nitro 3-max stack-depth ranges.

Ranges are stored as JSON under `data/expert_ranges/3max_nitro/*.json`,
one file per stack depth (e.g. `3max_nitro_15bb.json`, `3max_nitro_10bb.json`).

Each file contains the Nash push/fold strategy per position:
  {
    "stack_bb": 15,
    "scenarios": {
      "rfi:BTN":      {"AA": [...], "KK": [...], ...},
      "vs_btn_push:SB": {...},
      ...
    }
  }

PLACEHOLDER — populated once `PushFoldSolver` (N1) is implemented.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

RANGES_DIR = Path(__file__).resolve().parents[2] / "data" / "expert_ranges" / "3max_nitro"


def load_range_for_stack(stack_bb: int) -> Optional[Dict]:
    """Load the precomputed Nash strategy for the closest stack depth."""
    path = RANGES_DIR / f"3max_nitro_{stack_bb}bb.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)
