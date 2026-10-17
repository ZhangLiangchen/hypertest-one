# Codex runtime troubleshooting

Validated on 2026-10-17 with Codex CLI 0.159.2. This records environment diagnosis, not a successful live-model acceptance test.

The blockers below describe the previous cloud environment. On the same date,
local macOS and the deployed Debian 13 server independently completed real Codex
CLI 0.163.0 + model + Docker success and failure-diagnosis cycles. Their final
decisions were RELEASE_READY and RELEASE_BLOCKED. See
[first-phase acceptance](FIRST_PHASE_ACCEPTANCE.md) for identities, evidence and
scope; the old cloud errors do not describe current authentication or readiness.

## Structured result transport

The original adapter instructed the Agent to write its final JSON with a tool. That conflicts with Codex's normal read-only tool sandbox. The adapter now uses the official `--output-schema` and `--output-last-message` options: the Agent returns JSON as its final response and the CLI host saves it, while model-generated tools remain read-only. All five supported Mission types carry their complete typed result and Proposal payload schemas, including requirement and risk analysis.

The Codex-specific strict schema embeds the Mission's typed Proposal payload, closes objects, and makes every generated field required. It omits optional operational dictionaries from this provider projection, preserving the provider-independent TMP validator and defaults. A provider schema rejection is an integration/configuration error, not evidence of an authentication failure. See [official non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode#create-structured-outputs-with-a-schema) and [Structured Outputs schema restrictions](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas).

## Observed blockers

1. Normal managed-shell execution fails before model execution with EROFS. File-only syscall tracing identifies writes to the managed Codex runtime: `tmp/arg0`, `state_5.sqlite`, and `installation_id`. The aliases warning is nonfatal; installation ID initialization is fatal.
2. Supported `--ephemeral`, `log_dir`, and `sqlite_home` options relocate sessions/logs/SQLite but do not remove the installation ID requirement. Disabling analytics does not skip it. The official release unconditionally opens `installation_id` with read/write/create, even when it already exists.
3. A narrowly requested file permission was granted but did not make ordinary execution writable. A separately approved command outside that shell sandbox, still using Codex's own read-only sandbox, passed initialization and emitted `thread.started` and `turn.started`. This is a diagnostic result, not a persistent permission change for HyperTest Workers.
4. Model transport then failed. WebSocket requests received proxy CONNECT 403. A supported custom-provider HTTP/SSE probe retained the same ChatGPT login and official endpoint and also could not connect. Unauthenticated HTTPS HEAD probes to both `https://chatgpt.com/` and `https://api.openai.com/v1/models` returned proxy CONNECT 403. This denial occurs before a model response; it does not establish invalid login credentials or insufficient account permissions.

The environment configuration draft reports unrestricted networking, but these actual model-host connections remain denied. Changing the application alone cannot grant network access through that proxy.

## Source confirmation

The exact installed release requires installation ID initialization in [in_process.rs](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/app-server/src/in_process.rs#L445); [installation_id.rs](https://github.com/openai/codex/blob/rust-v0.159.2/codex-rs/core/src/installation_id.rs#L19) opens the runtime file for writing. No independent installation ID path override exists in that release. Ordinary configuration and ephemeral sessions do not address the read-only runtime root.

## Required environment conditions

- A writable Codex runtime directory on the Worker host, provisioned through supported platform permissions or a normal deployment environment.
- Authorized outbound HTTPS access to the selected model service; WebSocket access when that transport is selected. Keep the configured network proxy and TLS verification intact.
- A supported Codex login or API credential configured securely on that host. Do not paste credentials into chat or copy authentication files from the managed environment.
- Shared PostgreSQL, artifacts, and source workspace configuration for API and Worker, plus a working Docker daemon and trusted Runner image.

No authentication file contents or secret values were printed or copied. HOME/CODEX_HOME were not reassigned. Network controls were not bypassed.

## Is another server required?

An additional server is unnecessary if the current platform can supply the runtime permissions and authorized model connectivity above. Those conditions are not established by the current probes. If they cannot be changed, a separate Linux host is a practical alternative for the complete first-stage acceptance workflow.

A reasonable single-operator acceptance host is Ubuntu 24.04, 4 vCPU, 8 GiB RAM and at least 60 GiB SSD, with Docker, Python 3.12 and Node.js 22. A GPU is unnecessary when using a remote model API. These are suggested starting resources, not a measured production capacity guarantee. Hosting API, Web, Worker, PostgreSQL and artifacts together initially avoids introducing unimplemented distributed artifact synchronization.

On that environment, validate a real backend/API repository from PRD and Git through actual Codex proposals, canonical commits, Docker execution, trusted Evidence and final Verdict. Exercise both success and failure diagnosis. Existing provider-fixture tests and real Docker/browser checks remain valid, but do not replace this live-model acceptance.
