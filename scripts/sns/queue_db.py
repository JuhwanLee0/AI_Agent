import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from scripts.sns.config import DEFAULT_DB_PATH

class QueueDB:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS content_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    cover_title TEXT NOT NULL,
                    slides_json TEXT NOT NULL,
                    thread_text TEXT NOT NULL,
                    core_claims_json TEXT NOT NULL,
                    source_urls_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT_SCHEDULED',
                    verification_log TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_date ON content_queue (scheduled_date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON content_queue (status);")
            conn.commit()

    def add_draft(
        self,
        scheduled_date: str,
        category: str,
        topic: str,
        cover_title: str,
        slides: List[Dict[str, Any]],
        thread_text: str,
        core_claims: List[str],
        source_urls: List[str],
    ) -> int:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO content_queue (
                    scheduled_date, category, topic, cover_title,
                    slides_json, thread_text, core_claims_json, source_urls_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT_SCHEDULED', ?, ?)
                """,
                (
                    scheduled_date,
                    category,
                    topic,
                    cover_title,
                    json.dumps(slides, ensure_ascii=False),
                    thread_text,
                    json.dumps(core_claims, ensure_ascii=False),
                    json.dumps(source_urls, ensure_ascii=False),
                    now_str,
                    now_str,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM content_queue WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def get_items_by_date(self, scheduled_date: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM content_queue WHERE scheduled_date = ?"
        params = [scheduled_date]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def list_items(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM content_queue"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY scheduled_date DESC, id DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_all_items(self) -> List[Dict[str, Any]]:
        return self.list_items(limit=500)


    def update_verification_result(
        self,
        item_id: int,
        status: str,
        verification_log: str,
        slides: Optional[List[Dict[str, Any]]] = None,
        thread_text: Optional[str] = None,
        cover_title: Optional[str] = None,
    ):
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            updates = ["status = ?", "verification_log = ?", "updated_at = ?"]
            params = [status, verification_log, now_str]

            if slides is not None:
                updates.append("slides_json = ?")
                params.append(json.dumps(slides, ensure_ascii=False))
            if thread_text is not None:
                updates.append("thread_text = ?")
                params.append(thread_text)
            if cover_title is not None:
                updates.append("cover_title = ?")
                params.append(cover_title)

            params.append(item_id)
            query = f"UPDATE content_queue SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

    def delete_item(self, item_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM content_queue WHERE id = ?", (item_id,))
            conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["slides"] = json.loads(data["slides_json"])
        except Exception:
            data["slides"] = []
        try:
            data["core_claims"] = json.loads(data["core_claims_json"])
        except Exception:
            data["core_claims"] = []
        try:
            data["source_urls"] = json.loads(data["source_urls_json"])
        except Exception:
            data["source_urls"] = []
        return data
