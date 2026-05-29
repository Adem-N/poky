"""SolverOraclePlayer — Tier 3 layer that consults the TexasSolver cache.

Decision pipeline:
  1. Preflop  -> delegate to ExpertOnlyPlayer (Tier 1 ranges already validated)
  2. Postflop -> build SpotKey from Observation, lookup in CacheDB
       -> hit  : sample action from the GTO mixed strategy
       -> miss : fallback to ExpertOnlyPlayer (Tier 2 heuristic / postflop_rules)
  3. Translate solver-side actions ("CHECK", "BET 3.5") to poky Action enum
     via observation_to_spot.translate_solver_action.

The Player tracks coverage counters (hit / miss / preflop) so we can audit
how often the cache is actually consulted — the same diagnostic pattern as
ExpertOnlyPlayer.

For MVP, the cache hit rate is expected to be very low because:
 - the cache only holds a few demo spots
 - the SpotKey uses placeholder ranges, not real GTO ranges per position
Real coverage comes in Z2.5 (full cache build with proper range atlas).
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import List, Optional, Tuple

from poky.engine import Action, Observation, Stage
from poky.players.base import ActionEvent, Player
from poky.players.expert_only import ExpertOnlyPlayer
from poky.solver.cache_db import CacheDB
from poky.solver.observation_to_spot import (
    observation_to_spot_key,
    translate_solver_action,
)


class SolverOraclePlayer(Player):
    """GTO oracle player backed by a TexasSolver SQLite cache.

    Args:
        cache: open `CacheDB` for postflop lookups
        seed: RNG seed for stochastic sampling
        fallback_player: optional pre-built ExpertOnlyPlayer; if omitted,
            we instantiate one with the same seed
    """

    name = "solver_oracle"

    def __init__(
        self,
        cache: CacheDB,
        seed: Optional[int] = None,
        fallback_player: Optional[ExpertOnlyPlayer] = None,
    ):
        self.cache = cache
        self.rng = random.Random(seed)
        self.fallback = fallback_player or ExpertOnlyPlayer(seed=seed)

        # Coverage diagnostics.
        self.preflop_decisions = 0
        self.postflop_cache_hits = 0
        self.postflop_cache_misses = 0
        self.postflop_translation_misses = 0
        self.action_dist: dict = defaultdict(int)
        self._preflop_last_raiser: Optional[int] = None

    def act(self, obs: Observation) -> Action:
        if obs.stage == Stage.PREFLOP:
            self.preflop_decisions += 1
            return self.fallback.act(obs)

        is_pfa = (self._preflop_last_raiser is not None
                  and self._preflop_last_raiser == obs.player_id)
        spot_key = observation_to_spot_key(obs, is_pfa=is_pfa)
        if spot_key is None:
            # Couldn't build a SpotKey (multi-way, weird state) -> fallback.
            self.postflop_cache_misses += 1
            action = self.fallback.act(obs)
            self.action_dist[action] += 1
            return action

        sol = self.cache.get(spot_key)
        if sol is None:
            self.postflop_cache_misses += 1
            action = self.fallback.act(obs)
            self.action_dist[action] += 1
            return action

        # Cache hit — sample an action from the aggregated mixed strategy.
        action = self._sample_from_solution(sol, obs)
        if action is None:
            # Translation gave no legal poky Action -> fallback.
            self.postflop_cache_hits += 1            # cache had data, but
            self.postflop_translation_misses += 1    # we couldn't use it
            action = self.fallback.act(obs)
        else:
            self.postflop_cache_hits += 1
        self.action_dist[action] += 1
        return action

    def _sample_from_solution(self, sol, obs: Observation) -> Optional[Action]:
        """Aggregate solver per-action probabilities into poky Action buckets,
        then sample. Returns None if no action is mappable."""
        # Group solver actions by their poky-Action equivalent.
        bucket_probs: dict = defaultdict(float)
        for label, prob in sol.aggregated_strategy:
            translated = translate_solver_action(label, obs=obs)
            if translated is None:
                continue
            bucket_probs[translated] += prob

        if not bucket_probs:
            return None

        # Renormalize and sample.
        total = sum(bucket_probs.values())
        if total <= 0:
            return None
        items = list(bucket_probs.items())
        r = self.rng.random() * total
        cum = 0.0
        for act, p in items:
            cum += p
            if r <= cum:
                return act
        return items[-1][0]

    def observe_action(self, event: ActionEvent) -> None:
        if event.stage == Stage.PREFLOP and event.action in (
            Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN,
        ):
            self._preflop_last_raiser = event.actor
        # Forward to fallback too so its own state stays in sync.
        self.fallback.observe_action(event)

    def reset(self) -> None:
        self._preflop_last_raiser = None
        self.fallback.reset()

    def coverage_stats(self) -> dict:
        """Snapshot of cache hit/miss for the current run."""
        total_post = self.postflop_cache_hits + self.postflop_cache_misses
        hit_rate = (self.postflop_cache_hits / total_post) if total_post else 0.0
        return {
            "preflop_decisions": self.preflop_decisions,
            "postflop_cache_hits": self.postflop_cache_hits,
            "postflop_cache_misses": self.postflop_cache_misses,
            "postflop_translation_misses": self.postflop_translation_misses,
            "postflop_total": total_post,
            "postflop_hit_rate": hit_rate,
            "action_dist": dict(self.action_dist),
        }
