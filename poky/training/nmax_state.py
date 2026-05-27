"""
État de jeu N-max NLHE (3-max et plus), pour MCCFR Phase 5.

Généralisation de HUNLState (qui était HU-only) pour supporter 3, 6, 9 joueurs.

CONVENTIONS POSITION :
  - Position 0 = BTN (dealer)
  - Position 1 = SB
  - Position 2 = BB
  - Position 3..N-1 = UTG, MP, ..., CO (ordre clockwise depuis BB)

ORDRE D'ACTION :
  - PRÉFLOP : commence à la position suivante après BB. En 3-max c'est BTN.
    En 4-max+ c'est UTG (position 3). Sequence: action tourne clockwise.
  - POSTFLOP : commence à SB (position 1). Sequence clockwise jusqu'au BTN.

STREET CLOSURE :
  Une street est close quand tous les joueurs non-foldés ont :
   - tous matché la mise courante (committed identiques pour les actifs)
   - ET au moins 1 tour complet a eu lieu depuis le dernier raise
"""
import random
from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple

from poky.engine import Action, Stage
from poky.training.hunl_state import SB, BB, STARTING_STACK


@dataclass(frozen=True)
class NMaxState:
    """État pur NLHE N-max (N ≥ 2)."""
    num_players: int
    hole_cards: Tuple[Tuple[str, str], ...]   # une paire par joueur
    board: Tuple[str, ...]
    stage: Stage
    committed: Tuple[int, ...]                # chips mis par chacun
    stacks: Tuple[int, ...]                   # chips restants
    to_act: int
    folded: Tuple[bool, ...]
    last_aggressor: Optional[int] = None      # dernier raiser, None si pas de raise cette street
    actions_since_aggression: int = 0         # nb d'actions depuis last_aggressor (ou début street)
    action_history: Tuple[Tuple[int, int], ...] = ()
    starting_stack: int = STARTING_STACK

    def is_terminal(self) -> bool:
        active = [i for i in range(self.num_players) if not self.folded[i]]
        if len(active) <= 1:
            return True
        return self.stage == Stage.END

    def to_call(self) -> int:
        return max(self.committed) - self.committed[self.to_act]

    def pot(self) -> int:
        return sum(self.committed)

    def active_players(self) -> List[int]:
        return [i for i in range(self.num_players) if not self.folded[i]]

    def legal_actions(self) -> List[Action]:
        if self.is_terminal():
            return []
        legal: List[Action] = []
        my_stack = self.stacks[self.to_act]
        tc = self.to_call()
        if tc > 0:
            legal.append(Action.FOLD)
        legal.append(Action.CHECK_CALL)
        pot_now = self.pot()
        bet_half = max(BB, pot_now // 2)
        bet_full = max(BB, pot_now)
        for action, size in [(Action.RAISE_HALF_POT, bet_half),
                             (Action.RAISE_POT, bet_full)]:
            if my_stack > tc + size:
                legal.append(action)
        if my_stack > tc:
            legal.append(Action.ALL_IN)
        return legal

    def _next_actor(self, after: int) -> Optional[int]:
        """Prochain joueur actif (non-foldé, non-all-in) après `after`.
        Retourne None si personne ne peut agir."""
        for off in range(1, self.num_players):
            cand = (after + off) % self.num_players
            if not self.folded[cand] and self.stacks[cand] > 0:
                return cand
        return None

    def apply(self, action: Action) -> "NMaxState":
        legal = self.legal_actions()
        if action not in legal:
            raise ValueError(f"Action {action.name} illégale ; "
                             f"légales: {[a.name for a in legal]}")

        new_committed = list(self.committed)
        new_stacks = list(self.stacks)
        new_folded = list(self.folded)
        actor = self.to_act
        tc = self.to_call()
        is_aggressive = action in (Action.RAISE_HALF_POT, Action.RAISE_POT,
                                   Action.ALL_IN)

        if action == Action.FOLD:
            new_folded[actor] = True
        elif action == Action.CHECK_CALL:
            paid = min(tc, new_stacks[actor])
            new_stacks[actor] -= paid
            new_committed[actor] += paid
        elif action == Action.RAISE_HALF_POT:
            pot_now = self.pot()
            bet_size = max(BB, pot_now // 2)
            total = min(tc + bet_size, new_stacks[actor])
            new_stacks[actor] -= total
            new_committed[actor] += total
        elif action == Action.RAISE_POT:
            pot_now = self.pot()
            bet_size = max(BB, pot_now)
            total = min(tc + bet_size, new_stacks[actor])
            new_stacks[actor] -= total
            new_committed[actor] += total
        elif action == Action.ALL_IN:
            total = new_stacks[actor]
            new_stacks[actor] = 0
            new_committed[actor] += total

        new_history = self.action_history + ((actor, int(action)),)
        new_last_agg = (actor if is_aggressive else self.last_aggressor)
        new_actions_since_agg = (1 if is_aggressive
                                 else self.actions_since_aggression + 1)

        # Mise à jour folded et active count
        active = [i for i in range(self.num_players) if not new_folded[i]]

        # Si 1 seul actif → terminal
        if len(active) <= 1:
            return NMaxState(
                num_players=self.num_players,
                hole_cards=self.hole_cards, board=self.board,
                stage=Stage.END, committed=tuple(new_committed),
                stacks=tuple(new_stacks), to_act=actor,
                folded=tuple(new_folded),
                last_aggressor=new_last_agg,
                actions_since_aggression=new_actions_since_agg,
                action_history=new_history,
                starting_stack=self.starting_stack,
            )

        # Détermine si street close
        # Tous les actifs ont matché la mise courante ?
        max_committed = max(new_committed[i] for i in active)
        all_matched = all(new_committed[i] == max_committed
                          or new_stacks[i] == 0 for i in active)
        # Au moins 1 round complet depuis dernier raise ?
        # Approximatif : si nb actifs == nb actions_since_aggression ET all_matched
        # Plus simple : street_closed si chaque actif a eu sa chance d'agir
        # depuis le dernier raise.
        round_complete = (new_actions_since_agg >= len(active))
        someone_all_in = any(new_stacks[i] == 0 for i in active)

        street_closed = False
        if all_matched and (round_complete or someone_all_in):
            street_closed = True
        # Préflop spécial : BB option même si all matched après 1 tour
        if self.stage == Stage.PREFLOP and new_actions_since_agg < len(active):
            street_closed = False

        next_actor = self._next_actor_in_new_state(
            actor, new_folded, new_stacks)

        if street_closed:
            stage_map = {Stage.PREFLOP: Stage.FLOP, Stage.FLOP: Stage.TURN,
                         Stage.TURN: Stage.RIVER, Stage.RIVER: Stage.END}
            new_stage = stage_map.get(self.stage, Stage.END)
            # Postflop : SB (position 1) agit en premier, sinon premier actif
            if new_stage != Stage.PREFLOP and new_stage != Stage.END:
                # Premier actif à partir de SB
                for off in range(self.num_players):
                    cand = (1 + off) % self.num_players  # commence à pos 1 (SB)
                    if not new_folded[cand] and new_stacks[cand] > 0:
                        next_actor = cand
                        break
            new_last_agg = None
            new_actions_since_agg = 0
            # Si all-in, file à END
            if someone_all_in:
                new_stage = Stage.END
        else:
            new_stage = self.stage

        return NMaxState(
            num_players=self.num_players,
            hole_cards=self.hole_cards, board=self.board,
            stage=new_stage, committed=tuple(new_committed),
            stacks=tuple(new_stacks), to_act=next_actor if next_actor is not None else actor,
            folded=tuple(new_folded),
            last_aggressor=new_last_agg,
            actions_since_aggression=new_actions_since_agg,
            action_history=new_history,
            starting_stack=self.starting_stack,
        )

    def _next_actor_in_new_state(self, after: int, folded: list,
                                 stacks: list) -> Optional[int]:
        for off in range(1, self.num_players):
            cand = (after + off) % self.num_players
            if not folded[cand] and stacks[cand] > 0:
                return cand
        return None

    def with_board(self, new_board: Tuple[str, ...]) -> "NMaxState":
        return replace(self, board=new_board)


def deal_new_nmax(rng: random.Random, num_players: int,
                  starting_stack: int = STARTING_STACK
                  ) -> Tuple[NMaxState, Tuple[str, ...]]:
    """Deal random pour N joueurs. Retourne (state, deck_rest)."""
    from poky.equity.estimator import ALL_CARDS_PHEV
    if num_players < 2 or num_players > 9:
        raise ValueError(f"num_players doit être ∈ [2, 9], got {num_players}")
    if num_players * 2 + 5 > 52:
        raise ValueError(f"Trop de joueurs pour 52 cartes")

    deck = list(ALL_CARDS_PHEV)
    rng.shuffle(deck)
    def to_rlcard(c):
        return c[1].upper() + c[0].upper()
    holes = tuple(
        (to_rlcard(deck[2 * i]), to_rlcard(deck[2 * i + 1]))
        for i in range(num_players)
    )
    rest = tuple(to_rlcard(c) for c in deck[2 * num_players:])

    # Position 0 = BTN, 1 = SB, 2 = BB. Blindes postées.
    committed = [0] * num_players
    stacks = [starting_stack] * num_players
    committed[1] = SB
    committed[2] = BB
    stacks[1] -= SB
    stacks[2] -= BB

    # Premier à parler : si N=2 (HU), BTN/SB = pos 0 ? rlcard convention :
    # En N=2 dans notre code on garde HU avec BTN=pos 0 (différent de rlcard's HU).
    # En N≥3, premier à parler = pos 3 % num_players = BTN (3-max) ou UTG (4+).
    if num_players == 2:
        first = 0    # HU : BTN = SB acts first
    elif num_players == 3:
        first = 0    # 3-max : BTN acts first (post BB)
    else:
        first = 3    # UTG

    state = NMaxState(
        num_players=num_players,
        hole_cards=holes, board=(),
        stage=Stage.PREFLOP,
        committed=tuple(committed),
        stacks=tuple(stacks),
        to_act=first,
        folded=tuple(False for _ in range(num_players)),
        starting_stack=starting_stack,
    )
    return state, rest


def reveal_nmax_board(state: NMaxState, deck_rest: Tuple[str, ...]) -> NMaxState:
    """Distribue le board pour la street courante."""
    needed = {Stage.PREFLOP: 0, Stage.FLOP: 3, Stage.TURN: 4,
              Stage.RIVER: 5, Stage.END: max(len(state.board), 5)}[state.stage]
    if len(state.board) >= needed:
        return state
    new_cards = deck_rest[len(state.board):needed]
    return state.with_board(state.board + new_cards)


def terminal_utility_nmax(state: NMaxState) -> List[float]:
    """Utilités par joueur (zero-sum N-player)."""
    if not state.is_terminal():
        raise ValueError("Non terminal")
    utilities = [0.0] * state.num_players
    active = state.active_players()

    if len(active) == 1:
        # Tout le monde sauf un a fold → le restant gagne
        winner = active[0]
        for i in range(state.num_players):
            if i == winner:
                utilities[i] = sum(state.committed) - state.committed[i]
            else:
                utilities[i] = -state.committed[i]
        return utilities

    # Showdown
    if len(state.board) < 5:
        raise ValueError(f"Showdown impossible : board {len(state.board)} cartes")
    from poky.equity import evaluate7, rlcard_to_phev
    board_phev = [rlcard_to_phev(c) for c in state.board]
    scores = {}
    for i in active:
        hole_phev = [rlcard_to_phev(c) for c in state.hole_cards[i]]
        scores[i] = evaluate7(hole_phev, board_phev)
    # Plus petit = meilleur. Trouver les gagnants (split si égalité)
    best = min(scores.values())
    winners = [i for i in active if scores[i] == best]
    pot = sum(state.committed)
    share = pot / len(winners)
    for i in range(state.num_players):
        if i in winners:
            utilities[i] = share - state.committed[i]
        else:
            utilities[i] = -state.committed[i]
    return utilities
