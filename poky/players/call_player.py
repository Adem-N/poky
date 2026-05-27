"""
Baseline : "calling station" — suit toujours, ne relance jamais.
Référence canonique en poker AI : tout bot sérieux DOIT battre ce joueur
de manière statistiquement significative.
"""
from poky.engine import Action, Observation
from poky.players.base import Player


class AlwaysCallPlayer(Player):
    name = "call"

    def act(self, obs: Observation) -> Action:
        if Action.CHECK_CALL in obs.legal_actions:
            return Action.CHECK_CALL
        return Action.FOLD  # ne devrait jamais arriver mais sécurité
