# État du projet — Poky

Mis à jour : 2026-05-27 (session continue, Phases 1-4 livrées).

## Vue d'ensemble

Bot poker NLHE construit selon un plan en 7 phases (cf `~/.claude/plans/`). Pivot du projet : passé de "bot 42 soutenance" à **personnel long-terme, niveau pro**, ~1-3 mois.

**Architecture cible** : Pluribus-style MCCFR + abstractions + depth-limited subgame solving.

## Avancement par phase

| Phase | Quoi | Statut | Notes |
|---|---|---|---|
| 0 | Foundation (heuristic, arena, baselines) | ✅ Fait | Session 1 |
| **1** | **Postflop equity buckets (K=5/street)** | **✅ Fait** | 7 tests |
| **2** | **Leduc CFR + vanilla + exploitability** | **✅ Fait** | 17 tests, convergence -0.0876 vs -0.0856 ref |
| **3** | **Action abstraction + infoset encoding** | **✅ Fait** | 14 tests |
| **4** | **MCCFR blueprint HU NLHE** | **🚧 MVP** | 12+6+3 tests, hit rate 6.5% à 3k iters, training en cours 30k |
| 5 | Extension blueprint 3-max | ⬜ Pending | Réutilise mccfr_hunl param num_players |
| 6 | Depth-limited subgame solver | ⬜ Pending | LA pièce Pluribus |
| 7 | CFRPlayer prod + verification | 🚧 Partiel | BlueprintPlayer existe, CFRPlayer (avec subgame) reste à faire |

## Tests : 78 passent (43s sans Leduc, +3 min avec)

Suite complète :
```
test_engine.py          3
test_equity.py          7
test_arena.py           3
test_heuristic.py       6
test_archetypes.py      4
test_kuhn_cfr.py        3
test_linear_cfr.py      2
test_preflop_abstraction.py    8
test_postflop_abstraction.py   7
test_leduc_cfr.py      17  ← 3 min de runtime (convergence test)
test_infoset.py        14
test_hunl_state.py     12
test_mccfr_hunl.py      6
test_blueprint_player.py 3
=========================
Total                 95
```

## Architecture fichiers (post Phase 4)

```
poky/
├── engine/                 # rlcard wrapper (typé)
├── equity/                 # phevaluator + MC equity
├── abstraction/            # CARD + ACTION + INFOSET abstractions
│   ├── preflop.py            # 169 classes canoniques, ranked by equity
│   ├── postflop.py           # K=5 buckets/street, déterministe + cache
│   ├── action_abstraction.py # wrapper 5 actions
│   └── infoset.py            # byte-packed keys for strategy storage
├── arena/                  # tournament runner
├── players/                # ALL players
│   ├── base.py
│   ├── random_player.py, call_player.py
│   ├── heuristic.py, adaptive.py    # baselines
│   ├── archetypes.py                 # TAG/LAG/Maniac/Nit
│   ├── human.py                      # CLI
│   ├── nfsp_player.py                # baseline NFSP (déprécié pour ce path)
│   ├── claude_player.py, pro_claude.py  # test opponents
│   └── blueprint_player.py           # ← NEW : consomme MCCFR strategy
├── training/
│   ├── kuhn_cfr.py        # validation algo (vanilla + Linear)
│   ├── leduc_cfr.py       # validation intermédiaire ← NEW
│   ├── hunl_state.py      # pure HU NLHE state ← NEW
│   ├── mccfr_hunl.py      # external-sampling MCCFR ← NEW
│   └── nfsp_train.py      # déprécié
├── cli/                   # entrypoints
│   ├── arena, tournament, compare, nmax_tournament, play, long_session
│   ├── claude_vs_bot, eval_blueprint   ← NEW
│   └── ...
└── logging/
data/
├── blueprint_hu/          # MCCFR HU checkpoints
└── ...
```

## Bilan Phase 4 — MCCFR HU NLHE

**Ce qui marche** :
- Pipeline end-to-end : train → save → load → play in arena
- 105 it/s training (grâce au cache déterministe sur postflop_bucket)
- 79 318 info sets découverts après 3 000 iters
- BlueprintPlayer charge le checkpoint et joue (fallback heuristic si miss)

**Ce qui reste** :
- **Hit rate seulement 6.5%** sur 500 mains d'éval → besoin de :
  - (a) 100k+ itérations de training (au lieu de 3k)
  - (b) Aligner `HUNLState.legal_actions()` ↔ `obs.legal_actions` (rlcard) pour éviter les size-mismatch
- **Performance** : -47 bb/100 vs heuristic à 3k iters. Attendu vu sous-formation.

**Prochaines actions Phase 4 (urgentes)** :
1. Lancer training 100k-500k iters (5-25 min sur laptop) puis ré-évaluer
2. Aligner les legal_actions (refactor)
3. Bench sur 5000 mains pour stat sig.

## Commandes utiles

```powershell
# Activer env
.venv\Scripts\activate

# Suite de tests rapide (sans Leduc 3min)
pytest --ignore=tests/test_leduc_cfr.py

# Entraîner blueprint HU NLHE
python -m poky.training.mccfr_hunl --iterations 30000 --save-path data/blueprint_hu/mvp_30k.pkl

# Évaluer le blueprint vs heuristic HU
python -m poky.cli.eval_blueprint --model data/blueprint_hu/mvp_30k.pkl --hands 500

# Évaluer un Leduc CFR
python -m poky.training.leduc_cfr --iterations 1500
```

## Verification finale (Phase 7, plan)

Quand on aura blueprint + subgame solver, batterie de verification :

```powershell
python -m poky.cli.compare --a cfr --b heuristic --hands 10000   # cible +15 bb/100
python -m poky.cli.compare --a cfr --b adaptive --hands 10000    # cible +8 bb/100
python -m poky.cli.compare --a cfr --b pro_claude --hands 10000  # cible +5 bb/100
python -m poky.cli.tournament --champion cfr --hands 5000        # cible 0 LOSES
python -m poky.cli.nmax_tournament --table cfr,heuristic,heuristic,tag,lag,maniac --hands 5000
```
