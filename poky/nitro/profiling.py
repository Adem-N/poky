"""Opponent profiling — counters, stats, archetype classification.

Tracks per-opponent stats from observed preflop actions and showdowns.
Classifies opponents into one of 7 archetypes when there is enough signal.

Designed for *small-sample* Nitro use:
  - 5-8 hands per opponent within a single SnG
  - 100-300 hands per opponent across many sessions (via ProfileDB)

For small samples we rely on *extreme behavior* (Maniac push 3/3 = obvious)
rather than precise stats. For larger samples (cross-session DB), fuller
VPIP/PFR signatures become reliable enough for TAG/LAG categorisation.

Action categorisation (preflop only — postflop stats deferred to N5+):

    FOLD               -> if prior_aggression: face_aggression + fold_aggression
                          else: not voluntary; ignored
    CHECK_CALL         -> vpip
                          if prior_aggression: face_aggression + call_aggression
                          else: limp (called the BB; "open-limp" in 3-max)
    RAISE_HALF_POT/POT -> vpip + pfr
                          if prior_aggression: face_aggression + reraise
                          if stack_bb <= 12 AND action == ALL_IN: push_short
    ALL_IN (preflop)   -> vpip + pfr + (push_short if stack_bb <= 12)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, List, Optional

from poky.engine import Action


# Archetype labels (used in exploits.py for override lookup).
ARCHETYPE_MANIAC = "MANIAC"
ARCHETYPE_NIT = "NIT"
ARCHETYPE_STATION = "STATION"
ARCHETYPE_LIMPER = "LIMPER"
ARCHETYPE_LAG = "LAG"
ARCHETYPE_TAG = "TAG"
ARCHETYPE_UNKNOWN = "UNKNOWN"

ALL_ARCHETYPES = (
    ARCHETYPE_MANIAC, ARCHETYPE_NIT, ARCHETYPE_STATION, ARCHETYPE_LIMPER,
    ARCHETYPE_LAG, ARCHETYPE_TAG, ARCHETYPE_UNKNOWN,
)

# Cap on the showdown history (rolling buffer).
SHOWDOWN_HISTORY_CAP = 20

# Aggressive actions for VPIP / PFR counting.
_AGGR_ACTIONS = (Action.RAISE_HALF_POT, Action.RAISE_POT, Action.ALL_IN)


@dataclass
class OpponentProfile:
    """All counters for one opponent. Stats are derived via properties."""
    opp_id: str
    n_hands_observed: int = 0
    # Preflop voluntary action counters
    n_voluntary_actions: int = 0   # decisions excluding auto-posted blinds
    n_vpip: int = 0                # voluntarily put money in pot (call/raise)
    n_pfr: int = 0                 # preflop raise / all-in
    n_limp: int = 0                # call-the-BB with no prior aggression
    # Short-stack push tracking
    n_push_short: int = 0          # all-in when stack <= 12bb
    n_opportunities_short: int = 0  # voluntary decisions when stack <= 12bb
    # Defending stats
    n_face_aggression: int = 0     # had to act with to_call > 0 from a raise
    n_call_aggression: int = 0
    n_fold_aggression: int = 0
    n_reraise: int = 0
    # Showdown stats (when opp's cards are revealed)
    n_showdowns: int = 0
    showdown_hands: List[int] = field(default_factory=list)  # hand class IDs
    # Bookkeeping
    last_seen: str = ""

    # ---- Derived stats (safe division: 0/0 -> 0) ----

    @property
    def vpip(self) -> float:
        return self.n_vpip / self.n_voluntary_actions if self.n_voluntary_actions else 0.0

    @property
    def pfr(self) -> float:
        return self.n_pfr / self.n_voluntary_actions if self.n_voluntary_actions else 0.0

    @property
    def limp_freq(self) -> float:
        return self.n_limp / self.n_voluntary_actions if self.n_voluntary_actions else 0.0

    @property
    def push_short_freq(self) -> float:
        return self.n_push_short / self.n_opportunities_short if self.n_opportunities_short else 0.0

    @property
    def fold_to_aggr_freq(self) -> float:
        return self.n_fold_aggression / self.n_face_aggression if self.n_face_aggression else 0.0

    @property
    def call_to_aggr_freq(self) -> float:
        return self.n_call_aggression / self.n_face_aggression if self.n_face_aggression else 0.0

    def to_dict(self) -> dict:
        return {
            "opp_id": self.opp_id,
            "n_hands_observed": self.n_hands_observed,
            "n_voluntary_actions": self.n_voluntary_actions,
            "n_vpip": self.n_vpip,
            "n_pfr": self.n_pfr,
            "n_limp": self.n_limp,
            "n_push_short": self.n_push_short,
            "n_opportunities_short": self.n_opportunities_short,
            "n_face_aggression": self.n_face_aggression,
            "n_call_aggression": self.n_call_aggression,
            "n_fold_aggression": self.n_fold_aggression,
            "n_reraise": self.n_reraise,
            "n_showdowns": self.n_showdowns,
            "showdown_hands": list(self.showdown_hands),
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpponentProfile":
        return cls(
            opp_id=d["opp_id"],
            n_hands_observed=d.get("n_hands_observed", 0),
            n_voluntary_actions=d.get("n_voluntary_actions", 0),
            n_vpip=d.get("n_vpip", 0),
            n_pfr=d.get("n_pfr", 0),
            n_limp=d.get("n_limp", 0),
            n_push_short=d.get("n_push_short", 0),
            n_opportunities_short=d.get("n_opportunities_short", 0),
            n_face_aggression=d.get("n_face_aggression", 0),
            n_call_aggression=d.get("n_call_aggression", 0),
            n_fold_aggression=d.get("n_fold_aggression", 0),
            n_reraise=d.get("n_reraise", 0),
            n_showdowns=d.get("n_showdowns", 0),
            showdown_hands=list(d.get("showdown_hands", [])),
            last_seen=d.get("last_seen", ""),
        )


def update_profile(
    profile: OpponentProfile,
    *,
    is_preflop: bool,
    action: Action,
    prior_aggression: bool,
    stack_bb: float,
    is_blind_post: bool = False,
) -> None:
    """Update counters based on one action observed.

    Postflop actions are currently ignored (preflop signals carry the bulk
    of the archetype information for short-stack Nitro). Extend in N5+ if
    needed.
    """
    if not is_preflop or is_blind_post:
        return

    # Auto-fold to a BB walk doesn't tell us anything: only count folds that
    # required a real fold decision (faced a raise or had option to limp).
    if action == Action.FOLD and not prior_aggression:
        # Player wasn't really "voluntary" — they can fold for free pre-BB.
        # Still count as a voluntary action (they CHOSE to fold).
        profile.n_voluntary_actions += 1
        return

    profile.n_voluntary_actions += 1

    if stack_bb <= 12:
        profile.n_opportunities_short += 1

    if action == Action.FOLD:
        # Implies prior_aggression == True (handled above)
        profile.n_face_aggression += 1
        profile.n_fold_aggression += 1
        return

    if action == Action.CHECK_CALL:
        profile.n_vpip += 1
        if prior_aggression:
            profile.n_face_aggression += 1
            profile.n_call_aggression += 1
        else:
            # Open-limped (called BB with no prior raise)
            profile.n_limp += 1
        return

    if action in _AGGR_ACTIONS:
        profile.n_vpip += 1
        profile.n_pfr += 1
        if prior_aggression:
            profile.n_face_aggression += 1
            profile.n_reraise += 1
        if action == Action.ALL_IN and stack_bb <= 12:
            profile.n_push_short += 1
        return


def record_showdown(profile: OpponentProfile, hand_class_id: int) -> None:
    """Append the revealed hand class to the rolling showdown history."""
    profile.n_showdowns += 1
    profile.showdown_hands.append(int(hand_class_id))
    if len(profile.showdown_hands) > SHOWDOWN_HISTORY_CAP:
        # Keep only the most recent K
        profile.showdown_hands = profile.showdown_hands[-SHOWDOWN_HISTORY_CAP:]


def mark_seen(profile: OpponentProfile) -> None:
    """Update last_seen timestamp and increment n_hands_observed."""
    profile.n_hands_observed += 1
    profile.last_seen = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def classify_archetype(profile: OpponentProfile) -> str:
    """Map a profile to one of the 7 archetype labels.

    Priority order (first matching wins):
      1. MANIAC  — extreme push freq at short stack
      2. STATION — calls almost everything
      3. NIT     — folds way too much or vpip super tight
      4. LIMPER  — limps a lot (heuristic / loose-passive)
      5. LAG     — wide and aggressive
      6. TAG     — Nash-like baseline
      7. UNKNOWN — not enough data

    Each rule has a confidence gate (min sample size) to avoid flickering
    on tiny samples.
    """
    # 1. MANIAC: raises very frequently (jams any-2 vibe)
    # Two signals, EITHER triggers:
    #   a) push_short_freq high when stack tracking is available
    #   b) PFR very high overall (works without stack tracking)
    if profile.n_opportunities_short >= 3 and profile.push_short_freq > 0.5:
        return ARCHETYPE_MANIAC
    # Lowered to 0.50 so Maniacs who mix raises with calls still get caught.
    if profile.n_voluntary_actions >= 4 and profile.pfr > 0.50:
        return ARCHETYPE_MANIAC

    # 2. STATION: rarely folds to aggression (calls everything down)
    if profile.n_face_aggression >= 5 and profile.fold_to_aggr_freq < 0.30:
        return ARCHETYPE_STATION

    # 3. NIT: very tight (extreme fold freq, or VPIP very low)
    # Strict threshold to avoid over-classifying TAG/LAG as NIT (their vpip
    # can dip in 5-8 hand samples at hyper-turbo).
    if profile.n_voluntary_actions >= 5:
        if profile.vpip < 0.15:
            return ARCHETYPE_NIT
        if profile.n_face_aggression >= 4 and profile.fold_to_aggr_freq > 0.80:
            return ARCHETYPE_NIT

    # 4. LIMPER: limps a lot (heuristic / soft player)
    if profile.n_voluntary_actions >= 6 and profile.limp_freq > 0.35:
        return ARCHETYPE_LIMPER

    # 5-6. TAG / LAG require more sample for precision
    if profile.n_voluntary_actions >= 10:
        if profile.vpip > 0.40 and profile.pfr > 0.25:
            return ARCHETYPE_LAG
        if 0.20 <= profile.vpip <= 0.35 and 0.15 <= profile.pfr <= 0.25:
            return ARCHETYPE_TAG

    return ARCHETYPE_UNKNOWN
