# Critères de succès — Poky (scope Nitro 3-max)

But : chiffres honnêtes et reproductibles pour juger le NitroPlayer à
chaque phase. Format cible = **Winamax Expresso Nitro** (3-max NLHE,
stack départ 15bb, hyper-turbo, payouts winner-take-all sauf jackpots
≥100x avec 80/12/8).

Référence historique : ancien `SUCCESS_CRITERIA.md` (cash 100bb) est
préservé dans `git log` du snapshot pre-Nitro.

## Setup standard pour benchs SnG

- **Format** : SnG 3-max NLHE, stack départ 300 chips (15 BB), BB=20
- **Escalation blinds** : selon structure Winamax Nitro (60s par niveau ≈ 6-8 mains par niveau)
- **Payouts** : winner-take-all (cas majoritaire) sauf indication contraire
- **Échantillon** : minimum **500 SnGs** (ouvre IC95 sur ROI et win rate)
- **5+ seeds indépendants** par config
- **Rotation des sièges** : NitroPlayer occupe (SnG_idx % 3) — pour neutraliser bias positionnel
- **Stat sig** : IC95 sur win rate ; succès = bound inf > seuil

## Critères N1 — Push/fold solver Nash 3-max

`PushFoldSolver` doit produire des tables qui :

| Test | Cible |
|---|---|
| Convergence | exploitability < 0.1 BB / 100 mains après ≤ 200 iter |
| Symétrie | stacks égaux → strats identiques par position |
| Cross-check référence | ≥ 80% match avec push72o.com / ICMIZER sur 30 spots |
| Stack 5bb BTN open | push frequency ≥ 50% des mains (cohérent littérature) |
| Stack 15bb BB cold-call vs SB push | < 25% (large fold equity) |

## Critères N2 — ICM Malmuth-Harville

`malmuth_harville_equity` doit :

| Test | Cible |
|---|---|
| Stacks égaux + payouts 80/12/8 | equity = [33.3%, 33.3%, 33.3%] |
| Stack ≈ 0 | equity ≈ 0 pour ce joueur |
| Sum equities | = sum payouts (conservation) |
| Match HRC sur 10 stacks tests | < 1% écart absolu |

## Critères N3 — NitroPlayer brain

| Adversaire | Win rate cible (sur 500+ SnGs) | Bound inf IC95 |
|---|---|---|
| 2× RandomPlayer (sanity) | ≥ 80% | > 70% |
| 2× AlwaysCallPlayer (sanity) | ≥ 75% | > 65% |
| 2× HeuristicPlayer (baseline réf) | ≥ 55% | > 45% |
| 1× Heuristic + 1× Random | ≥ 60% | > 50% |
| 2× NitroPlayer (self-play) | 33.3% ± 5% (break-even attendu) | dans IC |
| 2× Fish archetype (pop Nitro simulée) | ≥ 60% | > 50% |

Baseline noise floor (sanity) :
- HVH 3-max : 33.3% par siège attendu (3 NitroPlayer self-play) ; bias par siège < 2 points
- ROI sum = 0 sur winner-take-all (zero-sum chips)

**Critère consolidé N3** : toutes les cellules ci-dessus passent. Une seule
qui échoue → retravailler avant N4.

## Critères N4 — Arena SnG opérationnelle

| Test | Cible |
|---|---|
| Blinds escalation correct | ≥ 6 mains par niveau au début, escalation effective |
| Élimination quand stack = 0 | pas de bug, payout assigné |
| Rotation positionnelle | distribution uniforme des sièges sur 500 SnGs |
| Stat sig | IC95 calculé correctement sur win rate |

## Critères finaux "très bon joueur, pas top du panier"

Définition opérationnelle pour la soirée Discord :

1. **Bat les fish** : vs 2× Fish archetype, win rate ≥ 60% (vs 33% baseline)
2. **Tient face à mid-regs** : vs 2× Heuristic, win rate ≥ 50% (ne perd pas significativement)
3. **Ne s'écroule pas vs lui-même** : self-play 33.3% ± 5%
4. **ROI positif** : sur 500 SnGs vs mix [Fish, Heuristic], ROI ≥ +10% (en chips)
5. **Cohérence ICM** (si activé) : vs 2× Heuristic en mode ICM, gain par survie mesurable

## Méthodologie de mesure honnête

1. **Toujours reporter** :
   - Win rate global + IC95
   - ROI moyen + IC95
   - Distribution finish positions (1st/2nd/3rd)
   - Sample size en SnGs
   - Couverture push/fold lookup (% décisions consultant le Nash, vs fallback)
2. **Toujours faire** :
   - Sanity check HVH (NitroPlayer self-play) avant de claim
   - Cycle des sièges pour neutraliser bias positionnel
   - Multi-seed (≥ 5)
3. **Drapeaux rouges** :
   - Couverture push/fold < 70% → fallback domine, le solver n'est pas utilisé
   - IC95 trop large → augmenter le sample (variance SnG est élevée)
   - Win rate > 80% vs Heuristic → suspect de bug (Heuristic n'est pas Random)
   - ROI > +50% → suspect de mismatch payouts ou compute
