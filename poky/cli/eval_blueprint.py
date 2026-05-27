"""
Évaluation rapide d'un BlueprintPlayer entraîné, en heads-up.

  python -m poky.cli.eval_blueprint --model data/blueprint_hu/mvp_3k.pkl --hands 1000

Sortie : bb/100 + IC95 du Blueprint vs Heuristic + hit rate des lookups.
"""
import argparse
import os
import sys

from poky.arena import run_match
from poky.players import BlueprintPlayer, HeuristicPlayer, RandomPlayer


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True,
                        help="path/to/mccfr_checkpoint.pkl")
    parser.add_argument("--hands", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--opponent", default="heuristic",
                        choices=["heuristic", "random"])
    args = parser.parse_args()

    if not os.path.exists(args.model):
        raise SystemExit(f"Modèle absent : {args.model}")

    bp = BlueprintPlayer(model_path=args.model, fallback_seed=42, sample_seed=42)
    opp_factory = {
        "heuristic": lambda: HeuristicPlayer(seed=1),
        "random": lambda: RandomPlayer(seed=1),
    }[args.opponent]
    opp = opp_factory()

    print(f"Eval BlueprintPlayer ({args.model}) vs {args.opponent} "
          f"sur {args.hands} mains heads-up")
    res = run_match([bp, opp], hands=args.hands, seed=args.seed)
    print()
    print(res.summary())
    print()
    print(f"Blueprint hit rate : {bp.hit_rate*100:.1f}% "
          f"({bp._lookup_hits} hits / {bp._lookup_hits + bp._lookup_misses} décisions)")
    print(f"Info sets dans le model : {len(bp.trainer.regret_sum):,}")
    print(f"Iterations training : {bp.trainer.iterations_done:,}")


if __name__ == "__main__":
    main()
