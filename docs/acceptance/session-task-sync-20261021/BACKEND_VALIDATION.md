# Session task synchronization backend validation

Date: 2026-10-21, Asia/Singapore. Local development only; no production migration/deployment and no SUT execution.

## Result

- Final targeted regression: **44 passed** (`tests/test_session_tasks.py`, `tests/test_interactive_api.py`, `tests/test_interactive_constraints.py`, `tests/test_interactive_scope.py`, `tests/test_native_intake.py`). This is 9 new management tests and 35 existing managed/native tests.
- The management tests use real PostgreSQL/API requests. They cover session uniqueness, concurrent updates, atomic idempotency, stale versions, original receipt lookup after later versions, unchanged revision reuse, omitted case retention, FAIL report history, historical task reconstruction, scoped authorization/revocation, same-actor client changes, report/task isolation, and immutable database history.
- Execution-side tables remain unchanged by the management round trip: legacy TestRun, TestExecution, Evidence, DurableJob, RunExecutionBinding, NativeTestRun and NativeConclusion. A management-only grant cannot submit the existing managed execution task.
- Scoped reads/writes require `task:sync`; existing grants do not acquire this scope automatically. Existing Web reads keep their deployment trust boundary. Provider/session references remain declared source metadata.
- Ruff checks pass for the changed backend, migration and backend tests.

## Database and migration

The existing exact container `hypertest-native-qa16-20261021` was started. The historical `hypertest_native_qa` database and volume were retained. New management development uses a separate `hypertest_session_sync_qa` database on loopback port 55439.

The first test run exposed a bug in the new migration's history trigger: a conditional expression referenced `NEW.project_id` on a CaseRevision row, which does not have that column. The affected sync transaction rolled back; this was not a successful partial intake. The migration source was corrected to branch on table type before accessing table-specific fields. Only the new management QA database's function was replaced during diagnosis; no rows were deleted or history rewritten. A subsequent test fixture error used an invalid direct legacy grant transition and was corrected to call the existing revoke API.

A related regression initially expected exactly 9 MCP tools; the additive two management tools now make 11, while the 9 existing execution tools remain unchanged. The HTTPS-only regression is run with the local HTTP development exception disabled in the test process; the development API separately enables the explicit loopback exception.

The final migration file was then applied from 0001 through 0022 to another new independent database, `hypertest_session_sync_migration_check_20261021`. That database reached `0022_session_task_sync` and contains the four new management tables. Two operation/immutable-guard smoke tests passed there without manual function replacement. Raw migration and smoke output: [migration-check.txt](migration-check.txt).

## Runtime boundary

Development API: `http://127.0.0.1:8101`; private runtime configuration is kept outside the repository under `~/.local/share/hypertest/session-sync-dev-20261021` (directory 0700, files 0600). No key is recorded here. Actual MCP ingestion and final restarted-runtime readback are recorded separately by the integration acceptance report.

Report Markdown is stored verbatim in PostgreSQL ReportRevision rows and original sync payloads. User-provided `artifact_uri`/`source_ref` are metadata only: the API does not execute them, read their local paths or fetch their URLs. This management profile does not independently authenticate test execution or generate a release verdict.
