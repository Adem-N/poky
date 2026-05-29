"""
Bench rapide pour itérer sur les ranges expertes.

Lance ExpertOnlyPlayer dans 1 siège contre (N-1) HeuristicPlayer sur le
nombre demandé de mains, en faisant tourner le siège de l'expert à chaque
main pour neutraliser le biais positionnel. Reporte :
  - bb/100 global avec IC95
  - Couverture préflop
  - Breakdown des actions par scenario_key
  - EV moyen par scenario_key (mains où ce scenario a été déclenché)

Usage :
  python scripts/bench_expert.py --hands 5000 --seeds 7,13,21,42,99
  python scripts/bench_expert.py --players 3 --hands 5000
  python scripts/bench_expert.py --players 6 --hands 3000
"""
import argparse
import math
from collections import defaultdict

from poky.engine import Game
from poky.players.archetypes import (
    LooseAggressivePlayer, ManiacPlayer, TightAggressivePlayer,
    TightPassivePlayer,
)
from poky.players.base import ActionEvent
from poky.players.call_player import AlwaysCallPlayer
from poky.players.expert_only import ExpertOnlyPlayer
from poky.players.heuristic import HeuristicPlayer
from poky.players.random_player import RandomPlayer


_OPP_FACTORIES = {
    "heuristic": HeuristicPlayer,
    "tag": TightAggressivePlayer,
    "lag": LooseAggressivePlayer,
    "maniac": ManiacPlayer,
    "nit": TightPassivePlayer,
    "random": RandomPlayer,
    "call": AlwaysCallPlayer,
}


BIG_BLIND = 2


def run_match(num_players: int, expert_factory, opp_factory,
              hands: int, seed: int, chips_per_player: int = 200):
    """Lance une partie de N joueurs avec l'expert qui cycle à chaque main.

    L'expert prend le siège (hand_idx % num_players). Cela neutralise le
    biais positionnel : sur N mains, l'expert passe ~ N/k fois par chaque
    siège. Cela suppose que rlcard attribue le dealer par fonction du seed
    (en pratique : oui), donc les sièges sont symétriques.

    Retourne (payoffs_expert_per_hand, expert_player_final).
    """
    expert = expert_factory()
    opps = [opp_factory() for _ in range(num_players - 1)]
    payoffs_expert = []

    for hand_idx in range(hands):
        expert_seat = hand_idx % num_players
        seats = list(opps)
        seats.insert(expert_seat, expert)
        assert len(seats) == num_players

        for p in seats:
            p.reset()

        game = Game(num_players=num_players, seed=seed + hand_idx,
                    chips_per_player=chips_per_player)
        obs, current_seat = game.reset()
        while not game.is_over():
            action = seats[current_seat].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]
            event = ActionEvent(
                actor=current_seat, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seats:
                p.observe_action(event)
            obs, current_seat = game.step(action)

        payoffs = game.payoffs()
        payoffs_expert.append(payoffs[expert_seat])

    expert.reset()    # flush last hand scenarios
    return payoffs_expert, expert


def summarize(label: str, payoffs_per_seed: dict, expert_per_seed: dict):
    """Affiche un résumé du benchmark."""
    print(f"\n=== {label} ===")
    total_payoffs = []
    for seed, payoffs in sorted(payoffs_per_seed.items()):
        hands = len(payoffs)
        chips_sum = sum(payoffs)
        bb100 = chips_sum / hands / BIG_BLIND * 100
        total_payoffs.extend(payoffs)
        print(f"  seed {seed:>4}: {chips_sum:+7.1f} chips, "
              f"{bb100:+6.2f} bb/100  ({hands} mains)")

    n_total = len(total_payoffs)
    mean_chips = sum(total_payoffs) / n_total
    var_chips = sum((p - mean_chips) ** 2 for p in total_payoffs) / max(n_total - 1, 1)
    std_chips = math.sqrt(var_chips)
    se_bb100 = (std_chips / math.sqrt(n_total)) / BIG_BLIND * 100
    mean_bb100 = mean_chips / BIG_BLIND * 100
    print(f"\n  >>> Mean : {mean_bb100:+6.2f} bb/100  "
          f"(+/-{1.96*se_bb100:.2f} IC95, n={n_total})")

    # Couverture (dernière seed représentative car expert reset à chaque seed)
    last_expert = list(expert_per_seed.values())[-1] if expert_per_seed else None
    if last_expert:
        total_decisions = last_expert.preflop_expert_hits + last_expert.preflop_fallback_hits
        coverage = last_expert.preflop_expert_hits / max(total_decisions, 1)
        print(f"  Couverture préflop : {coverage:.1%} "
              f"({last_expert.preflop_expert_hits} hits, "
              f"{last_expert.preflop_fallback_hits} fallback)")

    # Breakdown : scenarios déclenchés + actions agrégés sur toutes les seeds
    scenario_counts = defaultdict(int)
    scenario_action_counts = defaultdict(lambda: defaultdict(int))
    for expert in expert_per_seed.values():
        for sc_list in expert.scenarios_per_hand:
            for sc in sc_list:
                scenario_counts[sc] += 1
        for sc, actions in expert.scenario_actions.items():
            for action, count in actions.items():
                scenario_action_counts[sc][action] += count

    print("\n  Scenarios déclenchés (toutes seeds agrégées) :")
    for sc in sorted(scenario_counts, key=lambda s: -scenario_counts[s]):
        action_summary = dict(scenario_action_counts[sc])
        action_summary_str = ", ".join(f"{a.name}={n}" for a, n in
                                       sorted(action_summary.items(),
                                              key=lambda x: -x[1]))
        print(f"    {sc:32s}: n={scenario_counts[sc]:5d}  {action_summary_str}")

    # EV moyen par scenario : attribue le payoff de la main aux scenarios
    # déclenchés cette main. Si plusieurs scenarios déclenchés (RFI + vs_3bet
    # par ex), payoff attribué à CHACUN — somme(EV)>total. Utile en relatif.
    scenario_payoffs = defaultdict(list)
    for seed, payoffs in payoffs_per_seed.items():
        expert = expert_per_seed[seed]
        sc_per_hand = expert.scenarios_per_hand
        n_min = min(len(payoffs), len(sc_per_hand))
        for i in range(n_min):
            for sc in set(sc_per_hand[i]):
                scenario_payoffs[sc].append(payoffs[i])

    print("\n  EV moyen par scenario déclenché (en bb/main) :")
    for sc in sorted(scenario_payoffs, key=lambda s: -len(scenario_payoffs[s])):
        pl = scenario_payoffs[sc]
        if not pl:
            continue
        ev_bb = sum(pl) / len(pl) / BIG_BLIND
        print(f"    {sc:32s}: n={len(pl):>5}  EV={ev_bb:+.3f} bb/main")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=2,
                    choices=[2, 3, 6],
                    help="Nombre de joueurs (2/3/6)")
    ap.add_argument("--hands", type=int, default=5000)
    ap.add_argument("--seeds", type=str, default="7,13,21,42,99")
    ap.add_argument("--rng-seed", type=int, default=42)
    ap.add_argument("--opp", type=str, default="heuristic",
                    choices=list(_OPP_FACTORIES.keys()),
                    help="Archetype des adversaires")
    ap.add_argument("--chips", type=int, default=200,
                    help="Chips par joueur. 200 = 100bb effectif (BB=2). "
                         "Défaut historique 100=50bb.")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    n = args.players
    table_label = {2: "HU", 3: "3-max", 6: "6-max"}[n]
    opp_cls = _OPP_FACTORIES[args.opp]
    stack_bb = args.chips // BIG_BLIND
    print(f"Bench ExpertOnly vs {args.opp.upper()} — {table_label} — "
          f"stack={stack_bb}bb — "
          f"{args.hands} mains × {len(seeds)} seeds = "
          f"{args.hands*len(seeds)} mains total")

    payoffs_per_seed = {}
    expert_per_seed = {}
    for i, seed in enumerate(seeds):
        # Donner des seeds différentes à chaque opp pour casser le risque
        # de RNG corrélé entre adversaires.
        opp_seed_base = args.rng_seed + 1 + i * 100
        payoffs, expert = run_match(
            num_players=n,
            expert_factory=lambda: ExpertOnlyPlayer(seed=args.rng_seed),
            opp_factory=lambda _seed=opp_seed_base: opp_cls(
                seed=_seed + 1
            ),
            hands=args.hands, seed=seed,
            chips_per_player=args.chips,
        )
        payoffs_per_seed[seed] = payoffs
        expert_per_seed[seed] = expert

    summarize(f"ExpertOnly vs {args.opp.upper()} {table_label}",
              payoffs_per_seed, expert_per_seed)


if __name__ == "__main__":
    main()
