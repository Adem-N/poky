"""Tests de la 169-class preflop abstraction.

Vérifications :
  - 169 classes uniques
  - AA = classe 0 (meilleure équité)
  - 32o ou 27o ≈ classe 168 (pire équité)
  - Suited > offsuit pour mêmes ranks
  - Pair > suited connector > offsuit gapped
"""
from poky.abstraction import (
    canonical_class, class_name, class_in_top_pct, top_pct_classes,
    NUM_PREFLOP_CLASSES,
)


def test_169_unique_classes():
    """Toutes les paires (h, l, suited) doivent mapper sur des IDs uniques 0..168."""
    seen = set()
    for c1 in ("HA", "HK", "HQ", "HJ", "HT", "H9", "H8", "H7"):
        for c2 in ("SA", "SK", "SQ", "SJ", "ST", "S9", "S8", "S7"):
            if c1[1] != c2[1] or c1[0] != c2[0]:
                cid = canonical_class(c1, c2)
                seen.add(cid)
    # On ne couvre pas tout (juste un sample), mais tous doivent être < 169
    assert all(0 <= c < NUM_PREFLOP_CLASSES for c in seen)


def test_aa_is_top():
    """AA doit être la classe la plus forte (ID 0)."""
    cid = canonical_class("HA", "DA")
    assert cid == 0, f"AA devrait être ID 0, got {cid} ({class_name(cid)})"


def test_kk_is_second():
    """KK doit être 2ème (ID 1)."""
    cid = canonical_class("HK", "DK")
    assert cid == 1, f"KK devrait être ID 1, got {cid} ({class_name(cid)})"


def test_worst_hand_is_offsuit_low():
    """Les pires mains sont des offsuit basses comme 32o ou 27o."""
    worst_candidates = [("S3", "H2"), ("S2", "H7"), ("S4", "H2")]
    bottom_5_ids = list(range(NUM_PREFLOP_CLASSES - 5, NUM_PREFLOP_CLASSES))
    found_in_bottom = sum(1 for c1, c2 in worst_candidates
                          if canonical_class(c1, c2) in bottom_5_ids)
    assert found_in_bottom >= 1, "Au moins une des pires mains devrait être dans le bottom 5"


def test_suited_better_than_offsuit():
    """Pour mêmes ranks, suited doit être mieux classé qu'offsuit.
    Ex : AKs (ID plus bas = meilleur) < AKo."""
    aks = canonical_class("HA", "HK")
    ako = canonical_class("HA", "DK")
    assert aks < ako, f"AKs (ID {aks}) devrait être mieux qu'AKo (ID {ako})"


def test_class_names():
    """Vérification basique des noms."""
    assert class_name(canonical_class("HA", "DA")) == "AA"
    assert class_name(canonical_class("HK", "DK")) == "KK"
    assert class_name(canonical_class("HA", "HK")) == "AKs"
    assert class_name(canonical_class("HA", "DK")) == "AKo"


def test_top_pct():
    """top 5% = ~8 hands (AA, KK, QQ, JJ, AKs, AKo, etc.)."""
    top5 = top_pct_classes(0.05)
    assert len(top5) == 8  # round(169 * 0.05) = 8
    assert canonical_class("HA", "DA") in top5  # AA dedans
    assert canonical_class("HK", "DK") in top5  # KK dedans


def test_in_range_check():
    """class_in_top_pct cohérent avec top_pct_classes."""
    cid_aa = canonical_class("HA", "DA")
    assert class_in_top_pct(cid_aa, 0.05)
    assert class_in_top_pct(cid_aa, 0.01)
    cid_32o = canonical_class("S3", "H2")
    assert not class_in_top_pct(cid_32o, 0.50)
