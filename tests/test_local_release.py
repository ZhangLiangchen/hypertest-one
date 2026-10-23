"""Fixed-source Local release identity and offline bootstrap rejection boundaries.

No test launches a model, SUT, platform mutation or legacy credential setup.
Execution belongs to the authorized remote test host.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(filename):
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_script("build-local-release.py")
bootstrap = load_script("install-local-release.py")
dependencies = load_script("prepare-local-dependencies.py")
commands = load_script("local-release-commands.py")
release_plan = load_script("plan-local-release.py")
freeze = load_script("freeze-local-release-source.py")
COMMIT = "a" * 40
TAG = "local-v0.1.0-beta.1"


def dependency_wheel(name, version):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as wheel:
        wheel.writestr(f"{name}-{version}.dist-info/METADATA",
                       f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n")
    return content.getvalue()


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "source"
    for name in builder.REQUIRED | {"hypertest/local_sync/__init__.py", "hypertest/sync_core/__init__.py",
                                    "hypertest/interactive_client/__init__.py"}:
        path = source / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('"""Fixed source fixture, never executed."""\n')
    for name in ("session-sync.config.example.json", "mcp.example.json"):
        path = source / "src/hypertest/interactive_client/assets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    forbidden = source / "src/hypertest/cloud/__main__.py"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("raise RuntimeError('must not ship')\n")
    for name in builder.SOURCE_BOUND_FILES:
        path = source / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixed release source fixture\n")
    return source


@pytest.fixture
def dependency_lock(tmp_path):
    wheelhouse = tmp_path / "dependencies"
    wheelhouse.mkdir()
    rows = []
    for name, version in (("pydantic", "2.12.0"), ("httpx", "0.28.1"),
                          ("jsonschema", "4.25.0"), ("mcp", "1.28.0")):
        raw = dependency_wheel(name, version)
        filename = f"{name}-{version}-py3-none-any.whl"
        (wheelhouse / filename).write_bytes(raw)
        rows.append({"filename": filename, "name": name, "version": version,
                     "sha256": builder.sha256(raw), "origin_url": "https://files.pythonhosted.org/packages/fixed/" + filename})
    lock = {"schema_version": builder.LOCK_SCHEMA, "wheels": rows}
    path = tmp_path / "dependencies.lock.json"
    path.write_bytes(builder.encoded(lock))
    return path, wheelhouse, lock


@pytest.fixture
def bundle(tmp_path, source, dependency_lock):
    directory = tmp_path / "bundle"
    directory.mkdir()
    _, wheelhouse, lock = dependency_lock
    wheel_name, raw = builder.make_local_wheel(source, "0.1.0b1", COMMIT,
                                               ["pydantic==2.12.0"], 1_700_000_000)
    assets = {row["filename"]: (wheelhouse / row["filename"]).read_bytes() for row in lock["wheels"]}
    assets.update({wheel_name: raw, "install-local-release.py": b"# verified before execution\n",
                   "dependencies.lock.json": builder.encoded(lock), "requirements.lock": b"# fixture pins\n",
                   "INSTALL.md": b"Candidate. NOT_ACCEPTED.\n"})
    manifest = {"schema_version": bootstrap.SCHEMA, "release_tag": TAG, "version": "0.1.0b1",
        "source_commit": COMMIT, "source_repository": builder.REPOSITORY,
        "distribution_state": "CANDIDATE", "publication": "NOT_ASSERTED", "wheel": wheel_name,
        "compatibility": {"task_profile": "codex-session-task-sync/v1alpha1", "snapshot": "hypertest.sync-snapshot/v1"},
        "target": {"system": platform.system(), "machine": platform.machine(),
                   "python": f"{sys.version_info.major}.{sys.version_info.minor}", "acceptance": "NOT_ACCEPTED"},
        "hosts": {host: {"native_acceptance": "NOT_ACCEPTED"} for host in bootstrap.HOSTS},
        "dependencies": lock["wheels"],
        "assets": {name: {"sha256": builder.sha256(data), "size_bytes": len(data)} for name, data in assets.items()}}
    for name, data in assets.items():
        (directory / name).write_bytes(data)
    path = directory / "local-release-manifest.json"
    path.write_bytes(builder.encoded(manifest))
    return path, manifest


def verify(bundle):
    path, _ = bundle
    return bootstrap.verify_release(path, builder.sha256(path.read_bytes()), COMMIT, TAG)


def test_local_wheel_is_reproducible_and_excludes_cloud_and_platform(source):
    name, first = builder.make_local_wheel(source, "0.1.0b1", COMMIT, ["mcp==1.28.0"], 1_700_000_000)
    assert builder.make_local_wheel(source, "0.1.0b1", COMMIT, ["mcp==1.28.0"], 1_700_000_000) == (name, first)
    with zipfile.ZipFile(io.BytesIO(first)) as wheel:
        assert builder.REQUIRED <= set(wheel.namelist())
        assert not any(name.startswith(("hypertest/cloud/", "hypertest/application/", "hypertest/domain/")) for name in wheel.namelist())
        assert builder.wheel_metadata(first) == ("hypertest-local", "0.1.0b1")
        metadata = wheel.read("hypertest_local-0.1.0b1.dist-info/METADATA").decode()
        assert "Requires-Dist: mcp==1.28.0" in metadata
        assert "deepseek-harness-sdk" not in metadata


def test_offline_verification_never_creates_state_or_claims_native_acceptance(bundle):
    path, manifest = bundle
    before = {item.name: item.read_bytes() for item in path.parent.iterdir()}
    observed, assets = verify(bundle)
    assert observed == manifest and observed["publication"] == "NOT_ASSERTED"
    assert all(host["native_acceptance"] == "NOT_ACCEPTED" for host in observed["hosts"].values())
    assert len(assets) == len(manifest["assets"])
    assert before == {item.name: item.read_bytes() for item in path.parent.iterdir()}


def test_manifest_requires_independently_pinned_digest_and_exact_source(bundle):
    path, _ = bundle
    with pytest.raises(ValueError, match="independently trusted"):
        bootstrap.verify_release(path, "0" * 64, COMMIT, TAG)
    with pytest.raises(ValueError, match="identity"):
        bootstrap.verify_release(path, builder.sha256(path.read_bytes()), "b" * 40, TAG)
    with pytest.raises(ValueError, match="fixed Local tag"):
        bootstrap.verify_release(path, builder.sha256(path.read_bytes()), COMMIT, "latest")


def test_tampered_payload_and_final_symlink_are_rejected(bundle, tmp_path):
    path, manifest = bundle
    asset = path.parent / "INSTALL.md"
    original = asset.read_bytes()
    asset.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify(bundle)
    asset.unlink()
    outside = tmp_path / "outside.md"
    outside.write_bytes(original)
    asset.symlink_to(outside)
    with pytest.raises(OSError):
        verify(bundle)
    assert manifest["assets"]["INSTALL.md"]["sha256"] == builder.sha256(original)


def test_manifest_path_escape_and_unlocked_wheel_rejected_even_with_new_digest(bundle):
    path, manifest = bundle
    manifest["assets"]["../private-token"] = {"sha256": "0" * 64, "size_bytes": 0}
    path.write_bytes(builder.encoded(manifest))
    with pytest.raises(ValueError, match="asset name"):
        verify(bundle)
    del manifest["assets"]["../private-token"]
    extra = "unlocked-1.0-py3-none-any.whl"
    (path.parent / extra).write_bytes(b"unexpected")
    manifest["assets"][extra] = {"sha256": builder.sha256(b"unexpected"), "size_bytes": 10}
    path.write_bytes(builder.encoded(manifest))
    with pytest.raises(ValueError, match="unlocked wheel"):
        verify(bundle)


def test_lock_requires_exact_hash_identity_https_origin_and_all_direct_dependencies(dependency_lock):
    path, wheelhouse, lock = dependency_lock
    assert builder.locked_dependencies(path, wheelhouse)[0] == lock
    lock["wheels"][0]["origin_url"] = "https://user:secret@packages.invalid/wheel.whl"
    path.write_bytes(builder.encoded(lock))
    with pytest.raises(ValueError, match="non-secret fixed HTTPS"):
        builder.locked_dependencies(path, wheelhouse)
    lock["wheels"][0]["origin_url"] = "https://packages.invalid/fixed.whl"
    lock["wheels"][0]["sha256"] = "0" * 64
    path.write_bytes(builder.encoded(lock))
    with pytest.raises(ValueError, match="hash/identity"):
        builder.locked_dependencies(path, wheelhouse)
    lock["wheels"] = lock["wheels"][1:]
    path.write_bytes(builder.encoded(lock))
    with pytest.raises(ValueError, match="direct dependencies"):
        builder.locked_dependencies(path, wheelhouse)


def test_source_constraints_cannot_be_silently_downgraded(dependency_lock):
    _, _, lock = dependency_lock
    project = {"dependencies": ["pydantic>=2.10,<3.0"], "optional-dependencies": {"interactive": [
        "httpx>=0.28,<1.0", "jsonschema>=4.20,<5", "mcp>=1.28,<2"]}}
    assert "mcp==1.28.0" in builder.validate_source_requirements(project, lock)
    lock["wheels"][0]["version"] = "1.10.0"
    with pytest.raises(ValueError, match="outside"):
        builder.validate_source_requirements(project, lock)


def test_candidate_and_missing_authorization_block_before_install_mutation(bundle, tmp_path, monkeypatch):
    path, manifest = bundle
    observed, assets = verify(bundle)
    args = argparse.Namespace(allow_candidate=False, harness="codex", client_config=tmp_path / "missing.json",
        host_config=tmp_path / "host.toml", install_root=tmp_path / "installation")
    with pytest.raises(ValueError, match="NOT_ACCEPTED"):
        bootstrap.install_release(args, observed, assets)
    args.allow_candidate = True
    monkeypatch.setattr(bootstrap.venv, "EnvBuilder", lambda **kwargs: pytest.fail("must not create a venv without authorization"))
    with pytest.raises(FileNotFoundError):
        bootstrap.install_release(args, observed, assets)
    assert not args.install_root.exists() and not args.host_config.exists()
    assert manifest["assets"] == observed["assets"] and path.exists()


@pytest.fixture
def git_repository(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Release identity tests require git on the remote build host")
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "tracked").write_text("source\n")
    subprocess.run(["git", "-C", str(root), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fixed source"], check=True)
    return root, builder.git(root, "rev-parse", "HEAD")


def test_release_identity_requires_clean_fixed_commit_and_preserves_old_line(git_repository):
    root, commit = git_repository
    assert builder.release_identity(root, TAG, commit, False) == (commit, "0.1.0b1", "PLANNED")
    with pytest.raises(ValueError, match="existing tag"):
        builder.release_identity(root, TAG, commit, True)
    with pytest.raises(ValueError, match="full fixed commit"):
        builder.release_identity(root, TAG, "main", False)
    with pytest.raises(ValueError, match="Expected local-v"):
        builder.release_identity(root, "mcp-v0.1.0", commit, False)
    (root / "untracked").write_text("not released")
    with pytest.raises(ValueError, match="clean checkout"):
        builder.release_identity(root, TAG, commit, False)


def test_local_tag_must_point_at_exact_exported_commit(git_repository):
    root, commit = git_repository
    subprocess.run(["git", "-C", str(root), "tag", TAG, commit], check=True)
    assert builder.release_identity(root, TAG, None, True)[2] == "VERIFIED"
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                    "commit", "--allow-empty", "-qm", "different source"], check=True)
    newer = builder.git(root, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="another source"):
        builder.release_identity(root, TAG, newer, True)


def zipped_bundle(bundle):
    path, _ = bundle
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        for asset in path.parent.iterdir():
            archive.writestr(asset.name, asset.read_bytes())
    return content.getvalue()


def mock_download(monkeypatch, raw):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith(builder.REPOSITORY + "/releases/download/")
            assert timeout == 45
            return io.BytesIO(raw)
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(bootstrap, "target_id", lambda: "linux-x86_64-py312")


def test_https_target_bundle_is_verified_before_offline_asset_validation(bundle, tmp_path, monkeypatch):
    raw = zipped_bundle(bundle)
    mock_download(monkeypatch, raw)
    destination = tmp_path / "download"
    destination.mkdir()
    url = f"{builder.REPOSITORY}/releases/download/{TAG}/hypertest-{TAG}-linux-x86_64-py312.zip"
    path = bootstrap.download_bundle(url, builder.sha256(raw), TAG, destination)
    original, _ = bundle
    manifest, _ = bootstrap.verify_release(path, builder.sha256(original.read_bytes()), COMMIT, TAG)
    assert manifest["source_commit"] == COMMIT


@pytest.mark.parametrize("wrong_url", ["http://github.com/file.zip", "https://other.invalid/release.zip",
                                      "https://github.com/ZhangLiangchen/hypertest-one/releases/latest/download/file.zip"])
def test_online_installer_rejects_nonfixed_or_foreign_urls_before_network(wrong_url, tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "target_id", lambda: "linux-x86_64-py312")
    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", lambda *args: pytest.fail("must not download"))
    with pytest.raises(ValueError, match="exact selected"):
        bootstrap.download_bundle(wrong_url, "a" * 64, TAG, tmp_path)


def test_wrong_online_digest_does_not_extract_assets(bundle, tmp_path, monkeypatch):
    mock_download(monkeypatch, zipped_bundle(bundle))
    destination = tmp_path / "download"
    destination.mkdir()
    url = f"{builder.REPOSITORY}/releases/download/{TAG}/hypertest-{TAG}-linux-x86_64-py312.zip"
    with pytest.raises(ValueError, match="independently trusted"):
        bootstrap.download_bundle(url, "0" * 64, TAG, destination)
    assert list(destination.iterdir()) == []


def test_https_redirect_cannot_leave_github_release_channel():
    handler = bootstrap.HTTPSReleaseRedirect()
    with pytest.raises(ValueError, match="trusted HTTPS"):
        handler.redirect_request(None, None, 302, "redirect", {}, "http://github.com/payload")
    with pytest.raises(ValueError, match="trusted HTTPS"):
        handler.redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid/payload")


def test_pinned_archive_cannot_write_outside_download_directory(bundle, tmp_path, monkeypatch):
    original = zipped_bundle(bundle)
    content = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(content, "w") as archive:
        for row in source.infolist():
            archive.writestr(row, source.read(row))
        archive.writestr("../outside", b"no")
    raw = content.getvalue()
    mock_download(monkeypatch, raw)
    destination = tmp_path / "download"
    destination.mkdir()
    url = f"{builder.REPOSITORY}/releases/download/{TAG}/hypertest-{TAG}-linux-x86_64-py312.zip"
    with pytest.raises(ValueError, match="non-flat"):
        bootstrap.download_bundle(url, builder.sha256(raw), TAG, destination)
    assert not (tmp_path / "outside").exists()


def acceptance_evidence(source_digest, target):
    return {"schema_version": "hypertest.local-host-acceptance/v1", "local_source_sha256": source_digest,
        "release_tag": TAG, "target": target, "hosts": {host: {"versions": ["1.2.3"],
            "native_acceptance": "ACCEPTED", "mcp": "ACCEPTED", "automatic_trigger": "ACCEPTED",
            "sync_proof": "ACK_AND_FIXED_VERSION_FULL_READBACK", "evidence_refs": ["docs/acceptance-fixture.md"]}
            for host in bootstrap.HOSTS}}


def test_acceptance_binds_exact_source_target_and_real_sync_proof(tmp_path):
    target = {"system": "Darwin", "machine": "arm64", "python": "3.13"}
    source_digest = "b" * 64
    body = acceptance_evidence(source_digest, target)
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(body))
    observed, raw = builder.accepted_hosts(path, source_digest, TAG, target)
    assert observed == body["hosts"] and raw == path.read_bytes()
    with pytest.raises(ValueError, match="exact Local source"):
        builder.accepted_hosts(path, "c" * 64, TAG, target)
    with pytest.raises(ValueError, match="exact Local source"):
        builder.accepted_hosts(path, source_digest, TAG, {**target, "python": "3.12"})
    body["hosts"]["codex"]["sync_proof"] = "CONFIG_WRITTEN"
    path.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="fixed-version sync proof"):
        builder.accepted_hosts(path, source_digest, TAG, target)


def test_missing_acceptance_retains_independent_unaccepted_states():
    hosts, raw = builder.accepted_hosts(None, "a" * 64, TAG, {})
    assert raw is None
    assert all(row == {"native_acceptance": "NOT_ACCEPTED", "mcp": "NOT_ACCEPTED",
                       "automatic_trigger": "NOT_ACCEPTED"} for row in hosts.values())


def test_install_command_pins_bootstrap_manifest_bundle_tag_and_commit():
    record = {"release_tag": TAG, "source_commit": COMMIT, "bootstrap_sha256": "b" * 64,
              "manifest_sha256": "c" * 64, "bundle_sha256": "d" * 64, "python": "3.13",
              "bundle_url": f"{builder.REPOSITORY}/releases/download/{TAG}/fixed.zip", "distribution_state": "CANDIDATE"}
    command = commands.command(record, "deepseek-harness")
    assert command.startswith("python3.13 -I -c ")
    assert all(value in command for value in (TAG, COMMIT, "b" * 64, "c" * 64, "d" * 64))
    assert "--allow-candidate" in command and "--dsh-home" in command and "--profile" in command
    assert "latest" not in command and "curl" not in command and "Operator" not in command
    record["distribution_state"] = "RELEASE"
    assert "--allow-candidate" not in commands.command(record)


def test_reviewed_dependency_catalog_covers_two_python_minors_and_pinned_origins():
    path = ROOT / "scripts/local-release-dependencies.json"
    rows = dependencies.catalog_rows(path)
    assert {row["name"] for row in rows} >= builder.DIRECT_DEPENDENCIES
    assert any("cp313" in wheel["filename"] for row in rows for wheel in row["wheels"])
    assert any("cp312" in wheel["filename"] for row in rows for wheel in row["wheels"])
    assert not any(row["name"].startswith("deepseek-harness") for row in rows)


def test_selected_dependency_lock_rejects_unreviewed_extra_or_changed_bytes(dependency_lock):
    _, wheelhouse, lock = dependency_lock
    rows = [{"name": row["name"], "version": row["version"], "wheels": [{key: row[key]
             for key in ("filename", "sha256", "origin_url")}]} for row in lock["wheels"]]
    assert dependencies.selected_lock(rows, wheelhouse) == lock
    (wheelhouse / "unexpected.whl").write_bytes(b"unreviewed")
    with pytest.raises(ValueError, match="Unreviewed"):
        dependencies.selected_lock(rows, wheelhouse)
    (wheelhouse / "unexpected.whl").unlink()
    (wheelhouse / rows[0]["wheels"][0]["filename"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="reviewed origin/hash"):
        dependencies.selected_lock(rows, wheelhouse)


def test_automatic_install_requires_artifact_policy_before_any_install_mutation(bundle, tmp_path):
    observed, assets = verify(bundle)
    args = argparse.Namespace(allow_candidate=True, harness="codex", client_config=tmp_path / "client.json",
        host_config=tmp_path / "host.toml", install_root=tmp_path / "installation", enable_hooks=True,
        workspace=None, artifact_source=None)
    with pytest.raises(ValueError, match="explicitly selected workspace"):
        bootstrap.install_release(args, observed, assets)
    assert not args.install_root.exists()


def test_automatic_install_command_exists_only_for_actual_accepted_host_versions():
    record = {"release_tag": "local-v0.1.0", "source_commit": COMMIT, "bootstrap_sha256": "b" * 64,
        "manifest_sha256": "c" * 64, "bundle_sha256": "d" * 64, "python": "3.13",
        "bundle_url": builder.REPOSITORY + "/releases/download/local-v0.1.0/fixed.zip",
        "distribution_state": "RELEASE", "hosts": {"deepseek-harness": {"automatic_trigger": "NOT_ACCEPTED"}}}
    with pytest.raises(ValueError, match="actual host acceptance"):
        commands.command(record, "deepseek-harness", enable_hooks=True)
    record["hosts"]["deepseek-harness"] = {"automatic_trigger": "ACCEPTED", "versions": ["0.1.5-rc.1"]}
    command = commands.command(record, "deepseek-harness", enable_hooks=True)
    assert "--enable-hooks" in command and "--workspace" in command and "--harness-version 0.1.5-rc.1" in command
    assert "--event-bridge native-root" in command and "--hook-config" not in command


def test_local_source_digest_covers_fixed_deepseek_root_adapter(source):
    before = builder.local_source_digest(source)
    bridge = source / "src/hypertest/local_sync/deepseek_root_bridge.mjs"
    bridge.write_text("// changed root identity guard\n")
    assert builder.local_source_digest(source) != before


@pytest.mark.parametrize("name", ["scripts/local-release-dependencies.json", "pyproject.toml"])
def test_native_acceptance_digest_also_binds_dependency_pins_and_constraints(source, name):
    before = builder.local_source_digest(source)
    path = source / name
    path.write_text(path.read_text() + "# reviewed dependency change requires new acceptance\n")
    assert builder.local_source_digest(source) != before


def test_target_publication_and_evidence_updates_do_not_create_digest_self_reference(source):
    before = builder.local_source_digest(source)
    (source / "scripts/local-release-targets.json").write_text('{"publication":"RELEASE"}\n')
    evidence = source / "docs/local-acceptance/darwin-arm64-py313.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({"local_source_sha256": before, "native_acceptance": "NOT_ACCEPTED"}))
    assert builder.local_source_digest(source) == before


def matching_catalog(lock):
    return {"schema_version": "hypertest.local-dependency-catalog/v1", "python": ["3.12", "3.13"],
        "index_url": "https://pypi.org/simple", "distributions": [{"name": row["name"],
        "version": row["version"], "wheels": [{key: row[key] for key in ("filename", "sha256", "origin_url")}]} for row in lock["wheels"]]}


def test_actual_external_lock_must_match_fixed_source_transitive_pins(dependency_lock, tmp_path):
    _, _, lock = dependency_lock
    raw = dependency_wheel("attrs", "26.1.0")
    row = {"name": "attrs", "version": "26.1.0", "filename": "attrs-26.1.0-py3-none-any.whl",
        "origin_url": "https://files.pythonhosted.org/packages/fixed/attrs-26.1.0-py3-none-any.whl", "sha256": builder.sha256(raw)}
    lock["wheels"].append(row)
    path = tmp_path / "source-catalog.json"
    path.write_text(json.dumps(matching_catalog(lock)))
    builder.validate_catalog_lock(path, lock)
    # This replacement is internally valid and still has all direct deps. It
    # must fail even when native source acceptance itself has not changed.
    replacement = dependency_wheel("attrs", "26.2.0")
    lock["wheels"][-1] = {**row, "version": "26.2.0", "filename": "attrs-26.2.0-py3-none-any.whl",
        "origin_url": "https://files.pythonhosted.org/packages/fixed/attrs-26.2.0-py3-none-any.whl",
        "sha256": builder.sha256(replacement)}
    with pytest.raises(ValueError, match="fixed-source catalog"):
        builder.validate_catalog_lock(path, lock)


@pytest.mark.parametrize("field,value", [("origin_url", "https://different.invalid/same-wheel.whl"),
                                        ("sha256", "0" * 64), ("filename", "other-2.0-py3-none-any.whl")])
def test_matching_versions_cannot_replace_wheel_identity_or_origin(dependency_lock, tmp_path, field, value):
    _, _, lock = dependency_lock
    path = tmp_path / "source-catalog.json"
    path.write_text(json.dumps(matching_catalog(lock)))
    lock["wheels"][0][field] = value
    with pytest.raises(ValueError, match="fixed-source catalog"):
        builder.validate_catalog_lock(path, lock)


def test_formal_release_selects_only_real_accepted_target_not_candidate_os(tmp_path):
    root = tmp_path / "source"
    (root / "scripts").mkdir(parents=True)
    catalog = json.loads((ROOT / "scripts/local-release-targets.json").read_bytes())
    # This negative fixture starts without qualification regardless of which
    # exact targets the repository has subsequently accepted for publication.
    for target in catalog["targets"]:
        target.update(publication="CANDIDATE", acceptance_file=None)
    (root / "scripts/local-release-targets.json").write_text(json.dumps(catalog))
    assert len(release_plan.plan(root, TAG)["include"]) == 2
    with pytest.raises(ValueError, match="No accepted targets"):
        release_plan.plan(root, "local-v0.1.0")
    row = catalog["targets"][1]
    row["publication"] = "RELEASE"
    row["acceptance_file"] = "docs/local-acceptance/darwin-arm64-py313.json"
    (root / "scripts/local-release-targets.json").write_text(json.dumps(catalog))
    path = root / row["acceptance_file"]
    path.parent.mkdir(parents=True)
    evidence = acceptance_evidence("b" * 64, {key: row[key] for key in ("system", "machine", "python")})
    evidence["release_tag"] = "local-v0.1.0"
    path.write_text(json.dumps(evidence))
    selected = release_plan.plan(root, "local-v0.1.0")["include"]
    assert [item["target"] for item in selected] == ["darwin-arm64-py313"]


def test_release_source_allowlist_never_copies_cloud_implementation():
    selected = freeze.approved_paths(ROOT)
    assert "scripts/local-release-targets.json" in selected
    assert "src/hypertest/interactive_client/mcp_server.py" in selected
    assert "tests/test_session_task_mcp.py" in selected
    assert "src/hypertest/local_sync/deepseek_root_bridge.mjs" in selected
    assert "tests/test_local_deepseek_bridge.py" in selected
    assert not any(name.startswith(("src/hypertest/cloud/", "src/hypertest/deepseek_harness/")) for name in selected)
    for name in ("src/hypertest/config.py", "src/hypertest/main.py", "src/hypertest/domain/models.py", "pyproject.toml",
                 ".github/workflows/ci.yml", "web/app/projects/[projectId]/page.tsx"):
        assert name not in selected
