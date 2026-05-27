"""
CLI sparring : un humain (toi) contre des bots, en NLHE 3-max.

  python -m poky.cli.play                          # toi vs heuristique vs heuristique
  python -m poky.cli.play --opponents heuristic,call
  python -m poky.cli.play --hands 30               # match limité à 30 mains
  python -m poky.cli.play --hands 0                # illimité (Ctrl+C pour sortir)

À la fin de chaque main : résumé des cartes adverses qui sont allées au showdown
+ état des stacks. À la fin du match : ton bilan en chips et en bb/100.
"""
import argparse
import sys

from poky.arena import run_match  # juste pour réutiliser PlayerStats
from poky.arena.runner import PlayerStats, BIG_BLIND
from poky.engine import Game, PlayerStatus, Stage
from poky.players import (
    HumanCLIPlayer, HeuristicPlayer, RandomPlayer, AlwaysCallPlayer,
)
from poky.players.human import _render_cards, _STAGE_FR


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


BOT_FACTORY = {
    "heuristic": lambda i: HeuristicPlayer(seed=2000 + i),
    "random":    lambda i: RandomPlayer(seed=1000 + i),
    "call":      lambda i: AlwaysCallPlayer(),
}


def build_bots(spec: str):
    names = [n.strip() for n in spec.split(",") if n.strip()]
    return [BOT_FACTORY[n](i) for i, n in enumerate(names)]


def play_one_hand(players, seed, chips, human_seat):
    """Joue une main, affiche le détail, renvoie les payoffs."""
    for p in players:
        p.reset()
    game = Game(num_players=len(players), seed=seed, chips_per_player=chips)
    obs, current_seat = game.reset()

    history = []  # liste de (player_id, stage, action)
    last_stage = None

    while not game.is_over():
        if obs.stage != last_stage:
            if obs.stage != Stage.PREFLOP and current_seat != human_seat:
                # Annonce du changement de street pour que l'humain suive même
                # quand il ne joue pas tout de suite
                print(f"\n--- {_STAGE_FR[obs.stage]} : {_render_cards(obs.community_cards)} ---")
            last_stage = obs.stage

        action = players[current_seat].act(obs)
        if action not in obs.legal_actions:
            action = obs.legal_actions[0]
        history.append((current_seat, obs.stage, action))
        if current_seat != human_seat:
            # Annonce ce que le bot vient de faire
            name = players[current_seat].name
            print(f"  P{current_seat} ({name}) → {action.name}")
        obs, current_seat = game.step(action)

    payoffs = game.payoffs()
    print()
    print("───── Fin de main ─────")
    # Affiche les mains restantes à l'abattage.
    # NB rlcard : Card.__str__ renvoie "rank+suit" mais raw_obs["hand"] est
    # au format "suit+rank". On normalise vers le format attendu par _render_cards.
    game_players = game.env.game.players
    for i, p in enumerate(game_players):
        cards = [c.suit + c.rank for c in p.hand]
        status = p.status.name
        if status != "FOLDED":
            print(f"  P{i} {('TOI' if i == human_seat else players[i].name):<10} : "
                  f"{_render_cards(cards)}  ({status})")
    for i, payoff in enumerate(payoffs):
        sign = "+" if payoff >= 0 else ""
        label = "TOI" if i == human_seat else f"P{i} ({players[i].name})"
        print(f"  {label}  {sign}{payoff:.0f}")
    return payoffs


def main():
    parser = argparse.ArgumentParser(description="Sparring CLI : humain vs bots.")
    parser.add_argument("--opponents", default="heuristic,heuristic",
                        help="bots adverses séparés par virgules")
    parser.add_argument("--hands", type=int, default=20,
                        help="nombre de mains (0 = illimité jusqu'à Ctrl+C)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--chips", type=int, default=100)
    args = parser.parse_args()

    bots = build_bots(args.opponents)
    human = HumanCLIPlayer()
    # L'humain s'assoit toujours en siège 0 ; les bots remplissent les autres sièges.
    players = [human] + bots
    if len(players) != 3:
        raise SystemExit(
            f"Attendu 3 joueurs (1 humain + 2 bots), reçu {len(players)}. "
            f"Ajuste --opponents."
        )

    print("=" * 64)
    print(f"  POKY — sparring NLHE 3-max")
    print(f"  Tu joues contre : {[b.name for b in bots]}")
    print(f"  Stacks de départ : {args.chips}  |  Blinds : 1/{2}")
    print("=" * 64)

    my_stats = PlayerStats(name="TOI")
    seed = args.seed if args.seed is not None else 0
    hand_idx = 0
    try:
        while args.hands == 0 or hand_idx < args.hands:
            print(f"\n\n#### MAIN {hand_idx + 1} ####")
            payoffs = play_one_hand(players, seed + hand_idx,
                                    args.chips, human_seat=0)
            my_stats.chips += payoffs[0]
            my_stats.chips_sq += payoffs[0] * payoffs[0]
            my_stats.hands += 1
            hand_idx += 1
            print(f"\n  Bilan : {my_stats.chips:+.0f} chips  "
                  f"({my_stats.bb_per_100:+.1f} bb/100)")
    except (KeyboardInterrupt, EOFError):
        print("\n\nInterrompu.")

    print("\n" + "=" * 64)
    print(f"  Mains jouées  : {my_stats.hands}")
    print(f"  Gain net      : {my_stats.chips:+.0f} chips")
    print(f"  Winrate       : {my_stats.bb_per_100:+.2f} bb/100  "
          f"(±{my_stats.ci95_bb100:.2f})")
    print("=" * 64)


if __name__ == "__main__":
    main()
