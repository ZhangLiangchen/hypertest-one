"""Real Git fixture coverage for the source trust boundary (no mocked Git)."""
import base64
import hashlib
import json
import os
import subprocess
from uuid import uuid4

import pytest

from hypertest.connector.source import (
    LocalSourceAdapter,
    SourceBundleError,
    canonical,
    materialize,
    validate_origin,
    verify_bundle,
)
from hypertest.harness_bridge.protocol import BridgeError


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "private origin"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Source fixture")
    git(root, "config", "user.email", "source@example.invalid")
    (root / "app.py").write_text("print('pinned')\n")
    (root / "script").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(root / "script", 0o755)
    (root / "docs").mkdir()
    (root / "docs" / "readme").write_text("A real Git tree\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "source")
    (root / "docs" / "readme").write_text("Second commit with parent history\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "source with parent")
    return root


def prepare(repository, tmp_path):
    origin = repository.as_uri()
    adapter = LocalSourceAdapter(tmp_path / "connector", allowed_origins=[origin], allow_local_origin=True)
    payload = {"transfer_id": str(uuid4()), "request_id": str(uuid4()), "project_id": str(uuid4()),
               "node_id": str(uuid4()), "origin": origin, "ref": "main",
               "commit_sha": git(repository, "rev-parse", "HEAD"), "policy_version": "fixture-v1"}
    return adapter, payload, adapter.prepare(payload)


def test_real_git_parentless_bundle_clean_checkout_and_local_install(repository, tmp_path):
    # Dirty and untracked secrets from the user's checkout never cross the boundary.
    (repository / "app.py").write_text("dirty unapproved local edits")
    (repository / ".env").write_text("LOCAL_CREDENTIAL=not-for-upload")
    adapter, request, prepared = prepare(repository, tmp_path)
    content = prepared.bundle_path.read_bytes()
    source = verify_bundle(content, origin=request["origin"], commit_sha=request["commit_sha"])
    assert all(b"not-for-upload" not in raw and b"dirty unapproved" not in raw for _, raw in source.objects.values())
    assert sum(kind == "commit" for kind, _ in source.objects.values()) == 1
    output = materialize(source, tmp_path / "platform" / "accepted")
    assert git(output, "rev-parse", "HEAD") == request["commit_sha"]
    assert git(output, "remote", "get-url", "origin") == request["origin"]
    assert git(output, "status", "--porcelain") == ""
    assert (output / "app.py").read_text() == "print('pinned')\n"
    assert (output / "script").stat().st_mode & 0o111
    workspace_id = uuid4().hex
    install = {**request, "workspace_id": workspace_id, "run_id": str(uuid4()), "create": True,
               "bundle_sha256": prepared.receipt["bundle_sha256"], "root_tree": source.manifest["root_tree"]}
    workspace = adapter.install_workspace(install)
    assert workspace == adapter.root / ".hypertest-agent-sessions" / workspace_id / "repo"
    assert adapter.install_workspace({**install, "create": False}) == workspace
    (workspace / "app.py").write_text("tampered")
    with pytest.raises(BridgeError) as rejected:
        adapter.install_workspace({**install, "create": False})
    assert rejected.value.code == "WORKSPACE_INTEGRITY_REJECTED"
    with pytest.raises(BridgeError) as missing:
        adapter.install_workspace({**install, "workspace_id": uuid4().hex, "create": False})
    assert missing.value.code == "WORKSPACE_UNAVAILABLE"
    assert adapter.prepare(request).receipt == prepared.receipt


def test_local_origin_and_acquisition_allowlist_fail_closed(repository, tmp_path):
    with pytest.raises(SourceBundleError):
        validate_origin(repository.as_uri())
    with pytest.raises(SourceBundleError):
        validate_origin("https://user:password@example.invalid/repo.git")
    adapter, request, _ = prepare(repository, tmp_path)
    unapproved = LocalSourceAdapter(tmp_path / "unapproved", allow_local_origin=True)
    with pytest.raises(SourceBundleError, match="approved"):
        unapproved.prepare(request)
    for value in ["ssh://git@example.invalid/repo.git", "git@example.invalid:team/repo.git", "https://example.invalid/team/repo.git"]:
        assert validate_origin(value) == value


@pytest.mark.parametrize("kind", ["hash", "manifest", "origin", "unrelated", "duplicate", "compressed"])
def test_independent_receiver_rejects_tampering(repository, tmp_path, kind):
    _, request, prepared = prepare(repository, tmp_path)
    wire = json.loads(prepared.bundle_path.read_bytes())
    if kind == "hash":
        wire["objects"][0]["data"] = base64.b64encode(b"tampered").decode()
    elif kind == "manifest":
        wire["manifest"]["files"][0]["path"] = "../../outside"
    elif kind == "origin":
        wire["manifest"]["origin"] = "https://other.invalid/repo"
    elif kind == "unrelated":
        data = b"unrelated credential bytes"
        wire["objects"].append({"oid": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                                "type": "blob", "data": base64.b64encode(data).decode()})
    elif kind == "duplicate":
        wire["objects"].append(wire["objects"][0])
    else:
        wire["compression"] = "gzip"
    with pytest.raises(SourceBundleError):
        verify_bundle(canonical(wire), origin=request["origin"], commit_sha=request["commit_sha"])


@pytest.mark.parametrize("fixture", ["secret", "private_key", "lfs", "submodule", "symlink_escape", "git_symlink", "symlink_safe"])
def test_fixed_tree_prohibited_material_is_rejected_without_filtering(repository, tmp_path, fixture):
    if fixture == "secret":
        (repository / ".env").write_text("SECRET=never-upload")
    elif fixture == "private_key":
        (repository / "credential.txt").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n")
    elif fixture == "lfs":
        (repository / "asset.bin").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "a"*64 + "\nsize 100\n")
    elif fixture == "submodule":
        git(repository, "update-index", "--add", "--cacheinfo", f"160000,{git(repository, 'rev-parse', 'HEAD')},module")
    elif fixture == "symlink_escape":
        (repository / "outside").symlink_to("../../operator-secret")
    elif fixture == "git_symlink":
        (repository / "metadata").symlink_to(".git/config")
    else:
        (repository / "safe-link").symlink_to("docs/readme")
    if fixture != "submodule":
        git(repository, "add", ".")
    git(repository, "commit", "-m", "prohibited fixed input")
    with pytest.raises(SourceBundleError):
        prepare(repository, tmp_path)


def test_source_staging_quota_and_expired_crash_cleanup(tmp_path, monkeypatch):
    import time

    import hypertest.application.source_transfer as transfers
    from hypertest.application.services import ConflictError
    monkeypatch.setattr(transfers,"MAX_STAGING_BYTES",32)
    fd,path=transfers.reserve_staging(20)
    os.close(fd)
    assert path.stat().st_size == 20
    with pytest.raises(ConflictError,match="quota"):
        transfers.reserve_staging(20)
    old=time.time()-transfers.STAGING_RETENTION_SECONDS-1
    os.utime(path,(old,old))
    fd,new=transfers.reserve_staging(20)
    os.close(fd)
    assert not path.exists() and new.exists()
    new.unlink()


def test_prepare_deadline_and_managed_symlink_are_rejected_before_git(repository,tmp_path):
    import time
    adapter,request,_=prepare(repository,tmp_path)
    request={**request,"transfer_id":str(uuid4())}
    with pytest.raises(SourceBundleError,match="expired"):
        adapter.prepare(request,deadline=time.monotonic()-1)
    outside=tmp_path / "outside-acquisition"
    outside.mkdir()
    acquisition=adapter.root / "acquisitions" / request["transfer_id"]
    (acquisition / ".acquisition.lock").unlink()
    acquisition.rmdir()
    acquisition.symlink_to(outside,target_is_directory=True)
    with pytest.raises(SourceBundleError,match="symlink"):
        adapter.prepare(request)
    assert not list(outside.iterdir())


def bounded_wire(files):
    """Produce independent valid Git fixtures at transport resource boundaries."""
    from hypertest.connector.source import FORMAT
    def oid(kind,raw):
        return hashlib.sha1(kind.encode()+b" "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    objects=[]
    entries=[]
    tree=b""
    for path,raw in sorted(files.items()):
        identity=oid("blob",raw)
        tree+=b"100644 "+path.encode()+b"\0"+bytes.fromhex(identity)
        objects.append({"oid":identity,"type":"blob","data":base64.b64encode(raw).decode()})
        entries.append({"path":path,"mode":"100644","oid":identity,"sha256":hashlib.sha256(raw).hexdigest()})
    root=oid("tree",tree)
    commit=b"tree "+root.encode()+b"\nauthor Fixture <fixture@example.invalid> 1 +0000\ncommitter Fixture <fixture@example.invalid> 1 +0000\n\nBounded source fixture\n"
    target=oid("commit",commit)
    objects.extend([{"oid":root,"type":"tree","data":base64.b64encode(tree).decode()},
                    {"oid":target,"type":"commit","data":base64.b64encode(commit).decode()}])
    content=canonical({"format":FORMAT,"manifest":{"origin":"https://fixture.invalid/repo.git","commit_sha":target,
        "root_tree":root,"object_format":"sha1","files":entries},"objects":objects})
    return content,len(tree)+len(commit)


def test_real_object_byte_boundary_allows_24_mib_and_rejects_one_more_byte():
    from hypertest.connector.source import MAX_OBJECT_BYTES
    assert MAX_OBJECT_BYTES == 24*1024*1024
    content,_=bounded_wire({"large.bin":b"a"*MAX_OBJECT_BYTES})
    verified=verify_bundle(content)
    assert len(verified.files) == 1
    content,_=bounded_wire({"large.bin":b"a"*(MAX_OBJECT_BYTES+1)})
    with pytest.raises(SourceBundleError,match="bounds|limits"):
        verify_bundle(content)


def test_total_raw_boundary_includes_commit_and_tree_objects():
    from hypertest.connector.source import MAX_EXPANDED_BYTES, MAX_OBJECT_BYTES
    assert MAX_EXPANDED_BYTES == 32*1024*1024
    _,overhead=bounded_wire({"a.bin":b"a","b.bin":b"b"})
    remainder=MAX_EXPANDED_BYTES-MAX_OBJECT_BYTES-overhead
    content,_=bounded_wire({"a.bin":b"a"*MAX_OBJECT_BYTES,"b.bin":b"b"*remainder})
    verified=verify_bundle(content)
    assert sum(len(raw) for _,raw in verified.objects.values()) == MAX_EXPANDED_BYTES
    content,_=bounded_wire({"a.bin":b"a"*MAX_OBJECT_BYTES,"b.bin":b"b"*(remainder+1)})
    with pytest.raises(SourceBundleError,match="expanded bytes"):
        verify_bundle(content)


def test_bundle_byte_boundary_remains_48_mib_and_rejects_one_more_byte():
    from hypertest.connector.source import MAX_BUNDLE_BYTES
    assert MAX_BUNDLE_BYTES == 48*1024*1024
    content,_=bounded_wire({"app.py":b"print('safe')\n"})
    padded=content+b" "*(MAX_BUNDLE_BYTES-len(content))
    assert verify_bundle(padded).bundle_size == MAX_BUNDLE_BYTES
    with pytest.raises(SourceBundleError,match="bundle size"):
        verify_bundle(padded+b" ")
