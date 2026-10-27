# Decisions and verification

Session: [01a17c12-d4f6-7402-80e1-cc2e3463834f](sessions/01a17c12-d4f6-7402-80e1-cc2e3463834f.jsonl).
Commit IDs refer to this local repository and can be inspected using `git show`.

| Decision | Reason and result | Verification | Commit |
| --- | --- | --- | --- |
| Accepted: persist the entire bulk operation result, with certificate and audit writes in one transaction | Duplicate requests must replay issued outcomes rather than re-evaluate them as skipped. Database constraints additionally protect different-key requests. | [A2/A3/A4 automatic cases](../artifacts/acceptance-results.json), [real browser lost-response trace](../artifacts/ui-network.jsonl) | 034d905 |
| Corrected: sqlite3 connection context managers were assumed to close test connections | First run reached cleanup but failed on Windows file handles. Used contextlib.closing and explicitly terminated the owned Windows server process tree. Did not hide the failing run or mark its checks as passed. | [First failing report](../artifacts/acceptance-first-run.json), [12 passing cases after correction](../artifacts/acceptance-results.json) | fc63fcb |
| Scope tradeoff: synchronous bulk transactions and streamed CSV, without Redis or a job system | SQLite WAL, a short write transaction and bounded CSV batches cover the required workflow with fewer moving parts. Export resumption and reissuing revoked certificates are outside the selected scope. | [Acceptance contract committed first](../docs/ACCEPTANCE.md), [A6 timing and overlap](../artifacts/acceptance-results.json) | b0d1100, 034d905 |
| Corrected: course changes retained the previous course's displayed result | Observed during Chrome testing; clearing completed results prevents an old Safety 101 outcome appearing associated with newly selected First Aid. | [Clean-clone Chrome check](../artifacts/ui-verification.md) | 794a25c |

The initial dependency install reported a high-severity Vite advisory. Vite was
updated from 8.0.3 to 8.3.5 before verification; the subsequent install audit
reported zero vulnerabilities. Commands, errors and outputs remain in the native
session. No AI failure or user rejection has been invented for this record.

Post-delivery A2 improvement, explicitly authorized by the user in the same session:

| Decision | Reason and result | Verification | Commit |
| --- | --- | --- | --- |
| Accepted: optimistic read replay followed by recheck under the write lock; sessionStorage before sending | Completed results should not compete for a writer; reload must reuse the original key and payload. Keep the existing operation table and atomic write transaction. | [Tests committed before implementation](../docs/A2-RECOVERY-ACCEPTANCE.md), [old implementation failures](../artifacts/a2-before-results.json), [Chrome trace assertions](../artifacts/a2-ui-results.json) | f98f055, 0ee2032, 50370a5 |
| Corrected: retrying BUSY only at BEGIN IMMEDIATE was too narrow | Real concurrency produced BUSY during the preceding course SELECT. Extended retries only over the pre-write phase; failures after writes are still rolled back and reported. | [First implementation failures](../artifacts/a2-first-implementation-results.json), [diagnostic traceback](../artifacts/a2-concurrency-diagnostic.log), [16 passing HTTP cases](../artifacts/a2-regression-results.json) | 50370a5 |
| Scope: bounded waiting and per-tab recovery | Use a 60-second asynchronous waiting budget and sessionStorage. Long database outages may still return structured 503; closed-tab recovery is not promised. No queue, schema migration or cross-device history. | [Result and limitations](../docs/A2-RECOVERY-RESULTS.md), [five frontend tests](../artifacts/a2-frontend-tests.txt) | 50370a5 |
