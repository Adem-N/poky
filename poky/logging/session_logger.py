"""
Logger structuré pour les sessions de jeu (humain vs bot, bot vs bot, etc.).

Chaque session a un répertoire data/sessions/{session_id}/ contenant :
  - meta.json       : config de la session (joueurs, seed, etc.)
  - hand_{n}.json   : 1 fichier par main, format ci-dessous
  - summary.json    : agrégats à la fin

Format hand_{n}.json :
{
  "hand_id": 42,
  "seed": 1042,
  "dealer_id": 1,
  "starting_stacks": [100, 100, 100],
  "holes": {"0": ["HK","SQ"], "1": [...], "2": [...]},
  "actions": [
    {"stage": "PREFLOP", "actor": 1, "action": "RAISE_POT",
     "pot_before": 3, "to_call_before": 2,
     "all_committed_before": [2, 0, 1], "is_critical": false},
    ...
  ],
  "boards": {"flop": ["DT","C7","H2"], "turn": ["S5"], "river": ["DA"]},
  "final_status": ["ALIVE", "ALIVE", "FOLDED"],
  "payoffs": [5.0, -3.0, -2.0]
}

Le flag "is_critical" est positionné par les Players qui implémentent une
détection de spot intéressant (cf. ProClaude). Ça permet à l'analyser
de remonter facilement les décisions à reviewer humainement.
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HandRecord:
    hand_id: int
    seed: int
    dealer_id: int
    starting_stacks: List[int]
    holes: Dict[int, List[str]]
    actions: List[Dict[str, Any]] = field(default_factory=list)
    boards: Dict[str, List[str]] = field(default_factory=dict)
    final_status: List[str] = field(default_factory=list)
    payoffs: List[float] = field(default_factory=list)

    def add_action(self, stage: str, actor: int, action: str,
                   pot_before: int, to_call_before: int,
                   all_committed_before: List[int],
                   is_critical: bool = False,
                   note: Optional[str] = None):
        entry = {
            "stage": stage,
            "actor": actor,
            "action": action,
            "pot_before": pot_before,
            "to_call_before": to_call_before,
            "all_committed_before": list(all_committed_before),
            "is_critical": is_critical,
        }
        if note:
            entry["note"] = note
        self.actions.append(entry)


class SessionLogger:
    """Gère le répertoire d'une session et écrit les hands au fur et à mesure."""

    def __init__(self, session_name: Optional[str] = None,
                 root_dir: str = "data/sessions"):
        if session_name is None:
            session_name = time.strftime("%Y%m%d_%H%M%S")
        self.session_name = session_name
        self.dir = os.path.join(root_dir, session_name)
        os.makedirs(self.dir, exist_ok=True)
        self.hand_counter = 0

    def write_meta(self, meta: Dict[str, Any]):
        with open(os.path.join(self.dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def write_hand(self, record: HandRecord):
        path = os.path.join(self.dir, f"hand_{record.hand_id:05d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.__dict__, f, ensure_ascii=False, indent=2,
                      default=str)
        self.hand_counter = max(self.hand_counter, record.hand_id + 1)

    def write_summary(self, summary: Dict[str, Any]):
        with open(os.path.join(self.dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2,
                      default=str)
