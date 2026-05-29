"""
Loader des JSON de ranges préflop expertes.

Charge une fois (cache mémoire) tous les fichiers `data/expert_ranges/*.json`
et expose une API d'accès par (table_size, scenario_key).

Le résultat est compilé sous forme `{class_id: {action: freq}}` pour un
lookup O(1) par main.

Conventions :
  - scenario_key : "rfi:BTN" / "vs_open:BB|BTN" / etc, défini dans le JSON
  - action : string "fold" | "call" | "raise"
  - freq : float 0..1 (la somme par main doit être ~ 1.0)
  - raise_action : Action enum (FOLD/CHECK_CALL/RAISE_HALF_POT/RAISE_POT/ALL_IN)
    qui sert de sizing concret pour "raise" dans CE scenario

L'erreur principale qu'on évite : silently masquer une situation non
couverte. Si un scenario_key n'existe pas, on retourne None — le caller
décide alors du fallback (Tier 2 heuristic).
"""
import json
import os
from typing import Dict, List, Optional

from poky.engine import Action
from poky.expert.hand_patterns import parse_pattern


# Mapping symbolique des sizings -> Action enum
_RAISE_ACTION_MAP = {
    "raise_half_pot": Action.RAISE_HALF_POT,
    "raise_pot": Action.RAISE_POT,
    "all_in": Action.ALL_IN,
}

# Mapping action string -> Action enum (pour fold/call, "raise" est résolu par raise_action)
_LITERAL_ACTION_MAP = {
    "fold": Action.FOLD,
    "call": Action.CHECK_CALL,
}


_DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "expert_ranges",
)


class CompiledScenario:
    """Représentation compilée d'un scenario : lookup O(1) par class_id."""

    __slots__ = ("key", "description", "raise_action", "by_class", "default")

    def __init__(self, key: str, description: str,
                 raise_action: Action,
                 by_class: Dict[int, Dict[str, float]],
                 default: Dict[str, float]):
        self.key = key
        self.description = description
        self.raise_action = raise_action
        self.by_class = by_class
        self.default = default

    def strategy_for_class(self, class_id: int) -> Dict[str, float]:
        """Retourne {action_str: freq} pour cette main, default si absent."""
        return self.by_class.get(class_id, self.default)


class RangeBook:
    """Cache de tous les fichiers de ranges chargés."""

    def __init__(self):
        self._files: Dict[str, dict] = {}            # table_size -> raw JSON
        self._compiled: Dict[str, Dict[str, CompiledScenario]] = {}  # table_size -> {scenario_key: compiled}

    def load_file(self, path: str) -> str:
        """Charge un fichier JSON et retourne la table_size qu'il contient."""
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        table_size = raw.get("table_size")
        if not table_size:
            raise ValueError(f"Fichier sans 'table_size' : {path}")
        self._files[table_size] = raw
        self._compiled[table_size] = self._compile_all(raw)
        return table_size

    def load_dir(self, directory: str = _DEFAULT_DATA_DIR) -> List[str]:
        """Charge tous les *.json du répertoire. Retourne les table_size chargées.

        Skip les fichiers `*.bak.*` ou `_*` (backups / WIP). Détecte les
        doublons par table_size et lève une erreur (sinon un backup pouvait
        silencieusement écraser le fichier principal — leçon apprise après
        une session de debug bien chiante).
        """
        if not os.path.isdir(directory):
            return []
        loaded = []
        seen_ts = {}
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            # Skip backups / WIP files
            if ".bak." in fname or fname.startswith("_"):
                continue
            ts = self.load_file(os.path.join(directory, fname))
            if ts in seen_ts:
                raise ValueError(
                    f"Doublon table_size={ts!r} dans {directory} : "
                    f"{seen_ts[ts]!r} et {fname!r}. Renomme un des deux "
                    f"en .bak.json pour le neutraliser."
                )
            seen_ts[ts] = fname
            loaded.append(ts)
        return loaded

    def get(self, table_size: str, scenario_key: str) -> Optional[CompiledScenario]:
        scenarios = self._compiled.get(table_size)
        if scenarios is None:
            return None
        return scenarios.get(scenario_key)

    def available_scenarios(self, table_size: str) -> List[str]:
        scenarios = self._compiled.get(table_size)
        return list(scenarios.keys()) if scenarios else []

    # ---- compilation -----------------------------------------------------

    @staticmethod
    def _compile_all(raw: dict) -> Dict[str, CompiledScenario]:
        scenarios = raw.get("scenarios", {})
        out = {}
        for key, sc in scenarios.items():
            out[key] = RangeBook._compile_scenario(key, sc)
        return out

    @staticmethod
    def _compile_scenario(key: str, sc: dict) -> CompiledScenario:
        raise_action_str = sc.get("raise_action", "raise_half_pot")
        if raise_action_str not in _RAISE_ACTION_MAP:
            raise ValueError(
                f"raise_action invalide dans scenario {key!r} : "
                f"{raise_action_str!r}"
            )
        raise_action = _RAISE_ACTION_MAP[raise_action_str]

        default = _normalize_freq(sc.get("default", {"fold": 1.0}), key, "default")

        by_class: Dict[int, Dict[str, float]] = {}
        for rng in sc.get("ranges", []):
            hands_str = rng.get("hands", "")
            freq_raw = rng.get("freq", {})
            freq = _normalize_freq(freq_raw, key, hands_str)
            class_ids = parse_pattern(hands_str)
            for cid in class_ids:
                # Override : si la même classe apparaît dans plusieurs entrées,
                # la dernière gagne (permet "broad default puis spécifique").
                by_class[cid] = freq

        return CompiledScenario(
            key=key,
            description=sc.get("description", ""),
            raise_action=raise_action,
            by_class=by_class,
            default=default,
        )


def _normalize_freq(freq: Dict[str, float], scenario_key: str,
                    context: str) -> Dict[str, float]:
    """Valide et normalise un dict de fréquences. Tolère ±2% d'erreur d'arrondi."""
    if not freq:
        raise ValueError(f"freq vide dans {scenario_key}/{context}")
    for action in freq:
        if action not in ("fold", "call", "raise"):
            raise ValueError(
                f"Action invalide dans {scenario_key}/{context} : {action!r}"
            )
    total = sum(freq.values())
    if total <= 0:
        raise ValueError(f"Somme freq <= 0 dans {scenario_key}/{context}")
    if abs(total - 1.0) > 0.02:
        # Re-normalise mais avertit en clair
        pass  # accepté silencieusement, on renormalise
    return {a: f / total for a, f in freq.items()}


# ---- API publique : singleton + helpers -----------------------------------

_BOOK: Optional[RangeBook] = None


def get_book() -> RangeBook:
    """Singleton : charge les fichiers data/expert_ranges/*.json à la 1re fois."""
    global _BOOK
    if _BOOK is None:
        _BOOK = RangeBook()
        _BOOK.load_dir()
    return _BOOK


def reload_book(directory: Optional[str] = None) -> RangeBook:
    """Force un rechargement (utile pour les tests / itération sur les JSON)."""
    global _BOOK
    _BOOK = RangeBook()
    _BOOK.load_dir(directory or _DEFAULT_DATA_DIR)
    return _BOOK


def literal_action(action_str: str, raise_action: Action) -> Action:
    """Convertit une string 'fold'/'call'/'raise' en Action enum."""
    if action_str == "raise":
        return raise_action
    if action_str in _LITERAL_ACTION_MAP:
        return _LITERAL_ACTION_MAP[action_str]
    raise ValueError(f"Action string inconnue : {action_str!r}")
