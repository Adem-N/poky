"""SnG (Sit-and-Go) runner for 3-max hyper-turbo tournaments.

Plays a full Nitro-style SnG from start to finish:
  - 3 players start with equal stacks
  - Blinds escalate per a configurable schedule
  - When one player busts -> remaining 2 play heads-up
  - When second player busts -> SnG ends
  - Finish order determines payouts (e.g., 100/0/0 WTA, or 80/12/8 ICM split)

Built on top of rlcard's NLHE env by:
  1. Patching `game.init_chips` before each hand to preserve persistent stacks
  2. Manually setting `game.dealer_id` to rotate the button
  3. Switching to a 2-player env once one player busts
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import rlcard

from poky.engine import (
    Action, Game, Observation, PlayerStatus, Stage,
)
from poky.engine.game import Game as PokyGame   # alias to use _wrap


@dataclass
class BlindLevel:
    sb: int
    bb: int


# Default Nitro Winamax schedule (approx): 15bb starting stack with these
# levels every 4 hands (rough proxy for 60-second levels with ~10s/decision).
# Stack=300, BB starts at 20 -> 15bb. Levels: BB doubles roughly every 4 hands.
DEFAULT_NITRO_SCHEDULE = [
    BlindLevel(10, 20),    # level 0: 15bb starting
    BlindLevel(15, 30),    # level 1: 10bb
    BlindLevel(25, 50),    # level 2: 6bb
    BlindLevel(40, 80),    # level 3: 3.75bb
    BlindLevel(75, 150),   # level 4: 2bb
    BlindLevel(150, 300),  # level 5: 1bb (any chip = all-in)
]
DEFAULT_HANDS_PER_LEVEL = 4


@dataclass
class SnGResult:
    finish_order: List[int]          # [1st_idx, 2nd_idx, 3rd_idx]
    payouts: List[float]             # payout per seat (in payout units)
    hands_played: int
    final_stacks: List[int]


def _wrap_for_player(env, player_id: int, num_players: int) -> Observation:
    """Build an Observation from the rlcard env at the current state.

    Re-implements the wrapping logic to avoid double-init through PokyGame.
    """
    state = env.get_state(player_id)
    raw = state["raw_obs"]
    legal = [Action(int(a)) for a in state["legal_actions"]]
    stage_val = raw["stage"].value if hasattr(raw["stage"], "value") else int(raw["stage"])
    game = env.game
    statuses = []
    for p in game.players:
        name = p.status.name
        if name == "FOLDED":
            statuses.append(PlayerStatus.FOLDED)
        elif name == "ALLIN":
            statuses.append(PlayerStatus.ALLIN)
        else:
            statuses.append(PlayerStatus.ALIVE)
    return Observation(
        player_id=player_id,
        hole_cards=list(raw["hand"]),
        community_cards=list(raw["public_cards"]),
        pot=int(raw["pot"]),
        my_committed=int(raw["my_chips"]),
        my_stack=int(raw["stakes"][player_id]),
        all_committed=[int(c) for c in raw["all_chips"]],
        all_stacks=[int(s) for s in raw["stakes"]],
        stage=Stage(int(stage_val)),
        legal_actions=legal,
        num_players=num_players,
        dealer_id=int(game.dealer_id),
        small_blind=int(game.small_blind),
        big_blind=int(game.big_blind),
        player_statuses=statuses,
        raw_state=state,
    )


def _make_env(num_players: int, stacks: Sequence[int], dealer: int,
              sb: int, bb: int, seed: int):
    """Create a rlcard NLHE env preloaded with given stacks, dealer, blinds."""
    env = rlcard.make("no-limit-holdem", config={
        "game_num_players": num_players,
        "chips_for_each": max(stacks),       # placeholder; overwritten below
        "seed": seed,
    })
    g = env.game
    g.init_chips = list(map(int, stacks))
    g.dealer_id = dealer
    g.small_blind = sb
    g.big_blind = bb
    state, pid = env.reset()
    # Re-apply (env.reset() doesn't always pick up overridden dealer/blinds).
    g.dealer_id = dealer
    g.small_blind = sb
    g.big_blind = bb
    return env


class SnGRunner:
    """Runs a single 3-player SnG to completion.

    Args:
        starting_chips: chips per player at start of SnG (e.g., 300 for 15bb)
        blind_schedule: list of `BlindLevel` (sb, bb)
        hands_per_level: how many hands between blind escalations
        payouts: prize per finish position (e.g., [80, 12, 8] for Nitro 100x jackpot
                 or [100, 0, 0] for winner-take-all)
        max_hands: safety cap on total hands played in one SnG
    """

    def __init__(self,
                 starting_chips: int = 300,
                 blind_schedule: Optional[Sequence[BlindLevel]] = None,
                 hands_per_level: int = DEFAULT_HANDS_PER_LEVEL,
                 payouts: Optional[Sequence[float]] = None,
                 max_hands: int = 200):
        self.starting_chips = starting_chips
        self.schedule = list(blind_schedule or DEFAULT_NITRO_SCHEDULE)
        self.hands_per_level = hands_per_level
        self.payouts = list(payouts or [100.0, 0.0, 0.0])
        self.max_hands = max_hands

    def _blinds_at(self, hand_idx: int) -> BlindLevel:
        level = min(hand_idx // self.hands_per_level, len(self.schedule) - 1)
        return self.schedule[level]

    def play(self, players: Sequence, seed: int = 42) -> SnGResult:
        """Play one SnG with the given list of 3 players. Returns finish order."""
        if len(players) != 3:
            raise ValueError(f"expected 3 players, got {len(players)}")
        stacks = [self.starting_chips] * 3
        dealer = 0
        eliminated: List[int] = []        # in order of elimination (1st bust first)
        hand_idx = 0

        while len(eliminated) < 2 and hand_idx < self.max_hands:
            blinds = self._blinds_at(hand_idx)

            active = [i for i in range(3) if stacks[i] > 0]
            if len(active) < 2:
                break

            if len(active) == 3:
                stacks = self._play_3max_hand(
                    players, stacks, dealer, blinds, seed + hand_idx
                )
            else:
                stacks = self._play_hu_hand(
                    players, stacks, active, dealer, blinds, seed + hand_idx
                )

            # Detect new eliminations
            for i in active:
                if stacks[i] <= 0 and i not in eliminated:
                    eliminated.append(i)

            # Rotate dealer to next non-eliminated player
            for _ in range(3):
                dealer = (dealer + 1) % 3
                if stacks[dealer] > 0:
                    break
            hand_idx += 1

        # Finish order: winner (still has chips) is 1st, then reverse-eliminated.
        survivors = [i for i in range(3) if stacks[i] > 0]
        if not survivors:
            # Shouldn't happen, but degrade gracefully
            survivors = [eliminated[-1]] if eliminated else [0]
        winner = survivors[0]
        # Compose finish: 1st = winner, 2nd = last eliminated, 3rd = first eliminated
        finish = [winner] + eliminated[::-1]
        # Pad to length 3 (in case of weird draw / max_hands cutoff)
        while len(finish) < 3:
            missing = [i for i in range(3) if i not in finish]
            finish.append(missing[0])
        # Compute payouts per seat
        payouts_per_seat = [0.0] * 3
        for pos, seat in enumerate(finish):
            payouts_per_seat[seat] = self.payouts[pos]
        return SnGResult(
            finish_order=finish,
            payouts=payouts_per_seat,
            hands_played=hand_idx,
            final_stacks=list(stacks),
        )

    def _play_one_hand(self, env, players: Sequence,
                       num_at_table: int, seat_map: List[int]) -> List[int]:
        """Drive one hand through the env using the given player list.

        Args:
            env: rlcard env in initial state for this hand
            players: full 3-player list (some may be eliminated)
            num_at_table: 2 or 3
            seat_map: list of player indices participating (length num_at_table).
                      seat_map[i] = global player index at env seat i.

        Returns:
            list of payoffs per seat (length num_at_table), in env's seat order.
        """
        active_players = [players[seat_map[i]] for i in range(num_at_table)]
        for p in active_players:
            p.reset()
        from poky.players.base import ActionEvent

        state, pid = env.get_state(0), 0
        # Reset already happened in _make_env. Find current player.
        pid = env.game.game_pointer
        steps = 0
        while not env.is_over():
            obs = _wrap_for_player(env, pid, num_at_table)
            action = active_players[pid].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            ev = ActionEvent(
                actor=pid, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in active_players:
                p.observe_action(ev)
            state, pid = env.step(int(action))
            steps += 1
            if steps > 200:
                break
        return list(env.get_payoffs())

    def _play_3max_hand(self, players: Sequence, stacks: List[int],
                        dealer: int, blinds: BlindLevel, seed: int) -> List[int]:
        """Play one 3-max hand, returns updated stacks."""
        env = _make_env(3, stacks, dealer, blinds.sb, blinds.bb, seed)
        payoffs = self._play_one_hand(env, players, 3, seat_map=[0, 1, 2])
        return [int(stacks[i] + payoffs[i]) for i in range(3)]

    def _play_hu_hand(self, players: Sequence, stacks: List[int],
                      active: List[int], dealer: int, blinds: BlindLevel,
                      seed: int) -> List[int]:
        """Play one HU hand between the two non-busted players.

        active is a sorted list of 2 player indices. dealer is the GLOBAL
        dealer index; we map to HU env seat 0 (dealer) and seat 1 (non-dealer).
        """
        # If dealer is the eliminated player, pick next active for dealer.
        if dealer not in active:
            dealer = active[0]
        # Build seat_map: seat 0 = global dealer, seat 1 = the other active
        other = [i for i in active if i != dealer][0]
        seat_map = [dealer, other]
        hu_stacks = [stacks[dealer], stacks[other]]
        # HU rlcard: env_dealer is at seat 0
        env = _make_env(2, hu_stacks, dealer=0, sb=blinds.sb, bb=blinds.bb, seed=seed)
        payoffs = self._play_one_hand(env, players, 2, seat_map=seat_map)
        new_stacks = list(stacks)
        new_stacks[dealer] = int(stacks[dealer] + payoffs[0])
        new_stacks[other] = int(stacks[other] + payoffs[1])
        return new_stacks
