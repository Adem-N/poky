"""
Analyse les logs d'une session pour identifier les forces/faiblesses du bot.

Sortie : rapport human-readable + summary.json. Utilisé après chaque
session longue pour décider quoi améliorer dans le bot.

Heuristiques de "spot leak" :
  - Hands où le bot perd plus de 50% du pot avec des actions définies
    (le pire = "lose stack en se faisant trap")
  - Hands où le bot fold à un 3-bet alors qu'il avait gros investi
  - Hands où le bot bluff river qui se fait call
  - Hands où le bot call river qui perd
"""
import glob
import json
import math
import os
from collections import defaultdict
from typing import Dict, List


def load_session(session_dir: str):
    meta_path = os.path.join(session_dir, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    hands = []
    for p in sorted(glob.glob(os.path.join(session_dir, "hand_*.json"))):
        with open(p, encoding="utf-8") as f:
            hands.append(json.load(f))
    return meta, hands


def per_player_stats(meta: dict, hands: List[dict]) -> List[dict]:
    """Statistiques par seat (indéxé par siège). Pour récupérer les noms
    de joueurs, on regarde meta['players'] (rotation gérée séparément)."""
    if not hands:
        return []
    n = len(hands[0]["payoffs"])
    chips = [0.0] * n
    chips_sq = [0.0] * n
    hands_played = [0] * n
    vpip = [0] * n
    pfr = [0] * n
    bb_value = hands[0].get("starting_stacks", [100] * n)
    # On suppose BB=2 par défaut (rlcard standard)
    big_blind = 2

    for h in hands:
        for seat in range(n):
            chips[seat] += h["payoffs"][seat]
            chips_sq[seat] += h["payoffs"][seat] ** 2
            hands_played[seat] += 1
        # Tracker VPIP/PFR par hand
        vpiped = [False] * n
        pfred = [False] * n
        for a in h["actions"]:
            if a["stage"] != "PREFLOP":
                continue
            actor = a["actor"]
            act = a["action"]
            if act in ("RAISE_HALF_POT", "RAISE_POT", "ALL_IN"):
                if not vpiped[actor]:
                    vpip[actor] += 1
                    vpiped[actor] = True
                if not pfred[actor]:
                    pfr[actor] += 1
                    pfred[actor] = True
            elif act == "CHECK_CALL" and a["to_call_before"] > 0:
                if not vpiped[actor]:
                    vpip[actor] += 1
                    vpiped[actor] = True

    stats = []
    for s in range(n):
        h_count = hands_played[s]
        bb_per_100 = (chips[s] / big_blind) / max(h_count, 1) * 100
        if h_count >= 2:
            mean = chips[s] / h_count
            var = (chips_sq[s] - h_count * mean ** 2) / (h_count - 1)
            stderr = math.sqrt(max(var, 0) / h_count) / big_blind * 100
            ci95 = 1.96 * stderr
        else:
            ci95 = float("inf")
        stats.append({
            "seat": s,
            "hands": h_count,
            "chips": chips[s],
            "bb_per_100": bb_per_100,
            "ci95": ci95,
            "vpip_pct": 100.0 * vpip[s] / max(h_count, 1),
            "pfr_pct": 100.0 * pfr[s] / max(h_count, 1),
        })
    return stats


def leak_patterns(hands: List[dict], bot_seat: int) -> Dict[str, dict]:
    """Identifie les patterns de pertes du bot."""
    patterns = {
        "lost_3bet_pots":    {"count": 0, "loss": 0.0, "ex": []},
        "lost_river_bets":   {"count": 0, "loss": 0.0, "ex": []},
        "folded_3bet_after_open": {"count": 0, "loss": 0.0, "ex": []},
        "big_loss_hands":    {"count": 0, "loss": 0.0, "ex": []},
    }

    for h in hands:
        payoff = h["payoffs"][bot_seat]
        if payoff >= 0:
            continue  # on ne s'intéresse qu'aux pertes

        bot_actions = [(i, a) for i, a in enumerate(h["actions"])
                       if a["actor"] == bot_seat]

        # Pattern : pot 3-bet (au moins 2 raises préflop)
        preflop_raises = sum(1 for a in h["actions"]
                             if a["stage"] == "PREFLOP" and
                             a["action"] in ("RAISE_HALF_POT", "RAISE_POT", "ALL_IN"))
        if preflop_raises >= 2 and any(
                a["stage"] == "PREFLOP" and
                a["action"] in ("RAISE_HALF_POT", "RAISE_POT", "ALL_IN")
                for _, a in bot_actions):
            patterns["lost_3bet_pots"]["count"] += 1
            patterns["lost_3bet_pots"]["loss"] += abs(payoff)
            if len(patterns["lost_3bet_pots"]["ex"]) < 3:
                patterns["lost_3bet_pots"]["ex"].append({
                    "hand_id": h["hand_id"],
                    "holes": h["holes"].get(str(bot_seat)),
                    "payoff": payoff,
                })

        # Pattern : bot bet/raise sur river puis perd
        river_aggressions = [a for _, a in bot_actions
                             if a["stage"] == "RIVER" and
                             a["action"] in ("RAISE_HALF_POT", "RAISE_POT", "ALL_IN")]
        if river_aggressions:
            patterns["lost_river_bets"]["count"] += 1
            patterns["lost_river_bets"]["loss"] += abs(payoff)
            if len(patterns["lost_river_bets"]["ex"]) < 3:
                patterns["lost_river_bets"]["ex"].append({
                    "hand_id": h["hand_id"],
                    "holes": h["holes"].get(str(bot_seat)),
                    "board": h.get("boards"),
                    "payoff": payoff,
                })

        # Pattern : bot ouvre puis fold sur 3-bet
        if bot_actions and preflop_raises >= 2:
            first_bot = bot_actions[0][1]
            if first_bot["action"] in ("RAISE_HALF_POT", "RAISE_POT"):
                later_bot_folds = [a for _, a in bot_actions[1:]
                                   if a["stage"] == "PREFLOP" and
                                   a["action"] == "FOLD"]
                if later_bot_folds:
                    patterns["folded_3bet_after_open"]["count"] += 1
                    patterns["folded_3bet_after_open"]["loss"] += abs(payoff)
                    if len(patterns["folded_3bet_after_open"]["ex"]) < 3:
                        patterns["folded_3bet_after_open"]["ex"].append({
                            "hand_id": h["hand_id"],
                            "holes": h["holes"].get(str(bot_seat)),
                            "payoff": payoff,
                        })

        # Pattern : grosse perte (> 20 chips)
        if payoff <= -20:
            patterns["big_loss_hands"]["count"] += 1
            patterns["big_loss_hands"]["loss"] += abs(payoff)
            if len(patterns["big_loss_hands"]["ex"]) < 5:
                patterns["big_loss_hands"]["ex"].append({
                    "hand_id": h["hand_id"],
                    "holes": h["holes"].get(str(bot_seat)),
                    "board": h.get("boards"),
                    "payoff": payoff,
                })

    return patterns


def critical_spots(hands: List[dict]) -> List[dict]:
    """Liste des décisions flaggées critical_spot par les players (ProClaude)."""
    out = []
    for h in hands:
        for action_idx, a in enumerate(h["actions"]):
            if a.get("is_critical"):
                out.append({
                    "hand_id": h["hand_id"],
                    "action_index": action_idx,
                    "stage": a["stage"],
                    "actor": a["actor"],
                    "action_chosen": a["action"],
                    "pot_before": a["pot_before"],
                    "to_call_before": a["to_call_before"],
                    "note": a.get("note"),
                })
    return out


def render_report(meta: dict, hands: List[dict], bot_seat: int = None) -> str:
    if not hands:
        return "(session vide)"
    lines = []
    lines.append("=" * 72)
    lines.append(f"  SESSION : {meta.get('session_name', '?')}")
    lines.append(f"  {len(hands)} mains  |  joueurs : {meta.get('players', '?')}")
    lines.append("=" * 72)

    stats = per_player_stats(meta, hands)
    lines.append(f"\n{'Siège':<6} {'Joueur':<18} {'Mains':>6} {'Chips':>8} "
                 f"{'bb/100':>10} {'±IC95':>8} {'VPIP%':>8} {'PFR%':>8}")
    lines.append("-" * 72)
    players_names = meta.get("players", [f"P{i}" for i in range(len(stats))])
    for s in stats:
        nm = players_names[s["seat"]] if s["seat"] < len(players_names) else f"?{s['seat']}"
        lines.append(f"{s['seat']:<6} {nm:<18} {s['hands']:>6} "
                     f"{s['chips']:>+8.0f} {s['bb_per_100']:>+10.2f} "
                     f"{s['ci95']:>8.2f} {s['vpip_pct']:>7.1f} {s['pfr_pct']:>7.1f}")

    if bot_seat is not None:
        leaks = leak_patterns(hands, bot_seat)
        lines.append(f"\n--- Leaks du bot (siège {bot_seat}) ---")
        for name, info in leaks.items():
            if info["count"] > 0:
                lines.append(f"  {name:<28} : {info['count']:>4} hands, "
                             f"-{info['loss']:>6.0f} chips total")
                for ex in info["ex"]:
                    lines.append(f"    ex: hand {ex['hand_id']} "
                                 f"holes={ex.get('holes')} payoff={ex['payoff']:+.0f}")

    crit = critical_spots(hands)
    if crit:
        lines.append(f"\n--- Spots critiques (à reviewer) : {len(crit)} ---")
        for c in crit[:10]:
            lines.append(f"  hand {c['hand_id']:>4} action#{c['action_index']:>2} "
                         f"{c['stage']:<8} → {c['action_chosen']:<15} "
                         f"(pot={c['pot_before']}, to_call={c['to_call_before']})")
            if c.get("note"):
                lines.append(f"    note: {c['note']}")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True,
                        help="path/to/data/sessions/<session_name> or just <session_name>")
    parser.add_argument("--bot-seat", type=int, default=None)
    args = parser.parse_args()

    path = args.session
    if not os.path.isdir(path):
        path = os.path.join("data", "sessions", args.session)
    meta, hands = load_session(path)
    print(render_report(meta, hands, bot_seat=args.bot_seat))


if __name__ == "__main__":
    main()
