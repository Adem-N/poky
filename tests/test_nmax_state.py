"""
Tests pour NMaxState (Phase 5 — N-max NLHE).

Critères :
  - Deal 3-max : blinds correctement posées (SB=1, BB=2, BTN=0)
  - 3-max : BTN agit en premier préflop
  - Postflop : SB agit en premier
  - Fold de 2 sur 3 → 1 actif → terminal
  - Showdown 3-max : compte juste
"""
import random
import pytest

from poky.engine import Action, Stage
from poky.training.nmax_state import (
    NMaxState, deal_new_nmax, reveal_nmax_board, terminal_utility_nmax,
)
from poky.training.hunl_state import SB, BB, STARTING_STACK


def _new_3max(seed=42):
    return deal_new_nmax(random.Random(seed), num_players=3)


# ---- Setup initial 3-max --------------------------------------------------

def test_3max_blinds_posted():
    state, _ = _new_3max()
    assert state.num_players == 3
    # Position 0 = BTN (post 0), 1 = SB (post 1), 2 = BB (post 2)
    assert state.committed == (0, SB, BB)
    assert state.stacks == (STARTING_STACK, STARTING_STACK - SB, STARTING_STACK - BB)
    assert state.to_act == 0  # BTN acts first in 3-max
    assert state.stage == Stage.PREFLOP
    assert not any(state.folded)


def test_3max_holes_all_distinct():
    state, _ = _new_3max()
    all_cards = []
    for h in state.hole_cards:
        all_cards.extend(h)
    assert len(set(all_cards)) == 6  # 3 joueurs × 2 cartes distinctes


# ---- Action flow 3-max ---------------------------------------------------

def test_3max_btn_fold_then_action_goes_sb():
    state, _ = _new_3max()
    state = state.apply(Action.FOLD)   # BTN fold
    assert state.folded[0] is True
    assert state.to_act == 1   # SB now to act


def test_3max_2_folds_terminal():
    state, _ = _new_3max()
    state = state.apply(Action.FOLD)   # BTN fold
    state = state.apply(Action.FOLD)   # SB fold
    # BB wins by default
    assert state.is_terminal()


def test_3max_2_folds_utility():
    state, _ = _new_3max()
    state = state.apply(Action.FOLD)
    state = state.apply(Action.FOLD)
    utils = terminal_utility_nmax(state)
    # BTN n'a rien posté, SB a posté 1, BB gagne pot = 1 (SB blind)
    assert utils[0] == 0      # BTN
    assert utils[1] == -SB    # SB perd sa blind
    assert utils[2] == SB     # BB gagne celle du SB
    # sum = 0 (zero-sum dans ce contexte)
    assert sum(utils) == 0


# ---- Street advance ------------------------------------------------------

def test_3max_preflop_to_flop():
    """BTN call, SB call, BB check → flop, SB to act first."""
    state, deck = _new_3max()
    state = state.apply(Action.CHECK_CALL)  # BTN call 2
    state = state.apply(Action.CHECK_CALL)  # SB call 1 more to match
    state = state.apply(Action.CHECK_CALL)  # BB check
    assert state.stage == Stage.FLOP, f"Stage={state.stage}, expected FLOP"
    assert state.to_act == 1  # SB (pos 1) acts first postflop


# ---- Showdown 3-max -----------------------------------------------------

def test_3max_full_hand_zero_sum():
    state, deck = _new_3max(seed=42)
    # Joue jusqu'au showdown via check/call all streets
    for _ in range(20):
        if state.is_terminal():
            break
        if state.stage != Stage.PREFLOP and len(state.board) < {
                Stage.FLOP: 3, Stage.TURN: 4, Stage.RIVER: 5, Stage.END: 5
        }[state.stage]:
            state = reveal_nmax_board(state, deck)
        legal = state.legal_actions()
        action = Action.CHECK_CALL if Action.CHECK_CALL in legal else legal[0]
        state = state.apply(action)
    state = reveal_nmax_board(state, deck)
    assert state.is_terminal()
    utils = terminal_utility_nmax(state)
    assert abs(sum(utils)) < 1e-6


# ---- 6-max basic ---------------------------------------------------------

def test_6max_blinds_and_action_start():
    """6-max : pos 0=BTN, 1=SB, 2=BB, 3=UTG (first to act preflop)."""
    state, _ = deal_new_nmax(random.Random(7), num_players=6)
    assert state.num_players == 6
    assert state.committed[1] == SB
    assert state.committed[2] == BB
    assert state.to_act == 3   # UTG
