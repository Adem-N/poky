"""
Sanity checks pour valider que les benchs ExpertOnly ne sont pas biaisés.

Checks :
  (1) Zero-sum : sum(payoffs)==0 sur chaque main
  (2) Heuristic vs Heuristic : EV moyenne env 0 bb/100 (sinon biais de bench)
  (3) Position distribution : compteurs (offset_from_btn) pour le siège
      qui cycle, vérifier ~uniforme
  (4) Stack effectif : chips_per_player=200 chips, BB=2 → 50bb pas 100bb
"""
import argparse
import math
from collections import Counter

from poky.engine import Game
from poky.players.heuristic import HeuristicPlayer


BIG_BLIND = 2


def check_zero_sum(num_players: int, seed: int, n_hands: int = 200):
    """Vérifie que sum(payoffs) == 0 pour chaque main."""
    violations = 0
    max_dev = 0.0
    for h in range(n_hands):
        g = Game(num_players=num_players, seed=seed + h, chips_per_player=200)
        obs, p = g.reset()
        players = [HeuristicPlayer(seed=42 + i) for i in range(num_players)]
        for pl in players:
            pl.reset()
        while not g.is_over():
            a = players[p].act(obs)
            if a not in obs.legal_actions:
                a = obs.legal_actions[0]
            obs, p = g.step(a)
        payoffs = g.payoffs()
        s = sum(payoffs)
        max_dev = max(max_dev, abs(s))
        if abs(s) > 0.01:
            violations += 1
    return violations, max_dev


def check_heuristic_vs_heuristic(num_players: int, hands: int, seeds: list):
    """Joue Heuristic vs (N-1) Heuristic en cyclant un siège pour mesurer
    s'il y a un EV intrinsèque positionnel."""
    all_payoffs = []
    pos_counter = Counter()
    for seed in seeds:
        target = HeuristicPlayer(seed=42)
        opps = [HeuristicPlayer(seed=43 + i) for i in range(num_players - 1)]
        for hand_idx in range(hands):
            target_seat = hand_idx % num_players
            seats = list(opps)
            seats.insert(target_seat, target)
            for pl in seats:
                pl.reset()
            g = Game(num_players=num_players, seed=seed + hand_idx,
                     chips_per_player=200)
            obs, p = g.reset()
            # Record target's offset_from_btn for this hand
            offset = (target_seat - obs.dealer_id) % num_players
            pos_counter[offset] += 1
            while not g.is_over():
                a = seats[p].act(obs)
                if a not in obs.legal_actions:
                    a = obs.legal_actions[0]
                obs, p = g.step(a)
            pay = g.payoffs()
            all_payoffs.append(pay[target_seat])
    return all_payoffs, pos_counter


def summarize_payoffs(label, payoffs):
    n = len(payoffs)
    mean = sum(payoffs) / n
    var = sum((p - mean) ** 2 for p in payoffs) / max(n - 1, 1)
    std = math.sqrt(var)
    se = std / math.sqrt(n)
    mean_bb100 = mean / BIG_BLIND * 100
    ic95 = 1.96 * se / BIG_BLIND * 100
    print(f"{label}: mean={mean_bb100:+.2f} bb/100 (+/-{ic95:.2f} IC95, n={n})")
    return mean_bb100, ic95


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=6, choices=[2, 3, 6])
    ap.add_argument("--hands", type=int, default=3000)
    ap.add_argument("--seeds", type=str, default="7,13,42")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    n = args.players

    print(f"=== SANITY CHECKS — {n} joueurs ===\n")

    # (1) Zero-sum
    print("(1) Zero-sum (200 mains random heuristic) ...")
    viol, max_dev = check_zero_sum(n, seed=42, n_hands=200)
    status = "OK" if viol == 0 else f"FAIL ({viol} violations)"
    print(f"    sum(payoffs)==0 : {status}, max |dev|={max_dev:.4f}\n")

    # (2) Heuristic-vs-Heuristic
    print(f"(2) Heuristic vs {n-1}x Heuristic "
          f"({args.hands}x{len(seeds)}={args.hands*len(seeds)} mains) ...")
    payoffs, pos_counter = check_heuristic_vs_heuristic(n, args.hands, seeds)
    mean_bb100, ic95 = summarize_payoffs("    target (cycling seat)", payoffs)
    if abs(mean_bb100) - ic95 > 0:
        print(f"    !!! ATTENTION : biais positionnel détecté "
              f"(|{mean_bb100:+.2f}| > IC95 {ic95:.2f}) — pas null hypothesis")
    else:
        print(f"    OK Pas de biais détecté (|mean| < IC95)")

    # (3) Distribution positionnelle
    print(f"\n(3) Distribution position de l'expert "
          f"(uniforme attendu env {sum(pos_counter.values())//n} par position) :")
    for off in range(n):
        count = pos_counter[off]
        pct = count / sum(pos_counter.values()) * 100
        print(f"    offset_from_btn={off}: n={count:6d} ({pct:.1f}%)")

    # (4) Stack effectif
    print(f"\n(4) Stack effectif : chips_per_player=200, BB={BIG_BLIND} "
          f"-> stack = {200 // BIG_BLIND} bb")


if __name__ == "__main__":
    main()
