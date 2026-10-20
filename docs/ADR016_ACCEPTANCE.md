# ADR-016 implementation and acceptance — 2026-10-20

ADR-016 is implemented in this working tree. A real current-Agent cycle completed
against an isolated HTTPS platform with separate API and Worker processes,
PostgreSQL and a real Docker Runner. This change has **not been deployed to
production**. Existing production data, credentials, VPN allowlist and ADR-015
managed Harness processes were not modified.

Machine-readable observations and artifact hashes are recorded in
[adr016-20261020.json](evidence/adr016-20261020.json). Installation and operational
boundaries are in [INTERACTIVE_MCP_CLIENT.md](INTERACTIVE_MCP_CLIENT.md).

## Delivered behavior

- An installable Python MCP stdio server, private local transport daemon,
  persistent intent journal, configuration examples and packaged Agent Skill.
- Task submission and receipt lookup; execution attach and explicit continuation;
  nine bounded TMP tools; progress, evidence and report lookup/read.
- Project-scoped integration permissions, separate exact device authorization,
  controlled host attestation, native-session/workspace/epoch/Job claim binding
  and short execution grants. Tokens stay outside model-visible tool results.
- The API authenticates and persists typed requests. The original Job Worker
  consumes the inbox and invokes the existing TMP admission/Runner paths. It does
  not launch a replacement Agent for interactive execution.
- Query-first recovery after lost replies and transport restart. Expired ownership
  requires explicit operator recovery with the original native/workspace identity;
  the epoch increases and a linked retry Job preserves history. Source filesystem
  verification belongs to the Worker via the existing runtime-control channel.
- Additive migrations `0019_interactive_mcp` and `0020_interactive_tool_inbox`;
  existing SERVER_HOST and LOCAL_CONNECTOR / PLATFORM_MANAGED paths remain.

## Real current-Agent cycle

The actual Codex Desktop Agent in this conversation drove an official
`mcp.ClientSession` through [the transparent console](../scripts/interactive_mcp_console.py).
Each request crossed stdio MCP, the private Unix socket daemon, certificate-verified
HTTPS, the API inbox and the original Job Worker. The console generated no
Proposals and launched no Provider/model. The Agent read the returned contracts,
reasoned about the frozen PRD and authored the submitted tests. This is not a
claim that a tool catalog was hot-reloaded into the already-open chat.

The SUT was the selected Sum HTTP API at public repository
`https://github.com/ZhangLiangchen/hypertest-one`, fixed commit
`cc84398ad81c26bd484ebaae46e6f61713d912ad`. The local source adapter acquired that
commit and uploaded a Git bundle; the platform independently accepted it and
materialized its source copy. The controlled local workspace was independently
checked against the same origin and commit. The MCP client did not upload a dirty
checkout. This commit identifies the SUT and implementation base, not a committed
version of the new ADR-016 code.

| Observation | Result |
| --- | --- |
| Run | `01a157bb-b031-7bf2-9449-59fe02566051` |
| Execution selection | `LOCAL / LOCAL_CONNECTOR / INTERACTIVE_MCP` |
| Requirements / Risks / TestCases / Implementations | 2 / 3 / 4 / 4 |
| Formal execution | 1, trusted `docker`, `OFFICIAL`, `COMPLETED / PASS` |
| Real HTTP tests in Runner JUnit | 27 passed; 0 failures, errors or skips |
| Evidence | 5 `RUNNER / VERIFIED` objects, all read through MCP |
| Content verification | SHA-256 and byte count checked for all 5 objects |
| Gate | `FINAL / RELEASE_READY` |
| Report | Accepted, then read in 2 cursor pages; version, SHA-256 and size checked |
| Final lifecycle | Run `COMPLETED`, Job `SUCCEEDED`, Binding and main AgentSession `CLOSED` |

The closed AgentSession is the platform attachment. The user's native chat
remained usable, as required. The database contained exactly one native
AgentSession, one formal Execution and one `request_execution` inbox item for
this Run. The sanitized record stores only a hash of the native session ID; no
conversation, chain-of-thought, credentials or native metadata file is included.

## Authorization and reconnection observations

A deliberately short 10-second execution grant expired before work was submitted.
New work stopped and the old Job failed. Explicit operator recovery retained the
Run, main AgentSession, native identity and workspace, incremented epoch 1 to 2
and created a linked retry Job. The pre-grant rendezvous deadline subsequently
expired while preparing the console; a second explicit recovery increased the
epoch to 3. The successful cycle used that third Job. These failed historical
Jobs are retained rather than hidden.

After the Docker result returned, both stdio and the transport daemon were
stopped and restarted from the original trusted context. Querying the original
`request_execution` key returned the same Execution. Only an explicit
continuation obtained a fresh memory-only execution token. Reconnection did not
create another Run, native session, Job or formal execution. The current-Agent
restart occurred after the Runner completed; in-flight HTTP cancellation and
Runner drain are covered separately by the real Docker integration tests.

The initial current-Agent recoveries preceded the final change that moved source
verification from API to Worker. That final route is verified separately by the
integration tests: only the runtime-control Worker performs source verification,
same-key POST/GET return the original control result, and authorization is
rechecked after filesystem I/O. This distinction prevents the live local lab
from hiding a split-deployment filesystem requirement.

## Verification

The final single full regression ran against a new isolated database after all
runtime changes, including the Worker-only recovery fix: **967 passed, 18 skipped,
0 failed/errors**, in 162.01 seconds. It applied migrations from an empty schema
through `0020_interactive_tool_inbox`. `HYPERTEST_INTERACTIVE_DOCKER_E2E=1` enabled
both real interactive Docker scenarios. The 18 skips are existing separately
opt-in controlled Runner smoke tests; none is an interactive test. The run also
reported three warnings.

The regression covers the existing managed Harness paths as well as project/scope
isolation, atomic submission, native-session uniqueness, exact device rotation,
claim/epoch fencing, unknown-call reconciliation, cancellation/Runner drain,
operator-only Worker recovery and revocation during source verification. API and
Worker recovery tests verify that filesystem inspection runs only in the
runtime-control Worker, with exact authorization rechecked after that I/O.

Ruff passed for `src`, `tests`, `alembic` and the transparent console;
`git diff --check` passed. The final wheel was built and installed with its
`interactive` extra in a clean virtual environment; its entry point and config
export ran successfully. All 120 packaged source/asset files matched the tree,
and the 124 archive entries contained no credentials, journals or logs. Wheel
SHA-256: `5a7b0b9b1333dc19055c07a9a2b0b17d708d0fed0fd5a1f84a10730354539e4c`.
The uncommitted implementation is identified by a
[runtime source manifest](evidence/adr016-runtime-sha256.json), not by pretending
the base commit contains these changes.

After the final code was frozen, only the isolated lab API and Worker were
restarted. MCP still read the same completed Run and saved report. An operator
recovery request against that original `CLOSED` attachment traversed the final
Worker route and returned HTTP 409; the same recovery key returned the original
rejection, with no change to epoch, Session or binding status. The successful
recovery case for this final route remains the independent integration test
described above.

The test transport, lab API/Worker and the newly created PostgreSQL container
were stopped after verification. The database volume, private lab records and
built wheel were retained. No existing Connector or production process was
stopped or reconfigured.

## Pre-deployment concurrency review

The subsequent release review reproduced a PostgreSQL deadlock between explicit
continuation and integration revocation: opposite lock order could abort the
revocation transaction. Continuation now acquires the same ordered shared
authority locks before any short-grant lock, then revalidates the current
integration and exact device using the database clock before issuing a grant.
Three real concurrent API tests cover continuation winning, integration revocation
winning, and device rotation winning. All 28 focused API/runtime/constraint/scope
tests passed after this fix, including both real Docker scenarios and Worker-only
recovery; Ruff and diff checks passed. The earlier 967-test result, wheel hash
and source manifest identify the earlier isolated acceptance snapshot. The
merged release, its CI and deployed build identities are recorded separately.

## Current limits

LOCAL execution binding currently supports the controlled Codex Desktop stdio
launch context with matching native environment/owned metadata/process ancestry
and pinned kernel peer. A generic shared MCP host without this evidence supports
submission/read and CLOUD submission, and fails closed for LOCAL binding. A
replacement stdio process requires an explicit daemon restart in the original
context. An expired claim requires operator recovery; no process restart, polling
or journal lookup grants execution authority.

The new Web execution mode/driver selector is a separate UI delivery. This change
does not claim real private-Git or GitLab issue-write acceptance for ADR-016;
existing authorized source and issue execution paths are preserved and covered
by regression. Formal execution facts still come from the platform Runner,
independently of where the Agent performs its task.
