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
from poky.abstraction.action_abstraction import (
    ABSTRACT_ACTIONS,
    NUM_ABSTRACT_ACTIONS,
    legal_abstract_actions,
    action_index,
    index_to_action,
)
from poky.abstraction.infoset import (
    encode_history,
    decode_history,
    infoset_key,
    decode_for_debug,
    history_truncated,
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
    # action abstraction
    "ABSTRACT_ACTIONS",
    "NUM_ABSTRACT_ACTIONS",
    "legal_abstract_actions",
    "action_index",
    "index_to_action",
    # infoset
    "encode_history",
    "decode_history",
    "infoset_key",
    "decode_for_debug",
    "history_truncated",
]
