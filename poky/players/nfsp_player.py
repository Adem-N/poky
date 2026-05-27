"""
NFSPPlayer — wraps un NFSPAgent entraîné dans notre interface Player.

L'agent est chargé depuis un .pth produit par poky.training.nfsp_train.

Pour intégrer un NFSPAgent rlcard avec notre Game (qui ne sait gérer que des
Action enum), on traduit obs → état brut rlcard → predict → Action enum.
Comme on ne peut pas passer le 'state' brut au NFSPAgent depuis dehors,
on conserve le mécanisme rlcard : on regarde quel est l'index d'action de
plus grande proba parmi les actions légales.
"""
import os
from typing import Optional

import numpy as np
import torch

from poky.engine import Action, Observation
from poky.players.base import Player
from poky.players.heuristic import HeuristicPlayer


class NFSPPlayer(Player):
    """
    Charge un agent NFSP entraîné et l'utilise pour décider.
    Fallback sur HeuristicPlayer si la prédiction est aberrante.

    Pour utiliser :
        nfsp = NFSPPlayer(model_path="data/nfsp_3max/agent_0_latest.pth")
        # ou : NFSPPlayer.from_checkpoint_dir("data/nfsp_3max", agent_index=0)
    """
    name = "nfsp"

    def __init__(self, model_path: str, device: Optional[str] = "cpu",
                 fallback_seed: Optional[int] = None):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modèle NFSP introuvable : {model_path}")
        # rlcard sauve l'agent complet (architecture + poids) via torch.save
        self.agent = torch.load(model_path, map_location=device, weights_only=False)
        self.agent.set_device(device)
        self.fallback = HeuristicPlayer(seed=fallback_seed)
        self._last_raw_state = None  # mis à jour par le bridge

    @classmethod
    def from_checkpoint_dir(cls, directory: str, agent_index: int = 0,
                            tag: str = "latest", **kwargs):
        path = os.path.join(directory, f"agent_{agent_index}_{tag}.pth")
        return cls(model_path=path, **kwargs)

    def act(self, obs: Observation) -> Action:
        """Délègue au NFSPAgent. Fallback heuristique si pas de raw_state."""
        if obs.raw_state is None:
            return self.fallback.act(obs)
        try:
            action_id, _ = self.agent.eval_step(obs.raw_state)
            action = Action(int(action_id))
            if action in obs.legal_actions:
                return action
            return self.fallback.act(obs)
        except Exception:
            return self.fallback.act(obs)
