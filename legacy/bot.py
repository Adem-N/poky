import random
from deck import Deck
from evaluator import best_hand


def hand_strength(hole, board, simulations=300):
    """Estime la probabilité de gagner via Monte Carlo (heads-up)."""
    wins = 0
    ties = 0
    known = list(hole) + list(board)
    needed_board = 5 - len(board)

    for _ in range(simulations):
        deck = Deck(exclude=known)
        opp_hole = deck.draw(2)
        extra_board = deck.draw(needed_board)
        full_board = list(board) + extra_board

        my_rank = best_hand(list(hole) + full_board)
        opp_rank = best_hand(opp_hole + full_board)

        if my_rank > opp_rank:
            wins += 1
        elif my_rank == opp_rank:
            ties += 1

    return (wins + ties / 2) / simulations


def decide(hole, board, to_call, pot, my_stack, simulations=300):
    """
    Décide : 'fold', 'call' (ou check si to_call=0), 'raise'.
    Retourne (action, montant_raise_si_applicable).
    """
    strength = hand_strength(hole, board, simulations=simulations)
    pot_odds = to_call / (pot + to_call) if to_call > 0 else 0

    # Bluff occasionnel
    bluff = random.random() < 0.08

    if to_call == 0:
        if strength > 0.65 or bluff:
            raise_amt = min(my_stack, max(10, int(pot * (0.5 if strength < 0.8 else 1.0))))
            return ("raise", raise_amt)
        return ("check", 0)

    # Il y a une mise à suivre
    if strength < pot_odds - 0.05 and not bluff:
        return ("fold", 0)

    if strength > 0.75:
        raise_amt = min(my_stack, max(to_call * 2, int(pot * 0.75)))
        return ("raise", raise_amt)

    if strength > pot_odds:
        return ("call", to_call)

    if bluff:
        raise_amt = min(my_stack, max(to_call * 2, int(pot * 0.5)))
        return ("raise", raise_amt)

    return ("fold", 0)
