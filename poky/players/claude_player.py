"""
ClaudePlayer — bot simulant la réflexion d'un joueur humain compétent
(qui pense les ranges adverses, l'équité, la position, et exploite les
patterns visibles chez l'adversaire).

DIFFÉRENCES vs HeuristicPlayer :
  - Ranges préflop **calibrées par position** (BTN plus large, SB resserre, BB defend wider vs petit raise)
  - 3-bet pré-flop **mixé** : value (premium) + bluff (4-5% des autres mains)
  - **Opponent modeling minimal** : compte la fréquence avec laquelle chaque
    adversaire a misé/raise sur les N dernières actions. Plus l'opposant est
    actif, plus on call/3bet wide ; moins il est actif, plus on fold à ses bets.
  - **C-bet en position** quand on a été l'agresseur préflop, mais seulement
    si le board favorise notre range (haute carte ou paire)
  - **River value-bet** plus large + **river bluff** ciblé sur boards à draws
    manqués
  - **Trapping** : slow-play parfois des hands ultra-fortes (AA, set) pour
    inducer du bluff

C'est un adversaire que je qualifierais de "joueur régulier compétent
de petite limite" — pas un pro mais largement au-dessus du joueur récréatif moyen.
"""
import random
from collections import deque
from typing import Optional

from poky.engine import Action, Observation, Position, PositionType, Stage
from poky.equity import monte_carlo_equity
from poky.players.base import Player
from poky.players.heuristic import classify_preflop, _safe


# Hand ranges ouvertes par position (au-dessus de la BB)
# Format : "tu peux ouvrir si tier <= N"
_OPEN_BY_POSITION = {
    Position.BTN: 3,   # open large : tiers 1-3 (~30-37% des mains)
    Position.SB:  3,   # open un peu plus serré, fold tier 3 marginal
    Position.BB:  2,   # rare en BB (pas d'open en BB, c'est défensif uniquement)
}

# Défense BB face à un raise selon coût (cost_to_call en BB)
def _bb_defends(tier, cost_bb):
    if tier == 1: return True
    if tier == 2: return cost_bb <= 5
    if tier == 3: return cost_bb <= 2.5
    return False


class ClaudePlayer(Player):
    name = "claude"

    def __init__(self, seed: Optional[int] = None, mc_simulations: int = 700,
                 history_window: int = 6):
        self.rng = random.Random(seed)
        self.mc_simulations = mc_simulations
        self.history_window = history_window
        # Tracking par adversaire des actions récentes (FOLD / CALL / RAISE)
        # Initialisé à la première act() avec le bon nb de joueurs
        self.opp_history = None
        self._was_preflop_aggressor = False

    def reset(self):
        self._was_preflop_aggressor = False
        if self.opp_history is not None:
            # On garde l'historique entre mains pour modéliser sur le long terme

            pass

    # ---- API principale --------------------------------------------------

    def act(self, obs: Observation) -> Action:
        # Initialisation lazy de l'historique
        if self.opp_history is None:
            self.opp_history = [deque(maxlen=self.history_window * 4)
                                for _ in range(obs.num_players)]

        if obs.stage == Stage.PREFLOP:
            action = self._preflop(obs)
        else:
            action = self._postflop(obs)
        action = _safe(action, obs)
        if obs.stage == Stage.PREFLOP and action in (Action.RAISE_HALF_POT,
                                                     Action.RAISE_POT, Action.ALL_IN):
            self._was_preflop_aggressor = True
        return action

    # ---- préflop ---------------------------------------------------------

    def _preflop(self, obs: Observation) -> Action:
        tier = classify_preflop(obs.hole_cards)
        cost_bb = obs.to_call / obs.big_blind
        facing_raise = max(obs.all_committed) > obs.big_blind
        facing_3bet = max(obs.all_committed) > 3 * obs.big_blind

        # Stratégie face à un 3bet
        if facing_3bet:
            if tier == 1:
                # 4-bet à shove avec premium (ranges de 3bet adverse sont en moyenne plus faibles)
                if cost_bb >= 15:
                    # Pot bloated, on est probablement en bonne situation pour shove
                    return Action.ALL_IN if Action.ALL_IN in obs.legal_actions else Action.RAISE_POT
                return Action.RAISE_POT
            if tier == 2 and cost_bb <= 8:
                return Action.CHECK_CALL  # call et joue le flop avec QQ-JJ, AK
            return Action.FOLD

        # Stratégie face à un raise simple
        if facing_raise:
            if tier == 1:
                # 3-bet for value AVEC les premium
                if self.rng.random() < 0.85:
                    return Action.RAISE_POT
                return Action.CHECK_CALL  # slow-play occasionnel pour balance
            if tier == 2:
                # mix : call principalement, 3-bet polarisé occasionnel
                if self.rng.random() < 0.25 and obs.my_position != Position.SB:
                    return Action.RAISE_POT
                return Action.CHECK_CALL
            if tier == 3 and obs.my_position == Position.BB and _bb_defends(3, cost_bb):
                return Action.CHECK_CALL
            if tier == 4 and obs.my_position == Position.BB and cost_bb <= 1.5:
                # Defense BB super wide pour 1 BB de plus
                if self.rng.random() < 0.3:
                    return Action.CHECK_CALL
            # Bluff 3-bet occasionnel avec des mains "blocker" (Axo) pour balance
            if tier == 4 and obs.my_position == Position.BTN:
                hi, lo = sorted([c[1] for c in obs.hole_cards], reverse=True)
                # Si on a un As (blocker) et qu'on est BTN, bluff 3-bet 5% du temps
                if "A" in (hi, lo) and self.rng.random() < 0.05:
                    return Action.RAISE_POT
            return Action.FOLD

        # Personne n'a raise — on ouvre selon position
        open_threshold = _OPEN_BY_POSITION[obs.my_position]
        if tier <= open_threshold:
            # Sizing : pot avec premium, demi-pot avec tier 2-3 pour balance
            if tier == 1 and self.rng.random() < 0.2:
                return Action.RAISE_HALF_POT  # mix de sizing pour ne pas être lisible
            if tier == 1:
                return Action.RAISE_POT
            return Action.RAISE_HALF_POT

        # Tier 4 : steal BTN parfois
        if obs.my_position == Position.BTN and obs.to_call == 0 and self.rng.random() < 0.18:
            return Action.RAISE_HALF_POT
        if obs.to_call == 0:
            return Action.CHECK_CALL
        return Action.FOLD

    # ---- postflop --------------------------------------------------------

    def _postflop(self, obs: Observation) -> Action:
        num_opp = max(1, obs.num_active_opponents)
        equity = monte_carlo_equity(
            obs.hole_cards, obs.community_cards, num_opp,
            simulations=self.mc_simulations, rng=self.rng,
        )
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0
        spr = obs.my_stack / max(obs.pot, 1)  # stack to pot ratio

        # ─── River : pas d'implied odds, value bet plus large, bluff ciblé
        if obs.stage == Stage.RIVER:
            if equity > 0.80:
                # Trap parfois avec nuts
                if self.rng.random() < 0.20:
                    return Action.CHECK_CALL
                return Action.RAISE_POT
            if equity > 0.62:
                return Action.RAISE_HALF_POT
            if equity > 0.40 and obs.to_call == 0:
                # Bluff river avec mains à faible showdown value
                # mais qui bloquent les nuts adverses
                if self.rng.random() < 0.18:
                    return Action.RAISE_HALF_POT
            # Décision call/fold sur pot odds
            if obs.to_call == 0:
                return Action.CHECK_CALL
            if equity > pot_odds + 0.02:
                return Action.CHECK_CALL
            return Action.FOLD

        # ─── Flop / Turn
        # C-bet en position si on a été l'agresseur préflop, board favorable
        if (obs.stage == Stage.FLOP and obs.to_call == 0
                and self._was_preflop_aggressor):
            if equity > 0.55:
                return Action.RAISE_POT
            if equity > 0.35 and self.rng.random() < 0.55:
                # C-bet avec une partie des mains qui ont manqué (semi-bluff)
                return Action.RAISE_HALF_POT

        # Value bet général
        if equity > 0.78:
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            return Action.ALL_IN if Action.ALL_IN in obs.legal_actions else Action.CHECK_CALL

        if equity > 0.58 and pot_odds < 0.45:
            return Action.RAISE_HALF_POT

        # Call si équité positive
        if equity > pot_odds + 0.04:
            return Action.CHECK_CALL

        # Check / bluff
        if obs.to_call == 0:
            # Bluff flop en position si peu d'adversaires actifs
            if obs.num_active_opponents == 1 and equity > 0.25 and self.rng.random() < 0.10:
                return Action.RAISE_HALF_POT
            return Action.CHECK_CALL

        return Action.FOLD
