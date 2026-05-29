# Plan Pro Bot Poky V3.2 — priorité validation académique (2026-05-28)

## Note critique sur la fiabilité des sources

Suite à challenge légitime du user ("le repo DecisionHoldem est-il fiable, pas beaucoup d'étoiles"), recherche approfondie effectuée sur 4 candidats. Verdict honnête :

| Repo | Stars | Maintien | License | Multi-player | Validation prouvée |
|---|---|---|---|---|---|
| **DecisionHoldem** (AI-Decision) | 94 | Modeste | ⚠️ AGPL | ❌ HU only | ✅ **Paper + #1 Slumbot (+730 mbb/h)** |
| **deepcfr-6-players** (dberweger2017) | 92 | ✅ Mars 2025 | ✅ MIT | ✅ 6-max | ⚠️ Self-reported, maintainer admet |
| **Deep-CFR** (Steinberger) | 325 | ❌ Obsolète | ? | configurable | ✅ Paper original |
| **AlphaHoldem** (officiel) | N/A | ❌ Pas publié | N/A | N/A | ✅ Paper AAAI 2022 |

**Décision V3.2** : Le user préfère explicitement aller direct sur **DecisionHoldem** parce que **performance prouvée empiriquement** > facilité d'install. Raisonnement validé : on évite "validation fatigue" sur du non-prouvé.

## Stratégie : POC séquentiels (révisé V3.2)

```
POC #1 (3-7 jours) : DecisionHoldem  ← ATTAQUE DIRECTE
   ✅ +730 mbb/h vs Slumbot, ranked #1 leaderboard (PROUVÉ)
   ✅ Paper arxiv 2201.11580 (AAAI 2022)
   ⚠️ HU only → on étend en N-max avec notre code mccfr_nmax existant
   ⚠️ WSL2 + compilation C++ → coût one-time borné
   ⚠️ AGPL → OK projet personnel
   ↓ Si compilation impossible / KO ↓
POC #2 (5-7 jours, FALLBACK) : deepcfr-6-players
   ✅ MIT, Python pur, 6-max natif
   ⚠️ Perf non validée, maintainer admet "open research question"
   ↓ Si KO ↓
Plan C : retour à PLAN_PRO_BOT.md (V2 from-scratch)
   ⚠️ 3-4 mois mais sous contrôle total
```

**Rationale (réflexion du user 2026-05-28)** :
- "Académiquement prouvé > facile à installer" quand on construit un projet long-terme
- Coût de valider du non-validé ≈ coût d'installer du validé, mais résultat connu d'avance pour le validé
- Tier 1 (core engine) doit être solide pour que Tier 2-5 (couches au-dessus) aient un sens

---

## Architecture cible (inchangée vs V3 initial)

```
[CORE ENGINE : un des POC ci-dessus]
   ↓ Python bindings / wrapper
[POKY ORCHESTRATION]
   ├─ Dual-speed router (slow cash / fast Nitro)
   ├─ Adaptive exploitation layer (notre Tier 5)
   ├─ Population reads pour fast-fold anonyme
   ├─ N-max extension (si core est HU)
   └─ Fallback HeuristicPlayer
```

---

## Phases

### Phase Y0 — POC #1 : DecisionHoldem (3-7 jours)

**Tasks** :
1. **Setup environnement Linux** (Day 1, ~1-3h)
   - Installer WSL2 Ubuntu 22.04 sur Windows 11 : `wsl --install -d Ubuntu-22.04`
   - Setup outils : `sudo apt install build-essential cmake git python3-dev`
2. **Compilation DecisionHoldem** (Day 1-2, ~2-8h)
   - `git clone https://github.com/AI-Decision/DecisionHoldem` dans WSL2
   - Lire et suivre INSTALL.md à la lettre
   - Builder les .so files si pas fournis pré-compilés pour notre arch
   - Test smoke : lancer le binaire et faire jouer 1 main contre lui-même
3. **Reproduction de la validation paper** (Day 2-3, ~4-6h)
   - Lancer match DecisionHoldem vs Slumbot via leur infra (script dans repo)
   - Confirmer ordre de grandeur +730 mbb/h sur ~1000 mains
   - Si écart énorme : flag bug d'install
4. **Bridge Python** (Day 3-5, ~8-16h)
   - `poky/external/decisionholdem_bridge.py` : wrapper FFI (`ctypes` ou `cffi`) vers les .so
   - Convertir notre `Observation` rlcard → format attendu par DecisionHoldem
   - Convertir leur output → notre `Action` enum
   - Tests unit sur 5 situations de référence (AA preflop, missed flop draw, river bluff, etc.)
5. **Eval contre nos baselines** (Day 5-7, ~4-6h)
   - Match DecisionHoldem vs HeuristicPlayer sur 5000 mains HU
   - Match DecisionHoldem vs AdaptiveHeuristic sur 5000 mains
   - Match DecisionHoldem vs ProClaude sur 1000 mains

**Critère go/no-go** :
- ✅ **GO** : bat HeuristicPlayer de +50 bb/100 minimum (devrait être +200+ vu sa perf vs Slumbot)
- ⚠️ **À investiguer** : bat de +20 à +50 → bug dans bridge probablement
- ❌ **NO-GO COMPILATION** : impossible à compiler après 2j de debug → fallback Y0bis
- ❌ **NO-GO PERF** : ne bat pas heuristic → quelque chose de fondamental est cassé, fallback Y0bis

**Risques identifiés** :
- Compilation peut requérir libs spécifiques (Boost, etc.) → suivre INSTALL.md précisément
- .so binaires fournis peuvent être liés à versions Ubuntu spécifiques → recompiler from source si fail
- AGPL : si on touche au code DecisionHoldem, notre projet devient AGPL aussi. **Mitigation** : on ne modifie PAS leur code, juste wrapper externe. Notre code reste sous notre license choisie.
- Format input/output peut être obscur → lire le source C++ si besoin

**Estimation** : 25-50h (selon difficulté compilation)

---

### Phase Y0bis — POC #2 FALLBACK : deepcfr-6-players (SI Y0 KO)

**Tasks** :
- `git clone https://github.com/dberweger2017/deepcfr-texas-no-limit-holdem-6-players`
- Setup venv séparé (PyTorch + PyQt5)
- Charger pre-trained `flagship_models/first`
- Wrapper Python : `poky/external/dberweger_bridge.py`
- Eval contre nos baselines

**Critère go/no-go** :
- ✅ **GO** : bat HeuristicPlayer de +30 bb/100 minimum sur 5000 hands → on adopte
- ❌ **NO-GO** : ne bat pas → Plan C (retour from-scratch)

**Risques connus (lus dans README dberweger)** :
- "Older README claims more stable training than the current repo can honestly guarantee"
- Tester multiple checkpoints, pas juste celui fourni

**Estimation** : 30-40h

---

### Phase Y1 — Adaptive layer + dual-speed (1-2 semaines)

Identique au V3 initial — peut s'appliquer à n'importe quel core engine choisi (deepcfr-6p ou DecisionHoldem).

**Livrables** :
- `poky/expert/exploit_adjustments.py`
- `poky/cfr/dual_speed_router.py`
- Mode `fast` (Nitro, lookup blueprint only) vs `slow` (cash, full solver/subgame)

**Estimation** : 40-50h

---

### Phase Y2 — Population reads (1 semaine)

Pour fast-fold anonyme, tracking par POOL (room+format+stake) au lieu de par opponent.

**Livrables** :
- `poky/expert/population_profiles.py` avec profils pool publiés (Upswing/RedChip blogs)
- Integration dual_speed_router

**Estimation** : 25-30h

---

### Phase Y3 — N-max extension (2-3 semaines, SI le POC retenu est HU only)

Si on a pris DecisionHoldem (HU), on garde nos travaux mccfr_nmax existants pour 3-max/6-max.

Si on a pris deepcfr-6p (déjà 6-max), cette phase est skippée.

**Estimation** : 60-80h (conditionnel)

---

### Phase Y4 — Eval finale et iteration (ongoing)

Mêmes critères que V3 initial. 5/6 critères → pro-level atteint.

**Estimation** : 40h+ continu

---

## Budget total V3.1

Scénario optimiste (POC #1 marche) :
- Y0 : 30-40h
- Y1 : 40-50h
- Y2 : 25-30h
- Y4 : 40h
- **Total : ~140-160h ≈ 4 semaines**

Scénario moyen (POC #1 décevant, POC #2 OK) :
- Y0 : 30-40h (test échoué mais reste utile)
- Y0bis : 50-70h
- Y1 : 40-50h
- Y2 : 25-30h
- Y3 : 60-80h (HU bot, need N-max)
- Y4 : 40h
- **Total : ~250-310h ≈ 7-8 semaines**

Scénario pessimiste (les 2 POC échouent) :
- Y0 + Y0bis : 80-110h (investigation)
- Retour Plan V2 : 200-300h
- **Total : ~280-410h ≈ 8-12 semaines**

Compute : presque rien si POC réussit (modèles pre-trained). $50-200 si Plan B.

---

## Risques identifiés et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| deepcfr-6p perf < claims | Moyenne | Move to Y0bis | Validation rigoureuse dès Y0 |
| DecisionHoldem ne compile pas | Faible | Move to Plan B | WSL2 + suivre exactement leur INSTALL |
| Adaptive layer ne donne pas le boost attendu | Faible | Bot reste GTO-only | Reste compétitif quand même |
| Dual-speed router buggy | Moyenne | Fast mode dégradé | Tests rigoureux, fallback heuristic |
| Population reads pas validés | Élevée | Bot moins exploiteur en fast-fold | Acceptable, le pure GTO marche aussi en fast-fold |

---

## Choix philosophiques (inchangés)

1. **GTO + Exploit hybride** (pas pure GTO ni pure exploit)
2. **Population reads** > individual HUDs en fast-fold (anonyme)
3. **Dual-speed obligatoire** (slow pour cash, fast pour Nitro)
4. **Pre-trained > from-scratch** quand possible (gain de mois)

---

## Notes pour la prochaine session (post /clear)

Fresh-context-me doit :
1. Lire ce fichier (`docs/PLAN_PRO_BOT_V3.md`)
2. Démarrer par **Phase Y0** : clone deepcfr-6-players, test contre notre HeuristicPlayer
3. Critère go/no-go strict pour décider Y0 → Y1 ou Y0bis
4. Aucune dépendance externe ajoutée à `requirements.txt` avant validation POC

Sources :
- deepcfr-6p : https://github.com/dberweger2017/deepcfr-texas-no-limit-holdem-6-players
- DecisionHoldem : https://github.com/AI-Decision/DecisionHoldem
- DecisionHoldem paper : https://arxiv.org/abs/2201.11580
- AlphaHoldem paper (référence) : AAAI 2022 — code officiel non publié
- Awesome poker AI list : https://github.com/PokerBotAI/awesome-poker-ai
- Fast-fold strategy : https://www.vip-grinders.com/poker-strategy/fast-fold/

---

## Session 2026-05-28 (turn 2) — outcome

⚠️ Note "prochaine session" ci-dessus est OBSOLÈTE (héritée de V3, pas V3.2). V3.2 démarre par DecisionHoldem en POC #1, pas deepcfr.

**Y0 (DecisionHoldem) — ENTERRÉ** :
- ✅ Repo cloné, .so pre-compilées (`AlascasiaHoldem.so`, `blueprint.so`) chargent proprement sur Ubuntu 24.04 (ldd resolve, libc/libstdc++/libpthread OK)
- ✅ Wrapper Python `pypokergui/fish_player_setup.py` (117 lignes) déjà fait — API = 4 symbols ctypes
- ❌ **Bloqueur dur** : 5 fichiers binaires critiques (blueprint_strategy.dat + 4 cluster bins) uniquement sur Baidu Netdisk. Aucun mirror (HuggingFace/GitHub releases/forks tous vérifiés vides). Issue #13 repo = même demande sans réponse. Re-train hors-question (3-4j × 48 cores + Depth_limit_Search.h listé manquant par ailleurs).
- Décision user : Option C "pivot direct Y0bis, on enterre Y0".

**Y0bis (deepcfr-6p) — SMOKE PASSÉ, reste eval** :
- ✅ Repo cloné dans `C:\Users\poste113\Desktop\DEV\AN\deepcfr-6p\` (MIT, sibling de Poky)
- ✅ `flagship_models/first/` contient 2 vrais checkpoints (`1-model.pt` iter=2000 et `mixed_checkpoint_iter_11200.pt`)
- ✅ Venv Python 3.14 isolé, `pokers` Rust fork compilé en wheel local (`pokers-0.1.2-cp314-cp314-win_amd64.whl`)
- ⚠️ **Architecture mismatch** : checkpoints utilisent OLD arch (`fc1..fc6` séquentiel, 4 actions) ≠ code `main` (shared body + 2 heads, 3 actions + continuous sizing). Commit `192d6fe` marque le refactor.
- ✅ **Contournement** : shim minimal 20-lignes (`OldNet`) charge le checkpoint directement. Pas besoin de checkout l'ancien commit. Voir `deepcfr-6p/smoke_old_arch.py`.
- ✅ Smoke test : sur préflop UTG-ish, modèle renvoie Fold:18% Check/Call:47% RaiseHalfPot:15% RaisePot:20% — cohérent.

**Restant Y0bis** : ❌ TOUS TERMINÉS — **NO-GO franc**.

**Y0bis.6 résultats (5000 mains 6-max, DBerweger vs 5× HeuristicPlayer, seed 42)** :
| Test | bb/100 | ±IC95 | Verdict |
|---|---|---|---|
| `mixed_checkpoint_iter_11200` sample | **-731.72** | 72.01 | LOSES (très significatif) |
| `mixed_checkpoint_iter_11200` argmax | -734.97 | 75.92 | LOSES |
| `1-model.pt` iter 2000 sample | -701.00 | 59.08 | LOSES |

Les 5 HeuristicPlayer gagnent +100 à +175 bb/100 chacun, cohérent avec le partage des chips perdus par DBerweger (~73K / 5).

**Y0bis.7** : skippé. Si le modèle perd -700 vs HeuristicPlayer, il perd autant ou pire vs AdaptiveHeuristic + ProClaude qui sont plus forts.

**Diagnostic du NO-GO** (par ordre de probabilité) :
1. **Encoding cross-env biaisé** : bridge poky.Observation→156-dim peut différer subtilement du encode_state(pkrs.State) original (pot_chips=0 approximé, suit mapping, min_bet calcul, from_action partiel). Modèle n'a jamais vu cette distribution d'entrée.
2. **Training quality faible** : maintainer admet "peaked at 20+ chips vs random". HeuristicPlayer est >> random.
3. **Bugs dans le code d'entraînement OLD** : maintainer a refactoré justement parce que l'ancienne archi avait des regressions (issue #22) → checkpoints flagship entraînés sur du code buggué.
4. **Différences d'env subtiles** pokers (Rust) vs rlcard (poky) : min-raise, all-in handling.

Pour distinguer (1) de (2/3/4), il faudrait évaluer le modèle dans son env natif pokers vs RandomAgent (1-2h de travail). Si +20 chips → encoding fautif. Si LOSES aussi → modèle juste mauvais.

**Verdict global Y0+Y0bis** : les **deux POCs externes ont échoué** — Y0 sur l'accessibilité des données Baidu, Y0bis sur la performance réelle. Cela vindique la voie **from-scratch (Plan C = retour PLAN_PRO_BOT.md V2)** que V3 avait écarté par optimisme.

**Bridge livré** : `poky/external/dberweger_player.py` (200 lignes) + `scripts/eval_dberweger.py`. Réutilisables si on revient un jour à un autre checkpoint deepcfr-6p (re-trained avec current arch par exemple). Le shim charge n'importe quel state_dict OLD-arch fc1-fc6.

---

## 🛑 DÉCISION FINALE V3 (2026-05-28)

**User a choisi Plan C : retour from-scratch `docs/PLAN_PRO_BOT.md` V2.**

Le plan V3 entier (POC #1 + POC #2 + dual-speed + adaptive + N-max extension) est **archivé**. Les phases Y1-Y4 ne seront pas exécutées au-dessus d'un core engine externe.

Les leçons de V3 :
1. **"Validated > easy" suppose accessible** (Y0 mort sur Baidu hors-Chine)
2. **Les pre-trained externes NLHE-multi sont trop fragiles** : checkpoints obsolètes vs current arch (Y0bis), data hébergée en cloud chinois unique source (Y0), perf claims overstated par maintainers eux-mêmes (description.md deepcfr-6p admet "20+ chips vs random"), envs différents (rlcard ≠ pokers ≠ DecisionHoldem custom).
3. **Le coût d'un POC externe** (clone + setup + bridge + eval) est de l'ordre de **15-30h** par tentative — au moins aussi cher que progresser de quelques jours sur le from-scratch.
4. **Bridge code conservé** : `poky/external/dberweger_player.py` peut servir si plus tard quelqu'un re-trained deepcfr-6p avec current arch (peu probable mais possible).

**Prochaine session : ouvrir `docs/PLAN_PRO_BOT.md` (V2) et reprendre depuis la phase X courante.**

**Gotchas techniques à retenir** :
- `pkrs.State.from_seed(...)` crash silencieusement (exit 5) avec kwargs sur Python 3.14 + pokers @b1a48bd. **Toujours utiliser positional args** : `pkrs.State.from_seed(6, 0, 1.0, 2.0, 200.0, 42)`.
- `torch.load(weights_only=False)` bloqué par classifier (sécurité pickle). Défaut `weights_only=True` fonctionne pour les state_dicts standards (cas de nos checkpoints).
- Pour évaluer pré-trained externes : **toujours vérifier la compat state_dict** avant de planifier l'eval. Look at `ckpt['advantage_net'].keys()` vs current model architecture.
