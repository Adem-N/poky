"""ProShortStackPlayer — strong 3-max 15bb push/fold opponent.

Simulates a human pro who has studied push/fold Nash for short-stack 3-max
and plays close to GTO. Uses the same Nash tables NitroPlayer uses, but
WITHOUT any exploit overrides or profiling — pure baseline strategy.

Used by `scripts/play_vs_nitro.py` to test if NitroPlayer's exploits give
it edge over a pure Nash opponent.
"""
from __future__ import annotations

import random
from typing import Optional

from poky.abstraction.preflop import canonical_class, class_name
from poky.engine import Action, Observation, PlayerStatus, Stage
from poky.nitro.ranges import available_stacks, get_strategy
from poky.players.base import ActionEvent, Player
from poky.players.heuristic import HeuristicPlayer


_AGGRESSIVE = {Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN}


def _safe(want: Action, obs: Observation) -> Action:
    if want in obs.legal_actions:
        return want
    if want == Action.ALL_IN:
        for f in (Action.RAISE_POT, Action.RAISE_HALF_POT, Action.CHECK_CALL):
            if f in obs.legal_actions:
                return f
    if want == Action.CHECK_CALL:
        return Action.FOLD if (Action.FOLD in obs.legal_actions and obs.to_call > 0) else obs.legal_actions[0]
    return Action.FOLD if Action.FOLD in obs.legal_actions else obs.legal_actions[0]


class ProShortStackPlayer(Player):
    """A strong human-equivalent player for 3-max 15bb push/fold scenarios.

    Strategy:
      - Preflop: consult the same Nash tables as NitroPlayer (push/fold only)
      - Postflop: SPR-based commit (TPTK+ at SPR<=2.5, else fold)
      - Fallback to HeuristicPlayer for edge cases

    Difference vs NitroPlayer: NO profile-based exploits, NO pop baseline tilt.
    Pure Nash baseline → represents a reg who has studied charts but doesn't
    adapt mid-session.
    """

    name = "pro_shortstack"

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.fallback = HeuristicPlayer(seed=seed)
        self._preflop_status: dict = {}

    def act(self, obs: Observation) -> Action:
        if obs.num_players != 3:
            return self.fallback.act(obs)
        if obs.stage != Stage.PREFLOP:
            return self._postflop_decision(obs)
        return self._preflop_decision(obs)

    def observe_action(self, event: ActionEvent) -> None:
        if event.stage == Stage.PREFLOP:
            if event.action == Action.FOLD:
                self._preflop_status[event.actor] = "fold"
            elif event.action in _AGGRESSIVE:
                self._preflop_status[event.actor] = "push"
            elif event.action == Action.CHECK_CALL:
                already_pushed = any(
                    s == "push" for s in self._preflop_status.values()
                )
                self._preflop_status[event.actor] = "call" if already_pushed else "limp"
        self.fallback.observe_action(event)

    def reset(self) -> None:
        self._preflop_status = {}
        self.fallback.reset()

    def _preflop_decision(self, obs: Observation) -> Action:
        scenario = self._detect_scenario(obs)
        if scenario is None:
            return self.fallback.act(obs)
        hand_name = class_name(canonical_class(obs.hole_cards[0], obs.hole_cards[1]))
        eff_stack_bb = (obs.my_stack + obs.my_committed) / obs.big_blind
        if not available_stacks():
            return self.fallback.act(obs)
        freq = get_strategy(eff_stack_bb, scenario, hand_name)
        if freq is None:
            return self.fallback.act(obs)
        is_aggressive = self.rng.random() < freq
        if not is_aggressive:
            return _safe(Action.FOLD, obs)
        if scenario in ("btn_push", "sb_push_after_btn_fold"):
            return _safe(Action.ALL_IN, obs)
        return _safe(Action.CHECK_CALL, obs)

    def _detect_scenario(self, obs: Observation) -> Optional[str]:
        pos = (obs.player_id - obs.dealer_id) % 3
        btn_id = obs.dealer_id
        sb_id = (obs.dealer_id + 1) % 3
        if pos == 0:
            return "btn_push"
        if pos == 1:
            s = self._preflop_status.get(btn_id)
            if s == "fold": return "sb_push_after_btn_fold"
            if s == "push": return "sb_call_vs_btn"
            return None
        if pos == 2:
            b = self._preflop_status.get(btn_id)
            s = self._preflop_status.get(sb_id)
            if b == "push" and s == "call": return "bb_call_3way"
            if b == "push" and s == "fold": return "bb_call_vs_btn"
            if b == "fold" and s == "push": return "bb_call_vs_sb"
            return None
        return None

    def _postflop_decision(self, obs: Observation) -> Action:
        # Simple SPR commit
        spr = obs.my_stack / max(obs.pot, 1)
        # Use heuristic if SPR deep
        if spr > 4:
            return self.fallback.act(obs)
        # At low SPR, use simple rule: commit if we have any pair+
        from phevaluator import evaluate_cards
        from poky.equity.estimator import rlcard_to_phev
        try:
            hole_p = [rlcard_to_phev(c) for c in obs.hole_cards]
            board_p = [rlcard_to_phev(c) for c in obs.community_cards]
            if len(board_p) < 3:
                return self.fallback.act(obs)
            score = evaluate_cards(*(hole_p + board_p))
            # Pair or better (phev score <= 6185)
            if score <= 6185 and spr <= 2.5:
                # Commit
                for a in (Action.ALL_IN, Action.RAISE_POT,
                          Action.RAISE_HALF_POT, Action.CHECK_CALL):
                    if a in obs.legal_actions:
                        return a
            # Otherwise fold-or-check
            if obs.to_call == 0 and Action.CHECK_CALL in obs.legal_actions:
                return Action.CHECK_CALL
            if Action.FOLD in obs.legal_actions:
                return Action.FOLD
            return obs.legal_actions[0]
        except Exception:
            return self.fallback.act(obs)
