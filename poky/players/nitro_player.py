"""NitroPlayer — orchestrator for 3-max hyper-turbo (Winamax Expresso Nitro).

Decision pipeline:
  1. Preflop: detect scenario, look up Nash push/fold freq, apply exploit
     overrides based on per-opponent classifications, sample push/call/fold.
  2. Postflop: delegate to HeuristicPlayer (at 15bb start, postflop is shallow).
  3. Fallback to HeuristicPlayer for unrecognized scenarios.

Profiling layer (N5):
  - `_profiles: dict[seat, OpponentProfile]` — survives `reset()` between hands
  - Loaded from `profile_db` at start of session (via `opp_ids` mapping)
  - Updated in `observe_action()` from preflop actions
  - Flushed back to DB after each hand (`flush_profiles()`)
  - Classifications drive exploit overrides via `poky.nitro.exploits`

ICM mode: `use_icm=True` reserved for future. Current v1 = chip-EV only.
"""
from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, Optional

from poky.abstraction.preflop import canonical_class, class_name
from poky.engine import Action, Observation, PlayerStatus, Stage
from poky.nitro import exploits as nitro_exploits
from poky.nitro.postflop import postflop_decision
from poky.nitro.profile_db import ProfileDB
from poky.nitro.profiling import (
    ARCHETYPE_UNKNOWN, OpponentProfile,
    classify_archetype, mark_seen, update_profile,
)
from poky.nitro.ranges import available_stacks, get_strategy
from poky.players.base import ActionEvent, Player
from poky.players.heuristic import HeuristicPlayer


_AGGRESSIVE_ACTIONS = {Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN}

# N5.5 — iso-push range vs limpers at short stack.
# These are the WIDE thresholds, applied only when the limper is CLASSIFIED
# as LIMPER (i.e., we have evidence they limp weak hands frequently).
# For UNKNOWN limpers we use a conservative 20% fallback in _handle_iso_push.
# For NIT/TAG/etc we don't iso-push at all (fall back).
NUM_HAND_CLASSES = 169
_ISO_PUSH_TOP_PCT = {
    "sb_vs_btn_limp":  0.50,    # SB iso-push vs known-LIMPER BTN (top 50%)
    "bb_vs_limp":      0.55,    # BB iso-push vs known-LIMPER (top 55%)
    "bb_vs_sb_limp":   0.50,    # BB iso-push vs known-LIMPER SB (top 50%)
}


class NitroPlayer(Player):
    """Nash-based 3-max hyper-turbo SnG player with opponent profiling.

    Args:
        seed: RNG seed for mixed-strategy sampling and HeuristicPlayer fallback
        opp_ids: optional mapping {seat_id -> username string} for cross-session
                 profile loading. If None, no DB lookup (in-session learning only).
        profile_db: optional ProfileDB instance for persistent storage.
        use_icm: reserved (v1 = chip-EV only)
        exploit_level: deprecated; profile-driven exploits via `exploits.py` now.
        fallback_postflop: custom postflop player (default = HeuristicPlayer)
        payouts: ICM payout structure (placeholder)
        use_profiling: master switch (default True) — disable to revert to pure Nash
    """

    name = "nitro"

    def __init__(
        self,
        seed: Optional[int] = None,
        opp_ids: Optional[Dict[int, str]] = None,
        profile_db: Optional[ProfileDB] = None,
        use_icm: bool = False,
        exploit_level: float = 0.0,
        fallback_postflop: Optional[Player] = None,
        payouts: Optional[list] = None,
        use_profiling: bool = True,
        use_postflop_spr: bool = False,
    ):
        self.use_postflop_spr = use_postflop_spr
        self.rng = random.Random(seed)
        self.use_icm = use_icm
        self.exploit_level = max(0.0, min(1.0, exploit_level))
        self.payouts = payouts or [100.0, 0.0, 0.0]
        self.fallback = fallback_postflop or HeuristicPlayer(seed=seed)
        self.use_profiling = use_profiling

        # Profile state (survives reset)
        self.opp_ids: Dict[int, str] = dict(opp_ids or {})
        self.profile_db = profile_db
        self._profiles: Dict[int, OpponentProfile] = {}
        self._db_loaded = False

        # Per-hand state (reset between hands)
        self._preflop_status: dict = {}
        self._last_dealer_id: Optional[int] = None
        self._last_big_blind: Optional[int] = None
        self._last_stacks_snapshot: Optional[list] = None
        self._hand_seen_marked = False

        # Diagnostics
        self.nash_hits = 0
        self.preflop_fallback_hits = 0
        self.postflop_decisions = 0
        self.action_dist: dict = defaultdict(int)
        self.scenario_counts: dict = defaultdict(int)
        self.archetype_counts: dict = defaultdict(int)

    # ---- Player API -------------------------------------------------

    def act(self, obs: Observation) -> Action:
        # Snapshot obs context for opponent stack estimation in observe_action.
        self._last_dealer_id = obs.dealer_id
        self._last_big_blind = obs.big_blind
        self._last_stacks_snapshot = list(obs.all_stacks)

        if obs.num_players != 3:
            return self.fallback.act(obs)

        if obs.stage != Stage.PREFLOP:
            self.postflop_decisions += 1
            # N5.7 — SPR commit rules (opt-in via `use_postflop_spr` flag).
            # Default disabled because empirically the rules hurt vs LAG
            # (we fold to too many of their bets). Keep available for tuning.
            if getattr(self, "use_postflop_spr", False):
                decision = postflop_decision(obs, self.rng)
                if decision is not None and decision in obs.legal_actions:
                    action = decision
                    self.action_dist[action] += 1
                    return action
            action = self.fallback.act(obs)
            self.action_dist[action] += 1
            return action

        return self._preflop_decision(obs)

    def observe_action(self, event: ActionEvent) -> None:
        # Preflop status tracking (existing logic for scenario detection)
        if event.stage == Stage.PREFLOP:
            if event.action == Action.FOLD:
                self._preflop_status[event.actor] = "fold"
            elif event.action in _AGGRESSIVE_ACTIONS:
                self._preflop_status[event.actor] = "push"
            elif event.action == Action.CHECK_CALL:
                already_pushed = any(
                    s == "push" for s in self._preflop_status.values()
                )
                self._preflop_status[event.actor] = "call" if already_pushed else "limp"

        # Profile tracking (new)
        if self.use_profiling and event.stage == Stage.PREFLOP:
            self._update_opp_profile(event)

        self.fallback.observe_action(event)

    def reset(self) -> None:
        """Reset per-hand state. Profiles are PRESERVED across hands."""
        # Per-hand state cleared
        self._preflop_status = {}
        self._hand_seen_marked = False
        # Don't clear: _profiles, opp_ids, profile_db, _last_* snapshots
        self.fallback.reset()

    # ---- Profile management -----------------------------------------

    def _load_profiles_from_db(self) -> None:
        """One-time DB load for known opp_ids. Called lazily."""
        if self.profile_db is None or not self.opp_ids:
            self._db_loaded = True
            return
        for seat, opp_id in self.opp_ids.items():
            loaded = self.profile_db.load(opp_id)
            if loaded is not None:
                self._profiles[seat] = loaded
        self._db_loaded = True

    def flush_profiles(self) -> None:
        """Persist all in-memory profiles to DB. Called by SnGRunner after each hand."""
        if self.profile_db is None:
            return
        for seat, profile in self._profiles.items():
            if profile.opp_id:   # only persist named opponents
                self.profile_db.save(profile)

    def _get_or_create_profile(self, seat: int) -> OpponentProfile:
        if not self._db_loaded:
            self._load_profiles_from_db()
        if seat not in self._profiles:
            opp_id = self.opp_ids.get(seat, f"_seat{seat}")
            self._profiles[seat] = OpponentProfile(opp_id=opp_id)
        return self._profiles[seat]

    def _estimate_stack_bb(self, actor: int, event: ActionEvent) -> float:
        """Estimate the actor's stack in BB at the time of their decision.

        Uses the last act()-time snapshot if available. Otherwise defaults to
        15bb (typical Nitro starting stack). Slight inaccuracy is fine — we
        only use this for the optional `push_short` counter, which doubles up
        with the simpler `pfr` Maniac detection.
        """
        bb = event.big_blind or self._last_big_blind or 2
        if self._last_stacks_snapshot and actor < len(self._last_stacks_snapshot):
            # Snapshot is from MY act() time; for opp acting after me it's accurate,
            # for opp acting before me it's stale (but close enough for short detection).
            est_stack = self._last_stacks_snapshot[actor]
            return max(0.0, est_stack) / max(bb, 1)
        return 15.0   # default assumption

    def _update_opp_profile(self, event: ActionEvent) -> None:
        actor = event.actor
        # Don't profile ourselves — track only opponents.
        # We can't easily know "self" here; in practice, NitroPlayer is unique
        # in the seat list, so we update all seats including self (harmless).
        profile = self._get_or_create_profile(actor)

        # Determine prior_aggression from all_committed_before
        bb = event.big_blind or self._last_big_blind or 2
        prior_aggression = max(event.all_committed_before) > bb

        stack_bb = self._estimate_stack_bb(actor, event)

        update_profile(
            profile,
            is_preflop=(event.stage == Stage.PREFLOP),
            action=event.action,
            prior_aggression=prior_aggression,
            stack_bb=stack_bb,
            is_blind_post=False,   # rlcard blinds don't fire observe_action
        )
        if not self._hand_seen_marked:
            # Mark all seats as having played a hand (called once per hand)
            for s, p in self._profiles.items():
                if s == actor:  # only really know they played if we observed them act
                    pass
            mark_seen(profile)

    # ---- Preflop logic ----------------------------------------------

    def _preflop_decision(self, obs: Observation) -> Action:
        scenario = self._detect_scenario(obs)
        if scenario is None:
            return self._fallback_preflop(obs, reason="scenario_unknown")

        hand_name = class_name(canonical_class(obs.hole_cards[0], obs.hole_cards[1]))
        eff_stack_bb = (obs.my_stack + obs.my_committed) / obs.big_blind

        # N5.5 — limped-pot scenarios use hardcoded iso-push thresholds
        # (Nash table only covers push/fold scenarios; limps fall outside).
        if scenario in _ISO_PUSH_TOP_PCT:
            return self._handle_iso_push(obs, scenario, hand_name)

        if not available_stacks():
            return self._fallback_preflop(obs, reason="no_tables")

        freq = get_strategy(eff_stack_bb, scenario, hand_name)
        if freq is None:
            return self._fallback_preflop(obs, reason="hand_or_scenario_missing")

        if self.use_profiling:
            freq = self._apply_profile_exploits(freq, scenario, obs)
        elif self.exploit_level > 0:
            freq = self._apply_exploits_legacy(scenario, hand_name, freq)

        self.nash_hits += 1
        self.scenario_counts[scenario] += 1
        is_aggressive = self.rng.random() < freq
        action = self._map_to_action(scenario, is_aggressive, obs)
        self.action_dist[action] += 1
        return action

    def _handle_iso_push(self, obs: Observation, scenario: str,
                         hand_name: str) -> Action:
        """Decide push/fold vs a limper.

        Strategy depends on the limper's classification:
          - LIMPER (limp_freq high): iso-push moderately wide (top 35-45%) —
            their range is weak, we have high fold equity.
          - UNKNOWN: iso-push conservatively (top 20-25%) — could be either
            a fish limping junk or a TAG slow-playing premium; play safe.
          - Anything else (NIT, TAG, LAG, ...): fall back to Nash via a
            push/fold lookup if available, else heuristic. NIT especially
            often limps premiums, so pushing into them is -EV.
        """
        from poky.nitro.profiling import (
            ARCHETYPE_LIMPER, ARCHETYPE_UNKNOWN, classify_archetype,
        )

        # Find the limper's seat (where _preflop_status[seat] == "limp")
        limper_seat = None
        for seat, status in self._preflop_status.items():
            if status == "limp":
                limper_seat = seat
                break

        limper_archetype = ARCHETYPE_UNKNOWN
        if limper_seat is not None and limper_seat in self._profiles:
            limper_archetype = classify_archetype(self._profiles[limper_seat])

        # Decide threshold by archetype
        if limper_archetype == ARCHETYPE_LIMPER:
            base_top_pct = _ISO_PUSH_TOP_PCT.get(scenario, 0.40)   # wider iso
        elif limper_archetype == ARCHETYPE_UNKNOWN:
            # Conservative — could be a trap. Top 20%.
            base_top_pct = 0.20
        else:
            # NIT/TAG/LAG/STATION/MANIAC: don't iso-push, fall back.
            return self._fallback_preflop(obs, reason=f"limp_{limper_archetype.lower()}")

        threshold = int(base_top_pct * NUM_HAND_CLASSES)
        hand_class = canonical_class(obs.hole_cards[0], obs.hole_cards[1])
        is_push = hand_class < threshold

        self.nash_hits += 1
        self.scenario_counts[scenario] += 1
        action = _safe(Action.ALL_IN if is_push else Action.FOLD, obs)
        self.action_dist[action] += 1
        return action

    def _apply_profile_exploits(self, freq: float, scenario: str,
                                 obs: Observation) -> float:
        """Classify each seat then apply scenario-adjusted exploit override."""
        classifications: Dict[int, str] = {}
        for seat, profile in self._profiles.items():
            if seat == obs.player_id:
                continue  # don't classify self
            arch = classify_archetype(profile)
            classifications[seat] = arch
            self.archetype_counts[arch] += 1
        return nitro_exploits.adjust_for_scenario(
            base_freq=freq,
            scenario=scenario,
            dealer_id=obs.dealer_id,
            classifications=classifications,
            num_players=3,
        )

    def _detect_scenario(self, obs: Observation) -> Optional[str]:
        hero = obs.player_id
        pos_offset = (hero - obs.dealer_id) % 3
        btn_id = obs.dealer_id
        sb_id = (obs.dealer_id + 1) % 3

        if pos_offset == 0:
            return "btn_push"

        if pos_offset == 1:
            btn_status = self._preflop_status.get(btn_id)
            if btn_status == "fold":
                return "sb_push_after_btn_fold"
            if btn_status == "push":
                return "sb_call_vs_btn"
            if btn_status == "limp":
                return "sb_vs_btn_limp"   # N5.5 — iso-push opportunity
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
            # N5.5 — limped pots from BB perspective
            if btn_status == "limp" and sb_status in (None, "call", "limp"):
                return "bb_vs_limp"
            if btn_status == "fold" and sb_status == "limp":
                return "bb_vs_sb_limp"
            return None

        return None

    def _apply_exploits_legacy(self, scenario: str, hand_name: str,
                                 freq: float) -> float:
        """Old single-knob exploit (kept for backward compat when use_profiling=False)."""
        if self.exploit_level <= 0:
            return freq
        if scenario in ("btn_push", "sb_push_after_btn_fold"):
            return min(1.0, freq + 0.1 * self.exploit_level)
        if scenario in ("sb_call_vs_btn", "bb_call_3way",
                        "bb_call_vs_btn", "bb_call_vs_sb"):
            return max(0.0, freq - 0.05 * self.exploit_level)
        return freq

    def _map_to_action(self, scenario: str, is_aggressive: bool,
                       obs: Observation) -> Action:
        if not is_aggressive:
            return _safe(Action.FOLD, obs)
        if scenario in ("btn_push", "sb_push_after_btn_fold"):
            return _safe(Action.ALL_IN, obs)
        return _safe(Action.CHECK_CALL, obs)

    def _fallback_preflop(self, obs: Observation, reason: str) -> Action:
        self.preflop_fallback_hits += 1
        self.scenario_counts[f"_fallback_{reason}"] += 1
        action = self.fallback.act(obs)
        self.action_dist[action] += 1
        return action

    # ---- Diagnostics ------------------------------------------------

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
            "archetype_counts": dict(self.archetype_counts),
            "n_profiles": len(self._profiles),
        }


def _safe(want: Action, obs: Observation) -> Action:
    """Map `want` to closest legal action."""
    if want in obs.legal_actions:
        return want
    if want == Action.ALL_IN:
        for fallback in (Action.RAISE_POT, Action.RAISE_HALF_POT, Action.CHECK_CALL):
            if fallback in obs.legal_actions:
                return fallback
    if want == Action.CHECK_CALL:
        if Action.FOLD in obs.legal_actions and obs.to_call > 0:
            return Action.FOLD
        return obs.legal_actions[0]
    return Action.FOLD if Action.FOLD in obs.legal_actions else obs.legal_actions[0]
