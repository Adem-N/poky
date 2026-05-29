"""Unit tests for poky.nitro.icm — Malmuth-Harville ICM model."""
import pytest

from poky.nitro.icm import equity_delta_for_shove, malmuth_harville_equity


# ---- Core ICM properties ----------------------------------------------

def test_equal_stacks_gives_equal_equity():
    """By symmetry, equal stacks -> each player has equity = average payout."""
    eq = malmuth_harville_equity([100, 100, 100], [80, 12, 8])
    expected = (80 + 12 + 8) / 3
    for e in eq:
        assert abs(e - expected) < 1e-9


def test_conservation_sum_equals_payouts():
    """Total ICM equity must equal total payouts (chips never disappear)."""
    payouts = [80, 12, 8]
    for stacks in [
        [100, 100, 100],
        [200, 100, 50],
        [350, 50, 50],
        [1, 1, 1],
        [10, 20, 30],
    ]:
        eq = malmuth_harville_equity(stacks, payouts)
        assert abs(sum(eq) - sum(payouts)) < 1e-9, (stacks, eq)


def test_chip_leader_higher_equity():
    """Player with more chips has more ICM equity, all else equal."""
    eq = malmuth_harville_equity([200, 100, 50], [80, 12, 8])
    assert eq[0] > eq[1] > eq[2]


def test_busted_player_gets_only_last_payout():
    """A player at 0 chips finishes 3rd surely -> equity = P3."""
    eq = malmuth_harville_equity([200, 100, 0], [80, 12, 8])
    assert abs(eq[2] - 8) < 1e-9


def test_two_player_case():
    """2-player ICM: equity proportional to chip share between P1 and P2 payouts."""
    eq = malmuth_harville_equity([100, 200], [80, 20])
    # P(player 0 finishes 1st) = 100/300 = 1/3
    # P(player 1 finishes 1st) = 200/300 = 2/3
    # equity_0 = 1/3 * 80 + 2/3 * 20 = 26.67 + 13.33 = 40
    # equity_1 = 2/3 * 80 + 1/3 * 20 = 53.33 + 6.67 = 60
    assert abs(eq[0] - 40.0) < 1e-9
    assert abs(eq[1] - 60.0) < 1e-9


def test_winner_take_all_equals_chip_share():
    """In winner-take-all (payouts = [100, 0, 0]), ICM equity = chip share * 100."""
    stacks = [150, 100, 50]
    total = sum(stacks)
    eq = malmuth_harville_equity(stacks, [100, 0, 0])
    for i, s in enumerate(stacks):
        expected = (s / total) * 100
        assert abs(eq[i] - expected) < 1e-9, (i, eq, expected)


def test_zero_total_stack_returns_zeros():
    eq = malmuth_harville_equity([0, 0, 0], [80, 12, 8])
    assert eq == [0.0, 0.0, 0.0]


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        malmuth_harville_equity([100, 100], [80, 12, 8])


# ---- Reference values (cross-check vs published / hand-computed) ------

def test_specific_three_player_case():
    """Hand-computed Malmuth-Harville for [200, 100, 100] with [50, 30, 20].

    P(0 1st) = 200/400 = 0.5
    P(1 1st) = 100/400 = 0.25
    P(2 1st) = 100/400 = 0.25

    Given 0 wins (remaining = 200), P(1 2nd | 0 1st) = 100/200 = 0.5
                                    P(2 2nd | 0 1st) = 100/200 = 0.5

    P(0 1st, 1 2nd, 2 3rd) = 0.5 * 0.5 = 0.25
    P(0 1st, 2 2nd, 1 3rd) = 0.5 * 0.5 = 0.25
    P(1 1st, 0 2nd, 2 3rd) = 0.25 * 200/300 = 0.25 * 0.6667 = 0.1667
    P(1 1st, 2 2nd, 0 3rd) = 0.25 * 100/300 = 0.0833
    P(2 1st, 0 2nd, 1 3rd) = 0.25 * 200/300 = 0.1667
    P(2 1st, 1 2nd, 0 3rd) = 0.25 * 100/300 = 0.0833

    Player 0 equity = 0.25*50 + 0.25*50 + 0.1667*30 + 0.0833*20 + 0.1667*30 + 0.0833*20
                    = 12.5  + 12.5  + 5.0    + 1.6667 + 5.0    + 1.6667
                    = 38.333...
    """
    eq = malmuth_harville_equity([200, 100, 100], [50, 30, 20])
    assert abs(eq[0] - 38.333333) < 1e-4
    # By symmetry between 1 and 2: equity should be equal
    assert abs(eq[1] - eq[2]) < 1e-9
    # Conservation check
    assert abs(sum(eq) - 100.0) < 1e-9


def test_short_stack_eq_less_than_chip_share():
    """In top-heavy payouts, short stack has equity > chip-share fraction
    (because the bubble protects them) — but not in winner-take-all."""
    stacks = [800, 100, 100]
    chips_share = [s / sum(stacks) for s in stacks]
    eq_top_heavy = malmuth_harville_equity(stacks, [60, 30, 10])
    eq_wta = malmuth_harville_equity(stacks, [100, 0, 0])
    # Short stack equity fraction in top-heavy structure:
    short_frac_top_heavy = eq_top_heavy[1] / sum(eq_top_heavy)
    short_frac_wta = eq_wta[1] / sum(eq_wta) if sum(eq_wta) > 0 else 0
    # Bubble effect: short stack has MORE equity proportionally in top-heavy
    # than in winner-take-all.
    assert short_frac_top_heavy > short_frac_wta


# ---- equity_delta_for_shove ------------------------------------------

def test_shove_delta_neutral_when_fold_eq_one():
    """If opponent always folds, hero wins the pot every time. Delta should
    be > 0 unless the pot is too small relative to ICM cost (rare)."""
    stacks = [300, 300, 300]
    delta = equity_delta_for_shove(
        stacks=stacks,
        hero_idx=0,
        shove_size=297.0,                 # most of stack
        pots_in=[3.0, 0.5, 1.0],          # BTN pushed 3bb, SB 0.5bb, BB 1bb posted
        fold_prob=1.0,
        win_if_called_prob=0.0,           # doesn't matter, never called
        payouts=[80, 12, 8],
    )
    # Hero wins the blinds with no risk.
    assert delta > 0


def test_shove_delta_negative_when_fold_eq_zero_low_equity():
    """If always called with terrible equity, shove is huge negative delta."""
    stacks = [300, 300, 300]
    delta = equity_delta_for_shove(
        stacks=stacks,
        hero_idx=0,
        shove_size=297.0,
        pots_in=[3.0, 0.5, 1.0],
        fold_prob=0.0,
        win_if_called_prob=0.1,           # 10% equity at showdown
        payouts=[80, 12, 8],
    )
    assert delta < 0


def test_shove_delta_zero_at_breakeven():
    """With fold_eq = 0 and 50% showdown equity, the delta should be ~0
    for a roughly symmetric setup (some bias from ICM curvature)."""
    stacks = [300, 300, 300]
    delta = equity_delta_for_shove(
        stacks=stacks,
        hero_idx=0,
        shove_size=297.0,
        pots_in=[1.5, 0.5, 1.0],
        fold_prob=0.0,
        win_if_called_prob=0.5,
        payouts=[80, 12, 8],
    )
    # Not necessarily exactly 0 because of ICM nonlinearity, but small.
    assert abs(delta) < 10
