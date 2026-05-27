"""
Abstraction postflop par bucketing d'équité.

Pour MCCFR sur NLHE, l'espace d'états postflop (1326 × 22 100 flops = 25.99M
combinaisons, ×suits ×runouts pour turn/river) est trop grand pour être
stocké directement. On le compresse en **K=5 buckets par street** basés
sur l'équité estimée vs un range adversaire uniforme.

Méthode :
  1. Échantillonner N=10 000 états (hole, board) random pour chaque street
  2. Calculer l'équité Monte Carlo de chacun
  3. Trier les équités et définir K-1 frontières aux quantiles
  4. Cacher les frontières sur disque (4 nombres × 3 streets = 12 floats)
  5. À runtime : équité du nouvel état → bucket par bisection sur les frontières

Avantages de cette approche minimale :
  - Très petit cache disque (pas de gros lookup table)
  - Pas de canonicalisation suit-isomorphism complexe à coder
  - Easy à upgrader vers OCHS / EMD signatures (Johanson 2013) plus tard

Inconvénient : runtime nécessite ~100 sims MC par décision (~1-2 ms).
Pour MCCFR training, cela ralentit mais reste acceptable. Pour bot live, cache
les résultats par (canonical_hole_class, canonical_board_sig) à l'usage.
"""
import bisect
import json
import os
import random
from typing import List, Optional

from poky.equity import monte_carlo_equity
from poky.equity.estimator import ALL_CARDS_PHEV


NUM_BUCKETS = 5  # K par street
DEFAULT_SAMPLES = 10_000           # mains random par street pour calibrer
CALIBRATION_SIMULATIONS = 200      # MC sims pour chaque sample en calibration
RUNTIME_SIMULATIONS = 100          # MC sims pour bucketer un nouvel état

_CACHE_PATH = os.path.join(os.path.dirname(__file__),
                           "_postflop_buckets.json")

# État interne (chargé/calculé à la 1ère utilisation)
# Format : {'flop': [b1, b2, b3, b4], 'turn': [...], 'river': [...]}
_BOUNDARIES: Optional[dict] = None


def _phev_to_rlcard(phev_card: str) -> str:
    """phevaluator 'Ah' -> rlcard 'HA'."""
    return phev_card[1].upper() + phev_card[0].upper()


def _sample_state(street: str, rng: random.Random):
    """Tire un (hole, board) random pour le street demandé.
    Retourne 2 listes de cartes au format rlcard ('HQ' = Dame de Cœur)."""
    deck = list(ALL_CARDS_PHEV)
    rng.shuffle(deck)
    hole_phev = deck[:2]
    if street == "flop":
        board_phev = deck[2:5]
    elif street == "turn":
        board_phev = deck[2:6]
    elif street == "river":
        board_phev = deck[2:7]
    else:
        raise ValueError(f"street invalide : {street!r}")
    hole = [_phev_to_rlcard(c) for c in hole_phev]
    board = [_phev_to_rlcard(c) for c in board_phev]
    return hole, board


def _compute_boundaries_for_street(street: str, n_samples: int,
                                   simulations: int, seed: int) -> List[float]:
    """Calibre les K-1 frontières d'équité pour ce street, par quantiles."""
    rng = random.Random(seed)
    equities = []
    for _ in range(n_samples):
        hole, board = _sample_state(street, rng)
        eq = monte_carlo_equity(hole, board, num_opponents=1,
                                simulations=simulations, rng=rng)
        equities.append(eq)
    equities.sort()
    # K-1 frontières aux quantiles 1/K, 2/K, ..., (K-1)/K
    boundaries = []
    for k in range(1, NUM_BUCKETS):
        idx = int(round(len(equities) * k / NUM_BUCKETS))
        boundaries.append(equities[min(idx, len(equities) - 1)])
    return boundaries


def _calibrate_and_cache():
    """Calcule les frontières pour les 3 streets et écrit le cache."""
    print(f"Calibration postflop ({NUM_BUCKETS} buckets/street, "
          f"{DEFAULT_SAMPLES} samples × {CALIBRATION_SIMULATIONS} sims)...")
    result = {}
    for street, seed_offset in [("flop", 1), ("turn", 2), ("river", 3)]:
        print(f"  street={street}...")
        result[street] = _compute_boundaries_for_street(
            street, DEFAULT_SAMPLES, CALIBRATION_SIMULATIONS, 42 + seed_offset)
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


def _ensure_loaded():
    global _BOUNDARIES
    if _BOUNDARIES is not None:
        return
    if os.path.exists(_CACHE_PATH):
        with open(_CACHE_PATH, encoding="utf-8") as f:
            _BOUNDARIES = json.load(f)
    else:
        _BOUNDARIES = _calibrate_and_cache()


def _bucket_from_equity(equity: float, street: str) -> int:
    """Mappe une équité scalaire vers un bucket 0..K-1 via bisection
    sur les frontières du street."""
    _ensure_loaded()
    boundaries = _BOUNDARIES[street]
    return bisect.bisect_left(boundaries, equity)


# ---- API publique ---------------------------------------------------------

def flop_bucket(hole, board, simulations: int = RUNTIME_SIMULATIONS,
                rng: Optional[random.Random] = None) -> int:
    """Bucket 0..K-1 pour un état flop. K=5 par défaut.
    `hole` = 2 cartes, `board` = 3 cartes (format rlcard 'HQ')."""
    if len(board) != 3:
        raise ValueError(f"flop attend 3 cartes, got {len(board)}")
    eq = monte_carlo_equity(hole, board, num_opponents=1,
                            simulations=simulations, rng=rng)
    return _bucket_from_equity(eq, "flop")


def turn_bucket(hole, board, simulations: int = RUNTIME_SIMULATIONS,
                rng: Optional[random.Random] = None) -> int:
    if len(board) != 4:
        raise ValueError(f"turn attend 4 cartes, got {len(board)}")
    eq = monte_carlo_equity(hole, board, num_opponents=1,
                            simulations=simulations, rng=rng)
    return _bucket_from_equity(eq, "turn")


def river_bucket(hole, board, simulations: int = RUNTIME_SIMULATIONS,
                 rng: Optional[random.Random] = None) -> int:
    if len(board) != 5:
        raise ValueError(f"river attend 5 cartes, got {len(board)}")
    eq = monte_carlo_equity(hole, board, num_opponents=1,
                            simulations=simulations, rng=rng)
    return _bucket_from_equity(eq, "river")


def postflop_bucket(hole, board, **kwargs) -> int:
    """Dispatch automatique selon len(board)."""
    n = len(board)
    if n == 3:
        return flop_bucket(hole, board, **kwargs)
    if n == 4:
        return turn_bucket(hole, board, **kwargs)
    if n == 5:
        return river_bucket(hole, board, **kwargs)
    raise ValueError(f"len(board)={n} non-postflop")


def get_boundaries() -> dict:
    """Retourne les frontières chargées (utile pour inspecter/diagnostiquer)."""
    _ensure_loaded()
    return dict(_BOUNDARIES)
