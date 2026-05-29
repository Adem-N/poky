"""
Tier 1 — knowledge base : ranges GTO préflop publiées comme RÉFÉRENCE.

Le bot consulte ces ranges comme un livre de théorie : la stratégie par
défaut quand on ne sait rien d'autre. Le Tier 3 (MCCFR) peut dévier
librement, et le Tier 5 (adaptive) module selon le profil adverse.

Architecture :
  poky/expert/
    hand_patterns.py    # parse "22+", "A2s+", "76s-54s" -> set de class_ids
    preflop_ranges.py   # loader des JSON publiés
    context.py          # déduit la situation préflop depuis Observation
    range_lookup.py     # API publique pro_preflop_strategy(...)

Les charts sont externes (data/expert_ranges/*.json) pour pouvoir être
mises à jour / régénérées sans toucher au code.
"""
from poky.expert.range_lookup import pro_preflop_strategy

__all__ = ["pro_preflop_strategy"]
