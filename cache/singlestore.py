#!/usr/bin/env python3
"""
SingleStore-backed plan cache with vector search support.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

import config
from .base import BasePlanCache, _get_embedding
from common_types import CacheCandidate

# Module-level logger
_logger = logging.getLogger(__name__)


class SingleStorePlanCache(BasePlanCache):
    """SingleStore-backed cache for execution plans with a configurable TTL.

    Storage layout
    ──────────────
    plans(task_hash PK, task_text, plan, timestamp DATETIME, embedding VECTOR(1536))
      • embedding: JSON-encoded float list produced by text-embedding-3-small.
        NULL when the OpenAI API is unavailable at write time.

    Hybrid search
    ─────────────
    Uses SingleStore's vector search capabilities (DOT_PRODUCT or EUCLIDEAN_DISTANCE)
    combined with text search if needed. Note: FTS5 is SQLite-specific; SingleStore
    uses full-text search via SEARCH INDEX or LIKE queries for text matching.
    """

    # Score threshold and max candidates from config (will be set by factory)
    ALPHA: float = 0.6
    SCORE_THRESHOLD: float = 0.0
    MAX_CANDIDATES: int = 3

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "inst_agent",
        table: str = "plans",
        ttl_days: int = 30,
    ):
        try:
            import singlestoredb as s2
            self.s2 = s2
        except ImportError:
            raise ImportError(
                "singlestoredb package is not installed. "
                "Install it with: pip install singlestoredb"
            )
        # SQL injection guard: only allow safe identifier characters in table name.
        # Parameterised queries cannot be used for identifiers, so we whitelist instead.
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', table):
            raise ValueError(
                f"Invalid table name {table!r}. "
                "Only letters, digits, and underscores are allowed (max 64 chars)."
            )
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.table = table
        self.ttl_days = ttl_days
        self._init_db()
        print(f"Using SingleStore plan cache backend (host={host}, db={database})")

    def _connect(self):
        """Return a new SingleStore connection using stored credentials."""
        return self.s2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )

    def _init_db(self) -> None:
        """Initialize the SingleStore database and tables."""
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                # Check if table exists
                cursor.execute(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                    (self.table,)
                )
                table_exists = cursor.fetchone()[0] > 0

                if table_exists:
                    # Check if primary key on task_hash exists
                    cursor.execute("""
                        SELECT COUNT(*) FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = %s
                          AND COLUMN_NAME = 'task_hash'
                          AND CONSTRAINT_NAME = 'PRIMARY'
                    """, (self.table,))
                    has_pk = cursor.fetchone()[0] > 0

                    if not has_pk:
                        print(f"⚠️ Table {self.table} exists but lacks PRIMARY KEY on task_hash. Dropping and recreating...")
                        cursor.execute(f"DROP TABLE {self.table}")
                        conn.commit()
                        table_exists = False
                    else:
                        # Check embedding dimension
                        cursor.execute(
                            "SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = 'embedding'",
                            (self.table,)
                        )
                        row = cursor.fetchone()
                        if row:
                            col_type = row[0]  # e.g., "vector(1536)"
                            import re as _re
                            match = _re.search(r'vector\((\d+)\)', col_type, _re.IGNORECASE)
                            if match:
                                current_dim = int(match.group(1))
                                if current_dim != config.EMBEDDING_DIMENSION:
                                    print(f"\n❌ CRITICAL: SingleStore embedding dimension mismatch!")
                                    print(f"   Table '{self.table}' uses VECTOR({current_dim}), but your config requires VECTOR({config.EMBEDDING_DIMENSION}).")
                                    print(f"   (This happens when switching between OpenAI and Ollama/Local embeddings)")
                                    print(f"   To fix this, either set EMBEDDING_DIMENSION={current_dim} in your .env,")
                                    print(f"   or drop the table manually to allow the agent to recreate it: DROP TABLE {self.table};")
                                    print()
                                    raise ValueError(f"SingleStore dimension mismatch: {current_dim} vs {config.EMBEDDING_DIMENSION}")

                if not table_exists:
                    # Create plans table as COLUMNSTORE (required for vector and fulltext indexes)
                    cursor.execute(f"""
                        CREATE TABLE {self.table} (
                            task_hash VARCHAR(64) NOT NULL,
                            task_text TEXT NOT NULL,
                            plan LONGTEXT NOT NULL,
                            timestamp DATETIME NOT NULL,
                            embedding VECTOR({config.EMBEDDING_DIMENSION}) NULL,
                            url TEXT NULL,
                            markdown_file TEXT NULL,
                            PRIMARY KEY (task_hash),
                            SORT KEY (timestamp)
                        )
                    """)

                    # Create full-text search index
                    try:
                        cursor.execute(f"""
                            ALTER TABLE {self.table}
                            ADD FULLTEXT USING VERSION 2 fts_task_text (task_text)
                        """)
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "already exists" not in error_msg and "duplicate" not in error_msg:
                            print(f"⚠️  Could not create fulltext index: {e}")

                    conn.commit()
                    print(f"✅ Table {self.table} created with correct schema.")
        except Exception as e:
            _logger.debug("SingleStore _init_db error: %s", e)
            print("⚠️  Error initializing SingleStore cache (check logs for details)")
            raise
        finally:
            if 'conn' in locals():
                conn.close()

    def get(self, task: str) -> Optional[str]:
        """Fast O(1) exact-match lookup. Returns plan text or None."""
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT plan FROM {self.table} WHERE task_hash = %s AND timestamp > %s",
                    (self._hash_task(task), self._cutoff()),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            _logger.debug("SingleStore get error: %s", e)
            print("⚠️  Cache lookup failed (check logs for details)")
            return None
        finally:
            if 'conn' in locals():
                conn.close()

    def get_by_hash(self, task_hash: str) -> Optional[str]:
        """Retrieve a plan by its exact task hash."""
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT plan FROM {self.table} WHERE task_hash = %s AND timestamp > %s",
                    (task_hash, self._cutoff()),
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            _logger.debug("SingleStore get_by_hash error: %s", e)
            print("⚠️  Cache lookup failed (check logs for details)")
            return None
        finally:
            if 'conn' in locals():
                conn.close()

    def get_meta(self, task: str) -> Optional[dict]:
        """Return {task_hash, task_text, url, markdown_file} for *task*, or None."""
        task_hash = self._hash_task(task)
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT task_hash, task_text, url, markdown_file "
                    f"FROM {self.table} WHERE task_hash = %s AND timestamp > %s",
                    (task_hash, self._cutoff()),
                )
                row = cursor.fetchone()
            if row:
                return {"task_hash": row[0], "task_text": row[1],
                        "url": row[2], "markdown_file": row[3]}
            return None
        except Exception as e:
            _logger.debug("SingleStore get_meta error: %s", e)
            return None
        finally:
            if 'conn' in locals():
                conn.close()

    def set(self, task: str, plan: str, skip_embedding: bool = False,
            embedding_text: Optional[str] = None, url: Optional[str] = None,
            markdown_file: Optional[str] = None, task_text: Optional[str] = None,
            task_hash: Optional[str] = None) -> None:
        """Store plan. Optionally skip embedding generation.

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
        # Use the supplied hash when overwriting an existing entry; otherwise derive it.
        stored_hash = task_hash if task_hash is not None else self._hash_task(task)
        if skip_embedding:
            embedding = None
        else:
            # Use embedding_text if provided, otherwise fall back to task
            text_for_embedding = embedding_text if embedding_text is not None else task
            embedding = _get_embedding(text_for_embedding.strip())
        emb_json = json.dumps(embedding) if embedding else None
        # Use task_text if provided, otherwise fall back to task
        stored_task_text = task_text if task_text is not None else task.strip()

        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""INSERT INTO {self.table} (task_hash, task_text, plan, timestamp, embedding, url, markdown_file)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        task_text = VALUES(task_text),
                        plan = VALUES(plan),
                        timestamp = VALUES(timestamp),
                        embedding = VALUES(embedding),
                        url = VALUES(url),
                        markdown_file = VALUES(markdown_file)""",
                    (stored_hash, stored_task_text, plan, datetime.now(), emb_json, url, markdown_file),
                )
                conn.commit()
        except Exception as e:
            _logger.debug("SingleStore set error: %s", e)
            print("⚠️  Cache write failed (check logs for details)")
            raise
        finally:
            if 'conn' in locals():
                conn.close()

    def _escape_fts_query(self, query: str) -> str:
        """Escape special characters for full-text search.

        SingleStore FTS version 2 uses Lucene syntax.
        Special characters need to be escaped with backslash.
        """
        if not query or not query.strip():
            return ""

        # Remove leading/trailing whitespace
        query = query.strip()

        # Special characters that need escaping in Lucene queries
        # Reference: https://lucene.apache.org/core/9_10_0/queryparser/org/apache/lucene/queryparser/classic/package-summary.html
        special_chars = [
            '\\',  # Backslash must be escaped first
            '+', '-', '!', '(', ')', '{', '}', '[', ']',
            '^', '"', '~', '*', '?', ':', '/'
        ]

        escaped = query
        for char in special_chars:
            escaped = escaped.replace(char, '\\' + char)

        # Handle && and || operators (must be uppercase to be recognized as operators)
        # If lowercase, they should be escaped
        escaped = escaped.replace('&&', '\\&\\&')
        escaped = escaped.replace('||', '\\|\\|')

        return escaped

    def hybrid_search(self, task: str) -> list[CacheCandidate]:
        """Return up to MAX_CANDIDATES scored candidates for *task*."""
        query_emb = _get_embedding(task.strip())
        if query_emb is None:
            return []

        cutoff = self._cutoff()

        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                # Convert query embedding to JSON for VECTOR casting
                query_vec_json = json.dumps(query_emb)

                # Build FTS query
                escaped = self._escape_fts_query(task)

                # If escaped query is empty, skip FTS and use only vector search
                if not escaped:
                    print("⚠️  Empty FTS query, using vector search only")
                    cursor.execute(f"""
                        SELECT
                            task_hash,
                            task_text,
                            plan,
                            timestamp,
                            url,
                            markdown_file,
                            0 AS ft_score,
                            embedding <*> (%s):>VECTOR({config.EMBEDDING_DIMENSION}) AS vec_score
                        FROM {self.table}
                        WHERE timestamp > %s
                        ORDER BY vec_score DESC
                        LIMIT %s
                    """, (query_vec_json, cutoff, 200))

                    rows = cursor.fetchall()
                    candidates = []
                    for idx, row in enumerate(rows, 1):
                        task_hash, task_text, plan, timestamp, url, markdown_file, fts_score, vec_score = row
                        combined_score = 0.3 * (1.0 / (idx + 60))
                        print(f"   Vector score: {vec_score:.6f}, Combined: {combined_score:.6f}")
                        if combined_score < self.SCORE_THRESHOLD:
                            continue
                        if not isinstance(timestamp, datetime):
                            try:
                                timestamp = datetime.fromisoformat(str(timestamp))
                            except (ValueError, TypeError):
                                timestamp = datetime.now()
                        candidates.append(CacheCandidate(
                            task_hash=task_hash,
                            task_text=task_text,
                            plan=plan,
                            score=float(combined_score),
                            fts_score=float(fts_score),
                            vec_score=float(vec_score),
                            timestamp=timestamp,
                            url=url,
                            markdown_file=markdown_file,
                        ))
                    return candidates[: self.MAX_CANDIDATES]

                # Build BM25 query expression
                fts_query = f'task_text:({escaped})'

                print("🔍 Hybrid Search:")
                print(f"   BM25 Query: {fts_query}")
                print("   Vector Search: Using embedding similarity (1536 dimensions)")

                cursor.execute(f"""
                    WITH scored_results AS (
                        SELECT
                            task_hash,
                            task_text,
                            plan,
                            timestamp,
                            url,
                            markdown_file,
                            BM25({self.table}, %s) AS ft_score,
                            embedding <*> (%s):>VECTOR({config.EMBEDDING_DIMENSION}) AS vec_score,
                            ROW_NUMBER() OVER (ORDER BY BM25({self.table}, %s) DESC) AS fts_rank,
                            ROW_NUMBER() OVER (ORDER BY embedding <*> (%s):>VECTOR({config.EMBEDDING_DIMENSION}) DESC) AS vs_rank
                        FROM {self.table}
                        WHERE timestamp > %s
                            AND (BM25({self.table}, %s) > 0
                                OR embedding <*> (%s):>VECTOR({config.EMBEDDING_DIMENSION}) > 0)
                        LIMIT 500
                    )
                    SELECT
                        task_hash,
                        task_text,
                        plan,
                        timestamp,
                        url,
                        markdown_file,
                        ft_score,
                        vec_score,
                        fts_rank,
                        vs_rank,
                        0.3 * (1.0 / (fts_rank + 60)) + 0.7 * (1.0 / (vs_rank + 60)) AS combined_score
                    FROM scored_results
                    ORDER BY combined_score DESC
                    LIMIT %s
                """, (fts_query, query_vec_json, fts_query, query_vec_json, cutoff, fts_query, query_vec_json, self.MAX_CANDIDATES * 4))

                rows = cursor.fetchall()

                if not rows:
                    return []

                # Normalize BM25 scores to [0, 1] range (like SQLite backend)
                # Extract raw BM25 scores for normalization
                raw_bm25_scores = []
                for row in rows:
                    fts_score = row[6]
                    if fts_score is not None:
                        raw_bm25_scores.append(float(fts_score))

                # Calculate max for normalization (avoid division by zero)
                bm25_max = max(raw_bm25_scores) if raw_bm25_scores else 1.0
                if bm25_max <= 0:
                    bm25_max = 1.0

                candidates = []
                for row in rows:
                    task_hash, task_text, plan, timestamp, url, markdown_file, fts_score, vec_score, _, _, combined_score = row

                    if combined_score < self.SCORE_THRESHOLD:
                        continue

                    if not isinstance(timestamp, datetime):
                        try:
                            timestamp = datetime.fromisoformat(str(timestamp))
                        except (ValueError, TypeError):
                            timestamp = datetime.now()

                    # Normalize FTS score: divide by max to get [0, 1] range
                    norm_fts_score = float(fts_score) / bm25_max if fts_score is not None else 0.0

                    candidates.append(CacheCandidate(
                        task_hash=task_hash,
                        task_text=task_text,
                        plan=plan,
                        score=float(combined_score),
                        fts_score=norm_fts_score,
                        vec_score=float(vec_score),
                        timestamp=timestamp,
                        url=url,
                        markdown_file=markdown_file,
                    ))

                return candidates[: self.MAX_CANDIDATES]

        except Exception as e:
            _logger.debug("SingleStore hybrid_search error: %s", e)
            print(f"⚠️  Hybrid search failed: {e}")
            return []
        finally:
            if 'conn' in locals():
                conn.close()

    def clear(self) -> None:
        """Delete all cached plans."""
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM {self.table}")
                conn.commit()
        except Exception as e:
            _logger.debug("SingleStore clear error: %s", e)
            print("⚠️  Cache clear failed (check logs for details)")
        finally:
            if 'conn' in locals():
                conn.close()

    def cleanup_expired(self, batch_size: int = 1000) -> int:
        """Delete expired entries in batches. Returns total rows deleted."""
        cutoff = self._cutoff()
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {self.table} WHERE timestamp <= %s",
                    (cutoff,),
                )
                expired_count = cursor.fetchone()[0]

                if expired_count == 0:
                    print("✅ No expired plan cache entries to clean")
                    return 0

                # SingleStore/MySQL doesn't support DELETE with LIMIT in subquery
                # So we delete in batches using a simple approach
                try:
                    cursor.execute(
                        f"DELETE FROM {self.table} WHERE timestamp <= %s",
                        (cutoff,),
                    )
                    conn.commit()
                    deleted = cursor.rowcount
                except Exception as e:
                    _logger.debug("SingleStore cleanup batch error: %s", e)
                    print("⚠️  Cache cleanup batch failed (check logs for details)")
                    deleted = 0

                print(f"🧹 Cleaned up {deleted} expired plan cache entries")
                return deleted
        except Exception as e:
            _logger.debug("SingleStore cleanup_expired error: %s", e)
            print("⚠️  Cache cleanup failed (check logs for details)")
            return 0
        finally:
            if 'conn' in locals():
                conn.close()

    def get_stats(self) -> dict:
        """Get statistics about the cache."""
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {self.table}")
                total = cursor.fetchone()[0]

                cursor.execute(
                    f"SELECT COUNT(*) FROM {self.table} WHERE timestamp > %s",
                    (self._cutoff(),),
                )
                valid = cursor.fetchone()[0]

                cursor.execute(
                    f"SELECT COUNT(*) FROM {self.table} WHERE embedding IS NOT NULL AND timestamp > %s",
                    (self._cutoff(),),
                )
                with_emb = cursor.fetchone()[0]

                return {
                    "total_plans": total,
                    "valid_plans": valid,
                    "plans_with_embedding": with_emb,
                    "expired_plans": total - valid,
                    "ttl_days": self.ttl_days,
                }
        except Exception as e:
            _logger.debug("SingleStore get_stats error: %s", e)
            print("⚠️  Cache stats unavailable (check logs for details)")
            return {
                "total_plans": 0,
                "valid_plans": 0,
                "plans_with_embedding": 0,
                "expired_plans": 0,
                "ttl_days": self.ttl_days,
            }
        finally:
            if 'conn' in locals():
                conn.close()

    def list_plans(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """List recent plans with metadata and 1-based index.

        Args:
            limit: Maximum number of plans to return
            offset: Number of plans to skip (for pagination)

        Returns:
            list of dicts with keys: index, task_hash, task_text, timestamp, url, markdown_file
            index is 1-based and represents position in the list (1 = newest)
        """
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""SELECT task_hash, task_text, timestamp, url, markdown_file
                        FROM {self.table}
                        WHERE timestamp > %s
                        ORDER BY timestamp DESC
                        LIMIT %s OFFSET %s""",
                    (self._cutoff(), limit, offset)
                )
                rows = cursor.fetchall()

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
        except Exception as e:
            _logger.debug("SingleStore list_plans error: %s", e)
            print("⚠️  Could not list plans (check logs for details)")
            return []
        finally:
            if 'conn' in locals():
                conn.close()

    def delete(self, task_text: str, index: Optional[int] = None) -> bool:
        """Delete a specific plan by task text (partial match) or by index.

        Args:
            task_text: Task text to match (partial)
            index: Optional 1-based index from list_plans() output (newest first)

        Returns:
            True if a plan was deleted, False if no match found
        """
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                # If index is provided, use it (1-based, newest first)
                if index is not None:
                    if index < 1:
                        print("❌ Index must be 1 or greater")
                        return False
                    # Get the plan at the given index from the ordered list
                    cursor.execute(
                        f"""SELECT task_hash FROM {self.table}
                           WHERE timestamp > %s
                           ORDER BY timestamp DESC
                           LIMIT 1 OFFSET %s""",
                        (self._cutoff(), index - 1)
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        print(f"❌ No plan found at index {index}")
                        return False
                    task_hash = rows[0][0]
                    cursor.execute(
                        f"DELETE FROM {self.table} WHERE task_hash = %s",
                        (task_hash,)
                    )
                    conn.commit()
                    deleted = cursor.rowcount > 0
                    if deleted:
                        print(f"✅ Deleted plan at index {index}")
                    return deleted

                # Partial match on task_text only (hash matching removed)
                cursor.execute(
                    f"DELETE FROM {self.table} WHERE task_hash IN ("
                    f"SELECT task_hash FROM {self.table} WHERE task_text LIKE %s"
                    ")",
                    (f"%{task_text}%",)
                )
                conn.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    print(f"✅ Deleted {deleted} plan(s)")
                return deleted > 0
        except Exception as e:
            _logger.debug("SingleStore delete error: %s", e)
            print("⚠️  Delete failed (check logs for details)")
            return False
        finally:
            if 'conn' in locals():
                conn.close()

    def optimize(self) -> None:
        """Flush in-memory rowstore rows to columnstore format."""
        try:
            conn = self._connect()
            with conn.cursor() as cursor:
                cursor.execute(f"OPTIMIZE TABLE {self.table} FLUSH")
                conn.commit()
        except Exception as e:
            _logger.debug("SingleStore optimize error: %s", e)
            print("⚠️  Cache optimization failed (check logs for details)")
        finally:
            if 'conn' in locals():
                conn.close()
