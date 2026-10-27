import asyncio
import csv
import io
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .db import connection, initialize, insert_certificate, local_datetime, utc_now

ROOT = Path(__file__).resolve().parent.parent
SORT_FIELDS = {"learner_name": "l.name COLLATE NOCASE", "course_title": "c.title COLLATE NOCASE",
               "serial_number": "x.serial_number", "issue_date": "x.issued_local_date"}
SELECT = """SELECT x.*,l.name AS learner_name,c.title AS course_title,t.name AS tenant_name,t.timezone
FROM certificates x JOIN learners l ON l.id=x.learner_id AND l.tenant_id=x.tenant_id
JOIN courses c ON c.id=x.course_id AND c.tenant_id=x.tenant_id
JOIN tenants t ON t.id=x.tenant_id"""


class BulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: int = Field(gt=0, strict=True)


def query_spec(tenant_id, q, sort, direction):
    where = " WHERE x.tenant_id=?"
    params = [tenant_id]
    if q:
        literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where += " AND (l.name LIKE ? ESCAPE '\\' OR x.serial_number LIKE ? ESCAPE '\\')"
        params.extend([f"%{literal}%", f"%{literal}%"])
    order = f" ORDER BY {SORT_FIELDS[sort]} {direction.upper()},x.id ASC"
    return where, order, params


def certificate_json(row):
    result = dict(row)
    result["issue_date"] = result.pop("issued_local_date")
    result["issued_local"] = local_datetime(row["issued_at"], row["timezone"]).strftime("%Y-%m-%d %H:%M")
    return result


def detail(db, tenant_id, certificate_id):
    row = db.execute(SELECT + " WHERE x.tenant_id=? AND x.id=?", (tenant_id, certificate_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Certificate not found")
    result = certificate_json(row)
    result["audits"] = [dict(event) for event in db.execute(
        "SELECT a.event_type,a.occurred_at,u.email AS actor FROM audits a "
        "JOIN admins u ON u.tenant_id=a.tenant_id AND u.id=a.actor_id "
        "WHERE a.tenant_id=? AND a.certificate_id=? ORDER BY a.id", (tenant_id, certificate_id))]
    return result


def create_app(database=None, *, bulk_wait_seconds=60):
    database = Path(database or os.environ.get("CERTIFICATE_DB", ROOT / "data" / "demo.db"))

    @asynccontextmanager
    async def lifespan(app):
        initialize(database)
        yield

    app = FastAPI(title="Certificate Admin Console", lifespan=lifespan)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        logging.getLogger("certificate").error("Database request failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=503, content={"detail": "Database operation failed. Retry with the same operation key."})

    def actor(x_actor_token: Annotated[str | None, Header()] = None):
        with connection(database) as db:
            row = db.execute("SELECT a.*,t.name AS tenant_name,t.timezone FROM admins a "
                             "JOIN tenants t ON t.id=a.tenant_id WHERE a.token=?", (x_actor_token,)).fetchone()
        if row is None:
            raise HTTPException(401, "Choose a valid demo actor")
        return dict(row)

    Actor = Annotated[dict, Depends(actor)]

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/actors")
    def actors():
        with connection(database) as db:
            return [dict(row) for row in db.execute(
                "SELECT a.email,a.token,t.name AS tenant,t.timezone FROM admins a JOIN tenants t ON t.id=a.tenant_id ORDER BY a.id")]

    @app.get("/api/courses")
    def courses(current: Actor):
        with connection(database) as db:
            return [dict(row) for row in db.execute(
                "SELECT c.id,c.title,COUNT(e.learner_id) AS enrolled,COALESCE(SUM(e.completed),0) AS completed "
                "FROM courses c LEFT JOIN enrollments e ON e.tenant_id=c.tenant_id AND e.course_id=c.id "
                "WHERE c.tenant_id=? GROUP BY c.id ORDER BY c.id", (current["tenant_id"],))]

    @app.get("/api/certificates")
    def certificates(current: Actor, q: str = Query("", max_length=120),
                     sort: Literal["learner_name", "course_title", "serial_number", "issue_date"] = "issue_date",
                     direction: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1),
                     page_size: int = Query(20, ge=1, le=100)):
        where, order, params = query_spec(current["tenant_id"], q.strip(), sort, direction)
        with connection(database) as db:
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*) FROM (" + SELECT + where + ")", params).fetchone()[0]
            rows = db.execute(SELECT + where + order + " LIMIT ? OFFSET ?", params + [page_size, (page-1)*page_size]).fetchall()
            return {"items": [certificate_json(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    @app.get("/api/certificates/export")
    def export(current: Actor, q: str = Query("", max_length=120),
               sort: Literal["learner_name", "course_title", "serial_number", "issue_date"] = "issue_date",
               direction: Literal["asc", "desc"] = "desc"):
        where, order, params = query_spec(current["tenant_id"], q.strip(), sort, direction)

        def chunks():
            with connection(database) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                cursor = db.execute(SELECT + where + order, params)
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer, lineterminator="\r\n")
                writer.writerow(["learner_name", "course_title", "serial_number", "issue_date"])
                yield buffer.getvalue().encode("utf-8")
                while rows := cursor.fetchmany(1000):
                    buffer.seek(0)
                    buffer.truncate(0)
                    writer.writerows((r["learner_name"], r["course_title"], r["serial_number"], r["issued_local_date"]) for r in rows)
                    yield buffer.getvalue().encode("utf-8")

        return StreamingResponse(chunks(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": 'attachment; filename="certificates.csv"', "Cache-Control": "no-store"})

    @app.get("/api/certificates/{certificate_id}")
    def certificate(certificate_id: int, current: Actor):
        with connection(database) as db:
            return detail(db, current["tenant_id"], certificate_id)

    def replay(db, current, idempotency_key, request_json):
        old = db.execute("SELECT request_json,result_json FROM operations WHERE tenant_id=? AND actor_id=? "
                         "AND kind='bulk_issue' AND idempotency_key=?",
                         (current["tenant_id"], current["id"], idempotency_key)).fetchone()
        if old:
            if old["request_json"] != request_json:
                raise HTTPException(409, "Idempotency key is already used for a different request")
            return json.loads(old["result_json"])
        return None

    def bulk_attempt(body, current, idempotency_key, request_json):
        tenant = current["tenant_id"]
        with connection(database, timeout=0) as db:
            try:
                if db.execute("SELECT 1 FROM courses WHERE tenant_id=? AND id=?", (tenant, body.course_id)).fetchone() is None:
                    raise HTTPException(404, "Course not found")
                result = replay(db, current, idempotency_key, request_json)
                if result is not None:
                    return result
                db.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                # WAL can briefly report BUSY on reads too. Retry only before writes.
                if getattr(exc, "sqlite_errorcode", 0) & 0xFF == sqlite3.SQLITE_BUSY:
                    return None
                raise
            # Another process may have committed since the optimistic read.
            result = replay(db, current, idempotency_key, request_json)
            if result is not None:
                db.commit()
                return result
            operation_id, issued_at = uuid4().hex, utc_now()
            db.execute("INSERT INTO operations(id,tenant_id,actor_id,idempotency_key,request_json,created_at) VALUES(?,?,?,?,?,?)",
                       (operation_id, tenant, current["id"], idempotency_key, request_json, issued_at))
            enrolled = db.execute("SELECT e.learner_id,e.completed,l.name FROM enrollments e "
                                  "JOIN learners l ON l.tenant_id=e.tenant_id AND l.id=e.learner_id "
                                  "WHERE e.tenant_id=? AND e.course_id=? ORDER BY e.learner_id", (tenant, body.course_id)).fetchall()
            outcomes = []
            for learner in enrolled:
                result = {"learner_id": learner["learner_id"], "learner_name": learner["name"]}
                existing = db.execute("SELECT id,serial_number,status FROM certificates WHERE tenant_id=? AND course_id=? AND learner_id=?",
                                      (tenant, body.course_id, learner["learner_id"])).fetchone()
                if existing:
                    result.update(outcome="skipped", reason="already_certified", certificate_id=existing["id"], serial_number=existing["serial_number"])
                elif not learner["completed"]:
                    result.update(outcome="skipped", reason="not_completed")
                else:
                    db.execute("SAVEPOINT learner_issue")
                    try:
                        serial = f"CERT-{uuid4().hex.upper()}"
                        certificate_id = insert_certificate(db, tenant, body.course_id, learner["learner_id"], serial,
                                                            issued_at, current["timezone"], current["id"])
                    except sqlite3.IntegrityError:
                        db.execute("ROLLBACK TO learner_issue")
                        result.update(outcome="failed", reason="issuance_failed")
                    else:
                        result.update(outcome="issued", certificate_id=certificate_id, serial_number=serial)
                    finally:
                        db.execute("RELEASE learner_issue")
                outcomes.append(result)
            response = {"operation_id": operation_id, "course_id": body.course_id, "status": "completed",
                        "summary": {name: sum(row["outcome"] == name for row in outcomes) for name in ("issued", "skipped", "failed")},
                        "outcomes": outcomes}
            db.execute("UPDATE operations SET result_json=? WHERE id=?", (json.dumps(response, ensure_ascii=False), operation_id))
            db.commit()
            return response

    @app.post("/api/bulk-issue")
    async def bulk_issue(body: BulkRequest, current: Actor,
                         idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
        if not idempotency_key.strip():
            raise HTTPException(422, "Idempotency-Key must not be blank")
        request_json = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
        deadline = time.monotonic() + bulk_wait_seconds
        while True:
            result = await run_in_threadpool(bulk_attempt, body, current, idempotency_key, request_json)
            if result is not None:
                return result
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return JSONResponse(status_code=503, headers={"Retry-After":"1"}, content={
                    "code":"OPERATION_BUSY", "detail":"Database is busy. Continue using the same operation key."})
            # No open connection, transaction or worker thread is held while waiting.
            await asyncio.sleep(min(0.2, remaining))

    @app.post("/api/certificates/{certificate_id}/revoke")
    def revoke(certificate_id: int, current: Actor):
        with connection(database) as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM certificates WHERE tenant_id=? AND id=?", (current["tenant_id"], certificate_id)).fetchone():
                raise HTTPException(404, "Certificate not found")
            timestamp = utc_now()
            changed = db.execute("UPDATE certificates SET status='REVOKED',revoked_at=? WHERE tenant_id=? AND id=? AND status='ACTIVE'",
                                 (timestamp, current["tenant_id"], certificate_id)).rowcount
            if changed:
                db.execute("INSERT INTO audits(tenant_id,actor_id,certificate_id,event_type,occurred_at) VALUES(?,?,?,'REVOKED',?)",
                           (current["tenant_id"], current["id"], certificate_id, timestamp))
            result = detail(db, current["tenant_id"], certificate_id)
            db.commit()
            return result

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        if not (dist / "index.html").exists():
            raise HTTPException(503, "Build the frontend using the documented startup command")
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})

    return app


app = create_app()
