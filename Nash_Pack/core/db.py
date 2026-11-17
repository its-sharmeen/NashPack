import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "scans.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_label TEXT,
            image_path TEXT,
            status TEXT,
            score INTEGER,
            mandatory_missing INTEGER,
            warnings INTEGER,
            ocr_confidence REAL,
            result_json TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_scan(product_label, image_path, result):
    conn = get_conn()

    # `mandatory_missing` / `warnings` come back from the compliance engine
    # as *lists* (of missing declaration names / warning messages) — the
    # `scans` table stores their *counts* for fast dashboard queries. The
    # full lists still live inside `result_json`.
    mandatory_missing = result.get("mandatory_missing") or []
    warnings = result.get("warnings") or []

    mandatory_missing_count = (
        len(mandatory_missing)
        if isinstance(mandatory_missing, (list, tuple, set))
        else int(mandatory_missing or 0)
    )

    warnings_count = (
        len(warnings)
        if isinstance(warnings, (list, tuple, set))
        else int(warnings or 0)
    )

    cur = conn.execute(
        """INSERT INTO scans
           (product_label, image_path, status, score, mandatory_missing, warnings, ocr_confidence, result_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product_label,
            image_path,
            result["status"],
            result["score"],
            mandatory_missing_count,
            warnings_count,
            result["ocr_confidence"],
            json.dumps(result),
            result["timestamp"],
        ),
    )
    conn.commit()
    scan_id = cur.lastrowid
    conn.close()
    return scan_id


def get_scan(scan_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d["result_json"])
    return d


def list_scans(limit=200, query=None, status=None):
    """
    List scans, most recent first. Optionally filter by a free-text
    search over the product label (and, loosely, over the raw result
    JSON) and/or by exact compliance status — powers the register's
    search/retrieval facility.
    """
    conn = get_conn()

    sql = (
        "SELECT id, product_label, image_path, status, score, "
        "mandatory_missing, warnings, ocr_confidence, created_at "
        "FROM scans WHERE 1=1"
    )
    params = []

    if query:
        sql += " AND (product_label LIKE ? OR result_json LIKE ? OR CAST(id AS TEXT) = ?)"
        like = f"%{query.strip()}%"
        params.extend([like, like, query.strip()])

    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def dashboard_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM scans").fetchone()["c"]
    compliant = conn.execute("SELECT COUNT(*) c FROM scans WHERE status='COMPLIANT'").fetchone()["c"]
    warn = conn.execute("SELECT COUNT(*) c FROM scans WHERE status='COMPLIANT_WITH_WARNINGS'").fetchone()["c"]
    non_compliant = conn.execute("SELECT COUNT(*) c FROM scans WHERE status='NON_COMPLIANT'").fetchone()["c"]
    needs_rescan = conn.execute("SELECT COUNT(*) c FROM scans WHERE status='REQUIRES_RESCAN'").fetchone()["c"]
    errored = conn.execute("SELECT COUNT(*) c FROM scans WHERE status='ERROR'").fetchone()["c"]
    avg_score_row = conn.execute("SELECT AVG(score) a FROM scans").fetchone()
    avg_score = round(avg_score_row["a"], 1) if avg_score_row["a"] is not None else 0
    conn.close()
    return {
        "total": total,
        "compliant": compliant,
        "warnings": warn,
        "non_compliant": non_compliant,
        "needs_rescan": needs_rescan,
        "errored": errored,
        "avg_score": avg_score,
    }
