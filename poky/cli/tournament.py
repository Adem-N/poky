"""
Tournament CLI : fait jouer un bot champion contre toutes les baselines
et produit un rapport de leaderboard.

  python -m poky.cli.tournament                            # heuristic vs tout, 2000 mains
  python -m poky.cli.tournament --champion heuristic --hands 4000
  python -m poky.cli.tournament --champion tag             # changer le champion

C'est l'outil que j'utilise à chaque itération pour mesurer si le bot
progresse. Un bot qui "bat n'importe qui" doit afficher BEATS sur
TOUTES les lignes.
"""
import argparse
import os
import sys

from poky.arena import run_match
from poky.arena.runner import PlayerStats
from poky.players import (
    RandomPlayer, AlwaysCallPlayer, HeuristicPlayer,
    TightPassivePlayer, TightAggressivePlayer,
    LooseAggressivePlayer, ManiacPlayer, NFSPPlayer, ClaudePlayer,
    AdaptiveHeuristicPlayer,
)


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def _nfsp_factory(i):
    """Charge le NFSP entraîné. Préfère le 200k s'il existe, sinon le 30k."""
    candidates = [
        os.path.join("data", "nfsp_3max_200k", "agent_0_latest.pth"),
        os.path.join("data", "nfsp_3max", "agent_0_latest.pth"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return NFSPPlayer(model_path=path, fallback_seed=7000 + i)
    raise SystemExit(
        "NFSP non entraîné. Lance d'abord :\n"
        "  python -m poky.training.nfsp_train --episodes 200000"
    )


PLAYER_FACTORY = {
    "random":         lambda i: RandomPlayer(seed=1000 + i),
    "call":           lambda i: AlwaysCallPlayer(),
    "heuristic":      lambda i: HeuristicPlayer(seed=2000 + i),
    "tight_passive":  lambda i: TightPassivePlayer(seed=3000 + i),
    "tag":            lambda i: TightAggressivePlayer(seed=4000 + i),
    "lag":            lambda i: LooseAggressivePlayer(seed=5000 + i),
    "maniac":         lambda i: ManiacPlayer(seed=6000 + i),
    "nfsp":           _nfsp_factory,
    "claude":         lambda i: ClaudePlayer(seed=9000 + i),
    "adaptive":       lambda i: AdaptiveHeuristicPlayer(seed=8000 + i),
}


# La gauntlet : matchups à tester. Format : (label, list[opponent_names])
# Tous les matchups sont 3-max donc 2 adversaires.
DEFAULT_GAUNTLET = [
    ("vs random,random",         ["random", "random"]),
    ("vs call,call",             ["call", "call"]),
    ("vs tight_passive ×2",      ["tight_passive", "tight_passive"]),
    ("vs tag ×2",                ["tag", "tag"]),
    ("vs lag ×2",                ["lag", "lag"]),
    ("vs maniac ×2",             ["maniac", "maniac"]),
    ("vs tag + lag",             ["tag", "lag"]),
    ("vs maniac + tight_passive", ["maniac", "tight_passive"]),
    ("vs tag + maniac",          ["tag", "maniac"]),
]


def verdict(stats: PlayerStats) -> str:
    """BEATS si bb/100 - IC95 > 0, LOSES si bb/100 + IC95 < 0, sinon DRAW."""
    bb = stats.bb_per_100
    ci = stats.ci95_bb100
    if bb - ci > 0:
        return "BEATS"
    if bb + ci < 0:
        return "LOSES"
    return "DRAW"


def run_tournament(champion_name: str, hands: int, seed_base: int,
                   gauntlet=None) -> list:
    """Joue chaque matchup, renvoie une liste de (label, stats du champion)."""
    if gauntlet is None:
        gauntlet = DEFAULT_GAUNTLET

    results = []
    for matchup_idx, (label, opp_names) in enumerate(gauntlet):
        champion = PLAYER_FACTORY[champion_name](0)
        opponents = [PLAYER_FACTORY[n](i + 1) for i, n in enumerate(opp_names)]
        players = [champion] + opponents
        match_seed = seed_base + matchup_idx * 10_000
        res = run_match(players, hands=hands, seed=match_seed)
        champion_stats = res.stats[0]
        results.append((label, champion_stats))
        # Affichage progressif pour suivre en live
        v = verdict(champion_stats)
        print(f"  [{matchup_idx + 1}/{len(gauntlet)}] {label:<32} → "
              f"{champion_stats.bb_per_100:+8.2f} bb/100 ±{champion_stats.ci95_bb100:5.2f}  "
              f"[{v}]")
    return results


def render_report(champion_name: str, hands: int, results: list) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append(f"  TOURNOI Poky — champion : {champion_name}  ({hands} mains / matchup)")
    lines.append("=" * 72)
    lines.append(f"  {'Matchup':<34} {'bb/100':>10} {'±IC95':>8} {'Verdict':>8}")
    lines.append("-" * 72)
    scores = {"BEATS": 0, "DRAW": 0, "LOSES": 0}
    for label, stats in results:
        v = verdict(stats)
        scores[v] += 1
        lines.append(
            f"  {label:<34} {stats.bb_per_100:>+10.2f} {stats.ci95_bb100:>8.2f} {v:>8}"
        )
    lines.append("-" * 72)
    lines.append(f"  Bilan : {scores['BEATS']} BEATS  /  "
                 f"{scores['DRAW']} DRAW  /  {scores['LOSES']} LOSES")
    lines.append("=" * 72)
    # Verdict global
    if scores["LOSES"] > 0:
        glob = "BOT EXPLOITÉ — il y a des matchups qu'il PERD. À corriger en priorité."
    elif scores["DRAW"] > 0:
        glob = "BOT CORRECT mais pas dominant partout. Améliorations possibles."
    else:
        glob = "BOT DOMINANT : bat tous les archétypes de manière significative."
    lines.append(f"  → {glob}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Tournoi du champion vs gauntlet.")
    parser.add_argument("--champion", default="heuristic",
                        choices=list(PLAYER_FACTORY))
    parser.add_argument("--hands", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Démarrage du tournoi : {args.champion} vs gauntlet ({args.hands} mains × "
          f"{len(DEFAULT_GAUNTLET)} matchups)\n")
    results = run_tournament(args.champion, args.hands, args.seed)
    print()
    print(render_report(args.champion, args.hands, results))


if __name__ == "__main__":
    main()
