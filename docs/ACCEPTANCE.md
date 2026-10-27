# A1–A7 acceptance contract

This contract is committed before application implementation. Verification uses
isolated SQLite files, real HTTP requests, and database assertions. UI checks use
Chrome. Test reports distinguish executed checks from unverified work.

## Fixed fixtures and API

| Tenant | Actor header `X-Actor-Token` | Courses | Timezone |
| --- | --- | --- | --- |
| East, ID 1 | alice-east | 101 Safety 101; 102 First Aid | Australia/Sydney |
| West, ID 2 | bob-west | 201 Safety 101 | Australia/Perth |

Admin emails: alice@east.test and bob@west.test. Both tenants have Alex Lee.
East course 101: 1001 Alex Lee completed/uncertified; 1002 Jamie Chen incomplete;
1003 Casey Wong completed/certified; 1004 Morgan Li completed/uncertified.
West has corresponding separate learners. East certificate 1 and West certificate
2 use `2026-01-10T13:30:00Z`. Extra certificates test winter and date boundaries.
Each scenario starts from fresh fixtures unless deliberately testing a replay.

Planned API, all business routes require the actor header:

- `GET /api/actors`: public demo identity choices only.
- `GET /api/courses`: courses and completion counts for the actor's tenant.
- `GET /api/certificates?q=&sort=issue_date&direction=desc&page=1&page_size=20`.
- `GET /api/certificates/export` with the same search/sort, without pagination.
- `GET /api/certificates/{id}`.
- `POST /api/bulk-issue`, JSON `{ "course_id": 101 }`, header `Idempotency-Key`.
- `POST /api/certificates/{id}/revoke`, empty body.

Search is literal case-insensitive substring matching of learner name or serial.
Sort fields: learner_name, course_title, serial_number, issue_date; each uses the
requested direction followed by certificate ID ascending. Page size is bounded.
CSV has exactly learner_name,course_title,serial_number,issue_date and exports all
matching records, including revoked certificates. Calendar dates use tenant time.
One lifetime certificate per tenant/course/learner; revoked certificates are not
reissued. These are documented choices where the brief leaves details open.

## A1 Tenant isolation

As Bob, list/search Alex and verify only West rows and West total counts. Search
an East-only serial and export it: zero records. Fetch East certificate 1 and a
nonexistent ID: identical 404 response. Bulk issue course 101 and revoke East 1:
404, with no changes to certificates, audits, or operation records. Repeat the
direction with Alice. Courses also remain tenant-scoped. Missing/invalid tokens
return 401. Supplied tenant IDs cannot widen scope.

UI: switch actor while a request is in flight; no old-actor rows/details/results
may appear under the new actor. Both tenants' identical names remain distinct.

## A2 Retry safety

On fresh East course 101, send the same key and payload sequentially, then on a
fresh database synchronize five concurrent HTTP clients with a barrier. Every
caller must return 200 and identical operation ID and outcome data. The delta is
two certificates, two ISSUED audits, one operation. Each certificate has exactly
one ISSUED event. Replay must preserve issued, not recalculate it as skipped.

Restart the server with the same database and replay: identical result, zero
changes. Send different keys concurrently for the same course: still only two
new certificates/audits. Verify the same key used by Bob is independently scoped.
Holding the SQLite writer briefly during the concurrent test forces observable
overlap instead of relying on requests happening to race.

UI: double clicking during submission sends one logical operation; uncertain
network failure offers retry with the same key and frozen course, not a new key.

## A3 Key misuse

Use Alice/key K/course 101, then K/course 102: 409. First operation and result
remain unchanged; course 102 has no new certificates/audits. K/course 101 still
replays successfully. Race 101 and 102 under the same key on fresh fixtures:
exactly one succeeds, one returns 409. JSON whitespace/order differences do not
change meaning; unknown fields are rejected by schema. Unauthorized courses are
rejected before returning any stored result.

## A4 Learner outcomes and atomicity

Assert exact East 101 outcomes: Alex and Morgan issued, Jamie skipped with
not_completed, Casey skipped with already_certified. Summary counts equal the
outcome records; every enrollment appears exactly once in learner-ID order.

Inject an audit INSERT rejection for Morgan using a database trigger in the test
fixture only: Alex succeeds; Morgan fails with neither certificate nor audit.
Replay retains the original failed result. Removing the trigger and using a new
key may issue Morgan. Inject a failure when saving the final operation result:
the entire transaction must roll back, with no partial certificate/audit writes.
Do not expose fault-injection controls in production endpoints.

## A5 DST and local date

At `2026-01-10T13:30:00Z`, East must display `2026-01-11 00:30`, West
`2026-01-10 21:30`; CSV dates are 2026-01-11 and 2026-01-10 respectively.
At `2026-07-10T13:30:00Z`, East displays `2026-07-10 23:30`.
Create same-UTC-day/different-local-day and same-local-day/different-time fixtures.
Date sort asc/desc, paginated list, and CSV must agree on date then ID order.
Expectations use fixed known values and an independent reference ordering.

## A6 Export growth and responsiveness

An explicit generator creates a separate database with exactly 100,000 East
certificates, leaving the default quick-start database unchanged. West remains a
separate small set. Include repeated names, courses and local dates; serials are
unique. Query `q=Alex` to match a known large subset, sort by learner_name, then
export twice with no intervening mutations.

For each export measure from HTTP request start through the last response byte:
at most 60 seconds. Parse CSV (not physical newline counts), check exact headers,
all field values, exact matching East serial set, no duplicates, complete order,
and identical relative order for equal keys across both exports. The reference
comes from fixture/database data sorted independently, not the export itself.
Also export all 100,000 rows to verify the full volume rather than a tiny subset.

During the first export, after receiving initial bytes and before the download
finishes, send a list request. Record request/response timestamps and verify 200
before export completion. A merely sequential list request does not count.
Use a second request/connection, no artificial delay in the production handler.
Check another sort field/direction and Bob's export for query parity/isolation.

UI: search and sort, download CSV, verify its selection and order; pagination
must not restrict export to the visible page. List remains usable during export.

## A7 Revocation audit

Revoke an ACTIVE East certificate: 200, REVOKED, exactly one new REVOKED event.
Repeat sequentially and concurrently: status and first revocation timestamp stay
the same and audit count remains one. Original ISSUED event remains present.
Inject a revocation-audit INSERT failure: status must remain ACTIVE after rollback.
Cross-tenant request: 404 and zero changes. UI cancel produces no mutation;
confirm changes the displayed status and disables further revoke action.

## Additional required checks and evidence

From a clean checkout, one documented command installs declared dependencies,
initializes demo data, builds the UI and starts the app. Repeat startup must
preserve prior mutations. Frontend build, Python syntax checks and actual HTTP
verification are recorded separately. Chrome checks include loading, empty,
error/retry, actor selection, pagination, sorting, bulk progress/results, detail,
confirmation and export. No claim of passed UI checks without observed behavior.

The automatic runner writes artifacts/acceptance-results.json with case names,
durations and A6 measurements. UI observations go in artifacts/ui-verification.md.
README links these results and documents real commands, limitations and any
unfinished checks. AI evidence is native chronological JSONL with narrowly
declared redactions; do not replace it with a curated prompt list.

No implementation or polishing after the three-hour deadline. Section 6 remains
entirely for the candidate, outside this code and verification workflow.
