"""SPR-based postflop commit rules for short-stack 3-max.

At 15bb starting stack, postflop SPR is usually 0.5-4 after the preflop
action. At low SPR, postflop play collapses to binary "commit vs fold"
decisions based on hand strength.

Rules (`postflop_decision`):
  - Quads, Full house, Flush, Straight, Trips/Set: always commit
  - Two pair: commit at SPR <= 4
  - One pair:
      * Top pair: commit at SPR <= 3
      * Middle/under pair: commit at SPR <= 1.5
  - High card: fold to any bet (check if free)

Implementation uses phevaluator for hand strength classification. Returns
None when the situation is outside short-stack scope (no board, SPR very
deep) — caller falls back to HeuristicPlayer.
"""
from __future__ import annotations

import random
from typing import List, Optional

from phevaluator import evaluate_cards

from poky.engine import Action, Observation, Stage
from poky.equity.estimator import rlcard_to_phev


# Phevaluator hand-class thresholds (lower = stronger; max = 7462).
# https://en.wikipedia.org/wiki/Poker_hands and phevaluator README.
_QUADS_PLUS = 322       # straight flush, quads, full house
_FLUSH = 1599
_STRAIGHT = 1609
_TRIPS = 2467           # trips/set
_TWO_PAIR = 3325
_ONE_PAIR = 6185
# > 6185 = high card / nothing

# SPR commit thresholds per hand category. Mid-range values balancing
# value-committing vs not bleeding to passive-tight regs.
_COMMIT_SPR = {
    "monster":   1e9,    # always commit (quads+/flush/straight/trips)
    "two_pair":  3.5,
    "top_pair":  2.5,
    "mid_pair":  1.2,
    "high_card": 0.5,    # commit only if already pot-committed
}


def _classify_hand(hole_rlcard: List[str], board_rlcard: List[str]) -> str:
    """Return one of: monster, two_pair, top_pair, mid_pair, high_card."""
    hole_p = [rlcard_to_phev(c) for c in hole_rlcard]
    board_p = [rlcard_to_phev(c) for c in board_rlcard]
    score = evaluate_cards(*(hole_p + board_p))
    if score <= _TRIPS:
        return "monster"
    if score <= _TWO_PAIR:
        return "two_pair"
    if score <= _ONE_PAIR:
        # Distinguish top pair vs middle/under pair: compare our hole ranks
        # to the highest board rank.
        return _classify_pair_strength(hole_rlcard, board_rlcard)
    return "high_card"


_RANK_ORDER = "23456789TJQKA"


def _rank_value(card: str) -> int:
    """rlcard card 'HQ' -> 12 (Q rank), 'D4' -> 4."""
    return _RANK_ORDER.index(card[1]) + 2  # 2..14


def _classify_pair_strength(hole_rlcard: List[str],
                            board_rlcard: List[str]) -> str:
    """Given we have a pair (one_pair score range), is it top/mid/under?"""
    board_ranks = sorted({_rank_value(c) for c in board_rlcard}, reverse=True)
    hole_ranks = {_rank_value(c) for c in hole_rlcard}

    # Pocket pair case (both hole ranks the same)
    if len(hole_ranks) == 1:
        pp = next(iter(hole_ranks))
        top_board = board_ranks[0]
        if pp > top_board:
            return "top_pair"      # overpair (e.g. JJ on T82) is "top pair+" eq
        return "mid_pair"          # under-pair to board

    # Made pair with the board (one of our hole ranks matches a board rank)
    paired_rank = max(hole_ranks & set(board_ranks), default=0)
    if paired_rank == 0:
        # No pair? Shouldn't happen if phev said one_pair; fall back to mid.
        return "mid_pair"
    if paired_rank == board_ranks[0]:
        return "top_pair"
    return "mid_pair"


def postflop_decision(obs: Observation,
                       rng: Optional[random.Random] = None) -> Optional[Action]:
    """SPR-based commit decision. Returns None if outside short-stack scope.

    `rng` is currently unused (deterministic decisions) but kept for future
    randomization at borderline SPR cases.
    """
    if obs.stage == Stage.PREFLOP or len(obs.community_cards) < 3:
        return None   # not for preflop or pre-flop
    if obs.my_stack <= 0:
        return None

    spr = obs.my_stack / max(obs.pot, 1)
    if spr > 5:
        return None   # deep stack — let heuristic handle it

    category = _classify_hand(obs.hole_cards, obs.community_cards)
    threshold = _COMMIT_SPR.get(category, 0)
    should_commit = spr <= threshold

    if should_commit:
        # Pick the strongest aggressive action available.
        for a in (Action.ALL_IN, Action.RAISE_POT,
                  Action.RAISE_HALF_POT, Action.CHECK_CALL):
            if a in obs.legal_actions:
                return a
        return obs.legal_actions[0]

    # Don't commit: check if free, fold if facing a bet (unless tiny bet
    # giving good odds).
    if obs.to_call == 0 and Action.CHECK_CALL in obs.legal_actions:
        return Action.CHECK_CALL
    # Facing a bet — pot odds check
    pot_odds = obs.to_call / max(obs.pot + obs.to_call, 1)
    if pot_odds < 0.20 and Action.CHECK_CALL in obs.legal_actions:
        # Getting good odds (need <20% equity) — call.
        return Action.CHECK_CALL
    if Action.FOLD in obs.legal_actions:
        return Action.FOLD
    return obs.legal_actions[0]
