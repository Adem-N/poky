# Plan Pro Bot Poky — atteindre niveau pro (révisé 2026-05-28)

## Contexte

Le projet a atteint un état MVP solide (Phases 1-6 livrées) mais le bot MCCFR n'est PAS au niveau pro :
- HeuristicPlayer (rules) : champion play-ready (6 BEATS / 3 DRAW / 0 LOSES gauntlet)
- BlueprintPlayer (1.75M iters) : -28 ± 37 bb/100 vs HeuristicPlayer (perd légèrement)
- CFRPlayer (blueprint + subgame solver 2s) : -92 ± 246 bb/100 (statistiquement indistinguable)

**Insight utilisateur (validé)** : au lieu de l'entraînement aveugle, **injecter du savoir pro** (ranges GTO publiées) comme warm-start, puis raffiner par self-play. C'est l'architecture qu'AlphaGo a utilisée (SL → RL), et c'est la voie réaliste pour le poker vu nos ressources.

**Objectif** : bot **niveau pro** = bat de manière fiable les bons joueurs amateurs et les regs de petites limites. Pluribus-tier (bat les pros mondiaux) reste hors de portée d'un projet perso.

**Contrainte temps** : pas de deadline, qualité prime. Budget compute : OK pour vast.ai ($100-300 sur la durée).

---

## Architecture cible (5 tiers)

```
TIER 1 — Expert Knowledge (HARDCODÉ, NOUVEAU)
   Ranges GTO préflop par position + situation
   Principes postflop (c-bet, defense, bet sizing)
   Source : charts publiées (Snowie/GTOWizard/Pio outputs)
   ↓
TIER 2 — Equity Heuristics (DÉJÀ FAIT)
   HeuristicPlayer + AdaptivePlayer
   Monte Carlo equity + pot odds + position
   ↓
TIER 3 — CFR Refinement (DÉJÀ FAIT MVP, À AMÉLIORER)
   MCCFR blueprint warm-startée depuis Tier 1+2
   Self-play pour patcher les leaks que les rules manquent
   ↓
TIER 4 — Real-time Subgame Solving (DÉJÀ FAIT MVP, À AMÉLIORER)
   CFR sur sous-jeu courant pendant ~5-30s par décision
   ↓
TIER 5 — Opponent Modeling (DÉJÀ FAIT MVP)
   VPIP/PFR/AF tracking, profil-aware adjustments
```

**Le bot live (CFRPlayer v2) consulte les 5 tiers en cascade** : si Tier 5 détecte un exploit, agit. Sinon Tier 4 raffine. Sinon Tier 3 blueprint. Sinon Tier 2 heuristic. Sinon Tier 1 par défaut.

---

## Phases (~12-16 semaines de travail, 2 sessions × 4h/semaine)

### Phase X1 — Tier 1 : ranges GTO hardcodées (2-3 semaines)

**Quoi** : Injecter les ranges GTO publiées comme stratégie de base, par position et situation.

**Couverture minimale** :
- HU : open BTN, 3-bet BB vs BTN, 4-bet BTN vs 3-bet, call/raise BB
- 3-max : open BTN, open SB, 3-bet SB/BB vs BTN, 3-bet BB vs SB
- 6-max : open UTG/HJ/CO/BTN/SB, 3-bet patterns
- Toutes à 100bb effective stack (le plus étudié)
- Mix d'actions (frequencies, pas pure)

**Livrables** :
- `poky/expert/preflop_ranges.py` : dictionnaires position → hand → frequency_per_action
- Source data : charts publiques converties en JSON
  - GTOWizard free charts (https://gtowizard.com/free-resources/)
  - Snowie advisor screenshots → transcripts manuels
  - PokerCoaching free ranges
- `poky/expert/range_lookup.py` : fonction `pro_preflop_strategy(hole, position, action_context) -> List[(action, freq)]`
- Tests : vérifier des spots canoniques (AA toujours 3-bet/4-bet, 72o toujours fold UTG, etc.)

**Estimation** : 60-80h (recherche charts + parsing + tests)

**Critère de succès** : `ExpertOnlyPlayer` (qui ne joue QUE les ranges Tier 1 + heuristic Tier 2 postflop) bat HeuristicPlayer de +5 bb/100 minimum.

---

### Phase X2 — Tier 1 postflop principles (1-2 semaines)

**Quoi** : Encoder les principes postflop pro (c-bet sizing par texture, defense ranges, donk frequencies).

**Livrables** :
- `poky/expert/postflop_rules.py` : 
  - `cbet_decision(board_texture, sizing_option, ip_oop, ranges_in_play) -> action_freq`
  - `defense_vs_cbet(board, my_hand_class, position) -> action_freq`
  - Texture classifier : dry / wet / dynamic / locked
- Tests sanity : board AKx mid-equity → IP c-bet à 70% par défaut, etc.

**Estimation** : 30-50h

**Critère** : ajouter postflop rules au ExpertOnlyPlayer donne +2 bb/100 supplémentaires.

---

### Phase X3 — Multi-process MCCFR (1-2 semaines)

**Quoi** : Refactor MCCFR pour exploiter tous les cœurs CPU. Critique pour scaler le compute.

**Livrables** :
- `poky/training/mccfr_parallel.py` : workers en multiprocessing.Pool
- Partage de la table de stratégie via fichier mémoire mappé (mmap) ou Manager
- Synchronisation périodique des regrets entre workers
- `scripts/train_blueprint_mp.sh` : version multi-process du training overnight

**Optimisations annexes** :
- Réduire le _BUCKET_CACHE à 1M (fix la pression mémoire qui a causé le slowdown overnight)
- Cython/numba sur le hot path d'apply() (10-50× speedup possible)
- `poky/training/hunl_state.py` : numpy-vectorized batch state operations

**Estimation** : 60-80h

**Critère** : speedup ≥ 6× sur ton 8-core. Doit pouvoir faire 50M iters en 24h vs 5M actuellement.

---

### Phase X4 — Hybrid blueprint training (1 semaine + compute)

**Quoi** : Entraîner un blueprint warm-starté avec les ranges Tier 1.

**Livrables** :
- `poky/training/hybrid_mccfr.py` : 
  - Initialise les regrets pour matcher les ranges Tier 1 (pas zero)
  - Self-play raffine à partir de cette base "déjà pro"
- Convergence devrait être 5-10× plus rapide que from-scratch
- `scripts/train_hybrid.ps1` : training overnight 50M+ iters multi-process

**Compute** : laptop 24-48h, ou vast.ai $30-80 pour finir plus vite.

**Estimation** : 30-40h code + temps d'attente

**Critère** : blueprint hybride bat ExpertOnlyPlayer de +3 bb/100 sur 10k mains.

---

### Phase X5 — Subgame solver v2 (1-2 semaines)

**Quoi** : Améliorations critiques du solver actuel (Phase 6 MVP).

**Améliorations** :
- **Range-based solving** (pas sampling) : au lieu de sample 1 main adversaire par iter, conserver la distribution complète et faire CFR vectorisé sur ranges
- **Cached subgame trees** : si on revient à un état similaire (rare en HU mais possible), réutiliser
- **Dynamic time budget** : 1s pour décisions banales (préflop fold), 10s pour décisions critiques (river call)
- **Lazy depth limit** : ne pas dérouler jusqu'à terminal, utiliser blueprint comme value function aux leaves

**Livrables** :
- `poky/cfr/subgame_solver_v2.py`
- `poky/cfr/value_estimator.py` : leaf values via blueprint EV
- Tests : v2 doit battre v1 de +5 bb/100 minimum sur 500 mains

**Estimation** : 40-60h

---

### Phase X6 — Extension 3-max et 6-max (2 semaines)

**Quoi** : Étendre les Tier 1 et MCCFR aux tables multi-joueurs.

**Livrables** :
- Phase X1+X2 ranges étendues à 3-max et 6-max
- `poky/training/mccfr_nmax_v2.py` : version optimisée multi-process
- `poky/players/nmax_cfr_player.py` : équivalent CFRPlayer pour N-max
- Tests gauntlet 3-max et 6-max

**Critère** : NMaxCFRPlayer bat AdaptiveHeuristicPlayer sur 3-max gauntlet.

---

### Phase X7 — Évaluation finale + iteration (ongoing)

**Tests requis** :
1. Vs HeuristicPlayer 10k mains HU et 3-max → cible +15 bb/100
2. Vs AdaptiveHeuristicPlayer 10k mains → cible +10 bb/100
3. Vs ProClaude (notre proxy humain) 5k mains → cible +5 bb/100
4. Gauntlet complète 3/6/9-max → tous BEATS ou DRAW
5. Exploitability sur sous-jeu mesurée (best response value)
6. **Vs humains réels** : tu joues 200+ mains via `poky.cli.play` contre `cfr_v2`. Doit gagner ou être très serré.

Si tous critères passent → niveau pro atteint pour notre définition.

Si non → analyser les leaks, retour Phase X3-X5 ciblé.

**Estimation** : 20-40h évaluation + iterations multiples

---

## Compute budget total

- Phase X1-X2 : 0 (juste du code)
- Phase X3 : 0 (refactor)
- Phase X4 : ~$30-80 vast.ai (1 semaine de compute serveur)
- Phase X5 : 0 (algo work)
- Phase X6 : ~$50-150 vast.ai
- **Total : $80-230 en compute**

## Temps total

- 8 sessions/mois × 4h × 4 mois = 128h actif
- Plus temps d'attente compute (peut tourner overnight, weekend)
- **Total : 3-4 mois calendaires** réalistement

---

## Ressources externes à utiliser

**Charts GTO** :
- GTOWizard free : https://gtowizard.com/free-resources/
- Upswing Poker free preflop charts : https://upswingpoker.com/poker-charts/
- Run It Once free ranges (certaines)

**Tools** :
- `holdem-eval` (Python lib) si on veut équité plus rapide
- `treys` si phevaluator se montre limitant

**Papers de référence** :
- Brown & Sandholm 2017 "Safe and Nested Subgame Solving" (CFR-D)
- Brown & Sandholm 2019 "Solving Imperfect-Information Games via Discounted Regret Minimization" (Linear/Discounted CFR)
- Brown & Sandholm 2019 "Superhuman AI for multiplayer poker" (Pluribus)
- Lanctot et al. 2009 "Monte Carlo Sampling for Regret Minimization" (MCCFR variants)

---

## État du code au début de cette nouvelle phase

**Foundation solide existante (NE PAS toucher)** :
- `poky/engine/`, `poky/equity/`, `poky/arena/`, `poky/abstraction/preflop.py`, `poky/cli/*`
- `poky/players/heuristic.py`, `adaptive.py`, archetypes
- `poky/training/kuhn_cfr.py` (validé), `leduc_cfr.py` (validé)

**À étendre** :
- `poky/abstraction/postflop.py` : K=5 → K=10, ajouter clustering OCHS
- `poky/training/mccfr_hunl.py` et `mccfr_nmax.py` : version parallèle
- `poky/cfr/subgame_solver.py` : v2 avec range-based

**Nouveau** :
- `poky/expert/` : tout nouveau package pour Tier 1
- `poky/training/hybrid_mccfr.py`

**Modèles à régénérer après refactor** :
- `data/blueprint_hu/overnight_5M.pkl` : à re-entrainer avec hybrid
- `data/blueprint_3max/` : à entrainer (Phase B tourne actuellement, le résultat sera baseline)

---

## Ordre d'exécution recommandé

```
Session 1-2  : Phase X1 partie 1 (HU ranges)        — 8h
Session 3-4  : Phase X1 partie 2 + tests             — 8h
Session 5-6  : Phase X2 (postflop rules)             — 8h
Session 7-9  : Phase X3 (multi-process)              — 12h
Session 10   : Phase X4 setup + lancer training     — 4h
[Compute en background, jours/semaines]
Session 11-12: Phase X5 (subgame v2)                — 8h
Session 13-15: Phase X6 (3-max+6-max)               — 12h
Session 16-20: Phase X7 (eval continue + fixes)     — 20h
```

Total ~80h actif sur 4 mois.

---

## Définition de "succès final"

Le bot est considéré **pro-level pour notre projet** quand :

1. ✅ Bat HeuristicPlayer de +15 bb/100 sur 10 000 mains heads-up
2. ✅ Bat AdaptiveHeuristicPlayer de +10 bb/100 sur 10 000 mains
3. ✅ Bat ProClaude de +5 bb/100 sur 5 000 mains
4. ✅ Tournament 3-max et 6-max : 0 LOSES
5. ✅ Le créateur du projet (toi) joue 200 mains contre lui via CLI et le trouve **vraiment dur à battre**

Critère 5 est subjectif mais c'est le test ultime — si tu sens que tu perds clairement contre lui, c'est qu'il joue vraiment bien.

---

## Notes pour la session suivante (après /clear context)

Quand le user fait /clear et qu'un fresh-me reprend :
1. Lire ce fichier (`docs/PLAN_PRO_BOT.md`)
2. Lire `docs/STATUS.md` pour l'état détaillé du code
3. Lire `MEMORY.md` dans `~/.claude/projects/.../memory/` pour le contexte utilisateur
4. Démarrer par Phase X1 sauf si user dit autre chose
5. Le user est passionné, technique, et veut un VRAI bot pro. Pas de bullshit.
