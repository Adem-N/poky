# TexasSolver I/O format (champs utilisés par Poky)

Source : `external/TexasSolver/TexasSolver-v0.2.0-Windows/console_solver.exe`,
release v0.2.0 (2021-11). Doc officielle : https://github.com/bupticybee/TexasSolver.

## Invocation

```powershell
cd external/TexasSolver/TexasSolver-v0.2.0-Windows
.\console_solver.exe -i path/to/input.txt
```

Génère `output_result.json` dans le cwd. Le binary cherche `resources/`, `ranges/`,
`parameters/` en relatif → toujours invoquer depuis le dossier `TexasSolver-v0.2.0-Windows`.

## Input DSL (mini langage de commandes, 1 par ligne)

```
set_pot <chips>                       # pot avant la decision (en chips, pas bb)
set_effective_stack <chips>           # stack restant le plus petit des 2 joueurs
set_board <c1>,<c2>,<c3>[,<c4>[,<c5>]]   # flop minimum 3 cartes ; turn 4 ; river 5
                                         # format carte : <rank><suit>, ex Qs 8d 7h Tc 2h
set_range_ip <range>                  # range IP au format poker (T9s, 22+, AKo, ...)
set_range_oop <range>                 # range OOP au format poker
set_bet_sizes <pos>,<street>,<role>,<pct>
  # pos ∈ {oop, ip}
  # street ∈ {flop, turn, river}
  # role ∈ {bet, raise, donk}     # donk = bet OOP après que IP ait été aggresseur
  # pct = pourcentage du pot, ex 50, 75, 100
set_allin_threshold <ratio>           # quand SPR ≤ ratio, autoriser jam
build_tree
set_thread_num <n>
set_accuracy <exploit-floor>          # MBR target (1.0 = 1% du pot)
set_max_iteration <n>                 # cap pour CFR
set_print_interval <n>
set_use_isomorphism 0|1               # 1 = exploite symétries de suits
start_solve
set_dump_rounds <n>                   # 0=flop seul, 1=+turn, 2=+river
dump_result <path>
```

**Sample shipped** : `resources/text/commandline_sample_input.txt` (Qs8d7h flop, ranges minimales pour test rapide ≈ 30s).

## Output JSON (structure)

Tree récursif depuis le flop. Format de chaque node :

```json
{
  "actions": ["CHECK", "BET 2.000000"],          // legal actions à ce node
  "node_type": "action_node",                    // ou "chance_node" (carte deal) ou "showdown_node"
  "player": 0,                                   // 0=OOP, 1=IP
  "strategy": {
    "actions": ["CHECK", "BET 2.000000"],
    "strategy": {
      "Tc9c": [0.05, 0.95],                      // probas par hand combo
      "Td9d": [0.10, 0.90],
      ...
    }
  },
  "childrens": {
    "BET 2.000000": { ... node enfant ... },
    "CHECK": { ... node enfant ... }
  }
}
```

**Champs utilisés par Poky** :
- Au top-level : on cherche le node correspondant à notre `(player, history)` actuel
- À ce node : `strategy.actions` = liste des actions ordonnées, `strategy.strategy[<combo>]` = vecteur de probas (somme = 1)
- On match notre combo (ex `AhKs`) ; si pas dans la map, fallback `_combo_to_class()` pour aller à la hand class (ex `AKo`)
- `chance_node` = on attend la prochaine carte deal (turn/river), pas une décision agent

**Action labels** :
- `CHECK`, `CALL`, `FOLD` = sans argument
- `BET <chips>`, `RAISE <chips>` = montant absolu en chips (pas en % pot)
- `ALLIN` = tout-in

## Translation vers rlcard 5-actions (Poky)

Le solver produit des sizings continus en chips. On bucketise en :

| Solver action | Rlcard action |
|---|---|
| `FOLD` | `FOLD` |
| `CHECK` ou `CALL` | `CHECK_CALL` |
| `BET <x>` ou `RAISE <x>` avec `(x - to_call) / pot ∈ [0.33, 0.66]` | `RAISE_HALF_POT` |
| `BET <x>` ou `RAISE <x>` avec `(x - to_call) / pot ∈ [0.66, 1.5]` | `RAISE_POT` |
| `ALLIN` ou `RAISE <x>` avec `x ≥ effective_stack * 0.95` | `ALL_IN` |
| sizings `< 0.33 pot` | `CHECK_CALL` (passive treatment) |

Quand plusieurs `BET` ou `RAISE` solver tombent dans le même bucket rlcard, on
**agrège leurs probabilités** (somme).

## Range format (poker shorthand)

- `AA` = pair (toutes les 6 combos)
- `AKs` = suited (4 combos), `AKo` = offsuit (12 combos), `AK` = both (16 combos)
- `22+` = toutes les paires de 22 à AA
- `AKs+` = AKs, AQs, AJs, ...
- `K9s+` = K9s, KTs, KJs, KQs
- Ranges multiples séparées par virgule : `22+, A2s+, A8o+, KTo+, K9s+, ...`
- Range "weighted" : `AKs:0.5, AKo:0.3` (chaque combo pondéré 0..1)

Le solver ships des ranges préfabriqués pro-quality dans `ranges/qb_ranges/` (style PioSOLVER, 100bb, 3x opens) — on les utilisera comme ranges d'opponent pour les spots.
