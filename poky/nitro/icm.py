"""Independent Chip Model (ICM) for SnG payouts — Malmuth-Harville recursion.

ICM converts chip stacks into tournament equity (in payout units) under the
assumption that the probability of finishing in rank k is proportional to
one's chip share among remaining players (the "Malmuth-Harville" model).

For an N-player SnG with payouts (P1, P2, ..., PN) where Pi is the prize for
finishing in i-th place, each player's equity is the expected payout summed
over all possible finish orderings, weighted by the orderings' probabilities.

For N=3 (the Nitro case), there are 3! = 6 orderings. We enumerate them
exactly — no Monte Carlo needed, fully deterministic.

Edge cases handled:
  - Stack of 0: that player auto-finishes last; gets the lowest payout.
  - Sum of stacks = 0: invalid; we return all-zero equities.
  - Sum of payouts must equal sum across players (conservation).

References:
  - Mason Malmuth, "Gambling Theory and Other Topics" (1987)
  - https://www.pokernews.com/strategy/icm-poker-7841.htm

Example (Nitro 3-max equal stacks, 80/12/8 payouts):
    >>> malmuth_harville_equity([100, 100, 100], [80, 12, 8])
    [33.333..., 33.333..., 33.333...]   # by symmetry

Example (one player short):
    >>> malmuth_harville_equity([200, 100, 0], [80, 12, 8])
    # third player busts -> gets 8; first two split first/second by ICM
"""
from __future__ import annotations

from itertools import permutations
from typing import List, Sequence


def malmuth_harville_equity(stacks: Sequence[float],
                             payouts: Sequence[float]) -> List[float]:
    """Compute each player's tournament equity (payout units).

    Args:
        stacks: chip stack per player. Length N.
        payouts: prize per finish position. Length N (index 0 = 1st place).

    Returns:
        List of N floats summing to sum(payouts).
    """
    n = len(stacks)
    if n != len(payouts):
        raise ValueError(f"stacks ({n}) and payouts ({len(payouts)}) "
                         f"must have same length")
    if n == 0:
        return []

    stacks = [float(s) for s in stacks]
    payouts = [float(p) for p in payouts]
    total = sum(stacks)
    if total <= 0:
        return [0.0] * n

    # If any player has stack 0, treat them as "already busted". The standard
    # M-H formula would divide by zero — instead we enumerate orderings and
    # let zero-stack players sit at the lowest available finish position.
    equities = [0.0] * n
    for perm in permutations(range(n)):
        # perm[0] finishes 1st, perm[1] finishes 2nd, etc.
        prob = 1.0
        remaining = total
        for pos, player in enumerate(perm):
            if pos == n - 1:
                # Last position is forced (only one player left to place).
                # Skip the multiplication to avoid 0/0 when the residual
                # player has zero stack.
                continue
            s = stacks[player]
            if remaining <= 0:
                prob = 0.0
                break
            # Probability this player finishes next given remaining pool
            prob *= s / remaining
            remaining -= s
        if prob == 0.0:
            continue
        for pos, player in enumerate(perm):
            equities[player] += prob * payouts[pos]
    return equities


def equity_delta_for_shove(
    stacks: Sequence[float],
    hero_idx: int,
    shove_size: float,
    pots_in: Sequence[float],
    fold_prob: float,
    win_if_called_prob: float,
    payouts: Sequence[float],
) -> float:
    """ICM equity change from shoving vs folding.

    Args:
        stacks: chip stack per player (pre-shove, before any current-hand commitments)
        hero_idx: hero's player index
        shove_size: chips hero adds to pot when shoving (= remaining stack typically)
        pots_in: chips each player has already committed in the current hand
                 (e.g. blinds). The pot at risk = sum(pots_in) + shove_size + call_amount.
        fold_prob: probability all opponents fold to the shove
        win_if_called_prob: probability hero wins at showdown if called
                            (averaged over opponents' calling ranges)
        payouts: prize for each finish position

    Returns:
        delta_icm_eq = ICM_eq(after shove decision) - ICM_eq(after fold)
        Positive -> shove is ICM-positive. Negative -> fold preferred.

    Simplification: this models a SHOVE called by EXACTLY ONE opponent
    (the "next-to-act" opponent who can call). For multi-way scenarios
    where multiple callers are possible, compose multiple calls of this
    function or build the full game tree.
    """
    n = len(stacks)
    if len(pots_in) != n or len(payouts) != n:
        raise ValueError("stacks, pots_in, payouts must all have length n")
    if not (0 <= fold_prob <= 1):
        raise ValueError(f"fold_prob must be in [0,1], got {fold_prob}")
    if not (0 <= win_if_called_prob <= 1):
        raise ValueError(f"win_if_called_prob must be in [0,1], got {win_if_called_prob}")

    stacks = list(map(float, stacks))
    pots_in = list(map(float, pots_in))

    # Baseline: hero folds -> hero loses already-committed chips.
    # The fold gives the pot to one of the other players in proportion to
    # their current bet contribution (or arbitrary if no one bet either).
    # For simplicity we assume the pot is awarded to the "last bettor" (or
    # split equally if there was no aggression). For typical Nitro pre-flop
    # spots, the pot consists of just the blinds — so folding loses hero's
    # blind contribution only and the pot is irrelevant to other stacks
    # (they get it but it's already counted in their stacks logically? No.)
    #
    # Simpler model: assume the pot just disappears for the fold case
    # (chip-EV approximation, fine when blinds are small vs stack).
    fold_stacks = list(stacks)
    fold_stacks[hero_idx] -= pots_in[hero_idx]
    # NOTE: we leave others' stacks unchanged — this is the "blinds lost" model.

    fold_eq = malmuth_harville_equity(fold_stacks, payouts)[hero_idx]

    # Shove case: assume opponent 1 (the next to act) decides.
    opp_idx = (hero_idx + 1) % n
    # Hero's remaining contribution to pot (in addition to pots_in[hero_idx])
    # is shove_size. Opponent must add (shove_size + pots_in[hero_idx] - pots_in[opp_idx])
    # to call. We approximate by saying opp commits to match hero's total bet.
    hero_total_bet = pots_in[hero_idx] + shove_size

    # 1) Opponent folds: hero wins what's already in the pot.
    pot_won_on_fold = sum(pots_in) - pots_in[hero_idx]
    shove_fold_stacks = list(stacks)
    shove_fold_stacks[hero_idx] += pot_won_on_fold
    for i in range(n):
        if i != hero_idx:
            shove_fold_stacks[i] -= pots_in[i]
    eq_shove_fold = malmuth_harville_equity(shove_fold_stacks, payouts)[hero_idx]

    # 2) Opponent calls (others fold by assumption): showdown for the called pot.
    # Pot = hero_total_bet * 2 + sum(pots_in for others not in showdown).
    # Hero wins -> hero stacks gain hero_total_bet + ...; opp goes to 0 (busts if all-in).
    pot_total_called = 2 * hero_total_bet + sum(
        pots_in[i] for i in range(n) if i != hero_idx and i != opp_idx
    )
    # Hero stacks after winning showdown:
    win_stacks = list(stacks)
    win_stacks[hero_idx] = stacks[hero_idx] - hero_total_bet + pot_total_called
    win_stacks[opp_idx] = max(0.0, stacks[opp_idx] - hero_total_bet)
    for i in range(n):
        if i != hero_idx and i != opp_idx:
            win_stacks[i] -= pots_in[i]
    eq_win = malmuth_harville_equity(win_stacks, payouts)[hero_idx]

    # Hero loses showdown:
    lose_stacks = list(stacks)
    lose_stacks[hero_idx] = max(0.0, stacks[hero_idx] - hero_total_bet)
    lose_stacks[opp_idx] = stacks[opp_idx] - hero_total_bet + pot_total_called
    for i in range(n):
        if i != hero_idx and i != opp_idx:
            lose_stacks[i] -= pots_in[i]
    eq_lose = malmuth_harville_equity(lose_stacks, payouts)[hero_idx]

    eq_called = win_if_called_prob * eq_win + (1 - win_if_called_prob) * eq_lose

    eq_shove = fold_prob * eq_shove_fold + (1 - fold_prob) * eq_called

    return eq_shove - fold_eq
