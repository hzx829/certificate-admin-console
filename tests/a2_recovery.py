"""A2 extension plus all original A1-A7 tests; real processes, HTTP and database."""
import argparse
import json
import sqlite3
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from tests import acceptance as base


class Recovery(base.Acceptance):
    def test_A2_completed_replay_without_writer_lock(self):
        first = self.bulk("finished").json()
        before = self.counts()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            started = time.perf_counter()
            response = self.server.post("/api/bulk-issue", key="finished", json={"course_id":101}, timeout=1)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), first)
            self.assertLess(time.perf_counter()-started, 1)
            self.assertEqual(self.server.post("/api/bulk-issue", key="finished", json={"course_id":102}, timeout=1).status_code, 409)
            self.assertEqual(self.server.post("/api/bulk-issue", key="finished", json={"course_id":201}, timeout=1).status_code, 404)
            lock.rollback()
        self.assertEqual(self.counts(), before)

    def test_A2_uncommitted_twenty_seconds_two_processes(self):
        before = self.counts()
        gate = Path(self.temp.name) / "commit-gate"
        self.server.close()
        self.server = base.Server(self.path, app="tests.a2_server:app", env={"TEST_COMMIT_GATE":str(gate)})
        other = base.Server(self.path)
        release = Path(str(gate)+".release")
        try:
            with ThreadPoolExecutor(max_workers=7) as pool:
                first = pool.submit(self.bulk, "slow")
                deadline = time.monotonic()+10
                while not Path(str(gate)+".ready").exists():
                    self.assertLess(time.monotonic(), deadline, "First transaction did not reach commit gate")
                    time.sleep(0.02)
                timer = threading.Timer(20, lambda:release.write_text("release", encoding="utf-8"))
                timer.start()
                try:
                    started = time.perf_counter()
                    futures = [pool.submit(server.post, "/api/bulk-issue", key="slow", json={"course_id":101})
                               for server in (other,self.server,other,self.server,other)]
                    misuse = pool.submit(other.post, "/api/bulk-issue", key="slow", json={"course_id":102})
                    time.sleep(0.4)
                    self.assertEqual(self.counts(), before, "Partial results must remain invisible")
                    probe = time.perf_counter()
                    self.assertEqual(other.get("/api/certificates", timeout=2).status_code, 200)
                    self.assertLess(time.perf_counter()-probe, 2)
                    responses = [first.result(timeout=35)] + [f.result(timeout=35) for f in futures]
                    self.assertEqual([r.status_code for r in responses], [200]*6)
                    self.assertTrue(all(r.json() == responses[0].json() for r in responses))
                    self.assertEqual(misuse.result(timeout=10).status_code, 409)
                    self.assertGreaterEqual(time.perf_counter()-started, 19)
                    self.assertEqual(tuple(a-b for a,b in zip(self.counts(),before)), (2,2,1))
                finally:
                    release.write_text("release", encoding="utf-8")
                    timer.cancel()
                    timer.join()
        finally:
            release.write_text("release", encoding="utf-8")
            other.close()

    def test_A2_wait_budget_then_same_key_retry(self):
        self.server.close()
        self.server = base.Server(self.path, app="tests.a2_server:app", env={"TEST_BULK_WAIT_SECONDS":"1"})
        before = self.counts()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            started = time.perf_counter()
            response = self.bulk("budget")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json().get("code"), "OPERATION_BUSY")
            self.assertEqual(response.headers.get("Retry-After"), "1")
            self.assertLess(time.perf_counter()-started, 3)
            self.assertEqual(self.counts(), before)
            lock.rollback()
        first = self.bulk("budget")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.bulk("budget").json(), first.json())
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(),before)), (2,2,1))

    def test_A2_waiters_release_request_workers(self):
        before = self.counts()
        with closing(sqlite3.connect(self.path, isolation_level=None)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            with ThreadPoolExecutor(max_workers=48) as pool:
                futures = [pool.submit(self.bulk, "crowd") for _ in range(48)]
                try:
                    time.sleep(1)
                    started = time.perf_counter()
                    self.assertEqual(self.server.get("/api/certificates", timeout=2).status_code, 200)
                    self.assertLess(time.perf_counter()-started, 2)
                finally:
                    lock.rollback()
                responses = [f.result(timeout=15) for f in futures]
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertTrue(all(r.json() == responses[0].json() for r in responses))
        self.assertEqual(tuple(a-b for a,b in zip(self.counts(),before)), (2,2,1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="a2-regression-results.json")
    parser.add_argument("--new-only", action="store_true")
    args = parser.parse_args()
    suite = (unittest.TestSuite(Recovery(name) for name in Recovery.__dict__ if name.startswith("test_"))
             if args.new_only else unittest.defaultTestLoader.loadTestsFromTestCase(Recovery))
    started = datetime.now(UTC).isoformat()
    result = unittest.TextTestRunner(verbosity=2, resultclass=base.RecordedResult).run(suite)
    report = {"phase":"post-delivery A2 improvement", "started_at":started,
              "finished_at":datetime.now(UTC).isoformat(), "passed":result.wasSuccessful(),
              "cases":base.REPORT, "metrics":base.METRICS}
    (base.ARTIFACTS / Path(args.report).name).write_text(json.dumps(report,indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
