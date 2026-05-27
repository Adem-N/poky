"""
External-Sampling MCCFR pour Heads-Up NLHE.

ALGO (Lanctot et al. 2009) :
  - Chaque itération choisit un "traverser" (P0 ou P1, alterné).
  - On parcourt le game tree :
    * chance node (deal initial / révélation board) : on échantillonne UN outcome
    * noeud opposant : on échantillonne UNE action selon current strategy
    * noeud traverseur : on énumère TOUTES les actions, calcule les regrets
  - Mise à jour des regrets au traverseur, strategy_sum à chaque visite.

CARD ABSTRACTION :
  - Préflop : canonical_class (169 classes)
  - Postflop : postflop_bucket (5 buckets par street)

ACTION ABSTRACTION : déjà 5 actions discrètes via HUNLState.legal_actions().

STORAGE :
  - regret_sum, strategy_sum : dict[bytes, np.ndarray] en float32
  - Checkpoint via pickle (zstd compression deferred to optimization pass).

USAGE :
  trainer = HUNLMCCFRTrainer()
  trainer.train(iterations=10_000, log_every=1000)
  trainer.save("data/blueprint_hu/checkpoint_10k.pkl")
"""
import os
import pickle
import random
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from poky.abstraction import (
    canonical_class, postflop_bucket,
    NUM_ABSTRACT_ACTIONS, ABSTRACT_ACTIONS,
    action_index, encode_history, history_truncated,
)
from poky.engine import Action, Stage
from poky.training.hunl_state import (
    HUNLState, deal_new_hand, reveal_board_for_stage, terminal_utility,
    STARTING_STACK,
)


def state_infoset_key(state: HUNLState, actor: int) -> bytes:
    """
    Clé canonique de l'info set de `actor` à `state`.
    Combine : position (0=SB,1=BB), stage, card_bucket, history tronquée.
    """
    hole = state.hole_cards[actor]
    if state.stage == Stage.PREFLOP:
        bucket = canonical_class(hole[0], hole[1])
    else:
        bucket = postflop_bucket(list(hole), list(state.board))

    # Truncate history to last 24 actions for compactness
    hist = history_truncated(list(state.action_history), max_actions=24)
    hist_blob = encode_history(hist)

    out = bytearray()
    out.append(actor & 0xFF)
    out.append(int(state.stage) & 0xFF)
    out.append(bucket & 0xFF)
    out.append((bucket >> 8) & 0xFF)
    out += hist_blob
    return bytes(out)


class HUNLMCCFRTrainer:
    """External-Sampling MCCFR pour Heads-Up NLHE."""

    def __init__(self, seed: int = 42):
        # Strategy table : info_set_key -> (regret_sum, strategy_sum)
        # On stocke comme 2 dicts pour ne pas dupliquer la len(actions) variable.
        self.regret_sum: Dict[bytes, np.ndarray] = {}
        self.strategy_sum: Dict[bytes, np.ndarray] = {}
        self.rng = random.Random(seed)
        self.iterations_done = 0

    def _get_strategy(self, key: bytes, legal_indices: List[int]) -> np.ndarray:
        """Current strategy via regret matching. Toutes les tables sont de
        taille fixe NUM_ABSTRACT_ACTIONS (5) — illegal actions ont weight 0.
        Retourne un vecteur de taille len(legal_indices) (probabilités sur
        les actions légales courantes, somme à 1)."""
        if key not in self.regret_sum:
            # Toujours alloue 5 entries
            self.regret_sum[key] = np.zeros(NUM_ABSTRACT_ACTIONS, dtype=np.float32)
            self.strategy_sum[key] = np.zeros(NUM_ABSTRACT_ACTIONS, dtype=np.float32)
        regrets = self.regret_sum[key]
        # Masque par actions légales courantes
        positive = np.zeros(len(legal_indices), dtype=np.float32)
        for i, ai in enumerate(legal_indices):
            r = regrets[ai]
            positive[i] = max(r, 0.0)
        total = positive.sum()
        if total > 0:
            return positive / total
        n = len(legal_indices)
        return np.full(n, 1.0 / n, dtype=np.float32)

    def _maybe_reveal_board(self, state: HUNLState,
                            deck_rest: Tuple[str, ...]) -> HUNLState:
        """Si le stage demande un board (FLOP/TURN/RIVER), distribue."""
        if state.stage == Stage.PREFLOP or state.stage == Stage.END:
            return state
        return reveal_board_for_stage(state, deck_rest)

    def _traverse(self, state: HUNLState, deck_rest: Tuple[str, ...],
                  traverser: int) -> float:
        """
        Parcours récursif d'un tree, met à jour regrets pour traverser.
        Retourne l'utility espérée pour traverser à cet état.
        """
        state = self._maybe_reveal_board(state, deck_rest)

        if state.is_terminal():
            # Si on est à END mais board incomplet, complète (all-in run-out)
            if not any(state.folded) and len(state.board) < 5:
                # Slice par indice absolu pour éviter doublons
                missing = deck_rest[len(state.board):5]
                state = state.with_board(state.board + missing)
            u = terminal_utility(state)
            return u[traverser]

        actor = state.to_act
        legal = state.legal_actions()
        if not legal:
            u = terminal_utility(state)
            return u[traverser]
        legal_indices = [int(a) for a in legal]   # 0..4 per Action enum
        num_actions = len(legal)

        key = state_infoset_key(state, actor)
        sigma = self._get_strategy(key, legal_indices)   # array of len(legal)

        if actor == traverser:
            # Énumère toutes les actions, calcule regrets
            action_utils = np.zeros(num_actions, dtype=np.float32)
            for i, a in enumerate(legal):
                child = state.apply(a)
                action_utils[i] = self._traverse(child, deck_rest, traverser)
            node_util = float(np.dot(sigma, action_utils))

            # Update regrets : tables 5-large, indexées par enum value
            for i, ai in enumerate(legal_indices):
                regret = action_utils[i] - node_util
                self.regret_sum[key][ai] += regret
            return node_util
        else:
            # Échantillonne UNE action selon sigma, met à jour strategy_sum
            for i, ai in enumerate(legal_indices):
                self.strategy_sum[key][ai] += sigma[i]
            idx = self.rng.choices(range(num_actions), weights=sigma.tolist())[0]
            child = state.apply(legal[idx])
            return self._traverse(child, deck_rest, traverser)

    def train(self, iterations: int, log_every: int = 1000) -> List[float]:
        """Lance N itérations. Retourne la liste des |info_sets| à chaque log step."""
        history = []
        start = time.time()
        for it in range(1, iterations + 1):
            # Alterne le traverseur entre P0 et P1
            traverser = it % 2
            # Deal une nouvelle main (sample chance node racine)
            state, deck_rest = deal_new_hand(self.rng)
            self._traverse(state, deck_rest, traverser)
            self.iterations_done += 1

            if it % log_every == 0:
                elapsed = time.time() - start
                rate = it / elapsed
                history.append(len(self.regret_sum))
                print(f"  it {it:>6} | {rate:>5.0f} it/s | "
                      f"info sets vus : {len(self.regret_sum):,}", flush=True)
        return history

    # ---- Inference -------------------------------------------------------

    def average_strategy(self, key: bytes,
                         legal_indices: List[int]) -> np.ndarray:
        """Stratégie moyenne pour les actions légales courantes.
        Lit la table (taille 5 nouveau format), masque, renormalise.
        Si ancien format incompatible, retourne uniforme (fallback)."""
        n = len(legal_indices)
        if key not in self.strategy_sum:
            return np.full(n, 1.0 / n, dtype=np.float32)
        ss = self.strategy_sum[key]
        if len(ss) < NUM_ABSTRACT_ACTIONS:
            # Ancien format variable-size : pas indexable par action enum value
            return np.full(n, 1.0 / n, dtype=np.float32)
        masked = np.zeros(n, dtype=np.float32)
        for i, ai in enumerate(legal_indices):
            masked[i] = ss[ai]
        total = masked.sum()
        if total > 0:
            return masked / total
        return np.full(n, 1.0 / n, dtype=np.float32)

    # ---- Persistence -----------------------------------------------------

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "regret_sum": self.regret_sum,
                "strategy_sum": self.strategy_sum,
                "iterations_done": self.iterations_done,
            }, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str, seed: int = 42) -> "HUNLMCCFRTrainer":
        trainer = cls(seed=seed)
        with open(path, "rb") as f:
            data = pickle.load(f)
        trainer.regret_sum = data["regret_sum"]
        trainer.strategy_sum = data["strategy_sum"]
        trainer.iterations_done = data.get("iterations_done", 0)
        return trainer


# ---- CLI -----------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Train ES-MCCFR sur HU NLHE.")
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--log-every", type=int, default=1000)
    parser.add_argument("--save-path", default="data/blueprint_hu/mvp.pkl")
    args = parser.parse_args()

    trainer = HUNLMCCFRTrainer()
    print(f"Training HU NLHE ES-MCCFR : {args.iterations} iters")
    trainer.train(args.iterations, log_every=args.log_every)
    trainer.save(args.save_path)
    print(f"\nSauvegarde : {args.save_path}")
    print(f"Total info sets : {len(trainer.regret_sum):,}")


if __name__ == "__main__":
    main()
