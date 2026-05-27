"""
Génère un plot de convergence du CFR sur Kuhn pour la soutenance.

  python -m poky.training.plot_kuhn --out docs/kuhn_convergence.png
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")  # backend sans display
import matplotlib.pyplot as plt

from poky.training.kuhn_cfr import KuhnCFRTrainer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--out", default="docs/kuhn_convergence.png")
    args = parser.parse_args()

    trainer = KuhnCFRTrainer()
    history = trainer.train(args.iterations)

    expected = -1.0 / 18

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(range(1, len(history) + 1), history, label="Valeur courante (CFR)", linewidth=1.5)
    ax.axhline(expected, color="red", linestyle="--",
               label=f"Nash analytique (-1/18 ≈ {expected:.4f})")
    ax.set_xlabel("Itération CFR")
    ax.set_ylabel("Valeur du jeu pour J1")
    ax.set_title("Convergence du vanilla CFR sur Kuhn poker")
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_xscale("log")
    fig.tight_layout()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=120)
    print(f"Plot écrit : {args.out}")
    print(f"Valeur finale : {history[-1]:+.5f}  |  Nash : {expected:+.5f}  |  "
          f"écart : {abs(history[-1] - expected):.5f}")


if __name__ == "__main__":
    main()
