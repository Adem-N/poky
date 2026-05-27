"""
Entraînement NFSP (Neural Fictitious Self-Play) sur NLHE 3-max.

NFSP — Heinrich & Silver 2016. C'est l'algo qui a démontré le premier la
convergence vers un équilibre approximatif sur Leduc poker via deep learning,
puis a été étendu à NLHE par des successeurs (DeepStack, Libratus).

Principe : 3 agents (un par siège) jouent les uns contre les autres. Chacun
apprend en parallèle :
  - une politique d'**average response** par supervised learning (le but ultime,
    converge vers l'équilibre)
  - une politique de **best response** par DQN (utile au cours de l'apprentissage)
Le paramètre `anticipatory_param` mixe les deux pendant l'auto-jeu.

  python -m poky.training.nfsp_train --episodes 5000 --save-every 1000
  python -m poky.training.nfsp_train --episodes 50000 --device cpu      # entraînement long

Le résultat va dans data/nfsp_3max/ : un .pth par agent.
"""
import argparse
import os
import sys
import time

import torch
import rlcard
from rlcard.agents import NFSPAgent, RandomAgent
from rlcard.utils import tournament, reorganize


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


def make_env(num_players=3, seed=0):
    return rlcard.make("no-limit-holdem", config={
        "game_num_players": num_players,
        "seed": seed,
    })


def build_agents(env, device, hidden_layers=(256, 256),
                 rl_lr=0.0005, sl_lr=0.005,
                 q_replay_size=100_000, min_buffer=5000,
                 anticipatory=0.1):
    """Crée un agent NFSP par siège. Tous partagent la même architecture.

    Hyperparamètres par défaut CORRIGÉS suite à échec 200k :
      - rl_lr=0.0005 (au lieu du default rlcard 0.1, trop élevé)
      - q_replay_size=100k (au lieu de 20k default)
      - min_buffer=5000 (au lieu de 100 default) : démarrer l'apprentissage
        seulement après un buffer significatif → stabilité
    """
    agents = []
    for player_id in range(env.num_players):
        agent = NFSPAgent(
            num_actions=env.num_actions,
            state_shape=env.state_shape[player_id],
            hidden_layers_sizes=list(hidden_layers),
            q_mlp_layers=list(hidden_layers),
            rl_learning_rate=rl_lr,
            sl_learning_rate=sl_lr,
            anticipatory_param=anticipatory,
            q_replay_memory_size=q_replay_size,
            q_replay_memory_init_size=min_buffer,
            min_buffer_size_to_learn=min_buffer,
            device=device,
        )
        agents.append(agent)
    return agents


def evaluate_vs_random(env, champion_agent, hands=500, seed=999):
    """Mesure rapide : champion vs 2 randoms."""
    eval_env = make_env(num_players=env.num_players, seed=seed)
    agents = [champion_agent, RandomAgent(num_actions=env.num_actions),
              RandomAgent(num_actions=env.num_actions)]
    eval_env.set_agents(agents)
    payoffs = tournament(eval_env, hands)
    return payoffs[0]  # gain moyen par main de notre champion


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=5000)
    parser.add_argument("--save-every", type=int, default=1000)
    parser.add_argument("--eval-every", type=int, default=500)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--save-dir", default="data/nfsp_3max")
    parser.add_argument("--num-players", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rl-lr", type=float, default=0.0005,
                        help="RL learning rate (default fixé bas pour stabilité)")
    parser.add_argument("--sl-lr", type=float, default=0.005)
    parser.add_argument("--anticipatory", type=float, default=0.1)
    args = parser.parse_args()

    os.makedirs(args.save_dir, exist_ok=True)
    device = torch.device(args.device)

    print(f"NFSP training : {args.episodes} épisodes, "
          f"{args.num_players} joueurs, device={device}")
    print(f"Checkpoints : {args.save_dir}/")

    env = make_env(num_players=args.num_players, seed=args.seed)
    agents = build_agents(env, device=device,
                          rl_lr=args.rl_lr, sl_lr=args.sl_lr,
                          anticipatory=args.anticipatory)
    env.set_agents(agents)
    print(f"Hyperparams : rl_lr={args.rl_lr}  sl_lr={args.sl_lr}  "
          f"anticipatory={args.anticipatory}")

    start = time.time()
    last_eval_payoff = None

    for episode in range(1, args.episodes + 1):
        # Auto-jeu d'une main complète
        trajectories, payoffs = env.run(is_training=True)
        # Convertit trajectoires brutes [s0,a0,s1,a1,...,sn] en
        # transitions complètes (state, action, reward, next_state, done)
        trajectories = reorganize(trajectories, payoffs)
        # Feed des transitions aux agents pour apprentissage
        for player_id in range(args.num_players):
            for trans in trajectories[player_id]:
                agents[player_id].feed(trans)

        # Eval périodique vs random — métrique grossière mais rapide
        if episode % args.eval_every == 0:
            payoff = evaluate_vs_random(env, agents[0], hands=300, seed=args.seed + episode)
            last_eval_payoff = payoff
            elapsed = time.time() - start
            rate = episode / elapsed
            print(f"  ep {episode:>6} | {rate:>5.1f} ep/s | "
                  f"vs random : {payoff:+7.3f} chips/main", flush=True)

        # Checkpoints
        if episode % args.save_every == 0:
            for i, agent in enumerate(agents):
                path = os.path.join(args.save_dir, f"agent_{i}_ep{episode}.pth")
                torch.save(agent, path)
            # Pointeur "latest" pour faciliter le chargement
            for i, agent in enumerate(agents):
                latest_path = os.path.join(args.save_dir, f"agent_{i}_latest.pth")
                torch.save(agent, latest_path)
            print(f"  → checkpoint sauvé (ep {episode})", flush=True)

    # Sauvegarde finale
    for i, agent in enumerate(agents):
        path = os.path.join(args.save_dir, f"agent_{i}_final.pth")
        torch.save(agent, path)
        latest_path = os.path.join(args.save_dir, f"agent_{i}_latest.pth")
        torch.save(agent, latest_path)

    total = time.time() - start
    print(f"\nTerminé en {total/60:.1f} min.")
    print(f"Modèles dans : {args.save_dir}/agent_*_latest.pth")
    if last_eval_payoff is not None:
        print(f"Dernier eval vs random : {last_eval_payoff:+.3f} chips/main")


if __name__ == "__main__":
    main()
