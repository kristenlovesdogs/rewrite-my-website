"""
Storage layer for Rewrite My Website.
Uses Postgres if DATABASE_URL is set, otherwise falls back to filesystem (CSV + JSON files).
"""
import os
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

USE_POSTGRES = bool(os.environ.get("DATABASE_URL"))

ROOT = Path(__file__).parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
EMAILS_CSV = DATA / "emails.csv"
DATA.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)
if not EMAILS_CSV.exists():
    EMAILS_CSV.write_text("timestamp,email,url,report_id,ip\n")


def _connect():
    import psycopg
    url = os.environ["DATABASE_URL"]
    # Render gives postgres:// but psycopg prefers postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return psycopg.connect(url)


def init_schema():
    """Create tables if they don't exist. Call once at startup."""
    if not USE_POSTGRES:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    url TEXT NOT NULL,
                    email TEXT,
                    data JSONB NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS emails (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    email TEXT NOT NULL,
                    url TEXT NOT NULL,
                    report_id TEXT,
                    ip TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ip_usage (
                    ip TEXT PRIMARY KEY,
                    day DATE NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0
                )
            """)
        conn.commit()


# ============== Reports ==============

def save_report(report_id: str, data: dict):
    if USE_POSTGRES:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO reports (id, url, email, data) VALUES (%s, %s, %s, %s)",
                    (report_id, data.get("_url", ""), data.get("_email"), json.dumps(data)),
                )
            conn.commit()
    else:
        (REPORTS / f"{report_id}.json").write_text(json.dumps(data))


def load_report(report_id: str):
    if USE_POSTGRES:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM reports WHERE id = %s", (report_id,))
                row = cur.fetchone()
                if not row:
                    return None
                # JSONB returns a dict already in psycopg3
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    else:
        path = REPORTS / f"{report_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())


# ============== Emails ==============

def save_email(email: str, url: str, report_id: str, ip: str):
    if USE_POSTGRES:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO emails (email, url, report_id, ip) VALUES (%s, %s, %s, %s)",
                    (email, url, report_id, ip),
                )
            conn.commit()
    else:
        with EMAILS_CSV.open("a", newline="") as f:
            csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(), email, url, report_id, ip])


# ============== Rate limiting ==============

DAILY_LIMIT_DEFAULT = 5


def check_rate_limit(ip: str, daily_limit: int = DAILY_LIMIT_DEFAULT):
    today = datetime.now(timezone.utc).date()
    if USE_POSTGRES:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT day, count FROM ip_usage WHERE ip = %s", (ip,))
                row = cur.fetchone()
                count = 0
                if row:
                    day, count = row[0], row[1]
                    if day != today:
                        count = 0
                allowed = count < daily_limit
                remaining = max(0, daily_limit - count)
                return allowed, remaining
    else:
        # Filesystem fallback
        log_path = DATA / "ip_usage.json"
        log = {}
        if log_path.exists():
            try:
                log = json.loads(log_path.read_text())
            except Exception:
                log = {}
        entry = log.get(ip, {})
        if entry.get("date") != today.isoformat():
            entry = {"date": today.isoformat(), "count": 0}
        return entry["count"] < daily_limit, max(0, daily_limit - entry["count"])


def record_usage(ip: str):
    today = datetime.now(timezone.utc).date()
    if USE_POSTGRES:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ip_usage (ip, day, count) VALUES (%s, %s, 1)
                    ON CONFLICT (ip) DO UPDATE
                    SET count = CASE WHEN ip_usage.day = EXCLUDED.day THEN ip_usage.count + 1 ELSE 1 END,
                        day = EXCLUDED.day
                """, (ip, today))
            conn.commit()
    else:
        log_path = DATA / "ip_usage.json"
        log = {}
        if log_path.exists():
            try:
                log = json.loads(log_path.read_text())
            except Exception:
                log = {}
        entry = log.get(ip, {"date": today.isoformat(), "count": 0})
        if entry.get("date") != today.isoformat():
            entry = {"date": today.isoformat(), "count": 0}
        entry["count"] += 1
        log[ip] = entry
        log_path.write_text(json.dumps(log))
