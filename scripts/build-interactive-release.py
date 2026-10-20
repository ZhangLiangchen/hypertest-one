#!/usr/bin/env python3
"""Build MCP release assets from an exported, fixed Git commit, never local files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

REPOSITORY = "ZhangLiangchen/hypertest-one"
PROFILE = "hypertest.interactive-mcp/v1alpha1"


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, stderr=subprocess.PIPE
    ).strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install_instructions(manifest: dict) -> str:
    wheel = manifest["wheel"]
    base = manifest["download_base_url"]
    return f"""# HyperTest interactive MCP {manifest['version']}

Source commit: `{manifest['source_commit']}`. Release tag: `{manifest['release_tag']}`.
This file describes a fixed build; a locally built asset is not proof of publication.
Use Python 3.12+ on macOS or Linux. Generic stdio hosts can submit/read and request
CLOUD execution. Current-Agent LOCAL execution additionally requires the controlled
Codex Desktop adapter; registration does not prove the active native session.

Download this exact release wheel over HTTPS; do not install a moving branch,
`latest`, an unverified script, or an unrelated PyPI package:

```sh
mkdir -p "$HOME/.local/share/hypertest/releases/{manifest['release_tag']}"
cd "$HOME/.local/share/hypertest/releases/{manifest['release_tag']}"
curl --fail --show-error --proto '=https' --proto-redir '=https' --location \\
  --output {wheel['filename']} \\
  '{base}/{wheel['filename']}'
python3.12 - <<'PY'
import hashlib
from pathlib import Path
wheel = Path({wheel['filename']!r})
raw = wheel.read_bytes()
assert len(raw) == {wheel['size_bytes']}, 'Wheel size mismatch'
assert hashlib.sha256(raw).hexdigest() == {wheel['sha256']!r}, 'Wheel SHA-256 mismatch'
print('Verified fixed HyperTest wheel')
PY
python3.12 -m venv .venv
.venv/bin/python -m pip install './{wheel['filename']}[interactive]'
.venv/bin/hypertest-interactive --help
```

The wheel SHA-256 is `{wheel['sha256']}`. `release-manifest.json` records its
version, source commit, size, supported hosts and profile. `SHA256SUMS` covers the
wheel, manifest and this file. Compare against the independently selected release;
a checksum downloaded from an untrusted location is not independent authorization.

Next use the Project's **Create test run → My computer → MCP setup** instructions.
The administrator provides the existing device-management Operator key through a
private owned 0600 file or an interactive secret prompt. Keep it out of Agent chat,
MCP arguments, command arguments, generated client snippets and logs. The local
setup command uses existing operator-authorized pairing and registration APIs;
it is not an MCP tool. It stores narrow device/integration credentials locally
and does not grant source acquisition, issue operations or execution implicitly.

Configure the target host using the generated absolute executable/config paths.
Restart or reload that host when required; do not promise tool-catalog hot reload.
Use the setup doctor's HTTPS/profile and file-permission checks before declaring
installation complete. Preserve existing host MCP entries and private journals.
"""


def build(args: argparse.Namespace) -> dict:
    root = Path(git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel"))
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Release builds require a clean Git checkout, including untracked files")
    match = re.fullmatch(r"mcp-v(\d+\.\d+\.\d+)", args.tag)
    if match is None:
        raise ValueError("Release tag must be mcp-vMAJOR.MINOR.PATCH")
    commit = git(root, "rev-parse", "--verify", f"{args.ref or args.tag}^{{commit}}")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("A full fixed Git commit is required")
    try:
        tagged_commit = git(root, "rev-parse", "--verify", f"refs/tags/{args.tag}^{{commit}}")
    except subprocess.CalledProcessError:
        tagged_commit = None
    if tagged_commit is not None and tagged_commit != commit:
        raise ValueError("Release tag points to another source commit")
    if args.require_tag and tagged_commit != commit:
        raise ValueError("Publication requires an existing release tag at the exact source commit")
    epoch = git(root, "show", "-s", "--format=%ct", commit)
    output = args.output.expanduser().absolute()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Release output directory must be absent or empty")
    with tempfile.TemporaryDirectory(prefix="hypertest-mcp-release-") as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / "source.tar"
        subprocess.run(["git", "-C", str(root), "archive", "--format=tar", commit,
                        "--output", str(archive)], check=True)
        source = temporary_path / "source"
        source.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter="data")
        project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
        version = match.group(1)
        if project["name"] != "hypertest-one" or project["version"] != version:
            raise ValueError("Tag version must exactly match the exported pyproject version")
        wheels = temporary_path / "wheels"
        environment = dict(os.environ, SOURCE_DATE_EPOCH=epoch)
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation",
                        "--outdir", str(wheels), str(source)], check=True, env=environment)
        candidates = list(wheels.glob("*.whl"))
        if len(candidates) != 1:
            raise ValueError("Expected exactly one built wheel")
        wheel_path = candidates[0]
        raw = wheel_path.read_bytes()
        with zipfile.ZipFile(wheel_path) as wheel:
            names = set(wheel.namelist())
            required = {"hypertest/interactive_client/__main__.py",
                        "hypertest/interactive_client/mcp_server.py",
                        "hypertest/interactive_client/setup.py",
                        "hypertest/interactive_client/assets/config.example.json",
                        "hypertest/interactive_client/assets/mcp.example.json",
                        "hypertest/interactive_client/assets/hypertest-interactive/SKILL.md"}
            if not required <= names:
                raise ValueError("Wheel is missing MCP entry points or installation assets")
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise ValueError("Expected one wheel metadata record")
            metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))
            if metadata["Name"] != "hypertest-one" or metadata["Version"] != version:
                raise ValueError("Wheel metadata does not match the release")
        base = f"https://github.com/{REPOSITORY}/releases/download/{args.tag}"
        manifest = {"schema_version": "hypertest.interactive-release/v1",
                    "release_tag": args.tag, "version": version, "source_commit": commit,
                    "tag_verification": "verified" if tagged_commit == commit else "planned",
                    "repository": f"https://github.com/{REPOSITORY}",
                    "release_url": f"https://github.com/{REPOSITORY}/releases/tag/{args.tag}",
                    "download_base_url": base, "profile": PROFILE,
                    "requires_python": project["requires-python"],
                    "supported_operating_systems": ["macOS", "Linux"],
                    "generic_stdio_capabilities": ["task:submit", "run:read", "evidence:read", "report:read", "CLOUD"],
                    "local_execution_adapter": "codex-desktop-stdio/v1",
                    "wheel": {"filename": wheel_path.name, "sha256": digest(raw), "size_bytes": len(raw)}}
        assets = {wheel_path.name: raw,
                  "release-manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
                  "INSTALL.md": install_instructions(manifest).encode()}
        assets["SHA256SUMS"] = "".join(f"{digest(data)}  {name}\n" for name, data in sorted(assets.items())).encode()
        output.mkdir(parents=True, exist_ok=True)
        for name, data in assets.items():
            with (output / name).open("xb") as target:
                target.write(data)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Intended release tag; must match exported package version")
    parser.add_argument("--ref", help="Fixed Git ref to export; defaults to --tag")
    parser.add_argument("--require-tag", action="store_true", help="Reject unpublished/planned tag builds")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release build rejected: {error}\n")
    print(json.dumps({"source_commit": manifest["source_commit"], "tag": manifest["release_tag"],
                      "tag_verification": manifest["tag_verification"], "wheel": manifest["wheel"]}))


if __name__ == "__main__":
    main()
