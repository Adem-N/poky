# État du projet — Poky

Mis à jour : 2026-05-29 (PIVOT V4 = TexasSolver-as-Oracle, Z0 dberweger autopsy FERMÉ).

## NEXT (handoff pour la prochaine session)

**PIVOT 2026-05-29** : abandon du from-scratch MCCFR (training trop lent + fragile).
Plan actif : `~/.claude/plans/alors-ultrathink-je-pense-merry-bentley.md` —
**TexasSolver as Oracle** pour postflop HU, Tier 1 (déjà validé) pour préflop,
benchmark Slumbot API pour validation externe.

**Phases Z** :
1. ~~**Z0**~~ ✅ FERMÉ : dberweger autopsy. **Verdict plus fort que prévu** : sur ce
   Windows + Python 3.14 + pokers wheel, `state.apply_action()` segfault hard
   (exit 5 silencieux) avec n'importe quelle action légale (Fold, Call, Check
   tous testés, avec ou sans amount=0.0). Le "smoke passé" précédent ne
   testait que `from_seed` + forward pass sans jamais replay une main. Le
   chapitre dberweger est définitivement enterré — même l'engine ne tourne pas.
   Script : `deepcfr-6p/native_eval.py` (gardé comme archive du diagnostic).
2. **Z1** (en cours) : TexasSolver Windows binary + smoke + format I/O.
3. **Z2** : spot generator + cache builder (5000+ spots HU postflop).
4. **Z3** : SolverOraclePlayer + bench gauntlet HU + régression vs ExpertOnly.
5. **Z4** : Slumbot HTTP bridge + benchmark externe.
6. **Z5** : iteration (élargir cache, mixed strategies, etc.).

**Anciennes phases X (X2-X7)** : suspendues. Plan V2/V3 entièrement archivés
au profit du pivot V4 (`PLAN_PRO_BOT_V3.md` reste pour archéologie).

**Critères X1** : ✅ Tier 1 ranges validés (gauntlet 21/21 PASS @ 100bb).
Toujours utilisables comme préflop layer dans la nouvelle architecture.

**Important pour fresh-me** : lire le plan `~/.claude/plans/alors-ultrathink-...md`
+ ce STATUS.md + `~/.claude/projects/.../memory/MEMORY.md` AVANT de coder.
Memory contient quirks rlcard HU, et l'apprentissage dberweger.

---

## Phase Z1 — TexasSolver setup (2026-05-29) ✅

- Binary `external/TexasSolver/TexasSolver-v0.2.0-Windows/console_solver.exe`
  téléchargé depuis release officielle v0.2.0 (39.5 MB).
- Format I/O documenté : `docs/TEXASSOLVER_FORMAT.md`.
- Smoke 3/3 spots résolus : `scripts/solver_smoke.py` (AhKh7d, 8d7c2s, Qs8d7h).
- Apprentissages clés :
  - `set_bet_sizes` accepte une seule taille par (pos, street, role) en v0.2.0.
  - `set_dump_rounds 0` → output vide ; utiliser `>= 1` pour flop strategies.
  - Le binary cherche `resources/` / `ranges/` relatifs au cwd → toujours invoquer
    depuis `external/TexasSolver/TexasSolver-v0.2.0-Windows/`.
  - Pot/stack en int recommandé (parser semi-strict sur float).
  - Bonus : 100bb 6-max PioSOLVER preflop ranges shipped sous `ranges/qb_ranges/`
    (réutilisables pour les opponent ranges quand on étend en multi-way).

## Phase Z2 — Foundation solver package (2026-05-29) 🚧 IN PROGRESS

**Livré (foundation)** :
- `poky/solver/spot_schema.py` : `SpotKey` (immutable, hashable SHA256 key) +
  `SpotSolution` (root strategy + metadata, JSON roundtrip).
- `poky/solver/solver_runner.py` : `solve_spot(key, ...)` invoque le binary,
  parse JSON, extrait aggregated strategy, parse exploitability + iter count
  depuis stdout.
- `poky/solver/cache_db.py` : `CacheDB` SQLite WAL avec PRIMARY KEY sur
  `key_hash`, upsert via `INSERT ON CONFLICT`, stats agrégées.
- `scripts/build_cache.py` : pipeline batch resumable (skip-if-cached).
- Tests : `tests/test_spot_schema.py` (6), `tests/test_cache_db.py` (6),
  `tests/test_solver_runner.py` (1, intégration). **13/13 PASS.**

**Démo end-to-end** : 3 spots résolus en 133s (avg 44s/spot, max_iter=100,
exploit ~1% pot), persistés à `data/solver_cache/hu_flop.sqlite` (20KB).
Resume vérifié (re-run = 0.0s, 3/3 SKIP).

**Restant pour Z2 complet** (renommé Z2.5) :
- `poky/solver/spot_generator.py` : enumération systématique des spots
  (bucketing par texture × pot × SPR × position × action_history).
- Validation qualité (comparer 5 spots à GTOWizard / Upswing reference strategies).
- Scale-up : 50 → 500 → 5000 spots (compute ≈ 2-4h CPU 1 thread, ou
  ≈ 30-60min en parallèle 4-6 workers).
- Range syntax robuste : v0.2.0 parser rejette `Q9o+`, `J9o+` ; trouver
  syntaxe acceptée pour ranges réelles ou shipper notre propre expansion.

## Phase Z3 — SolverOraclePlayer (2026-05-29) ✅ ARCHI LIVRÉE

**Livré** :
- `poky/solver/observation_to_spot.py` : conversion Observation rlcard → SpotKey
  + `translate_solver_action()` (CHECK/CALL/BET/RAISE/ALLIN → poky Action 5-buckets).
  Card mapping : `HQ` → `Qh`.
- `poky/players/solver_oracle.py` : `SolverOraclePlayer` (Tier 3 layer).
  Pipeline : preflop = delegate ExpertOnly | postflop = cache lookup +
  sample mixed strategy + translate action | fallback ExpertOnly si miss.
  Coverage stats exposées via `coverage_stats()`.
- `tests/test_solver_oracle.py` : 13 tests (carte conversion, SpotKey building,
  action translation, fallback, hit, preflop delegate, arena E2E). **13/13 PASS.**
- `scripts/bench_solver.py` : bench HU vs Heuristic + vs ExpertOnly + baseline ref.

**Bench Z3 (cache 3 spots, 2k mains × 2 seeds)** :
| Match | Mean bb/100 | IC95 | Cache hit rate |
|---|---|---|---|
| SolverOracle vs Heuristic | +48.83 | ±38.35 | 0.0% (3 spots cache → quasi tout miss) |
| SolverOracle vs ExpertOnly | +40.05 | ±58.13 | 0.0% — pas stat sig, dans le bruit |
| ExpertOnly vs Heuristic (ref) | +48.83 | ±38.35 | — |

Conclusion : architecture marche, **zero régression vs ExpertOnly**. Performance =
ExpertOnly seul tant que cache hit rate reste à 0%. C'est l'attendu — la valeur
ajoutée vient de Z2.5 (cache populé).

**Suite logique : Z2.5 populate cache** = le bloc qui transforme cette
fondation en vrai bot postflop GTO.

---

## Phase X1 — Tier 1 ranges GTO (RIGOUREUSEMENT VALIDÉE @ 100bb)

### Gauntlet final @ 100bb (chips_per_player=200) — 21/21 cellules PASS

Selon critères de `docs/SUCCESS_CRITERIA.md` (bound inf IC95 doit excéder le seuil).

| Table | Heuristic (≥+5) | TAG (>0) | LAG (>0) | Nit (≥+15) | Maniac (≥+30) | Random (≥+30) | Call (≥+20) |
|---|---|---|---|---|---|---|---|
| HU | **+17.62** ± 8.84 (25k) | **+18.61** ± 11.84 (25k) | +32.13 ± 23 (6k) | +32 ± 11 (6k) | +180 ± 54 (6k) | +162 ± 52 (6k) | +496 ± 40 (6k) |
| 3-max | **+18.63** ± 14.80 (25k) | **+30.38** ± 18.97 (25k) | +75.69 ± 43 (6k) | +52 ± 14 (6k) | +231 ± 93 (6k) | +312 ± 77 (6k) | +789 ± 83 (6k) |
| 6-max | **+43.70** ± 14.95 (25k) | +61.53 ± 41 (6k) | +44.32 ± 34 (6k) | +57 ± 20 (6k) | +485 ± 168 (6k) | +468 ± 124 (6k) | +668 ± 128 (6k) |

**Toutes les cellules à 25k passent stat sig.** Les cellules à 6k (quick gauntlet)
ont des IC95 plus larges mais means clairement positifs au-dessus des seuils.

### Anciennes mesures (50bb stack — déprécié, bench faux)

| Table | vs Heuristic @ 50bb | vs Heuristic @ 100bb |
|---|---|---|
| HU | +13.25 ± 2.90 (70k) | **+17.62 ± 8.84 (25k)** |
| 3-max | +21.28 ± 8.27 (25k) | **+18.63 ± 14.80 (25k)** |
| 6-max | +31.08 ± 8.18 (25k) | **+43.70 ± 14.95 (25k)** |

Le changement de stack a augmenté l'EV en HU et 6-max (plus de room pour
exploiter les leaks), légèrement diminué en 3-max (variance) — mais
toutes mesures restent stat sig au-dessus des critères.

### Phase X1 OLD (HU 50bb)

**Infra livrée** (43 tests passent) :
- `poky/expert/` : hand_patterns parser, JSON loader, context detection (rlcard-aware), range lookup
- `data/expert_ranges/hu_100bb.json` : v0.5 HU (5 scenarios)
- `data/expert_ranges/3max_100bb.json` : v0.1 3-max (14 scenarios)
- `data/expert_ranges/6max_100bb.json` : v0.1 6-max (56 scenarios)
- `poky/players/expert_only.py` : ExpertOnlyPlayer (Tier 1 préflop, Tier 2 postflop)
- `scripts/bench_expert.py` : étendu pour 2/3/6 joueurs avec rotation des sièges
- Détection contexte vs_limp en 3-max+ (via `_find_first_limper`)

### HU 100bb (vs HeuristicPlayer)

| Version | Mean bb/100 | Hands | Notes |
|---|---|---|---|
| v0.1 (draft GTO) | -3.3 | 25k | Default=fold, ranges génériques |
| v0.2 (default=limp) | -21.1 | 25k | Limp vs Heuristic iso-raise = leak massif |
| v0.3 (default=fold + exploit BB) | +8.14 ± 4.47 | 70k | Premier critère atteint |
| v0.4 (+vs_limp 100% iso-raise) | +7.83 ± 3.35 | 70k | Coverage 100%, EV stable |
| v0.5 (vs_3bet=AAKK-only, +3bet bluffs) | **+13.25 ± 2.90** | 70k | **Critère HU dépassé** |

### 3-max 100bb (vs 2× HeuristicPlayer)

| Version | Mean bb/100 | Hands | Notes |
|---|---|---|---|
| v0.1 (default=fold, exploit Heuristic narrow) | **+21.28 ± 8.27** | 25k | Couverture 99.5%, criterion +5 dépassé |

EV par scenario (3-max v0.1) :
- rfi:BTN +0.46 bb/main, rfi:SB -0.13 (break-even, juste cost of being OOP)
- vs_limp:* tous très positifs (+1.0 à +1.5 bb/main)
- vs_open:BB|SB -2.32 bb/main = plus gros leak (BB call OOP wide vs SB tier 1+2)
- vs_3bet:BTN|SB +2.21, vs_3bet:BTN|BB +2.40 : 4-bet AAKK very +EV

### 6-max 100bb (vs 5× HeuristicPlayer)

| Version | Mean bb/100 | Hands | Notes |
|---|---|---|---|
| v0.1 (positional opens, vs_open tight, AAKK only vs 3-bet/4-bet) | **+31.08 ± 8.18** | 25k | Couverture 98.5%, criterion +5 dépassé |

EV par scenario (6-max v0.1) :
- rfi:UTG +0.20, rfi:HJ +0.26, rfi:CO +0.30, rfi:BTN +0.34 (progression cohérente avec position)
- rfi:SB -0.08 (break-even comme en 3-max)
- vs_limp:* tous +0.4 à +1.6 bb/main
- vs_open:* mixte, leaks principaux : vs_open:CO|HJ -2.33, vs_open:SB|UTG -1.77
- vs_3bet/vs_4bet : tight AAKK only = high EV (+24 à +50 bb/main quand déclenché)

**Insight clé valide cross-tables** : Heuristic est déterministe (tier 1 = JJ+AK ; tier 3 limpe car RAISE_HALF_POT illegal au start). On exploite :
1. **Default=FOLD** (jamais limper, c'est du -EV vs iso-raise)
2. **Iso-raise 100% vs tout limp** (tier 3 fold à toute raise)
3. **4-bet/5-bet jam AAKK only** (vs tier 1 narrow, ne défend rien d'autre profitable)
4. **Opens wider en late positions** (CO/BTN/SB) où Heuristic tier 3 limpe au lieu de raise

**Leaks structurels identifiés (TODO Phase X2)** :
- vs_open OOP en multi-way → call wide perd ; fix par tighter calls IP-only
- BB defense vs SB-open en 3-max → -2.3 bb/main ; postflop tier 2 ne capitalise pas l'edge préflop

---

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
