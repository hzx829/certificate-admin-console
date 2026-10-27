# A2 recovery: tests before implementation

This is a user-authorized improvement after the original timed delivery. Preserve
the original bundle. No database schema, queue, or production fault endpoint is needed.

Backend checks (tests/a2_recovery.py) extend the original 12 real HTTP tests:

1. Completed operation replay and conflicting payload return immediately during an
   unrelated SQLite writer; unauthorized course still returns 404. No extra writes.
2. A test-only connection wrapper pauses a real bulk transaction immediately before
   commit for 20 seconds. Six calls across two server processes return identical 200
   results; a competing course gets 409. No uncommitted side effects are visible.
   A list request succeeds during the wait. Delta: two certificates, two audits,
   one operation. The fixture lives only in tests/a2_server.py.
3. One-second test wait budget: structured 503 OPERATION_BUSY + Retry-After: 1,
   no side effects, original key succeeds after releasing the lock.
4. 48 waiting HTTP requests must not exhaust the synchronous request workers;
   a list request completes within two seconds, then all callers receive one result.
5. Run the original A1-A7 suite, including rollback injection and 100,000-row export.

Frontend checks: node --test frontend/src/pending.test.mjs. Save key and immutable
payload before sending, restore by actor, clear only the confirmed key, surface
storage failures and reject malformed records instead of losing recovery context.

Chrome checks use isolated test databases and the test proxy, recording real keys:

| Scenario | Expected |
| --- | --- |
| Commit succeeds, response lost, reload | Continue original operation uses original key/payload and returns original issued outcomes |
| Reload while transaction pending | Recovery still uses original key; one operation and one set of certificate/audit changes |
| Alice pending, switch Bob, switch Alice | Bob never sends Alice's operation; Alice restores her original course/key |
| Confirmed operation, next deliberate issue | New key; previous recovery record cleared |
| sessionStorage write denied | Visible storage error and zero POST requests |
| Busy budget exhausted | Pending key survives; retry with same key can complete |

Production wait budget is 60 seconds, followed by an explicit retriable busy result.
The budget applies to waiting for a writer, not to arbitrary execution time. Waiting
releases the connection and thread. Recheck the key inside the acquired transaction.
sessionStorage covers reload and actor switching in one tab, not closed-tab recovery.

Record red tests before touching application code, then passing full regression
and observed Chrome results. Never label a planned check as executed.
