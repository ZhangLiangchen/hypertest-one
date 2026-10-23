"""Host release tooling contracts; no Docker, SDK, model or DB is started."""
from __future__ import annotations

import base64
import importlib.util
import io
import os
import stat
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops/deepseek"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(OPS))
    result = {}
    for name in ("release_files", "build_worker_release", "render_worker_service", "provision_server_credentials"):
        spec = importlib.util.spec_from_file_location(name, OPS / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result[name] = module
    return result


def archive(path, entries):
    with tarfile.open(path, "w") as stream:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o755 if kind == "directory" else 0o644
            if kind == "symlink":
                member.type, member.linkname = tarfile.SYMTYPE, content
                stream.addfile(member)
            elif kind == "directory":
                member.type = tarfile.DIRTYPE
                stream.addfile(member)
            else:
                raw = content.encode()
                member.size = len(raw)
                stream.addfile(member, io.BytesIO(raw))


@pytest.mark.parametrize("entries", [
    [("../escape", "file", "wrong")],
    [("/absolute", "file", "wrong")],
    [("link", "symlink", "/outside"), ("link/escape", "file", "wrong")],
    [("same", "file", "first"), ("same", "file", "second")],
])
def test_archive_refuses_escaping_duplicate_and_link_ancestors_before_write(modules, tmp_path, entries):
    source = tmp_path / "source.tar"
    archive(source, entries)
    target = tmp_path / "rootfs"
    target.mkdir()
    with pytest.raises(ValueError):
        modules["release_files"].extract_image(source, target)
    assert list(target.iterdir()) == []


def test_rootfs_absolute_link_is_retained_only_after_regular_writes(modules, tmp_path, monkeypatch):
    files = modules["release_files"]
    monkeypatch.setattr(files.os, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(files.os, "lchown", lambda *args, **kwargs: None)
    source = tmp_path / "rootfs.tar"
    archive(source, [("usr/bin/tool", "file", "fixed"), ("bin", "symlink", "usr/bin"),
                     ("etc/mtab", "symlink", "/proc/mounts")])
    target = tmp_path / "rootfs"
    target.mkdir()
    files.extract_image(source, target)
    assert (target / "usr/bin/tool").read_text() == "fixed"
    assert os.readlink(target / "etc/mtab") == "/proc/mounts"


def test_render_rejects_real_placeholder_but_preserves_shell_argument_syntax(modules):
    renderer = modules["render_worker_service"]
    assert renderer.render('exec "$@" @PATH@', {"PATH": "/fixed"}) == 'exec "$@" /fixed'
    with pytest.raises(ValueError, match="unresolved"):
        renderer.render("@MISSING@", {})


def test_doctor_observes_only_public_integrity_and_never_starts_worker(modules, tmp_path, monkeypatch):
    files = modules["release_files"]
    renderer = modules["render_worker_service"]
    release = tmp_path / "release"
    release.mkdir()
    files.write_new(release / "release.json", b"fixed")
    target = tmp_path / "units"
    target.mkdir()
    files.write_new(target / "worker.service", b"ExecStart=fixed\n")
    record = {"profile": "hypertest-cloud-service-render/v1", "source_commit": "a" * 40,
        "release_directory": str(release), "release_manifest_sha256": files.digest(release / "release.json"),
        "codex_enabled": False, "files": {"worker.service": files.digest(target / "worker.service")}}
    files.json_new(target / "render.json", record)

    def forbidden(*args, **kwargs):
        raise AssertionError("Static doctor must not inspect credentials or prepare execution")

    monkeypatch.setattr(renderer, "private_env", forbidden)
    monkeypatch.setattr(renderer, "prepare", forbidden)
    observed = renderer.doctor(target)
    assert observed["status"] == "PREPARED"
    assert observed["startup_admission"] == "NOT_RUN"
    assert not any(observed[key] for key in ("sdk_started", "model_started", "database_accessed", "task_claimed"))
    (target / "worker.service").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        renderer.doctor(target)


class TrustedOutput:
    """Only host ownership metadata is synthetic; file writes use tmp_path."""
    def __init__(self, path, *, uid=0, mode=0o700):
        self.path = path
        self.parent = SimpleNamespace(parents=(), stat=lambda: SimpleNamespace(st_uid=uid, st_mode=mode))
        self.name = path.name

    def exists(self):
        return self.path.exists()

    def is_symlink(self):
        return self.path.is_symlink()

    def mkdir(self, **kwargs):
        return self.path.mkdir(**kwargs)

    def __truediv__(self, other):
        return self.path / other


@pytest.mark.parametrize("corruption,reason", [
    ("short_commit", "exact commit"), ("floating_image", "digest-qualified"),
    ("existing_output", "new release"), ("head_changed", "checkout differs"),
    ("dirty_checkout", "dirty checkout"), ("remote_changed", "fetched origin ref"),
    ("remote_traversal", "fetched origin ref"), ("wrong_nss", "997:988"),
    ("writable_parent", "root-owned"),
])
def test_release_refuses_provenance_identity_and_existing_outputs_before_build(modules, tmp_path, monkeypatch, corruption, reason):
    builder = modules["build_worker_release"]
    commit = "a" * 40
    destination = tmp_path / commit
    args = SimpleNamespace(checkout=tmp_path, output=TrustedOutput(destination), commit=commit,
        remote_ref="origin/cloud-release", python_image="python@sha256:" + "b" * 64,
        codex_payload=None, codex_manifest_sha256="")
    if corruption == "short_commit":
        args.commit = "a" * 12
    elif corruption == "floating_image":
        args.python_image = "python:3.12"
    elif corruption == "existing_output":
        destination.mkdir()
        (destination / "retained").write_bytes(b"keep existing release")
    elif corruption == "remote_traversal":
        args.remote_ref = "origin/../other"
    elif corruption == "writable_parent":
        args.output = TrustedOutput(destination, mode=0o777)
    commands = []
    def git_output(command, **kwargs):
        commands.append(command)
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return "c" * 40 if corruption == "head_changed" else commit
        if command[:2] == ["git", "status"]:
            return " M keep-dirty-source.py" if corruption == "dirty_checkout" else ""
        if command == ["git", "rev-parse", "refs/remotes/origin/cloud-release"]:
            return "c" * 40 if corruption == "remote_changed" else commit
        raise AssertionError("Only the three fixed read-only Git metadata queries are permitted")
    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected release must not archive, build, start, access DB or execute a model")
    monkeypatch.setattr(builder, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(builder, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(builder, "regular_directory", lambda path: None)
    monkeypatch.setattr(builder, "output", git_output)
    monkeypatch.setattr(builder, "subprocess", SimpleNamespace(run=forbidden))
    monkeypatch.setattr(builder, "pwd", SimpleNamespace(getpwnam=lambda name: SimpleNamespace(
        pw_uid=998 if corruption == "wrong_nss" else 997, pw_gid=988)))
    with pytest.raises(ValueError, match=reason):
        builder.build(args)
    if corruption == "existing_output":
        assert (destination / "retained").read_bytes() == b"keep existing release"
        assert {p.name for p in destination.iterdir()} == {"retained"}
    else:
        assert not destination.exists()
    assert all(command[0] == "git" for command in commands)


@pytest.mark.parametrize("unsafe", ["PYTHONPATH=/untrusted", "HYPERTEST_CLOUD_SSH_ENABLED=true",
    "HYPERTEST_CLOUD_RUNTIME_ROOT=/tmp/old-validation", "CREDENTIALS_DIRECTORY=/untrusted",
    "HYPERTEST_CLOUD_MODEL=$(read_secret)", "HYPERTEST_CLOUD_ENABLED=true"])
def test_worker_env_cannot_replace_controlled_fields_or_execute_syntax(modules, unsafe):
    renderer = modules["render_worker_service"]
    content = ("HYPERTEST_DATABASE_URL=postgresql+asyncpg://fixture.invalid/current\n"
        "HYPERTEST_CLOUD_ENABLED=true\nHYPERTEST_CLOUD_WORKER_ENABLED=true\n"
        "HYPERTEST_CLOUD_MODEL_REQUEST_COST_MICROUNITS=1\n" + unsafe + "\n")

    class EnvFile:
        def is_absolute(self):
            return True

        def resolve(self, **kwargs):
            return self

        def __str__(self):
            return "/trusted/worker.env"

        def stat(self):
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)

        def read_text(self):
            return content

    with pytest.raises(ValueError, match="controlled field|unsupported syntax"):
        renderer.private_env(EnvFile())


def test_unit_paths_refuse_symlinks_relative_names_and_unescaped_systemd_syntax(modules, tmp_path):
    renderer = modules["render_worker_service"]
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    spaced = tmp_path / "unit path"
    spaced.mkdir()
    assert renderer.safe_path(real) == str(real)
    for path in (Path("relative"), alias, spaced):
        with pytest.raises(ValueError, match="canonical"):
            renderer.safe_path(path)


@pytest.fixture
def rendering(modules, tmp_path, monkeypatch):
    files, renderer = modules["release_files"], modules["render_worker_service"]
    release = tmp_path / ("a" * 40)
    release.mkdir()
    for name in ("source", "rootfs/opt/hypertest-cloud/venv"):
        (release / name).mkdir(parents=True)
    for name in ("source.tar", "rootfs.tar", "venv.tar"):
        files.write_new(release / name, ("synthetic public " + name).encode())
    manifest = {"source_commit": release.name, "source_archive_sha256": files.digest(release / "source.tar"),
        "venv_archive_sha256": files.digest(release / "venv.tar")}
    files.json_new(release / "release.json", manifest)
    release_hash = files.digest(release / "release.json")
    files.json_new(release / "preparation.json", {"release_manifest_sha256": release_hash,
        "rootfs_archive_sha256": files.digest(release / "rootfs.tar")})
    for name in ("worker.env", "wrapping", "model", "resolv.conf"):
        files.write_new(tmp_path / name, b"synthetic path only; not a real credential")
    runtime = SimpleNamespace(uid=997, gid=988, mode=0o700)
    runtime.stat = lambda: SimpleNamespace(st_uid=runtime.uid, st_gid=runtime.gid, st_mode=runtime.mode)
    original_safe_path = renderer.safe_path
    monkeypatch.setattr(renderer, "safe_path", lambda path: "/persistent/runtime" if path is runtime else original_safe_path(path))
    monkeypatch.setattr(renderer, "private_env", lambda path: {})
    args = SimpleNamespace(release=release, release_sha256=release_hash, output=tmp_path / "units",
        env=tmp_path / "worker.env", runtime=runtime, wrapping_key=tmp_path / "wrapping",
        deepseek_key=tmp_path / "model", resolv_conf=tmp_path / "resolv.conf",
        codex_oauth=None, codex_manifest_sha256="")
    return renderer, args, runtime


@pytest.mark.parametrize("field,value", [("uid", 0), ("gid", 999), ("mode", 0o750)])
def test_renderer_rejects_wrong_runtime_identity_before_creating_units(rendering, field, value):
    renderer, args, runtime = rendering
    setattr(runtime, field, value)
    with pytest.raises(ValueError, match="997:988 0700"):
        renderer.prepare(args)
    assert not args.output.exists()


def test_rendered_doctor_uses_same_admission_but_cannot_claim_or_run_models_and_output_is_new_only(rendering):
    renderer, args, _ = rendering
    record = renderer.prepare(args)
    service = (args.output / "hypertest-cloud-worker.service").read_text()
    doctor = (args.output / "hypertest-cloud-worker-doctor.service").read_text()
    assert "@ROOTFS_HOST@" not in service and "@RELEASE_MANIFEST_SHA256@" not in doctor
    assert "ExecStart=/opt/hypertest-cloud/venv/bin/python -m hypertest.cloud\n" in service
    assert "ExecStart=/usr/bin/true\nRuntimeMaxSec=180s\n" in doctor
    assert "ExecStart=/opt/hypertest-cloud/venv/bin/python -m hypertest.cloud\n" not in doctor
    assert "PrivateNetwork=yes" in doctor and "PrivateNetwork=no" not in doctor
    assert next(line for line in service.splitlines() if line.startswith("ExecStartPre=")) == next(
        line for line in doctor.splitlines() if line.startswith("ExecStartPre="))
    assert "BindPaths=/persistent/runtime:/var/lib/hypertest-cloud/runtime" in doctor
    assert "LoadCredential=wrapping-key:" in doctor and "%d/wrapping-key" in doctor
    assert record["startup_admission"] == "NOT_RUN"
    assert record["service_started"] is record["database_accessed"] is record["model_started"] is False
    before = {path.name: path.read_bytes() for path in args.output.iterdir() if path.is_file()}
    with pytest.raises(FileExistsError):
        renderer.prepare(args)
    assert before == {path.name: path.read_bytes() for path in args.output.iterdir() if path.is_file()}
    (args.output / "unexpected.conf").write_text("unlisted configuration")
    with pytest.raises(ValueError, match="fileset"):
        renderer.doctor(args.output)


def test_private_provision_preserves_source_identity_and_permissions_and_never_reuses_leaf(modules, tmp_path, monkeypatch):
    provisioner = modules["provision_server_credentials"]
    wrapping = tmp_path / "source-wrapping"
    wrapping.write_bytes(base64.b64encode(b"x" * 32) + b"\n")
    wrapping.chmod(0o400)
    platform = tmp_path / "source-platform"
    operator = b"synthetic-original-operator-identity-0123456789"
    platform.write_bytes(b"HYPERTEST_CONNECTOR_OPERATOR_KEY=" + operator + b"\n")
    platform.chmod(0o600)
    before = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in (wrapping, platform)}
    ca = b"-----BEGIN CERTIFICATE-----\npublic-fixture-only\n-----END CERTIFICATE-----\n"
    public_ca = SimpleNamespace(is_symlink=lambda: False, is_file=lambda: True,
        stat=lambda: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o444), read_bytes=lambda: ca)
    public_ca.resolve = lambda **kwargs: public_ca
    reads, owners = [], []

    def read_source(path, **kwargs):
        reads.append(path)
        return path.read_bytes()

    monkeypatch.setattr(provisioner, "private_read", read_source)
    monkeypatch.setattr(provisioner, "os", SimpleNamespace(chown=lambda path, uid, gid: owners.append((path.name, uid, gid))))
    monkeypatch.setattr(provisioner, "canonical_directory", lambda path: None)
    destination = tmp_path / "private-copy"
    args = SimpleNamespace(output=TrustedOutput(destination), wrapping_key=wrapping,
        platform_env=platform, public_ca=public_ca, api_uid=999, api_gid=989)
    result = provisioner.provision(args)
    assert (destination / "api-wrapping-key").read_bytes() == before[wrapping][0]
    assert (destination / "web-operator-key").read_bytes() == operator
    assert (destination / "issuer-ca.crt").read_bytes() == ca
    assert owners == [("api-wrapping-key", 999, 989), ("web-operator-key", 1000, 1000), ("issuer-ca.crt", 0, 0)]
    assert stat.S_IMODE((destination / "api-wrapping-key").stat().st_mode) == 0o600
    assert stat.S_IMODE((destination / "web-operator-key").stat().st_mode) == 0o600
    assert all((path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) == original for path, original in before.items())
    assert result["same_wrapping_identity"] and result["same_operator_identity"]
    assert result["source_permissions_changed"] is result["credential_values_emitted"] is result["service_started"] is False
    for name in ("intent.json", "result.json"):
        public = (destination / name).read_bytes()
        assert operator not in public and before[wrapping][0].strip() not in public
    with pytest.raises(ValueError, match="new credential leaf"):
        provisioner.provision(args)
    assert reads == [wrapping, platform]


def test_private_operator_projection_is_exact_and_never_shell_evaluated(modules):
    reader = modules["provision_server_credentials"].operator_from_env
    secret = "synthetic-only-operator-identity-0123456789"
    assert reader(("OTHER=ignored\nHYPERTEST_CONNECTOR_OPERATOR_KEY=" + secret + "\n").encode()) == secret.encode()
    for content in (b"HYPERTEST_CONNECTOR_OPERATOR_KEY=$(execute)\n",
                    (("HYPERTEST_CONNECTOR_OPERATOR_KEY=" + secret + "\n") * 2).encode(), b"OTHER=x\n"):
        with pytest.raises(ValueError):
            reader(content)


def test_fixed_persistent_unit_keeps_namespace_admission_and_credentials_separate():
    template = (OPS / "hypertest-cloud-worker.service.in").read_text()
    assert "User=hypertest-cloud" in template and "RootDirectory=@ROOTFS_HOST@" in template
    for text in ("MemoryMax=2G", "MemorySwapMax=0", "TasksMax=256", "NoNewPrivileges=yes",
                 "CapabilityBoundingSet=\n", "Restart=no", "%d/wrapping-key", "%d/deepseek-key"):
        assert text in template
    assert "[Install]" not in template.split("[Unit]", 1)[1]
    assert "worker_admission" in template
    builder = (OPS / "build_worker_release.py").read_text()
    assert "refs/remotes/" in builder and "!= (997, 988)" in builder
    assert "extract_image(rootfs_archive, rootfs)" in builder
    assert "/tmp/hypertest-cloud-validation" not in builder
