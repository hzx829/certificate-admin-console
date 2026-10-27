"""Test-only server: pause the first bulk transaction immediately before commit."""
import inspect
import os
import time
from contextlib import contextmanager
from pathlib import Path

from app import main

original_connection = main.connection
gate = os.environ.get("TEST_COMMIT_GATE")


class PausedConnection:
    def __init__(self, db):
        self.db = db
        self.bulk_result_written = False

    def __getattr__(self, name):
        return getattr(self.db, name)

    def execute(self, sql, *args):
        result = self.db.execute(sql, *args)
        if sql.startswith("UPDATE operations SET result_json="):
            self.bulk_result_written = True
        return result

    def commit(self):
        ready, release = Path(gate + ".ready"), Path(gate + ".release")
        if self.bulk_result_written and not ready.exists():
            ready.write_text("uncommitted transaction paused", encoding="utf-8")
            deadline = time.monotonic() + 90
            while not release.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Test commit gate timed out")
                time.sleep(0.02)
        return self.db.commit()


@contextmanager
def test_connection(path, **kwargs):
    with original_connection(path, **kwargs) as db:
        yield PausedConnection(db) if gate else db


main.connection = test_connection
options = {}
if "bulk_wait_seconds" in inspect.signature(main.create_app).parameters:
    options["bulk_wait_seconds"] = float(os.environ.get("TEST_BULK_WAIT_SECONDS", "60"))
app = main.create_app(**options)
