#!/usr/bin/env python3
"""Create fixed-digest install commands from built Local bundles; never publish.

Review and deliver these commands through a trusted channel. A checksum file
downloaded beside an executable is not a substitute for that trust decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import zipfile
from pathlib import Path

REPOSITORY = "https://github.com/ZhangLiangchen/hypertest-one"


def command(record: dict, host: str = "codex", *, enable_hooks: bool = False) -> str:
    if host not in {"codex", "claude-code", "deepseek-harness"}:
        raise ValueError("Select one actual Local host")
    bootstrap_url = f"{REPOSITORY}/releases/download/{record['release_tag']}/install-local-release.py"
    code = ("import hashlib,sys,urllib.request; "
            f"r=urllib.request.urlopen({bootstrap_url!r},timeout=45); "
            "u=urllib.parse.urlsplit(r.url); "
            "(u.scheme=='https' and u.hostname in {'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}) or sys.exit('BLOCKED: bootstrap redirect'); "
            "b=r.read(1048577); r.close(); "
            f"(len(b)<=1048576 and hashlib.sha256(b).hexdigest()=={record['bootstrap_sha256']!r}) or sys.exit('BLOCKED: bootstrap digest'); "
            "exec(compile(b,'<verified HyperTest Local bootstrap>','exec'))")
    args = [f"python{record['python']}", "-I", "-c", code, "--bundle-url", record["bundle_url"],
            "--trusted-bundle-sha256", record["bundle_sha256"],
            "--trusted-manifest-sha256", record["manifest_sha256"],
            "--source-commit", record["source_commit"], "--release-tag", record["release_tag"],
            "--install-root", f"/ABS/PRIVATE/hypertest-local-{host}", "--harness", host,
            "--host-config", "/ABS/SELECTED/host-config", "--client-config", "/ABS/PRIVATE/authorized-client.json"]
    if record["distribution_state"] == "CANDIDATE":
        args.append("--allow-candidate")
    if enable_hooks:
        accepted = record.get("hosts", {}).get(host, {})
        if (accepted.get("automatic_trigger") != "ACCEPTED" or not accepted.get("versions")):
            raise ValueError("Do not generate an automatic Hook command without actual host acceptance")
        args += ["--enable-hooks", "--workspace", "/ABS/SELECTED/test-workspace",
                 "--harness-version", accepted["versions"][0]]
        if host in {"claude-code", "codex"}:
            args += ["--hook-config", "/ABS/SELECTED/host-hook-config"]
    if host == "deepseek-harness":
        args += ["--dsh-home", "/ABS/SELECTED/dsh-home", "--profile", "EXISTING_PROFILE"]
        if enable_hooks:
            args += ["--event-bridge", "native-root"]
    return shlex.join(args)


def release_record(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > 450 * 1024 * 1024:
        raise ValueError("Bounded regular Local bundle required")
    with zipfile.ZipFile(path) as bundle:
        raw = bundle.read("local-release-manifest.json")
        manifest = json.loads(raw)
        bootstrap = bundle.read("install-local-release.py")
        if (manifest["schema_version"] != "hypertest.local-release/v1"
                or manifest["source_repository"] != REPOSITORY
                or manifest["assets"]["install-local-release.py"]["sha256"] != hashlib.sha256(bootstrap).hexdigest()
                or manifest["distribution_state"] not in {"CANDIDATE", "RELEASE"}):
            raise ValueError("Invalid Local manifest/bootstrap identity")
    tag, commit = manifest["release_tag"], manifest["source_commit"]
    if (re.fullmatch(r"local-v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", tag) is None
            or re.fullmatch(r"[a-f0-9]{40}", commit) is None):
        raise ValueError("Fixed Local tag and commit required")
    target = manifest["target"]
    machine = {"aarch64": "arm64"}.get(target["machine"], target["machine"])
    target_id = f"{target['system'].lower()}-{machine}-py{target['python'].replace('.', '')}"
    if (target["system"] not in {"Darwin", "Linux"} or machine not in {"arm64", "x86_64"}
            or target["python"] not in {"3.12", "3.13"}
            or path.name != f"hypertest-{tag}-{target_id}.zip"):
        raise ValueError("Target archive name differs from manifest")
    return {"target_id": target_id, "python": target["python"], "release_tag": tag, "source_commit": commit,
            "distribution_state": manifest["distribution_state"], "hosts": manifest["hosts"],
            "bootstrap_sha256": hashlib.sha256(bootstrap).hexdigest(),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "bundle_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bundle_url": f"{REPOSITORY}/releases/download/{tag}/{path.name}"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = [release_record(path) for path in sorted(args.bundles.rglob("hypertest-local-v*.zip"))]
    if (not records or len({row["target_id"] for row in records}) != len(records)
            or len({(row["release_tag"], row["source_commit"], row["bootstrap_sha256"]) for row in records}) != 1):
        parser.error("Bundles must share one source/tag/bootstrap and have unique targets")
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = {"schema_version": "hypertest.local-install-catalog/v1", "publication": "NOT_ASSERTED", "targets": records}
    (args.output / "local-install-catalog.json").write_text(json.dumps(catalog, sort_keys=True, indent=2) + "\n")
    notes = [f"# HyperTest Local {records[0]['release_tag']}", "", f"Source: `{records[0]['source_commit']}`.", "",
             "Review these fixed digests through your trusted release channel before executing. Replace only the absolute private paths and selected host. Existing authorized task:sync configuration is required; no token belongs in this command.", "",
             "Host MCP, automatic triggers and real sync acceptance are listed per exact target below. Installation itself does not establish acceptance on your machine. Hooks remain off unless explicitly selected with accepted host version evidence.", ""]
    for record in records:
        notes += [f"## {record['target_id']} ({record['distribution_state']})", "", "```json",
                  json.dumps(record["hosts"], indent=2), "```", "",
                  f"Bootstrap SHA-256: `{record['bootstrap_sha256']}`.",
                  f"Manifest SHA-256: `{record['manifest_sha256']}`.",
                  f"Bundle SHA-256: `{record['bundle_sha256']}`.", ""]
        for host in ("codex", "claude-code", "deepseek-harness"):
            notes += [f"{host}:", "", "```sh", command(record, host), "```", ""]
            if record["hosts"].get(host, {}).get("automatic_trigger") == "ACCEPTED":
                notes += ["With explicitly selected workspace and the accepted Hook version:", "", "```sh",
                          command(record, host, enable_hooks=True), "```", ""]
    (args.output / "LOCAL_INSTALL.md").write_text("\n".join(notes))
    print(json.dumps({"targets": len(records), "publication": "NOT_ASSERTED"}))


if __name__ == "__main__":
    main()
