"""
Tests pour action abstraction + infoset encoding (Phase 3).

Critères :
  - encode/decode history est l'identité
  - infoset_key déterministe : mêmes inputs → même bytes
  - Différents inputs → différentes bytes
  - Cohérence entre infoset_key et decode_for_debug
  - legal_abstract_actions wrap obs.legal_actions
  - action_index / index_to_action sont inverses
"""
import pytest

from poky.abstraction import (
    encode_history, decode_history,
    infoset_key, decode_for_debug, history_truncated,
    legal_abstract_actions, action_index, index_to_action,
    ABSTRACT_ACTIONS, NUM_ABSTRACT_ACTIONS,
)
from poky.engine import Action, Game


# ---- Action abstraction ---------------------------------------------------

def test_num_abstract_actions():
    assert NUM_ABSTRACT_ACTIONS == 5


def test_action_index_roundtrip():
    for a in ABSTRACT_ACTIONS:
        i = action_index(a)
        assert index_to_action(i) == a


def test_legal_abstract_actions_from_real_obs():
    """En début de main 3-max, on a au moins FOLD et CHECK_CALL."""
    game = Game(num_players=3, seed=42)
    obs, _ = game.reset()
    legal = legal_abstract_actions(obs)
    assert Action.FOLD in legal
    assert Action.CHECK_CALL in legal
    # Toutes doivent être dans ABSTRACT_ACTIONS
    for a in legal:
        assert a in ABSTRACT_ACTIONS


# ---- Encode/decode history -----------------------------------------------

def test_encode_decode_history_empty():
    assert decode_history(encode_history([])) == []


def test_encode_decode_history_roundtrip():
    hist = [(0, 1), (1, 3), (2, 0), (0, 4), (1, 1)]
    encoded = encode_history(hist)
    assert isinstance(encoded, bytes)
    assert decode_history(encoded) == hist


def test_history_size_in_bytes():
    """5 actions → 1 byte longueur + 5 bytes data = 6 bytes total."""
    hist = [(0, 1)] * 5
    encoded = encode_history(hist)
    assert len(encoded) == 6


def test_history_truncated():
    hist = [(0, i % 5) for i in range(40)]
    truncated = history_truncated(hist, max_actions=12)
    assert len(truncated) == 12
    # Les 12 dernières doivent être préservées
    assert truncated == hist[-12:]


def test_history_no_truncation_when_short():
    hist = [(0, 1), (1, 2), (2, 3)]
    assert history_truncated(hist, max_actions=12) == hist


# ---- Infoset key ----------------------------------------------------------

def _get_obs():
    """Récupère une obs réelle d'un jeu 3-max."""
    game = Game(num_players=3, seed=42)
    obs, _ = game.reset()
    return obs


def test_infoset_key_deterministic():
    obs = _get_obs()
    hist = [(0, 1), (1, 3)]
    k1 = infoset_key(obs, hist, card_bucket=7)
    k2 = infoset_key(obs, hist, card_bucket=7)
    assert k1 == k2


def test_infoset_key_different_cards_different_keys():
    obs = _get_obs()
    hist = [(0, 1)]
    k1 = infoset_key(obs, hist, card_bucket=5)
    k2 = infoset_key(obs, hist, card_bucket=42)
    assert k1 != k2


def test_infoset_key_different_history_different_keys():
    obs = _get_obs()
    k1 = infoset_key(obs, [(0, 1)], card_bucket=7)
    k2 = infoset_key(obs, [(0, 1), (1, 3)], card_bucket=7)
    assert k1 != k2


def test_infoset_key_decode_roundtrip():
    obs = _get_obs()
    hist = [(0, 1), (1, 3), (2, 0)]
    key = infoset_key(obs, hist, card_bucket=42)
    decoded = decode_for_debug(key)
    assert decoded["card_bucket"] == 42
    assert decoded["stage"] == int(obs.stage)
    assert decoded["history"] == hist


def test_infoset_key_card_bucket_supports_uint16():
    obs = _get_obs()
    # 169 préflop classes (max valid card_bucket préflop) doit passer
    key = infoset_key(obs, [], card_bucket=168)
    assert decode_for_debug(key)["card_bucket"] == 168
    # Et même un gros bucket id (théorique)
    key = infoset_key(obs, [], card_bucket=50000)
    assert decode_for_debug(key)["card_bucket"] == 50000


def test_infoset_key_card_bucket_overflow_raises():
    obs = _get_obs()
    with pytest.raises(ValueError):
        infoset_key(obs, [], card_bucket=70000)  # > uint16 max
    with pytest.raises(ValueError):
        infoset_key(obs, [], card_bucket=-1)
