"""
AURA OS — SQLite Database
Persistent storage for tasks, logs, and knowledge nodes.
Auto-creates aura.db on first run. Zero config needed.
"""

import sqlite3
import json
import uuid
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "aura.db"


# ── CONNECTION ────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    """Context manager that opens, yields, commits, and closes a connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── SETUP ─────────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist yet. Called once at startup."""
    with get_conn() as conn:
        conn.executescript("""
            -- Every task submitted by the user
            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                query       TEXT NOT NULL,
                context     TEXT,
                status      TEXT DEFAULT 'queued',
                result      TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            -- Every log line streamed from agents
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     TEXT NOT NULL,
                time        TEXT NOT NULL,
                agent       TEXT NOT NULL,
                message     TEXT NOT NULL,
                level       TEXT DEFAULT 'info',
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            -- Knowledge graph nodes
            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                tags        TEXT DEFAULT '[]',
                source      TEXT DEFAULT 'aura',
                created_at  TEXT NOT NULL
            );

            -- Knowledge graph edges (relationships between nodes)
            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node   TEXT NOT NULL,
                to_node     TEXT NOT NULL,
                relation    TEXT NOT NULL,
                weight      INTEGER DEFAULT 1,
                FOREIGN KEY (from_node) REFERENCES knowledge_nodes(id),
                FOREIGN KEY (to_node)   REFERENCES knowledge_nodes(id)
            );
        """)
    print(f"✦ Database ready → {DB_PATH}")


# ── TASKS ─────────────────────────────────────────────────────────────────────

def create_task(task_id: str, query: str, context: str | None = None) -> dict:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (id, query, context, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (task_id, query, context, "queued", now, now)
        )
    return get_task(task_id)


def update_task(task_id: str, status: str, result: str | None = None):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=?",
            (status, result, now, task_id)
        )


def get_task(task_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        task["logs"] = get_task_logs(task_id)
        return task


def get_all_tasks() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


# ── LOGS ──────────────────────────────────────────────────────────────────────

def add_log(task_id: str, time: str, agent: str, message: str, level: str = "info"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (task_id, time, agent, message, level) VALUES (?,?,?,?,?)",
            (task_id, time, agent, message, level)
        )


def get_task_logs(task_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT time, agent, message, level FROM logs WHERE task_id=? ORDER BY id ASC",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── KNOWLEDGE NODES ───────────────────────────────────────────────────────────

def add_knowledge_node(title: str, content: str, tags: list, source: str = "aura") -> dict:
    node_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    tags_json = json.dumps(tags)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO knowledge_nodes (id, title, content, tags, source, created_at) VALUES (?,?,?,?,?,?)",
            (node_id, title, content, tags_json, source, now)
        )

        # Auto-link nodes sharing tags
        existing = conn.execute(
            "SELECT id, tags FROM knowledge_nodes WHERE id != ?", (node_id,)
        ).fetchall()

        for row in existing:
            existing_tags = json.loads(row["tags"] or "[]")
            shared = set(tags) & set(existing_tags)
            if shared:
                conn.execute(
                    "INSERT INTO knowledge_edges (from_node, to_node, relation, weight) VALUES (?,?,?,?)",
                    (node_id, row["id"], f"shares_tag:{list(shared)[0]}", len(shared))
                )

    return get_knowledge_node(node_id)


def get_knowledge_node(node_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"] or "[]")
        return d


def get_all_knowledge() -> dict:
    with get_conn() as conn:
        nodes = conn.execute(
            "SELECT * FROM knowledge_nodes ORDER BY created_at DESC"
        ).fetchall()
        edges = conn.execute("SELECT * FROM knowledge_edges").fetchall()

        node_list = []
        for n in nodes:
            d = dict(n)
            d["tags"] = json.loads(d["tags"] or "[]")
            node_list.append(d)

        return {
            "nodes": node_list,
            "edges": [dict(e) for e in edges],
            "stats": {
                "total_nodes": len(node_list),
                "total_edges": len(edges),
            }
        }


def search_knowledge(query: str, top_k: int = 5) -> list:
    """Keyword search across title, content, and tags."""
    if not query:
        return []
    keywords = query.lower().split()

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_nodes ORDER BY created_at DESC"
        ).fetchall()

    scored = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d["tags"] or "[]")
        text = (d["title"] + " " + d["content"] + " " + " ".join(d["tags"])).lower()
        score = sum(
            3 if kw in d["title"].lower() else
            2 if any(kw in t.lower() for t in d["tags"]) else
            text.count(kw)
            for kw in keywords if kw in text
        )
        if score > 0:
            scored.append((score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [n for _, n in scored[:top_k]]


def delete_knowledge_node(node_id: str) -> bool:
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM knowledge_nodes WHERE id=?", (node_id,)).fetchone()
        if not rows:
            return False
        conn.execute("DELETE FROM knowledge_nodes WHERE id=?", (node_id,))
        conn.execute("DELETE FROM knowledge_edges WHERE from_node=? OR to_node=?", (node_id, node_id))
    return True


# ── STATS ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    with get_conn() as conn:
        tasks_total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        tasks_done  = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='complete'").fetchone()[0]
        logs_total  = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        nodes_total = conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0]
        edges_total = conn.execute("SELECT COUNT(*) FROM knowledge_edges").fetchone()[0]

    return {
        "tasks_total": tasks_total,
        "tasks_complete": tasks_done,
        "logs_total": logs_total,
        "knowledge_nodes": nodes_total,
        "knowledge_edges": edges_total,
    }