"""
Wrapper du moteur No-Limit Hold'em (basé sur rlcard).

Pourquoi un wrapper plutôt que d'utiliser rlcard directement partout :
  - on isole les types rlcard dans CE fichier, donc on peut changer de moteur
    (OpenSpiel, PyPokerEngine, custom) sans toucher au reste du code
  - on expose une API typée et explicite (Observation, Action, Stage) plus
    facile à manipuler que le dict brut de rlcard
  - on garantit la même représentation utilisée par les Players, l'arène,
    le training CFR et l'adaptateur plateforme

Notation des cartes (héritée de rlcard) : "HQ" = Dame de Cœur, "D4" = 4 de Carreau,
"S2" = 2 de Pique, "CT" = 10 de Trèfle. Premier caractère = suit (S/H/D/C),
second caractère = rank (2-9, T, J, Q, K, A).
"""
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Tuple

import rlcard


class Action(IntEnum):
    """Actions abstraites — les sizings sont calculés par rlcard."""
    FOLD = 0
    CHECK_CALL = 1       # check si rien à suivre, sinon call
    RAISE_HALF_POT = 2   # raise égal à 0.5 × pot
    RAISE_POT = 3        # raise égal à 1.0 × pot
    ALL_IN = 4           # tapis


class Stage(IntEnum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3
    END = 4


class Position(IntEnum):
    """Position en 3-max. Pour N >= 4, utilise PositionType."""
    BTN = 0   # bouton, dealer
    SB = 1    # small blind
    BB = 2    # big blind


class PositionType(IntEnum):
    """
    Position sémantique généralisée pour toutes les tailles de table.
    Dérivée de l'offset par rapport au bouton et du nombre de joueurs.
    """
    BUTTON = 0      # dealer, dernier à parler postflop (meilleure position)
    SMALL_BLIND = 1
    BIG_BLIND = 2
    EARLY = 3       # UTG en 6-max+, premier à parler préflop (pire pour ouvrir)
    MIDDLE = 4      # MP, HJ en 7-9-max
    LATE = 5        # CO en 5-max+, dernier à parler avant BTN préflop


def position_type(offset_from_btn: int, num_players: int) -> "PositionType":
    """
    Catégorise une position. `offset_from_btn` = (player_id - dealer_id) % num_players.
      offset 0 = BTN
      offset 1 = SB
      offset 2 = BB
      offset 3+ = positions "à parler" en fonction de la taille de table
    """
    if offset_from_btn == 0:
        return PositionType.BUTTON
    if offset_from_btn == 1:
        return PositionType.SMALL_BLIND
    if offset_from_btn == 2:
        return PositionType.BIG_BLIND
    # offset 3..num_players-1 : positions hors blindes ni bouton
    n_action_seats = num_players - 3   # nombre de sièges hors BTN/SB/BB
    idx = offset_from_btn - 3          # 0 = UTG, n_action_seats-1 = CO
    if n_action_seats <= 1:
        return PositionType.MIDDLE
    if idx == 0:
        return PositionType.EARLY
    if idx == n_action_seats - 1:
        return PositionType.LATE
    return PositionType.MIDDLE


class PlayerStatus(IntEnum):
    ALIVE = 0
    FOLDED = 1
    ALLIN = 2


# Actions disponibles dans l'ordre canonique — utile pour itérer ou construire
# des vecteurs de probabilités pour CFR.
ACTIONS = [Action.FOLD, Action.CHECK_CALL, Action.RAISE_HALF_POT,
           Action.RAISE_POT, Action.ALL_IN]


@dataclass
class Observation:
    """Tout ce qu'un joueur voit à son tour de parole.

    Toutes les infos exposées ici sont publiques : tout joueur humain assis
    à la table les voit (positions, blinds, qui a fold). Aucune info secrète
    n'est leakée (les hole cards des autres restent invisibles).
    """
    player_id: int                  # 0..num_players-1, qui doit jouer
    hole_cards: List[str]           # 2 cartes privées, ex ["HQ", "D4"]
    community_cards: List[str]      # 0, 3, 4 ou 5 cartes
    pot: int                        # taille totale du pot
    my_committed: int               # ce que j'ai déjà mis dans cette main
    my_stack: int                   # stack restant (chips encore devant moi)
    all_committed: List[int]        # ce que chaque joueur a mis dans cette main
    all_stacks: List[int]           # stacks restants de chacun
    stage: Stage
    legal_actions: List[Action]     # actions actuellement légales
    num_players: int

    # Métadonnées de position et statut (toutes publiques) :
    dealer_id: int                  # qui est au bouton
    small_blind: int                # taille de la SB (ex 1)
    big_blind: int                  # taille de la BB (ex 2)
    player_statuses: List[PlayerStatus]   # ALIVE / FOLDED / ALLIN par joueur

    # État brut rlcard — uniquement pour les Players ML (NFSP, DQN, ...) qui
    # parlent le format rlcard nativement (état encodé + legal actions OrderedDict).
    # Ignoré par tous les autres Players. None si non disponible.
    raw_state: Optional[dict] = None

    @property
    def offset_from_btn(self) -> int:
        """0 = BTN, 1 = SB, 2 = BB, 3+ = positions à parler."""
        return (self.player_id - self.dealer_id) % self.num_players

    @property
    def my_position(self) -> Position:
        """Position du joueur courant — valable strictement pour 3-max."""
        if self.num_players != 3:
            raise ValueError(
                f"Position est réservée au 3-max. Pour N={self.num_players} "
                f"utilise position_type ou offset_from_btn."
            )
        return Position(self.offset_from_btn)

    @property
    def my_position_type(self) -> "PositionType":
        """Type de position généralisé pour toute taille de table."""
        return position_type(self.offset_from_btn, self.num_players)

    @property
    def num_active_opponents(self) -> int:
        """Nombre d'adversaires encore en jeu (non foldés)."""
        return sum(1 for i, s in enumerate(self.player_statuses)
                   if i != self.player_id and s != PlayerStatus.FOLDED)

    @property
    def to_call(self) -> int:
        """Chips à mettre pour suivre la mise courante (0 si on peut checker)."""
        return max(self.all_committed) - self.my_committed


class Game:
    """
    Encapsule un environnement rlcard NLHE multi-joueurs.

    Cycle d'utilisation :
        game = Game(num_players=3, seed=42)
        obs, player_id = game.reset()
        while not game.is_over():
            action = mes_bots[player_id].act(obs)
            obs, player_id = game.step(action)
        payoffs = game.payoffs()  # liste de gains/pertes par joueur
    """

    def __init__(self, num_players: int = 3, seed: Optional[int] = None,
                 chips_per_player: int = 100):
        self.num_players = num_players
        config = {
            "game_num_players": num_players,
            "chips_for_each": chips_per_player,
            "seed": seed if seed is not None else 0,
        }
        self.env = rlcard.make("no-limit-holdem", config=config)

    def reset(self) -> Tuple[Observation, int]:
        state, player_id = self.env.reset()
        return self._wrap(state, player_id), player_id

    def step(self, action: Action) -> Tuple[Optional[Observation], int]:
        """
        Joue `action` pour le joueur courant. Retourne (next_obs, next_player_id).
        Si la main est terminée, next_obs vaut None et next_player_id vaut -1.
        """
        next_state, next_player = self.env.step(int(action))
        if self.env.is_over():
            return None, -1
        return self._wrap(next_state, next_player), next_player

    def is_over(self) -> bool:
        return self.env.is_over()

    def payoffs(self) -> List[float]:
        """Gains de chaque joueur pour la main qui vient de se terminer (somme nulle)."""
        return list(self.env.get_payoffs())

    # ---- interne -----------------------------------------------------------

    def _wrap(self, state: dict, player_id: int) -> Observation:
        raw = state["raw_obs"]
        legal = [Action(int(a)) for a in state["legal_actions"]]
        stage_val = raw["stage"].value if hasattr(raw["stage"], "value") else int(raw["stage"])

        # Récupère dealer, blinds, statuts via les internals rlcard.
        game = self.env.game
        # Map rlcard PlayerStatus -> notre PlayerStatus (sécurité au cas où les noms changent).
        statuses = []
        for p in game.players:
            name = p.status.name
            if name == "FOLDED":
                statuses.append(PlayerStatus.FOLDED)
            elif name == "ALLIN":
                statuses.append(PlayerStatus.ALLIN)
            else:
                statuses.append(PlayerStatus.ALIVE)

        return Observation(
            player_id=player_id,
            hole_cards=list(raw["hand"]),
            community_cards=list(raw["public_cards"]),
            pot=int(raw["pot"]),
            my_committed=int(raw["my_chips"]),
            my_stack=int(raw["stakes"][player_id]),
            all_committed=[int(c) for c in raw["all_chips"]],
            all_stacks=[int(s) for s in raw["stakes"]],
            stage=Stage(int(stage_val)),
            legal_actions=legal,
            num_players=self.num_players,
            dealer_id=int(game.dealer_id),
            small_blind=int(game.small_blind),
            big_blind=int(game.big_blind),
            player_statuses=statuses,
            raw_state=state,
        )
