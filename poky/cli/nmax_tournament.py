"""
Tournament N-max avec composition mixte de tables.
Permet de tester : 3 instances adaptive + 3 archétypes hétérogènes, etc.

  python -m poky.cli.nmax_tournament --table adaptive,adaptive,adaptive,tag,lag,maniac --hands 1500
  python -m poky.cli.nmax_tournament --table adaptive,tag,lag,maniac,call,random --hands 2000

Le runner gère la rotation des sièges, donc chaque joueur joue à chaque
position de manière équilibrée. Le bilan détaillé indique le gain net
par joueur, avec IC95%.
"""
import argparse
import sys

from poky.arena import run_match
from poky.cli.tournament import PLAYER_FACTORY


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def build_players(spec):
    names = [n.strip() for n in spec.split(",") if n.strip()]
    if len(names) < 3:
        raise SystemExit("Au moins 3 joueurs requis.")
    return [PLAYER_FACTORY[n](i) for i, n in enumerate(names)], names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True,
                        help="liste de bots, ex 'adaptive,adaptive,tag,lag,maniac,call'")
    parser.add_argument("--hands", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--chips", type=int, default=100)
    args = parser.parse_args()

    players, names = build_players(args.table)
    print(f"Table {len(players)}-max : {names}")
    print(f"Mains : {args.hands}  |  seed : {args.seed}  |  stack départ : {args.chips}")
    print()
    res = run_match(players, hands=args.hands, seed=args.seed,
                    chips_per_player=args.chips)
    print(res.summary())

    # Bilan : ranking
    ranking = sorted(enumerate(res.stats),
                     key=lambda kv: -kv[1].bb_per_100)
    print("\n--- Classement final ---")
    for rank, (i, s) in enumerate(ranking, 1):
        print(f"  #{rank}  {s.name:<20} {s.bb_per_100:>+10.2f} bb/100  "
              f"(±{s.ci95_bb100:.1f})")


if __name__ == "__main__":
    main()
