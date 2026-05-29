"""Convert a poky.engine.Observation into a TexasSolver SpotKey.

The conversion is deliberately conservative for MVP:
- Cards: rlcard "HQ" -> TexasSolver "Qh" (suit/rank swap + lowercase).
- Board: only the community cards (3=flop, 4=turn, 5=river).
- Pot/stack: read directly from Observation in chips.
- Ranges: placeholders strings derived from position only (e.g. "BTN_open"
  / "BB_defend"). Real range strings are looked up by `RangeAtlas` in a
  later phase; for now this means the cache hit rate on a sparsely-populated
  DB will be very low — the architecture is the point.

Returns None when no SpotKey can be built (e.g. preflop, hole_cards missing,
or unrecognized num_players for the simplified position labels).
"""
from __future__ import annotations

from typing import Optional

from poky.engine import Observation, Stage
from poky.solver.spot_schema import SpotKey


# rlcard suit (upper) -> TexasSolver suit (lower)
_SUIT_MAP = {"S": "s", "H": "h", "D": "d", "C": "c"}


def card_rlcard_to_solver(card: str) -> str:
    """'HQ' -> 'Qh', 'D4' -> '4d', 'CT' -> 'Tc'."""
    if len(card) != 2:
        raise ValueError(f"unexpected rlcard format: {card!r}")
    suit_rlcard, rank = card[0], card[1]
    suit_solver = _SUIT_MAP.get(suit_rlcard)
    if suit_solver is None:
        raise ValueError(f"unknown suit: {card!r}")
    return f"{rank}{suit_solver}"


def _street_from_stage(stage: Stage) -> Optional[str]:
    if stage == Stage.FLOP:
        return "flop"
    if stage == Stage.TURN:
        return "turn"
    if stage == Stage.RIVER:
        return "river"
    return None


def _placeholder_range(position_label: str, role: str) -> str:
    """Return a stable placeholder range string keyed by (position, role).

    Real ranges will be plugged in by Z2.5 when we have a RangeAtlas.
    For now this means cache keys are stable but ranges are coarse — hits
    only happen if the build_cache used the same placeholder.
    """
    return f"{position_label}_{role}"


def observation_to_spot_key(
    obs: Observation,
    *,
    is_pfa: bool,
) -> Optional[SpotKey]:
    """Build a SpotKey from the current Observation.

    is_pfa: True if the hero is the preflop aggressor (raised before
            current street). Determines role labels (IP/OOP open vs defend).
    """
    street = _street_from_stage(obs.stage)
    if street is None:
        return None
    if not obs.community_cards or len(obs.community_cards) < 3:
        return None

    expected_len = {"flop": 3, "turn": 4, "river": 5}[street]
    if len(obs.community_cards) != expected_len:
        return None

    try:
        board = tuple(card_rlcard_to_solver(c) for c in obs.community_cards)
    except ValueError:
        return None

    # Effective stack = min of two stacks for HU; for >2 players take min
    # among alive opponents.
    eff_stack = min(obs.my_stack, *(s for s in obs.all_stacks if s > 0))

    # Position labels — only HU is supported by the cache for now.
    if obs.num_players != 2:
        return None
    pos_label_hero = "BTN" if obs.offset_from_btn == 1 else "BB"
    pos_label_villain = "BB" if pos_label_hero == "BTN" else "BTN"

    # IP/OOP in HU: postflop the BB is OOP, the BTN is IP.
    hero_is_ip = (pos_label_hero == "BTN")

    role_hero = "open" if is_pfa else "defend"
    role_villain = "defend" if is_pfa else "open"

    ip_range = _placeholder_range(
        "BTN" if hero_is_ip else "BB",
        role_hero if hero_is_ip else role_villain,
    )
    oop_range = _placeholder_range(
        "BB" if hero_is_ip else "BTN",
        role_villain if hero_is_ip else role_hero,
    )

    return SpotKey(
        street=street,
        board=board,
        pot_chips=int(obs.pot),
        effective_stack=int(eff_stack),
        ip_range=ip_range,
        oop_range=oop_range,
    )


def translate_solver_action(
    action_label: str,
    *,
    obs: Observation,
) -> Optional["object"]:
    """Map a TexasSolver action string to the closest legal poky Action.

    Returns None if no mapping makes sense (e.g. solver outputs CHECK but
    we must call — caller can fallback to ExpertOnly Tier 2).
    """
    from poky.engine import Action  # local import to avoid circulars

    label = action_label.strip().upper()
    if label.startswith("FOLD"):
        return Action.FOLD if Action.FOLD in obs.legal_actions else None
    if label.startswith("CHECK") or label.startswith("CALL"):
        return Action.CHECK_CALL if Action.CHECK_CALL in obs.legal_actions else None
    if label.startswith("ALLIN") or label.startswith("ALL_IN"):
        if Action.ALL_IN in obs.legal_actions:
            return Action.ALL_IN
        if Action.RAISE_POT in obs.legal_actions:
            return Action.RAISE_POT
        return None

    # BET <chips> or RAISE <chips>: bucket by (additional/pot) ratio.
    parts = label.split()
    if len(parts) < 2:
        return None
    try:
        chips = float(parts[1])
    except ValueError:
        return None

    additional = max(0.0, chips - float(obs.to_call))
    pot = max(1.0, float(obs.pot))
    ratio = additional / pot

    # Translate to discrete bucket; prefer larger if borderline + legal.
    if ratio >= 1.5 or chips >= obs.my_stack * 0.95:
        if Action.ALL_IN in obs.legal_actions:
            return Action.ALL_IN
        if Action.RAISE_POT in obs.legal_actions:
            return Action.RAISE_POT
    if ratio >= 0.66:
        if Action.RAISE_POT in obs.legal_actions:
            return Action.RAISE_POT
        if Action.RAISE_HALF_POT in obs.legal_actions:
            return Action.RAISE_HALF_POT
    if ratio >= 0.33:
        if Action.RAISE_HALF_POT in obs.legal_actions:
            return Action.RAISE_HALF_POT
        if Action.RAISE_POT in obs.legal_actions:
            return Action.RAISE_POT
    # ratio < 0.33: treat as passive (would be a min-bet) -> CHECK_CALL
    if Action.CHECK_CALL in obs.legal_actions:
        return Action.CHECK_CALL
    return None
