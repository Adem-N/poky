"""
ExpertOnlyPlayer — Tier 1 + Tier 2 sans CFR.

Préflop : consulte les ranges GTO publiées (poky.expert) si la situation
est couverte. Sinon, fallback HeuristicPlayer (Tier 2).

Postflop : 100% HeuristicPlayer (Tier 2 — Monte Carlo equity + pot odds).

Sert deux objectifs :
  1. Mesurer la valeur APPORTÉE par les ranges expertes vs le tier 2 nu.
     Critère Phase X1 : ExpertOnly bat Heuristic de +5 bb/100 minimum.
  2. Servir de "ground truth pro" pour bootstrapper l'entraînement MCCFR
     (warm-start des regrets — Phase X4).

Le sampling des fréquences mixed est déterministe par seed pour
reproductibilité des benchmarks.
"""
import random
from collections import defaultdict
from typing import List, Optional, Tuple

from poky.engine import Action, Observation, Stage
from poky.expert.context import detect_context
from poky.expert.postflop_rules import pro_postflop_strategy
from poky.expert.range_lookup import pro_preflop_strategy, sample_action
from poky.players.base import ActionEvent, Player
from poky.players.heuristic import HeuristicPlayer


_RAISE_ACTIONS = {Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN}


def _safe(action: Action, obs: Observation) -> Action:
    """Replie sur une action légale si celle voulue ne l'est pas.

    Copie de la logique de heuristic._safe, dupliquée volontairement pour
    garder ce fichier autonome.
    """
    if action in obs.legal_actions:
        return action
    if action == Action.ALL_IN and Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    if action == Action.RAISE_POT and Action.RAISE_HALF_POT in obs.legal_actions:
        return Action.RAISE_HALF_POT
    if action == Action.RAISE_HALF_POT and Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    if Action.CHECK_CALL in obs.legal_actions:
        return Action.CHECK_CALL
    return Action.FOLD


class ExpertOnlyPlayer(Player):
    """Joueur qui consulte les ranges expertes préflop et délègue postflop
    au HeuristicPlayer.

    Args:
        seed: graine RNG pour le sampling des frequencies mixed
        mc_simulations: passés au HeuristicPlayer postflop
        bluff_freq: passés au HeuristicPlayer postflop
        fallback_to_heuristic: si True (défaut), bascule sur HeuristicPlayer
            préflop quand la situation n'est pas couverte par les ranges.
            Si False, retourne FOLD systématiquement (pour debug / mesure
            de couverture).
    """

    name = "expert_only"

    def __init__(
        self,
        seed: Optional[int] = None,
        mc_simulations: int = 600,
        bluff_freq: float = 0.05,
        fallback_to_heuristic: bool = True,
        use_postflop_rules: bool = True,
    ):
        self.rng = random.Random(seed)
        self.fallback_to_heuristic = fallback_to_heuristic
        self.use_postflop_rules = use_postflop_rules
        self._mc_simulations = mc_simulations
        self._heuristic = HeuristicPlayer(
            seed=seed,
            mc_simulations=mc_simulations,
            bluff_freq=bluff_freq,
        )
        # Compteurs pour diagnostiquer la couverture
        self.preflop_expert_hits = 0
        self.preflop_fallback_hits = 0
        self.postflop_expert_hits = 0
        self.postflop_fallback_hits = 0
        # Diagnostic : actions prises par scenario_key
        # {scenario_key: {action: count}}
        self.scenario_actions: dict = defaultdict(lambda: defaultdict(int))
        # Diagnostic : scenarios déclenchés dans la main courante (utile
        # pour attribuer les payoffs main-par-main par scenario).
        self._scenarios_in_hand: List[str] = []
        # Log "scenarios par main" : pousser à chaque reset.
        self.scenarios_per_hand: List[List[str]] = []
        # Flag pour ne pas pousser une entrée vide avant la première main.
        self._has_played_a_hand = False
        # PFA tracking : player_id du dernier raiser préflop. None si
        # personne (limped pot). Mis à jour via observe_action.
        self._preflop_last_raiser: Optional[int] = None

    def act(self, obs: Observation) -> Action:
        if obs.stage == Stage.PREFLOP:
            return self._preflop(obs)
        return self._postflop(obs)

    def observe_action(self, event: ActionEvent) -> None:
        """Track preflop aggressor pour la décision c-bet postflop."""
        if event.stage == Stage.PREFLOP and event.action in _RAISE_ACTIONS:
            self._preflop_last_raiser = event.actor

    def _preflop(self, obs: Observation) -> Action:
        strategy = pro_preflop_strategy(obs)
        if strategy is None:
            self.preflop_fallback_hits += 1
            self._scenarios_in_hand.append("fallback")
            if self.fallback_to_heuristic:
                return self._heuristic.act(obs)
            return _safe(Action.FOLD, obs)

        self.preflop_expert_hits += 1
        ctx = detect_context(obs)
        scenario_key = ctx[1] if ctx else "unknown"
        self._scenarios_in_hand.append(scenario_key)

        # Map chaque action de la strategy au plus proche équivalent légal
        # via _safe(). Cela évite de tomber dans le fallback heuristic quand
        # une action voulue (ex RAISE_HALF_POT) n'est pas exactement légale
        # mais a un équivalent (RAISE_POT).
        combined: dict = defaultdict(float)
        for a, f in strategy:
            safe = _safe(a, obs)
            combined[safe] += f
        strategy_legal = list(combined.items())
        if not strategy_legal:
            if self.fallback_to_heuristic:
                return self._heuristic.act(obs)
            return _safe(Action.FOLD, obs)

        action = sample_action(strategy_legal, self.rng)
        self.scenario_actions[scenario_key][action] += 1
        return action

    def _postflop(self, obs: Observation) -> Action:
        if not self.use_postflop_rules:
            return self._heuristic.act(obs)

        was_pfa = (self._preflop_last_raiser is not None
                   and self._preflop_last_raiser == obs.player_id)
        strategy = pro_postflop_strategy(obs, was_pfa=was_pfa, rng=self.rng)
        if strategy is None:
            self.postflop_fallback_hits += 1
            return self._heuristic.act(obs)

        self.postflop_expert_hits += 1
        # Map actions vers legal_actions de manière sûre
        combined: dict = defaultdict(float)
        for a, f in strategy:
            safe = _safe(a, obs)
            combined[safe] += f
        strategy_legal = list(combined.items())
        if not strategy_legal:
            return self._heuristic.act(obs)
        return sample_action(strategy_legal, self.rng)

    def reset(self) -> None:
        # On pousse TOUJOURS (même si vide) à partir de la 2e main, pour
        # garder scenarios_per_hand[i] aligné avec la i-ème main jouée
        # (qu'on y ait agi ou pas). Skip le premier reset (avant hand 0)
        # pour ne pas pousser une entrée vide initiale.
        if self._has_played_a_hand:
            self.scenarios_per_hand.append(self._scenarios_in_hand)
            self._scenarios_in_hand = []
        self._has_played_a_hand = True
        self._preflop_last_raiser = None
        self._heuristic.reset()
