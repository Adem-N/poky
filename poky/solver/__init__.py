"""TexasSolver integration package.

See `docs/TEXASSOLVER_FORMAT.md` for I/O format and design notes.

Layers:
  - spot_schema : SpotKey + SpotSolution dataclasses
  - solver_runner : invokes the console binary, parses JSON
  - cache_db : SQLite store for solved spots
  - spot_generator : enumerates representative spots for batch solving
"""
from poky.solver.spot_schema import SpotKey, SpotSolution
from poky.solver.cache_db import CacheDB

__all__ = ["SpotKey", "SpotSolution", "CacheDB"]
