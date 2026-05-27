# Poky

Bot de poker No-Limit Texas Hold'em 3-max, conçu pour jouer de manière autonome sur une plateforme à argent virtuel (projet libre IA — 42 Paris).

## Objectif

Construire un bot suffisamment fort pour battre un joueur humain (le juge en soutenance) en NLHE 3-max, en s'appuyant sur :

1. Une **stratégie pré-calculée par CFR** (Counterfactual Regret Minimization) — base académique des bots qui ont battu les pros humains (Libratus 2017, Pluribus 2019).
2. Un **moteur d'évaluation** et un **harnais de simulation** pour mesurer rigoureusement la qualité du bot face à des adversaires baseline.
3. Un **adaptateur** vers la plateforme cible.

## Stack

- **rlcard** — moteur de jeu NLHE multi-joueurs + agents RL (CFR, Deep CFR, DMC, NFSP)
- **phevaluator** — évaluation 5/7-cartes en ~100 ns (Cactus Kev en C)
- **PyTorch** — pour Deep CFR / DMC
- **numpy / matplotlib** — math et plots
- **pytest** — tests

## Structure

```
Poky/
├── legacy/                  # ancien code CLI préservé (référence uniquement)
├── poky/
│   ├── engine/              # wrapper rlcard : Observation, Action, Game (API stable)
│   ├── equity/              # phevaluator + Monte Carlo equity
│   ├── players/             # Random, AlwaysCall, Heuristic, HumanCLI
│   ├── arena/               # runner bot-vs-bot avec stats (bb/100, IC95%)
│   ├── training/            # CFR : Kuhn validé, NLHE à venir
│   ├── abstraction/         # buckets de cartes (à venir)
│   ├── platform_adapter/    # client réseau plateforme 42 (à venir, attend spec)
│   └── cli/                 # entrypoints : play, arena
├── tests/                   # 22 tests pytest, tous verts
├── docs/                    # plots, doc soutenance
├── data/                    # stratégies entraînées (à venir)
└── requirements.txt
```

## Démarrage

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pytest                           # 22 tests doivent passer
```

## Commandes utiles

### Sparring : toi contre le bot
```bash
python -m poky.cli.play                                    # 20 mains vs heuristic,heuristic
python -m poky.cli.play --opponents heuristic,call         # mix d'adversaires
python -m poky.cli.play --hands 100 --seed 42              # reproductible
python -m poky.cli.play --hands 0                          # illimité (Ctrl+C)
```

### Arène : bots les uns contre les autres
```bash
python -m poky.cli.arena --players heuristic,random,call --hands 2000
python -m poky.cli.arena --players heuristic,heuristic,heuristic --hands 5000  # self-play
```

### Tournament : champion vs gauntlet d'archétypes humains (3-max)
```bash
python -m poky.cli.tournament --champion heuristic --hands 2500
python -m poky.cli.tournament --champion adaptive --hands 2500    # adaptive avec opp. modeling
python -m poky.cli.tournament --champion nfsp --hands 3000        # après entraînement
```

### Tournament N-max : tables 6-max / 9-max / compositions custom
```bash
python -m poky.cli.nmax_tournament --table adaptive,adaptive,adaptive,tag,lag,maniac --hands 1500
python -m poky.cli.nmax_tournament --table heuristic,heuristic,random,random,call,call --hands 2000
```
Permet de mettre **plusieurs instances** du bot à la même table (elles sont indépendantes,
chacune avec son propre tracker d'adversaires et son seed RNG).

### Comparaison de deux champions
```bash
python -m poky.cli.compare --a heuristic --b adaptive --hands 2500
```

### Entraînement CFR / NFSP
```bash
# Validation sur Kuhn poker (toy game) — converge vers -1/18 (Nash analytique)
python -m poky.training.kuhn_cfr --iterations 20000

# Plot de convergence Kuhn (soutenance)
python -m poky.training.plot_kuhn --out docs/kuhn_convergence.png

# Entraînement NFSP sur NLHE 3-max (~48 ep/s sur CPU)
python -m poky.training.nfsp_train --episodes 30000   # ~10 min
python -m poky.training.nfsp_train --episodes 200000  # ~1h, qualité production
```
Le modèle se sauve dans `data/nfsp_3max/` et est consommé automatiquement par
`NFSPPlayer` qu'on injecte dans le tournament.

## Résultats actuels (sanity checks)

Sur 2000 mains, 3-max, blinds 1/2, stack 100 :

| Match | bb/100 du joueur 1 | IC95% |
|---|---|---|
| heuristic vs random vs call | **+210** | ±82 |
| call vs random vs random | +239 | ±218 |
| heuristic self-play (rotation) | ~0 | ±47 |

Le HeuristicPlayer écrase nettement les baselines. Self-play est dans le bruit → pas d'exploit positionnel résiduel.

## CFR : validation sur Kuhn poker

Vanilla CFR sur Kuhn poker (jeu jouet à 3 cartes, équilibre de Nash connu analytiquement) :

- Valeur du jeu pour J1 obtenue : **-0.056** vs Nash analytique **-1/18 ≈ -0.0556** (écart 0.001)
- Stratégies pures (toujours bet K, toujours check Q, etc.) : conformes à 99%+
- Fréquences mixtes (J2 bet J = 1/3, J2 call Q = 1/3) : conformes à ±5%

Voir `docs/kuhn_convergence.png` pour le plot.

## Prochaines étapes

Voir [docs/STATUS.md](docs/STATUS.md) pour le détail et la reprise du travail.

## Références académiques

- Kuhn, H. W. 1950. *A simplified two-person poker.*
- Zinkevich et al. 2007. *Regret Minimization in Games with Incomplete Information.*
- Lanctot et al. 2009. *Monte Carlo Sampling for Regret Minimization in Extensive Games.*
- Brown & Sandholm 2017. *Libratus: The Superhuman AI for No-Limit Poker.*
- Brown et al. 2019. *Deep Counterfactual Regret Minimization.*
- Brown & Sandholm 2019. *Superhuman AI for multiplayer poker* (Pluribus, 6-max NLHE).
- Zha et al. 2020. *RLCard: A Platform for Reinforcement Learning in Card Games.*
