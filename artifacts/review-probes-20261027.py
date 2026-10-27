"""Post-deadline review probes; not part of the original assessment implementation."""
import csv
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import initialize
from tests.acceptance import Server


def counts(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("certificates", "audits", "operations"))


@contextmanager
def fixture(processes=1):
    parent = ROOT / "artifacts" / "tmp"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="post-deadline-review-", dir=parent) as folder:
        path = Path(folder) / "review.db"
        initialize(path)
        servers = []
        try:
            for _ in range(processes):
                servers.append(Server(path))
            yield path, servers
        finally:
            for server in reversed(servers):
                server.close()


def bulk(server, key, course=101, actor="alice-east"):
    return server.post("/api/bulk-issue", actor=actor, key=key, json={"course_id": course})


def multi_process():
    with fixture(2) as (path, servers):
        before = counts(path)
        barrier = threading.Barrier(6)
        def call(index):
            barrier.wait(timeout=10)
            return bulk(servers[index % 2], "multi-process")
        with closing(sqlite3.connect(path, isolation_level=None)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(call, i) for i in range(6)]
                time.sleep(0.3)
                lock.commit()
                responses = [future.result(timeout=30) for future in futures]
        assert all(r.status_code == 200 for r in responses)
        assert all(r.json() == responses[0].json() for r in responses)
        delta = tuple(a-b for a,b in zip(counts(path), before))
        assert delta == (2, 2, 1)
        return {"processes": 2, "concurrent_requests": 6, "delta_cert_audit_operation": delta,
                "identical_results": True, "classification": "covered"}


def long_writer_wait():
    with fixture() as (path, servers):
        before = counts(path)
        with closing(sqlite3.connect(path, isolation_level=None)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            started = time.perf_counter()
            response = bulk(servers[0], "wait-longer-than-timeout")
            seconds = time.perf_counter() - started
            assert response.status_code == 503
            assert counts(path) == before
            lock.rollback()
        retry = bulk(servers[0], "wait-longer-than-timeout")
        assert retry.status_code == 200
        assert retry.json()["summary"] == {"issued": 2, "skipped": 2, "failed": 0}
        assert tuple(a-b for a,b in zip(counts(path), before)) == (2, 2, 1)
        return {"first_status": response.status_code, "wait_seconds": seconds,
                "retry_status": retry.status_code, "no_side_effect_before_retry": True,
                "classification": "confirmed_limitation",
                "meaning": "Safe to retry, but not every original call returns the logical operation result under prolonged writer contention."}


def scope_and_revoke_replay():
    with fixture() as (path, servers):
        server = servers[0]
        first = bulk(server, "used-key").json()
        before = counts(path)
        denied = bulk(server, "used-key", 201)
        assert denied.status_code == 404
        assert counts(path) == before
        assert bulk(server, "used-key").json() == first
        cert = next(r["certificate_id"] for r in first["outcomes"] if r["learner_id"] == 1001)
        revoked = server.post(f"/api/certificates/{cert}/revoke").json()
        assert revoked["status"] == "REVOKED"
        assert bulk(server, "used-key").json() == first
        next_operation = bulk(server, "new-after-revoke").json()
        assert next_operation["summary"] == {"issued": 0, "skipped": 4, "failed": 0}
        assert next(r for r in next_operation["outcomes"] if r["learner_id"] == 1001)["reason"] == "already_certified"
        server.close()
        servers[0] = Server(path)
        assert servers[0].post(f"/api/certificates/{cert}/revoke").json() == revoked
        return {"unauthorized_course_with_existing_key": 404, "historical_operation_result_preserved": True,
                "revoked_certificate_not_reissued": True, "revoke_replay_after_restart_identical": True,
                "classification": "covered"}


def empty_and_query_matrix():
    with fixture() as (path, servers):
        server = servers[0]
        with closing(sqlite3.connect(path)) as db:
            db.execute("INSERT INTO courses VALUES(103,1,'Empty course')")
            db.commit()
        before = counts(path)
        empty = bulk(server, "empty", 103).json()
        assert empty["summary"] == {"issued": 0, "skipped": 0, "failed": 0}
        assert empty["outcomes"] == []
        assert tuple(a-b for a,b in zip(counts(path), before)) == (0, 0, 1)
        bulk(server, "all-learners")
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            raw = [dict(r) for r in db.execute("SELECT x.id,l.name AS learner_name,c.title AS course_title,x.serial_number,x.issued_local_date AS issue_date FROM certificates x JOIN learners l ON l.id=x.learner_id JOIN courses c ON c.id=x.course_id WHERE x.tenant_id=1")]
        cases = 0
        for q in ("", "aLeX", "e-demo", "%"):
            selected = [r for r in raw if q.lower() in r["learner_name"].lower() or q.lower() in r["serial_number"].lower()]
            for field in ("learner_name", "course_title", "serial_number", "issue_date"):
                for direction in ("asc", "desc"):
                    expected = sorted(sorted(selected, key=lambda r:r["id"]),
                                      key=lambda r:r[field].lower() if field in ("learner_name", "course_title") else r[field],
                                      reverse=direction == "desc")
                    params = {"q": q, "sort": field, "direction": direction}
                    response = server.get("/api/certificates/export", params=params)
                    assert response.status_code == 200
                    actual = list(csv.DictReader(io.StringIO(response.text, newline="")))
                    assert actual == [{k:r[k] for k in ("learner_name", "course_title", "serial_number", "issue_date")} for r in expected]
                    paginated = []
                    for page in range(1, max(1, len(expected))+1):
                        response = server.get("/api/certificates", params={**params, "page": page, "page_size": 1})
                        assert response.status_code == 200
                        data = response.json()
                        assert data["total"] == len(expected)
                        paginated += data["items"]
                    assert [r["id"] for r in paginated] == [r["id"] for r in expected]
                    cases += 1
        return {"empty_course": "zero outcomes, zero certificates/audits, one operation",
                "search_sort_direction_combinations": cases, "classification": "covered"}


if __name__ == "__main__":
    report = {"phase": "post-deadline review only", "started_at": datetime.now(UTC).isoformat(),
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "probes": []}
    for probe in (multi_process, long_writer_wait, scope_and_revoke_replay, empty_and_query_matrix):
        started = time.perf_counter()
        try:
            result = {"name": probe.__name__, "observed_as_expected": True, **probe()}
        except Exception as error:
            result = {"name": probe.__name__, "observed_as_expected": False, "error": repr(error)}
        result["seconds"] = time.perf_counter()-started
        report["probes"].append(result)
        print(json.dumps(result), flush=True)
    report["finished_at"] = datetime.now(UTC).isoformat()
    (ROOT / "artifacts" / "review-probes-20261027.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.exit(0 if all(p["observed_as_expected"] for p in report["probes"]) else 1)
