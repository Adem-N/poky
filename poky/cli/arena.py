"""
CLI : fait jouer des bots les uns contre les autres.

  python -m poky.cli.arena --players random,call,random --hands 1000
  python -m poky.cli.arena --players call,call,call --hands 5000 --seed 42
"""
import argparse
import sys

from poky.arena import run_match
from poky.players import RandomPlayer, AlwaysCallPlayer, HeuristicPlayer


# Force UTF-8 sur Windows (sinon le ± du résumé s'affiche cassé en cp1252)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


PLAYER_FACTORY = {
    "random": lambda i: RandomPlayer(seed=1000 + i),
    "call": lambda i: AlwaysCallPlayer(),
    "heuristic": lambda i: HeuristicPlayer(seed=2000 + i),
}


def build_players(spec: str):
    names = [n.strip() for n in spec.split(",") if n.strip()]
    players = []
    for i, name in enumerate(names):
        if name not in PLAYER_FACTORY:
            raise SystemExit(f"Joueur inconnu : {name!r}. Disponibles : {list(PLAYER_FACTORY)}")
        players.append(PLAYER_FACTORY[name](i))
    return players


def main():
    parser = argparse.ArgumentParser(description="Arène bot-vs-bot Poky.")
    parser.add_argument("--players", default="random,call,random",
                        help="liste de bots séparés par virgules (ex: random,call,random)")
    parser.add_argument("--hands", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--chips", type=int, default=100,
                        help="stack de départ par joueur")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    players = build_players(args.players)
    print(f"Match : {[p.name for p in players]} | {args.hands} mains | seed {args.seed}")
    result = run_match(players, hands=args.hands, seed=args.seed,
                       chips_per_player=args.chips, verbose=args.verbose)
    print(result.summary())


if __name__ == "__main__":
    main()
