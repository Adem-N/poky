"""Baseline : joue uniformément au hasard parmi les actions légales."""
import random

from poky.engine import Action, Observation
from poky.players.base import Player


class RandomPlayer(Player):
    name = "random"

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def act(self, obs: Observation) -> Action:
        return self.rng.choice(obs.legal_actions)
