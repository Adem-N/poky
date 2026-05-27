"""
Interface commune à tous les bots.

Un Player reçoit une Observation et renvoie une Action.
Optionnellement, il peut observer les actions des autres pour faire de
l'opponent modeling.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from poky.engine import Action, Observation, Stage


@dataclass
class ActionEvent:
    """Événement d'action publique observable par tous les joueurs à la table.

    Sert uniquement aux infos publiques — pas de fuite des hole cards des autres.
    """
    actor: int                       # qui a joué
    action: Action                   # ce qu'il a fait
    stage: Stage                     # à quelle street
    to_call_before: int              # combien il devait suivre
    all_committed_before: List[int]  # mises totales avant son action
    big_blind: int


class Player(ABC):
    name: str = "player"

    @abstractmethod
    def act(self, obs: Observation) -> Action:
        """Choisit une action parmi obs.legal_actions."""
        ...

    def reset(self) -> None:
        """Appelé avant chaque nouvelle main. Override si état interne à reset."""
        pass

    def observe_action(self, event: ActionEvent) -> None:
        """
        Appelé par l'arène pour CHAQUE action de CHAQUE joueur (y compris soi).
        Permet de faire du tracking d'adversaire (VPIP, PFR, AF, etc.).
        Override pour utiliser ; default = no-op.
        """
        pass
