from collections import Counter
from itertools import combinations

# Catégories (du plus faible au plus fort)
HIGH_CARD = 0
PAIR = 1
TWO_PAIR = 2
THREE_KIND = 3
STRAIGHT = 4
FLUSH = 5
FULL_HOUSE = 6
FOUR_KIND = 7
STRAIGHT_FLUSH = 8

CATEGORY_NAMES = {
    HIGH_CARD: "Carte haute",
    PAIR: "Paire",
    TWO_PAIR: "Double paire",
    THREE_KIND: "Brelan",
    STRAIGHT: "Suite",
    FLUSH: "Couleur",
    FULL_HOUSE: "Full",
    FOUR_KIND: "Carré",
    STRAIGHT_FLUSH: "Quinte flush",
}


def _straight_high(values):
    """Retourne la carte haute d'une suite formée par `values` (set), sinon 0."""
    vs = set(values)
    if {14, 2, 3, 4, 5}.issubset(vs):
        best = 5
    else:
        best = 0
    for high in range(14, 5, -1):
        if all((high - i) in vs for i in range(5)):
            best = max(best, high)
            break
    return best


def _rank_5(cards):
    """Évalue exactement 5 cartes. Retourne un tuple comparable."""
    values = sorted((c.value for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    value_counts = Counter(values)
    by_count = sorted(value_counts.items(), key=lambda x: (-x[1], -x[0]))
    counts = [c for _, c in by_count]
    ordered_values = [v for v, _ in by_count]

    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(values)

    if is_flush and straight_high:
        return (STRAIGHT_FLUSH, straight_high)
    if counts[0] == 4:
        return (FOUR_KIND, ordered_values[0], ordered_values[1])
    if counts[0] == 3 and counts[1] == 2:
        return (FULL_HOUSE, ordered_values[0], ordered_values[1])
    if is_flush:
        return (FLUSH, *values)
    if straight_high:
        return (STRAIGHT, straight_high)
    if counts[0] == 3:
        return (THREE_KIND, ordered_values[0], *ordered_values[1:])
    if counts[0] == 2 and counts[1] == 2:
        return (TWO_PAIR, ordered_values[0], ordered_values[1], ordered_values[2])
    if counts[0] == 2:
        return (PAIR, ordered_values[0], *ordered_values[1:])
    return (HIGH_CARD, *values)


def best_hand(cards):
    """Meilleure main parmi 5 à 7 cartes."""
    if len(cards) < 5:
        raise ValueError("Il faut au moins 5 cartes")
    return max(_rank_5(combo) for combo in combinations(cards, 5))


def describe(rank_tuple):
    return CATEGORY_NAMES[rank_tuple[0]]
