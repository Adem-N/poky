"""
Tests pour le state HU NLHE (Phase 4 - foundation pour MCCFR).

Critères :
  - Deal initial : SB/BB correctement posés
  - Legal actions cohérentes par street
  - Street advances correctement (préflop → flop → turn → river → END)
  - Terminal utility = zero-sum
  - Préflop : BB option respectée (SB call ne ferme PAS la street)
  - Fold termine immédiatement
"""
import random

import pytest

from poky.engine import Action, Stage
from poky.training.hunl_state import (
    deal_new_hand, reveal_board_for_stage, terminal_utility,
    HUNLState, SB, BB, STARTING_STACK,
)


def _new_hand(seed=42):
    rng = random.Random(seed)
    return deal_new_hand(rng)


# ---- Setup initial --------------------------------------------------------

def test_deal_initial_blinds_posted():
    state, _ = _new_hand()
    assert state.committed == (SB, BB)
    assert state.stacks == (STARTING_STACK - SB, STARTING_STACK - BB)
    assert state.to_act == 0   # SB acts first préflop
    assert state.stage == Stage.PREFLOP
    assert not any(state.folded)


def test_deal_holes_distinct():
    state, _ = _new_hand()
    all_cards = set(state.hole_cards[0]) | set(state.hole_cards[1])
    assert len(all_cards) == 4   # 2 cartes par joueur, toutes distinctes


# ---- Legal actions --------------------------------------------------------

def test_legal_preflop_sb():
    state, _ = _new_hand()
    legal = state.legal_actions()
    assert Action.FOLD in legal       # SB peut fold
    assert Action.CHECK_CALL in legal # call de 1 chip


def test_legal_check_when_no_bet():
    """Postflop, BB acts first ; aucun bet → check possible."""
    state, deck = _new_hand()
    # SB call, BB check → flop
    state = state.apply(Action.CHECK_CALL)   # SB call (to 2)
    state = state.apply(Action.CHECK_CALL)   # BB check → flop
    assert state.stage == Stage.FLOP
    legal = state.legal_actions()
    assert Action.FOLD not in legal      # pas de fold quand to_call=0 (option future)
    assert Action.CHECK_CALL in legal


# ---- Street transitions --------------------------------------------------

def test_preflop_bb_option_respected():
    """Préflop : après SB call (committed égaux), BB DOIT pouvoir agir."""
    state, _ = _new_hand()
    state2 = state.apply(Action.CHECK_CALL)  # SB call
    # committed (2, 2), même montant. Mais on doit rester préflop !
    assert state2.stage == Stage.PREFLOP, "BB doit avoir l'option préflop"
    assert state2.to_act == 1


def test_preflop_closes_after_bb_check():
    """SB call → BB check → flop (= 2 actions, dernière CHECK_CALL, committed égal)."""
    state, _ = _new_hand()
    state = state.apply(Action.CHECK_CALL)   # SB call → committed (2,2), street_count=1
    assert state.stage == Stage.PREFLOP
    state = state.apply(Action.CHECK_CALL)   # BB check → street_count=2, close
    assert state.stage == Stage.FLOP


def test_postflop_check_check_closes():
    """Postflop check/check → street suivante."""
    state, _ = _new_hand()
    state = state.apply(Action.CHECK_CALL)  # SB call
    state = state.apply(Action.CHECK_CALL)  # BB check → FLOP
    # Sur le flop, BB (joueur 1) agit en premier
    assert state.stage == Stage.FLOP
    assert state.to_act == 1
    state = state.apply(Action.CHECK_CALL)  # BB check
    state = state.apply(Action.CHECK_CALL)  # SB check → TURN
    assert state.stage == Stage.TURN


# ---- Fold ----------------------------------------------------------------

def test_fold_terminates_game():
    state, _ = _new_hand()
    state = state.apply(Action.FOLD)   # SB fold
    assert state.is_terminal()
    assert state.folded[0] is True


def test_fold_utility():
    state, _ = _new_hand()
    state = state.apply(Action.FOLD)   # SB fold (committed 1 chip)
    u0, u1 = terminal_utility(state)
    assert u0 == -1 and u1 == 1  # P0 perd son SB de 1, P1 gagne 1


# ---- Showdown utility ----------------------------------------------------

def test_showdown_zero_sum():
    """Run jusqu'au showdown (cc-cc partout), vérifie U0 + U1 = 0."""
    state, deck = _new_hand(seed=42)
    # SB call, BB check → FLOP
    state = state.apply(Action.CHECK_CALL)
    state = state.apply(Action.CHECK_CALL)
    state = reveal_board_for_stage(state, deck)
    # FLOP : check check → TURN
    state = state.apply(Action.CHECK_CALL)
    state = state.apply(Action.CHECK_CALL)
    state = reveal_board_for_stage(state, deck)
    # TURN : check check → RIVER
    state = state.apply(Action.CHECK_CALL)
    state = state.apply(Action.CHECK_CALL)
    state = reveal_board_for_stage(state, deck)
    # RIVER : check check → END
    state = state.apply(Action.CHECK_CALL)
    state = state.apply(Action.CHECK_CALL)
    assert state.stage == Stage.END
    u0, u1 = terminal_utility(state)
    assert abs(u0 + u1) < 1e-9


# ---- Raise mechanics -----------------------------------------------------

def test_raise_increases_pot():
    state, _ = _new_hand()
    pot_before = state.pot()
    state = state.apply(Action.RAISE_POT)
    pot_after = state.pot()
    assert pot_after > pot_before


def test_all_in_drains_stack():
    state, _ = _new_hand()
    state = state.apply(Action.ALL_IN)
    assert state.stacks[0] == 0
    assert state.committed[0] == STARTING_STACK
