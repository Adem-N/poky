"""
Cartes et paquet pour Texas Hold'em.

Convention :
  - Rangs : "23456789TJQKA" (T = 10)
  - Couleurs : s=pique, h=cœur, d=carreau, c=trèfle
  - Écriture courte : "As" = As de pique, "Th" = 10 de cœur, "2c" = 2 de trèfle
"""
import random

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}  # 2..14 (As=14)


class Card:
    __slots__ = ("rank", "suit")

    def __init__(self, rank, suit):
        if rank not in RANK_VALUE:
            raise ValueError(f"Rang invalide : {rank!r}")
        if suit not in SUITS:
            raise ValueError(f"Couleur invalide : {suit!r}")
        self.rank = rank
        self.suit = suit

    @classmethod
    def from_str(cls, s):
        """Parse 'As', 'Th', '2c'…"""
        if len(s) != 2:
            raise ValueError(f"Format carte invalide : {s!r}")
        return cls(s[0].upper() if s[0] != "T" else "T", s[1].lower())

    @property
    def value(self):
        return RANK_VALUE[self.rank]

    def __repr__(self):
        return f"{self.rank}{self.suit}"

    def __eq__(self, other):
        return isinstance(other, Card) and self.rank == other.rank and self.suit == other.suit

    def __hash__(self):
        return hash((self.rank, self.suit))


def all_cards():
    """52 cartes dans l'ordre canonique."""
    return [Card(r, s) for r in RANKS for s in SUITS]


class Deck:
    """
    Paquet mélangé. `seed` permet de rejouer la même main (utile pour les tests / l'arène).
    `exclude` retire des cartes déjà connues (utile pour Monte Carlo).
    """
    def __init__(self, exclude=None, seed=None):
        excluded = set(exclude) if exclude else set()
        self.cards = [c for c in all_cards() if c not in excluded]
        rng = random.Random(seed) if seed is not None else random
        rng.shuffle(self.cards)

    def draw(self, n=1):
        if n > len(self.cards):
            raise ValueError(f"Paquet épuisé ({len(self.cards)} cartes restantes, {n} demandées)")
        drawn = self.cards[:n]
        self.cards = self.cards[n:]
        return drawn

    def __len__(self):
        return len(self.cards)
