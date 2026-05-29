"""Verbose single-SnG playthrough: NitroPlayer vs 2x ProShortStackPlayer.

Prints every decision with full context so we can review the bot's actual
plays manually.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import rlcard
from poky.engine import Action, PlayerStatus, Stage
from poky.players.base import ActionEvent
from poky.players.nitro_player import NitroPlayer
from poky.players.pro_shortstack import ProShortStackPlayer
from poky.nitro.sng_runner import _make_env, _wrap_for_player, BlindLevel, SnGRunner


def play_verbose_sng(seed: int = 42):
    print(f"=== Verbose SnG seed={seed} ===\n")
    nitro = NitroPlayer(seed=seed)
    p0 = ProShortStackPlayer(seed=seed + 100)
    p1 = ProShortStackPlayer(seed=seed + 200)
    players = [nitro, p0, p1]   # seat 0 = NITRO

    stacks = [300, 300, 300]
    dealer = 0
    hand_idx = 0
    eliminated = []

    schedule = [BlindLevel(10, 20), BlindLevel(15, 30),
                BlindLevel(25, 50), BlindLevel(40, 80), BlindLevel(75, 150)]

    while len(eliminated) < 2 and hand_idx < 30:
        level = min(hand_idx // 4, len(schedule) - 1)
        sb = schedule[level].sb
        bb = schedule[level].bb
        active = [i for i in range(3) if stacks[i] > 0]
        if len(active) < 2:
            break

        print(f"\n--- HAND {hand_idx+1} | dealer=seat{dealer} | blinds {sb}/{bb} | stacks {stacks} ---")

        # Reset preflop_status etc
        for p in players:
            p.reset()

        if len(active) == 3:
            env = _make_env(3, stacks, dealer, sb, bb, seed=seed + hand_idx * 7)
            seat_map = [0, 1, 2]
        else:
            # HU
            other = [i for i in active if i != dealer][0] if dealer in active else active[1]
            dlr = dealer if dealer in active else active[0]
            other = [i for i in active if i != dlr][0]
            seat_map = [dlr, other]
            env = _make_env(2, [stacks[dlr], stacks[other]], 0, sb, bb,
                            seed=seed + hand_idx * 7)

        # Print hole cards
        for env_seat in range(len(seat_map)):
            global_seat = seat_map[env_seat]
            who = "NITRO" if global_seat == 0 else f"PRO{global_seat}"
            cards = env.game.players[env_seat].hand
            cards_str = ",".join([f"{c.suit}{c.rank}" for c in cards])
            print(f"   seat{global_seat} ({who}): {cards_str}")

        pid = env.game.game_pointer
        steps = 0
        while not env.is_over() and steps < 50:
            global_seat = seat_map[pid]
            who = "NITRO" if global_seat == 0 else f"PRO{global_seat}"
            obs = _wrap_for_player(env, pid, len(seat_map))
            action = players[global_seat].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            stage = obs.stage.name
            board_str = ",".join([f"{c[0]}{c[1]}" for c in obs.community_cards]) or "—"
            print(f"   [{stage:7s}] {who} (pot={obs.pot:>3} board={board_str:>10} my_stack={obs.my_stack:>3}) -> {action.name}")
            ev = ActionEvent(
                actor=pid, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in players:
                p.observe_action(ev)
            state, pid = env.step(int(action))
            steps += 1

        payoffs = env.get_payoffs()
        for env_seat, global_seat in enumerate(seat_map):
            delta = int(payoffs[env_seat])
            sign = "+" if delta >= 0 else ""
            who = "NITRO" if global_seat == 0 else f"PRO{global_seat}"
            print(f"   Hand result: {who} {sign}{delta} chips (now {stacks[global_seat] + delta})")
            stacks[global_seat] = int(stacks[global_seat] + delta)

        for i in active:
            if stacks[i] <= 0 and i not in eliminated:
                eliminated.append(i)
                print(f"   *** seat{i} eliminated (finished {3 - len(eliminated) + 1})")
        for _ in range(3):
            dealer = (dealer + 1) % 3
            if stacks[dealer] > 0:
                break
        hand_idx += 1

    print(f"\n=== SnG ended after {hand_idx} hands. Final stacks: {stacks} ===")
    survivors = [i for i in range(3) if stacks[i] > 0]
    if survivors:
        winner = survivors[0]
        who = "NITRO" if winner == 0 else f"PRO{winner}"
        print(f"WINNER: {who}")
    return stacks, eliminated


if __name__ == "__main__":
    for seed in [1, 7, 42, 99, 123]:
        play_verbose_sng(seed=seed)
        print("\n" + "=" * 80)
