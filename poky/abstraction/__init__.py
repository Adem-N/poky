"""
Card abstractions pour Poker AI.

Préflop : 169 classes canoniques (13 pairs + 78 suited + 78 offsuit).
Postflop : k-means buckets sur equity histograms (à venir).

Référence : Johanson et al. 2013, "Evaluating State-Space Abstractions in
Extensive-Form Games".
"""
from poky.abstraction.preflop import (
    canonical_class,
    class_name,
    class_in_top_pct,
    top_pct_classes,
    all_classes_sorted,
    NUM_PREFLOP_CLASSES,
)
from poky.abstraction.postflop import (
    flop_bucket,
    turn_bucket,
    river_bucket,
    postflop_bucket,
    get_boundaries,
    NUM_BUCKETS as NUM_POSTFLOP_BUCKETS,
)

__all__ = [
    # preflop
    "canonical_class",
    "class_name",
    "class_in_top_pct",
    "top_pct_classes",
    "all_classes_sorted",
    "NUM_PREFLOP_CLASSES",
    # postflop
    "flop_bucket",
    "turn_bucket",
    "river_bucket",
    "postflop_bucket",
    "get_boundaries",
    "NUM_POSTFLOP_BUCKETS",
]
