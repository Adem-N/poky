# État du projet — Poky

Mis à jour : 2026-05-29 (cleanup pivot Nitro — repo nettoyé, fondations gardées).

## NEXT (handoff pour la prochaine session)

**Plan actif** : `docs/PLAN_NITRO.md` (remplace tous les plans antérieurs).

**Pivot 2026-05-29** : abandon du scope cash 100bb HU/3max/6max et bascule
intégrale sur **Winamax Expresso Nitro** (SnG 3-max 15bb hyper-turbo).
Beaucoup plus accessible : Nash equilibrium 3-max push/fold solvable en
quelques secondes, pas besoin de Pluribus-level. Cible "très bon joueur,
pas top du panier" = atteignable.

**Phases N** :
1. ✅ **N0 cleanup** (fait 2026-05-29) — snapshot git + suppression
   aggressive de tout MCCFR/CFR/NFSP/blueprint/dberweger, suppression
   ~6GB checkpoints, nettoyage __init__. Tests : 178 → 124, tous green.
2. **N1 Nash push/fold 3-max** (3-5 jours) — `poky/nitro/pushfold.py`,
   génération JSON tables pour 6/8/10/12/15 BB.
3. **N2 ICM** (1-2 jours) — `poky/nitro/icm.py`, Malmuth-Harville.
4. **N3 NitroPlayer** (3-5 jours) — `poky/players/nitro_player.py`
   orchestrant pushfold + postflop rules + exploit overlay + ICM optionnel.
5. **N4 Arena SnG + bench** (2-3 jours) — adapter arena pour blinds
   escalation + payouts, `scripts/bench_nitro.py`.
6. **N5 validation finale** (ongoing) — gauntlet 3-max vs Fish/Heuristic/Random.

**Brain seul, hors scope plateforme**. L'intégration vision/keyboard
viendra après N5 (phase N6, pas avant que le brain soit solide).

**Important pour fresh-me** : lire dans cet ordre
1. `docs/PLAN_NITRO.md` (le plan actif)
2. Ce STATUS.md
3. `docs/SUCCESS_CRITERIA.md`
4. `docs/TEXASSOLVER_FORMAT.md` (utile pour spots postflop rares)
5. `~/.claude/projects/.../memory/MEMORY.md` (quirks rlcard HU, historique pivots)

---

## Acquis (à conserver tels quels)

### Phase X1 — Ranges expertes 100bb (validées mais hors scope actif)

Le travail Tier 1 ranges (HU/3max/6max @ 100bb) reste accessible via
`data/expert_ranges/*.json` et `poky/players/expert_only.py`. Validé
gauntlet 21/21 cellules @ 100bb (cf snapshot git pre-Nitro).
Réutilisé si on revient un jour au cash 100bb. Pour Nitro 15bb, ces
ranges sont fausses car la stack-depth change tout — N1 produira les
ranges Nitro-spécifiques.

### Phase Z0-Z3 — TexasSolver foundation (livrée 2026-05-29)

Infra TexasSolver intégrée :
- `external/TexasSolver/` : binary v0.2.0 (39 MB)
- `poky/solver/` : SpotKey + CacheDB SQLite + solver_runner + observation_to_spot
- `poky/players/solver_oracle.py` : SolverOraclePlayer (lookup + fallback)
- 36 tests (spot_schema 6 + cache_db 6 + solver_runner 1 + solver_oracle 13 + autres). PASS.
- `data/solver_cache/hu_flop.sqlite` : 3 spots demo (HU, plus utilisé en Nitro)

Pour Nitro, ce solver est **secondaire** (spots postflop deep-stack rares
en 15bb). Le brain principal sera Nash push/fold + heuristic, beaucoup
plus simple et adapté.

### Phase Z0 — Dberweger autopsy ✅ FERMÉ

Verdict définitif : sur Windows + Python 3.14, la wheel pokers segfault
sur `state.apply_action()`. Modèle dberweger inutilisable. Chapitre clos.

---

## Tests post-cleanup : 124/124 PASS

```
tests/test_engine.py                 3
tests/test_arena.py                  3
tests/test_equity.py                 7
tests/test_archetypes.py             4
tests/test_heuristic.py              6
tests/test_preflop_abstraction.py    8
tests/test_postflop_abstraction.py   7
tests/test_expert_ranges.py          N
tests/test_postflop_rules.py         N
tests/test_spot_schema.py            6
tests/test_cache_db.py               6
tests/test_solver_runner.py          1 (integration, requires binary)
tests/test_solver_oracle.py         13
=====================================
Total                              124
```

(Les ~54 tests supprimés concernaient CFR/MCCFR/blueprint — cf `git log`.)

---

## Architecture actuelle (post-cleanup)

```
poky/
├── engine/              # rlcard wrapper (Observation, Action, Game)
├── equity/              # phevaluator + Monte Carlo equity
├── abstraction/         # 169 préflop classes + postflop buckets + action abstraction
├── arena/               # tournament runner (sera étendu pour SnG en N4)
├── expert/              # range lookup framework (préflop_ranges, postflop_rules, context)
├── solver/              # TexasSolver wrapper (Phase Z2)
├── nitro/               # 🆕 Nitro-specific (placeholders, à implémenter N1-N3)
│   ├── pushfold.py        # PLACEHOLDER — Nash 3-max solver
│   ├── icm.py             # PLACEHOLDER — Malmuth-Harville
│   ├── ranges.py          # loader JSON tables
│   ├── postflop.py        # PLACEHOLDER — SPR commit rules
│   └── exploits.py        # PLACEHOLDER — pop Nitro overlays
├── players/
│   ├── base.py
│   ├── random_player, call_player, heuristic, archetypes
│   ├── adaptive (référence baseline)
│   ├── human (CLI play)
│   ├── expert_only (Tier 1+2, sera adapté pour Nitro)
│   └── solver_oracle (Tier 3 via cache)
├── cli/                 # play.py, arena.py (génériques)
└── logging/             # session_logger, analyzer

data/
├── expert_ranges/
│   ├── 3max_100bb.json     # référence ancienne (utilisable si retour cash)
│   ├── hu_100bb.json
│   ├── 6max_100bb.json
│   └── 3max_nitro/         # 🆕 à populer en N1
├── solver_cache/
│   └── hu_flop.sqlite      # 3 spots demo (Phase Z2)
└── .gitkeep

external/
└── TexasSolver/            # binary v0.2.0

scripts/
├── sanity_bench.py
├── gauntlet.py             # multi-archetype gauntlet
├── bench_expert.py         # pattern réutilisable
├── bench_solver.py         # Phase Z3 bench
├── build_cache.py          # Phase Z2 cache builder
├── solver_smoke.py         # smoke TexasSolver
└── [à venir] build_pushfold_tables.py, bench_nitro.py

docs/
├── PLAN_NITRO.md           # 🆕 plan actif
├── STATUS.md               # ce fichier
├── SUCCESS_CRITERIA.md     # à adapter pour Nitro
└── TEXASSOLVER_FORMAT.md   # I/O format solver
```
