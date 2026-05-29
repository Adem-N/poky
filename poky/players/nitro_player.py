"""NitroPlayer — orchestrator for 3-max hyper-turbo (Winamax Expresso Nitro).

Decision pipeline:
  1. Preflop: detect scenario (BTN open / SB vs BTN action / BB closing action)
     from prior preflop actions. Look up Nash push/fold frequency for the
     current effective stack depth (via poky.nitro.ranges). Sample push/call
     vs fold from the mixed strategy.
  2. Postflop: delegate to HeuristicPlayer (at 15bb start, postflop is shallow
     and rare — pushing/calling preflop is where 95% of the edge comes from).
  3. Fallback to HeuristicPlayer for unrecognized scenarios (e.g. limped pots,
     min-raise wars not in our Nash model).

ICM mode: `use_icm=True` activates Malmuth-Harville-based shove adjustments
on top of the chip-EV Nash baseline (placeholder for v1; defers to chip-EV).

Exploit mode: `exploit_level` in [0, 1] controls how much we deviate from
GTO toward exploitive play vs Nitro fish pop (placeholder for v1).
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Optional

from poky.abstraction.preflop import canonical_class, class_name
from poky.engine import Action, Observation, Stage, PlayerStatus
from poky.players.base import ActionEvent, Player
from poky.players.heuristic import HeuristicPlayer
from poky.nitro.ranges import available_stacks, get_strategy


_AGGRESSIVE_ACTIONS = {Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN}


class NitroPlayer(Player):
    """Nash-based 3-max hyper-turbo SnG player.

    Args:
        seed: RNG seed for mixed-strategy sampling and HeuristicPlayer fallback
        use_icm: if True, apply ICM-aware adjustments (placeholder; v1 = chip EV)
        exploit_level: 0.0 = pure Nash, 1.0 = full exploit vs Nitro fish pop
                       (placeholder; v1 = no adjustment)
        fallback_postflop: custom postflop player (default = HeuristicPlayer)
        payouts: prize structure for ICM mode (e.g., [80, 12, 8])
    """

    name = "nitro"

    def __init__(
        self,
        seed: Optional[int] = None,
        use_icm: bool = False,
        exploit_level: float = 0.0,
        fallback_postflop: Optional[Player] = None,
        payouts: Optional[list] = None,
    ):
        self.rng = random.Random(seed)
        self.use_icm = use_icm
        self.exploit_level = max(0.0, min(1.0, exploit_level))
        self.payouts = payouts or [100.0, 0.0, 0.0]   # winner-take-all by default
        self.fallback = fallback_postflop or HeuristicPlayer(seed=seed)

        # State tracked across actions in the current hand.
        # player_id -> "fold" | "push" | "call" | "blind"  (only filled if observed)
        self._preflop_status: dict = {}

        # Diagnostic counters
        self.nash_hits = 0                # preflop decision used Nash table
        self.preflop_fallback_hits = 0    # preflop fell back (scenario not detected)
        self.postflop_decisions = 0       # postflop delegated to fallback
        self.action_dist: dict = defaultdict(int)
        self.scenario_counts: dict = defaultdict(int)

    # ---- Player API -------------------------------------------------

    def act(self, obs: Observation) -> Action:
        # Only 3-max is supported.
        if obs.num_players != 3:
            return self.fallback.act(obs)

        if obs.stage != Stage.PREFLOP:
            self.postflop_decisions += 1
            action = self.fallback.act(obs)
            self.action_dist[action] += 1
            return action

        return self._preflop_decision(obs)

    def observe_action(self, event: ActionEvent) -> None:
        if event.stage == Stage.PREFLOP:
            if event.action == Action.FOLD:
                self._preflop_status[event.actor] = "fold"
            elif event.action in _AGGRESSIVE_ACTIONS:
                self._preflop_status[event.actor] = "push"
            elif event.action == Action.CHECK_CALL:
                # Distinguish: was there aggression before? If yes, it's a CALL;
                # otherwise it's a CHECK/limp.
                already_pushed = any(
                    s == "push" for s in self._preflop_status.values()
                )
                self._preflop_status[event.actor] = "call" if already_pushed else "limp"
        # Always forward to fallback so its internal state stays in sync.
        self.fallback.observe_action(event)

    def reset(self) -> None:
        self._preflop_status = {}
        self.fallback.reset()

    # ---- Preflop logic ----------------------------------------------

    def _preflop_decision(self, obs: Observation) -> Action:
        scenario = self._detect_scenario(obs)
        if scenario is None:
            return self._fallback_preflop(obs, reason="scenario_unknown")

        hand_name = class_name(canonical_class(obs.hole_cards[0], obs.hole_cards[1]))

        # Effective stack at the START of the hand = current stack + already committed.
        eff_stack_chips = obs.my_stack + obs.my_committed
        eff_stack_bb = eff_stack_chips / obs.big_blind

        # If no Nash tables available, fall back.
        if not available_stacks():
            return self._fallback_preflop(obs, reason="no_tables")

        freq = get_strategy(eff_stack_bb, scenario, hand_name)
        if freq is None:
            return self._fallback_preflop(obs, reason="hand_or_scenario_missing")

        freq_adj = self._apply_exploits(scenario, hand_name, freq)

        self.nash_hits += 1
        self.scenario_counts[scenario] += 1
        is_aggressive = self.rng.random() < freq_adj
        action = self._map_to_action(scenario, is_aggressive, obs)
        self.action_dist[action] += 1
        return action

    def _detect_scenario(self, obs: Observation) -> Optional[str]:
        """Map (hero position, prior actions) to one of the six Nash scenarios."""
        hero = obs.player_id
        pos_offset = (hero - obs.dealer_id) % 3

        # Position 0 = BTN, 1 = SB, 2 = BB (3-max action order: BTN -> SB -> BB)
        btn_id = obs.dealer_id
        sb_id = (obs.dealer_id + 1) % 3

        if pos_offset == 0:
            # Hero is BTN, no prior action expected -> open decision.
            return "btn_push"

        if pos_offset == 1:
            btn_status = self._preflop_status.get(btn_id)
            if btn_status == "fold":
                return "sb_push_after_btn_fold"
            if btn_status == "push":
                return "sb_call_vs_btn"
            # BTN limped / unknown -> outside our Nash model.
            return None

        if pos_offset == 2:
            btn_status = self._preflop_status.get(btn_id)
            sb_status = self._preflop_status.get(sb_id)
            if btn_status == "push" and sb_status == "call":
                return "bb_call_3way"
            if btn_status == "push" and sb_status == "fold":
                return "bb_call_vs_btn"
            if btn_status == "fold" and sb_status == "push":
                return "bb_call_vs_sb"
            return None

        return None

    def _apply_exploits(self, scenario: str, hand_name: str, freq: float) -> float:
        """Adjust Nash frequency toward exploit when `exploit_level > 0`.

        v1: simple multiplicative knob; production exploits will be scenario-
        specific (BTN wider, 3-bet tighter, call thinner vs station, etc.).
        """
        if self.exploit_level <= 0:
            return freq
        # Placeholder: widen aggressive scenarios slightly.
        if scenario in ("btn_push", "sb_push_after_btn_fold"):
            return min(1.0, freq + 0.1 * self.exploit_level)
        # Tighten calling vs unknown pushers slightly (fish push for value).
        if scenario in ("sb_call_vs_btn", "bb_call_3way",
                        "bb_call_vs_btn", "bb_call_vs_sb"):
            return max(0.0, freq - 0.05 * self.exploit_level)
        return freq

    def _map_to_action(self, scenario: str, is_aggressive: bool,
                       obs: Observation) -> Action:
        if not is_aggressive:
            return _safe(Action.FOLD, obs)
        # For aggressive scenarios:
        if scenario in ("btn_push", "sb_push_after_btn_fold"):
            return _safe(Action.ALL_IN, obs)
        # Call scenarios:
        return _safe(Action.CHECK_CALL, obs)

    def _fallback_preflop(self, obs: Observation, reason: str) -> Action:
        self.preflop_fallback_hits += 1
        self.scenario_counts[f"_fallback_{reason}"] += 1
        action = self.fallback.act(obs)
        self.action_dist[action] += 1
        return action

    # ---- Diagnostics -----------------------------------------------

    def coverage_stats(self) -> dict:
        total_preflop = self.nash_hits + self.preflop_fallback_hits
        nash_rate = (self.nash_hits / total_preflop) if total_preflop else 0.0
        return {
            "preflop_total": total_preflop,
            "nash_hits": self.nash_hits,
            "preflop_fallback_hits": self.preflop_fallback_hits,
            "postflop_decisions": self.postflop_decisions,
            "nash_hit_rate": nash_rate,
            "action_dist": dict(self.action_dist),
            "scenario_counts": dict(self.scenario_counts),
        }


def _safe(want: Action, obs: Observation) -> Action:
    """Replace `want` with the nearest legal action when not in obs.legal_actions."""
    if want in obs.legal_actions:
        return want
    if want == Action.ALL_IN:
        for fallback in (Action.RAISE_POT, Action.RAISE_HALF_POT, Action.CHECK_CALL):
            if fallback in obs.legal_actions:
                return fallback
    if want == Action.CHECK_CALL:
        if Action.FOLD in obs.legal_actions and obs.to_call > 0:
            # Can't call (e.g. forced all-in); fold if there's a cost.
            return Action.FOLD
        return obs.legal_actions[0]
    return Action.FOLD if Action.FOLD in obs.legal_actions else obs.legal_actions[0]
