"""
CFRPlayer : combine blueprint + subgame solving en temps réel.

C'est l'ASSEMBLAGE FINAL de Pluribus-style architecture :
  1. Blueprint MCCFR pré-entraîné (warm start, ~5h overnight)
  2. Subgame solver appelé à chaque décision (~1s par coup)
  3. Fallback heuristic pour cas où subgame solver échoue

USAGE :
  player = CFRPlayer(
      blueprint_path="data/blueprint_hu/overnight_5M.pkl",
      time_budget_s=1.0,
  )
  # Joue HU NLHE comme n'importe quel Player

NOTE : version HU uniquement. Pour 3-max, on aurait un NMaxCFRPlayer.
"""
import os
import random
from typing import Optional

import numpy as np

from poky.cfr.subgame_solver import SubgameSolver
from poky.engine import Action, Observation, Stage
from poky.players.base import Player, ActionEvent
from poky.players.heuristic import HeuristicPlayer
from poky.training.hunl_state import HUNLState, SB, BB, STARTING_STACK
from poky.training.mccfr_hunl import HUNLMCCFRTrainer


class CFRPlayer(Player):
    """Blueprint + subgame solver = bot fort pour HU NLHE."""
    name = "cfr"

    def __init__(self, blueprint_path: str,
                 time_budget_s: float = 1.0,
                 fallback_seed: Optional[int] = None,
                 sample_seed: Optional[int] = None):
        if not os.path.exists(blueprint_path):
            raise FileNotFoundError(f"Blueprint introuvable : {blueprint_path}")
        self.blueprint = HUNLMCCFRTrainer.load(blueprint_path)
        self.solver = SubgameSolver(
            blueprint=self.blueprint,
            time_budget_s=time_budget_s,
            seed=sample_seed,
        )
        self.fallback = HeuristicPlayer(seed=fallback_seed)
        self.rng = random.Random(sample_seed if sample_seed is not None else 0)
        # État par main
        self._action_history = []
        self._solver_calls = 0
        self._solver_errors = 0

    def reset(self) -> None:
        self._action_history = []

    def observe_action(self, event: ActionEvent) -> None:
        self._action_history.append((event.actor, int(event.action)))

    def act(self, obs: Observation) -> Action:
        if obs.num_players != 2:
            return self.fallback.act(obs)

        # rlcard HU convention : dealer == BB (cf. blueprint_player.py)
        def seat_to_role(seat_id: int) -> int:
            return 1 if seat_id == obs.dealer_id else 0

        my_role = seat_to_role(obs.player_id)
        opp_role = 1 - my_role

        # Construit la HUNLState à partir de l'obs
        # Hole cards : on a les nôtres, opp = placeholder qu'on remplacera par sample
        holes = [None, None]
        holes[my_role] = tuple(obs.hole_cards)
        holes[opp_role] = ("XX", "YY")   # placeholder, sera réécrit par solver

        # Convertit l'history seat-based en role-based pour matcher blueprint
        history_role = tuple(
            (seat_to_role(seat), act_id)
            for seat, act_id in self._action_history
        )

        # Recalcule committed/stacks au format role
        committed = [0, 0]
        stacks = [STARTING_STACK, STARTING_STACK]
        for seat in range(2):
            role = seat_to_role(seat)
            committed[role] = obs.all_committed[seat]
            stacks[role] = obs.all_stacks[seat]

        # Compte les actions de la street courante
        # On utilise une approximation : compte depuis le début de la dernière street
        street_count = sum(1 for ev in history_role[-12:] if True)  # approximation
        # Plus précis : on reset à chaque street advance, mais c'est compliqué à reconstruire
        # depuis l'history. On utilise 24 max (sera tronqué).

        try:
            state = HUNLState(
                hole_cards=tuple(holes),
                board=tuple(obs.community_cards),
                stage=obs.stage,
                committed=tuple(committed),
                stacks=tuple(stacks),
                to_act=my_role,
                folded=(False, False),  # si folded, on serait pas en train d'act
                action_history=history_role,
                street_action_count=street_count,
                starting_stack=STARTING_STACK,
            )

            # Known cards : nos hole + board visible
            known = list(obs.hole_cards) + list(obs.community_cards)

            legal_solver, probs = self.solver.solve(state, known)
            if len(legal_solver) == 0:
                raise RuntimeError("Solver returned empty")

            # Map legal_solver (Actions) → indices dans obs.legal_actions
            # Les 2 listes devraient matcher si les state.legal_actions et obs.legal_actions sont cohérents
            obs_legal = obs.legal_actions
            # Construit prob par obs_legal
            obs_probs = np.zeros(len(obs_legal), dtype=np.float32)
            for i, a in enumerate(legal_solver):
                if a in obs_legal:
                    obs_probs[obs_legal.index(a)] = probs[i]
            if obs_probs.sum() == 0:
                raise RuntimeError("No overlap between solver legal and obs legal")
            obs_probs = obs_probs / obs_probs.sum()

            idx = self.rng.choices(range(len(obs_legal)),
                                   weights=obs_probs.tolist())[0]
            self._solver_calls += 1
            return obs_legal[idx]
        except Exception as e:
            self._solver_errors += 1
            return self.fallback.act(obs)

    @property
    def solver_success_rate(self) -> float:
        total = self._solver_calls + self._solver_errors
        return self._solver_calls / max(total, 1)
