import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .db import connection, initialize, local_datetime


def generate_large(path, count=100000):
    path = Path(path).resolve()
    default = Path(__file__).resolve().parent.parent / "data" / "demo.db"
    if path == default.resolve() or path.exists():
        raise ValueError("Large-data generation requires a new database path, separate from data/demo.db")
    if count < 4:
        raise ValueError("East count must be at least 4")
    initialize(path)
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        initial = db.execute("SELECT COUNT(*) FROM certificates WHERE tenant_id=1").fetchone()[0]
        next_id = db.execute("SELECT MAX(id)+1 FROM certificates").fetchone()[0]
        for start in range(0, count - initial, 5000):
            learners, enrollments, certs, audits = [], [], [], []
            for i in range(start, min(start+5000, count-initial)):
                learner, cid, course = 1000000+i, next_id+i, 101+(i % 2)
                name = "Alex Lee" if i % 3 == 0 else f"Learner {i % 32:02d}"
                if i % 1000 == 999:
                    name = 'CSV, "quoted"\nlearner'
                issued = (datetime(2026, 1, 1, 13, 30, tzinfo=UTC) + timedelta(days=i % 30)).isoformat().replace("+00:00", "Z")
                learners.append((learner, 1, name))
                enrollments.append((1, course, learner, 1))
                certs.append((cid, 1, course, learner, f"E-LARGE-{i:07d}", issued,
                              local_datetime(issued, "Australia/Sydney").date().isoformat()))
                audits.append((1, 1, cid, "ISSUED", issued))
            db.executemany("INSERT INTO learners VALUES(?,?,?)", learners)
            db.executemany("INSERT INTO enrollments VALUES(?,?,?,?)", enrollments)
            db.executemany("INSERT INTO certificates(id,tenant_id,course_id,learner_id,serial_number,issued_at,issued_local_date) VALUES(?,?,?,?,?,?,?)", certs)
            db.executemany("INSERT INTO audits(tenant_id,actor_id,certificate_id,event_type,occurred_at) VALUES(?,?,?,?,?)", audits)
        db.commit()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--large", action="store_true")
    args = parser.parse_args()
    if args.large:
        print(f"Created {generate_large(args.database):,} East certificates in {args.database}")
    else:
        initialize(args.database)
        print(f"Initialized demo data in {args.database}")
