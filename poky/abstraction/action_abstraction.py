"""
Action abstraction pour MCCFR sur NLHE.

NLHE a en théorie un continuum de sizings (n'importe quel int de min-raise à all-in).
Pour MCCFR, on collapse en 5 actions discrètes — c'est exactement ce que rlcard
expose déjà via son enum `Action` :

  FOLD             = 0
  CHECK_CALL       = 1
  RAISE_HALF_POT   = 2
  RAISE_POT        = 3
  ALL_IN           = 4

Cette abstraction (cf. Pluribus) capture suffisamment de granularité pour
atteindre un niveau pro — on perd un peu sur les small-bets (1/3 pot) mais on
gagne énormément en compacité du game tree.

API :
  legal_abstract_actions(obs) -> List[Action]
    Filtre l'enum Action par ce qui est légal dans l'état courant.
  action_index(action) -> int
    0..4, utilisé pour indexer regret_sum / strategy_sum dans MCCFR.
  index_to_action(idx) -> Action
    Inverse.
"""
from typing import List

from poky.engine import Action


# Ordre canonique des actions abstraites (correspond à leur valeur enum)
ABSTRACT_ACTIONS: List[Action] = [
    Action.FOLD,
    Action.CHECK_CALL,
    Action.RAISE_HALF_POT,
    Action.RAISE_POT,
    Action.ALL_IN,
]

NUM_ABSTRACT_ACTIONS = len(ABSTRACT_ACTIONS)


def legal_abstract_actions(obs) -> List[Action]:
    """Retourne les actions abstraites légales pour l'observation courante.
    Wrapper sur obs.legal_actions, ordre canonique conservé."""
    legal = set(obs.legal_actions)
    return [a for a in ABSTRACT_ACTIONS if a in legal]


def action_index(action: Action) -> int:
    """Index 0..4 d'une action abstraite (= sa valeur enum)."""
    return int(action)


def index_to_action(idx: int) -> Action:
    """Action correspondant à un index 0..4."""
    return ABSTRACT_ACTIONS[idx]
