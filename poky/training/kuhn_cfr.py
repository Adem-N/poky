"""
Vanilla Counterfactual Regret Minimization sur Kuhn poker.

POURQUOI ce fichier existe : Kuhn poker est le jeu canonique sur lequel on
valide une implémentation CFR — il est tellement petit qu'on connaît son
équilibre de Nash exact analytiquement (cf. Kuhn 1950), et la valeur du jeu
pour le joueur 1 vaut exactement -1/18.

Si notre CFR converge vers cette valeur ET vers les stratégies analytiques,
on a une preuve forte que l'algo est correct. On peut alors l'appliquer à
des jeux plus gros (Leduc, puis NLHE abstrait) avec confiance.

RÈGLES DE KUHN POKER :
  - 3 cartes : J (0), Q (1), K (2)
  - 2 joueurs, chacun mise 1 chip d'ante
  - chaque joueur reçoit 1 carte, la 3ème est défaussée
  - Joueur 1 : check ("c") ou bet ("b" → +1 chip)
      → si check :
          Joueur 2 : check (showdown, pot 2) ou bet ("b" → +1)
              → si bet : Joueur 1 fold (J2 gagne 2) ou call (showdown, pot 4)
      → si bet : Joueur 2 fold (J1 gagne 2) ou call (showdown, pot 4)

ÉQUILIBRE DE NASH ANALYTIQUE (Kuhn 1950) :
  J1 avec K : toujours bet
  J1 avec Q : check toujours ; call la bet avec proba 1/3
  J1 avec J : bet avec proba α ∈ [0, 1/3] ; fold toujours sur bet
  J2 avec K : toujours bet/call
  J2 avec Q : check toujours ; call avec proba 1/3
  J2 avec J : bet avec proba 1/3 ; fold toujours
  Valeur pour J1 : -1/18 ≈ -0.0556 (J2 a un léger avantage)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


CARDS = [0, 1, 2]  # J, Q, K
CARD_LABEL = {0: "J", 1: "Q", 2: "K"}


# ---- Logique du jeu Kuhn -------------------------------------------------

def is_terminal(history: str) -> bool:
    return history in ("cc", "cbf", "cbc", "bf", "bc")


def active_player(history: str) -> int:
    """0 = J1, 1 = J2. J1 commence ; chaque action change le tour sauf
    une fois 2 actions consécutives sans terminal."""
    return len(history) % 2


def legal_actions(history: str) -> List[str]:
    """À tout non-terminal, soit on est dans un noeud check/bet (deux options),
    soit dans un noeud fold/call (deux options)."""
    if history in ("", "c"):
        return ["c", "b"]   # check ou bet
    return ["f", "c"]       # fold ou call


def terminal_utility(history: str, card_p1: int, card_p2: int) -> int:
    """Utilité pour le joueur 1 au noeud terminal."""
    winner = 1 if card_p1 > card_p2 else -1
    if history == "cc":
        return winner * 1      # showdown, pot = 2 chips, gagnant +1
    if history == "cbf":
        return -1              # J1 check, J2 bet, J1 fold → J2 prend la blind de J1
    if history == "cbc":
        return winner * 2      # showdown, pot = 4
    if history == "bf":
        return 1               # J2 fold → J1 prend la blind de J2
    if history == "bc":
        return winner * 2      # showdown, pot = 4
    raise ValueError(f"Non-terminal : {history!r}")


# ---- Structure des info sets ---------------------------------------------

@dataclass
class InfoSet:
    """Données par info set : regret cumulé + somme des stratégies (pour la moyenne)."""
    num_actions: int
    regret_sum: List[float] = field(default_factory=list)
    strategy_sum: List[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.regret_sum:
            self.regret_sum = [0.0] * self.num_actions
        if not self.strategy_sum:
            self.strategy_sum = [0.0] * self.num_actions

    def current_strategy(self) -> List[float]:
        """Regret matching : action ∝ max(0, regret)."""
        positive = [max(r, 0.0) for r in self.regret_sum]
        total = sum(positive)
        if total > 0:
            return [r / total for r in positive]
        return [1.0 / self.num_actions] * self.num_actions

    def average_strategy(self) -> List[float]:
        total = sum(self.strategy_sum)
        if total > 0:
            return [s / total for s in self.strategy_sum]
        return [1.0 / self.num_actions] * self.num_actions


# ---- CFR -----------------------------------------------------------------

class KuhnCFRTrainer:
    def __init__(self):
        self.info_sets: Dict[str, InfoSet] = {}

    def _info_key(self, card: int, history: str) -> str:
        return f"{CARD_LABEL[card]}:{history}"

    def _info_set(self, card: int, history: str) -> InfoSet:
        key = self._info_key(card, history)
        if key not in self.info_sets:
            self.info_sets[key] = InfoSet(num_actions=2)
        return self.info_sets[key]

    def cfr(self, history: str, card_p1: int, card_p2: int,
            reach_p1: float, reach_p2: float) -> float:
        """
        Returns expected utility from player 1's perspective at this history.
        Met à jour les regrets et la somme de stratégies des info sets visités.
        """
        if is_terminal(history):
            return terminal_utility(history, card_p1, card_p2)

        player = active_player(history)
        card = card_p1 if player == 0 else card_p2
        info = self._info_set(card, history)
        sigma = info.current_strategy()
        actions = legal_actions(history)

        action_utils = [0.0] * len(actions)
        node_util = 0.0
        for i, a in enumerate(actions):
            if player == 0:
                action_utils[i] = self.cfr(history + a, card_p1, card_p2,
                                           reach_p1 * sigma[i], reach_p2)
            else:
                action_utils[i] = self.cfr(history + a, card_p1, card_p2,
                                           reach_p1, reach_p2 * sigma[i])
            node_util += sigma[i] * action_utils[i]

        # Regret : différence entre prendre l'action i contre-factuellement et
        # suivre sigma. Signé selon la perspective du joueur courant.
        opp_reach = reach_p2 if player == 0 else reach_p1
        own_reach = reach_p1 if player == 0 else reach_p2
        sign = 1.0 if player == 0 else -1.0
        for i in range(len(actions)):
            regret = sign * (action_utils[i] - node_util)
            info.regret_sum[i] += opp_reach * regret
            info.strategy_sum[i] += own_reach * sigma[i]

        return node_util

    def train(self, iterations: int) -> List[float]:
        """
        Lance `iterations` passes complètes (toutes les distributions énumérées).
        Retourne la valeur moyenne du jeu pour J1 à chaque itération
        (devrait converger vers -1/18 ≈ -0.0556).
        """
        history_values = []
        cumulative = 0.0
        for it in range(1, iterations + 1):
            iter_util = 0.0
            for c1 in CARDS:
                for c2 in CARDS:
                    if c1 != c2:
                        iter_util += self.cfr("", c1, c2, 1.0, 1.0)
            iter_util /= 6  # 6 distributions équiprobables
            cumulative += iter_util
            history_values.append(cumulative / it)
        return history_values

    # ---- analyse ---------------------------------------------------------

    def average_strategies(self) -> Dict[str, List[float]]:
        return {key: info.average_strategy()
                for key, info in sorted(self.info_sets.items())}

    def pretty_print(self) -> str:
        lines = []
        for key, strat in self.average_strategies().items():
            actions = legal_actions(key.split(":")[1])
            parts = [f"{a}={p:.3f}" for a, p in zip(actions, strat)]
            lines.append(f"  {key:<10}  " + "  ".join(parts))
        return "\n".join(lines)


# ---- Exécutable autonome -------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Entraînement CFR sur Kuhn poker.")
    parser.add_argument("--iterations", type=int, default=20_000)
    args = parser.parse_args()

    trainer = KuhnCFRTrainer()
    history = trainer.train(args.iterations)
    final_value = history[-1]

    print(f"Itérations : {args.iterations}")
    print(f"Valeur de jeu J1 (moyenne courante) : {final_value:+.5f}")
    print(f"Valeur attendue (Nash analytique)   : {-1/18:+.5f}")
    print(f"Écart : {abs(final_value - (-1/18)):.5f}")
    print()
    print("Stratégie moyenne par info set :")
    print(trainer.pretty_print())


if __name__ == "__main__":
    main()
