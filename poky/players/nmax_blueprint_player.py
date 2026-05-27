"""
NMaxBlueprintPlayer : consomme un blueprint MCCFR N-max (3-max et plus).

Différence avec BlueprintPlayer (HU) :
  - Aligne sur la convention rlcard N-max STANDARD (BTN = dealer, BTN acts first préflop)
  - Pas de flip nécessaire (contrairement à HU où dealer=BB chez rlcard)

L'offset = (player_id - dealer_id) % num_players :
  0 = BTN, 1 = SB, 2 = BB, 3+ = autres positions
Cohérent avec la convention NMaxState (pos 0 = BTN).
"""
import os
import random
from typing import Optional

import numpy as np

from poky.abstraction import (
    canonical_class, postflop_bucket,
    encode_history, history_truncated,
)
from poky.engine import Action, Observation, Stage
from poky.players.base import Player, ActionEvent
from poky.players.heuristic import HeuristicPlayer
from poky.training.mccfr_nmax import NMaxMCCFRTrainer


class NMaxBlueprintPlayer(Player):
    """Joue selon un blueprint MCCFR pré-entraîné pour N-max NLHE."""
    name = "nmax_blueprint"

    def __init__(self, model_path: str, fallback_seed: Optional[int] = None,
                 sample_seed: Optional[int] = None):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Blueprint introuvable : {model_path}")
        self.trainer = NMaxMCCFRTrainer.load(model_path)
        self.fallback = HeuristicPlayer(seed=fallback_seed)
        self.rng = random.Random(sample_seed if sample_seed is not None else 0)
        self._action_history = []
        self._lookup_hits = 0
        self._lookup_misses = 0

    def reset(self) -> None:
        self._action_history = []

    def observe_action(self, event: ActionEvent) -> None:
        self._action_history.append((event.actor, int(event.action)))

    def act(self, obs: Observation) -> Action:
        if obs.num_players != self.trainer.num_players:
            # Blueprint trained for a different table size
            return self.fallback.act(obs)

        N = obs.num_players

        def seat_to_offset(seat_id: int) -> int:
            return (seat_id - obs.dealer_id) % N

        offset = seat_to_offset(obs.player_id)

        try:
            if obs.stage == Stage.PREFLOP:
                bucket = canonical_class(obs.hole_cards[0], obs.hole_cards[1])
            else:
                bucket = postflop_bucket(list(obs.hole_cards),
                                         list(obs.community_cards))
        except Exception:
            return self.fallback.act(obs)

        history_positional = [
            (seat_to_offset(seat), act_id)
            for seat, act_id in self._action_history
        ]
        history_trunc = history_truncated(history_positional, max_actions=24)
        hist_blob = encode_history(history_trunc)

        key = bytearray()
        key.append(offset & 0xFF)
        key.append(int(obs.stage) & 0xFF)
        key.append(bucket & 0xFF)
        key.append((bucket >> 8) & 0xFF)
        key += hist_blob
        key_bytes = bytes(key)

        legal = obs.legal_actions
        legal_indices = [int(a) for a in legal]
        if key_bytes in self.trainer.strategy_sum:
            self._lookup_hits += 1
            avg = self.trainer.average_strategy(key_bytes, legal_indices)
            if avg.sum() > 0:
                idx = self.rng.choices(range(len(legal)),
                                       weights=avg.tolist())[0]
                return legal[idx]
        self._lookup_misses += 1
        return self.fallback.act(obs)

    @property
    def hit_rate(self) -> float:
        total = self._lookup_hits + self._lookup_misses
        return self._lookup_hits / max(total, 1)
