# Plan Nitro — Bot 3-max hyper-turbo (Winamax Expresso Nitro)

**Plan actif au 2026-05-29 (remplace tous les plans antérieurs).**

## Contexte

Pivot du projet vers un format unique et bien défini : **Winamax Expresso
Nitro** (ou format 3-max hyper-turbo équivalent pour soirée Discord).

Avant ce pivot, on visait du cash NLHE 100bb HU/3max/6max — c'était
ambitieux mais trop large vu les ressources open-source disponibles
(pas de Pluribus public, pretrained externes morts). Le passé est
documenté dans le snapshot git du 2026-05-29 et dans memory.

**Pourquoi Nitro change la donne** :

| Critère | Cash 100bb | Nitro 3-max 15bb |
|---|---|---|
| Stack effectif | 100 BB profond | **15 BB court** |
| Branching factor décision tree | Énorme (sizings continus, 4 streets) | Petit (push/fold dominant) |
| Nash equilibrium solvable | Non en 3-max | **Oui en quelques secondes** |
| ICM | N/A | Optionnel (multiplier ≥100x seulement) |
| Pop opponent | Mix regs+amateurs | **Majoritairement fish** (chase jackpot) |
| Compute pour solver | Heures-jours | **Secondes-minutes** |
| Niveau "très bon" atteignable | Demande Pluribus-level | **Réalisable avec Nash + heuristic** |

## Spécification du format

Winamax Expresso Nitro :
- **3-max NLHE**, sit-and-go
- **Stack départ : 300 chips = 15 BB** (BB initial = 20)
- **Hyper turbo** : niveau toutes les **60 secondes**
- **Durée moyenne : 10-12 mains**
- **Payouts** :
  - Multiplicateur ≤10x (majorité des games) : **winner-take-all**, ICM ignorable
  - Multiplicateur ≥100x (rare) : **80/12/8** split → ICM matters

## Architecture cible

```
                NitroPlayer (orchestrateur)
                       |
       +---------------+---------------+----------------+
       |               |               |                |
   PreflopLogic    PostflopLogic    ExploitOverlay    ICMLayer (opt)
       |               |               |                |
       v               v               v                v
   pushfold.py     postflop.py     exploits.py       icm.py
   (Nash table     (SPR-based      (pop reads        (Malmuth-
    par stack)      commit rules)   vs Nitro fish)    Harville)
```

**Décision pipeline** au moment d'agir :
```
1. Si stack effectif <= 12 BB OU postflop SPR <= 1.5
   -> push/fold lookup (Nash table 3-max à la stack depth la plus proche)

2. Sinon, preflop (stack 13-15 BB)
   -> open-raise/3-bet/4-bet ranges (Nash résolu + sizing 2.0x ou 2.2x)

3. Sinon, postflop early (stack 13-15 BB, SPR 2-4)
   -> rules SPR-based (commit threshold par texture × hand strength)

4. Override exploit (toujours en couche au-dessus)
   -> ajuste pour pop Nitro : open + wide, 3-bet value tight, c-bet wide

5. Override ICM (si flag activé)
   -> ICM-equity au lieu de chip-EV pour les shoves
```

## Phases d'implémentation

### N0 — Cleanup (FAIT 2026-05-29) ✅

Snapshot git + suppression aggressive de tout ce qui ne sert plus :
- Supprimé : `poky/training/` (~50 fichiers MCCFR/NFSP/CFR), `poky/cfr/`,
  6 players deprecated, 10 tests CFR, 6 GB de checkpoints,
  ancien `PLAN_PRO_BOT*.md`.
- Conservé : engine, equity, abstraction, arena, expert, solver,
  players de base + ExpertOnly + SolverOracle, infra TexasSolver.
- Tests : 178 → 124 (les 54 supprimés étaient CFR-related), tous green.

### N1 — Nash push/fold solver 3-max (3-5 jours)

**Livrables** :
- `poky/nitro/pushfold.py` : `PushFoldSolver` (best-response iteration)
  - Game tree : BTN(push/fold) → SB(call/fold or push/fold) → BB(call/fold)
  - 169 hand classes × 3 positions × ~5 decision points
  - Convergence en ~50-200 itérations
- `scripts/build_pushfold_tables.py` : génère JSON tables pour 6/8/10/12/15 BB
- `data/expert_ranges/3max_nitro/3max_nitro_{6,8,10,12,15}bb.json`
- `tests/test_nitro_pushfold.py` :
  - Test convergence vs solution publique de référence (Sauce123 / push72o)
  - Test symétrie quand stacks égaux
  - Test : à 5 BB BTN doit push >50% (vérifié par littérature)

**Critère succès N1** : tables générées avec exploitability < 0.1 BB / 100 mains
au point d'équilibre. Cross-check ≥ 80% match avec push72o.com sur 30 spots.

### N2 — ICM Malmuth-Harville (1-2 jours)

**Livrables** :
- `poky/nitro/icm.py` :
  - `malmuth_harville_equity(stacks, payouts) -> equities`
  - `equity_delta_for_shove(...)` (utilise la précédente)
- `tests/test_nitro_icm.py` :
  - Stacks égaux + payouts 80/12/8 → equities = [33.3, 33.3, 33.3]
  - Edge cases : 1 stack ≈ 0 → on a déjà perdu
  - Cohérence : somme(equities) ≈ somme(payouts)

**Critère succès N2** : matches numériquement ICMIZER / HRC sur 10 stacks
de test.

### N3 — NitroPlayer (3-5 jours)

**Livrables** :
- `poky/nitro/postflop.py` : règles SPR-based (commit thresholds)
- `poky/nitro/exploits.py` : overlays pop Nitro (open wider, c-bet more)
- `poky/players/nitro_player.py` : `NitroPlayer` (orchestrateur)
  - `act(obs)` : route entre push/fold lookup / preflop ranges / postflop rules
  - `use_icm: bool` flag pour activer/désactiver couche ICM
  - `exploit_level: float` (0.0 = pure GTO, 1.0 = full exploit)
- `tests/test_nitro_player.py` :
  - act() ne crash pas sur preflop/flop/turn/river
  - Push/fold cohérent à stack court (5 BB AA → push BTN/SB/BB)
  - Open-raise wider en BTN vs early position

**Critère succès N3** : NitroPlayer bat HeuristicPlayer 3-max @ 15bb-15bb-15bb
≥ +30 bb/100 sur 5k mains (Heuristic est faible en short-stack).

### N4 — Arena SnG + bench (2-3 jours)

**Livrables** :
- Adapter `poky/arena/` pour SnG :
  - Stacks variables (pas reset à chaque main)
  - Blind escalation toutes les N mains
  - Élimination quand stack = 0
  - Tracking des payouts par finish position
- `scripts/bench_nitro.py` :
  - 100+ SnGs simulés
  - Reporte : ROI moyen, win rate (1ère place), payout total, IC95
- Optionnel : `poky/players/fish_player.py` (archétype reflétant pop Nitro
  basé sur les exploits.py — bot calling-station loose)

**Critère succès N4** : NitroPlayer (vs 2× Fish ou 2× Random) gagne ≥ 50% des
SnGs (vs 33.3% baseline), idéalement ≥ 60%.

### N5 — Validation finale et iteration (ongoing)

Si N1-N4 livrés :
- vs Heuristic 3-max SnG : ≥ 55% win rate
- vs 2× Random : ≥ 80% win rate (sanity)
- vs 1× Heuristic + 1× Random : ≥ 60% win rate
- vs 2× NitroPlayer (self-play) : break-even ±10%
- Mesurer si exploit overlay donne un boost vs pure GTO (devrait +5 à +15% win rate vs fish)

### N6 — (Plus tard, hors scope soirée) Adapter plateforme

Pour brancher le bot sur Winamax / Pokernow / arena Discord :
- Vision (OCR du table state)
- Keyboard automation pour clic actions
- Anti-detection (timings randomisés, mouse movement, etc.)
- **Hors scope** : tu m'as dit de ne pas y toucher tant que le brain n'est pas fini.

## Budget temps

| Phase | Effort | Notes |
|---|---|---|
| N0 cleanup | 1h | ✅ fait |
| N1 pushfold | 3-5 jours | code + validation vs référence |
| N2 ICM | 1-2 jours | math standard, well-documented |
| N3 NitroPlayer | 3-5 jours | code + bench vs baseline |
| N4 arena SnG + bench | 2-3 jours | refactor arena + nouveau bench |
| N5 validation | ongoing | itérer sur résultats |
| **Total brain** | **~2-3 semaines** | confortable vu ton "1 mois+" |

Compute requis : **quasi nul**. Push/fold solver tourne en secondes, pas de
GPU nécessaire. Le TexasSolver qu'on a installé reste utilisable pour
quelques spots postflop deep-stack rares mais n'est plus la fondation.

## Fichiers gardés vs supprimés

### Conservés (encore utiles)
- `poky/engine/` : rlcard wrapper
- `poky/equity/` : phevaluator, MC equity
- `poky/abstraction/` : 169 classes préflop, postflop buckets
- `poky/arena/` : tournament runner (sera étendu pour SnG en N4)
- `poky/expert/` : framework range lookup (réutilisé pour Nitro)
- `poky/solver/` : TexasSolver wrapper (Z0-Z3, garde pour spots rares)
- `poky/players/` : base, random, call, heuristic, archetypes, human,
  adaptive, expert_only, solver_oracle (Tier 2 fallback)
- `poky/cli/` : play, arena (entrées CLI génériques)
- `data/expert_ranges/3max_100bb.json` : référence 100bb si besoin
- `external/TexasSolver/` : binary GTO solver
- Tests : 124 conservés (engine, equity, arena, archetypes, heuristic,
  expert_ranges, postflop_rules, preflop/postflop abstraction,
  spot_schema, cache_db, solver_runner, solver_oracle)

### Supprimés (commit `snapshot pre-Nitro` les préserve dans git)
- `poky/training/` : tout CFR/MCCFR/NFSP
- `poky/cfr/` : subgame_solver
- `poky/platform_adapter/` : était vide
- Players : nfsp, blueprint, nmax_blueprint, cfr, claude, pro_claude
- CLI : tournament, compare (référencaient des players morts)
- Tests : 10 fichiers CFR-related
- Scripts : eval_dberweger, bench_x2
- ~6 GB checkpoints data/ : blueprint_*, nfsp_*, overnight, sessions
- Docs : PLAN_PRO_BOT.md, PLAN_PRO_BOT_V3.md (archive in git)

## Sources / références techniques

- Spin & Go strategy : https://www.vip-grinders.com/poker-strategy/spin-and-go/
- bitB Hyper Spins guide : https://bitb-spins.com/articles/beginners-guide-to-hyper-spins-winamax-nitro/
- Push/fold Nash 20bb HU : https://gtocharts.com/nash/
- Holdem Resources Calculator (paid reference) : https://www.holdemresources.net/
- Push72o free push/fold charts : https://www.push72o.com/push-or-fold/
- ICM theory : https://www.pokernews.com/strategy/icm-poker-7841.htm
