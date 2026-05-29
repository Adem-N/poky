"""SQLite store for OpponentProfile — persists across SnG sessions.

Same pattern as `poky/solver/cache_db.py`: WAL mode, single-table upsert via
INSERT ... ON CONFLICT. One row per opponent (keyed by opp_id string).

Designed for the Discord-night use case: you accumulate stats on your
friends across multiple sessions, and each new SnG starts with their
historical profile pre-loaded.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator, List, Optional

from poky.nitro.profiling import OpponentProfile

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    opp_id          TEXT PRIMARY KEY,
    profile_json    TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    n_hands         INTEGER NOT NULL
);
"""


class ProfileDB:
    """Thin SQLite wrapper for OpponentProfile persistence."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def load(self, opp_id: str) -> Optional[OpponentProfile]:
        """Return the cached profile for this opp_id, or None if not seen yet."""
        cur = self._conn.execute(
            "SELECT profile_json FROM profiles WHERE opp_id = ?",
            (opp_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return OpponentProfile.from_dict(json.loads(row[0]))

    def save(self, profile: OpponentProfile) -> None:
        """Upsert one profile. Idempotent."""
        self._conn.execute(
            """
            INSERT INTO profiles (opp_id, profile_json, last_seen, n_hands)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(opp_id) DO UPDATE SET
                profile_json = excluded.profile_json,
                last_seen    = excluded.last_seen,
                n_hands      = excluded.n_hands
            """,
            (
                profile.opp_id,
                json.dumps(profile.to_dict(), separators=(",", ":")),
                profile.last_seen,
                profile.n_hands_observed,
            ),
        )
        self._conn.commit()

    def list_ids(self) -> List[str]:
        cur = self._conn.execute("SELECT opp_id FROM profiles ORDER BY last_seen DESC")
        return [r[0] for r in cur.fetchall()]

    def stats(self) -> dict:
        cur = self._conn.execute(
            """
            SELECT
                COUNT(*) AS n_profiles,
                SUM(n_hands) AS total_hands,
                MAX(n_hands) AS max_hands_per_opp,
                MIN(last_seen) AS first_seen,
                MAX(last_seen) AS last_seen
            FROM profiles
            """
        )
        row = cur.fetchone()
        return {
            "n_profiles": row[0],
            "total_hands": row[1] or 0,
            "max_hands_per_opp": row[2] or 0,
            "first_seen": row[3],
            "last_seen": row[4],
            "db_size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    def iter_profiles(self) -> Iterator[OpponentProfile]:
        cur = self._conn.execute("SELECT profile_json FROM profiles")
        for (pj,) in cur:
            yield OpponentProfile.from_dict(json.loads(pj))
