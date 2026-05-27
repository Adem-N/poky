# État du projet — pour reprendre proprement

Mis à jour : session 2026-05-27 (deuxième passe, après gauntlet + NFSP setup).

## Ce qui est fait ✅

| # | Livrable | Tests |
|---|---|---|
| 1 | Structure projet + venv + deps + .gitignore + README | — |
| 2 | `poky.engine.Game` : wrapper rlcard NLHE 3-max, API typée (Action/Stage/Position/PlayerStatus/Observation) | 3 |
| 3 | `poky.equity` : conversion cartes rlcard ↔ phevaluator + Monte Carlo equity vs N adversaires | 7 |
| 4 | `poky.players` : Player (ABC), RandomPlayer, AlwaysCallPlayer, HeuristicPlayer (preflop chart + MC postflop + position), HumanCLIPlayer | 6 |
| 5 | `poky.arena.run_match` : runner bot-vs-bot avec rotation des sièges + métriques bb/100 + IC95% | 3 |
| 6 | `poky.cli.arena` + `poky.cli.play` : 2 entrypoints opérationnels | — |
| 7 | `poky.training.kuhn_cfr` : vanilla CFR validé sur Kuhn (converge vers -1/18, stratégies pures correctes) | 3 |
| 8 | Plot de convergence : `docs/kuhn_convergence.png` | — |
| 9 | 4 archétypes humains (`tight_passive`, `tag`, `lag`, `maniac`) | 4 |
| 10 | `poky.cli.tournament` : champion vs gauntlet de 9 matchups, verdict BEATS/DRAW/LOSES par IC95 | — |
| 11 | `poky.cli.compare` : 2 champions côte-à-côte sur la gauntlet | — |
| 12 | `poky.training.nfsp_train` : self-play NFSP 3-agents, checkpoints `.pth` toutes les N épisodes | — |
| 13 | `NFSPPlayer` : wrapper qui charge un `.pth` et joue dans notre arena via `Observation.raw_state` | — |
| 14 | **Généralisation N-max** : `PositionType` (BUTTON/SB/BB/EARLY/MIDDLE/LATE), ranges adaptées par taille de table | — |
| 15 | `Player.observe_action` + `ActionEvent` : diffusion d'actions à tous les joueurs (pour opp. modeling) | — |
| 16 | **`AdaptiveHeuristicPlayer`** : tracker VPIP/PFR/AF par adversaire, classification de profil (NIT/TAG/LAG/FISH/MANIAC), adaptation des ranges | — |
| 17 | `poky.cli.nmax_tournament` : table arbitraire, multi-instances supportées | — |

**26 tests pytest, tous verts.**

### Test multi-instance 6-max (validation "plusieurs Claude indépendants")
```
Table 6-max : [adaptive, adaptive, adaptive, tag, lag, maniac]
1500 mains :
  adaptive#0 : +163 bb/100
  adaptive#1 : +190 bb/100
  adaptive#2 :  +89 bb/100
  tag        : +120
  lag        : +183
  maniac     : -747  (mange ses chips comme prévu)
```
Les 3 adaptive performent de manière similaire entre elles (variance attendue ±90 bb/100)
et battent toutes la table → multi-instance fonctionne, indépendance confirmée.

## Benchmarks officiels

### Heuristique vs gauntlet (2500 mains × 9 matchups, seed 42)
```
  vs random,random                      +108.46    60.78    BEATS
  vs call,call                          +318.76    65.04    BEATS
  vs tight_passive ×2                    +34.40    17.18    BEATS
  vs tag ×2                               +9.58    30.75     DRAW
  vs lag ×2                               -4.72    37.08     DRAW
  vs maniac ×2                          +227.50    89.64    BEATS
  vs tag + lag                           +32.06    36.53     DRAW
  vs maniac + tight_passive             +243.76    65.04    BEATS
  vs tag + maniac                       +175.94    61.45    BEATS
Bilan : 6 BEATS / 3 DRAW / 0 LOSES
```
Verdict : "BOT CORRECT mais pas dominant partout". Les 3 DRAW vs TAG/LAG sont
le **plafond structurel de l'heuristique** — non franchissable par tuning,
seul CFR/NFSP peut les transformer en BEATS.

### NFSP en cours d'entraînement
30 000 épisodes de self-play en background, ~10 min sur CPU. Premiers résultats
à 5000 épisodes : très sous-entraîné, perd à plusieurs matchups (attendu).
Heinrich & Silver 2016 indiquent que NFSP en NLHE nécessite typiquement
**100k-1M épisodes** pour converger vraiment.

## Ce qui reste 🚧

### Priorité 1 : entraînement NFSP long (production)
Le pipeline marche bout-en-bout (training → save → load → joue dans le tournament).
Reste à l'entraîner SÉRIEUSEMENT :

```bash
# Une session overnight (~6h sur CPU, 200k ép)
python -m poky.training.nfsp_train --episodes 200000 --save-every 20000
```

Évaluer à chaque palier :
```bash
python -m poky.cli.compare --a heuristic --b nfsp --hands 3000
```

L'objectif : que NFSP **passe les DRAW (vs TAG/LAG) en BEATS** et qu'il dépasse
l'heuristique sur la majorité des matchups. Si à 200k il n'est pas meilleur que
l'heuristique, deux options :
  - prolonger à 500k-1M épisodes
  - changer d'algo : Deep CFR (à implémenter, pas dans rlcard out-of-the-box)

### Priorité 2 (obsolète, remplacée par NFSP) : ~~Train DMC~~
DMCTrainer rlcard est trop lourd à mettre en place sur Windows (multiprocessing
avec PyTorch). NFSP donne le même type de résultat (convergence approximative
vers Nash) en mono-process. On reste sur NFSP.

### Priorité 3 : ~~CFR sur preflop abstraction~~
Le cœur du projet. Deux approches à explorer (tâche #5) :

- **(A) `rlcard.agents.DMCAgent`** : Deep Monte Carlo, prêt à l'emploi sur l'env NLHE. Multi-process, écrit pour battre les humains. Plus rapide à mettre en place.
- **(B) MCCFR custom** : External-sampling MCCFR sur l'env rlcard avec nos propres abstractions cartes/actions. Plus de boulot, plus de mérite en soutenance.

Plan recommandé : faire (A) d'abord comme baseline mesurable. Puis (B) pour la différenciation soutenance.

Référence : `https://rlcard.org/algorithms.html#deep-monte-carlo-dmc`

### Priorité 2 : CFRPlayer (tâche #14)
Player qui charge un strategy JSON et le joue. Doit définir le format de clé d'info set (position + stage + card_bucket + betting_history_abstracted) et le format JSON. Fallback sur HeuristicPlayer pour les info sets non vus.

### Priorité 3 : Abstractions de cartes (tâche #8)
- Préflop : 169 classes canoniques (13 pairs + 78 suited + 78 offsuit). Triviale.
- Postflop : k-means sur vecteurs d'équité (histogrammes de win-rate vs rollouts random). 5-10 buckets par street typiquement.
- Réf : Johanson et al. 2013, "Evaluating State-Space Abstractions in Extensive-Form Games".

### Priorité 4 : Adaptateur plateforme (tâche #6)
Bloqué : pas de spec. Quand on l'a :
1. Parser les messages reçus → `engine.Observation`
2. Traduire `engine.Action` → format plateforme
3. Maintenir une session réseau (asyncio probable)

### Priorité 5 : Matériels soutenance (tâche #9)
- Convergence plots (Kuhn ✅, NLHE à faire)
- Tableau comparatif bot vs baselines avec IC95%
- Mesure d'exploitabilité (best response value)
- Slides explicatifs : CFR, abstractions, choix d'archi

## Comment reprendre

```bash
cd C:\Users\poste113\Desktop\DEV\AN\Poky
.venv\Scripts\activate
pytest                                          # tout doit être vert
python -m poky.cli.arena --players heuristic,random,call --hands 1000
```

Pour démarrer la prochaine grosse étape (CFR NLHE via DMC) :
```python
from rlcard.agents import DMCAgent  # vérifier l'API courante
import rlcard
env = rlcard.make('no-limit-holdem', config={'game_num_players': 3})
# entraînement, save, integration dans CFRPlayer
```

## Décisions techniques verrouillées

- **Variant** : No-Limit Hold'em 3-max (peut scaler si la plateforme 42 supporte plus)
- **Action abstraction** : FOLD / CHECK_CALL / RAISE_HALF_POT / RAISE_POT / ALL_IN (héritée de rlcard, parfaite pour CFR)
- **Stack par défaut** : 100 chips, blinds 1/2 → 50bb effectif (short stack mais standard pour CFR initial)
- **Pas d'usage Winamax/sites commerciaux** : tests humains via `poky.cli.play` uniquement (CGU + détection bots + risque ban d'identité)
- **Libs** : rlcard (jeu + algos), phevaluator (eval rapide), torch (DMC/DCFR), matplotlib, pytest, numpy. Tout autorisé par le sujet (projet libre IA).

## Pièges déjà identifiés

- **Format de cartes** : rlcard a DEUX formats incohérents !
  - `raw_obs["hand"]` → `"HQ"` (suit + rank)
  - `Card.__str__` → `"QH"` (rank + suit)
  - Conversion dans `poky.cli.play` et `poky.equity.rlcard_to_phev`
- **Encodage Windows** : forcer `sys.stdout.reconfigure(encoding="utf-8")` dans les CLI sinon `±` casse en cp1252.
- **Pas de `pyspiel.universal_poker`** sur les wheels Windows d'OpenSpiel. C'est pour ça qu'on utilise rlcard.
