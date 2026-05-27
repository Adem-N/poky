"""
HumanCLIPlayer — adapte un humain au tour de table comme n'importe quel autre bot.
Affiche l'état de la table en français, demande l'action à l'utilisateur.
"""
from poky.engine import Action, Observation, PositionType, Stage, PlayerStatus
from poky.players.base import Player


_STAGE_FR = {
    Stage.PREFLOP: "Pré-flop",
    Stage.FLOP: "Flop",
    Stage.TURN: "Turn",
    Stage.RIVER: "River",
    Stage.END: "Showdown",
}
_POSITION_FR = {
    PositionType.BUTTON: "BTN (bouton)",
    PositionType.SMALL_BLIND: "SB (small blind)",
    PositionType.BIG_BLIND: "BB (big blind)",
    PositionType.EARLY: "Early (UTG)",
    PositionType.MIDDLE: "Middle (MP)",
    PositionType.LATE: "Late (CO)",
}
_STATUS_CHAR = {
    PlayerStatus.ALIVE: " ",
    PlayerStatus.FOLDED: "X",
    PlayerStatus.ALLIN: "T",  # T pour Tapis
}
_ACTION_PROMPT = {
    Action.FOLD: ("f", "fold"),
    Action.CHECK_CALL: ("c", "check/call"),
    Action.RAISE_HALF_POT: ("h", "raise demi-pot"),
    Action.RAISE_POT: ("p", "raise pot"),
    Action.ALL_IN: ("a", "all-in"),
}


def _render_cards(cards) -> str:
    if not cards:
        return "—"
    # Convertit "HQ" -> "Q♥" pour l'affichage
    suits = {"H": "♥", "D": "♦", "S": "♠", "C": "♣"}
    return " ".join(c[1] + suits[c[0]] for c in cards)


class HumanCLIPlayer(Player):
    name = "human"

    def act(self, obs: Observation) -> Action:
        self._render(obs)
        return self._prompt(obs)

    # ---- affichage --------------------------------------------------------

    def _render(self, obs: Observation):
        print()
        print("═" * 64)
        print(f"  {_STAGE_FR[obs.stage]:<10}  "
              f"Pot : {obs.pot}  |  Tu joues : {_POSITION_FR[obs.my_position_type]}")
        print(f"  Board   : {_render_cards(obs.community_cards)}")
        print(f"  Ta main : {_render_cards(obs.hole_cards)}  "
              f"(stack {obs.my_stack}, déjà misé {obs.my_committed})")
        print()
        print(f"  {'Joueur':<10} {'Statut':<8} {'Misé':>6} {'Stack':>7}")
        for i in range(obs.num_players):
            label = "TOI" if i == obs.player_id else f"P{i}"
            if i == obs.dealer_id:
                label += "*"
            status = _STATUS_CHAR[obs.player_statuses[i]]
            print(f"  {label:<10} [{status}]      {obs.all_committed[i]:>6} {obs.all_stacks[i]:>7}")
        if obs.to_call > 0:
            print(f"\n  À suivre : {obs.to_call} chips")

    # ---- saisie d'action --------------------------------------------------

    def _prompt(self, obs: Observation) -> Action:
        options = [(action, *_ACTION_PROMPT[action]) for action in obs.legal_actions]
        legend = "  /  ".join(f"({key}){label}" for _, key, label in options)
        while True:
            choice = input(f"\n  Action ? [{legend}] > ").strip().lower()
            for action, key, _ in options:
                if choice == key or choice.startswith(key):
                    return action
            print("  Choix invalide.")
