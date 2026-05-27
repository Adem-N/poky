"""
4 bots représentant les archétypes humains classiques en NLHE.
Servent de "gauntlet" pour mesurer la qualité du bot champion :
si tu bats les 4 de manière statistiquement significative, tu bats
en pratique 95% des joueurs humains récréatifs.

Référence : taxonomie classique TAG/LAG/Nit/Maniac (cf. Sklansky, Harrington).
"""
import random
from typing import Optional

from poky.engine import Action, Observation, PositionType, Stage
from poky.equity import monte_carlo_equity
from poky.players.base import Player
from poky.players.heuristic import classify_preflop


def _safe(action: Action, obs: Observation) -> Action:
    """Replie sur une action légale si celle voulue ne l'est pas."""
    if action in obs.legal_actions:
        return action
    if action == Action.RAISE_POT and Action.RAISE_HALF_POT in obs.legal_actions:
        return Action.RAISE_HALF_POT
    if action == Action.RAISE_HALF_POT and Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    if action == Action.ALL_IN and Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    if Action.CHECK_CALL in obs.legal_actions:
        return Action.CHECK_CALL
    return Action.FOLD


# ============================================================================
# TightPassivePlayer ("nit" / "rock")
# Le joueur ultra-prudent. Ne joue que premium. Call seulement, jamais raise.
# Type "papy" du club de poker. Facile à exploiter en lui volant ses blinds.
# ============================================================================

class TightPassivePlayer(Player):
    name = "tight_passive"

    def __init__(self, mc_simulations: int = 400, seed: Optional[int] = None):
        self.mc_simulations = mc_simulations
        self.rng = random.Random(seed)

    def act(self, obs: Observation) -> Action:
        if obs.stage == Stage.PREFLOP:
            tier = classify_preflop(obs.hole_cards)
            if tier <= 2:                      # premium ou strong
                return _safe(Action.CHECK_CALL, obs)
            if obs.to_call == 0:
                return _safe(Action.CHECK_CALL, obs)
            return Action.FOLD

        # Postflop : call seulement quand on a vraiment de la main
        equity = monte_carlo_equity(
            obs.hole_cards, obs.community_cards,
            max(1, obs.num_active_opponents),
            simulations=self.mc_simulations, rng=self.rng,
        )
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0
        if obs.to_call == 0:
            return _safe(Action.CHECK_CALL, obs)
        if equity > pot_odds + 0.10:           # exige une marge confortable
            return _safe(Action.CHECK_CALL, obs)
        return Action.FOLD


# ============================================================================
# TightAggressivePlayer ("TAG")
# L'archétype du régulier compétent. Joue 15% de mains, mais frappe fort
# quand il joue. Difficile à battre sans aussi être agressif.
# ============================================================================

class TightAggressivePlayer(Player):
    name = "tag"

    def __init__(self, mc_simulations: int = 500, seed: Optional[int] = None):
        self.mc_simulations = mc_simulations
        self.rng = random.Random(seed)

    def act(self, obs: Observation) -> Action:
        if obs.stage == Stage.PREFLOP:
            tier = classify_preflop(obs.hole_cards)
            if tier == 1:                       # premium → raise pot
                return _safe(Action.RAISE_POT, obs)
            if tier == 2:                       # strong → raise demi-pot, call si raise
                if obs.to_call == 0:
                    return _safe(Action.RAISE_HALF_POT, obs)
                return _safe(Action.CHECK_CALL, obs)
            if tier == 3 and obs.to_call == 0:
                return _safe(Action.RAISE_HALF_POT, obs)
            if tier == 3 and obs.my_position_type == PositionType.BIG_BLIND and obs.to_call <= 2 * obs.big_blind:
                return _safe(Action.CHECK_CALL, obs)
            return _safe(Action.CHECK_CALL if obs.to_call == 0 else Action.FOLD, obs)

        # Postflop : value-bet agressif
        equity = monte_carlo_equity(
            obs.hole_cards, obs.community_cards,
            max(1, obs.num_active_opponents),
            simulations=self.mc_simulations, rng=self.rng,
        )
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0
        if equity > 0.75:
            return _safe(Action.RAISE_POT, obs)
        if equity > 0.55:
            return _safe(Action.RAISE_HALF_POT, obs)
        if equity > pot_odds + 0.05:
            return _safe(Action.CHECK_CALL, obs)
        if obs.to_call == 0:
            return _safe(Action.CHECK_CALL, obs)
        return Action.FOLD


# ============================================================================
# LooseAggressivePlayer ("LAG")
# Joue beaucoup de mains, met la pression constamment. Difficile à lire.
# C'est le profil typique du joueur online compétent en short stack.
# ============================================================================

class LooseAggressivePlayer(Player):
    name = "lag"

    def __init__(self, mc_simulations: int = 500, seed: Optional[int] = None,
                 aggression_freq: float = 0.5):
        self.mc_simulations = mc_simulations
        self.aggression_freq = aggression_freq
        self.rng = random.Random(seed)

    def act(self, obs: Observation) -> Action:
        if obs.stage == Stage.PREFLOP:
            tier = classify_preflop(obs.hole_cards)
            if tier <= 2:
                return _safe(Action.RAISE_POT, obs)
            if tier == 3:
                if self.rng.random() < 0.75:
                    return _safe(Action.RAISE_HALF_POT, obs)
                return _safe(Action.CHECK_CALL, obs)
            # tier 4 : tente de voler en position
            if obs.to_call == 0:
                if self.rng.random() < self.aggression_freq:
                    return _safe(Action.RAISE_HALF_POT, obs)
                return _safe(Action.CHECK_CALL, obs)
            if obs.my_position_type == PositionType.BIG_BLIND and obs.to_call <= 2 * obs.big_blind:
                if self.rng.random() < 0.4:
                    return _safe(Action.CHECK_CALL, obs)
            return Action.FOLD

        # Postflop : bet large même sans avoir grand-chose
        equity = monte_carlo_equity(
            obs.hole_cards, obs.community_cards,
            max(1, obs.num_active_opponents),
            simulations=self.mc_simulations, rng=self.rng,
        )
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0
        if equity > 0.65:
            return _safe(Action.RAISE_POT, obs)
        if equity > 0.40 and self.rng.random() < self.aggression_freq:
            return _safe(Action.RAISE_HALF_POT, obs)
        if equity > pot_odds:
            return _safe(Action.CHECK_CALL, obs)
        if obs.to_call == 0 and self.rng.random() < 0.3:
            return _safe(Action.RAISE_HALF_POT, obs)  # bluff freq élevée
        if obs.to_call == 0:
            return _safe(Action.CHECK_CALL, obs)
        return Action.FOLD


# ============================================================================
# ManiacPlayer ("fish déchaîné" / "spew")
# Raise/bet quasi tout le temps. Exploitable en serrant et call-down.
# Représente le pire des recreational players, mais aussi le plus dangereux
# en variance courte.
# ============================================================================

class ManiacPlayer(Player):
    name = "maniac"

    def __init__(self, seed: Optional[int] = None, allin_freq: float = 0.15):
        self.rng = random.Random(seed)
        self.allin_freq = allin_freq

    def act(self, obs: Observation) -> Action:
        if self.rng.random() < self.allin_freq and Action.ALL_IN in obs.legal_actions:
            return Action.ALL_IN
        # En priorité, raise. Sinon call. Sinon fold (très rare).
        for preferred in (Action.RAISE_POT, Action.RAISE_HALF_POT,
                          Action.CHECK_CALL):
            if preferred in obs.legal_actions:
                return preferred
        return Action.FOLD
