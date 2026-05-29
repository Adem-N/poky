"""
API publique du Tier 1 — `pro_preflop_strategy`.

Étant donné une Observation préflop, retourne la distribution d'actions
recommandée par les ranges expertes, OU None si la situation n'est pas
couverte (auquel cas le caller bascule sur Tier 2).

Le résultat est une List[Tuple[Action, freq]] qu'on peut :
  - sampler aléatoirement pour jouer (Tier 1 pur)
  - utiliser comme warm-start pour MCCFR (Tier 3)
  - moduler par Tier 5 (adaptive)
"""
from typing import List, Optional, Tuple

from poky.abstraction.preflop import canonical_class
from poky.engine import Action, Observation
from poky.expert.context import detect_context
from poky.expert.preflop_ranges import get_book, literal_action


def pro_preflop_strategy(obs: Observation) -> Optional[List[Tuple[Action, float]]]:
    """Stratégie préflop GTO de référence pour cette observation.

    Retourne :
      - List[(Action, freq)] avec sum(freq) ≈ 1.0, frequencies > 0
      - None si : pas en préflop, table non supportée, scenario non couvert,
        sizing exotique, etc.

    Le caller doit toujours vérifier que l'action retournée est dans
    obs.legal_actions et fallback si nécessaire (utiliser _safe ou
    équivalent).
    """
    ctx = detect_context(obs)
    if ctx is None:
        return None
    table_size, scenario_key, _hero_pos = ctx

    book = get_book()
    scenario = book.get(table_size, scenario_key)
    if scenario is None:
        return None

    if len(obs.hole_cards) != 2:
        return None
    class_id = canonical_class(obs.hole_cards[0], obs.hole_cards[1])

    freq_dict = scenario.strategy_for_class(class_id)
    # Convertit les action strings en Action enum, filtre les freq = 0
    out: List[Tuple[Action, float]] = []
    for action_str, f in freq_dict.items():
        if f <= 0:
            continue
        action = literal_action(action_str, scenario.raise_action)
        out.append((action, f))

    if not out:
        return None
    return out


def sample_action(strategy: List[Tuple[Action, float]], rng) -> Action:
    """Tire une action selon les fréquences. rng doit avoir .random().

    Si la somme des freq != 1, renormalise. Robuste aux float-erreurs.
    """
    total = sum(f for _, f in strategy)
    if total <= 0:
        # Ne devrait pas arriver — fallback FOLD
        return Action.FOLD
    r = rng.random() * total
    acc = 0.0
    for action, f in strategy:
        acc += f
        if r <= acc:
            return action
    return strategy[-1][0]
