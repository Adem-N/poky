"""
Texas Hold'em heads-up : Humain vs Bot.
Lancer :  python main.py
"""
from deck import Deck
from evaluator import best_hand, describe
from bot import decide

SMALL_BLIND = 5
BIG_BLIND = 10
START_STACK = 500


def show_cards(cards):
    return " ".join(str(c) for c in cards)


def ask_human(to_call, pot, stack):
    while True:
        if to_call == 0:
            prompt = f"[Pot {pot} | Stack {stack}] (c)heck / (b)et / (f)old ? "
        else:
            prompt = f"[Pot {pot} | À suivre {to_call} | Stack {stack}] (c)all / (r)aise / (f)old ? "
        choice = input(prompt).strip().lower()

        if choice in ("f", "fold"):
            return ("fold", 0)
        if choice in ("c", "check", "call"):
            return ("check" if to_call == 0 else "call", to_call)
        if choice in ("b", "bet", "r", "raise"):
            try:
                amt = int(input(f"  Montant (min {max(BIG_BLIND, to_call * 2)}) : "))
            except ValueError:
                print("  Montant invalide.")
                continue
            if amt <= to_call or amt > stack:
                print("  Montant hors limites.")
                continue
            return ("raise", amt)
        print("  Choix invalide.")


def betting_round(state, board, first_to_act):
    """
    state = {'human_stack', 'bot_stack', 'pot', 'human_bet', 'bot_bet'}
    first_to_act : 'human' ou 'bot'
    Retourne le gagnant si quelqu'un fold, sinon None.
    """
    players = [first_to_act, "bot" if first_to_act == "human" else "human"]
    acted = {"human": False, "bot": False}
    idx = 0

    while True:
        actor = players[idx % 2]
        other = "bot" if actor == "human" else "human"
        to_call = state[f"{other}_bet"] - state[f"{actor}_bet"]
        stack = state[f"{actor}_stack"]

        if to_call == 0 and acted[actor] and acted[other]:
            return None
        if stack == 0:
            idx += 1
            continue

        if actor == "human":
            print(f"\nTon tour. Board : {show_cards(board) if board else '(pré-flop)'}")
            print(f"Tes cartes : {show_cards(state['human_hole'])}")
            action, amount = ask_human(to_call, state["pot"], stack)
        else:
            action, amount = decide(
                state["bot_hole"], board, to_call, state["pot"], stack
            )
            label = {"fold": "se couche", "check": "checke", "call": f"suit ({amount})",
                     "raise": f"relance à {amount}"}[action]
            print(f"\nBot : {label}.")

        if action == "fold":
            return other

        if action in ("check", "call"):
            pay = min(to_call, stack)
            state[f"{actor}_stack"] -= pay
            state[f"{actor}_bet"] += pay
            state["pot"] += pay
            acted[actor] = True
            if acted[other] and state["human_bet"] == state["bot_bet"]:
                return None

        elif action == "raise":
            pay = min(amount - state[f"{actor}_bet"], stack)
            state[f"{actor}_stack"] -= pay
            state[f"{actor}_bet"] += pay
            state["pot"] += pay
            acted[actor] = True
            acted[other] = False  # l'autre doit ré-agir

        idx += 1


def showdown(state, board):
    human_rank = best_hand(state["human_hole"] + board)
    bot_rank = best_hand(state["bot_hole"] + board)
    print("\n--- SHOWDOWN ---")
    print(f"Toi : {show_cards(state['human_hole'])}  →  {describe(human_rank)}")
    print(f"Bot : {show_cards(state['bot_hole'])}  →  {describe(bot_rank)}")
    if human_rank > bot_rank:
        return "human"
    if bot_rank > human_rank:
        return "bot"
    return "split"


def play_hand(human_stack, bot_stack, human_is_dealer):
    deck = Deck()
    human_hole = deck.draw(2)
    bot_hole = deck.draw(2)

    # Blinds : dealer = small blind en heads-up
    if human_is_dealer:
        human_bet, bot_bet = SMALL_BLIND, BIG_BLIND
        first_preflop = "human"
    else:
        human_bet, bot_bet = BIG_BLIND, SMALL_BLIND
        first_preflop = "bot"

    state = {
        "human_stack": human_stack - human_bet,
        "bot_stack": bot_stack - bot_bet,
        "pot": human_bet + bot_bet,
        "human_bet": human_bet,
        "bot_bet": bot_bet,
        "human_hole": human_hole,
        "bot_hole": bot_hole,
    }

    print("\n========== NOUVELLE MAIN ==========")
    print(f"Stacks : Toi {state['human_stack']} | Bot {state['bot_stack']} | Pot {state['pot']}")
    print(f"Tes cartes : {show_cards(human_hole)}")

    board = []
    streets = [("pré-flop", 0), ("flop", 3), ("turn", 1), ("river", 1)]
    first = first_preflop

    for name, n in streets:
        if n > 0:
            board += deck.draw(n)
            print(f"\n--- {name.upper()} --- Board : {show_cards(board)}")
        # reset des mises courantes pour les streets post-flop
        if name != "pré-flop":
            state["human_bet"] = 0
            state["bot_bet"] = 0
            first = "human" if not human_is_dealer else "bot"  # non-dealer parle d'abord post-flop

        winner = betting_round(state, board, first)
        if winner:
            print(f"\n>>> {winner.upper()} remporte le pot de {state['pot']} (l'autre fold).")
            if winner == "human":
                return state["human_stack"] + state["pot"], state["bot_stack"]
            return state["human_stack"], state["bot_stack"] + state["pot"]

    winner = showdown(state, board)
    if winner == "split":
        half = state["pot"] // 2
        print(f">>> Partage du pot : {half} chacun.")
        return state["human_stack"] + half, state["bot_stack"] + half
    if winner == "human":
        print(f">>> Tu remportes {state['pot']} !")
        return state["human_stack"] + state["pot"], state["bot_stack"]
    print(f">>> Le bot remporte {state['pot']}.")
    return state["human_stack"], state["bot_stack"] + state["pot"]


def main():
    human_stack = START_STACK
    bot_stack = START_STACK
    human_is_dealer = True

    print("=== POKY — Texas Hold'em Heads-Up ===")
    print(f"Blinds {SMALL_BLIND}/{BIG_BLIND}, stack de départ {START_STACK}.\n")

    while human_stack > 0 and bot_stack > 0:
        human_stack, bot_stack = play_hand(human_stack, bot_stack, human_is_dealer)
        human_is_dealer = not human_is_dealer
        print(f"\n=> Stacks : Toi {human_stack} | Bot {bot_stack}")
        if human_stack <= 0 or bot_stack <= 0:
            break
        cont = input("\nMain suivante ? (o/n) ").strip().lower()
        if cont not in ("", "o", "oui", "y", "yes"):
            break

    print("\n========== PARTIE TERMINÉE ==========")
    if human_stack <= 0:
        print("Tu as perdu tout ton stack. Le bot gagne.")
    elif bot_stack <= 0:
        print("Tu as ruiné le bot. Bravo !")
    else:
        print(f"Stacks finaux — Toi : {human_stack} | Bot : {bot_stack}")


if __name__ == "__main__":
    main()
