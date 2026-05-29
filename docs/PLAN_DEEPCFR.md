# Plan DeepCFR — Bot Nitro pro-grade (DeepCFR maison, 60%+ vs pros)

**Plan actif au 2026-05-29 (succède à PLAN_NITRO.md une fois N5 stabilisé).**

## Contexte

Le bot actuel (N5 livré, 242 tests PASS) bat largement les profils
récréatifs (Nit 80%, TAG 73%, Heuristic 53%) mais **ne bat pas les
opposants push/fold-trained** : vs `ProShortStackPlayer` qui utilise les
mêmes tables Nash que nous, le bot tombe à **31% win rate** (sous baseline
33%). Les observations verbeuses montrent des plays incohérents (fold 44
vs BTN push, call J2o all-in à 9bb) que n'importe quel pro exploite.

**Cible** : un VRAI bot pro-grade qui tient face à des joueurs ayant
étudié push/fold Nash pour 15bb 3-max, win rate ≥ 50% vs Pro-style et
≥ 60% sur le mix moyen-à-bon.

**Pourquoi DeepCFR et pas autre chose** :
- Nash equilibrium est par définition unbeatable → notre plafond théorique
  vs un Nash perfect est 33% (1/N)
- Notre solver actuel (Fictitious Play sur abstraction 169 classes) converge
  vers une approximation imparfaite de Nash → notre stratégie est exploitable
- DeepCFR (Brown et al., 2019) produit une approximation BEAUCOUP plus proche
  du vrai Nash, avec sample-efficient training via neural nets
- Implémentations validées existent (OpenSpiel, Steinberger Deep-CFR)
- C'est l'approche utilisée par Libratus (HU) et Pluribus (6-max)

**Important** : DeepCFR vise un Nash plus proche du vrai. Il ne nous fera pas
gagner +60% vs un PERFECT Nash player (impossible mathématiquement). Mais
il nous fait gagner vs des opposants qui jouent un Nash imparfait — ce que
sont la quasi-totalité des humains, même les pros.

## Architecture cible

```
[Couche 1 : DeepCFR-trained policy (NEW)]                    <- C'est le cœur
       Réseau neuronal entraîné sur 3-max push/fold 15bb
       Input : (stack_bb, scenario, hand_class)
       Output : action distribution (push/call/fold)

       ↓ optionnellement combiné avec ↓

[Couche 2 : exploit overlay si profile connu (existant N5)]
       Si opp classified MANIAC/NIT/etc → micro-adjust

       ↓

[Couche 3 : decision sampling + action mapping (existant N3)]
       Sample from policy, map to rlcard Action

[Couche 4 : postflop heuristic (existant)]
```

**Architecture training (offline)** :

```
[State sampler] → tire un état (cards + position + stacks + history)
        ↓
[Tree traversal] → explore les branches d'action
        ↓
[Regret computation] → calcule le regret de chaque action
        ↓
[Neural net update] → train value net et policy net
        ↓ (loop pour N itérations)
[Final policy net] → fixed, persisted comme .pth checkpoint
```

## Choix techniques

| Décision | Option choisie | Pourquoi |
|---|---|---|
| Framework | **PyTorch** | Mature, GPU-friendly, ecosystem dense |
| DeepCFR impl | **OpenSpiel** (DeepMind) reference | Validated, used by research community |
| Game backend | **OpenSpiel `universal_poker`** | Supports 3-max NLHE natively |
| Training compute | **GPU** (RTX 3060+ local ou cloud A100) | DeepCFR neural training needs GPU |
| Cost | **$50-200** si GPU cloud (vast.ai), $0 si local | Acceptable |
| Action abstraction | **2 actions (push/fold)** initialement | Match Nash table scope ; étendre plus tard |
| Card abstraction | **169 classes préflop** (réutilise notre code) | Cohérent avec stack actuel |
| Iterations target | **10k-50k** CFR iterations | Standard pour push/fold; ~5-20h GPU |

**Pourquoi OpenSpiel et pas re-implémenter** : DeepCFR a 12+ pièges
subtils (sampling distribution, advantage memory, target network update,
exploitability tracking, etc.). Réimplémenter from-scratch = 2 mois.
OpenSpiel = 1-2 semaines pour l'intégration.

## Phases d'implémentation

### Phase D0 — Setup environnement (3-5 jours)

**Livrables** :
- Vérifier ou installer PyTorch + CUDA (GPU local ou cloud)
- `pip install open_spiel` (binding Python d'OpenSpiel)
- `deepcfr-poky/` nouveau venv séparé (PyTorch a beaucoup de deps)
- Smoke test : `python -c "import pyspiel; print(pyspiel.universal_poker)"`
- Smoke test : load un game NLHE 3-max via universal_poker, jouer 1 main
  random pour vérifier que le moteur tourne

**Critère go/no-go** :
- ✅ pyspiel importe sans erreur sur Windows Python 3.14 (ou Linux/WSL si
  Windows pose problème)
- ✅ NLHE 3-max universal_poker game tournable
- ❌ Si pyspiel ne build pas sur notre OS : pivot vers Steinberger/Deep-CFR
  (pure Python, plus simple mais moins validé)

### Phase D1 — Adapter le game pour 3-max push/fold 15bb (5-7 jours)

**Livrables** :
- `deepcfr/game_config.py` : ACPC game definition pour 3-max NLHE
  - 3 players
  - Starting stacks variables (~5-15bb per training run)
  - Action abstraction : limite à FOLD + ALL_IN (pas de raise sizings, comme nos Nash tables)
  - Card abstraction : 169 préflop classes via custom info_state_string
- `deepcfr/bucket_state.py` : map full game state → bucketed info state
  (réutilise `poky/abstraction/preflop.py`)
- Tests : 3 SnG hands joués, info_state encoding correct

**Critère go/no-go** :
- ✅ Game tournable avec abstraction 169 + 2 actions
- ✅ Exploitability initial calculable (avant training)

### Phase D2 — DeepCFR training pipeline (7-10 jours)

**Livrables** :
- `deepcfr/train.py` : utilise `pyspiel.deep_cfr` ou implémentation OpenSpiel
- Pipeline d'entraînement avec checkpoints periodiques
- Tracking de l'exploitability au fil des itérations
- Sauvegarde du policy net entraîné

**Hyperparamètres à explorer** :
- Iterations : 1k → 5k → 20k → 50k
- Advantage memory size : 1M-10M states
- Strategy memory size : 1M-10M
- Neural net architecture : 3-5 layers, 64-256 units
- Learning rate : 1e-4 to 1e-3
- Batch size : 256-2048

**Critère go/no-go** :
- ✅ Exploitability descend sous 30 mBB/h après 10k iters
- ✅ Policy net sample produit des actions cohérentes avec Nash publié

### Phase D3 — Eval vs baselines (5 jours)

**Livrables** :
- `deepcfr/eval.py` : load policy net + jouer vs baselines
- Bench complet :
  - vs Pure Nash (notre `ProShortStackPlayer`) : cible ≥ 35% win rate
  - vs Old NitroPlayer (le bot actuel) : cible ≥ 45% win rate
  - vs Self-play : cible 33% par seat (symétrie)
  - vs Random/Maniac : cible ≥ 50% (must not regress)
- Comparaison side-by-side : Old NitroPlayer vs DeepCFR-NitroPlayer
  sur les 6 archétypes

**Critère go/no-go FINAL** :
- ✅ vs ProShortStackPlayer ≥ 40% (vs current 31%) → on a passé le Nash gap
- ✅ Conservé ou amélioré les autres baselines (Heuristic ≥ 50%, TAG ≥ 70%)

### Phase D4 — Integration NitroPlayer (5 jours)

**Livrables** :
- `poky/players/nitro_player.py` : nouveau paramètre `use_deepcfr: bool`
- Quand `True` : query le policy net au lieu de Nash table lookup
- Garder option fallback Nash si DeepCFR pas chargé
- `data/deepcfr/policy.pth` : checkpoint final
- Documentation du nouveau workflow

**Tests** :
- NitroPlayer avec DeepCFR loaded passe tous les tests existants (243+)
- Bench final 6 archétypes avec DeepCFR ON vs OFF

## Budget temps + compute

| Phase | Effort actif | Compute |
|---|---|---|
| D0 Setup | 3-5 jours | 0 |
| D1 Adapt game | 5-7 jours | 0 |
| D2 Training pipeline | 7-10 jours | ~5-20h GPU |
| D3 Eval | 5 jours | 0 |
| D4 Integration | 5 jours | 0 |
| **Total** | **5-6 semaines actives** | **$50-200 si GPU cloud** |

Avec compute local (RTX 3060+) : $0. Avec vast.ai A100 ($1/h) pour 20h
training : $20. Confortable.

## Critères de succès

**DeepCFR réussi si TOUS les critères passent** :

1. **Tests** : 250+ passing (242 actuels + nouveaux DeepCFR tests)
2. **Vs ProShortStackPlayer** : ≥ 40% win rate (vs 31% actuellement) sur 200 SnGs
3. **Vs HeuristicPlayer** : ≥ 50% maintenu (pas de régression vs 53% actuel)
4. **Vs TAG** : ≥ 65% maintenu (vs 73% actuel — possible légère baisse car
   DeepCFR est moins agressif vs sub-optimal)
5. **Vs LAG** : ≥ 45% (vs 42% actuel)
6. **Vs Nit** : ≥ 75% (vs 80% actuel)
7. **Self-play** : 33% ± 5% par seat (test de symétrie Nash)
8. **Exploitability** : < 30 mBB/h sur l'abstraction (mesurable via OpenSpiel)

**Cible utilisateur final 60% avg vs decent opps** :
- Avg {Heuristic 50, TAG 65, LAG 45} = 53.3% → encore court
- MAIS la principale victoire = passer de 31% → 40-45% vs Pro
- C'est LA différence pour la soirée vs "real pros"

**Réalité brutale (à mentionner au user)** :
- Vs un parfait Nash player, on PLAFONNE à 33% par symétrie
- DeepCFR aide à se rapprocher de Nash, pas à le dépasser
- Pour dépasser 60% vs pros, faut soit :
  - Population-specific exploits (nécessite >100h de data par opp pool)
  - Pluribus-style search at runtime (10x compute, beaucoup plus complexe)

## Risques et mitigations

| Risque | Probabilité | Mitigation |
|---|---|---|
| pyspiel ne build pas sur Windows Python 3.14 | Élevée | Fallback : Linux/WSL2, ou Steinberger Deep-CFR pure-Python |
| Training instable (exploitability ne descend pas) | Moyenne | Multiple seeds + hyperparam tuning ; OpenSpiel impl est robust |
| Compute trop long ou trop cher | Faible | Cap iterations à 20k ; vast.ai spot instances |
| Performance gain marginal (DeepCFR ≈ FP) | Élevée | Mesurer exploitability ; si pas d'amélioration, raison architecturale |
| Integration breaks existing tests | Moyenne | use_deepcfr flag par défaut OFF, opt-in |

## Vérification end-to-end

```powershell
# 1. Setup DeepCFR env
cd deepcfr-poky
.\venv\Scripts\activate
python -c "import pyspiel; import torch; print(torch.cuda.is_available())"

# 2. Run training
python -m deepcfr.train --iters 10000 --save-dir checkpoints/

# 3. Monitor exploitability
tensorboard --logdir runs/

# 4. Eval
python -m deepcfr.eval --policy checkpoints/iter_10000.pth --opp pro_shortstack --sngs 200
# Cible : ≥ 40% win rate

# 5. Full bench (after D4)
python scripts/bench_nitro.py --sngs 200 --opp pro_shortstack --use-deepcfr
python scripts/bench_nitro.py --sngs 200 --opp heuristic --use-deepcfr
# ... pour tous les archétypes
```

## Fichiers à créer

```
deepcfr-poky/                       # Nouveau sibling de Poky/ (séparé pour PyTorch deps)
├── venv/                          # PyTorch + OpenSpiel
├── requirements.txt
├── deepcfr/
│   ├── __init__.py
│   ├── game_config.py             # 3-max 15bb push/fold game definition
│   ├── bucket_state.py            # 169-class abstraction wrapper
│   ├── train.py                   # DeepCFR training pipeline
│   ├── eval.py                    # Eval vs baselines
│   └── policy_loader.py           # Load .pth + sample from net
├── checkpoints/
│   └── iter_*.pth                 # Trained policy nets (.gitignored — large)
├── runs/                          # TensorBoard logs
└── tests/
    ├── test_game_config.py
    ├── test_bucket_state.py
    └── test_policy_loader.py

# Poky/ (existing repo) :
├── poky/players/nitro_player.py   # Modify : add use_deepcfr flag + DeepCFRPolicy
├── data/deepcfr/                  # New : .pth checkpoints (gitignored)
└── docs/PLAN_DEEPCFR.md           # This file
```

## Notes spéciales

**Pourquoi un sibling repo `deepcfr-poky/` et pas dans Poky** :
- PyTorch + CUDA deps sont lourdes (~3 GB), polluent l'env actuel
- Training peut tourner sur un autre OS/machine sans toucher Poky
- Le checkpoint final (.pth) est petit (~10 MB), importable dans Poky

**Pourquoi 2 actions (push/fold) et pas full sizings** :
- Notre Nash tables actuelles sont push/fold only — mismatch dangereux sinon
- Training avec full action space = 100-1000x plus de compute
- Au stack 15bb réel, push/fold capture 95% de l'edge ; sizing minor

**Path alternative** : si DeepCFR via OpenSpiel échoue (build, compute, etc.),
fallback sur **Sauce123's published Nash charts** importés directement via
JSON. Ce sont des solves DeepCFR-equivalent déjà faits, accessibles via
upswingpoker / push72o / coaching sites. Trade-off : pas d'apprentissage,
mais qualité Nash garantie.

## Calendrier réaliste

- **Semaine 1** : D0 + start D1
- **Semaine 2-3** : D1 complet + start D2
- **Semaine 4** : D2 training (compute long, dev fait)
- **Semaine 5** : D3 eval
- **Semaine 6** : D4 integration + bench finaux

**Total : 6 semaines** pour passer du bot actuel à un bot pro-grade
mesurablement meilleur vs Nash-style opponents.

---

## Conditions de lancement

Le user doit d'abord confirmer :
1. **Budget temps** : 6 semaines de dev actif (1-2h/jour minimum)
2. **Budget compute** : $50-200 si pas de GPU local
3. **Risque accepté** : DeepCFR peut ne pas livrer +30% win rate vs Pro
   (peut livrer "seulement" +10% — c'est déjà énorme mais en-deçà des
   espoirs)
4. **OS** : prêt à utiliser WSL2 ou Linux si pyspiel ne build pas Windows

Si tous OUI → on lance D0 dans la prochaine session.
