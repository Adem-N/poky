"""SPR-based postflop decision rules for the early hands of a Nitro game.

Once stacks are <= 12bb, postflop barely exists (SPR <= 1.5, decisions are
binary commit-or-fold). At 15bb start with the first one or two pots played
small, SPR can be 2-4 and postflop becomes meaningful for ~2-3 hands per
game.

Strategy is rule-based (not solver-driven) because:
  1. The tree is shallow and decisions are usually committed
  2. Computing GTO postflop for every stack/board combo would dominate compute
  3. Population reads dominate edge over GTO at this depth in Nitro pop

Rules (PLACEHOLDER — implement in N3):
  - As PFA on flop with SPR <= 2: c-bet 33% almost always (high fold-equity)
  - As PFA on flop with SPR 2-4: c-bet 50% with strong/draw, check back marginal
  - Facing c-bet IP: call wide (peel) if SPR <= 2 (committed); fold marginal SPR > 3
  - Donk leads OOP: very rare, only nut/draws
  - Turn/river: commit thresholds based on (hand_strength, board_runout)
"""
from __future__ import annotations
