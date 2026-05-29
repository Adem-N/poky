"""Nash equilibrium push/fold solver for 3-max short stack NLHE.

For stack depths <= ~12bb, optimal play in NLHE 3-max collapses to a pure
push-or-fold game preflop: open-raise sizes become unprofitable because
SPR is so low post-call that postflop EV approaches zero.

Solving the 3-max push/fold equilibrium:
  - Game tree per stack depth:
      BTN: push or fold
        -> SB: call or fold (if BTN pushed) | push or fold (if BTN folded)
            -> BB: call or fold (if anyone pushed) | check (if all folded)
  - Each player has 169 canonical hand classes
  - Equilibrium found via iterative best-response (~50-200 iterations)
  - Output: per-position, per-hand-class push or call frequency

PLACEHOLDER — implementation in task N1.
"""
from __future__ import annotations


class PushFoldSolver:
    """Computes the Nash equilibrium push/fold strategy for 3-max NLHE."""

    def __init__(self, stack_bb: float, sb_bb: float = 0.5, bb_bb: float = 1.0,
                 ante_bb: float = 0.0):
        self.stack_bb = stack_bb
        self.sb_bb = sb_bb
        self.bb_bb = bb_bb
        self.ante_bb = ante_bb

    def solve(self, max_iterations: int = 200, tolerance: float = 1e-4) -> dict:
        """Iterate best-response until convergence. Returns strategy dict.

        Strategy dict structure:
            {
              "BTN": {"push": [169 frequencies], "fold": [...]},
              "SB":  {"call_vs_btn": [...], "push_if_btn_folded": [...]},
              "BB":  {"call_vs_btn": [...], "call_vs_sb": [...]},
            }
        """
        raise NotImplementedError("N1 — implement Nash push/fold iteration")
