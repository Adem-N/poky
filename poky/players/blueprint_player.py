"""
BlueprintPlayer : utilise une stratégie MCCFR entraînée pour décider.

Workflow :
  1. Charge une strategy table (poky.training.mccfr_hunl.HUNLMCCFRTrainer)
  2. À chaque act(), reconstruit la key info-set (position + stage + card_bucket + history)
  3. Lookup avg_strategy, sample action
  4. Fallback : si key absente → HeuristicPlayer (pour les info sets pas appris)

LIMITATION ACTUELLE : conçu pour heads-up (2 joueurs). Pour 3-max+, on entraînera
un blueprint séparé (Phase 5).
"""
import os
import random
from typing import List, Optional, Tuple

import numpy as np

from poky.abstraction import (
    canonical_class, postflop_bucket,
    encode_history, history_truncated, action_index, index_to_action,
    ABSTRACT_ACTIONS, NUM_ABSTRACT_ACTIONS,
)
from poky.engine import Action, Observation, Stage
from poky.players.base import Player, ActionEvent
from poky.players.heuristic import HeuristicPlayer
from poky.training.mccfr_hunl import HUNLMCCFRTrainer


class BlueprintPlayer(Player):
    """Joue selon une stratégie MCCFR pré-entraînée (HU NLHE).
    Fallback HeuristicPlayer si l'info set est inconnu (jamais visité en training)."""
    name = "blueprint"

    def __init__(self, model_path: str, fallback_seed: Optional[int] = None,
                 sample_seed: Optional[int] = None):
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Blueprint introuvable : {model_path}. Entraîne d'abord avec "
                f"`python -m poky.training.mccfr_hunl`."
            )
        self.trainer = HUNLMCCFRTrainer.load(model_path)
        self.fallback = HeuristicPlayer(seed=fallback_seed)
        self.rng = random.Random(sample_seed if sample_seed is not None else 0)
        # État par main (reset avant chaque nouvelle main)
        self._action_history: List[Tuple[int, int]] = []
        self._dealer_id: Optional[int] = None
        self._lookup_hits = 0
        self._lookup_misses = 0

    def reset(self) -> None:
        self._action_history = []
        self._dealer_id = None

    def observe_action(self, event: ActionEvent) -> None:
        """Track les actions de tous les joueurs pour reconstruire la history."""
        # Convertit seat_id → offset depuis le dealer (= position 0..N-1)
        # Pour le moment on n'a pas dealer_id direct ici. On utilisera obs.dealer_id
        # lors du prochain act() pour rebaser. En attendant on stocke (seat, action).
        self._action_history.append((event.actor, int(event.action)))

    def act(self, obs: Observation) -> Action:
        if obs.num_players != 2:
            # Notre blueprint est entraîné HU uniquement
            return self.fallback.act(obs)

        # CONVENTION rlcard HU : dealer == BB (non-standard).
        # MCCFR convention : role 0 = SB (first to act préflop), role 1 = BB.
        # Donc : role = 1 si player_id == dealer_id (= BB), sinon 0 (= SB).
        def seat_to_role(seat_id: int) -> int:
            return 1 if seat_id == obs.dealer_id else 0

        offset = seat_to_role(obs.player_id)

        # Bucket de la main
        try:
            if obs.stage == Stage.PREFLOP:
                bucket = canonical_class(obs.hole_cards[0], obs.hole_cards[1])
            else:
                bucket = postflop_bucket(list(obs.hole_cards),
                                         list(obs.community_cards))
        except Exception:
            return self.fallback.act(obs)

        # Convertit l'action_history (seat-based) en (role-based) pour matcher
        # la convention MCCFR (role 0 = SB, role 1 = BB)
        history_positional = [
            (seat_to_role(seat), act_id)
            for seat, act_id in self._action_history
        ]
        history_trunc = history_truncated(history_positional, max_actions=24)
        hist_blob = encode_history(history_trunc)

        # Reconstruit la key exactement comme state_infoset_key
        key = bytearray()
        key.append(offset & 0xFF)
        key.append(int(obs.stage) & 0xFF)
        key.append(bucket & 0xFF)
        key.append((bucket >> 8) & 0xFF)
        key += hist_blob
        key_bytes = bytes(key)

        # Lookup
        legal = obs.legal_actions
        num_actions = len(legal)
        if key_bytes in self.trainer.strategy_sum:
            ss = self.trainer.strategy_sum[key_bytes]
            # Si la taille de la stratégie sauvée matche les legal actions courantes,
            # on l'utilise. Sinon (state space slightly diff), fallback.
            if len(ss) == num_actions:
                self._lookup_hits += 1
                total = ss.sum()
                if total > 0:
                    avg = ss / total
                else:
                    avg = np.full(num_actions, 1.0 / num_actions, dtype=np.float32)
                idx = self.rng.choices(range(num_actions),
                                       weights=avg.tolist())[0]
                return legal[idx]
        self._lookup_misses += 1
        return self.fallback.act(obs)

    # ---- Diagnostics ----------------------------------------------------

    @property
    def hit_rate(self) -> float:
        total = self._lookup_hits + self._lookup_misses
        return self._lookup_hits / max(total, 1)
