import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, timezone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
 id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
 email TEXT NOT NULL UNIQUE, token TEXT NOT NULL UNIQUE, UNIQUE(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS courses (
 id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
 title TEXT NOT NULL, UNIQUE(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS learners (
 id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL REFERENCES tenants(id),
 name TEXT NOT NULL, UNIQUE(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS enrollments (
 tenant_id INTEGER NOT NULL, course_id INTEGER NOT NULL, learner_id INTEGER NOT NULL,
 completed INTEGER NOT NULL CHECK(completed IN (0,1)),
 PRIMARY KEY(tenant_id,course_id,learner_id),
 FOREIGN KEY(tenant_id,course_id) REFERENCES courses(tenant_id,id),
 FOREIGN KEY(tenant_id,learner_id) REFERENCES learners(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS certificates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER NOT NULL,
 course_id INTEGER NOT NULL, learner_id INTEGER NOT NULL,
 serial_number TEXT NOT NULL UNIQUE, issued_at TEXT NOT NULL,
 issued_local_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE'
 CHECK(status IN ('ACTIVE','REVOKED')), revoked_at TEXT,
 UNIQUE(tenant_id,course_id,learner_id), UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,course_id,learner_id)
 REFERENCES enrollments(tenant_id,course_id,learner_id),
 CHECK((status='ACTIVE' AND revoked_at IS NULL) OR
       (status='REVOKED' AND revoked_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS audits (
 id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id INTEGER NOT NULL,
 actor_id INTEGER NOT NULL, certificate_id INTEGER NOT NULL,
 event_type TEXT NOT NULL CHECK(event_type IN ('ISSUED','REVOKED')),
 occurred_at TEXT NOT NULL, UNIQUE(certificate_id,event_type),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES admins(tenant_id,id),
 FOREIGN KEY(tenant_id,certificate_id) REFERENCES certificates(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL, actor_id INTEGER NOT NULL,
 kind TEXT NOT NULL DEFAULT 'bulk_issue', idempotency_key TEXT NOT NULL,
 request_json TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL,
 UNIQUE(tenant_id,actor_id,kind,idempotency_key),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES admins(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS certificate_date ON certificates(tenant_id,issued_local_date,id);
CREATE INDEX IF NOT EXISTS certificate_tenant ON certificates(tenant_id,id);
"""


def utc_now():
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def local_datetime(timestamp, timezone):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone))


@contextmanager
def connection(path, *, timeout=15):
    db = sqlite3.connect(str(path), timeout=timeout, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        if db.in_transaction:
            db.rollback()
        db.close()


def insert_certificate(db, tenant_id, course_id, learner_id, serial, issued_at, timezone, actor_id, certificate_id=None):
    cursor = db.execute(
        "INSERT INTO certificates(id,tenant_id,course_id,learner_id,serial_number,issued_at,issued_local_date) "
        "VALUES(?,?,?,?,?,?,?)",
        (certificate_id, tenant_id, course_id, learner_id, serial, issued_at,
         local_datetime(issued_at, timezone).date().isoformat()),
    )
    certificate_id = cursor.lastrowid
    db.execute("INSERT INTO audits(tenant_id,actor_id,certificate_id,event_type,occurred_at) VALUES(?,?,?,'ISSUED',?)",
               (tenant_id, actor_id, certificate_id, issued_at))
    return certificate_id


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]:
            db.commit()
            return
        db.executemany("INSERT INTO tenants VALUES(?,?,?)", [
            (1, "East", "Australia/Sydney"), (2, "West", "Australia/Perth")])
        db.executemany("INSERT INTO admins VALUES(?,?,?,?)", [
            (1, 1, "alice@east.test", "alice-east"), (2, 2, "bob@west.test", "bob-west")])
        db.executemany("INSERT INTO courses VALUES(?,?,?)", [
            (101, 1, "Safety 101"), (102, 1, "First Aid"), (201, 2, "Safety 101")])
        learners = []
        enrollments = []
        for tenant, base, course in [(1, 1000, 101), (2, 2000, 201)]:
            for offset, name, completed in [(1, "Alex Lee", 1), (2, "Jamie Chen", 0),
                                             (3, "Casey Wong", 1), (4, "Morgan Li", 1)]:
                learners.append((base + offset, tenant, name))
                enrollments.append((tenant, course, base + offset, completed))
        for learner_id, name in [(1101, "Taylor Park"), (1103, "Winter Example"),
                                 (1104, "Before Midnight"), (1105, "Same Date")]:
            learners.append((learner_id, 1, name))
            enrollments.append((1, 102, learner_id, 1))
        db.executemany("INSERT INTO learners VALUES(?,?,?)", learners)
        db.executemany("INSERT INTO enrollments VALUES(?,?,?,?)", enrollments)
        fixtures = [
            (1, 1, 101, 1003, "E-DEMO-001", "2026-01-10T13:30:00Z", "Australia/Sydney", 1),
            (2, 2, 201, 2003, "W-DEMO-001", "2026-01-10T13:30:00Z", "Australia/Perth", 2),
            (3, 1, 102, 1103, "E-WINTER-001", "2026-07-10T13:30:00Z", "Australia/Sydney", 1),
            (4, 1, 102, 1104, "E-BOUNDARY-001", "2026-01-10T12:30:00Z", "Australia/Sydney", 1),
            (5, 1, 102, 1105, "E-SAME-DATE-001", "2026-01-10T13:05:00Z", "Australia/Sydney", 1),
        ]
        for cid, tenant, course, learner, serial, issued, timezone, actor in fixtures:
            insert_certificate(db, tenant, course, learner, serial, issued, timezone, actor, cid)
        db.commit()
