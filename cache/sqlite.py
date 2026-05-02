#!/usr/bin/env python3
"""
SQLite-backed plan cache with FTS5 and vector similarity support.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import BasePlanCache, _cosine, _get_embedding
from common_types import CacheCandidate

# Module-level logger — DB/connection error details go here (not to stdout)
_logger = logging.getLogger(__name__)


class SQLitePlanCache(BasePlanCache):
    """SQLite-backed cache for execution plans with a configurable TTL.

    Storage layout
    ──────────────
    plans(task_hash PK, task_text, plan, timestamp, embedding TEXT)
      • embedding: JSON-encoded float list produced by text-embedding-3-small.
        NULL when the OpenAI API is unavailable at write time.

    plans_fts  — FTS5 virtual table mirroring task_text for BM25 search.

    Lookup strategy
    ───────────────
    1. Exact-hash lookup  (normalized SHA-256 → instant O(1) hit).
    2. Hybrid search      (FTS5 BM25 + cosine vector similarity, scored and
                           ranked) — called explicitly by PlannerAgent so the
                           user can choose a candidate interactively.
    """

    # Hybrid-score mixing weight: 0 = pure FTS, 1 = pure vector
    ALPHA: float = 0.6
    # Minimum hybrid score to include a candidate in results
    SCORE_THRESHOLD: float = 0.0
    # Maximum candidates returned by hybrid_search()
    MAX_CANDIDATES: int = 3

    def __init__(self, db_path: str = ".plan_cache.db", ttl_days: int = 30):
        self.db_path = Path(db_path)
        self.ttl_days = ttl_days
        self._init_db()

    # ── Schema ────────────────────────────────────────────────────

    def _ensure_integrity(self) -> None:
        """Check DB integrity and rebuild from backup if corrupted."""
        if not self.db_path.exists():
            return
        try:
            with sqlite3.connect(self.db_path,
                                 detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            print(f"⚠️  Database corruption detected in {self.db_path}")
            print("   Rebuilding database...")
            backup_path = self.db_path.with_suffix('.db.backup')
            try:
                self.db_path.rename(backup_path)
                print(f"   Backup saved to: {backup_path}")
            except OSError:
                pass
            self._init_db()
            print("✅ Database rebuilt successfully")
            return
        
        # Check FTS5 integrity and rebuild if needed
        self._rebuild_fts_if_needed()
    
    def _rebuild_fts_if_needed(self) -> None:
        """Check if FTS5 table is in sync with main table and rebuild if necessary."""
        if not self.db_path.exists():
            return
        
        try:
            with sqlite3.connect(self.db_path,
                                 detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                # Check if FTS5 table exists
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='plans_fts'"
                )
                if not cursor.fetchone():
                    # FTS5 table doesn't exist, try to create it
                    try:
                        conn.execute("""
                            CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts
                            USING fts5(task_text, task_hash UNINDEXED, content=plans,
                                       content_rowid=rowid)
                        """)
                        # Recreate triggers
                        conn.execute("""
                            CREATE TRIGGER IF NOT EXISTS plans_ai
                            AFTER INSERT ON plans BEGIN
                                INSERT INTO plans_fts(rowid, task_text, task_hash)
                                VALUES (new.rowid, new.task_text, new.task_hash);
                            END
                        """)
                        conn.execute("""
                            CREATE TRIGGER IF NOT EXISTS plans_ad
                            AFTER DELETE ON plans BEGIN
                                DELETE FROM plans_fts WHERE rowid = old.rowid;
                            END
                        """)
                        conn.execute("""
                            CREATE TRIGGER IF NOT EXISTS plans_au
                            AFTER UPDATE ON plans BEGIN
                                DELETE FROM plans_fts WHERE rowid = old.rowid;
                                INSERT INTO plans_fts(rowid, task_text, task_hash)
                                VALUES (new.rowid, new.task_text, new.task_hash);
                            END
                        """)
                        conn.commit()
                        # Populate FTS5 with existing data
                        conn.execute(
                            "INSERT INTO plans_fts(rowid, task_text, task_hash) "
                            "SELECT rowid, task_text, task_hash FROM plans"
                        )
                        conn.commit()
                        print("✅ FTS5 table created and populated")
                    except sqlite3.DatabaseError as e:
                        print(f"⚠️  Warning: Could not create FTS5 table: {e}")
                        print("   Hybrid search will be disabled.")
                    return
                
                # Check if FTS5 is in sync by comparing counts
                # If counts differ, FTS5 is out of sync
                counts = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM plans) as main_count, "
                    "(SELECT COUNT(*) FROM plans_fts) as fts_count"
                ).fetchone()
                
                if counts:
                    main_count, fts_count = counts
                    if main_count != fts_count:
                        print(f"⚠️  FTS5 table out of sync: {main_count} main rows, {fts_count} FTS rows")
                        print("   Rebuilding FTS5 table...")
                        
                        try:
                            # Backup FTS5 table schema
                            cursor = conn.execute(
                                "SELECT sql FROM sqlite_master WHERE type='table' AND name='plans_fts'"
                            )
                            fts_schema = cursor.fetchone()
                            
                            if fts_schema:
                                # Drop and recreate FTS5
                                conn.execute("DROP TABLE IF EXISTS plans_fts")
                                conn.commit()
                                
                                # Recreate FTS5 using the original schema
                                schema_sql = fts_schema[0]
                                print(f"   Debug: Recreating FTS5 with schema: {schema_sql[:100]}...")
                                conn.execute(schema_sql)
                                conn.commit()
                                
                                # Recreate triggers
                                try:
                                    conn.execute("""
                                        CREATE TRIGGER IF NOT EXISTS plans_ai
                                        AFTER INSERT ON plans BEGIN
                                            INSERT INTO plans_fts(rowid, task_text, task_hash)
                                            VALUES (new.rowid, new.task_text, new.task_hash);
                                        END
                                    """)
                                    conn.execute("""
                                        CREATE TRIGGER IF NOT EXISTS plans_ad
                                        AFTER DELETE ON plans BEGIN
                                            DELETE FROM plans_fts WHERE rowid = old.rowid;
                                        END
                                    """)
                                    conn.execute("""
                                        CREATE TRIGGER IF NOT EXISTS plans_au
                                        AFTER UPDATE ON plans BEGIN
                                            DELETE FROM plans_fts WHERE rowid = old.rowid;
                                            INSERT INTO plans_fts(rowid, task_text, task_hash)
                                            VALUES (new.rowid, new.task_text, new.task_hash);
                                        END
                                    """)
                                except sqlite3.DatabaseError as e:
                                    print(f"   Warning: Error creating triggers: {e}")
                                
                                # Repopulate FTS5 from main table
                                result = conn.execute(
                                    "INSERT INTO plans_fts(rowid, task_text, task_hash) "
                                    "SELECT rowid, task_text, task_hash FROM plans"
                                )
                                conn.commit()
                                print(f"✅ FTS5 table rebuilt and synchronized ({result.rowcount} rows inserted)")
                            else:
                                print("⚠️  Could not get FTS5 schema, skipping rebuild")
                        except sqlite3.DatabaseError as e:
                            print(f"⚠️  Error during FTS5 rebuild: {e}")
                            raise  # Re-raise to be caught by outer handler
        
        except sqlite3.DatabaseError as e:
            print(f"⚠️  Error checking FTS5 integrity: {e}")
            print("   FTS5 table may be corrupted. Consider rebuilding the database.")

    def _rebuild_fts_aggressive(self) -> None:
        """Aggressive FTS5 rebuild that handles severe corruption.
        
        This method uses a more thorough approach to fix FTS5 corruption,
        particularly the "missing row from content table" error.
        """
        if not self.db_path.exists():
            return
        
        print("   Performing aggressive FTS5 rebuild...")
        
        try:
            with sqlite3.connect(self.db_path,
                                 detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                # Check if FTS5 table exists
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='plans_fts'"
                )
                if not cursor.fetchone():
                    print("   FTS5 table doesn't exist, creating...")
                    self._init_db()
                    return
                
                # Get the original schema before dropping
                cursor = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='plans_fts'"
                )
                fts_schema_row = cursor.fetchone()
                
                if not fts_schema_row:
                    print("   Could not retrieve FTS5 schema, falling back to full DB rebuild")
                    self._init_db()
                    return
                
                fts_schema = fts_schema_row[0]
                
                # Step 1: Drop all triggers first
                print("   Dropping FTS5 triggers...")
                conn.execute("DROP TRIGGER IF EXISTS plans_ai")
                conn.execute("DROP TRIGGER IF EXISTS plans_ad")
                conn.execute("DROP TRIGGER IF EXISTS plans_au")
                conn.commit()
                
                # Step 2: Drop the FTS5 table
                print("   Dropping FTS5 table...")
                conn.execute("DROP TABLE IF EXISTS plans_fts")
                conn.commit()
                
                # Step 3: Force SQLite to clean up by running VACUUM in a separate connection
                # This helps clear any cached content table references
                print("   Running VACUUM to clean up database...")
                conn.execute("VACUUM")
                conn.commit()
                
                # Step 4: Recreate FTS5 without content linkage initially
                print("   Creating fresh FTS5 table...")
                # Create a standalone FTS5 table first (no content=plans)
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts_new
                    USING fts5(task_text, task_hash UNINDEXED)
                """)
                conn.commit()
                
                # Step 5: Copy data from main table to the new FTS5
                print("   Populating FTS5 with data from plans table...")
                result = conn.execute(
                    "INSERT INTO plans_fts_new(rowid, task_text, task_hash) "
                    "SELECT rowid, task_text, task_hash FROM plans"
                )
                conn.commit()
                print(f"   Inserted {result.rowcount} rows into temporary FTS5")
                
                # Step 6: Drop the old FTS5 completely and rename the new one
                print("   Replacing old FTS5 with new one...")
                conn.execute("DROP TABLE IF EXISTS plans_fts")
                conn.commit()
                
                conn.execute("ALTER TABLE plans_fts_new RENAME TO plans_fts")
                conn.commit()
                
                # Step 7: Recreate triggers for the new FTS5
                print("   Recreating FTS5 triggers...")
                try:
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS plans_ai
                        AFTER INSERT ON plans BEGIN
                            INSERT INTO plans_fts(rowid, task_text, task_hash)
                            VALUES (new.rowid, new.task_text, new.task_hash);
                        END
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS plans_ad
                        AFTER DELETE ON plans BEGIN
                            DELETE FROM plans_fts WHERE rowid = old.rowid;
                        END
                    """)
                    conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS plans_au
                        AFTER UPDATE ON plans BEGIN
                            DELETE FROM plans_fts WHERE rowid = old.rowid;
                            INSERT INTO plans_fts(rowid, task_text, task_hash)
                            VALUES (new.rowid, new.task_text, new.task_hash);
                        END
                    """)
                    conn.commit()
                    print("✅ FTS5 triggers recreated successfully")
                except sqlite3.DatabaseError as e:
                    print(f"   Warning: Error creating triggers: {e}")
                    print("   FTS5 table will work but won't auto-update on changes")
                
                # Step 8: Verify the rebuild
                print("   Verifying FTS5 rebuild...")
                cursor = conn.execute("SELECT COUNT(*) FROM plans_fts")
                fts_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM plans")
                main_count = cursor.fetchone()[0]
                
                if fts_count == main_count:
                    print(f"✅ FTS5 rebuild complete: {fts_count} rows synchronized")
                else:
                    print(f"⚠️  FTS5 count mismatch after rebuild: {fts_count} FTS vs {main_count} main")
                    print("   FTS5 is functional but may have missing entries")
                
        except sqlite3.DatabaseError as e:
            print(f"⚠️  Error during aggressive FTS5 rebuild: {e}")
            print("   Falling back to full database reinitialization...")
            # Last resort: rebuild the entire database
            self._init_db()

    def _init_db(self) -> None:
        # Check for database corruption and recover if needed
        if self.db_path.exists():
            try:
                with sqlite3.connect(self.db_path,
                                     detect_types=sqlite3.PARSE_DECLTYPES) as conn:
                    conn.execute("PRAGMA integrity_check").fetchone()
            except sqlite3.DatabaseError:
                print(f"⚠️  Database corruption detected in {self.db_path}")
                print("   Creating backup and rebuilding database...")
                backup_path = self.db_path.with_suffix('.db.backup')
                try:
                    self.db_path.rename(backup_path)
                    print(f"   Backup saved to: {backup_path}")
                except OSError:
                    pass

        with sqlite3.connect(self.db_path,
                             detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    task_hash TEXT PRIMARY KEY,
                    task_text TEXT    NOT NULL,
                    plan      TEXT    NOT NULL,
                    timestamp DATETIME NOT NULL,
                    embedding TEXT    DEFAULT NULL,
                    url        TEXT    DEFAULT NULL,
                    markdown_file TEXT DEFAULT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON plans(timestamp)"
            )
            # FTS5 virtual table — keeps task_text searchable via BM25
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS plans_fts
                    USING fts5(task_text, task_hash UNINDEXED, content=plans,
                               content_rowid=rowid)
                """)
            except sqlite3.DatabaseError as e:
                # FTS5 may not be available or table may be corrupted
                print(f"⚠️  Warning: Could not create FTS5 virtual table: {e}")
                print("   Hybrid search will be disabled.")

            # Triggers to keep plans_fts in sync with plans (only if FTS5 table exists)
            try:
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS plans_ai
                    AFTER INSERT ON plans BEGIN
                        INSERT INTO plans_fts(rowid, task_text, task_hash)
                        VALUES (new.rowid, new.task_text, new.task_hash);
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS plans_ad
                    AFTER DELETE ON plans BEGIN
                        DELETE FROM plans_fts WHERE rowid = old.rowid;
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS plans_au
                    AFTER UPDATE ON plans BEGIN
                        DELETE FROM plans_fts WHERE rowid = old.rowid;
                        INSERT INTO plans_fts(rowid, task_text, task_hash)
                        VALUES (new.rowid, new.task_text, new.task_hash);
                    END
                """)
            except sqlite3.DatabaseError:
                # FTS5 table doesn't exist or is corrupted, skip triggers
                pass

            conn.commit()

            # Optional: Check for embedding dimension mismatch if table has data
            try:
                row = conn.execute(
                    "SELECT embedding FROM plans WHERE embedding IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    import config
                    latest_emb = json.loads(row[0])
                    if isinstance(latest_emb, list) and len(latest_emb) > 0:
                        db_dim = len(latest_emb)
                        if db_dim != config.EMBEDDING_DIMENSION:
                            print(f"\n{'!'*70}")
                            print(f"⚠️  WARNING: SQLite embedding dimension mismatch detected!")
                            print(f"{'!'*70}")
                            print(f"   Latest cached entry uses {db_dim} dimensions,")
                            print(f"   but your current config uses {config.EMBEDDING_DIMENSION} dimensions.")
                            print(f"   (This usually means you switched embedding providers.)")
                            print(f"   Hybrid search results may be inaccurate.")
                            print(f"   To fix this, either update .env or clear the cache: planner-shell clear-cache")
                            print(f"{'!'*70}\n")
            except Exception as e:
                # Don't fail the whole app for a warning check
                _logger.debug("SQLite dimension check error: %s", e)

    # ── Internal helpers ──────────────────────────────────────────

    def _valid_rows(self, conn: sqlite3.Connection) -> list[tuple]:
        """Return all non-expired (task_hash, task_text, plan, timestamp, embedding, url, markdown_file) rows."""
        return conn.execute(
            "SELECT task_hash, task_text, plan, timestamp, embedding, url, markdown_file "
            "FROM plans WHERE timestamp > ?",
            (self._cutoff(),),
        ).fetchall()

    # ── Public API — exact lookup ─────────────────────────────────

    def get(self, task: str) -> Optional[str]:
        """Fast O(1) exact-match lookup. Returns plan text or None."""
        self._ensure_integrity()
        with sqlite3.connect(self.db_path,
                             detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            row = conn.execute(
                "SELECT plan FROM plans WHERE task_hash = ? AND timestamp > ?",
                (self._hash_task(task), self._cutoff()),
            ).fetchone()
        return row[0] if row else None

    def get_by_hash(self, task_hash: str) -> Optional[str]:
        """Retrieve a plan by its exact task hash."""
        self._ensure_integrity()
        with sqlite3.connect(self.db_path,
                             detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            row = conn.execute(
                "SELECT plan FROM plans WHERE task_hash = ? AND timestamp > ?",
                (task_hash, self._cutoff()),
            ).fetchone()
        return row[0] if row else None

    def get_meta(self, task: str) -> Optional[dict]:
        """Return {task_hash, task_text, url, markdown_file} for *task*, or None."""
        self._ensure_integrity()
        task_hash = self._hash_task(task)
        with sqlite3.connect(self.db_path,
                             detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            row = conn.execute(
                "SELECT task_hash, task_text, url, markdown_file "
                "FROM plans WHERE task_hash = ? AND timestamp > ?",
                (task_hash, self._cutoff()),
            ).fetchone()
        if row:
            return {"task_hash": row[0], "task_text": row[1],
                    "url": row[2], "markdown_file": row[3]}
        return None

    def set(self, task: str, plan: str, skip_embedding: bool = False,
            embedding_text: Optional[str] = None, url: Optional[str] = None,
            markdown_file: Optional[str] = None, task_text: Optional[str] = None,
            task_hash: Optional[str] = None) -> None:
        """Store plan. Optionally skip embedding generation (e.g., for URL/markdown inputs).

        Args:
            task: The task text (used for hashing when task_hash is not provided)
            plan: The execution plan to store
            skip_embedding: If True, no embedding is generated
            embedding_text: Text to use for embedding generation. If None, uses 'task'.
            url: URL string if this plan was generated from a URL (optional)
            markdown_file: Markdown file path if this plan was generated from a file (optional)
            task_text: Text to store in the task_text column. If None, uses 'task'.
            task_hash: If provided, use this hash directly instead of computing from 'task'.
                       Used when overwriting an existing cache entry (e.g. after refine).
        """
        self._ensure_integrity()
        # Use the supplied hash when overwriting an existing entry; otherwise derive it.
        stored_hash = task_hash if task_hash is not None else self._hash_task(task)
        if skip_embedding:
            embedding = None
        else:
            # Use embedding_text if provided, otherwise fall back to task
            text_for_embedding = embedding_text if embedding_text is not None else task
            embedding = _get_embedding(text_for_embedding.strip())
        emb_json  = json.dumps(embedding) if embedding else None
        # Use task_text if provided, otherwise fall back to task
        stored_task_text = task_text if task_text is not None else task.strip()
        with sqlite3.connect(self.db_path,
                             detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans "
                "(task_hash, task_text, plan, timestamp, embedding, url, markdown_file) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (stored_hash, stored_task_text, plan, datetime.now(), emb_json, url, markdown_file),
            )
            conn.commit()

    # ── Public API — hybrid search ────────────────────────────────

    def hybrid_search(self, task: str) -> list[CacheCandidate]:
        """Return up to MAX_CANDIDATES scored candidates for *task*.

        Scoring
        ───────
        FTS score   : BM25 rank from SQLite FTS5, normalised to [0, 1].
                      SQLite returns negative BM25 values; we negate and
                      apply min-max normalisation across the result set.
        Vector score: cosine similarity between the query embedding and each
                      stored embedding.  Rows without an embedding get 0.
        Hybrid score: α × vec_score + (1-α) × fts_score   (α = ALPHA = 0.6)

        Candidates below SCORE_THRESHOLD are filtered out.
        """
        self._ensure_integrity()
        cutoff = self._cutoff()
        with sqlite3.connect(self.db_path,
                             detect_types=sqlite3.PARSE_DECLTYPES) as conn:

            # ── Step 1: BM25 via FTS5 ────────────────────────────
            # bm25() returns negative values (higher = more relevant → less negative)
            fts_rows = []
            try:
                # Check if FTS5 table exists and is accessible
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='plans_fts'"
                )
                if cursor.fetchone():
                    # Try a simple query to verify FTS5 is working
                    conn.execute("SELECT rowid FROM plans_fts LIMIT 1").fetchall()
                    
                    # FTS5 is available, perform the search
                    fts_rows = conn.execute(
                        """SELECT p.task_hash, p.task_text, p.plan, p.timestamp,
                                  p.embedding, p.url, p.markdown_file, -bm25(plans_fts) AS bm25_score
                           FROM plans_fts
                           JOIN plans p ON plans_fts.task_hash = p.task_hash
                           WHERE plans_fts MATCH ?
                             AND p.timestamp > ?
                           ORDER BY bm25_score DESC
                           LIMIT ?""",
                        (
                            # FTS5 query: each word is optional, boosting phrase match
                            " OR ".join(
                                re.sub(r'[^\w\s]', '', task.strip()).split()
                            ) or task.strip(),
                            cutoff,
                            self.MAX_CANDIDATES * 4,  # fetch extra before vector re-rank
                        ),
                    ).fetchall()
            except sqlite3.DatabaseError as e:
                # FTS5 query failed (corruption, missing content, etc.)
                print(f"⚠️  FTS5 search failed: {e}")
                print("   Attempting to rebuild FTS5 and retry...")
                
                # Try to rebuild FTS5 immediately with aggressive recovery
                try:
                    self._rebuild_fts_aggressive()
                    # Retry the FTS5 query after rebuild
                    fts_rows = conn.execute(
                        """SELECT p.task_hash, p.task_text, p.plan, p.timestamp,
                                  p.embedding, p.url, p.markdown_file, -bm25(plans_fts) AS bm25_score
                           FROM plans_fts
                           JOIN plans p ON plans_fts.task_hash = p.task_hash
                           WHERE plans_fts MATCH ?
                             AND p.timestamp > ?
                           ORDER BY bm25_score DESC
                           LIMIT ?""",
                        (
                            " OR ".join(
                                re.sub(r'[^\w\s]', '', task.strip()).split()
                            ) or task.strip(),
                            cutoff,
                            self.MAX_CANDIDATES * 4,
                        ),
                    ).fetchall()
                    if fts_rows:
                        print("✅ FTS5 rebuild successful - using FTS results.")
                except sqlite3.DatabaseError:
                    # Rebuild also failed, fall back to vector-only
                    print("   FTS5 rebuild failed. Falling back to vector-only search.")
                    fts_rows = []

            # ── Step 2: All valid rows for vector fallback ────────
            # (covers entries whose task_text has no FTS token overlap)
            all_rows = self._valid_rows(conn)

        # Build combined candidate set (FTS results + all rows for vector)
        seen: dict[str, list] = {}
        for row in fts_rows:
            # fts_rows: [task_hash, task_text, plan, timestamp, embedding, url, markdown_file, bm25_score]
            seen[row[0]] = list(row) + [True]   # True = has_fts_score

        for row in all_rows:
            if row[0] not in seen:
                # all_rows: [task_hash, task_text, plan, timestamp, embedding, url, markdown_file]
                # Add bm25 placeholder and has_fts flag
                seen[row[0]] = list(row) + [None, False]
            # Append bm25_score placeholder for non-FTS rows
            # row format in seen: [hash, text, plan, ts, emb, url, markdown_file, bm25|None, has_fts]

        # ── Step 3: Compute BM25 normalised scores ────────────────
        # Divide by the maximum score so the best hit = 1.0 and others are
        # proportional. Min-max normalization collapses to 0.0 when only one
        # document matches, so we use max-normalization instead.
        raw_bm25 = {h: v[7] for h, v in seen.items() if v[8] and v[7] is not None}
        if raw_bm25:
            bm25_max = max(raw_bm25.values())
            denom = bm25_max if bm25_max > 0 else 1.0
            norm_bm25 = {h: s / denom for h, s in raw_bm25.items()}
        else:
            norm_bm25 = {}

        # ── Step 4: Compute vector scores ─────────────────────────
        query_emb = _get_embedding(task.strip())

        # ── Step 5: Compose hybrid score ──────────────────────────
        candidates: list[CacheCandidate] = []
        for task_hash, vals in seen.items():
            # vals format: [task_hash, task_text, plan, timestamp, embedding, url, markdown_file, bm25_score, has_fts]
            _, task_text, plan, timestamp, emb_json, url, markdown_file = vals[:7]

            # Vector score
            vec_score = 0.0
            if query_emb is not None and emb_json is not None:
                try:
                    vec_score = max(0.0, _cosine(query_emb, json.loads(emb_json)))
                except (ValueError, json.JSONDecodeError):
                    vec_score = 0.0

            fts_score = norm_bm25.get(task_hash, 0.0)

            # If neither source has a signal, skip
            if fts_score == 0.0 and vec_score == 0.0:
                continue

            # Weight: use only available signals when one is absent
            if query_emb is None:
                # No embedding API → pure FTS
                hybrid = fts_score
            elif not norm_bm25:
                # No FTS hits → pure vector
                hybrid = vec_score
            else:
                hybrid = self.ALPHA * vec_score + (1 - self.ALPHA) * fts_score

            if hybrid < self.SCORE_THRESHOLD:
                continue

            candidates.append(CacheCandidate(
                task_hash=task_hash,
                task_text=task_text,
                plan=plan,
                score=hybrid,
                fts_score=fts_score,
                vec_score=vec_score,
                timestamp=timestamp if isinstance(timestamp, datetime)
                          else datetime.fromisoformat(str(timestamp)),
                url=url,
                markdown_file=markdown_file,
            ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[: self.MAX_CANDIDATES]

    # ── Public API — maintenance ──────────────────────────────────

    def clear(self) -> None:
        self._ensure_integrity()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM plans")
            conn.commit()

    def cleanup_expired(self, batch_size: int = 1000) -> int:
        """Delete expired entries in batches. Returns total rows deleted."""
        self._ensure_integrity()
        cutoff = self._cutoff()
        with sqlite3.connect(self.db_path) as conn:
            expired_count = conn.execute(
                "SELECT COUNT(*) FROM plans WHERE timestamp <= ?", (cutoff,)
            ).fetchone()[0]

            if expired_count == 0:
                print("✅ No expired plan cache entries to clean")
                return 0

            deleted = 0
            while deleted < expired_count:
                cur = conn.execute(
                    """DELETE FROM plans WHERE rowid IN (
                           SELECT rowid FROM plans WHERE timestamp <= ? LIMIT ?
                       )""",
                    (cutoff, batch_size),
                )
                conn.commit()
                deleted += cur.rowcount
                if cur.rowcount == 0:
                    break

        print(f"🧹 Cleaned up {deleted} expired plan cache entries")
        return deleted

    def get_stats(self) -> dict:
        self._ensure_integrity()
        cutoff = self._cutoff()
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
            valid = conn.execute(
                "SELECT COUNT(*) FROM plans WHERE timestamp > ?", (cutoff,)
            ).fetchone()[0]
            with_emb = conn.execute(
                "SELECT COUNT(*) FROM plans WHERE embedding IS NOT NULL AND timestamp > ?",
                (cutoff,),
            ).fetchone()[0]
        return {"total_plans": total, "valid_plans": valid,
                "plans_with_embedding": with_emb,
                "expired_plans": total - valid, "ttl_days": self.ttl_days}

    def list_plans(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """List recent plans with metadata and 1-based index.

        Args:
            limit: Maximum number of plans to return
            offset: Number of plans to skip (for pagination)

        Returns:
            list of dicts with keys: index, task_hash, task_text, timestamp, url, markdown_file
            index is 1-based and represents position in the list (1 = newest)
        """
        self._ensure_integrity()
        cutoff = self._cutoff()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT task_hash, task_text, timestamp, url, markdown_file
                   FROM plans
                   WHERE timestamp > ?
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (cutoff, limit, offset)
            ).fetchall()

        result = []
        for idx, row in enumerate(rows, start=1):
            task_hash, task_text, timestamp, url, markdown_file = row
            result.append({
                "index": idx,
                "task_hash": task_hash,
                "task_text": task_text,
                "timestamp": timestamp if isinstance(timestamp, datetime)
                            else datetime.fromisoformat(str(timestamp)),
                "url": url,
                "markdown_file": markdown_file,
            })
        return result

    def delete(self, task_text: str, index: Optional[int] = None) -> bool:
        """Delete a specific plan by task text (partial match) or by index.

        Args:
            task_text: Task text to match (partial)
            index: Optional 1-based index from list_plans() output (newest first)

        Returns:
            True if a plan was deleted, False if no match found
        """
        self._ensure_integrity()
        with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            # If index is provided, use it (1-based, newest first)
            if index is not None:
                if index < 1:
                    print("❌ Index must be 1 or greater")
                    return False
                # Get the plan at the given index from the ordered list
                rows = conn.execute(
                    """SELECT task_hash FROM plans
                       WHERE timestamp > ?
                       ORDER BY timestamp DESC
                       LIMIT 1 OFFSET ?""",
                    (self._cutoff(), index - 1)
                ).fetchall()
                if not rows:
                    print(f"❌ No plan found at index {index}")
                    return False
                task_hash = rows[0][0]
                cur = conn.execute(
                    "DELETE FROM plans WHERE task_hash = ?",
                    (task_hash,)
                )
                conn.commit()
                deleted = cur.rowcount > 0
                if deleted:
                    print(f"✅ Deleted plan at index {index}")
                return deleted

            # Partial match on task_text only (hash matching removed)
            cur = conn.execute(
                "DELETE FROM plans WHERE task_hash IN ("
                "SELECT task_hash FROM plans WHERE task_text LIKE ?"
                ")",
                (f"%{task_text}%",)
            )
            conn.commit()
            return cur.rowcount > 0
