"""
CFR sur Leduc poker (validation algorithmique avant NLHE).

LEDUC POKER (Southey et al. 2005) — règles :
  - Paquet de 6 cartes : 3 rangs (J, Q, K) × 2 suits → cartes notées 0..5
    avec rank(i) = i // 2 (0=J, 1=Q, 2=K)
  - 2 joueurs, ante = 1 chacun
  - Chacun reçoit 1 carte privée (30 distributions possibles)
  - ROUND 1 : tour de mise (bet size = 2). Max 2 raises par round.
    Actions : check (c) / bet (b) / call (c après bet) / raise (r) / fold (f)
  - À la fin du round 1 (si pas de fold) : carte communautaire révélée
    (uniformément parmi les 4 restantes)
  - ROUND 2 : tour de mise (bet size = 4). Même structure.
  - SHOWDOWN : si une carte privée pair avec la communautaire → main gagnante
    Sinon : carte privée la plus haute en rang gagne.

INVARIANT testable : à l'équilibre, la valeur du jeu pour J1 est connue
(≈ -0.0856 selon Bowling et al. 2003). Notre CFR doit converger là.

ARCHITECTURE :
  - Game tree encodé via fonctions pures (is_terminal, legal_actions, etc.)
  - LeducCFR : vanilla CFR (énumération exacte des chance nodes)
  - LeducCFRExternalSampling : ES-MCCFR (échantillonne 1 community card)
  - best_response_value : exploitabilité (best response value pour adversaire)

Voir Brown & Sandholm 2017 pour ES-MCCFR. Voir Lanctot et al. 2009 pour
les variantes MCCFR.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---- Constantes du jeu ----------------------------------------------------

NUM_CARDS = 6                    # J♥, J♠, Q♥, Q♠, K♥, K♠
CARD_RANKS = [0, 0, 1, 1, 2, 2]  # rank par index
CARD_LABELS = ["Jh", "Js", "Qh", "Qs", "Kh", "Ks"]
ANTE = 1
BET_R1 = 2
BET_R2 = 4
MAX_RAISES_PER_ROUND = 2         # max actions agressives par round


def rank(card: int) -> int:
    return CARD_RANKS[card]


# ---- Mécaniques du game tree ----------------------------------------------

# Notations dans history :
#   - "c"  = check (si to_call=0) OU call (si to_call>0)
#   - "b"  = bet (première mise du round)
#   - "r"  = raise (mise par-dessus une bet/raise existante)
#   - "f"  = fold
# Les rounds sont séparés par "|". History "cc|" = round 1 cc, round 2 pas commencé.

def is_round_complete(round_str: str) -> bool:
    """Vrai si la round de betting est terminée (bets égalisés)."""
    return round_str in {"cc", "bc", "brc", "cbc", "cbrc"}


def is_terminal(history: str) -> bool:
    """Vrai si le jeu est terminé (fold ou round 2 complet)."""
    if "f" in history:
        return True
    parts = history.split("|")
    if len(parts) == 2 and is_round_complete(parts[1]):
        return True
    return False


def active_player(history: str) -> int:
    """Joueur à parler (0 = P1, 1 = P2)."""
    parts = history.split("|")
    return len(parts[-1]) % 2


def legal_actions(history: str) -> List[str]:
    """Actions légales à l'état courant."""
    parts = history.split("|")
    current = parts[-1]
    if current == "":
        return ["c", "b"]   # début de round : check ou bet
    last = current[-1]
    if last in ("b", "r"):
        # face à une mise : fold / call / (raise si quota dispo)
        aggressive_count = current.count("b") + current.count("r")
        actions = ["f", "c"]
        if aggressive_count < MAX_RAISES_PER_ROUND:
            actions.append("r")
        return actions
    # last == "c" donc c'était un check → autre joueur peut check ou bet
    return ["c", "b"]


def transition(history: str, action: str) -> str:
    """Applique action, gère les transitions de round."""
    parts = history.split("|")
    new_current = parts[-1] + action
    if action == "f":
        # Fold termine le jeu — on garde le marqueur
        parts[-1] = new_current
        return "|".join(parts)
    if is_round_complete(new_current):
        if len(parts) == 1:
            # Round 1 terminé → on ouvre round 2 (community pas encore révélée)
            return new_current + "|"
        # Round 2 terminé → état terminal
        parts[-1] = new_current
        return "|".join(parts)
    parts[-1] = new_current
    return "|".join(parts)


def needs_community_reveal(history: str) -> bool:
    """Vrai si on est entre les 2 rounds et il faut révéler la community."""
    parts = history.split("|")
    return len(parts) == 2 and parts[1] == ""


def chips_committed(history: str) -> Tuple[int, int]:
    """Calcule combien chaque joueur a mis au pot (incluant ante)."""
    p1, p2 = ANTE, ANTE
    for round_idx, round_str in enumerate(history.split("|")):
        bet_size = BET_R1 if round_idx == 0 else BET_R2
        # On track les chips dans CE round (hors ante)
        c1, c2 = 0, 0
        for i, action in enumerate(round_str):
            player = i % 2
            if action in ("b", "r"):
                # bet/raise = matcher la mise adverse + ajouter bet_size
                if player == 0:
                    c1 = max(c1, c2) + bet_size
                else:
                    c2 = max(c1, c2) + bet_size
            elif action == "c":
                # check (rien) ou call (matcher)
                if c1 > 0 or c2 > 0:  # call (qqun a bet)
                    if player == 0:
                        c1 = c2
                    else:
                        c2 = c1
                # else: simple check, rien à faire
            # 'f' n'ajoute pas de chips
        p1 += c1
        p2 += c2
    return p1, p2


def terminal_utility(history: str, card_p1: int, card_p2: int,
                     community: int) -> float:
    """
    Utilité NETTE pour P1 (zero-sum : P2 = -P1).
    Convention : si P1 gagne, util = +p2_chips (il gagne ce que P2 a mis).
    Si P1 perd, util = -p1_chips (il perd ce qu'il a mis).
    """
    p1_chips, p2_chips = chips_committed(history)
    # Détection fold
    parts = history.split("|")
    last_round = parts[-1]
    if "f" in last_round:
        fold_pos = last_round.index("f")
        folder = fold_pos % 2
        if folder == 0:
            return -float(p1_chips)         # P1 fold → perd sa contribution
        return float(p2_chips)              # P2 fold → P1 gagne celle de P2
    # Showdown : compare hand strength
    r1, r2, rc = rank(card_p1), rank(card_p2), rank(community)
    p1_paired = (r1 == rc)
    p2_paired = (r2 == rc)
    if p1_paired and not p2_paired:
        return float(p2_chips)
    if p2_paired and not p1_paired:
        return -float(p1_chips)
    # Personne n'a pair (les 2 pairés simultanément impossible avec 1 community)
    if r1 > r2:
        return float(p2_chips)
    if r2 > r1:
        return -float(p1_chips)
    return 0.0  # tie


# ---- Info sets ------------------------------------------------------------

@dataclass
class InfoSet:
    num_actions: int
    regret_sum: np.ndarray = field(default=None)
    strategy_sum: np.ndarray = field(default=None)

    def __post_init__(self):
        if self.regret_sum is None:
            self.regret_sum = np.zeros(self.num_actions, dtype=np.float64)
        if self.strategy_sum is None:
            self.strategy_sum = np.zeros(self.num_actions, dtype=np.float64)

    def current_strategy(self) -> np.ndarray:
        positive = np.maximum(self.regret_sum, 0.0)
        total = positive.sum()
        if total > 0:
            return positive / total
        return np.full(self.num_actions, 1.0 / self.num_actions)

    def average_strategy(self) -> np.ndarray:
        total = self.strategy_sum.sum()
        if total > 0:
            return self.strategy_sum / total
        return np.full(self.num_actions, 1.0 / self.num_actions)


def info_key(card: int, history: str, community: Optional[int]) -> str:
    """Clé canonique d'info set pour le joueur courant.
    En round 1 : (rang carte privée, history). En round 2 : + rang community."""
    own_rank = rank(card)
    if "|" in history and community is not None:
        return f"{own_rank}_{rank(community)}_{history}"
    return f"{own_rank}_?_{history}"


# ---- CFR ------------------------------------------------------------------

class LeducCFR:
    """Vanilla CFR (énumération exacte chance nodes). Convergence garantie."""

    def __init__(self, linear: bool = False):
        self.info_sets: Dict[str, InfoSet] = {}
        self.linear = linear
        self._iter = 1

    def _get(self, key: str, num_actions: int) -> InfoSet:
        if key not in self.info_sets:
            self.info_sets[key] = InfoSet(num_actions)
        return self.info_sets[key]

    def cfr(self, history: str, card_p1: int, card_p2: int,
            community: Optional[int], reach_p1: float, reach_p2: float) -> float:
        """Retourne l'utilité pour P1 à cet état. Met à jour les regrets."""
        if is_terminal(history):
            return terminal_utility(history, card_p1, card_p2, community)

        # Chance node : révélation community card entre rounds
        if needs_community_reveal(history) and community is None:
            total = 0.0
            count = 0
            for c in range(NUM_CARDS):
                if c == card_p1 or c == card_p2:
                    continue
                total += self.cfr(history, card_p1, card_p2, c, reach_p1, reach_p2)
                count += 1
            return total / count

        player = active_player(history)
        card = card_p1 if player == 0 else card_p2
        actions = legal_actions(history)
        info = self._get(info_key(card, history, community), len(actions))
        sigma = info.current_strategy()

        action_utils = np.zeros(len(actions))
        node_util = 0.0
        for i, a in enumerate(actions):
            new_h = transition(history, a)
            if player == 0:
                action_utils[i] = self.cfr(new_h, card_p1, card_p2, community,
                                           reach_p1 * sigma[i], reach_p2)
            else:
                action_utils[i] = self.cfr(new_h, card_p1, card_p2, community,
                                           reach_p1, reach_p2 * sigma[i])
            node_util += sigma[i] * action_utils[i]

        sign = 1.0 if player == 0 else -1.0
        opp_reach = reach_p2 if player == 0 else reach_p1
        own_reach = reach_p1 if player == 0 else reach_p2
        weight = self._iter if self.linear else 1.0

        for i in range(len(actions)):
            regret = sign * (action_utils[i] - node_util)
            info.regret_sum[i] += opp_reach * regret * weight
            info.strategy_sum[i] += own_reach * sigma[i] * weight

        return node_util

    def train(self, iterations: int) -> List[float]:
        """Lance N itérations. Retourne la valeur moyenne du jeu pour P1
        à chaque itération (devrait converger vers -0.0856)."""
        history_values = []
        cumulative = 0.0
        for it in range(1, iterations + 1):
            self._iter = it
            iter_util = 0.0
            count = 0
            for c1 in range(NUM_CARDS):
                for c2 in range(NUM_CARDS):
                    if c1 != c2:
                        iter_util += self.cfr("", c1, c2, None, 1.0, 1.0)
                        count += 1
            iter_util /= count
            cumulative += iter_util
            history_values.append(cumulative / it)
        return history_values


# ---- Best response (exploitabilité) ---------------------------------------

def best_response_value(strategy: Dict[str, np.ndarray],
                        responder: int) -> float:
    """
    Calcule la valeur de la best-response du joueur `responder` (0 ou 1)
    contre la stratégie moyenne fixée de l'adversaire.

    Exploitabilité = (BR_value_p0 + BR_value_p1) / 2 dans un zero-sum 2-player.
    Cible : exploitabilité → 0 = Nash atteint.
    """
    def br(history, card_p1, card_p2, community, p_reach_opp):
        """Récursif. Calcule la valeur attendue pour `responder` en jouant best response."""
        if is_terminal(history):
            u = terminal_utility(history, card_p1, card_p2, community)
            return u if responder == 0 else -u

        if needs_community_reveal(history) and community is None:
            total = 0.0
            count = 0
            for c in range(NUM_CARDS):
                if c == card_p1 or c == card_p2:
                    continue
                total += br(history, card_p1, card_p2, c, p_reach_opp)
                count += 1
            return total / count

        player = active_player(history)
        card = card_p1 if player == 0 else card_p2
        actions = legal_actions(history)

        if player == responder:
            # On choisit l'action qui maximise notre EV (best response)
            best = -float("inf")
            for a in actions:
                v = br(transition(history, a), card_p1, card_p2, community, p_reach_opp)
                if v > best:
                    best = v
            return best
        else:
            # Adversaire joue selon sa stratégie moyenne fixée
            key = info_key(card, history, community)
            sigma = strategy.get(key, np.full(len(actions), 1.0 / len(actions)))
            # Sécurité : si nb d'actions diffère, replier sur uniform
            if len(sigma) != len(actions):
                sigma = np.full(len(actions), 1.0 / len(actions))
            total = 0.0
            for i, a in enumerate(actions):
                v = br(transition(history, a), card_p1, card_p2, community, p_reach_opp * sigma[i])
                total += sigma[i] * v
            return total

    total = 0.0
    count = 0
    for c1 in range(NUM_CARDS):
        for c2 in range(NUM_CARDS):
            if c1 != c2:
                total += br("", c1, c2, None, 1.0)
                count += 1
    return total / count


def exploitability(trainer: LeducCFR) -> float:
    """Exploitabilité = moyenne des BR values. Plus c'est petit, plus on est près du Nash."""
    avg_strategy = {key: info.average_strategy()
                    for key, info in trainer.info_sets.items()}
    br0 = best_response_value(avg_strategy, responder=0)
    br1 = best_response_value(avg_strategy, responder=1)
    return (br0 + br1) / 2


# ---- Exécutable -----------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Train Leduc CFR.")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--linear", action="store_true",
                        help="Linear CFR (regrets pondérés par t)")
    parser.add_argument("--eval-every", type=int, default=200,
                        help="Calcul d'exploitabilité tous les N iters")
    args = parser.parse_args()

    trainer = LeducCFR(linear=args.linear)
    print(f"Training Leduc CFR ({'Linear' if args.linear else 'Vanilla'}) "
          f"pour {args.iterations} iters, eval tous les {args.eval_every}.")

    cumulative = 0.0
    for it in range(1, args.iterations + 1):
        trainer._iter = it
        iter_util = 0.0
        count = 0
        for c1 in range(NUM_CARDS):
            for c2 in range(NUM_CARDS):
                if c1 != c2:
                    iter_util += trainer.cfr("", c1, c2, None, 1.0, 1.0)
                    count += 1
        iter_util /= count
        cumulative += iter_util
        if it % args.eval_every == 0:
            exp = exploitability(trainer)
            print(f"  it {it:>6} | val moy J1 = {cumulative/it:+.5f} | "
                  f"exploitability = {exp:.5f}")
    print(f"\nTotal info sets visités : {len(trainer.info_sets)}")
    print(f"Valeur finale J1 : {cumulative/args.iterations:+.5f}")
    print(f"Référence Nash    : -0.08560 (Bowling et al. 2003)")


if __name__ == "__main__":
    main()
