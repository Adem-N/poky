"""
External-Sampling MCCFR pour NLHE N-max (3-max et plus).

Généralisation de mccfr_hunl.py pour des tables N joueurs.

ATTENTION THÉORIE :
  - En 2-player zero-sum (HU), MCCFR converge vers Nash garanti.
  - En N-player (3+), la garantie de convergence disparaît. Mais empiriquement
    (Pluribus 2019) ça reste très efficace.

CARD ABSTRACTION : préflop 169 classes + postflop 5 buckets/street.
ACTION ABSTRACTION : 5 actions (FOLD / CHECK_CALL / RAISE_HALF_POT / RAISE_POT / ALL_IN).

USAGE :
  trainer = NMaxMCCFRTrainer(num_players=3)
  trainer.train(iterations=10_000)
  trainer.save("data/blueprint_3max/mvp.pkl")
"""
import os
import pickle
import random
import time
from typing import Dict, List, Optional

import numpy as np

from poky.abstraction import (
    canonical_class, postflop_bucket,
    NUM_ABSTRACT_ACTIONS, encode_history, history_truncated,
)
from poky.engine import Action, Stage
from poky.training.nmax_state import (
    NMaxState, deal_new_nmax, reveal_nmax_board, terminal_utility_nmax,
    STARTING_STACK,
)


def nmax_state_infoset_key(state: NMaxState, actor: int) -> bytes:
    """Clé canonique d'info set pour `actor` à `state` (N-max version).
    Format : offset_from_btn(1) + stage(1) + card_bucket(2) + history."""
    # Position offset from BTN (= actor since pos 0 = BTN par convention NMaxState)
    offset = actor

    hole = state.hole_cards[actor]
    if state.stage == Stage.PREFLOP:
        bucket = canonical_class(hole[0], hole[1])
    else:
        bucket = postflop_bucket(list(hole), list(state.board))

    hist = history_truncated(list(state.action_history), max_actions=24)
    hist_blob = encode_history(hist)

    out = bytearray()
    out.append(offset & 0xFF)
    out.append(int(state.stage) & 0xFF)
    out.append(bucket & 0xFF)
    out.append((bucket >> 8) & 0xFF)
    out += hist_blob
    return bytes(out)


class NMaxMCCFRTrainer:
    """External-Sampling MCCFR pour NLHE N-max (N ≥ 2)."""

    def __init__(self, num_players: int = 3, seed: int = 42):
        self.num_players = num_players
        self.regret_sum: Dict[bytes, np.ndarray] = {}
        self.strategy_sum: Dict[bytes, np.ndarray] = {}
        self.rng = random.Random(seed)
        self.iterations_done = 0

    def _get_strategy(self, key: bytes, legal_indices: List[int]) -> np.ndarray:
        if key not in self.regret_sum:
            self.regret_sum[key] = np.zeros(NUM_ABSTRACT_ACTIONS, dtype=np.float32)
            self.strategy_sum[key] = np.zeros(NUM_ABSTRACT_ACTIONS, dtype=np.float32)
        regrets = self.regret_sum[key]
        positive = np.zeros(len(legal_indices), dtype=np.float32)
        for i, ai in enumerate(legal_indices):
            positive[i] = max(regrets[ai], 0.0)
        total = positive.sum()
        if total > 0:
            return positive / total
        n = len(legal_indices)
        return np.full(n, 1.0 / n, dtype=np.float32)

    def _maybe_reveal_board(self, state: NMaxState, deck_rest):
        if state.stage in (Stage.PREFLOP, Stage.END):
            return state
        return reveal_nmax_board(state, deck_rest)

    def _traverse(self, state: NMaxState, deck_rest, traverser: int) -> float:
        state = self._maybe_reveal_board(state, deck_rest)

        if state.is_terminal():
            if len(state.active_players()) > 1 and len(state.board) < 5:
                missing = deck_rest[len(state.board):5]
                state = state.with_board(state.board + missing)
            utils = terminal_utility_nmax(state)
            return utils[traverser]

        actor = state.to_act
        legal = state.legal_actions()
        if not legal:
            utils = terminal_utility_nmax(state)
            return utils[traverser]
        legal_indices = [int(a) for a in legal]
        num_actions = len(legal)

        key = nmax_state_infoset_key(state, actor)
        sigma = self._get_strategy(key, legal_indices)

        if actor == traverser:
            action_utils = np.zeros(num_actions, dtype=np.float32)
            for i, a in enumerate(legal):
                child = state.apply(a)
                action_utils[i] = self._traverse(child, deck_rest, traverser)
            node_util = float(np.dot(sigma, action_utils))
            for i, ai in enumerate(legal_indices):
                regret = action_utils[i] - node_util
                self.regret_sum[key][ai] += regret
            return node_util
        else:
            for i, ai in enumerate(legal_indices):
                self.strategy_sum[key][ai] += sigma[i]
            idx = self.rng.choices(range(num_actions), weights=sigma.tolist())[0]
            child = state.apply(legal[idx])
            return self._traverse(child, deck_rest, traverser)

    def train(self, iterations: int, log_every: int = 1000) -> List[int]:
        history = []
        start = time.time()
        for it in range(1, iterations + 1):
            traverser = it % self.num_players  # rotate over all N players
            state, deck_rest = deal_new_nmax(self.rng, self.num_players)
            self._traverse(state, deck_rest, traverser)
            self.iterations_done += 1
            if it % log_every == 0:
                elapsed = time.time() - start
                rate = it / elapsed
                history.append(len(self.regret_sum))
                print(f"  it {it:>6} | {rate:>5.0f} it/s | "
                      f"info sets : {len(self.regret_sum):,}", flush=True)
        return history

    def average_strategy(self, key: bytes, legal_indices: List[int]) -> np.ndarray:
        n = len(legal_indices)
        if key not in self.strategy_sum:
            return np.full(n, 1.0 / n, dtype=np.float32)
        ss = self.strategy_sum[key]
        if len(ss) < NUM_ABSTRACT_ACTIONS:
            return np.full(n, 1.0 / n, dtype=np.float32)
        masked = np.zeros(n, dtype=np.float32)
        for i, ai in enumerate(legal_indices):
            masked[i] = ss[ai]
        total = masked.sum()
        if total > 0:
            return masked / total
        return np.full(n, 1.0 / n, dtype=np.float32)

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "num_players": self.num_players,
                "regret_sum": self.regret_sum,
                "strategy_sum": self.strategy_sum,
                "iterations_done": self.iterations_done,
            }, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str, seed: int = 42) -> "NMaxMCCFRTrainer":
        with open(path, "rb") as f:
            data = pickle.load(f)
        trainer = cls(num_players=data["num_players"], seed=seed)
        trainer.regret_sum = data["regret_sum"]
        trainer.strategy_sum = data["strategy_sum"]
        trainer.iterations_done = data.get("iterations_done", 0)
        return trainer


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-players", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--log-every", type=int, default=1000)
    parser.add_argument("--save-path", default="data/blueprint_3max/mvp.pkl")
    args = parser.parse_args()
    trainer = NMaxMCCFRTrainer(num_players=args.num_players)
    print(f"Training {args.num_players}-max NLHE ES-MCCFR : {args.iterations} iters")
    trainer.train(args.iterations, log_every=args.log_every)
    trainer.save(args.save_path)
    print(f"\nSauvegarde : {args.save_path}")
    print(f"Total info sets : {len(trainer.regret_sum):,}")


if __name__ == "__main__":
    main()
