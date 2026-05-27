"""
HeuristicPlayer — bot heuristique de référence pour 3-max NLHE.

Approche : "tight aggressive sans bluffs débiles". L'expérience du tournoi
a montré que les profils trop agressifs (3-bet systématique, c-bet à 65%,
steal en BTN) régressent fortement contre les bots passifs (calling
stations, maniacs). Ce bot reste calibré pour battre **tous** les
archétypes mesurés, pas seulement les bons.

Logique :
  • Préflop : classification de la main en 4 tiers + décision basée sur la
    situation (open / face à un raise / face à un 3bet).
  • Postflop : Monte Carlo equity vs N adversaires actifs + pot odds.
    Value bet large quand on a vraiment, fold/check sinon.
  • River value-bet plus généreux car pas d'implied odds.
  • 4-bet shove avec tier 1 face à un 3bet (situation rare mais énorme EV).

Pourquoi pas plus de bluffs : sans opponent modeling, bluffer uniformément
perd vs calling stations. Le bluff_freq reste bas et ciblé sur les checks.

Cible mesurée (cf. tournament report) : BEATS tous les archétypes ou DRAW.
Le DRAW vs TAG/LAG sera levé par CFR, pas par plus d'heuristique.
"""
import random
from typing import Optional

from poky.engine import Action, Observation, Position, PositionType, Stage
from poky.equity import monte_carlo_equity
from poky.players.base import Player


# Conversion rang lettre -> valeur numérique
_RANK_VAL = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
             "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def classify_preflop(hole_rlcard) -> int:
    """
    Retourne le tier de la main préflop :
      1 = premium (TT+, AKo, AKs, AQs)              ≈ 4% des mains
      2 = strong  (77-99, AQo, ATs-AJs, KJs+, KQo)  ≈ 8%
      3 = playable (22-66, suited aces, broadway,
                    suited connectors, KTo+)         ≈ 25%
      4 = trash (tout le reste)
    Format rlcard : "HQ" = Dame de Cœur. Suit en position 0, rang en position 1.
    """
    suits = [c[0] for c in hole_rlcard]
    ranks = sorted([_RANK_VAL[c[1]] for c in hole_rlcard], reverse=True)
    high, low = ranks
    suited = suits[0] == suits[1]
    pair = high == low

    if pair and high >= 10:                       # TT+
        return 1
    if high == 14 and low == 13:                  # AK
        return 1
    if high == 14 and low == 12 and suited:       # AQs
        return 1

    if pair and high >= 7:                        # 77-99
        return 2
    if high == 14 and low == 12:                  # AQo
        return 2
    if high == 14 and low >= 10 and suited:       # ATs, AJs
        return 2
    if high == 13 and low >= 11 and suited:       # KJs, KQs
        return 2
    if high == 13 and low == 12:                  # KQo
        return 2

    if pair:                                      # 22-66
        return 3
    if suited:
        if high == 14:                            # tous les suited aces
            return 3
        if high == 13 and low >= 9:               # K9s-KTs
            return 3
        if high - low <= 1 and low >= 5:          # connecteurs 54s+
            return 3
        if high - low == 2 and low >= 6:          # 1-gappers 6-8s+
            return 3
        if high >= 10 and low >= 9:               # T9s, J9s, JTs
            return 3
    else:
        if high == 14 and low >= 10:              # ATo, AJo
            return 3
        if high == 13 and low == 11:              # KJo
            return 3
        if high == 12 and low == 11:              # QJo
            return 3

    return 4


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


class HeuristicPlayer(Player):
    name = "heuristic"

    def __init__(
        self,
        seed: Optional[int] = None,
        mc_simulations: int = 600,
        bluff_freq: float = 0.05,
    ):
        self.rng = random.Random(seed)
        self.mc_simulations = mc_simulations
        self.bluff_freq = bluff_freq

    def act(self, obs: Observation) -> Action:
        if obs.stage == Stage.PREFLOP:
            return _safe(self._preflop(obs), obs)
        return _safe(self._postflop(obs), obs)

    # ---- préflop ---------------------------------------------------------

    def _preflop(self, obs: Observation) -> Action:
        tier = classify_preflop(obs.hole_cards)
        facing_raise = obs.to_call > obs.big_blind - obs.my_committed
        ptype = obs.my_position_type
        is_bb = ptype == PositionType.BIG_BLIND

        # Tier 1 : premium - toujours agressif (3-bet ferme inclus)
        if tier == 1:
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            if Action.RAISE_HALF_POT in obs.legal_actions:
                return Action.RAISE_HALF_POT
            return Action.ALL_IN

        # Tier 2 : strong - ouvre toujours, suit un raise
        if tier == 2:
            if facing_raise:
                return Action.CHECK_CALL
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            return Action.RAISE_HALF_POT

        # Tier 3 : playable - ouverture conditionnée à la position
        # Plus on est tôt, plus on resserre (joueurs derrière qui peuvent payer/3bet)
        if tier == 3:
            if facing_raise:
                # Défense BB seulement, et bon marché
                if is_bb and obs.to_call <= 2 * obs.big_blind:
                    return Action.CHECK_CALL
                return Action.FOLD
            # Pas de raise : open seulement en position tardive ou bouton
            if ptype in (PositionType.BUTTON, PositionType.LATE,
                         PositionType.SMALL_BLIND):
                if Action.RAISE_HALF_POT in obs.legal_actions:
                    return Action.RAISE_HALF_POT
                return Action.CHECK_CALL
            if ptype == PositionType.MIDDLE:
                # Open occasionnel en MP
                if self.rng.random() < 0.5 and \
                        Action.RAISE_HALF_POT in obs.legal_actions:
                    return Action.RAISE_HALF_POT
                return Action.CHECK_CALL if obs.to_call == 0 else Action.FOLD
            # EARLY (UTG) : fold tier 3 en full ring
            return Action.CHECK_CALL if obs.to_call == 0 else Action.FOLD

        # Tier 4 : trash
        if obs.to_call == 0:
            return Action.CHECK_CALL
        return Action.FOLD

    # ---- postflop --------------------------------------------------------

    def _postflop(self, obs: Observation) -> Action:
        num_opp = max(1, obs.num_active_opponents)
        equity = monte_carlo_equity(
            hole_rlcard=obs.hole_cards,
            board_rlcard=obs.community_cards,
            num_opponents=num_opp,
            simulations=self.mc_simulations,
            rng=self.rng,
        )
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0

        # Patch B : "stack preservation" — quand on a déjà beaucoup investi
        # (≥40% du stack initial) ET équité moyenne (<0.78), évite l'ALL-IN.
        # Cela corrige le leak "paires moyennes vont à tapis vs overpair".
        stack_committed_ratio = obs.my_committed / max(obs.my_stack + obs.my_committed, 1)
        protect_stack = stack_committed_ratio >= 0.4 and equity < 0.78

        # Très fort : value bet pot (sauf protection stack)
        if equity > 0.80 and not protect_stack:
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            return Action.ALL_IN if Action.ALL_IN in obs.legal_actions else Action.CHECK_CALL

        # Fort + pas sous pression majeure : value bet demi-pot
        if equity > 0.60 and pot_odds < 0.4 and not protect_stack:
            if Action.RAISE_HALF_POT in obs.legal_actions:
                return Action.RAISE_HALF_POT

        # Patch A : RIVER bluffcatcher discipline.
        # L'adversaire qui mise sur river a une range tightenée vs random.
        # Notre MC surestime notre équité. On exige un buffer plus gros.
        if obs.stage == Stage.RIVER and obs.to_call > 0:
            # Si bet est ≥ 1/3 du pot, multi-street pression probable
            bet_to_pot = obs.to_call / max(obs.pot, 1)
            threshold = 0.15 if bet_to_pot >= 0.30 else 0.05
            if equity > pot_odds + threshold:
                return Action.CHECK_CALL
            return Action.FOLD

        # Équité positive vs pot odds : on suit (autres streets)
        if equity > pot_odds + 0.03:
            return Action.CHECK_CALL

        if obs.to_call == 0:
            # Bluff occasionnel quand on est checké
            if self.rng.random() < self.bluff_freq and \
                    Action.RAISE_HALF_POT in obs.legal_actions:
                return Action.RAISE_HALF_POT
            return Action.CHECK_CALL

        return Action.FOLD
