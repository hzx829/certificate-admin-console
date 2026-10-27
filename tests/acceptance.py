"""Real HTTP + SQLite acceptance, independent expected outcomes, no browser mocks."""
import csv
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.db import initialize
from app.seed import generate_large

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
METRICS = {}


class Server:
    def __init__(self, database):
        self.database = database
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = open(str(database) + ".log", "ab")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port), "--no-access-log"],
            cwd=ROOT, env={**os.environ, "CERTIFICATE_DB": str(database)},
            stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.client = httpx.Client(base_url=self.url, timeout=65, trust_env=False)
        for _ in range(200):
            try:
                if self.client.get("/api/health").status_code == 200:
                    return
            except httpx.TransportError:
                pass
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        self.close()
        raise RuntimeError(Path(str(database) + ".log").read_text(errors="replace"))

    def close(self):
        self.client.close()
        if self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.process.terminate()
            self.process.wait(timeout=10)
        self.log.close()

    def get(self, path, actor="alice-east", **kwargs):
        return self.client.get(path, headers={"X-Actor-Token": actor}, **kwargs)

    def post(self, path, actor="alice-east", key=None, **kwargs):
        headers = {"X-Actor-Token": actor}
        if key is not None:
            headers["Idempotency-Key"] = key
        return self.client.post(path, headers=headers, **kwargs)


class Acceptance(unittest.TestCase):
    def setUp(self):
        temp_root = ARTIFACTS / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="acceptance-", dir=temp_root)
        self.path = Path(self.temp.name) / "test.db"
        initialize(self.path)
        self.server = Server(self.path)

    def tearDown(self):
        self.server.close()
        # Cleanup is confined to our own generated test directory.
        assert Path(self.temp.name).resolve().parent == (ARTIFACTS / "tmp").resolve()
        self.temp.cleanup()

    def rows(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(sql, params).fetchall()

    def execute(self, sql):
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript(sql)
            db.commit()

    def counts(self):
        return tuple(self.rows(f"SELECT COUNT(*) FROM {table}")[0][0] for table in ("certificates", "audits", "operations"))

    def bulk(self, key="same", course=101, actor="alice-east"):
        return self.server.post("/api/bulk-issue", actor=actor, key=key, json={"course_id": course})

    def race(self, function, count=5, hold_writer=False):
        barrier = threading.Barrier(count)
        def worker(index):
            barrier.wait(timeout=10)
            return function(index)
        lock = sqlite3.connect(self.path, isolation_level=None)
        try:
            if hold_writer:
                lock.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=count) as pool:
                futures = [pool.submit(worker, i) for i in range(count)]
                if hold_writer:
                    time.sleep(0.25)
                    lock.commit()
                return [future.result(timeout=30) for future in futures]
        finally:
            lock.close()

    def csv_rows(self, response):
        self.assertEqual(response.status_code, 200, response.text[:300])
        return list(csv.DictReader(io.StringIO(response.text, newline="")))

    def test_A1_tenant_isolation(self):
        before = self.counts()
        self.assertEqual(self.server.client.get("/api/certificates").status_code, 401)
        self.assertEqual(self.server.get("/api/certificates", actor="invalid").status_code, 401)
        for actor, other_cert, other_course, serial, own_tenant in [
            ("bob-west", 1, 101, "E-DEMO-001", 2), ("alice-east", 2, 201, "W-DEMO-001", 1)]:
            data = self.server.get("/api/certificates", actor=actor, params={"tenant_id": 3-own_tenant}).json()
            self.assertTrue(all(row["tenant_id"] == own_tenant for row in data["items"]))
            self.assertEqual(data["total"], len(data["items"]))
            self.assertEqual(self.server.get("/api/certificates", actor=actor, params={"q": serial}).json()["total"], 0)
            denied = self.server.get(f"/api/certificates/{other_cert}", actor=actor)
            absent = self.server.get("/api/certificates/999999", actor=actor)
            self.assertEqual((denied.status_code, denied.json()), (404, absent.json()))
            self.assertEqual(self.bulk("unauthorized", other_course, actor).status_code, 404)
            self.assertEqual(self.server.post(f"/api/certificates/{other_cert}/revoke", actor=actor).status_code, 404)
            self.assertEqual(self.csv_rows(self.server.get("/api/certificates/export", actor=actor, params={"q": serial})), [])
            courses = self.server.get("/api/courses", actor=actor).json()
            self.assertNotIn(other_course, [row["id"] for row in courses])
        self.assertEqual(self.counts(), before)
        self.bulk("east-alex")
        self.bulk("west-alex", 201, "bob-west")
        for actor, tenant in [("alice-east", 1), ("bob-west", 2)]:
            alex = self.server.get("/api/certificates", actor=actor, params={"q": "alex"}).json()
            self.assertEqual(alex["total"], 1)
            self.assertEqual(alex["items"][0]["tenant_id"], tenant)

    def test_A2_sequential_replay_and_restart(self):
        before = self.counts()
        first = self.bulk().json()
        self.assertEqual(first["summary"], {"issued": 2, "skipped": 2, "failed": 0})
        self.assertEqual(first, self.bulk().json())
        self.server.close()
        self.server = Server(self.path)
        self.assertEqual(first, self.bulk().json())
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(), before)), (2, 2, 1))
        self.assertEqual(self.bulk("same", 201, "bob-west").status_code, 200)

    def test_A2_concurrent_replay(self):
        before = self.counts()
        responses = self.race(lambda _: self.bulk(), hold_writer=True)
        self.assertEqual([r.status_code for r in responses], [200]*5)
        self.assertTrue(all(r.json() == responses[0].json() for r in responses))
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(), before)), (2, 2, 1))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM certificates c WHERE (SELECT COUNT(*) FROM audits a WHERE a.certificate_id=c.id AND event_type='ISSUED')!=1"), [(0,)])

    def test_A2_different_keys_same_course(self):
        before = self.counts()
        responses = self.race(lambda i: self.bulk(f"key-{i}"), hold_writer=True)
        self.assertEqual([r.status_code for r in responses], [200]*5)
        self.assertEqual(sum(r.json()["summary"]["issued"] for r in responses), 2)
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(), before)), (2, 2, 5))

    def test_A3_key_misuse(self):
        first = self.bulk().json()
        before = self.counts()
        stored = self.rows("SELECT * FROM operations")
        self.assertEqual(self.bulk(course=102).status_code, 409)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.rows("SELECT * FROM operations"), stored)
        self.assertEqual(first, self.bulk().json())
        equivalent = self.server.client.post("/api/bulk-issue", headers={"X-Actor-Token": "alice-east", "Idempotency-Key": "same", "Content-Type": "application/json"}, content=' { "course_id" : 101 } ')
        self.assertEqual(equivalent.json(), first)
        self.assertEqual(self.server.post("/api/bulk-issue", key="same", json={"course_id":101,"extra":True}).status_code, 422)
        self.assertEqual(self.server.post("/api/bulk-issue", json={"course_id":101}).status_code, 422)

    def test_A3_concurrent_key_misuse(self):
        responses = self.race(lambda i: self.bulk("collision", 101+i), count=2, hold_writer=True)
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        winner = next(r.json() for r in responses if r.status_code == 200)
        other = 102 if winner["course_id"] == 101 else 101
        self.assertEqual(self.rows("SELECT COUNT(*) FROM certificates WHERE course_id=?", (other,)), [(3 if other == 102 else 1,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM operations"), [(1,)])

    def test_A4_outcomes_and_single_learner_rollback(self):
        self.execute("""CREATE TRIGGER reject_morgan BEFORE INSERT ON audits
        WHEN NEW.event_type='ISSUED' AND (SELECT learner_id FROM certificates WHERE id=NEW.certificate_id)=1004
        BEGIN SELECT RAISE(ABORT,'injected audit failure'); END;""")
        before = self.counts()
        first = self.bulk().json()
        self.assertEqual([(r["learner_id"],r["outcome"],r.get("reason")) for r in first["outcomes"]],
                         [(1001,"issued",None),(1002,"skipped","not_completed"),(1003,"skipped","already_certified"),(1004,"failed","issuance_failed")])
        self.assertEqual(first["summary"], {"issued":1,"skipped":2,"failed":1})
        self.assertEqual(self.rows("SELECT COUNT(*) FROM certificates WHERE learner_id=1004"), [(0,)])
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(), before)), (1,1,1))
        self.execute("DROP TRIGGER reject_morgan;")
        self.assertEqual(self.bulk().json(), first)
        self.assertEqual(self.bulk("retry-failed").json()["summary"], {"issued":1,"skipped":3,"failed":0})

    def test_A4_whole_operation_rollback(self):
        self.execute("""CREATE TRIGGER reject_result BEFORE UPDATE OF result_json ON operations
        BEGIN SELECT RAISE(ABORT,'injected final result failure'); END;""")
        before = self.counts()
        self.assertEqual(self.bulk().status_code, 503)
        self.assertEqual(self.counts(), before)
        self.execute("DROP TRIGGER reject_result;")
        self.assertEqual(self.bulk().json()["summary"]["issued"], 2)

    def test_A5_dates_sorting_and_query_parity(self):
        self.assertEqual(self.server.get("/api/certificates/1").json()["issued_local"], "2026-01-11 00:30")
        self.assertEqual(self.server.get("/api/certificates/2", actor="bob-west").json()["issued_local"], "2026-01-10 21:30")
        self.assertEqual(self.server.get("/api/certificates/3").json()["issued_local"], "2026-07-10 23:30")
        for direction, expected in [("asc", [4,1,5,3]), ("desc", [3,1,5,4])]:
            items = []
            for page in (1,2):
                items += self.server.get("/api/certificates", params={"sort":"issue_date","direction":direction,"page":page,"page_size":2}).json()["items"]
            self.assertEqual([r["id"] for r in items], expected)
            rows = self.csv_rows(self.server.get("/api/certificates/export", params={"sort":"issue_date","direction":direction,"page_size":1}))
            self.assertEqual([r["serial_number"] for r in rows], [r["serial_number"] for r in items])
            self.assertEqual([r["issue_date"] for r in rows], [r["issue_date"] for r in items])
        west = self.csv_rows(self.server.get("/api/certificates/export", actor="bob-west"))
        self.assertEqual(west[0]["issue_date"], "2026-01-10")
        for search in ("%", "_", "\\"):
            self.assertEqual(self.server.get("/api/certificates", params={"q": search}).json()["total"], 0)
        self.assertEqual(self.server.get("/api/certificates", params={"sort":"invalid"}).status_code, 422)

    def test_A6_large_export(self):
        original_counts = self.counts()
        large = Path(self.temp.name) / "large.db"
        generated_at = time.perf_counter()
        generate_large(large)
        generation_seconds = time.perf_counter() - generated_at
        self.assertEqual(self.counts(), original_counts)
        with self.assertRaises(ValueError):
            generate_large(self.path)
        self.server.close()
        self.path = large
        self.server = Server(self.path)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM certificates WHERE tenant_id=1"), [(100000,)])
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            raw = [dict(r) for r in db.execute("SELECT x.id,l.name AS learner_name,c.title AS course_title,x.serial_number,x.issued_local_date AS issue_date FROM certificates x JOIN learners l ON l.id=x.learner_id JOIN courses c ON c.id=x.course_id WHERE x.tenant_id=1")]
        fields = ["learner_name", "course_title", "serial_number", "issue_date"]
        expected_alex = sorted([r for r in raw if "alex" in r["learner_name"].lower()], key=lambda r:(r["learner_name"].lower(), r["id"]))
        expected_all = sorted(raw, key=lambda r:(r["issue_date"], r["id"]))
        params = {"q":"Alex", "sort":"learner_name", "direction":"asc"}
        received = threading.Event()
        timing = {}
        def download():
            started = time.perf_counter()
            timing["export_start"] = started
            data = bytearray()
            with httpx.Client(timeout=60, trust_env=False) as client:
                with client.stream("GET", self.server.url + "/api/certificates/export", params=params, headers={"X-Actor-Token":"alice-east"}) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        received.set()
            timing["export_end"] = time.perf_counter()
            return bytes(data), timing["export_end"]-started
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(download)
            self.assertTrue(received.wait(10))
            timing["list_start"] = time.perf_counter()
            probe = self.server.get("/api/certificates", params={"q":"Alex"})
            timing["list_end"] = time.perf_counter()
            first, first_seconds = future.result(timeout=60)
        self.assertEqual(probe.status_code, 200)
        self.assertLess(timing["list_end"], timing["export_end"], "List must finish while export is still downloading")
        started = time.perf_counter()
        second_response = self.server.get("/api/certificates/export", params=params)
        second_seconds = time.perf_counter()-started
        second = second_response.content
        first_rows = list(csv.DictReader(io.StringIO(first.decode("utf-8"), newline="")))
        self.assertEqual(list(first_rows[0]), fields)
        self.assertEqual(first_rows, [{key:r[key] for key in fields} for r in expected_alex])
        self.assertEqual(first, second)
        self.assertEqual(probe.json()["total"], len(expected_alex))
        started = time.perf_counter()
        complete = self.csv_rows(self.server.get("/api/certificates/export", params={"sort":"issue_date","direction":"asc"}))
        full_seconds = time.perf_counter()-started
        self.assertEqual(complete, [{key:r[key] for key in fields} for r in expected_all])
        self.assertEqual(len({r["serial_number"] for r in complete}), 100000)
        # Independent stable sort: ID ascending first, then the requested descending key.
        expected_desc = sorted(sorted(expected_alex,key=lambda r:r["id"]),key=lambda r:r["course_title"].lower(),reverse=True)
        alternate = self.csv_rows(self.server.get("/api/certificates/export", params={"q":"Alex","sort":"course_title","direction":"desc"}))
        self.assertEqual(alternate, [{key:r[key] for key in fields} for r in expected_desc])
        west = self.csv_rows(self.server.get("/api/certificates/export", actor="bob-west"))
        self.assertEqual([r["serial_number"] for r in west], ["W-DEMO-001"])
        for seconds in (first_seconds,second_seconds,full_seconds):
            self.assertLessEqual(seconds, 60)
        METRICS["A6"] = {"east_rows":100000,"matching_rows":len(expected_alex),"generation_seconds":generation_seconds,
                         "first_export_seconds":first_seconds,"second_export_seconds":second_seconds,"full_export_seconds":full_seconds,
                         "concurrent_list_seconds":timing["list_end"]-timing["list_start"],
                         "overlap_seconds":timing["export_end"]-timing["list_end"]}

    def test_A7_revoke_retry_and_concurrency(self):
        before = self.counts()
        responses = self.race(lambda _:self.server.post("/api/certificates/1/revoke"), hold_writer=True)
        self.assertEqual([r.status_code for r in responses], [200]*5)
        first = responses[0].json()
        self.assertEqual(first["status"], "REVOKED")
        self.assertTrue(all(r.json() == first for r in responses))
        self.assertEqual(self.server.post("/api/certificates/1/revoke").json(), first)
        self.assertEqual([r["event_type"] for r in first["audits"]], ["ISSUED", "REVOKED"])
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(), before)), (0,1,0))

    def test_A7_audit_failure_rolls_back_status(self):
        self.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON audits WHEN NEW.event_type='REVOKED'
        BEGIN SELECT RAISE(ABORT,'injected revocation audit failure'); END;""")
        before = self.counts()
        self.assertEqual(self.server.post("/api/certificates/1/revoke").status_code, 503)
        self.assertEqual(self.server.get("/api/certificates/1").json()["status"], "ACTIVE")
        self.assertEqual(self.counts(), before)


class RecordedResult(unittest.TextTestResult):
    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        failures = {str(t):text for t,text in self.failures+self.errors}
        REPORT.append({"case":str(test),"passed":str(test) not in failures,"seconds":time.perf_counter()-self.started,
                       **({"failure":failures[str(test)]} if str(test) in failures else {})})
        super().stopTest(test)


REPORT = []
if __name__ == "__main__":
    ARTIFACTS.mkdir(exist_ok=True)
    started_at = datetime.now(UTC).isoformat()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    report = {"started_at":started_at,"finished_at":datetime.now(UTC).isoformat(),"passed":result.wasSuccessful(),
              "cases":REPORT,"metrics":METRICS}
    (ARTIFACTS / "acceptance-results.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    sys.exit(0 if result.wasSuccessful() else 1)
