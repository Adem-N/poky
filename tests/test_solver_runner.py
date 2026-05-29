"""Integration test for poky.solver.solver_runner.

Invokes the actual TexasSolver binary. Slow (~20s/spot), so isolated to its
own file. Skipped automatically if the binary isn't installed.
"""
import pytest

from poky.solver.solver_runner import DEFAULT_SOLVER_DIR, solve_spot
from poky.solver.spot_schema import SpotKey


pytestmark = pytest.mark.skipif(
    not (DEFAULT_SOLVER_DIR / "console_solver.exe").exists(),
    reason="TexasSolver binary not installed at external/TexasSolver/",
)


def test_solve_tiny_spot_returns_valid_solution():
    spot = SpotKey(
        street="flop",
        board=("Ah", "Kh", "7d"),
        pot_chips=6,
        effective_stack=97,
        ip_range="AKs,KQs",
        oop_range="QQ,JTs",
    )
    sol = solve_spot(spot, max_iter=40, accuracy=1.0, threads=4)

    # Basic sanity.
    assert sol.spot_key.hash_key() == spot.hash_key()
    assert sol.player_at_root in (0, 1)
    assert len(sol.root_actions) >= 1
    assert sol.iterations > 0
    assert sol.elapsed_sec > 0
    assert sol.solver_version == "TexasSolver-v0.2.0"

    # Strategy probs per combo sum to ~1.
    for combo, probs in sol.root_strategy.items():
        assert len(probs) == len(sol.root_actions), combo
        assert abs(sum(probs) - 1.0) < 1e-3, (combo, probs)

    # Aggregated freqs sum to ~1.
    if sol.aggregated_strategy:
        total = sum(p for _, p in sol.aggregated_strategy)
        assert abs(total - 1.0) < 1e-3
