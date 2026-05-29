"""
Tier 2 postflop rules — principes pro postflop appliqués comme heuristiques.

Couvre pour Phase X2 le seul case haute-fréquence + haute-valeur :
**c-bet sur le flop quand on est preflop-aggressor (PFA)**. Les autres
spots (turn, river, defense vs c-bet) restent au Tier 2 nu (HeuristicPlayer).

Pourquoi ce focus :
  - PFA c-bet flop = ~30% des mains qu'on joue. Volume énorme.
  - Heuristic c-bet seulement si equity > 0.6. Sur les boards où notre
    equity vs random est ~0.3-0.5 mais où on garde l'initiative et
    où l'adversaire a souvent raté le board (typique broadway hands),
    on rate beaucoup de c-bets profitables.
  - Adversaire Heuristic fold si equity < pot_odds + 0.03. Sur un c-bet
    de 1/2 pot, pot_odds = 0.25 → fold si equity < 0.28. Notre fold
    equity est massive sur les flops déconnectés.

Logique :
  texture(flop) → DRY | SEMI | WET | PAIRED
  equity(my_hand, board) → MC simulation
  → action probability distribution

Sur le turn/river, on rentre dans le scope Phase X2.x (à venir).
"""
import random
from enum import Enum
from typing import List, Optional, Tuple

from poky.engine import Action, Observation, Stage
from poky.equity import monte_carlo_equity


class FlopTexture(Enum):
    """Quatre catégories suffisantes pour différencier les c-bet patterns."""
    DRY = "DRY"            # déconnecté + rainbow / 2-tone basse connect.
    SEMI = "SEMI"          # un draw possible + rang spread mid
    WET = "WET"             # monotone OU 2-tone connecté
    PAIRED = "PAIRED"      # paire au board


_RANK_VAL = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
             "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}


def flop_texture(community_cards: List[str]) -> Optional[FlopTexture]:
    """Classifie la texture d'un flop (3 cartes) en 4 catégories.

    Retourne None si pas exactement 3 cartes (turn/river → autre logique).
    Convention rlcard : carte = 'HQ' (suit Hearts, rank Queen).
    """
    if len(community_cards) != 3:
        return None

    ranks = sorted([_RANK_VAL[c[1]] for c in community_cards], reverse=True)
    suits = [c[0] for c in community_cards]

    is_paired = len(set(ranks)) < 3
    n_suits = len(set(suits))
    is_monotone = n_suits == 1
    is_twotone = n_suits == 2
    spread = ranks[0] - ranks[2]

    # Connectivité : nombre de "straight outs" envisageables
    # Heuristique simple : spread ≤ 4 = connecté (un str8 draw possible)
    is_connected = spread <= 4 and not is_paired

    if is_paired:
        return FlopTexture.PAIRED
    if is_monotone:
        # Flop monotone toujours WET (flush draw garanti)
        return FlopTexture.WET
    if is_twotone and is_connected:
        return FlopTexture.WET
    if is_twotone:
        # Two-tone mais spread > 4 (ex Ks 7c 2s) → SEMI (1 flush draw)
        return FlopTexture.SEMI
    if is_connected:
        # Rainbow connected (ex 9h 8c 7d) → SEMI (str8 draws communs)
        return FlopTexture.SEMI
    # Rainbow déconnecté (ex Kh 7c 2d) → DRY
    return FlopTexture.DRY


def _norm(d: dict) -> List[Tuple[Action, float]]:
    """Convertit {action: weight} → [(action, normalized_freq), ...]."""
    total = sum(d.values())
    if total <= 0:
        return []
    return [(a, w / total) for a, w in d.items() if w > 0]


def cbet_flop_pfa(obs: Observation, rng: random.Random,
                  mc_simulations: int = 200) -> Optional[List[Tuple[Action, float]]]:
    """Stratégie c-bet quand on est PFA sur le flop.

    Principes appliqués :
      - Boards DRY : c-bet wide (jusqu'à 75%), petit sizing (1/2 pot).
        On a la range advantage post-raise vs caller.
      - Boards WET : c-bet polarisé (value top + draws), bigger size pour
        denier les implied odds des draws.
      - Boards PAIRED : c-bet ~60% small (range advantage forte).
      - Boards SEMI : intermédiaire.

    Combinés avec notre equity (MC vs 1 random opp) :
      - equity > 0.65 : pure value, bet quasi-toujours.
      - equity 0.40-0.65 : depend texture (DRY → bet, WET → check more).
      - equity < 0.40 : bluff sparingly sur DRY, check sur WET.

    Retourne None si situation non-supportée (sizing exotique, etc.).
    """
    texture = flop_texture(obs.community_cards)
    if texture is None:
        return None
    if Action.RAISE_HALF_POT not in obs.legal_actions:
        # Si on ne peut pas faire un sizing standard, abandonne au Tier 2
        return None
    # Si quelqu'un a déjà bet/raise sur ce flop, ce n'est plus un "c-bet"
    # (c'est un raise-vs-bet). Hors scope X2.
    if obs.to_call > 0:
        return None

    num_opp = max(1, obs.num_active_opponents)
    equity = monte_carlo_equity(
        hole_rlcard=obs.hole_cards,
        board_rlcard=obs.community_cards,
        num_opponents=num_opp,
        simulations=mc_simulations,
        rng=rng,
    )

    # Stratégie v0.3 (sizing-aware, value-only) :
    #
    # Insights après v0.1/v0.2 :
    # - Bluffer flop vs Heuristic est -EV : leur defense (equity>0.28) est trop
    #   wide pour fold à un bluff (~30% fold equity, math négative).
    # - Heuristic value bet equity>0.60 (small) ou >0.80 (big). On peut :
    #   (a) LOWER le threshold de value bet à 0.50 → extraire value de hands
    #       que Heuristic check (où on perd le edge en check par derrière).
    #   (b) Sur boards WET avec nuts/near-nuts (>0.75), monter à RAISE_POT
    #       au lieu de HALF_POT pour denier les implied odds des draws.
    # - Sur DRY high (Axx, Kxx) où on a la range advantage, value bet plus
    #   wide (equity>0.45 OK).

    if texture == FlopTexture.DRY:
        if equity > 0.80:
            return _norm({Action.RAISE_POT: 0.85, Action.RAISE_HALF_POT: 0.15})
        if equity > 0.55:
            return _norm({Action.RAISE_HALF_POT: 0.90, Action.CHECK_CALL: 0.10})
        if equity > 0.45:
            # Wider value bet sur DRY (range advantage)
            return _norm({Action.RAISE_HALF_POT: 0.65, Action.CHECK_CALL: 0.35})
        # marginal/air : check, no bluff
        return _norm({Action.CHECK_CALL: 1.0})

    if texture == FlopTexture.SEMI:
        if equity > 0.80:
            return _norm({Action.RAISE_POT: 0.80, Action.RAISE_HALF_POT: 0.20})
        if equity > 0.55:
            return _norm({Action.RAISE_HALF_POT: 0.80, Action.CHECK_CALL: 0.20})
        if equity > 0.45:
            return _norm({Action.RAISE_HALF_POT: 0.55, Action.CHECK_CALL: 0.45})
        return _norm({Action.CHECK_CALL: 1.0})

    if texture == FlopTexture.WET:
        if equity > 0.75:
            # Nuts WET : bet big pour denier les draws
            return _norm({Action.RAISE_POT: 0.85, Action.RAISE_HALF_POT: 0.15})
        if equity > 0.60:
            return _norm({Action.RAISE_HALF_POT: 0.70, Action.CHECK_CALL: 0.30})
        if equity > 0.50:
            return _norm({Action.RAISE_HALF_POT: 0.40, Action.CHECK_CALL: 0.60})
        return _norm({Action.CHECK_CALL: 1.0})

    if texture == FlopTexture.PAIRED:
        if equity > 0.75:
            return _norm({Action.RAISE_POT: 0.75, Action.RAISE_HALF_POT: 0.25})
        if equity > 0.55:
            return _norm({Action.RAISE_HALF_POT: 0.85, Action.CHECK_CALL: 0.15})
        if equity > 0.40:
            return _norm({Action.RAISE_HALF_POT: 0.50, Action.CHECK_CALL: 0.50})
        return _norm({Action.CHECK_CALL: 1.0})

    return None


def pro_postflop_strategy(obs: Observation, *, was_pfa: bool,
                          rng: random.Random) -> Optional[List[Tuple[Action, float]]]:
    """Entry point Tier 2 postflop expert.

    Args:
      obs: Observation au tour de hero.
      was_pfa: True si hero a été le dernier raiser préflop (PFA).
      rng: pour le sample MC equity (déterministe par seed).

    Retourne :
      - List[(Action, freq)] avec sum freq ≈ 1.0
      - None si situation non couverte → caller fallback Tier 2 (Heuristic).

    Scope Phase X2 v0.1 :
      - FLOP only
      - PFA c-bet only (pas defense vs c-bet, pas turn/river)
    """
    if obs.stage != Stage.FLOP:
        return None
    if not was_pfa:
        return None
    return cbet_flop_pfa(obs, rng)
