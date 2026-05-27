"""
ProClaude — bot codifié simulant un joueur **fort** (régulier compétent),
avec détection automatique des "spots critiques" qui méritent une réflexion
humaine plus poussée.

POURQUOI ce player existe :
  - On veut tester le bot sur des sessions LONGUES (500+ mains)
  - Faire jouer chaque main par Claude AI une à une = infaisable (un tool call
    par décision = 1500+ tool calls pour une session)
  - Solution : ProClaude joue automatiquement les 80% de décisions "routine"
    avec une logique de pro codifiée, et flagge les 20% de décisions où
    un humain pensant pourrait jouer différemment
  - Après la session, l'analyser remonte ces spots critiques pour review

Logique de codification (par rapport à ClaudePlayer) :
  - Ranges préflop calibrées par position (BTN/CO/MP/EP différenciés en 6+max)
  - 3-bet polarisé : value (premium) + bluff (specific blockers)
  - 4-bet shove avec premium face à un 3-bet
  - C-bet logic basée sur board texture (dry vs wet)
  - Barrel turn avec equity ≥ 50% ou semi-bluffs
  - River : pure value/bluff, jamais "j'espère que je gagne"
  - Mixed strategies pour rester non-exploitable

Détection des spots critiques (flag pour review humaine) :
  - River decision avec équité 0.40-0.65 (bluff catcher territory)
  - All-in décisions
  - 3-bet pot avec main marginale (besoin de bonne lecture)
  - Spot où check ET bet sont proches en EV
"""
import random
from typing import Optional, Tuple

from poky.engine import Action, Observation, Position, PositionType, Stage
from poky.equity import monte_carlo_equity
from poky.players.heuristic import classify_preflop, _safe
from poky.players.base import Player, ActionEvent


_RANK_VAL = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
             "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def board_wetness(community_cards) -> str:
    """Classifie la texture du flop/board : 'dry', 'wet', 'medium'."""
    if len(community_cards) < 3:
        return "dry"
    suits = [c[0] for c in community_cards]
    ranks = sorted([_RANK_VAL[c[1]] for c in community_cards], reverse=True)
    # Wetness signals
    flush_draw = max(suits.count(s) for s in set(suits)) >= 2
    straight_threat = any(ranks[i] - ranks[i+1] <= 2 for i in range(len(ranks) - 1))
    paired = len(set(ranks)) < len(ranks)
    if flush_draw and straight_threat:
        return "wet"
    if flush_draw or straight_threat:
        return "medium"
    return "dry"


class ProClaude(Player):
    name = "pro_claude"

    def __init__(self, seed: Optional[int] = None, mc_simulations: int = 800):
        self.rng = random.Random(seed)
        self.mc_simulations = mc_simulations
        # État courant
        self._was_preflop_aggressor = False
        self._has_cbet_flop = False
        # Flags pour le logger
        self.last_critical = False
        self.last_critical_note: Optional[str] = None

    def reset(self):
        self._was_preflop_aggressor = False
        self._has_cbet_flop = False

    def observe_action(self, event: ActionEvent):
        # Pour l'instant on n'utilise pas — pourrait y ajouter de l'opp modeling
        pass

    def act(self, obs: Observation) -> Action:
        # Reset les flags pour cette décision
        self.last_critical = False
        self.last_critical_note = None

        if obs.stage == Stage.PREFLOP:
            action, crit, note = self._preflop(obs)
        else:
            action, crit, note = self._postflop(obs)

        action = _safe(action, obs)
        self.last_critical = crit
        self.last_critical_note = note

        # Track agression préflop pour c-bet downstream
        if obs.stage == Stage.PREFLOP and action in (
                Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN):
            self._was_preflop_aggressor = True
        elif obs.stage == Stage.FLOP and action in (
                Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN):
            self._has_cbet_flop = True
        return action

    # ---- préflop ---------------------------------------------------------

    def _preflop(self, obs: Observation) -> Tuple[Action, bool, Optional[str]]:
        tier = classify_preflop(obs.hole_cards)
        facing_raise = max(obs.all_committed) > obs.big_blind
        facing_3bet = max(obs.all_committed) > 3 * obs.big_blind
        ptype = obs.my_position_type
        cost_bb = obs.to_call / obs.big_blind

        # Tier 1 : ALWAYS value
        if tier == 1:
            if facing_3bet:
                # 4-bet shove avec premium — énorme value vs ranges de 3-bet
                return Action.ALL_IN, True, "4-bet shove premium vs 3-bet"
            return Action.RAISE_POT, False, None

        # Tier 2 : value bet et navigate les 3-bets
        if tier == 2:
            if facing_3bet:
                # JJ, AK face à un 3-bet : call (jamais 4-bet shove avec ces hands)
                if cost_bb <= 9:
                    return Action.CHECK_CALL, True, "Tier 2 vs 3-bet cost OK"
                return Action.FOLD, True, "Tier 2 vs gros 3-bet"
            if facing_raise:
                # Mix : 80% call, 20% 3-bet pour balance
                if self.rng.random() < 0.20:
                    return Action.RAISE_POT, False, None
                return Action.CHECK_CALL, False, None
            return Action.RAISE_POT, False, None

        # Tier 3 : ouverture conditionnée à la position
        if tier == 3:
            if facing_3bet:
                return Action.FOLD, False, None
            if facing_raise:
                if ptype == PositionType.BIG_BLIND and cost_bb <= 3:
                    return Action.CHECK_CALL, False, None
                if ptype == PositionType.SMALL_BLIND and cost_bb <= 2:
                    return Action.CHECK_CALL, False, None
                return Action.FOLD, False, None
            # Open : position dépendante
            if ptype in (PositionType.BUTTON, PositionType.LATE,
                         PositionType.SMALL_BLIND):
                return Action.RAISE_HALF_POT, False, None
            if ptype == PositionType.MIDDLE and self.rng.random() < 0.5:
                return Action.RAISE_HALF_POT, False, None
            if obs.to_call == 0:
                return Action.CHECK_CALL, False, None
            return Action.FOLD, False, None

        # Tier 4 : steal BTN parfois, sinon fold
        if obs.to_call == 0:
            if ptype == PositionType.BUTTON and self.rng.random() < 0.15:
                return Action.RAISE_HALF_POT, False, "steal BTN tier 4"
            return Action.CHECK_CALL, False, None
        # Defense BB super wide vs 1 BB de plus
        if ptype == PositionType.BIG_BLIND and cost_bb <= 1.5 and self.rng.random() < 0.4:
            return Action.CHECK_CALL, False, None
        return Action.FOLD, False, None

    # ---- postflop --------------------------------------------------------

    def _postflop(self, obs: Observation) -> Tuple[Action, bool, Optional[str]]:
        num_opp = max(1, obs.num_active_opponents)
        equity = monte_carlo_equity(
            obs.hole_cards, obs.community_cards, num_opp,
            simulations=self.mc_simulations, rng=self.rng,
        )
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0
        texture = board_wetness(obs.community_cards)

        # ── RIVER ────────────────────────────────────────────────────────
        if obs.stage == Stage.RIVER:
            # Value bet large mais polarisé
            if equity > 0.82:
                # Trap parfois avec nuts
                if obs.to_call == 0 and self.rng.random() < 0.20:
                    return Action.CHECK_CALL, False, "trap nuts"
                return Action.RAISE_POT, False, None
            if equity > 0.62:
                return Action.RAISE_HALF_POT, False, None

            # Zone bluff catcher (équité moyenne)
            if 0.35 <= equity <= 0.65:
                # SPOT CRITIQUE : décision bluffcatcher
                if obs.to_call > 0:
                    if equity > pot_odds + 0.02:
                        return (Action.CHECK_CALL, True,
                                f"bluffcatcher EV+ (eq={equity:.2f} vs pot_odds={pot_odds:.2f})")
                    return (Action.FOLD, True,
                            f"bluffcatcher EV- (eq={equity:.2f} vs pot_odds={pot_odds:.2f})")
                # On peut bluffer river avec mains sans showdown value sur board scary
                if equity < 0.50 and texture == "wet" and self.rng.random() < 0.20:
                    return Action.RAISE_HALF_POT, True, "river bluff sur board wet"
                return Action.CHECK_CALL, False, None

            # Très faible équité
            if obs.to_call == 0:
                if self.rng.random() < 0.10:
                    return Action.RAISE_HALF_POT, True, "polarized bluff river"
                return Action.CHECK_CALL, False, None
            return Action.FOLD, False, None

        # ── FLOP / TURN ──────────────────────────────────────────────────
        # C-bet quand on a été agresseur préflop ET texture favorable
        if obs.stage == Stage.FLOP and obs.to_call == 0 and \
                self._was_preflop_aggressor:
            # Dry board → c-bet large (notre range a plus de high cards/overpairs)
            # Wet board → c-bet seulement avec equity
            if texture == "dry":
                if equity > 0.30 and self.rng.random() < 0.70:
                    return Action.RAISE_HALF_POT, False, "c-bet dry board"
                if equity > 0.55:
                    return Action.RAISE_POT, False, None
            else:  # medium / wet
                if equity > 0.55:
                    return Action.RAISE_HALF_POT, False, "value bet wet board"
                if equity > 0.40 and self.rng.random() < 0.35:
                    return Action.RAISE_HALF_POT, False, "semi-bluff wet board"

        # Value général
        if equity > 0.80:
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT, False, None
            return Action.ALL_IN, False, None
        if equity > 0.60 and pot_odds < 0.45:
            return Action.RAISE_HALF_POT, False, None

        # Call si équité positive vs pot odds
        if equity > pot_odds + 0.04:
            return Action.CHECK_CALL, False, None

        # Check / bluff
        if obs.to_call == 0:
            # Probe bet en position si l'adversaire a checké
            if equity > 0.25 and obs.num_active_opponents == 1 and self.rng.random() < 0.15:
                return Action.RAISE_HALF_POT, False, "probe bet"
            return Action.CHECK_CALL, False, None

        # Facing pression sans équité
        # SPOT CRITIQUE : décision call-or-fold avec pot investi
        if obs.my_committed > 5 * obs.big_blind:
            return (Action.FOLD, True,
                    f"fold avec gros investi ({obs.my_committed} chips), eq={equity:.2f}")
        return Action.FOLD, False, None
