"""
État de jeu Heads-Up NLHE simplifié, pur (sans side effects), pour MCCFR.

Pourquoi pas rlcard ? rlcard.Game ne supporte pas le "fork" propre nécessaire
pour explorer plusieurs branches au noeud traverseur en MCCFR. Une classe
d'état immutable (clone par dataclasses.replace) résout ça.

ABSTRACTION D'ACTIONS (5 valeurs, alignée sur poky.engine.Action) :
  FOLD              = 0
  CHECK_CALL        = 1
  RAISE_HALF_POT    = 2
  RAISE_POT         = 3
  ALL_IN            = 4

CONVENTIONS HU :
  - Player 0 = button (BTN/SB), poste SB et agit en premier préflop
  - Player 1 = big blind (BB), poste BB et agit en premier postflop
  - Stacks initiaux : starting_stack (100 chips par défaut, blinds 1/2 → 50bb)

STREET CLOSURE :
  Une street est close quand : dernière action = CHECK_CALL ET
  committed[0] == committed[1] ET ≥2 actions ont été jouées cette street.
  (Cette règle simple capture le préflop BB option et les check-back postflop.)

Le state est représenté comme dataclass frozen. Le clone est implicite (replace).
"""
import random
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

from poky.engine import Action, Stage


SB = 1
BB = 2
STARTING_STACK = 100  # 50 BB


@dataclass(frozen=True)
class HUNLState:
    hole_cards: Tuple[Tuple[str, str], Tuple[str, str]]
    board: Tuple[str, ...]
    stage: Stage
    committed: Tuple[int, int]
    stacks: Tuple[int, int]
    to_act: int
    folded: Tuple[bool, bool]
    action_history: Tuple[Tuple[int, int], ...] = ()
    street_action_count: int = 0
    starting_stack: int = STARTING_STACK

    # ---- queries ----------------------------------------------------------

    def is_terminal(self) -> bool:
        if any(self.folded):
            return True
        if self.stage == Stage.END:
            return True
        return False

    def to_call(self) -> int:
        return max(self.committed) - self.committed[self.to_act]

    def pot(self) -> int:
        return sum(self.committed)

    def legal_actions(self) -> List[Action]:
        if self.is_terminal():
            return []
        legal: List[Action] = []
        my_stack = self.stacks[self.to_act]
        tc = self.to_call()

        if tc > 0:
            legal.append(Action.FOLD)
        legal.append(Action.CHECK_CALL)

        # Raises seulement si on a plus que le call requis
        pot_now = self.pot()
        bet_half = max(BB, pot_now // 2)
        bet_full = max(BB, pot_now)
        for action, size in [(Action.RAISE_HALF_POT, bet_half),
                             (Action.RAISE_POT, bet_full)]:
            total_needed = tc + size
            if my_stack > total_needed:
                legal.append(action)
        if my_stack > tc:
            legal.append(Action.ALL_IN)
        return legal

    # ---- transitions -----------------------------------------------------

    def apply(self, action: Action) -> "HUNLState":
        """Retourne un nouveau state après application de l'action."""
        legal = self.legal_actions()
        if action not in legal:
            raise ValueError(f"Action {action.name} illégale ; "
                             f"légales: {[a.name for a in legal]}")

        new_committed = list(self.committed)
        new_stacks = list(self.stacks)
        new_folded = list(self.folded)
        actor = self.to_act
        tc = self.to_call()

        if action == Action.FOLD:
            new_folded[actor] = True
        elif action == Action.CHECK_CALL:
            paid = min(tc, new_stacks[actor])
            new_stacks[actor] -= paid
            new_committed[actor] += paid
        elif action in (Action.RAISE_HALF_POT, Action.RAISE_POT):
            pot_now = self.pot()
            bet_size = (pot_now // 2 if action == Action.RAISE_HALF_POT
                        else pot_now)
            bet_size = max(BB, bet_size)
            total = tc + bet_size
            total = min(total, new_stacks[actor])
            new_stacks[actor] -= total
            new_committed[actor] += total
        elif action == Action.ALL_IN:
            total = new_stacks[actor]
            new_stacks[actor] = 0
            new_committed[actor] += total

        new_history = self.action_history + ((actor, int(action)),)
        new_street_count = self.street_action_count + 1

        # Si fold, terminal direct
        if new_folded[actor]:
            return HUNLState(
                hole_cards=self.hole_cards, board=self.board,
                stage=Stage.END, committed=tuple(new_committed),
                stacks=tuple(new_stacks), to_act=actor,
                folded=tuple(new_folded), action_history=new_history,
                street_action_count=new_street_count,
                starting_stack=self.starting_stack,
            )

        # Détermine si street close
        committed_equal = new_committed[0] == new_committed[1]
        someone_all_in = new_stacks[0] == 0 or new_stacks[1] == 0
        last_was_check_call = (action == Action.CHECK_CALL)

        street_closed = False
        if committed_equal and (
                (last_was_check_call and new_street_count >= 2) or someone_all_in):
            street_closed = True

        # Tour suivant
        other = 1 - actor
        new_to_act = other

        if street_closed:
            # Avance street
            stage_map = {Stage.PREFLOP: Stage.FLOP, Stage.FLOP: Stage.TURN,
                         Stage.TURN: Stage.RIVER, Stage.RIVER: Stage.END}
            new_stage = stage_map.get(self.stage, Stage.END)
            # Postflop, BB (joueur 1) agit en premier
            new_to_act = 1 if new_stage != Stage.PREFLOP else 0
            new_street_count = 0   # reset compteur pour nouvelle street
            # Si all-in, on file directement à END (run out board)
            if someone_all_in:
                new_stage = Stage.END
        else:
            new_stage = self.stage

        return HUNLState(
            hole_cards=self.hole_cards, board=self.board,
            stage=new_stage, committed=tuple(new_committed),
            stacks=tuple(new_stacks), to_act=new_to_act,
            folded=tuple(new_folded), action_history=new_history,
            street_action_count=new_street_count,
            starting_stack=self.starting_stack,
        )

    def with_board(self, new_board: Tuple[str, ...]) -> "HUNLState":
        """Retourne un état avec board mis à jour (utilisé pour révélation cartes)."""
        return replace(self, board=new_board)


# ---- Factory ---------------------------------------------------------------

def _to_rlcard(phev_card: str) -> str:
    """phevaluator 'Ah' -> rlcard 'HA'."""
    return phev_card[1].upper() + phev_card[0].upper()


def deal_new_hand(rng: random.Random,
                  starting_stack: int = STARTING_STACK) -> Tuple[HUNLState, Tuple[str, ...]]:
    """
    Crée un nouvel état début-de-main avec deal random.
    Retourne (state, full_deck_rest) où full_deck_rest est les 48 cartes
    restantes (pour distribution incrémentale du board).
    """
    from poky.equity.estimator import ALL_CARDS_PHEV
    deck = list(ALL_CARDS_PHEV)
    rng.shuffle(deck)
    hole0 = (_to_rlcard(deck[0]), _to_rlcard(deck[1]))
    hole1 = (_to_rlcard(deck[2]), _to_rlcard(deck[3]))
    rest = tuple(_to_rlcard(c) for c in deck[4:])
    state = HUNLState(
        hole_cards=(hole0, hole1), board=(),
        stage=Stage.PREFLOP,
        committed=(SB, BB),
        stacks=(starting_stack - SB, starting_stack - BB),
        to_act=0, folded=(False, False),
        starting_stack=starting_stack,
    )
    return state, rest


def reveal_board_for_stage(state: HUNLState, deck_rest: Tuple[str, ...]) -> HUNLState:
    """
    Si le state demande un board update (juste passé en flop/turn/river),
    distribue les cartes nécessaires depuis deck_rest. Idempotent.

    IMPORTANT : deck_rest est ordonné [flop1, flop2, flop3, turn, river, ...autres],
    donc on slice par INDICE absolu pour éviter les doublons entre streets.
    """
    needed = {Stage.PREFLOP: 0, Stage.FLOP: 3, Stage.TURN: 4,
              Stage.RIVER: 5, Stage.END: max(len(state.board), 5)}[state.stage]
    if len(state.board) >= needed:
        return state
    # Slice par indice absolu : board déjà 3 cartes (flop) → turn = deck_rest[3:4]
    new_cards = deck_rest[len(state.board):needed]
    new_board = state.board + new_cards
    return state.with_board(new_board)


# ---- Évaluation finale (utility) ------------------------------------------

def terminal_utility(state: HUNLState) -> Tuple[float, float]:
    """
    Utilities pour (P0, P1) au noeud terminal.
    Si fold : le folder perd sa contribution, l'autre gagne la sienne.
    Si showdown : compare via phevaluator, pot va au gagnant (split si égalité).
    Convention : zero-sum, U[0] + U[1] = 0.
    """
    if not state.is_terminal():
        raise ValueError("État non-terminal")

    c0, c1 = state.committed
    if state.folded[0]:
        return (-float(c0), float(c0))
    if state.folded[1]:
        return (float(c1), -float(c1))

    # Showdown — il faut un board complet (5 cartes)
    if len(state.board) < 5:
        raise ValueError(f"Showdown impossible : board incomplet ({len(state.board)} cartes)")

    from poky.equity import evaluate7, rlcard_to_phev
    hole0_phev = [rlcard_to_phev(c) for c in state.hole_cards[0]]
    hole1_phev = [rlcard_to_phev(c) for c in state.hole_cards[1]]
    board_phev = [rlcard_to_phev(c) for c in state.board]
    score0 = evaluate7(hole0_phev, board_phev)
    score1 = evaluate7(hole1_phev, board_phev)
    # phevaluator : plus petit = meilleur
    if score0 < score1:
        # P0 gagne, gagne ce que P1 a mis
        return (float(c1), -float(c1))
    if score1 < score0:
        return (-float(c0), float(c0))
    # Tie : split du pot
    avg = (c1 - c0) / 2.0   # rééquilibre
    return (avg, -avg)
