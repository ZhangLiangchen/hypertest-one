# Interactive Agent MCP client

The current release is deployed and its controlled current-Agent cycle is
verified; release identity, acceptance scope and recovery evidence are recorded
in [ADR-016 production deployment](ADR016_PRODUCTION_DEPLOYMENT.md).

## Install and pair from “My computer”

In **Create test run → My computer**, copy the MCP installation prompt for this
Project and give it to the Agent that will use HyperTest. The prompt contains
the HTTPS platform address, Project ID, fixed release identity and setup steps;
it must not contain a device-management, device or integration secret. The Agent
installs the verified wheel, runs local setup, and adds the generated paths-only
MCP entry to its own supported host configuration while preserving existing entries.
Reload/restart the host if it requires that to discover new tools.

This change supplies release tooling and setup guidance. **The planned first
public distribution tag is `mcp-v0.1.0`; adding the workflow or displaying an
installation prompt does not publish that release.** Until an operator actually
publishes its assets, use the fixed-commit development installation below rather
than an invented release URL, a moving `main`, or an unrelated PyPI package. The
[release page](https://github.com/ZhangLiangchen/hypertest-one/releases) is where
operators publish the versioned wheel, `release-manifest.json`, `SHA256SUMS` and
`INSTALL.md`. Select a concrete tag and full source commit; verify the wheel's
exact SHA-256 and size from that approved build before installing it.

The device-management key is the existing **global single-Operator credential**
`HYPERTEST_CONNECTOR_OPERATOR_KEY`, configured by the deployment administrator in
the protected `platform.env`. Ask that administrator for authorized access via
an owned `0600` secret file or enter it at the setup command's interactive hidden
prompt. There is no public “get management key” API, and being logged into an
Agent, Git or GitLab does not grant it. Do not paste it into Agent chat or a shell
command. The Web form keeps an explicitly entered key only in that view's memory.
See the [deployment configuration](../ops/container/CONNECTOR_TLS.md#配置归属).

After installing the approved wheel, run this command locally, replacing the
nonsecret placeholders and using absolute private paths:

```sh
python -m hypertest.interactive_client setup \
  --api-url https://hypertest.example.com/api/v1 \
  --project-id 00000000-0000-0000-0000-000000000001 \
  --directory /absolute/private/hypertest-project \
  --operator-key-file /absolute/private/operator.key \
  --name 'My computer' --host generic
python -m hypertest.interactive_client doctor \
  --config /absolute/private/hypertest-project/client.json
```

Omit `--operator-key-file` only for a real interactive terminal: setup then reads
the key through a hidden prompt and fails if no terminal is available. Use
`--ca-file /absolute/path/to/approved-ca.pem` for a private CA; preserve hostname
and certificate checks and the existing VPN/allowlist access. `--host generic`
supports submission/read and CLOUD through stdio on macOS/Linux. Select
`--host codex-desktop` only for the controlled native adapter; setup does not prove
that the currently configured host can bind this chat for LOCAL execution.
Windows and arbitrary native Agent execution adapters are not currently supported.

`setup` is a separate local preparation command, **not an MCP tool**. Under the
explicit operator authorization it pairs a new device, registers a stable
installation and a scoped Project integration; selecting the controlled host
also approves that Project's Harness adapter policy using the existing APIs. It writes narrow credentials to
owned private files, emits public IDs and configuration paths, and does not put
the Operator key in the runtime config or MCP snippet. Source acquisition,
approved repository origins, issue-executor rights, fixed source transfers,
Run binding and short execution grants remain separate. Installation does not
start another Agent or replace the existing server or Connector-managed modes.
Check setup failures before retrying; never rotate/revoke an existing device or
discard a private journal to make an uncertain registration appear successful.
Each preparation POST is marked uncertain in a durable private setup record
before transmission. If a response or one-time credential is lost, setup refuses
to replay that step and reports administrator reconciliation required; it does
not manufacture a new node, installation or registration.

The doctor validates local configuration and platform profile connectivity;
successful checks mean the configured capabilities are available, not that a
test Run has executed. Pairing and installation alone do not make a device's
managed WSS Connector online, upload source, or produce trusted Runner Evidence.

## Fixed-source development installation

ADR-016 implementation provides a local stdio MCP server, a separate private
Connector daemon, a durable intent journal, and a trusted host adapter. It does
not start a Provider, model or substitute Agent. For development, first check
out and review an explicit full commit, then install with Python 3.12+:

```sh
uv pip install -e '.[interactive]'
python -m hypertest.interactive_client print-client-config --config /absolute/private/config.json
```

The second command emits a client installation snippet containing executable and
configuration paths only. The package includes examples and the usage Skill at
`hypertest/interactive_client/assets/`; copy the `hypertest-interactive` Skill
directory to the target client's supported skill location. Do not copy tokens
into the client snippet or Skill. The official MCP SDK handles stdio protocol
negotiation; HyperTest additionally requires business profile
`hypertest.interactive-mcp/v1alpha1` from the platform capabilities endpoint.

For a trusted Codex project, place the stdio entry in `.codex/config.toml` (or use
the user-level `~/.codex/config.toml`). Use absolute executable/config paths:

```toml
[mcp_servers.hypertest]
command = "/absolute/venv/bin/python"
args = ["-m", "hypertest.interactive_client", "stdio", "--config", "/absolute/private/config.json", "--autostart"]
startup_timeout_sec = 20
tool_timeout_sec = 120
```

These are the [official Codex MCP configuration fields](https://developers.openai.com/codex/mcp/).
Registration alone does not prove the active native session. The controlled host
checks below still apply; a generic shared MCP launch without that capability
supports submission/read and CLOUD, and rejects LOCAL execution binding.

Keep configuration, integration/device tokens, state and the journal owned by
the current user. Config/token files require mode `0600`, state directories
`0700`. The socket directory must have a short absolute path suitable for Unix
domain sockets. The daemon verifies the kernel peer UID/PID and a separate local
IPC capability, and never exposes the integration/device/execution token through
MCP. HTTPS verifies certificates and rejects redirects; an explicit test-only
loopback HTTP setting does not permit remote HTTP.

An example private config, with credential **paths** rather than values:

```json
{
  "api_url": "https://hypertest.example.invalid/api/v1",
  "state_dir": "/absolute/private/ht-interactive",
  "integration_token_file": "/absolute/private/integration-token",
  "device_token_file": "/absolute/private/device-token",
  "node_id": "00000000-0000-0000-0000-000000000003",
  "host_adapter": {"kind": "codex-desktop-stdio"},
  "workspaces": {}
}
```

Integration authorization, device identity, Project Harness capability,
source-acquisition and issue-executor permissions are independent. Runtime MCP
tools do not create or expand them; the separate operator-authorized setup CLI
only performs its explicitly requested preparation. LOCAL requires already accepted fixed source;
it does not upload a dirty checkout or fetch another branch on its own.

For manual preparation instead of setup, prepare the existing Project,
[pair its device](LOCAL_CONNECTOR.md#3-配对并保存设备凭据)
and obtain an [ACCEPTED source transfer](LOCAL_CONNECTOR.md#61-固定源码请求) through
the ADR-015 preparation flow. Keep its approved origin, full commit SHA, node ID
and transfer ID. This MCP plugin has no source-upload or device-pairing tool.
All UUIDs below are examples: replace them with the registered identities; retain
one freshly generated `client_instance_id` per installation across restarts.

An operator registers the integration with
`POST /api/v1/interactive/registrations`, using the protected `X-Hypertest-Operator-Key`
configuration described in the pairing guide. The complete body for this
submit/read/execute edition is:

```json
{
  "actor_ref": "approved-operator-codex",
  "client_instance_id": "00000000-0000-4000-8000-000000000002",
  "project_id": "00000000-0000-0000-0000-000000000001",
  "scopes": ["task:submit", "run:read", "evidence:read", "report:read", "run:execute"],
  "expires_in_days": 30
}
```

Store the returned one-time `integration_token` directly in the private file
named by `integration_token_file`, and the separately paired device token in
`device_token_file`, both `0600`. Retain the nonsecret registration IDs; do not
paste either response or operator credentials into MCP arguments, chat or Skill.
Submission/read-only clients may request fewer scopes and cannot execute.

The node also needs a separately approved Project Harness capability explicitly
allowing this adapter. The operator body for
`POST /api/v1/harness-nodes/{node_id}/capabilities` is:

```json
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "capability": "harness",
  "constraints": {"interactive_host_adapters": ["codex-desktop-stdio/v1"]},
  "policy_version": "operator-v1"
}
```

An existing active capability must use the documented [revoke/regrant workflow](LOCAL_CONNECTOR.md#撤销项目能力) to
change policy; installation does not replace it or expand source/issue rights.

For LOCAL / INTERACTIVE_MCP, the shipped adapter supports a **controlled current
Codex Desktop stdio launch context**: matching native thread/session environment,
owned native metadata, a real Codex ancestor and process birth, and the live
kernel-observed stdio peer must agree. Generic MCP hosts do not automatically
provide this identity. Missing/inconsistent capability rejects local binding;
submission/read and CLOUD remain available. Do not invent IDs or set another
chat's session environment to bypass the check. The adapter reads native session
metadata only, not the conversation or chain-of-thought.

The first trusted stdio peer PID and process birth are pinned for the daemon
lifetime. A replacement stdio process cannot take over just because it shares
the Codex ancestor. A transient connection loss in the original live process may
reconnect; after process replacement, explicitly restart the daemon in the
original trusted native context, query the same submission/attach identities,
then request explicit continuation. An expired claim still needs operator
recovery. Do not advertise a shared generic MCP server as automatic cross-chat
resume.

Transport restart preserves the configured workspace and private journal; it
does not create a native session, Job, execution grant or a replacement request.
Execution tokens are memory-only. After daemon restart, query the original
attachment and operation identities first; continuing needs a new explicit
continuation intent under a still-valid claim, or the operator recovery workflow
if ownership has expired. Reuse the original Run, native session and attach key.

For the initial LOCAL task, call `hypertest_submit_task` with this typed argument
shape. Replace the illustrative frozen inputs with the approved SUT inputs; the
origin/SHA/node/transfer must match the existing ACCEPTED transfer. The environment
profile must already be available to the platform Runner. Keep the submission key
for all lost-reply queries, and omit `bootstrap.idempotency_key`:

```json
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "submission_key": "sum-regression-sha-cc84398-1",
  "execution_mode": "LOCAL",
  "execution_driver": "INTERACTIVE_MCP",
  "bootstrap": {
    "repository_url": "https://github.com/ZhangLiangchen/hypertest-one",
    "commit_sha": "cc84398ad81c26bd484ebaae46e6f61713d912ad",
    "prd_text": "Use real HTTP through the Runner-provided HYPERTEST_BASE_URL; do not call ASGI handlers, TestClient or functions directly. POST /v1/sum accepts exactly a and b, both strict integers in [-1000000,1000000], and returns HTTP 200 with exactly {\"result\":a+b}. Missing fields, additional fields, booleans, strings and fractions return HTTP 422. Behavior for integers outside that range is unspecified; do not invent a rejection requirement.",
    "configuration_text": "{\"test_scope\":\"sum-http-regression\",\"transport\":\"real-http\"}",
    "policy": {},
    "environment": {
      "profile_id": "python-api-v2",
      "service": {"app": "examples.api_sut.app:app", "health_path": "/health", "startup_timeout_seconds": 20}
    },
    "harness_mode": "LOCAL_CONNECTOR",
    "harness_node_id": "00000000-0000-0000-0000-000000000003",
    "source_bundle_transfer_id": "00000000-0000-0000-0000-000000000004"
  },
  "budget": {"max_steps": 32, "timeout_seconds": 300, "harness_budget_seconds": 3600}
}
```

The accepted receipt supplies `test_run_id` and `initial_job_id`; it grants no
execution authority. A lost reply is queried with `hypertest_get_submission`
using the original `project_id` and `submission_key`.

After a Run is accepted, register its existing controlled pinned repository in
the private config and restart the daemon before binding:

```json
{
  "workspaces": {
    "00000000-0000-0000-0000-000000000005": {
      "workspace_id": "0123456789abcdef0123456789abcdef",
      "path": "/absolute/controlled/pinned-repo",
      "commit_sha": "cc84398ad81c26bd484ebaae46e6f61713d912ad",
      "origin": "https://github.com/ZhangLiangchen/hypertest-one",
      "source_bundle_transfer_id": "00000000-0000-0000-0000-000000000004"
    }
  }
}
```

`workspace_id` is a stable 32-character lowercase UUID hex identity for this
controlled workspace, for example `uuid.uuid4().hex`; retain it across reconnects.
Replace the example mapping key with the receipt's actual `test_run_id`.

The daemon checks this mapping against the platform's run:execute-scoped
execution-context endpoint before host
attestation. The host adapter independently verifies source and lifecycle; an
empty directory, arbitrary model-supplied path, dirty source, a different origin
or native session is not valid evidence. The platform creates its independent
source copy from the accepted transfer, rather than reading the local path.

Start manually, or let the stdio entry start only the transport daemon:

```sh
python -m hypertest.interactive_client daemon --config /absolute/private/config.json
python -m hypertest.interactive_client stdio --config /absolute/private/config.json --autostart
python -m hypertest.interactive_client stop --config /absolute/private/config.json
```

For actual current-Agent execution, use the controlled stdio launch context. A
daemon started outside that context cannot infer the current chat from being
alive. The daemon stores the private socket capability in `ipc.token`; stdio
loads that local capability, while only the daemon reads platform credentials.
SIGTERM closes the daemon and removes its socket. Do not unlink a live socket
to force a second daemon.

Use `hypertest_submit_task`, then `hypertest_bind_execution` with a stable
`attach_key`. Binding does not itself start a model or provide a runtime grant.
Query `hypertest_get_execution`; when the coordinator is ready, explicitly call
`hypertest_bind_execution` with `action: "continue"` and a stable
`continuation_key`. The daemon keeps the returned execution token privately.
Then use the nine TMP tools with `{execution_id, arguments}`; the current Agent
performs analysis and writes Proposals, while the platform validates and obtains
trusted Runner facts. The API enqueues typed tool requests for the original
Worker coordinator; the API process does not run Docker or start a Provider.
Queries never renew execution authority.

With the actual returned Run ID substituted, the MCP calls are:

| Tool | Arguments |
| --- | --- |
| `hypertest_bind_execution` | `{"run_id":"00000000-0000-0000-0000-000000000005","attach_key":"sum-attach-1"}` |
| `hypertest_get_execution` | `{"run_id":"00000000-0000-0000-0000-000000000005","attach_key":"sum-attach-1"}` |
| `hypertest_bind_execution`, only after `execute_ready: true` | `{"run_id":"00000000-0000-0000-0000-000000000005","attach_key":"sum-attach-1","action":"continue","continuation_key":"sum-continue-1"}` |

Use the returned `execution_id` for TMP calls. For example, call
`request_mission` with the existing business arguments nested inside the wrapper:

```json
{
  "execution_id": "00000000-0000-0000-0000-000000000006",
  "arguments": {"idempotency_key": "sum-requirements-1", "mission_type": "ANALYZE_REQUIREMENTS"}
}
```

Read its full Mission contract before reasoning and submitting a Proposal.
Never supply a native session ID, host proof, token or claim in these arguments.

All nine tools use a durable transport request key. For writes this is the
business `arguments.idempotency_key`; an optional outer `request_key` must match
it. For `get_state` and `get_issue`, the daemon creates a key when omitted and
returns it with a pending/unknown result. Repeat the same call with that outer
`request_key` to query the original request, including after daemon restart.
Keep the same arguments. `QUEUED` and `RUNNING` mean the Worker has not returned
the result yet, and `UNKNOWN` requires reconciliation; none permits another POST
under a replacement key. A successful transport unwraps the original TMP result
and adds `_transport` provenance; a domain `REJECTED` result remains rejected.

Evidence/report page hash accumulation is daemon-memory-only. After daemon
restart, an earlier content cursor fails with `CONTENT_VERSION_CONFLICT`; a
partial stream is never accepted as a verified whole object. Read the same
object again from its first page, retain the pinned object version and hash,
and verify the complete byte count and digest. Do not join pages from different
versions. Restarting a read does not renew authorization or issue a write. The
current-Agent two-page report acceptance used one live daemon, and does not
claim a durable read accumulator across process restart.

Before each submission/attach/continue/tool write, the local journal persists the
intent; it marks SENT before network I/O. A lost reply becomes UNKNOWN and can
only be queried under the same identity, including after daemon restart.
NOT_FOUND is not proof that the write did not execute. No reconnect, MCP
cancellation or restart automatically resends a POST, changes keys, launches a
new Run or resumes an Agent. Continuing after uncertain grant delivery needs
reconciliation and a new explicit operator intent; it is not a background retry.

Closing a local Agent stops its reasoning, while an already accepted Runner may
finish under its original valid ownership. Reconnection proves the original host
identity again; expired claims require the existing fenced recovery workflow.
Revoking platform authority does not promise to terminate the entire personal
chat or its native tools. One real native execution session binds at most one
Run; it may submit/read other Runs. Formal Evidence and Gate decisions remain
platform facts, and local shell output remains exploratory context.

Expired ownership requires the independent operator recovery API, which the MCP
plugin does not expose. An authorized operator client sends
`POST /api/v1/interactive/executions/{execution_id}/recover` with the operator
authorization, current integration bearer, original node device authorization,
and private trusted-host proof. Its body contains `expected_epoch`,
`expected_row_version`, a stable `retry_key`, and `host_proof`; the latter comes
from the trusted adapter, never a model-supplied native ID. Keep these credentials
outside the Agent's tool arguments and do not add an operator key to plugin config.

The API records a bounded runtime-control request. The trusted Worker verifies
the original fixed source/workspace outside aggregate locks, then rechecks
authorization, expected versions, original native identity and settled old
Job/Runner state before recovery. It increments the original binding epoch and
creates a linked retry Job; it does not reopen a terminal Job or start another
Agent. API-side recovery does not run Git or read the server source mirror.

The POST waits only for a bounded interval. For `QUEUED`, `RUNNING`, `UNKNOWN`,
or a lost reply, the operator queries
`GET /api/v1/interactive/executions/{execution_id}/recoveries/by-key?retry_key=...`
using the operator and current integration authorization. Keep the original
`retry_key`; NOT_FOUND does not prove the POST was absent, and UNKNOWN is not
permission to submit another recovery. A successful response identifies the
original binding and `new_job_id`. Query the original execution attachment until
the coordinator is ready, then explicitly continue to obtain a fresh private
short execution grant. Recovery status, daemon restart and ordinary queries do
not themselves grant execution authority.

## Build and publish a distribution (maintainers)

The release workflow is separate from application deployment and does not change
production data, Operator/device grants, VPN rules or either managed Harness.
Before publication, select the reviewed full source commit and package version.
The tag must exactly equal `mcp-v` plus `pyproject.toml`'s version; do not reuse a
published tag for different source or leave a new tag claiming the old package version.

From a clean checkout, a local candidate build can use a fixed commit before its
tag exists. Put output outside the repository so it stays clean:

```sh
python -m pip install build==1.2.2.post1 hatchling==1.27.0
python scripts/build-interactive-release.py \
  --tag mcp-v0.1.0 --ref <reviewed-full-commit> \
  --output /absolute/outside/repository/mcp-v0.1.0
```

The builder exports that committed tree with `git archive`, requires its package
version to match, builds with the commit timestamp, verifies wheel metadata and
bundled MCP/Skill assets, and emits:

| Asset | Contract |
|---|---|
| `hypertest_one-<version>-py3-none-any.whl` | Fixed-source installable Python package including the `interactive` extra metadata and CLI/assets. |
| `release-manifest.json` | `hypertest.interactive-release/v1`, intended tag/version, full source commit, tag-verification status, HTTPS download URLs, profile/host limits, wheel filename/size/SHA-256. |
| `INSTALL.md` | Exact release commands with the built wheel's literal SHA-256 and size, plus authorization and host boundaries. |
| `SHA256SUMS` | SHA-256 of the wheel, manifest and installation instructions. |

A planned-tag manifest is a candidate build, not a published release. On an
explicitly authorized `mcp-v*` tag push,
[the release workflow](../.github/workflows/release-interactive.yml) requires the
tag at the exact source commit, builds its assets, installs the wheel and its
interactive dependencies in a fresh venv, and imports the CLI/resources from
outside the repository. It checks `setup`/`doctor` help and the executable entry
point before creating a GitHub release. Existing releases are not overwritten.
Record the actual release URL and wheel digest after publication; only then mark
that distribution available in installation guidance. No PyPI publication or
universal Agent/operating-system support is implied by these assets.
