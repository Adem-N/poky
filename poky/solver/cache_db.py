"""SQLite-backed store for solved poker spots.

One row per (SpotKey hash) — `put()` is upsert. Designed to be cheap to
re-open, safe under concurrent readers, and resumable under the build
pipeline (a Ctrl-C mid-build leaves earlier rows intact).

Schema (created on first open if absent):
    CREATE TABLE solutions (
        key_hash         TEXT PRIMARY KEY,
        key_json         TEXT NOT NULL,
        solution_json    TEXT NOT NULL,
        solved_at        TEXT NOT NULL,
        solver_version   TEXT NOT NULL,
        iterations       INTEGER NOT NULL,
        exploitability   REAL,
        elapsed_sec      REAL
    );
    CREATE INDEX idx_street_stack ON solutions(...);  -- TODO if we add bucketing queries
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

from poky.solver.spot_schema import SpotKey, SpotSolution


SCHEMA = """
CREATE TABLE IF NOT EXISTS solutions (
    key_hash        TEXT PRIMARY KEY,
    key_json        TEXT NOT NULL,
    solution_json   TEXT NOT NULL,
    solved_at       TEXT NOT NULL,
    solver_version  TEXT NOT NULL,
    iterations      INTEGER NOT NULL,
    exploitability  REAL,
    elapsed_sec     REAL
);
"""


class CacheDB:
    """Thin SQLite wrapper for SpotSolution persistence."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so a multi-process build pipeline can
        # share a single DB. Writes still serialize through SQLite.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def exists(self, key: SpotKey) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM solutions WHERE key_hash = ? LIMIT 1",
            (key.hash_key(),),
        )
        return cur.fetchone() is not None

    def get(self, key: SpotKey) -> Optional[SpotSolution]:
        cur = self._conn.execute(
            "SELECT solution_json FROM solutions WHERE key_hash = ?",
            (key.hash_key(),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SpotSolution.from_dict(json.loads(row[0]))

    def put(self, solution: SpotSolution) -> None:
        """Upsert one solution. Idempotent — overwrites existing key."""
        key = solution.spot_key
        self._conn.execute(
            """
            INSERT INTO solutions
                (key_hash, key_json, solution_json, solved_at, solver_version,
                 iterations, exploitability, elapsed_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key_hash) DO UPDATE SET
                key_json       = excluded.key_json,
                solution_json  = excluded.solution_json,
                solved_at      = excluded.solved_at,
                solver_version = excluded.solver_version,
                iterations     = excluded.iterations,
                exploitability = excluded.exploitability,
                elapsed_sec    = excluded.elapsed_sec
            """,
            (
                key.hash_key(),
                key.canonical_json(),
                json.dumps(solution.to_dict(), separators=(",", ":")),
                solution.solved_at,
                solution.solver_version,
                solution.iterations,
                solution.exploitability,
                solution.elapsed_sec,
            ),
        )
        self._conn.commit()

    def stats(self) -> dict:
        cur = self._conn.execute(
            """
            SELECT
                COUNT(*) AS n,
                AVG(iterations) AS avg_iter,
                AVG(exploitability) AS avg_exploit,
                AVG(elapsed_sec) AS avg_elapsed,
                MIN(solved_at) AS first_solved,
                MAX(solved_at) AS last_solved
            FROM solutions
            """
        )
        row = cur.fetchone()
        return {
            "n_solutions": row[0],
            "avg_iterations": row[1],
            "avg_exploitability": row[2],
            "avg_elapsed_sec": row[3],
            "first_solved": row[4],
            "last_solved": row[5],
            "db_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    def iter_keys(self) -> Iterator[SpotKey]:
        """Yield every cached SpotKey (useful for sanity checks)."""
        cur = self._conn.execute("SELECT key_json FROM solutions")
        for (kj,) in cur:
            d = json.loads(kj)
            d["board"] = tuple(d["board"])
            d["bet_menu"] = tuple(tuple(e) for e in d.get("bet_menu", ()))
            yield SpotKey(**d)
