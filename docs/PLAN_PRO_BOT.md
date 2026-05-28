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

## Architecture cible (5 tiers, ARCHITECTURE ADAPTATIVE)

**Principe clé** : les ranges GTO ne sont PAS des règles rigides — c'est une *connaissance de référence*, comme un livre de théorie qu'un pro a lu. Le bot **part** de ces ranges mais s'en **écarte dynamiquement** selon : le profil adverse, le résultat du self-play, l'analyse de la situation spécifique.

```
TIER 1 — Knowledge Base (RÉFÉRENCE, pas obligation)
   - Ranges GTO publiées comme "stratégie par défaut quand inconnu"
   - Mixed frequencies (ex AKs 3-bet 70% / call 30%) — déjà non-déterministe
   - Le bot CONNAÎT ces ranges mais peut les ignorer
   - Utilisé comme warm-start pour MCCFR (Tier 3)
   ↓
TIER 2 — Equity-aware play (DÉJÀ FAIT)
   - HeuristicPlayer + AdaptivePlayer
   - Monte Carlo equity, pot odds, position
   - Fallback robuste si autres tiers indisponibles
   ↓
TIER 3 — CFR Learning (DÉJÀ FAIT MVP, À ÉTENDRE)
   - MCCFR self-play, warm-startée depuis Tier 1+2
   - **Peut S'ÉLOIGNER des ranges GTO** si self-play trouve mieux
   - Découvre les leaks que les rules manquent
   - Multi-process pour scale
   ↓
TIER 4 — Real-time Subgame Solver (DÉJÀ FAIT MVP, À AMÉLIORER)
   - CFR sur sous-jeu courant, 5-30s par décision
   - Considère la situation SPÉCIFIQUE (cartes board, ranges déduites adverses)
   - **Range estimation basée sur les actions observées de l'adversaire**, pas hardcodée
   ↓
TIER 5 — Adaptive Exploitation (NOUVEAU + extension de l'existant)
   - VPIP/PFR/AF tracking par adversaire (déjà)
   - **Déviations CALCULÉES des ranges GTO selon profil détecté** :
     • vs nit (VPIP<15) : steal +30%, fold to 3-bet +20%
     • vs fish (VPIP>40 + low AF) : value bet wider, supprime bluffs
     • vs maniac (high AF) : call down lighter, 3-bet polarisé
     • vs TAG/inconnu : reste GTO
   - **Switch dynamique GTO ↔ Exploit** : confiance dans le modèle adverse
```

**Le bot live consulte les tiers en CASCADE D'INFLUENCE** (pas de fallback) :
1. Tier 1 fournit la base (ce que GTO dirait)
2. Tier 3 modifie selon ce que le self-play a appris
3. Tier 4 raffine selon la situation spécifique (real-time CFR)
4. Tier 5 dévie selon le profil adverse détecté
5. Tier 2 sert de garde-fou (équité sanity check)

**Le bot N'EST JAMAIS hardcodé sur une seule action** : à chaque info-set il a une distribution de probabilités, modifiée par tous les tiers.

---

## Phases (~12-16 semaines de travail, 2 sessions × 4h/semaine)

### Phase X1 — Tier 1 : ranges GTO comme RÉFÉRENCE (2-3 semaines)

**Quoi** : Charger les ranges GTO publiées comme **connaissance de référence**, pas comme règles obligatoires. Le bot consulte ces ranges mais le Tier 3 (MCCFR) peut dévier librement, et le Tier 5 (adaptive) module selon l'adversaire.

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

### Phase X4.5 — Tier 5 : Adaptive Exploitation (NOUVEAU, 1 semaine)

**Quoi** : Étendre `AdaptiveHeuristicPlayer` pour devenir une couche de **déviation calculée** au-dessus de la stratégie de base.

**Logique** : pour chaque opposant, on a un profil estimé (déjà tracké). Selon ce profil, on calcule des "modificateurs" qu'on applique aux probabilités d'action du bot.

**Livrables** :
- `poky/expert/exploit_adjustments.py` :
  - `compute_deviation(base_strategy, opp_profile, situation) -> adjusted_strategy`
  - Tables d'ajustement par profil × situation (sourced from poker theory) :
    * vs NIT : multiplie bet_freq × 1.3, fold_to_3bet × 1.2
    * vs FISH : value_bet_threshold ÷ 1.2, bluff_freq × 0.5
    * vs MANIAC : call_threshold ÷ 1.3, polarize_3bet
    * vs TAG : ~GTO, légère agression supplémentaire
- `poky/players/exploitation_layer.py` : wrapper qui prend n'importe quel bot et applique des déviations
- **Switch dynamique GTO ↔ Exploit** :
  * Si sample size < 30 → 100% GTO
  * Si sample size 30-100 → mix progressif
  * Si sample size > 100 + profil clair → full exploit
  * Si profil incohérent / changeant → revient à GTO (l'adversaire est un meta-player)

**Critère succès** : sur table de profils mixtes (TAG + LAG + Maniac + Nit + Fish), le bot avec exploitation layer gagne +3 bb/100 vs même bot sans la couche.

**Estimation** : 30-40h

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

## Philosophie d'adaptation (clarification importante)

**Le bot N'EST PAS un simple lookup de ranges hardcodées.** À chaque décision en live :

1. **Détermine la base** : ranges GTO (Tier 1) modifiées par ce que MCCFR a appris (Tier 3) → donne une distribution de probabilités initiale
2. **Raffine la situation** : subgame solver (Tier 4) ajuste selon les cartes spécifiques + ranges adverses déduites des actions observées dans la main
3. **Exploite si possible** : couche adaptive (Tier 5) module les probabilités selon le profil de l'adversaire détecté sur les hands précédentes
4. **Sample** : tire l'action selon la distribution finale

**Le bot dévie en permanence.** Deux décisions dans la même situation peuvent être différentes (mixed strategy). Et la même situation avec un adversaire différent donne des stratégies différentes.

**Garde-fous contre le "trop d'exploit"** :
- Sample size minimum avant de dévier (30 hands de profil clair)
- Si profil incohérent → revient en GTO
- Adversaire qui semble adapter SES exploitation → assume meta-player, joue GTO
- Toujours un certain pourcentage de mixed pour rester non-exploitable

C'est l'architecture utilisée par Pluribus pour 6-max NLHE (Brown & Sandholm 2019).

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
