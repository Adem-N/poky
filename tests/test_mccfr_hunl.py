"""
Tests pour MCCFR HU NLHE (Phase 4).

Critères :
  - Pipeline tourne sans crash (smoke 50 iters)
  - Stratégie moyenne est une distribution valide (somme à 1, ≥ 0)
  - Save/load roundtrip préserve la table
  - Le nombre d'info sets augmente avec le training
"""
import os
import tempfile

import numpy as np
import pytest

from poky.training.mccfr_hunl import HUNLMCCFRTrainer, state_infoset_key
from poky.training.hunl_state import deal_new_hand
import random


def test_smoke_50_iters_no_crash():
    trainer = HUNLMCCFRTrainer(seed=42)
    trainer.train(iterations=50, log_every=100)
    assert trainer.iterations_done == 50
    assert len(trainer.regret_sum) > 0


def test_strategy_is_valid_distribution():
    """Toutes les stratégies retournées doivent être des distributions
    (somme = 1, valeurs ∈ [0, 1])."""
    trainer = HUNLMCCFRTrainer(seed=42)
    trainer.train(iterations=100, log_every=200)
    for key, ss in trainer.strategy_sum.items():
        if ss.sum() > 0:
            avg = ss / ss.sum()
            assert abs(avg.sum() - 1.0) < 1e-5
            assert np.all(avg >= 0)
            assert np.all(avg <= 1.0 + 1e-5)


def test_state_infoset_key_deterministic():
    """Même état → même key."""
    rng = random.Random(7)
    state, _ = deal_new_hand(rng)
    k1 = state_infoset_key(state, actor=0)
    k2 = state_infoset_key(state, actor=0)
    assert k1 == k2


def test_state_infoset_key_distinct_per_actor():
    """Les 2 joueurs ont des keys différentes au même état (cartes privées)."""
    rng = random.Random(7)
    state, _ = deal_new_hand(rng)
    k0 = state_infoset_key(state, actor=0)
    k1 = state_infoset_key(state, actor=1)
    assert k0 != k1


def test_save_load_roundtrip():
    """Save + load préserve la strategy table."""
    trainer = HUNLMCCFRTrainer(seed=42)
    trainer.train(iterations=100, log_every=200)
    n_iters = trainer.iterations_done
    n_isets = len(trainer.regret_sum)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_ckpt.pkl")
        trainer.save(path)
        loaded = HUNLMCCFRTrainer.load(path)

    assert loaded.iterations_done == n_iters
    assert len(loaded.regret_sum) == n_isets
    # Vérifie que les regrets de quelques keys sont identiques
    sample_keys = list(trainer.regret_sum.keys())[:5]
    for k in sample_keys:
        assert np.allclose(trainer.regret_sum[k], loaded.regret_sum[k])


def test_info_sets_grow_with_training():
    """Plus on entraîne, plus on découvre d'info sets."""
    trainer = HUNLMCCFRTrainer(seed=42)
    trainer.train(iterations=50, log_every=100)
    n1 = len(trainer.regret_sum)
    trainer.train(iterations=50, log_every=100)
    n2 = len(trainer.regret_sum)
    assert n2 > n1, f"Info sets devraient croître : {n1} → {n2}"
