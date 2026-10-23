# SSH fixed-diagnostic fixture (prepared, not deployed or accepted)

This is an explicit loopback fixture for `SSH_FIXED_DIAGNOSTICS_V1`. It does not
test a real staging SUT, run a remote test framework or enable general SSH. The
project framework remains in the Cloud workspace. No Local configuration,
production sshd, administrator keys, VPN or firewall is changed by these files.

The remote helper closure is `hypertest/__init__.py`, `cloud/__init__.py`,
`cloud/errors.py`, `cloud/ssh_profile.py`, `cloud/ssh_tickets.py`, and
`cloud/ssh_remote.py`. Install these exact frozen bytes root-owned and readonly
under the dedicated fixture source root. It needs stdlib plus Ed25519 support in
`cryptography`; it does not import Pydantic, SQLAlchemy, asyncpg, SDK or models.
The acceptance host has Python 3.13.5 / cryptography 43; these are independently
frozen fixture dependencies, not the Cloud wheel's Python/dependency baseline.

The explicitly prepared fixture root is
`/var/tmp/hypertest-cloud-ssh-fixture-20261023-r25`, user
`hypertest-ssh-fixture` UID996/GID987, `/run/user/996/bus`, and its own bounded
`user-996.slice`. The user manager must be running and have memory/pids cgroup
delegation. Never invoke a system-level systemd unit or grant this SSH account
general sudo. `SystemdUserManager` uses only `/usr/bin/systemd-run --user` and
`/usr/bin/systemctl --user`.

The fixed remote prefix is `/opt/hypertest-ssh`. Before creating it, reject any
existing path: do not merge or overwrite unknown host state. An independently
reviewed fixture namespace mapping is also possible, but the sshd helper **and
the separate systemd user manager** must see identical fixed paths. Bind mounting
only sshd's namespace does not expose scripts to user-manager workloads.

Required layout, prepared by the authorized operator only:

| Path | Ownership/mode and contents |
| --- | --- |
| `/opt/hypertest-ssh/bin/control` | root 0555, rendered `ssh-control.in`, fixed helper source/state/UID |
| `/opt/hypertest-ssh/bin/unit` | root 0555, rendered `ssh-unit.in`; preserves only validated InvocationID before env-i |
| `/opt/hypertest-ssh/catalog.json` | root 0444, rendered public environment/catalog |
| `/opt/hypertest-ssh/actions/read-deployment` | root 0555, exact `ssh_fixture_read_deployment.py` bytes |
| `/opt/hypertest-ssh/fixture/deployment.json` | root 0444, `{"fixture":"hypertest-ssh-readonly-v1","build_id":"hypertest-ssh-fixture-r25"}` |
| fixture state root | UID996/GID987 0700, new persistent operation records, never removed while unknown |
| host/client/signing private keys | host-private 0600 within root 0700 `keys`, never copied to helper/source/catalog |

`render_ssh_fixture_catalog.py` accepts **public** host-key and authority-key files,
the frozen helper/action source paths, an explicit port, and a new output path.
The existing 32-byte `code/ssh-authority-public.raw` can be used directly; it is
converted to the full OpenSSH Ed25519 public key without reading/recreating its
private identity. It writes one new 0444 file with O_EXCL and never launches SSH.
The inner `catalog_sha256` is over `SshProfile.catalog_document()`, not the outer
environment JSON file hash. Keep both identities distinct.

Render `ssh-fixture-sshd_config.in` with a new unused loopback port, the synthetic
host key and a public authorized_keys file containing only the synthetic client
public key. Use `restrict,command="/opt/hypertest-ssh/bin/control"` plus the explicit
ForceCommand/forwarding restrictions in the config. The authorized_keys path and
its parent must be readable/traversable by UID996; do not point it into root0700
`keys`. The dedicated account must be eligible for public-key login; do not
unlock another user's account or touch the production sshd configuration.
If this newly created fixture account is locked and UsePAM=no rejects it, the
operator may set an unusable password marker `*` for only this new account;
password authentication remains disabled. No existing account may be changed.
Render the standalone service template to a new `/run/systemd/system` unit; it
contains no Install section. Its root sshd parent only authenticates/drops to the
fixture user. Workloads are non-root user-manager units, separate from sshd's
cgroup and governed by the pre-provisioned user slice and per-operation limits.

Before any real invoke, verify effective fixed paths, readonly action/source
bytes, actual user-manager cgroup limits, helper digest, and the worker's **new**
pinned `/usr/bin/ssh` executable digest. The prior worker rootfs has no SSH client
and must remain unchanged. A host ssh binary is not an automatic fallback.

The first action is a fixed no-argument readonly deployment diagnostic. Its
success demonstrates only that diagnostic, SSH authentication, bounded output,
durable operation identity/query, and separately observed remote stopping.
Lost acknowledgements, missing units, expiry, crash gaps, stale generations,
revocation, output limits and descendant cleanup require explicit negative
acceptance. SSH disconnect/local kill/elapsed TTL alone never proves remote stop.

Successful units use RemainAfterExit until QUERY observes matching boot ID,
InvocationID, durable command result and empty cgroup. It then acknowledges an
exact unit stop, checks post-stop inactive/empty, writes durable stop-proof.json,
and seals terminal bytes. No `--collect` is used. A transient unit may be GC'ed
after an acknowledged stop: that branch requires the original identity's
successful stop job plus observation that its original cgroup is empty/removed;
unit NOT_FOUND alone never supplies proof. The durable stop proof also closes
the crash gap before terminal.json. SSH operations stay separate from submission
receipts. Never replay START after UNKNOWN/NOT_FOUND or replace its key.

XBlock staging SSH/log-server work is Local-only via the user's Mac Workbench
access; dev166 private-chain work is also Local-only. No local env_password or
administrator credential is read/copied here. Staging Web/API-only Cloud work
has separate authorization. This generic fixture does not connect either site,
change their VPN/routes/forwarding, or create an XBlock management task.

The authority signing key is independent of the SSH login key and wrapping/model
keys. Tickets are host-only, action-bound and short lived; generation alone is not
authority. A valid already-sent ticket may arrive after DB fencing within its
bounded expiry window. STOP/hard deadline and subsequent observation close that
window; do not claim immediate remote revocation. Once the SSH credential is
revoked, no new transport may use its retained private bytes, including cleanup.

Cleanup is explicit: stop only the named fixture sshd/user workloads, confirm all
original operations terminal and cgroups empty, preserve private evidence and
unknown state, then remove only the exact new fixture unit/user/prefix that this
acceptance created. Do not delete shared source, old attempts or production state.
