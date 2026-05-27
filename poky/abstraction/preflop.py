"""
169 classes canoniques de mains de départ en NLHE.

Pour les 52 choose 2 = 1326 combinaisons de cartes, il existe seulement
**169 classes stratégiquement distinctes** :
  - 13 pocket pairs  (AA, KK, ..., 22)
  - 78 suited combos (AKs, AQs, ..., 32s)
  - 78 offsuit combos (AKo, AQo, ..., 32o)

Chaque classe a un ID canonique 0..168, **ordonné par équité décroissante**
contre 1 adversaire random heads-up. ID 0 = AA (la meilleure), ID 168 = 32o
(la pire).

Pourquoi 169 et pas 1326 : les "suit isomorphism" (la couleur précise
n'importe pas avant le board). Si tu as As de Pique + Roi de Pique,
stratégiquement c'est équivalent à As de Cœur + Roi de Cœur — c'est juste
"AKs" (Ace-King suited).

Cette abstraction divise le tree de jeu pré-flop par **~8x**, ce qui est
indispensable pour faire converger un CFR sur NLHE.
"""
import json
import os
import random
from typing import List, Tuple

from poky.equity import monte_carlo_equity


NUM_PREFLOP_CLASSES = 169

_RANKS = "23456789TJQKA"
_RANK_TO_INT = {r: i for i, r in enumerate(_RANKS, start=2)}  # 2..14

# Cache disque pour le ranking (~5s à recalculer)
_CACHE_PATH = os.path.join(os.path.dirname(__file__),
                           "_preflop_ranking_cache.json")

# État interne (calculé à la première utilisation, puis caché en mémoire)
_CLASSES: List[Tuple[int, int, bool]] = []   # ordonné par equity décroissante
_CLASS_ID: dict = {}                          # (high, low, suited) -> id


def _generate_all_classes() -> List[Tuple[int, int, bool, str, str]]:
    """Génère les 169 classes avec 2 cartes représentatives chacune.
    Format des cartes : 'HQ' = Dame de Cœur (rlcard convention)."""
    out = []
    for h in range(14, 1, -1):
        for l in range(h, 1, -1):
            if h == l:
                # Pair : 2 suits différents (ex AA = Hearts + Diamonds)
                c1 = "H" + _RANKS[h - 2]
                c2 = "D" + _RANKS[l - 2]
                out.append((h, l, False, c1, c2))
            else:
                # Suited : même suit
                c1_s = "H" + _RANKS[h - 2]
                c2_s = "H" + _RANKS[l - 2]
                out.append((h, l, True, c1_s, c2_s))
                # Offsuit : suits différents
                c1_o = "H" + _RANKS[h - 2]
                c2_o = "D" + _RANKS[l - 2]
                out.append((h, l, False, c1_o, c2_o))
    assert len(out) == NUM_PREFLOP_CLASSES
    return out


def _compute_equity_ranking(simulations: int = 800) -> List[Tuple[int, int, bool]]:
    """Calcule l'équité préflop de chaque classe vs 1 random opponent.
    Retourne les 169 classes ordonnées par équité décroissante."""
    rng = random.Random(42)
    enriched = []
    for h, l, suited, c1, c2 in _generate_all_classes():
        eq = monte_carlo_equity([c1, c2], [], num_opponents=1,
                                simulations=simulations, rng=rng)
        enriched.append((eq, h, l, suited))
    enriched.sort(key=lambda x: -x[0])
    return [(h, l, suited) for _, h, l, suited in enriched]


def _ensure_loaded():
    """Lazy-load : charge depuis le cache disque ou calcule + sauve."""
    global _CLASSES, _CLASS_ID
    if _CLASSES:
        return
    if os.path.exists(_CACHE_PATH):
        with open(_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        _CLASSES = [tuple(c) for c in raw]
    else:
        _CLASSES = _compute_equity_ranking()
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump([list(c) for c in _CLASSES], f, indent=2)
    _CLASS_ID = {c: i for i, c in enumerate(_CLASSES)}


def canonical_class(card1: str, card2: str) -> int:
    """
    Retourne l'ID canonique (0..168) d'une main de départ.
    0 = AA (meilleur), 168 = la pire main (typiquement 32o).
    Format des cartes : 'HQ' = Dame de Cœur (rlcard).
    """
    _ensure_loaded()
    s1, r1 = card1[0], card1[1]
    s2, r2 = card2[0], card2[1]
    v1, v2 = _RANK_TO_INT[r1], _RANK_TO_INT[r2]
    high, low = max(v1, v2), min(v1, v2)
    if high == low:
        key = (high, low, False)        # pair
    else:
        key = (high, low, s1 == s2)     # suited si même suit
    return _CLASS_ID[key]


def class_name(class_id: int) -> str:
    """Nom lisible : 'AA', 'AKs', 'AKo', '22', etc."""
    _ensure_loaded()
    h, l, suited = _CLASSES[class_id]
    rh, rl = _RANKS[h - 2], _RANKS[l - 2]
    if h == l:
        return f"{rh}{rh}"
    return f"{rh}{rl}{'s' if suited else 'o'}"


def class_in_top_pct(class_id: int, pct: float) -> bool:
    """True si la classe fait partie des top pct% des mains préflop.
    Ex : `class_in_top_pct(canonical_class('HA', 'HA'), 0.05)` → True (AA dans top 5%)."""
    threshold = max(1, int(round(NUM_PREFLOP_CLASSES * pct)))
    return class_id < threshold


def top_pct_classes(pct: float) -> List[int]:
    """Liste des IDs de classes dans les top pct% (ordonnés par force)."""
    threshold = max(1, int(round(NUM_PREFLOP_CLASSES * pct)))
    return list(range(threshold))


def all_classes_sorted() -> List[Tuple[int, str]]:
    """Retourne [(id, name)] pour les 169 classes dans l'ordre d'équité."""
    _ensure_loaded()
    return [(i, class_name(i)) for i in range(NUM_PREFLOP_CLASSES)]
