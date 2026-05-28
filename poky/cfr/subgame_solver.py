"""
Depth-limited subgame solver pour NLHE HU.

C'EST LA PIÈCE CLÉS de Pluribus : au moment de décider, le bot RAFFINE la
blueprint en temps réel sur le spot actuel via quelques itérations de CFR.

PRINCIPE (Brown & Sandholm 2017, "Safe and Nested Subgame Solving") :
  1. À chaque décision, on connaît : notre main + le board public.
     On NE connaît PAS : la main de l'adversaire, les futures cartes.
  2. Pour chaque itération du solver :
       a) Sample les cartes inconnues (chance node externe)
       b) Construit la HUNLState concrète résultante
       c) Run un pas de CFR (énumération au joueur traverseur, sample chez l'autre)
       d) Met à jour les regrets LOCAUX (pas la blueprint)
  3. Après N itérations (ou time_budget atteint) :
       Retourne la stratégie moyenne locale pour le root info-set.

WARM START : les regrets initiaux sont importés de la blueprint si elle a
visité ce info-set. Ça démarre proche d'une bonne strat, le solver raffine.

USAGE :
  solver = SubgameSolver(blueprint=trainer, time_budget_s=1.0)
  action_probs = solver.solve(state, my_hole, board, dealer_pos=...)
"""
import random
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from poky.abstraction import (
    canonical_class, postflop_bucket,
    encode_history, history_truncated, NUM_ABSTRACT_ACTIONS,
)
from poky.engine import Action, Stage
from poky.equity.estimator import ALL_CARDS_PHEV
from poky.training.hunl_state import (
    HUNLState, SB, BB, STARTING_STACK,
    reveal_board_for_stage, terminal_utility,
)
from poky.training.mccfr_hunl import HUNLMCCFRTrainer, state_infoset_key


def _phev_to_rlcard(phev_card: str) -> str:
    return phev_card[1].upper() + phev_card[0].upper()


class SubgameSolver:
    """Résout en temps réel un sous-jeu enraciné à un état HUNL.

    Le solver fait du CFR avec sampling des chance nodes (hole cards adverses
    + futures community cards). Tous les regrets/strategies sont LOCAUX —
    la blueprint n'est jamais modifiée.
    """

    def __init__(self, blueprint: HUNLMCCFRTrainer,
                 time_budget_s: float = 1.0,
                 min_iterations: int = 200,
                 max_iterations: int = 20000,
                 seed: Optional[int] = None):
        self.blueprint = blueprint
        self.time_budget_s = time_budget_s
        self.min_iterations = min_iterations
        self.max_iterations = max_iterations
        self.rng = random.Random(seed if seed is not None else 0)

    def solve(self, root_state: HUNLState,
              known_cards: List[str]) -> Tuple[List[Action], np.ndarray]:
        """
        Résout le sous-jeu depuis `root_state`. Retourne (legal_actions, prob_array).

        `root_state` doit avoir :
          - hole_cards[my_actor] = nos vraies cartes
          - hole_cards[other] = placeholders (peuvent être vides ou random)
          - board = community cards visibles
          - stage, committed, stacks, to_act corrects

        `known_cards` = liste de toutes les cartes visibles publiquement +
        nos hole cards (au format rlcard 'HQ'). Utilisé pour sample le reste.
        """
        legal = root_state.legal_actions()
        if not legal:
            return [], np.zeros(0)
        if len(legal) == 1:
            # Une seule option, pas besoin de solver
            return legal, np.array([1.0])

        local_regret: Dict[bytes, np.ndarray] = {}
        local_strategy: Dict[bytes, np.ndarray] = {}

        my_actor = root_state.to_act
        opp_actor = 1 - my_actor
        my_hole = list(root_state.hole_cards[my_actor])
        board = list(root_state.board)

        # Cartes restantes pour sampler hole adversaire + futur board
        all_cards = list(ALL_CARDS_PHEV)
        # ALL_CARDS_PHEV est en format phev, convertir en rlcard
        all_cards_rlcard = [_phev_to_rlcard(c) for c in all_cards]
        known_set = set(known_cards)
        remaining = [c for c in all_cards_rlcard if c not in known_set]

        start = time.time()
        iter_count = 0
        while iter_count < self.min_iterations or (
                iter_count < self.max_iterations
                and time.time() - start < self.time_budget_s):
            # Sample opp hole + future board pour cette itération
            self.rng.shuffle(remaining)
            opp_hole = (remaining[0], remaining[1])
            # Combien de board cards manque-t-il pour aller jusqu'à river ?
            board_needed = 5 - len(board)
            future_board = tuple(remaining[2:2 + board_needed]) if board_needed > 0 else ()
            full_board = tuple(board) + future_board

            # Construit la state concrète pour cette itération
            new_holes = list(root_state.hole_cards)
            new_holes[opp_actor] = opp_hole
            # Pour notre actor, garder les vraies cartes
            new_holes[my_actor] = tuple(my_hole)
            iter_state = root_state.__class__(
                hole_cards=tuple(new_holes),
                board=full_board,
                stage=root_state.stage,
                committed=root_state.committed,
                stacks=root_state.stacks,
                to_act=root_state.to_act,
                folded=root_state.folded,
                action_history=root_state.action_history,
                street_action_count=root_state.street_action_count,
                starting_stack=root_state.starting_stack,
            )

            # 1 itération CFR par traverser (alterne)
            traverser = my_actor if iter_count % 2 == 0 else opp_actor
            self._cfr(iter_state, traverser, local_regret, local_strategy)
            iter_count += 1

        # Stratégie moyenne au root
        root_key = state_infoset_key(root_state, my_actor)
        legal_indices = [int(a) for a in legal]
        avg = self._average_strategy(root_key, local_strategy, legal_indices)
        return legal, avg

    def _cfr(self, state: HUNLState, traverser: int,
             local_regret: Dict[bytes, np.ndarray],
             local_strategy: Dict[bytes, np.ndarray]) -> float:
        """Run un pas de CFR (recursif) sur la state donnée pour traverser."""
        if state.is_terminal():
            # Pour all-in run-out, board déjà complet par construction
            u = terminal_utility(state)
            return u[traverser]

        actor = state.to_act
        legal = state.legal_actions()
        if not legal:
            return terminal_utility(state)[traverser]
        legal_indices = [int(a) for a in legal]
        num_actions = len(legal)

        key = state_infoset_key(state, actor)
        sigma = self._get_strategy(key, legal_indices, local_regret)

        if actor == traverser:
            action_utils = np.zeros(num_actions, dtype=np.float64)
            for i, a in enumerate(legal):
                child = state.apply(a)
                action_utils[i] = self._cfr(child, traverser, local_regret, local_strategy)
            node_util = float(np.dot(sigma, action_utils))

            if key not in local_regret:
                local_regret[key] = self._init_regret_from_blueprint(key)
            for i, ai in enumerate(legal_indices):
                regret = action_utils[i] - node_util
                local_regret[key][ai] += regret
            return node_util
        else:
            if key not in local_strategy:
                local_strategy[key] = self._init_strategy_from_blueprint(key)
            for i, ai in enumerate(legal_indices):
                local_strategy[key][ai] += sigma[i]
            idx = self.rng.choices(range(num_actions), weights=sigma.tolist())[0]
            child = state.apply(legal[idx])
            return self._cfr(child, traverser, local_regret, local_strategy)

    def _init_regret_from_blueprint(self, key: bytes) -> np.ndarray:
        """Warm start : copie les regrets de la blueprint si dispo."""
        if key in self.blueprint.regret_sum:
            bp = self.blueprint.regret_sum[key]
            if len(bp) >= NUM_ABSTRACT_ACTIONS:
                return bp.copy().astype(np.float64)
        return np.zeros(NUM_ABSTRACT_ACTIONS, dtype=np.float64)

    def _init_strategy_from_blueprint(self, key: bytes) -> np.ndarray:
        if key in self.blueprint.strategy_sum:
            bp = self.blueprint.strategy_sum[key]
            if len(bp) >= NUM_ABSTRACT_ACTIONS:
                return bp.copy().astype(np.float64)
        return np.zeros(NUM_ABSTRACT_ACTIONS, dtype=np.float64)

    def _get_strategy(self, key: bytes, legal_indices: List[int],
                      local_regret: Dict[bytes, np.ndarray]) -> np.ndarray:
        """Regret matching sur la table locale (avec fallback blueprint si jamais)."""
        regrets = None
        if key in local_regret:
            regrets = local_regret[key]
        elif key in self.blueprint.regret_sum:
            bp = self.blueprint.regret_sum[key]
            if len(bp) >= NUM_ABSTRACT_ACTIONS:
                regrets = bp

        n = len(legal_indices)
        if regrets is not None:
            masked = np.maximum(regrets[legal_indices], 0.0)
            total = masked.sum()
            if total > 0:
                return masked / total
        return np.full(n, 1.0 / n, dtype=np.float64)

    def _average_strategy(self, key: bytes,
                          local_strategy: Dict[bytes, np.ndarray],
                          legal_indices: List[int]) -> np.ndarray:
        n = len(legal_indices)
        # Priorité au local (raffiné), fallback blueprint, fallback uniforme
        if key in local_strategy:
            ss = local_strategy[key]
            masked = ss[legal_indices]
            if masked.sum() > 0:
                return (masked / masked.sum()).astype(np.float32)
        if key in self.blueprint.strategy_sum:
            ss = self.blueprint.strategy_sum[key]
            if len(ss) >= NUM_ABSTRACT_ACTIONS:
                masked = ss[legal_indices]
                if masked.sum() > 0:
                    return (masked / masked.sum()).astype(np.float32)
        return np.full(n, 1.0 / n, dtype=np.float32)
