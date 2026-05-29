# Plan ML Pro Bot — DeepCFR + Opponent Embedding

**Plan actif au 2026-05-29.** Succède à PLAN_NITRO.md (livré jusqu'à N5).

## Contexte (résumé pour fresh-context-me)

Le bot actuel (Nitro 3-max 15bb, dans `poky/`) bat les récréatifs (Heuristic
53%, Nit 80%, TAG 73%) mais **NE BAT PAS** des opposants push/fold-trained :
vs `ProShortStackPlayer` (qui utilise les mêmes tables Nash sans exploits),
on tombe à **31% win rate** (sous baseline 33.3%).

Diagnostic : notre Nash solver (Fictitious Play sur abstraction 169-classes)
converge vers une approximation imparfaite de Nash. Les Pros le repèrent en
3-5 mains et nous exploitent.

**Objectif** : ML-driven bot capable de :
1. Tenir face à des Pros (≥ 40% win rate vs ProShortStackPlayer)
2. S'adapter aux comportements observés (au-delà des 7 archétypes hardcodés actuels)

**Deux briques ML** combinées :
- **Phase D** : DeepCFR pour apprendre une stratégie quasi-Nash via neural net
- **Phase E** : Opponent Embedding pour profiler les opps via deep learning au lieu de seuils hardcodés

## Architecture cible (vision finale)

```
                     [NitroPlayer v2 — ML edition]
                                |
        +-----------------------+-------------------------+
        |                       |                         |
   [BASE STRATEGY]        [OPP UNDERSTANDING]      [DECISION SAMPLER]
        |                       |                         |
        v                       v                         v
   DeepCFR policy net      Opp embedding net         Conditional sample
   (Phase D)               (Phase E)                 (Phase D+E combined)
   In : (stack_bb,         In : (action_history,
         scenario,                cards_shown,
         hand_class,              hands_played)
         opp_embedding)     Out : 32-64-dim
   Out : action               opp_vector
         distribution                          ↓ feed back as condition

   Fallback : Nash tables actuelles (poky/nitro/ranges.py) si ML pas chargé
```

**Décision pipeline runtime** :
```
NitroPlayer.act(obs):
  1. obs -> (stack_bb, scenario, hand_class)        [existant]
  2. Pour chaque opp : update opp_embedding         [Phase E]
  3. Query DeepCFR policy net avec contexte +
     embeddings -> action distribution               [Phase D+E]
  4. Sample action depuis la distribution
  5. Map to rlcard Action enum                      [existant]
```

## Architecture training (offline, GPU)

```
DeepCFR (Phase D) :                Opp Embedder (Phase E) :
                                    
[3-max game tree]                   [Hand histories database]
       ↓                                    ↓
[Traversal sampling]                [Action sequences]
       ↓                                    ↓
[Regret computation]                [Encoder (LSTM ou Transformer)]
       ↓                                    ↓
[Value net update]                  [Opp embedding (32-64 dim)]
       ↓                                    ↓
[Policy net update]                 [Strategy net consumes embedding]
       ↓                                    ↓
[Iterate 10-50k iters]              [Train via self-play with synth opps]
       ↓                                    ↓
[checkpoint .pth]                   [encoder .pth]
```

---

## PHASE D — DeepCFR (semaines 1-6)

### D0 — Setup environnement (3-5 jours)

**Pourquoi un sibling repo `deepcfr-poky/` séparé** :
- PyTorch + CUDA deps lourdes (~3 GB) polluent l'env Poky actuel
- Permet training sur autre machine (Linux GPU) sans toucher Poky
- Le `.pth` final (~10-50 MB) est petit, importable dans Poky par référence

**Livrables** :
- Cloner Poky dans un sibling `deepcfr-poky/`
- Venv séparé : `python -m venv deepcfr-poky/.venv` (Python 3.11 ou 3.12, PAS 3.14 — pyspiel peut ne pas compiler)
- `pip install torch open_spiel numpy tensorboard`
- Smoke test :
  ```python
  import pyspiel, torch
  print("CUDA:", torch.cuda.is_available())
  game = pyspiel.load_game("universal_poker(...)")  # voir D1
  ```

**Critère go/no-go D0** :
- ✅ pyspiel importe + torch.cuda.is_available() = True
- ❌ Si pyspiel ne build pas (Windows) : pivot WSL2 Ubuntu, ou fallback Steinberger Deep-CFR (pure Python, moins validé)

### D1 — Game definition 3-max push/fold 15bb (5-7 jours)

**Livrables** :
- `deepcfr/game_config.py` : définition ACPC du jeu
  - 3 players, NLHE
  - Stack varie (5-15bb pendant training)
  - **Action abstraction : FOLD + ALL_IN seulement** (match nos tables actuelles, ne pas étendre)
  - Card abstraction : 169 classes préflop via custom info_state_string
- `deepcfr/bucket_state.py` : réutilise `poky/abstraction/preflop.py:canonical_class`
- Tests : 5 SnG hands jouées en mode universal_poker, conversion correcte

**Critère go/no-go D1** :
- ✅ 100 random games tournent sans crash
- ✅ Best-response exploitability calculable (`pyspiel.exploitability`)

### D2 — DeepCFR training pipeline (7-10 jours dev + compute)

**Livrables code** :
- `deepcfr/train.py` : utilise `pyspiel.deep_cfr` reference impl
- Logging via TensorBoard (exploitability, loss curves)
- Checkpoints périodiques (toutes les 1k iters)
- Resume from checkpoint si interrompu

**Hyperparams à explorer** :
| Param | Range | Notes |
|---|---|---|
| iterations | 1k → 5k → 20k → 50k | 50k pour final |
| advantage memory | 1M-10M states | More = better but RAM-bound |
| strategy memory | 1M-10M | Same |
| policy net layers | 3-5 | start 3 |
| policy net width | 64-256 | start 128 |
| learning rate | 1e-4 to 1e-3 | tune |
| batch size | 256-2048 | GPU-bound |

**Compute** :
- Local GPU (RTX 3060+) : 5-10h pour 20k iters
- Cloud vast.ai A100 spot ($1/h) : 1-3h pour 20k iters
- Budget total : $20-100 including hyperparam search

**Critère go/no-go D2** :
- ✅ Exploitability descend sous 30 mBB/h après 10k iters
- ✅ Policy net sample produit des actions cohérentes (AA push 100%, 32o fold ~100%, etc.)

### D3 — Eval vs baselines (5 jours)

**Livrables** :
- `deepcfr/eval.py` : load policy net, sample, jouer dans notre arena
- Bench complet sur 200 SnGs chaque :
  - vs ProShortStackPlayer (le test critique) : cible ≥ 40%
  - vs Old NitroPlayer (le bot actuel) : cible ≥ 45%
  - vs HeuristicPlayer : cible ≥ 50%
  - vs TAG : cible ≥ 65%
  - vs LAG : cible ≥ 45%
  - vs Nit : cible ≥ 75%
  - Self-play (3x DeepCFR) : 33% ± 5% par seat

**Critère go/no-go D3 (LE plus important)** :
- ✅ Vs ProShortStackPlayer ≥ 40% (vs 31% actuel) → Phase D réussie
- ❌ Si < 35% : training a échoué, debug ou retry avec autres hyperparams

### D4 — Integration NitroPlayer (5 jours)

**Livrables** :
- `data/deepcfr/policy_net.pth` (copié depuis deepcfr-poky/)
- `poky/players/nitro_player.py` : nouveau param `use_deepcfr: bool` (default False)
- `poky/nitro/deepcfr_policy.py` : loader + sampler (torch.load + forward pass)
- Tests : 250+ passing, `--use-deepcfr` flag dans `scripts/bench_nitro.py`

**Critère D4** :
- ✅ Tous les tests existants passent (régression)
- ✅ Bench DeepCFR ON vs OFF disponible

---

## PHASE E — Opponent Embedding (semaines 7-14)

### Pourquoi cette phase

Notre `classify_archetype` actuel (7 archétypes, seuils si/sinon) classifie
**à gros grain** :
- Le même opp peut être "TAG" un jour, "NIT" le lendemain selon la variance
- Pas de nuance entre 2 TAGs différents (un 22% VPIP vs un 28%)
- Le classifier perd toute l'info temporelle (séquence d'actions)

L'opponent embedding apprend une représentation **continue, riche, temporelle** :
- Vecteur de 32-64 dim qui résume "comment cet opp joue"
- Conditionne la stratégie DeepCFR pour s'adapter en temps réel
- Mécanisme prouvé dans la recherche poker (cf. ReBeL, Pluribus implicite)

### E0 — Hand history collection (1-2 semaines)

**Livrables** :
- `poky/nitro/hand_history.py` : log de chaque main jouée par chaque opp_id
  - Format JSON Lines (`.jsonl`) : 1 ligne par main
  - Champs : opp_id, position, stack_bb, action_seq, won_pot, hand_shown (si showdown)
- Modifier `SnGRunner` pour appeler `log_hand()` après chaque main
- Backfill via re-run de 1000 SnGs sur les 7 archétypes = ~30k mains de data

**Critère E0** :
- ✅ Dataset de 30k+ mains accessible
- ✅ Conversion vers tensors PyTorch OK

### E1 — Encoder architecture (1-2 semaines)

**Livrables** :
- `deepcfr/opp_encoder.py` :
  - Input : séquence des K=20 dernières mains de l'opp
    - Chaque main → vecteur (one-hot position, hand_class si shown, action_seq encoded, won_pot)
  - Backbone : **LSTM** (simple) ou **Transformer** (mieux mais plus complexe)
  - Output : embedding 32-64 dim
- Tests : encoder produit des embeddings différents pour MANIAC vs NIT

**Choix architecture** :
- **LSTM** : simple, marche bien pour séquences <30, ~1 jour dev
- **Transformer-small** : plus expressif, gère mieux 50+ mains, ~3 jours dev
- **Recommandation** : LSTM pour MVP, upgrade Transformer si gains insuffisants

### E2 — Training encoder + conditioning policy (2-3 semaines + compute)

**Approche : End-to-end training**
- Le policy net DeepCFR (Phase D) est **étendu** pour accepter opp_embedding en input
- Encoder et policy entraînés ensemble
- Self-play avec opp pool synthétique : génère des opps "Nit", "Maniac", "Mix random", etc.
- Loss : objectif CFR (regret minimization) sur ces opps

**Compute** :
- Plus lourd que Phase D : 20-50h GPU
- vast.ai A100 spot : $50-100

**Critère E2** :
- ✅ Embedding capture les archétypes (visualisable via PCA/t-SNE : Maniacs forment un cluster)
- ✅ Policy avec embedding ≠ policy sans (les actions diffèrent vs Maniac vs Nit)

### E3 — Eval avec opp learning (1 semaine)

**Livrables** :
- Bench où le bot **commence sans données** et apprend l'opp pendant la partie
- 200 SnGs chacun vs : ProShortStack (Nash), Maniac, Nit, TAG, LAG, Heuristic
- Pour chaque, mesurer win rate **par dixième de session** (mains 1-3, 4-6, 7-10, 10+)
  - Cible : amélioration mesurable dans le temps (proof that learning works)

**Critère E3** :
- ✅ Vs Maniac : win rate dans la 2e moitié des mains ≥ 1ère moitié + 15%
  (preuve que l'embedding identifie Maniac et adapte la stratégie)
- ✅ Vs ProShortStack : ≥ 45% (encore mieux que Phase D seule à 40%)

### E4 — Integration dans NitroPlayer (1 semaine)

**Livrables** :
- `poky/nitro/opp_embedder.py` : runtime version (load encoder .pth + run forward)
- NitroPlayer met à jour l'embedding en `observe_action()`
- DeepCFR policy net query avec embedding inclus
- Tests + bench final

---

## Calendrier global

```
Semaine   1  2  3  4  5  6  7  8  9 10 11 12 13 14
Phase    D0 D1 D2 D2 D3 D4 E0 E1 E2 E2 E2 E3 E4 buffer
         |==========|==========|=====================|====|
         Phase D       Phase D       Phase E          fin
         setup         compute       setup+train+eval
```

**Total : 14 semaines (~3.5 mois)** de dev actif (1-2h/jour minimum).

## Budget total

| Item | Bas | Haut |
|---|---|---|
| Phase D compute (GPU 5-30h) | $0 (local) | $100 (cloud) |
| Phase E compute (GPU 20-50h) | $0 (local) | $200 (cloud) |
| Vast.ai disk/spot premium | $0 | $50 |
| **Total compute** | **$0** | **$350** |

Avec GPU local raisonnable (RTX 3060 / 3070 / 4060) : **gratuit**.
Avec cloud (vast.ai A100 spot) : **~$200-300 max**.

## Critères de succès final (après D4 + E4)

| Métrique | Aujourd'hui | Cible Phase D | Cible Phase D+E | Verdict |
|---|---|---|---|---|
| Tests passing | 242 | 260+ | 280+ | sanity |
| Vs ProShortStack | 31% | ≥ 40% | **≥ 45%** | **LE test critique** |
| Vs Heuristic | 53% | ≥ 50% | ≥ 55% | maintien |
| Vs TAG | 73% | ≥ 65% | ≥ 70% | maintien |
| Vs LAG | 42% | ≥ 45% | ≥ 50% | gain |
| Vs Nit | 80% | ≥ 75% | ≥ 80% | maintien |
| Vs Maniac | 15% | ≥ 25% | **≥ 40%** | grand gain via E |
| Self-play 3-way | 33% ± 5% | maintenu | maintenu | symétrie |
| Exploitability | non mesuré | < 30 mBB/h | < 20 mBB/h | académique |
| **Avg vs {H, TAG, LAG}** | **53%** | **≥ 55%** | **≥ 60%** | **target user** |

**Le 60% sur "moyens à bons" devrait être atteignable** avec D+E combinés.

## Risques identifiés

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| pyspiel ne build pas Windows Python 3.14 | Élevée | Bloque D | Linux/WSL2 ou Steinberger Deep-CFR |
| Training D instable (expl ne descend pas) | Moyenne | Bloque D3 | Tune hyperparams, multiple seeds, OpenSpiel impl est robust |
| Embedding E n'apprend rien d'utile | Moyenne | Phase E zero gain | Transformer au lieu de LSTM, plus de data |
| Cloud compute trop cher | Faible | Délai | Vast.ai spot, training en off-peak |
| Phase D+E ensemble = +5% au lieu de +15% espéré | Moyenne | Goal manqué | Diminuer le scope (pas Phase F Pluribus) |
| Régression sur tests existants | Faible | Casse Poky | use_deepcfr=False default, opt-in |

## Path alternatif si pyspiel échoue

**Fallback A** : **Steinberger Deep-CFR** (pure Python, repo:
github.com/EricSteinberger/Deep-CFR). Moins validé que OpenSpiel mais
fonctionne. Mêmes phases D0-D4, juste l'impl change.

**Fallback B** : **Import direct des charts Sauce123/HRC** (push/fold Nash
déjà solvé par d'autres). Plus rapide (1 semaine vs 6) mais pas
d'apprentissage = pas la valeur de Phase E.

**Fallback C** : **OpenSpiel via Linux/WSL2** si Windows ne build pas
pyspiel. ~3 jours de setup additionnel.

## Workflow concret pour démarrer la prochaine session

```powershell
# Étape 1 : Récupérer le repo
cd Desktop\DEV\AN
git clone https://github.com/Adem-N/poky.git deepcfr-poky
cd deepcfr-poky

# Étape 2 : Lire les plans
cat docs/PLAN_NITRO.md         # contexte ancien
cat docs/PLAN_ML_PRO_BOT.md    # ce plan (le plan actif)

# Étape 3 : Setup env (D0)
python -m venv .venv  # idéalement Python 3.11 ou 3.12
.\.venv\Scripts\activate
pip install torch open_spiel numpy tensorboard

# Étape 4 : Smoke test
python -c "import pyspiel, torch; print('CUDA:', torch.cuda.is_available()); g = pyspiel.load_game('kuhn_poker'); print(g)"

# Si OK, on commence vraiment D1.
# Si pyspiel échoue : fallback Linux/WSL2 ou Steinberger Deep-CFR.
```

## Ressources techniques

- **DeepCFR paper** : Brown, Lerer, Gross, Sandholm. "Deep Counterfactual
  Regret Minimization" (ICML 2019). https://arxiv.org/abs/1811.00164
- **OpenSpiel DeepCFR impl** : https://github.com/deepmind/open_spiel/blob/master/open_spiel/python/algorithms/deep_cfr.py
- **Pluribus paper** (pour context Opp Embedding) : Brown & Sandholm. "Superhuman
  AI for Multiplayer Poker" (Science 2019).
- **Steinberger Deep-CFR** : https://github.com/EricSteinberger/Deep-CFR
- **Notre repo actuel** : https://github.com/Adem-N/poky

## Notes pour fresh-context-me

- **Lire d'abord** : `docs/PLAN_NITRO.md` (contexte ancien), puis ce plan
- **État actuel de Poky** : Phases N0-N5 livrées (242 tests PASS), NitroPlayer
  fonctionne mais bat pas Pros (31% vs ProShortStack)
- **Ce qui marche déjà** : Nash tables, profiling-based exploits, SnG arena,
  postflop SPR (opt-in)
- **Le NOUVEAU work** : DeepCFR (Phase D) + Opp Embedding (Phase E), dans
  un sibling repo `deepcfr-poky/`
- **Plan workflow** : commit dans Poky les fichiers d'integration (D4, E4)
  seulement ; tout le code de training/eval vit dans `deepcfr-poky/`
- **Critère final** : sur 200 SnGs vs ProShortStackPlayer, win rate ≥ 45%.
  C'est LA condition de succès du projet ML.

---

## TL;DR pour la prochaine session

1. Setup PyTorch + OpenSpiel dans `deepcfr-poky/.venv` (D0, 3-5 jours)
2. Définir le 3-max push/fold game (D1, 1 semaine)
3. Train DeepCFR (D2, ~1 semaine dev + 1 semaine compute)
4. Eval vs ProShortStack (D3, doit atteindre ≥40%)
5. Integrer dans NitroPlayer (D4, 1 semaine)
6. Collecter hand histories + train Opp Embedder (E0-E2, 5 semaines)
7. Eval + integration (E3-E4, 2 semaines)

**Total : 14 semaines actif + ~$0-300 compute. Cible : 60%+ vs {Heuristic, TAG, LAG}, ≥45% vs ProShortStack.**
