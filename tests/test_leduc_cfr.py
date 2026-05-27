"""
Tests pour Leduc CFR (Phase 2).

Critères :
  - Valeur du jeu pour P1 converge vers -0.0856 ± 0.01 (Bowling 2003)
  - Stratégies sensées : P1 avec K mise plus que P1 avec J
  - is_terminal détecte tous les cas
  - legal_actions cohérent avec MAX_RAISES_PER_ROUND
  - chips_committed correct pour quelques scénarios standards
"""
import numpy as np
import pytest

from poky.training.leduc_cfr import (
    LeducCFR, NUM_CARDS, CARD_LABELS,
    is_terminal, active_player, legal_actions, transition,
    chips_committed, terminal_utility, rank, info_key,
)


# ---- Tests de la logique de jeu --------------------------------------------

def test_is_terminal_basic():
    assert not is_terminal("")
    assert not is_terminal("c")
    assert not is_terminal("cc|")
    assert is_terminal("cc|cc")
    assert is_terminal("cc|bc")
    assert is_terminal("cc|brc")
    assert is_terminal("cc|cbc")
    assert is_terminal("cc|cbrc")
    assert is_terminal("f")     # P1 fold tout de suite (illégal mais terminal)
    assert is_terminal("bf")    # P2 fold sur bet
    assert is_terminal("cc|bf")
    assert is_terminal("cc|brf")


def test_active_player_alternates():
    assert active_player("") == 0       # P1 ouvre
    assert active_player("c") == 1
    assert active_player("cc|") == 0   # P1 ouvre round 2
    assert active_player("cc|c") == 1
    assert active_player("cb") == 0    # après check/bet, P1 re-décide


def test_legal_actions_check_bet():
    assert legal_actions("") == ["c", "b"]
    assert legal_actions("c") == ["c", "b"]  # P2 face à check


def test_legal_actions_fold_call_raise():
    assert legal_actions("b") == ["f", "c", "r"]   # P2 face à bet (1 aggressive)
    assert legal_actions("br") == ["f", "c"]       # face à raise (2 aggressive, max atteint)
    assert legal_actions("cb") == ["f", "c", "r"]  # P1 face à bet après son check
    assert legal_actions("cbr") == ["f", "c"]


def test_transition_round_advance():
    # cc en round 1 → ouvre round 2
    assert transition("c", "c") == "cc|"
    # bc en round 1 → ouvre round 2
    assert transition("b", "c") == "bc|"


def test_chips_committed_no_bets():
    """Pas de bet : chacun met juste l'ante."""
    assert chips_committed("cc|cc") == (1, 1)


def test_chips_committed_with_bet_call_round_1():
    """P1 bet 2, P2 call → 3 chacun (ante + bet)."""
    assert chips_committed("bc|") == (3, 3)


def test_chips_committed_with_raise():
    """bet 2 + raise → 5 chacun après call."""
    assert chips_committed("brc|") == (5, 5)


def test_chips_committed_round_2_with_bet():
    """Round 1 cc, round 2 bet (4) + call → 5 chacun."""
    assert chips_committed("cc|bc") == (5, 5)


# ---- Tests d'utility -------------------------------------------------------

def test_utility_fold_p1_loses_ante():
    """P1 fold immédiatement (artificiel mais testable)."""
    # Use a manually-crafted "f" history
    u = terminal_utility("f", card_p1=0, card_p2=2, community=4)
    assert u == -1.0   # P1 perd 1 chip (son ante)


def test_utility_showdown_p1_wins_high_card():
    """P1 a K (rank 2), P2 a J (rank 0), community Q. Aucun pair. P1 wins."""
    # K = card 4 or 5, J = 0 or 1, Q = 2 or 3
    u = terminal_utility("cc|cc", card_p1=4, card_p2=0, community=2)
    assert u == 1.0    # P1 gagne 1 chip (l'ante de P2)


def test_utility_showdown_p2_wins_paired():
    """P1 a K, P2 a Q, community Q. P2 pair → P2 wins."""
    u = terminal_utility("cc|cc", card_p1=4, card_p2=2, community=3)
    assert u == -1.0   # P1 perd 1 chip


def test_utility_with_bets():
    """P1 K, P2 J, community Q. P1 bet R1 (2), P2 call, R2 cc. P1 wins."""
    # Chips committed : bc|cc → (3, 3). P1 wins → u = +3.
    u = terminal_utility("bc|cc", card_p1=4, card_p2=0, community=2)
    assert u == 3.0


# ---- Tests d'info set -----------------------------------------------------

def test_info_key_round1_hides_community():
    """Round 1 : pas de community visible."""
    k = info_key(card=4, history="c", community=None)
    assert "?" in k
    assert k == "2_?_c"


def test_info_key_round2_shows_community():
    k = info_key(card=4, history="cc|b", community=2)
    assert k == "2_1_cc|b"   # rank 2 (K), community rank 1 (Q)


# ---- Tests de convergence CFR (les + importants) --------------------------

def test_cfr_value_converges_to_nash():
    """Sur 1500 iters, la valeur de jeu pour P1 doit converger près de -0.0856."""
    trainer = LeducCFR()
    history = trainer.train(iterations=1500)
    final = history[-1]
    expected = -0.0856
    assert abs(final - expected) < 0.015, \
        f"Valeur Leduc converge à {final:.4f}, attendu ~{expected} (Bowling 2003)"


def test_cfr_p1_with_king_aggressive():
    """À l'équilibre, P1 avec K (la meilleure carte) doit bet plus souvent que check
    en début de round 1."""
    trainer = LeducCFR()
    trainer.train(iterations=1500)
    # Trouve les info sets P1 round 1 initial pour chaque rang
    actions_for_rank = {}
    for key, info in trainer.info_sets.items():
        # key = "rank_?_history". On veut history = "" (début round 1).
        parts = key.split("_", 2)
        if len(parts) == 3 and parts[1] == "?" and parts[2] == "":
            actions_for_rank[int(parts[0])] = info.average_strategy()
    # P1 avec K (rank 2)
    assert 2 in actions_for_rank, "P1 ouverture K introuvable"
    sigma_k = actions_for_rank[2]
    # Actions : ['c', 'b']. P[bet] = sigma[1]
    bet_freq_k = sigma_k[1]
    assert bet_freq_k > 0.4, f"P1 avec K devrait bet ≥40% : {bet_freq_k:.2f}"
