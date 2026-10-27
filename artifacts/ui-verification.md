# Chrome verification

Executed on 2026-10-27, Asia/Shanghai, through the Chrome extension and the
computer-use/browser tool. This is an observation record, not a replacement for
the complete native session. Test data is synthetic.

| Check | Observed result |
| --- | --- |
| Initial render | Four East certificates, appropriate course counts, readable table and issue panel. Initial layout was visually inspected with a screenshot. |
| Loading | Loading actors and Loading certificates observed, including with a delayed list response. Submit disabled until courses are loaded. |
| Actor and isolation | West showed only its certificate; searching E-DEMO-001 returned No certificates found. Switching back reset the old search and results. |
| Timezones | East E-DEMO-001 showed 2026-01-11 00:30; West W-DEMO-001 showed 2026-01-10 21:30; East winter fixture showed 2026-07-10 23:30. |
| Bulk progress | A temporary SQLite writer held the request in flight. A double click produced one operation; course and submit controls were visibly disabled with Processing this course. |
| Learner outcomes | Safety 101 completed with 2 issued, 2 skipped, 0 failed. Alex and Morgan issued; Jamie not completed; Casey already certified. |
| Pagination and sorting | Six records appeared after issuance, five on page one and one on page two. Changing to learner ascending reset page one and ordered Alex, Before Midnight, Casey, Morgan, Same Date. |
| Details and revocation | Detail showed serial, course, tenant, local time and issuance audit. Cancel left ACTIVE with one audit; confirmation showed REVOKED and exactly one new revocation event. List reflected REVOKED. |
| Errors and recovery | Stopped the owned server. Search showed an error and Retry list; bulk showed Retry same operation with its course frozen. Restarted the same DB: list recovered and First Aid issued Taylor once. Existing revocation survived restart. |
| CSV parity | Actual downloaded CSV contained all six matching records despite five-row pagination, ordered by learner. A filtered download contained only Alex. Files were parsed from the browser download directory. |
| Delayed old-actor response | Test-only proxy delayed East list responses eight seconds. Switched to West while East was loading; West remained visible after the delayed East response, with no East data or old operation results. |
| Response lost after commit | Proxy forwarded West issuance successfully then dropped the response. UI offered retry; retry returned the original 2 issued outcomes. Two proxy trace records have the same key and identical results, first dropped and second delivered. |
| Large CSV in Chrome | Independent 100,000-East database displayed 100000 total. Search Alex produced 33299. Export and Next were both usable; repeated export from page two still produced all 33299 rows. Parsed downloads were identical, unique and in increasing certificate-ID order for equal learner names. |
| Course-result association | Review found that selecting another course kept the previous result visible. Fixed by clearing completed results when course changes. Clean-clone Chrome check confirmed Safety 101 results disappeared on selecting First Aid. |
| Clean clone | A clone without .venv, node_modules, dist or data started with one run.ps1 command; browser showed four fresh East certificates and could issue the expected two. |

Evidence: [proxy trace](ui-network.jsonl), [startup results](startup-verification.json),
[automated acceptance](acceptance-results.json), and native session
`01a17c12-d4f6-7402-80e1-cc2e3463834f`.

The fault fixture is [tests/ui_proxy.py](../tests/ui_proxy.py). It runs separately
from the production app and adds no application endpoint or fault flag. Its
response-loss trace verifies real network requests rather than inferred UI state.
Exact export/list overlap and wall-clock durations are asserted in the automatic
HTTP test; browser observations alone are not used to claim timing guarantees.

No mobile or additional-browser checks were performed. The independent written
answers were not opened, created, or reviewed.
