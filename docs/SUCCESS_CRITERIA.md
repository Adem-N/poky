# Critères de succès — Poky

But : avoir des **chiffres honnêtes et reproductibles** pour juger de la
qualité du bot à chaque phase. Le critère "+5 bb/100 vs HeuristicPlayer"
(historique Phase X1) était insuffisant — Heuristic a des leaks
exploit-spécifiques liés à l'abstraction rlcard 5-actions. Battre
Heuristic ne veut pas dire être proche d'un pro.

## Setup standard pour tous les benchs

- **Stack** : 100 bb effectif (chips_per_player=200, BB=2).
- **Tailles de tables** : HU, 3-max, 6-max — chacune doit passer les critères.
- **Échantillon** : minimum 25 000 mains par bench (5 seeds × 5 000).
- **Rotation positionnelle** : siège de l'expert cycle à chaque main (vérifié uniforme).
- **Stat sig** : IC95 sur la moyenne, succès = bound inférieur de l'IC > seuil.

## Baseline noise floor (sanity)

Avant tout claim, vérifier que la mesure n'est pas biaisée :

| Check | Cible | Mesure |
|---|---|---|
| HeuristicPlayer vs (N-1)× HeuristicPlayer, siège cyclé | mean dans IC95 de 0 | actuellement +2.72 ± 21.02 (6-max 100bb 25k) — OK |
| sum(payoffs) par main | = 0 exactement | OK |
| Distribution position cible | uniforme 1/N par offset_from_btn | OK (16.1-17.2% à 1/6) |

## Critères Phase X1 — Tier 1 preflop ranges

Phase X1 = ranges GTO préflop tunées contre Heuristic. C'est un **exploit
tuner**, pas une stratégie robuste — mais doit quand même montrer qu'il
**bat tous les archétypes** au-dessus du noise floor.

Pour chaque taille de table (HU, 3-max, 6-max), ExpertOnlyPlayer doit :

| Adversaire | Bound inf IC95 | Sample |
|---|---|---|
| HeuristicPlayer (baseline overfit) | ≥ +5 bb/100 | 25k mains |
| TightAggressive (≈ joueur récréatif sérieux) | > 0 bb/100 | 25k mains |
| LooseAggressive | > 0 bb/100 | 25k mains |
| TightPassive (Nit) | ≥ +15 bb/100 | 10k mains |
| Maniac | ≥ +30 bb/100 | 10k mains |
| RandomPlayer | ≥ +30 bb/100 | 10k mains |
| AlwaysCallPlayer | ≥ +20 bb/100 | 10k mains |

Les seuils ≥ X pour les baselines triviaux (Random, Call, Maniac) sont des
**garde-fous** : si on ne bat pas largement un Random, c'est qu'il y a un
bug ou un leak grave dans la stratégie. Ces baselines DOIVENT être
massivement battus.

**Critère consolidé X1** : tous les critères ci-dessus passent sur les 3
tailles de table. Si une seule case échoue → retravailler.

## Critères Phase X2 — Postflop principles

À définir. Doit minimum maintenir tous les critères X1 ET ajouter :

- vs HeuristicPlayer toujours ≥ +5 bb/100 sur les 3 tailles
- Couverture Tier 2 (postflop rules) ≥ 70% des spots postflop ?
- Pas de régression vs aucun archétype (toutes les cellules X1 stables ou +)

## Critères Phase X3+ — MCCFR blueprint

Le bot blueprint doit, en plus des critères X2 :

- Sur Kuhn poker : converger vers Nash (exploitability < 0.001)
- Sur Leduc poker : converger vers Nash (exploitability < 0.01)
- Sur HU NLHE abstraction : exploitability mesurée et publiée
- vs ExpertOnlyPlayer : ≥ 0 bb/100 sur 50k mains (pas régresser le Tier 1)

## Critères finaux — "Pro level"

Définition cible (à atteindre fin Phase X7) :

1. **Gauntlet archétypes** : bat TOUS les archétypes (HU + 3-max + 6-max), bound inf IC95 > 0.
2. **vs blueprint own** : ≥ 0 (non self-defeating).
3. **vs un baseline externe fort** : par exemple, un MCCFR référence open-source. À identifier.
4. **Exploitability** (HU NLHE abstraction) : ≤ 30 mbb/h via best-response sur strategy abstraite.
5. **Long-run stability** : sur 100k+ mains, pas de drift en EV (variance OK, mean stable).

Note : ne PAS confondre "bat Heuristic à +30 bb/100" avec "joue niveau pro".
Heuristic est un opponent au strategy déterministe ; les pros n'ont pas
ces patterns exploitables.

## Méthodologie de mesure honnête

1. **Toujours reporter** :
   - mean bb/100
   - IC95 (1.96 × SE)
   - n (taille échantillon)
   - couverture Tier 1 (% décisions consultant les ranges expertes vs fallback)
2. **Toujours faire** :
   - HVH baseline check avant claim (≈ 0 attendu)
   - Cycle des sièges pour neutraliser bias positionnel
   - Multi-seed (≥ 5)
   - Stack effectif explicite dans le label
3. **Drapeaux rouges** :
   - Couverture Tier 1 < 50% → résultat = surtout celui de Tier 2, pas du Tier 1
   - IC95 bound inf < 0 → ne pas claim de victoire
   - Hand sample < 10k → variance trop élevée pour conclure
   - 1 seul seed → résultat = chance, pas signal
   - Stack pas spécifié → benchmark non-reproductible
