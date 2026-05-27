"""
Arène bot-vs-bot : fait jouer K bots sur N mains et collecte des stats.

Métriques clés :
  - chips nets par joueur (somme algébrique des gains/pertes)
  - bb/100 (gains en big blinds par 100 mains — métrique standard en poker)
  - intervalle de confiance à 95% sur bb/100 (la variance au poker est énorme,
    sans IC les chiffres n'ont aucun sens)

Rotation des sièges : chaque main, on rotate qui occupe quel siège. Sur 3 joueurs
et 3·N mains, chaque joueur joue exactement N mains à chaque position. Ça neutralise
le biais positionnel (le bouton est meilleure position que la BB).
"""
import math
from dataclasses import dataclass, field
from typing import List, Sequence

from poky.engine import Game
from poky.players.base import Player, ActionEvent


BIG_BLIND = 2  # rlcard default ; à factoriser si on change la config


@dataclass
class PlayerStats:
    name: str
    chips: float = 0.0          # somme des gains nets en chips
    chips_sq: float = 0.0       # somme des carrés des gains par main (pour la variance)
    hands: int = 0

    @property
    def bb_per_100(self) -> float:
        if self.hands == 0:
            return 0.0
        return (self.chips / BIG_BLIND) / self.hands * 100

    @property
    def stderr_bb100(self) -> float:
        """Erreur standard de la moyenne, en bb/100."""
        if self.hands < 2:
            return float("inf")
        mean = self.chips / self.hands
        var = (self.chips_sq - self.hands * mean * mean) / (self.hands - 1)
        var = max(var, 0.0)
        se_chips_per_hand = math.sqrt(var / self.hands)
        return (se_chips_per_hand / BIG_BLIND) * 100

    @property
    def ci95_bb100(self) -> float:
        return 1.96 * self.stderr_bb100


@dataclass
class MatchResult:
    stats: List[PlayerStats]
    hands_played: int
    seed: int

    def summary(self) -> str:
        lines = [
            f"=== Résultat sur {self.hands_played} mains (seed {self.seed}) ===",
            f"{'Joueur':<15} {'Mains':>8} {'Chips':>10} {'bb/100':>10} {'±IC95%':>10}",
            "-" * 60,
        ]
        for s in self.stats:
            lines.append(
                f"{s.name:<15} {s.hands:>8} {s.chips:>+10.1f} "
                f"{s.bb_per_100:>+10.2f} {s.ci95_bb100:>10.2f}"
            )
        return "\n".join(lines)


def run_match(players: Sequence[Player], hands: int, seed: int = 0,
              chips_per_player: int = 100, verbose: bool = False) -> MatchResult:
    """
    Joue `hands` mains entre les bots `players`. Renvoie un MatchResult.

    `players` doit contenir num_players bots (3 par défaut pour 3-max).
    On rotate les sièges chaque main pour neutraliser la position.
    """
    n = len(players)
    stats = [PlayerStats(name=f"{p.name}#{i}") for i, p in enumerate(players)]

    for hand_idx in range(hands):
        # Rotation des sièges : à la main h, le joueur logique i s'assoit au siège (i+h) % n.
        # Donc le siège s est occupé par le joueur (s - h) % n.
        seat_to_player = [(s - hand_idx) % n for s in range(n)]
        seat_players = [players[seat_to_player[s]] for s in range(n)]
        for p in seat_players:
            p.reset()

        game = Game(num_players=n, seed=seed + hand_idx,
                    chips_per_player=chips_per_player)
        obs, current_seat = game.reset()
        while not game.is_over():
            action = seat_players[current_seat].act(obs)
            if action not in obs.legal_actions:
                # Garde-fou : si un bot retourne une action illégale, on FOLD.
                action = obs.legal_actions[0]
            # Diffuse l'événement d'action à TOUS les joueurs (pour opponent modeling)
            event = ActionEvent(
                actor=current_seat,
                action=action,
                stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seat_players:
                p.observe_action(event)
            obs, current_seat = game.step(action)

        payoffs = game.payoffs()
        for seat, payoff in enumerate(payoffs):
            player_idx = seat_to_player[seat]
            stats[player_idx].chips += payoff
            stats[player_idx].chips_sq += payoff * payoff
            stats[player_idx].hands += 1

        if verbose and (hand_idx + 1) % max(1, hands // 10) == 0:
            print(f"  {hand_idx + 1}/{hands} mains jouées")

    return MatchResult(stats=stats, hands_played=hands, seed=seed)
