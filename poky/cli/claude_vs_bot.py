"""
Mode où Claude (moi) joue main par main contre le bot.
Le script accepte une liste d'actions préfixée et joue jusqu'à ce qu'il
ait besoin d'une action en plus. Affiche TOUTES les observations vues
par Claude (positions, hole cards, board, pot, action history).

Usage :
  python -m poky.cli.claude_vs_bot --hand 0                       # voir 1ère obs
  python -m poky.cli.claude_vs_bot --hand 0 --actions f           # 1 action puis stop
  python -m poky.cli.claude_vs_bot --hand 0 --actions c,h,c       # 3 actions

Codes d'action : f=FOLD, c=CHECK/CALL, h=RAISE_HALF_POT,
                 p=RAISE_POT, a=ALL_IN.
"""
import argparse
import sys

from poky.engine import Action, Game, Position, Stage
from poky.players import HeuristicPlayer

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

_CODE = {"f": Action.FOLD, "c": Action.CHECK_CALL,
         "h": Action.RAISE_HALF_POT, "p": Action.RAISE_POT, "a": Action.ALL_IN}
_STAGE_FR = {Stage.PREFLOP: "Pré-flop", Stage.FLOP: "Flop",
             Stage.TURN: "Turn", Stage.RIVER: "River", Stage.END: "End"}
_POSITION_FR = {Position.BTN: "BTN", Position.SB: "SB", Position.BB: "BB"}


def _render_cards(cards):
    if not cards: return "—"
    suits = {"H": "♥", "D": "♦", "S": "♠", "C": "♣"}
    return " ".join(c[1] + suits[c[0]] for c in cards)


def render_obs(obs, claude_seat):
    print(f"\n=== {_STAGE_FR[obs.stage]}  Pot={obs.pot}  Tour de joueur={obs.player_id} "
          f"{'(CLAUDE)' if obs.player_id == claude_seat else '(BOT)'} ===")
    print(f"  Position Claude : {_POSITION_FR[obs.my_position] if obs.player_id == claude_seat else '-'}")
    print(f"  Dealer (BTN) au siège : {obs.dealer_id}")
    print(f"  Hole cards Claude : {_render_cards(obs.hole_cards) if obs.player_id == claude_seat else 'masquées (bot tour)'}")
    print(f"  Board : {_render_cards(obs.community_cards)}")
    print(f"  Mises en cours par siège : {obs.all_committed}")
    print(f"  Stacks restants par siège : {obs.all_stacks}")
    print(f"  Statuts : {[s.name for s in obs.player_statuses]}")
    if obs.to_call > 0:
        print(f"  À suivre : {obs.to_call} chips  |  pot odds = "
              f"{obs.to_call/(obs.pot+obs.to_call):.3f}")
    print(f"  Actions légales : {[a.name for a in obs.legal_actions]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hand", type=int, default=0,
                        help="indice de main (= seed offset, donc reproductible)")
    parser.add_argument("--actions", default="",
                        help="actions Claude pré-décidées : f,c,h,p,a séparées par virgules")
    parser.add_argument("--claude-seat", type=int, default=0)
    parser.add_argument("--seed-base", type=int, default=42)
    args = parser.parse_args()

    actions_queue = [_CODE[a.strip()] for a in args.actions.split(",") if a.strip()]
    bot = HeuristicPlayer(seed=2000)
    bot2 = HeuristicPlayer(seed=2001)
    bots_by_seat = {0: bot, 1: bot, 2: bot2}  # remplacés selon claude_seat
    # On veut : claude au siège claude_seat, bots aux autres sièges
    bots_by_seat = {}
    for s in range(3):
        if s != args.claude_seat:
            bots_by_seat[s] = HeuristicPlayer(seed=2000 + s)
            bots_by_seat[s].reset()

    game = Game(num_players=3, seed=args.seed_base + args.hand, chips_per_player=100)
    obs, current = game.reset()

    claude_actions_used = 0

    while not game.is_over():
        if current == args.claude_seat:
            render_obs(obs, args.claude_seat)
            if claude_actions_used < len(actions_queue):
                chosen = actions_queue[claude_actions_used]
                if chosen not in obs.legal_actions:
                    print(f"\n!!! Action {chosen.name} ILLÉGALE — refait ton choix.")
                    return
                print(f"\n→ CLAUDE joue : {chosen.name}")
                claude_actions_used += 1
                obs, current = game.step(chosen)
            else:
                print("\n>>> ACTION CLAUDE ATTENDUE — relance avec --actions [actions précédentes],<ton choix>")
                print(f">>> Actions Claude déjà jouées : {[a.name for a in actions_queue[:claude_actions_used]]}")
                return
        else:
            # Tour du bot
            action = bots_by_seat[current].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            print(f"  Bot siège {current} ({bots_by_seat[current].name}) → {action.name}")
            obs, current = game.step(action)

    # Fin de main
    print("\n────── FIN DE MAIN ──────")
    payoffs = game.payoffs()
    rl_players = game.env.game.players
    for s in range(3):
        cards = [c.suit + c.rank for c in rl_players[s].hand]
        status = rl_players[s].status.name
        label = "CLAUDE" if s == args.claude_seat else f"BOT_{s}"
        if status != "FOLDED":
            print(f"  {label} (siège {s}) : {_render_cards(cards)}  ({status})  payoff={payoffs[s]:+.0f}")
        else:
            print(f"  {label} (siège {s}) : (foldé)  payoff={payoffs[s]:+.0f}")


if __name__ == "__main__":
    main()
