"""
Session de jeu LONGUE avec logging structuré + rapport de leaks.

  python -m poky.cli.long_session --champion adaptive --hands 500
  python -m poky.cli.long_session --champion nfsp --hands 1000 --session-name nfsp_v1_test

L'opposant est par défaut ProClaude (notre simulation de joueur pro).
3-max : ProClaude vs Champion vs Champion.

Outputs :
  - Logs dans data/sessions/{session_name}/hand_*.json
  - Méta dans data/sessions/{session_name}/meta.json
  - Rapport printé : stats par joueur + patterns de leaks du champion
"""
import argparse
import os
import sys
import time

from poky.arena.runner import PlayerStats, BIG_BLIND
from poky.cli.tournament import PLAYER_FACTORY
from poky.engine import Game, Stage
from poky.players import ProClaude
from poky.players.base import ActionEvent
from poky.logging import SessionLogger, HandRecord
from poky.logging.analyzer import render_report, load_session


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


_STAGE_NAME = {
    Stage.PREFLOP: "PREFLOP",
    Stage.FLOP: "FLOP",
    Stage.TURN: "TURN",
    Stage.RIVER: "RIVER",
    Stage.END: "END",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--champion", default="adaptive",
                        choices=list(PLAYER_FACTORY))
    parser.add_argument("--hands", type=int, default=500)
    parser.add_argument("--seed-base", type=int, default=42)
    parser.add_argument("--chips", type=int, default=100)
    parser.add_argument("--session-name", default=None)
    parser.add_argument("--num-players", type=int, default=3,
                        help="taille de la table (3-max par défaut)")
    args = parser.parse_args()

    # Composition : seat 0 = ProClaude, seats 1..N-1 = champion
    pro = ProClaude(seed=99)
    bots = [PLAYER_FACTORY[args.champion](i)
            for i in range(args.num_players - 1)]
    players = [pro] + bots
    player_names = [p.name for p in players]

    logger = SessionLogger(session_name=args.session_name)
    print(f"Session {logger.session_name} : {player_names}, "
          f"{args.hands} mains, seed {args.seed_base}")
    print(f"Logs : {logger.dir}/")

    logger.write_meta({
        "session_name": logger.session_name,
        "players": player_names,
        "num_players": args.num_players,
        "hands": args.hands,
        "seed_base": args.seed_base,
        "chips_per_player": args.chips,
        "champion": args.champion,
        "pro_seat": 0,
        "champion_seats": list(range(1, args.num_players)),
        "started_at": time.time(),
    })

    # Stats agrégées
    stats = [PlayerStats(name=p.name) for p in players]

    start = time.time()
    for hand_idx in range(args.hands):
        # Rotation des sièges pour neutralité positionnelle
        seat_to_player = [(s - hand_idx) % args.num_players
                          for s in range(args.num_players)]
        seat_players = [players[seat_to_player[s]] for s in range(args.num_players)]
        for p in seat_players:
            p.reset()

        game = Game(num_players=args.num_players,
                    seed=args.seed_base + hand_idx,
                    chips_per_player=args.chips)
        obs, current_seat = game.reset()

        # Initialisation du HandRecord
        rl_players = game.env.game.players
        holes = {str(s): [c.suit + c.rank for c in rl_players[s].hand]
                 for s in range(args.num_players)}
        record = HandRecord(
            hand_id=hand_idx,
            seed=args.seed_base + hand_idx,
            dealer_id=int(game.env.game.dealer_id),
            starting_stacks=[args.chips] * args.num_players,
            holes=holes,
            boards={},
        )

        last_stage = None
        while not game.is_over():
            # Détection nouveau stage → log les cartes ajoutées au board
            if obs.stage != last_stage and obs.community_cards:
                stage_name = _STAGE_NAME[obs.stage]
                if stage_name == "FLOP":
                    record.boards["flop"] = list(obs.community_cards[:3])
                elif stage_name == "TURN" and len(obs.community_cards) >= 4:
                    record.boards["turn"] = [obs.community_cards[3]]
                elif stage_name == "RIVER" and len(obs.community_cards) >= 5:
                    record.boards["river"] = [obs.community_cards[4]]
                last_stage = obs.stage

            action = seat_players[current_seat].act(obs)
            if action not in obs.legal_actions:
                action = obs.legal_actions[0]

            # Capte le flag critical depuis ProClaude
            is_crit = getattr(seat_players[current_seat], "last_critical", False)
            note = getattr(seat_players[current_seat], "last_critical_note", None)

            record.add_action(
                stage=_STAGE_NAME[obs.stage],
                actor=current_seat,
                action=action.name,
                pot_before=obs.pot,
                to_call_before=obs.to_call,
                all_committed_before=obs.all_committed,
                is_critical=is_crit,
                note=note,
            )

            # Diffuse l'event aux autres players (opp modeling)
            event = ActionEvent(
                actor=current_seat, action=action, stage=obs.stage,
                to_call_before=obs.to_call,
                all_committed_before=list(obs.all_committed),
                big_blind=obs.big_blind,
            )
            for p in seat_players:
                p.observe_action(event)

            obs, current_seat = game.step(action)

        # Fin de main : payoffs et statut
        payoffs = game.payoffs()
        record.payoffs = [float(x) for x in payoffs]
        record.final_status = [p.status.name for p in game.env.game.players]
        logger.write_hand(record)

        # Stats par joueur (selon rotation)
        for seat, payoff in enumerate(payoffs):
            player_idx = seat_to_player[seat]
            stats[player_idx].chips += payoff
            stats[player_idx].chips_sq += payoff * payoff
            stats[player_idx].hands += 1

        if (hand_idx + 1) % max(1, args.hands // 20) == 0:
            elapsed = time.time() - start
            rate = (hand_idx + 1) / elapsed
            print(f"  hand {hand_idx + 1:>5}/{args.hands}  "
                  f"({rate:.1f} hands/s)", flush=True)

    # Summary
    summary = {
        "players": player_names,
        "hands": args.hands,
        "elapsed_sec": time.time() - start,
        "results": [
            {
                "name": s.name,
                "chips": s.chips,
                "bb_per_100": s.bb_per_100,
                "ci95_bb100": s.ci95_bb100,
                "hands": s.hands,
            } for s in stats
        ],
    }
    logger.write_summary(summary)

    print()
    print(f"=== Bilan {args.hands} mains ({time.time()-start:.1f}s) ===")
    for s in stats:
        print(f"  {s.name:<15}  {s.chips:>+8.0f} chips  "
              f"{s.bb_per_100:>+8.2f} bb/100  ±{s.ci95_bb100:.1f}")

    # Rapport détaillé via analyzer
    print()
    meta, hands = load_session(logger.dir)
    # On reporte les leaks DU CHAMPION (seat 1 par convention, mais avec rotation
    # c'est compliqué — pour simplifier on agrège tous les sièges qui ne sont pas pro)
    # Pour ce premier rapport, on indique siège 1
    print(render_report(meta, hands, bot_seat=1))


if __name__ == "__main__":
    main()
