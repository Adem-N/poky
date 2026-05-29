"""Nitro 3-max hyper-turbo SnG brain.

Target format: Winamax Expresso Nitro (or equivalent 3-max SnG):
  - 3 players, NLHE
  - Starting stack: 15bb (300 chips at BB=20)
  - Hyper turbo blinds (60s levels)
  - Average game length: 10-12 hands
  - Winner-take-all if jackpot multiplier <= 10x (majority of games)
  - 80/12/8 split if jackpot multiplier >= 100x (rare, ICM matters)

Modules:
  - pushfold     : Nash equilibrium push/fold solver for 3-max short stack
  - icm          : Malmuth-Harville ICM model (3-player, 80/12/8 payouts)
  - ranges       : loaders for precomputed stack-depth ranges
  - postflop     : SPR-based commit rules for the rare deep-stack hands
  - exploits     : population-based overrides on top of GTO baseline
"""
