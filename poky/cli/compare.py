"""
Compare deux champions sur la même gauntlet d'archétypes.

  python -m poky.cli.compare --a heuristic --b nfsp --hands 2000

Sortie : tableau side-by-side de bb/100 + verdict, et delta de qui gagne quoi.
Utile pour valider si une nouvelle version du bot (ou un NFSP entraîné) est
réellement supérieur à un baseline.
"""
import argparse
import sys

from poky.cli.tournament import (
    PLAYER_FACTORY, DEFAULT_GAUNTLET, run_tournament, verdict,
)


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, choices=list(PLAYER_FACTORY))
    parser.add_argument("--b", required=True, choices=list(PLAYER_FACTORY))
    parser.add_argument("--hands", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"=== Comparaison : {args.a}  vs  {args.b}  ===")
    print(f"({args.hands} mains par matchup, sur la gauntlet de "
          f"{len(DEFAULT_GAUNTLET)} adversaires)\n")

    print(f"--- {args.a} ---")
    res_a = run_tournament(args.a, args.hands, args.seed)
    print(f"\n--- {args.b} ---")
    res_b = run_tournament(args.b, args.hands, args.seed)

    print("\n" + "=" * 90)
    print(f"  {'Matchup':<32} {args.a:>12} {args.b:>12} {'Δ':>10} {'Gagnant':>10}")
    print("-" * 90)
    a_wins = b_wins = ties = 0
    for (label_a, stats_a), (_, stats_b) in zip(res_a, res_b):
        delta = stats_b.bb_per_100 - stats_a.bb_per_100
        if abs(delta) < (stats_a.ci95_bb100 + stats_b.ci95_bb100):
            winner = "TIE"
            ties += 1
        elif stats_a.bb_per_100 > stats_b.bb_per_100:
            winner = args.a
            a_wins += 1
        else:
            winner = args.b
            b_wins += 1
        print(f"  {label_a:<32} {stats_a.bb_per_100:>+12.2f} "
              f"{stats_b.bb_per_100:>+12.2f} {delta:>+10.2f} {winner:>10}")
    print("-" * 90)
    print(f"  Bilan : {args.a} gagne {a_wins}  |  {args.b} gagne {b_wins}  |  "
          f"{ties} matchups indécidables (overlap des IC95)")
    print("=" * 90)


if __name__ == "__main__":
    main()
