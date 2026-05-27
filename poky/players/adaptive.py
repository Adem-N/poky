"""
AdaptiveHeuristicPlayer — heuristique + opponent modeling.

Idée : suit pour chaque adversaire les stats clés du poker live/online :
  - VPIP (Voluntarily Put $ In Pot) : % de mains où il met volontairement de
    l'argent au pot pré-flop (hors blinds) → mesure combien de mains il joue
  - PFR  (PreFlop Raise) : % de mains où il raise pré-flop
  - AF   (Aggression Factor) postflop : raises / calls
  - Fold-to-3bet : % de fois où il fold face à un 3-bet

Profil dérivé (style 2D loose/tight × passive/aggressive) :
  - NIT     : VPIP < 15
  - TAG     : VPIP 15-30, PFR/VPIP > 0.6
  - LAG     : VPIP 30-50, PFR/VPIP > 0.6
  - LP_FISH : VPIP > 30, PFR/VPIP < 0.5 (calling station)
  - MANIAC  : VPIP > 50, AF > 2

Ajustements vs profil :
  - vs NIT     : steal plus large en BTN/CO ; fold à ses raises (que premium)
  - vs TAG     : 3-bet polarisé (premium + bluff blockers) ; fold flop bets sans equity
  - vs LAG     : tighten value range mais call down lighter face à sa pression
  - vs LP_FISH : value-bet très large (paye avec n'importe quoi) ; jamais bluff
  - vs MANIAC  : tighten preflop, call down très large (overpair > top pair top kicker)

Sample size faible (< 30 mains) → on traite comme "inconnu" et on joue base heuristique.
"""
from dataclasses import dataclass, field
from typing import List

from poky.engine import Action, Observation, PositionType, Stage
from poky.equity import monte_carlo_equity
from poky.players.base import Player, ActionEvent
from poky.players.heuristic import HeuristicPlayer, classify_preflop, _safe


# ---- Tracker --------------------------------------------------------------

@dataclass
class OppStats:
    hands_observed: int = 0           # nb mains où il a eu sa carte distribuée
    voluntary_pot_count: int = 0      # nb mains avec VPIP
    pfr_count: int = 0                # nb mains avec raise pré-flop
    threebet_count: int = 0           # nb mains avec 3-bet pré-flop
    threebet_facing: int = 0          # nb mains où il a fait face à un open
    fold_to_threebet: int = 0         # nb fois où il a fold face à un 3-bet
    fold_to_threebet_facing: int = 0  # nb fois où il a fait face à un 3-bet
    postflop_raises: int = 0
    postflop_calls: int = 0
    # État courant pour la main en cours
    this_hand_vpiped: bool = False
    this_hand_pfred: bool = False
    this_hand_open_seen: bool = False    # quelqu'un a ouvert avant lui
    this_hand_threebet_seen: bool = False  # un 3-bet a eu lieu

    @property
    def vpip(self) -> float:
        if self.hands_observed == 0:
            return 0.5
        return self.voluntary_pot_count / self.hands_observed

    @property
    def pfr(self) -> float:
        if self.hands_observed == 0:
            return 0.5
        return self.pfr_count / self.hands_observed

    @property
    def af(self) -> float:
        """Aggression factor : >1 = agressif, <1 = passif. ~1.5-2 typique d'un bon joueur."""
        if self.postflop_calls == 0:
            return self.postflop_raises if self.postflop_raises > 0 else 1.0
        return self.postflop_raises / self.postflop_calls

    @property
    def fold_to_3bet_pct(self) -> float:
        if self.fold_to_threebet_facing == 0:
            return 0.5
        return self.fold_to_threebet / self.fold_to_threebet_facing


PROFILE_UNKNOWN = "unknown"
PROFILE_NIT = "nit"
PROFILE_TAG = "tag"
PROFILE_LAG = "lag"
PROFILE_FISH = "fish"
PROFILE_MANIAC = "maniac"


def classify_profile(stats: OppStats) -> str:
    if stats.hands_observed < 30:
        return PROFILE_UNKNOWN
    v, p, a = stats.vpip, stats.pfr, stats.af
    if v > 0.55 and a > 1.8:
        return PROFILE_MANIAC
    if v < 0.18:
        return PROFILE_NIT
    if v > 0.35 and (p / max(v, 0.01)) < 0.5:
        return PROFILE_FISH
    if v > 0.30 and (p / max(v, 0.01)) >= 0.6:
        return PROFILE_LAG
    return PROFILE_TAG


class OpponentTracker:
    def __init__(self, num_players: int, my_seat: int):
        self.num_players = num_players
        self.my_seat = my_seat
        self.opp = [OppStats() for _ in range(num_players)]
        self._raises_this_street = 0  # pour détecter 3-bets

    def on_new_hand(self):
        for o in self.opp:
            o.hands_observed += 1
            o.this_hand_vpiped = False
            o.this_hand_pfred = False
            o.this_hand_open_seen = False
            o.this_hand_threebet_seen = False
        self._raises_this_street = 0

    def observe(self, event: ActionEvent):
        if event.actor == self.my_seat:
            # On ne se track pas soi-même
            return
        o = self.opp[event.actor]
        is_aggressive = event.action in (
            Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN)
        is_call = event.action == Action.CHECK_CALL and event.to_call_before > 0

        if event.stage == Stage.PREFLOP:
            # VPIP : on met volontairement de l'argent (call ou raise) hors blind post
            # Un check (to_call=0) ne compte pas. Le BB qui complete pour 0 = pas VPIP.
            if is_aggressive or is_call:
                if not o.this_hand_vpiped:
                    o.voluntary_pot_count += 1
                    o.this_hand_vpiped = True
            if is_aggressive:
                if not o.this_hand_pfred:
                    o.pfr_count += 1
                    o.this_hand_pfred = True
                # Détection 3-bet : si quelqu'un a déjà raise (1 raise = open, 2 = 3-bet)
                if self._raises_this_street >= 1:
                    o.threebet_count += 1
                    o.this_hand_threebet_seen = True
                self._raises_this_street += 1
            # Si quelqu'un avait ouvert avant lui et qu'il fait face à un 3-bet
            if event.action == Action.FOLD and self._raises_this_street >= 2:
                o.fold_to_threebet += 1
                o.fold_to_threebet_facing += 1
        else:
            # Postflop
            if is_aggressive:
                o.postflop_raises += 1
            elif is_call:
                o.postflop_calls += 1


# ---- AdaptiveHeuristicPlayer ----------------------------------------------

class AdaptiveHeuristicPlayer(HeuristicPlayer):
    """Heuristique avec opponent modeling : ajuste les ranges selon les
    profils détectés. Plus le sample est gros, plus l'adaptation est fine."""
    name = "adaptive"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tracker = None  # initialisé à la première act()
        self._my_seat = None
        self._num_players = None
        # Pluribus-inspired : track per-opp aggression par street de cette main.
        # Sert à calculer un equity-discount range-aware au moment de la décision.
        self._opp_aggression_streets: dict = {}

    def reset(self) -> None:
        super().reset()
        if self.tracker is not None:
            self.tracker.on_new_hand()
        self._opp_aggression_streets = {}

    def observe_action(self, event: ActionEvent) -> None:
        if self.tracker is None:
            return
        self.tracker.observe(event)
        # Track per-stage aggression par adversaire (pas nous-mêmes)
        if event.actor != self._my_seat and event.action in (
                Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN):
            self._opp_aggression_streets.setdefault(event.actor, set()).add(event.stage)

    def _ensure_tracker(self, obs: Observation):
        if self.tracker is None:
            self._my_seat = obs.player_id
            self._num_players = obs.num_players
            self.tracker = OpponentTracker(obs.num_players, obs.player_id)
            # On a manqué le on_new_hand initial — on l'invoque maintenant
            self.tracker.on_new_hand()

    def _opponent_profiles(self) -> List[str]:
        if self.tracker is None:
            return [PROFILE_UNKNOWN] * (self._num_players or 3)
        return [classify_profile(s) for s in self.tracker.opp]

    def _table_looseness(self) -> float:
        """VPIP moyen des adversaires actifs (excluant nous-mêmes)."""
        if self.tracker is None:
            return 0.5
        vpips = [self.tracker.opp[i].vpip
                 for i in range(self.tracker.num_players)
                 if i != self.tracker.my_seat
                 and self.tracker.opp[i].hands_observed > 0]
        return sum(vpips) / max(len(vpips), 1)

    def act(self, obs: Observation) -> Action:
        self._ensure_tracker(obs)
        # Délègue à la logique base + ajustements ciblés
        return super().act(obs)

    # ---- Override préflop avec ajustements profile-aware ----------------

    def _preflop(self, obs: Observation) -> Action:
        tier = classify_preflop(obs.hole_cards)
        facing_raise = obs.to_call > obs.big_blind - obs.my_committed
        ptype = obs.my_position_type
        looseness = self._table_looseness()
        profiles = self._opponent_profiles()
        active_opps_profiles = [profiles[i] for i in range(obs.num_players)
                                if i != obs.player_id
                                and obs.player_statuses[i].name != "FOLDED"]

        # Ajustement contre les nits : open plus large car ils foldent souvent
        # Ajustement contre les fish : tighter car ils ne foldent pas
        any_fish = PROFILE_FISH in active_opps_profiles or \
            PROFILE_MANIAC in active_opps_profiles
        all_nits = (active_opps_profiles and
                    all(p == PROFILE_NIT for p in active_opps_profiles))

        # Tier 1 : toujours raise pot (sauf vs fish : ALL_IN parfois pour value max)
        if tier == 1:
            if any_fish and PROFILE_FISH in active_opps_profiles:
                # Fish paie large, value-bet plus gros
                return Action.RAISE_POT
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            return Action.RAISE_HALF_POT if Action.RAISE_HALF_POT in obs.legal_actions else Action.ALL_IN

        # Tier 2 : facing raise → fold si vs nit (il a probablement mieux), call sinon
        if tier == 2:
            if facing_raise:
                # Identifier l'agresseur (dernier raiser approx = celui avec max committed)
                aggressor = max(range(obs.num_players),
                                key=lambda i: obs.all_committed[i] if i != obs.player_id else -1)
                if profiles[aggressor] == PROFILE_NIT and obs.to_call > 4 * obs.big_blind:
                    # Nit fait un gros raise = il a AA/KK, on fold même JJ/AK
                    return Action.FOLD
                return Action.CHECK_CALL
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            return Action.RAISE_HALF_POT

        # Tier 3 : adaptation forte selon position et adversaires
        if tier == 3:
            if facing_raise:
                if ptype == PositionType.BIG_BLIND and obs.to_call <= 2 * obs.big_blind:
                    return Action.CHECK_CALL
                # Vs nits qui raise : on fold même T3 en BB
                aggressor = max(range(obs.num_players),
                                key=lambda i: obs.all_committed[i] if i != obs.player_id else -1)
                if profiles[aggressor] == PROFILE_NIT:
                    return Action.FOLD
                return Action.FOLD
            # Open tier 3 conditionnel à position et looseness adverse
            if ptype in (PositionType.BUTTON, PositionType.LATE):
                if all_nits:
                    # Steal très large vs des nits
                    return Action.RAISE_HALF_POT if Action.RAISE_HALF_POT in obs.legal_actions else Action.CHECK_CALL
                if Action.RAISE_HALF_POT in obs.legal_actions:
                    return Action.RAISE_HALF_POT
                return Action.CHECK_CALL
            if ptype == PositionType.SMALL_BLIND:
                if Action.RAISE_HALF_POT in obs.legal_actions:
                    return Action.RAISE_HALF_POT
                return Action.CHECK_CALL
            # MIDDLE/EARLY/BB : fold sauf en BB freeplay
            if obs.to_call == 0:
                return Action.CHECK_CALL
            return Action.FOLD

        # Tier 4 : steal vs nits depuis BTN si tout le monde a fold
        if tier == 4:
            if obs.to_call == 0 and ptype == PositionType.BUTTON and all_nits:
                # Vol systématique contre table de nits
                if self.rng.random() < 0.5 and \
                        Action.RAISE_HALF_POT in obs.legal_actions:
                    return Action.RAISE_HALF_POT
            if obs.to_call == 0:
                return Action.CHECK_CALL
            return Action.FOLD

    # ---- Override postflop avec range-aware equity (Pluribus-inspired) ----

    def _max_opp_aggression_before(self, current_stage) -> int:
        """Nombre max de streets pré-courantes où un adversaire a été agressif."""
        if not self._opp_aggression_streets:
            return 0
        return max(
            (len([s for s in streets if s != current_stage])
             for streets in self._opp_aggression_streets.values()),
            default=0,
        )

    def _aggressor_is_tight(self, obs) -> bool:
        """True si l'adversaire qui mise est un joueur tight/TAG (donc sa range est
        vraiment tightenée par ses bets). False si maniac/fish/random — leurs bets
        sont du bruit, on ne doit pas discounter."""
        if self.tracker is None:
            return False
        # Identifie le dernier raiser (= max committed parmi les adversaires)
        if not self._opp_aggression_streets:
            return False
        # Trouve les adversaires qui ont agressé cette main
        active_aggressors = [a for a in self._opp_aggression_streets
                             if a != obs.player_id
                             and obs.player_statuses[a].name != "FOLDED"]
        if not active_aggressors:
            return False
        # Si au moins un agresseur a un profil "tight" (sample >= 30), on discount
        for opp in active_aggressors:
            stats = self.tracker.opp[opp]
            if stats.hands_observed >= 30:
                profile = classify_profile(stats)
                if profile in (PROFILE_NIT, PROFILE_TAG):
                    return True
                if profile in (PROFILE_MANIAC, PROFILE_FISH):
                    return False
        # Échantillon insuffisant : on suppose moyen → discount modéré OK
        return True

    def _postflop(self, obs: Observation) -> Action:
        num_opp = max(1, obs.num_active_opponents)
        raw_equity = monte_carlo_equity(
            hole_rlcard=obs.hole_cards,
            board_rlcard=obs.community_cards,
            num_opponents=num_opp,
            simulations=self.mc_simulations,
            rng=self.rng,
        )
        # Range tightening discount conditionnel : on n'applique le discount
        # que si l'agresseur est un joueur tight (TAG/nit/unknown). Vs maniac/fish,
        # leurs bets sont du bruit, leur range reste large → pas de discount.
        agg = self._max_opp_aggression_before(obs.stage)
        if agg > 0 and self._aggressor_is_tight(obs):
            discount = max(0.45, 1.0 - 0.15 * agg)
        else:
            discount = 1.0
        equity = raw_equity * discount

        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call > 0 else 0.0

        # Protection stack (héritée du heuristic patch B)
        stack_committed_ratio = obs.my_committed / max(
            obs.my_stack + obs.my_committed, 1)
        protect_stack = stack_committed_ratio >= 0.4 and equity < 0.78

        # Très fort : value bet pot (raw equity car on est l'agresseur ici)
        if raw_equity > 0.80 and not protect_stack:
            if Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            return Action.ALL_IN if Action.ALL_IN in obs.legal_actions else Action.CHECK_CALL

        if raw_equity > 0.60 and pot_odds < 0.4 and not protect_stack:
            if Action.RAISE_HALF_POT in obs.legal_actions:
                return Action.RAISE_HALF_POT

        # RIVER discipline (héritée du heuristic patch A) avec equity range-aware
        if obs.stage == Stage.RIVER and obs.to_call > 0:
            bet_to_pot = obs.to_call / max(obs.pot, 1)
            threshold = 0.15 if bet_to_pot >= 0.30 else 0.05
            if equity > pot_odds + threshold:
                return Action.CHECK_CALL
            return Action.FOLD

        if equity > pot_odds + 0.03:
            return Action.CHECK_CALL

        if obs.to_call == 0:
            if self.rng.random() < self.bluff_freq and \
                    Action.RAISE_HALF_POT in obs.legal_actions:
                return Action.RAISE_HALF_POT
            return Action.CHECK_CALL

        return Action.FOLD
