"""
Évaluation de mains et estimation d'équité par Monte Carlo.

Pourquoi phevaluator : implémentation C de l'algorithme Cactus Kev avec tables
de hash parfait. Évalue une main 5 ou 7 cartes en ~100 nanosecondes. À ce prix-là
on peut faire 10 000 rollouts Monte Carlo par décision sans ralentir le bot.

Convention `phevaluator` : carte = "Rh" avec R ∈ {2..9, T, J, Q, K, A} et h ∈ {h, d, c, s}.
Score : entier de 1 (royale) à 7462 (carte haute la plus faible). Plus petit = meilleur.

Convention rlcard : carte = "SR" où S ∈ {S, H, D, C} (1ère pos !) et R ∈ {2-9, T, J, Q, K, A}.
On convertit avec `rlcard_to_phev`.
"""
import random
from typing import List, Optional

from phevaluator import evaluate_cards


# ---- Conversion de format de cartes ---------------------------------------

_RLCARD_SUITS = set("SHDC")
_RLCARD_RANKS = set("23456789TJQKA")


def rlcard_to_phev(card: str) -> str:
    """rlcard 'HQ' -> phevaluator 'Qh'."""
    if len(card) != 2 or card[0] not in _RLCARD_SUITS or card[1] not in _RLCARD_RANKS:
        raise ValueError(f"Carte rlcard invalide : {card!r}")
    return card[1] + card[0].lower()


# Toutes les cartes au format phevaluator (52 cartes)
ALL_CARDS_PHEV = [r + s for r in "23456789TJQKA" for s in "hdcs"]


# ---- Évaluation 7 cartes --------------------------------------------------

def evaluate7(hole_phev: List[str], board_phev: List[str]) -> int:
    """Score phevaluator pour la meilleure main 5 parmi 7 (ou moins). Plus petit = meilleur."""
    cards = list(hole_phev) + list(board_phev)
    return evaluate_cards(*cards)


# ---- Monte Carlo equity ---------------------------------------------------

def monte_carlo_equity(
    hole_rlcard: List[str],
    board_rlcard: List[str],
    num_opponents: int,
    simulations: int = 1000,
    rng: Optional[random.Random] = None,
) -> float:
    """
    Probabilité de gagner (+ moitié des splits) sachant nos hole cards et le board.

    Tire `simulations` rollouts où l'on :
      1) donne aléatoirement 2 cartes à chacun des `num_opponents` adversaires,
      2) complète le board à 5 cartes,
      3) compare notre main à toutes celles des adversaires.

    Renvoie un float dans [0, 1].
    """
    if rng is None:
        rng = random
    hole = [rlcard_to_phev(c) for c in hole_rlcard]
    board = [rlcard_to_phev(c) for c in board_rlcard]
    known = set(hole) | set(board)
    deck = [c for c in ALL_CARDS_PHEV if c not in known]

    cards_to_draw = num_opponents * 2 + (5 - len(board))
    if cards_to_draw > len(deck):
        raise ValueError("Pas assez de cartes restantes pour la simulation")

    wins = 0.0
    for _ in range(simulations):
        sample = rng.sample(deck, cards_to_draw)
        # 1) cartes adversaires
        idx = 0
        opp_holes = []
        for _ in range(num_opponents):
            opp_holes.append(sample[idx:idx + 2])
            idx += 2
        # 2) board complet
        full_board = board + sample[idx:]
        # 3) évaluation
        my_score = evaluate7(hole, full_board)
        beats = 0
        ties = 0
        for opp in opp_holes:
            opp_score = evaluate7(opp, full_board)
            if my_score < opp_score:  # plus petit = meilleur
                beats += 1
            elif my_score == opp_score:
                ties += 1
        if beats == num_opponents:
            wins += 1.0
        elif beats + ties == num_opponents:
            # split entre nous et les `ties` adversaires qui égalent
            wins += 1.0 / (1 + ties)

    return wins / simulations


# ---- Description qualitative (pour debug / affichage) ---------------------

_BUCKETS = [
    (10,    "Quinte flush royale ou similaire"),
    (166,   "Carré"),
    (322,   "Full"),
    (1599,  "Couleur"),
    (1609,  "Suite"),
    (2467,  "Brelan"),
    (3325,  "Double paire"),
    (6185,  "Paire"),
    (7462,  "Carte haute"),
]


def hand_strength_label(score: int) -> str:
    """Score phevaluator -> nom français de la catégorie."""
    for max_score, label in _BUCKETS:
        if score <= max_score:
            return label
    return "?"
