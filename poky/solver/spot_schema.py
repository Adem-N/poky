"""Dataclasses for TexasSolver spot inputs and parsed outputs.

`SpotKey` is the canonical, hashable cache key — two queries with the same
key MUST produce the same `SpotSolution` (modulo CFR variance).

`SpotSolution` holds the parsed GTO strategy at the root decision node,
plus metadata needed to judge cache freshness/quality.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

# Action label prefixes used by TexasSolver in the JSON output.
SOLVER_ACTION_LABELS = ("CHECK", "CALL", "FOLD", "BET", "RAISE", "ALLIN")


@dataclass(frozen=True)
class SpotKey:
    """Cache key for one postflop spot.

    Designed so that two semantically-identical spots produce identical
    (and hashable) keys. Board cards are stored sorted within each street
    contribution to neutralize permutation noise — except the river card
    which is order-sensitive (turn before river).

    Fields use only primitive types for safe SQLite roundtrip.
    """

    street: str                          # "flop" | "turn" | "river"
    board: Tuple[str, ...]               # e.g. ("Ah", "Kh", "7d") — canonical order
    pot_chips: int                       # solver-side pot before hero's first action
    effective_stack: int                 # smaller of the two stacks
    ip_range: str                        # poker-shorthand string, e.g. "AKs,KQs"
    oop_range: str                       # poker-shorthand string
    # Bet/raise menu (compact tuple to keep equality stable across runs).
    # Each entry: (position, street, role, pct) e.g. ("ip", "flop", "bet", 50)
    bet_menu: Tuple[Tuple[str, str, str, int], ...] = field(default_factory=tuple)
    allin_threshold: float = 0.67        # SPR below which only jam sizing is offered

    def __post_init__(self):
        if self.street not in ("flop", "turn", "river"):
            raise ValueError(f"invalid street: {self.street}")
        expected_len = {"flop": 3, "turn": 4, "river": 5}[self.street]
        if len(self.board) != expected_len:
            raise ValueError(
                f"{self.street} expects {expected_len} board cards, got {len(self.board)}"
            )
        for c in self.board:
            if len(c) != 2 or c[0] not in "23456789TJQKA" or c[1] not in "shdc":
                raise ValueError(f"invalid card: {c!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    def canonical_json(self) -> str:
        """Stable JSON form for hashing — sorted keys, no whitespace."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    def hash_key(self) -> str:
        """Stable SHA256 used as the SQLite primary key."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass
class SpotSolution:
    """Parsed root-level GTO strategy for a SpotKey.

    `root_strategy` maps each combo string the solver reported (e.g. "AhKh")
    to a list of (action_label, probability) pairs whose probs sum to ~1.
    Combos missing from the source range are absent from the dict.

    `aggregated_strategy` is the same averaged across all combos in the
    hero range — useful for the "facing this spot, on average we ..." view.

    `raw_path` is the on-disk JSON path, kept around in case we need to
    re-parse with finer detail later.
    """

    spot_key: SpotKey
    player_at_root: int                                  # 0 = OOP, 1 = IP
    root_actions: List[str]                              # e.g. ["CHECK", "BET 3.000000"]
    root_strategy: Dict[str, List[float]]                # combo -> list aligned with root_actions
    aggregated_strategy: List[Tuple[str, float]]         # [(action, avg_prob), ...]
    iterations: int = 0
    exploitability: Optional[float] = None
    solved_at: str = ""                                  # ISO-8601 UTC
    elapsed_sec: float = 0.0
    solver_version: str = ""
    raw_path: str = ""                                   # absolute path or "" if discarded

    def to_dict(self) -> dict:
        return {
            "spot_key": self.spot_key.to_dict(),
            "player_at_root": self.player_at_root,
            "root_actions": self.root_actions,
            "root_strategy": self.root_strategy,
            "aggregated_strategy": [list(p) for p in self.aggregated_strategy],
            "iterations": self.iterations,
            "exploitability": self.exploitability,
            "solved_at": self.solved_at,
            "elapsed_sec": self.elapsed_sec,
            "solver_version": self.solver_version,
            "raw_path": self.raw_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpotSolution":
        sk_dict = dict(d["spot_key"])
        sk_dict["board"] = tuple(sk_dict["board"])
        sk_dict["bet_menu"] = tuple(tuple(e) for e in sk_dict.get("bet_menu", ()))
        spot_key = SpotKey(**sk_dict)
        return cls(
            spot_key=spot_key,
            player_at_root=d["player_at_root"],
            root_actions=list(d["root_actions"]),
            root_strategy={k: list(v) for k, v in d["root_strategy"].items()},
            aggregated_strategy=[tuple(p) for p in d["aggregated_strategy"]],
            iterations=d.get("iterations", 0),
            exploitability=d.get("exploitability"),
            solved_at=d.get("solved_at", ""),
            elapsed_sec=d.get("elapsed_sec", 0.0),
            solver_version=d.get("solver_version", ""),
            raw_path=d.get("raw_path", ""),
        )
