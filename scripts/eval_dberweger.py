"""Eval DBerwegerPlayer vs HeuristicPlayer en 6-max.

Usage:
    python scripts/eval_dberweger.py --hands 100     # sanity test
    python scripts/eval_dberweger.py --hands 5000    # Y0bis.6 GO/NO-GO
"""
import argparse
import sys
import time

from poky.arena import run_match
from poky.external.dberweger_player import DBerwegerPlayer
from poky.players import HeuristicPlayer


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-opp", type=int, default=5,
                    help="Nombre de HeuristicPlayer adversaires (table = 1+n).")
    ap.add_argument("--sample", action="store_true", default=True,
                    help="Sample stochastique de l'action (défaut True).")
    ap.add_argument("--argmax", action="store_false", dest="sample",
                    help="Argmax déterministe au lieu de sample.")
    ap.add_argument("--ckpt", type=str, default=None)
    args = ap.parse_args()

    print(f"DBerweger vs {args.n_opp}× HeuristicPlayer  ({1+args.n_opp}-max, "
          f"{args.hands} mains, seed={args.seed}, sample={args.sample})")
    print("Chargement du checkpoint…", flush=True)
    t0 = time.time()
    champion = DBerwegerPlayer(checkpoint_path=args.ckpt, sample=args.sample, seed=args.seed)
    print(f"  loaded in {time.time()-t0:.2f}s", flush=True)

    opponents = [HeuristicPlayer(seed=2000+i) for i in range(args.n_opp)]
    players = [champion] + opponents

    print(f"Lancement match…", flush=True)
    t0 = time.time()
    result = run_match(players, hands=args.hands, seed=args.seed)
    dt = time.time() - t0
    print(f"  done in {dt:.1f}s ({args.hands/dt:.1f} hands/s)\n", flush=True)

    print(result.summary())
    print()

    # Verdict explicite pour DBerweger.
    bb = result.stats[0].bb_per_100
    ci = result.stats[0].ci95_bb100
    if bb - ci > 30:
        verdict = "GO STRONG (bat HeuristicPlayer de +30 bb/100 minimum, critère Y0bis OK)"
    elif bb - ci > 0:
        verdict = "BEATS mais pas franc (entre 0 et +30 bb/100 — sous le seuil Y0bis)"
    elif bb + ci < 0:
        verdict = "LOSES (HeuristicPlayer domine — NO-GO Y0bis)"
    else:
        verdict = "DRAW (statistiquement indistinct de 0 — NO-GO Y0bis)"
    print(f"VERDICT DBerweger : {verdict}")
    print(f"  bb/100 = {bb:+.2f}  ±IC95 = {ci:.2f}")


if __name__ == "__main__":
    main()
