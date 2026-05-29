"""Independent Chip Model (ICM) for 3-player SnG payouts.

ICM converts chip stacks into tournament equity assuming the probability
of finishing in position k is proportional to one's chip share among
remaining players (Malmuth-Harville model).

For 3-player Spin & Go with split payout (e.g. 80/12/8 of prize pool):
  - Player A's equity = sum over finish positions of (P[finish k] * payout_k)

Used for ICM-adjusted shoves: when ICM matters (jackpot multiplier >= 100x
in Winamax Nitro), shoving wide loses tournament EV even if chip EV is
positive — because doubling up has diminishing returns vs busting.

PLACEHOLDER — implementation in task N2.
"""
from __future__ import annotations

from typing import List, Tuple


def malmuth_harville_equity(stacks: List[float], payouts: List[float]) -> List[float]:
    """Compute each player's tournament equity (in payout units).

    Args:
        stacks: chip stacks per player (length N)
        payouts: payout per finish position (length N; index 0 = 1st place)

    Returns:
        List of N floats, each the equity of player i.
    """
    raise NotImplementedError("N2 — implement Malmuth-Harville recursion")


def equity_delta_for_shove(
    current_stacks: List[float],
    hero_idx: int,
    shove_size: float,
    fold_eq: float,
    showdown_eq: float,
    payouts: List[float],
) -> float:
    """ICM equity delta from a single shove decision.

    Returns:
        Expected change in ICM equity from shoving vs folding.
        Positive -> shove is +EV in ICM. Negative -> fold is better.
    """
    raise NotImplementedError("N2 — implement ICM shove delta")
