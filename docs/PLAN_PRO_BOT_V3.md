# Plan Pro Bot Poky V3 — basé sur recherche état de l'art (2026-05-28)

## TL;DR du changement vs V2

**V2 (abandonné)** : re-implémenter blueprint MCCFR + subgame solver from scratch en Python pur. Honnête mais lent : 3-4 mois pour atteindre peut-être niveau pro.

**V3 (proposé)** : **adapter DecisionHoldem** (pre-trained C++ bot qui bat Slumbot à +730 mbb/h) comme moteur core, et construire **autour** :
- Adaptive exploitation layer (population reads + opponent modeling)
- Mode dual-speed (slow pour cash regular, fast pour Nitro/Zoom)
- Extension N-max (DecisionHoldem est HU uniquement)
- UI / orchestration

**Gain estimé** : 3-4 mois → 4-6 semaines pour niveau pro confirmé en HU.

---

## Architecture V3

```
┌─────────────────────────────────────────────────────────────┐
│  CORE ENGINE (DecisionHoldem, C++ pre-trained, AGPL)        │
│  HU NLHE blueprint 200M iters + depth-limited subgame solver│
│  Niveau pro PROUVÉ (bat Slumbot, bat DeepStack reproduction)│
└─────────────────────────────────────────────────────────────┘
                          ▲ Python bindings
                          │
┌─────────────────────────────────────────────────────────────┐
│  POKY ORCHESTRATION (notre Python)                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ DUAL-SPEED ROUTER                                     │  │
│  │  - Slow mode (cash regular) : full DecisionHoldem    │  │
│  │  - Fast mode (Nitro / Zoom) : blueprint-only lookup  │  │
│  │  Switching auto selon time_budget détecté            │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ADAPTIVE EXPLOITATION LAYER (notre Tier 5 du V2)     │  │
│  │  - Population reads (par poker room / format)        │  │
│  │  - Individual opponent modeling (VPIP/PFR/AF)        │  │
│  │  - Switch GTO ↔ Exploit selon confiance            │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ N-MAX EXTENSION (notre code MCCFR_nmax existant)     │  │
│  │  Pour 3-max, 6-max, 9-max où DecisionHoldem n'est    │  │
│  │  pas applicable (HU only)                            │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ FALLBACK : HeuristicPlayer + AdaptivePlayer          │  │
│  │  Si tout le reste échoue                              │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Phases V3

### Phase Y1 — POC DecisionHoldem (1-2 semaines)

**Risque clé du plan** : DecisionHoldem doit être utilisable sur notre stack.

**Tasks** :
- Cloner repo `AI-Decision/DecisionHoldem`
- Lire les .so / .py / docs disponibles
- Compiler sur WSL Linux (les .so sont Linux x86_64)
- OU utiliser un VM Linux léger / Docker
- Lancer le bot vs Slumbot via leur infra de test pour confirmer perfs
- Écrire wrapper Python `poky.cfr.decisionholdem_engine` :
  - `get_action(obs) -> Action` qui appelle le bot C++
  - Conversion obs rlcard ↔ format DecisionHoldem

**Livrable** : `poky/players/decisionholdem_player.py` qui joue HU NLHE via le moteur C++.

**Critère succès** :
- Le bot bat HeuristicPlayer de **+30 bb/100** minimum sur 1000 hands
- Latence < 5s par décision (acceptable pour cash regular)

**Critère KO** : si on n'arrive pas à le faire tourner en 2 semaines, on revient au Plan V2.

**Estimation** : 40-60h

---

### Phase Y2 — Adaptive Exploitation Layer (1 semaine)

**Quoi** : Construire la couche d'adaptation par-dessus DecisionHoldem (qui joue GTO pur).

**Couche dévie les probabilités** selon :
- Profil adverse détecté (déjà fait dans AdaptiveHeuristicPlayer)
- Population reads par room/format
- Type de session (fast-fold vs regular)

**Livrables** :
- `poky/expert/exploit_adjustments.py` : tables de déviation par profil×situation
- `poky/players/adaptive_decisionholdem.py` : wrapper qui combine DecisionHoldem + adaptation
- Tests A/B : DecisionHoldem nu vs DecisionHoldem+adaptation sur table mixte

**Critère succès** : +5 bb/100 vs DecisionHoldem nu sur table mixte (TAG+LAG+Fish+Maniac+Nit)

**Estimation** : 30-40h

---

### Phase Y3 — Mode dual-speed (1 semaine)

**Quoi** : Router intelligent qui choisit entre slow et fast mode selon contexte.

**Slow mode** (cash regular, ~10s/main moyenne) :
- Full DecisionHoldem avec depth-limited solving
- Latence 2-5s par décision
- Précision maximale

**Fast mode** (Nitro, Zoom, Hyper-Turbo, ~3s/main) :
- Blueprint-only lookup (skip le real-time solving)
- Latence <100ms par décision
- Précision légèrement réduite mais largement suffisante (le Nitro pool est weaker)

**Détection auto** :
- Time-since-last-action observé → infère le format
- OU paramètre explicite (`--mode nitro|cash|tournament`)

**Adjustments fast-fold** (par recherche) :
- C-bet sizing 25-40% pot (au lieu de 50-66%)
- Open sizes 2x-2.25x (au lieu de 2.5x-3x)
- 3-bet linéaire (value + bluff continu) plutôt que polarisé
- Cbet 75-85% range avec smaller sizings
- Skip thin value bets, polarize au lieu
- Tighten call-downs vs multi-street aggression

**Livrables** :
- `poky/cfr/dual_speed_router.py` : choisit le mode
- `poky/expert/fast_fold_adjustments.py` : modifications pour Nitro/Zoom
- Mode `fast` activable via param

**Critère succès** : fast mode latence < 100ms, garde >90% du winrate du slow mode contre HeuristicPlayer.

**Estimation** : 30-40h

---

### Phase Y4 — Population reads (population-level HUDs) (1 semaine)

**Insight pro** : en fast-fold, individual HUDs ne s'accumulent pas (anonyme). Mais POPULATION leaks oui — la masse fold trop, c-bet trop, etc.

**Tasks** :
- Track stats par **POOL** (pas par opponent) :
  - Format (Nitro vs Cash regular)
  - Stake (micro / low / mid / high)
  - Room (Winamax, PokerStars, etc.)
- Adjustments basés sur les profils pool typiques

**Données** :
- Le user peut importer ses propres hands histories (Winamax export)
- On fait stats agrégées
- OU on hardcode des profils pool publiés (Upswing/Red Chip blogs)

**Livrables** :
- `poky/expert/population_profiles.py` : profils pool par room+format+stake
- Integration dans dual_speed_router

**Estimation** : 25-30h

---

### Phase Y5 — Extension N-max (2-3 semaines)

**Quoi** : DecisionHoldem est HU only. Pour 3-max, 6-max, on garde notre code existant (mccfr_nmax.py) mais on l'améliore.

**Tasks** :
- Réutiliser notre `NMaxMCCFRTrainer` et `NMaxBlueprintPlayer`
- Améliorer abstractions postflop (K=10 ou OCHS-like)
- Multi-process self-play (déjà planifié V2)
- Warm-start depuis ranges GTO 6-max (RangeConverter free charts)
- Training overnight 3-max et 6-max

**Critère** : `nmax_cfr_player` bat AdaptiveHeuristic sur 3-max gauntlet (DRAW minimum).

**Estimation** : 60-80h

---

### Phase Y6 — Évaluation finale + iteration (ongoing)

**Tests** :
1. HU NLHE 100bb : DecisionHoldem+adaptive vs HeuristicPlayer → cible +50 bb/100 sur 5000 mains (DecisionHoldem nu fait déjà ce score contre Slumbot, donc largement faisable contre notre heuristic)
2. HU NLHE 50bb shallow stack : même bot adapté → cible +30 bb/100
3. 3-max NLHE : `nmax_cfr_player` vs AdaptiveHeuristic → cible +10 bb/100
4. 6-max NLHE : idem → cible +5 bb/100
5. Fast mode Nitro simulé : winrate ≥ 80% du slow mode
6. **User joue 200 mains contre notre bot final** → "vraiment dur à battre" subjectif

**Critère pro-level** : 5/6 critères passés.

**Estimation** : 40h continu sur weeks d'itération

---

## Budget total V3

- Phase Y1 : 40-60h (POC DecisionHoldem)
- Phase Y2 : 30-40h (adaptive layer)
- Phase Y3 : 30-40h (dual-speed)
- Phase Y4 : 25-30h (population reads)
- Phase Y5 : 60-80h (N-max)
- Phase Y6 : 40h (eval+iter)
- **Total : 225-290h = 4-7 semaines à 40h/semaine**

Compute : minimal (DecisionHoldem déjà entraîné), peut-être $20-50 si on doit refaire des trainings N-max.

---

## Plan B : si DecisionHoldem ne fonctionne pas

Si Phase Y1 échoue (incompatibilité WSL, license, perf), on revient au **Plan V2** (re-implémenter from scratch). Long mais réalisable.

---

## Choix philosophiques validés par la recherche

1. **GTO + Exploit** : confirmé par paper Patrick 2025 et par la pratique fast-fold pro
2. **Population reads en fast-fold** : insight clé qu'on n'avait pas
3. **Dual-speed nécessaire** : 5s/décision impossible en Nitro
4. **Pre-trained model preferable to from-scratch** : DecisionHoldem prouve qu'on peut

---

## Notes pour la prochaine session (post /clear)

Fresh-context-me doit :
1. Lire ce fichier (`docs/PLAN_PRO_BOT_V3.md`)
2. Démarrer par **Phase Y1** : cloner DecisionHoldem, vérifier compatibilité Windows/WSL
3. Si Y1 réussit → bot pro en 4-6 semaines
4. Si Y1 échoue → fallback Plan V2 (long format)

Sources clés :
- DecisionHoldem : https://github.com/AI-Decision/DecisionHoldem
- DeepStack-Leduc (référence) : https://github.com/lifrordi/DeepStack-Leduc
- PyStack (alternative) : https://github.com/doas3140/PyStack
- Free GTO ranges : https://rangeconverter.com/free-poker-charts
- Paper Patrick 2025 (max-exploit) : https://arxiv.org/abs/2512.04714
- Fast-fold strategy guide : https://www.vip-grinders.com/poker-strategy/fast-fold/
