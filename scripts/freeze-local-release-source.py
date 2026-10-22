#!/usr/bin/env python3
"""Prepare a reviewable Local-only source branch in a NEW isolated checkout.

Does not commit, tag, push, build, publish or change the shared worktree/index.
The release owner reviews this checkout and its exact path/hash inventory first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

BASE = "5c03e4d90bed69b6420238849cbb3a8bae2f4c42"
BRANCH = "codex/local-mode-release-v0.1.0"
DIRECTORIES = ("src/hypertest/local_sync", "src/hypertest/sync_core")
FILES = (
    "src/hypertest/interactive_client/__main__.py", "src/hypertest/interactive_client/config.py",
    "src/hypertest/interactive_client/ipc.py", "src/hypertest/interactive_client/service.py",
    "scripts/build-local-release.py", "scripts/install-local-release.py", "scripts/prepare-local-dependencies.py",
    "scripts/local-release-commands.py", "scripts/freeze-local-release-source.py", "scripts/local-release-dependencies.json",
    "scripts/plan-local-release.py", "scripts/local-release-targets.json",
    ".github/workflows/local-release.yml", "tests/test_task_sync_core.py",
    "web/lib/local-mode-install.ts", "web/app/projects/[projectId]/local-mode-guide.tsx",
    "web/app/projects/[projectId]/session-tasks.tsx", "web/tests/local-mode-guide.test.cjs",
    "web/tests/session-tasks.test.cjs", "docs/LOCAL_MODE_RELEASE_AND_INSTALLATION.md",
    "docs/LOCAL_MODE_RELEASE_BUILD.md", "docs/LOCAL_MODE_IMPLEMENTATION_STATUS.md",
    "docs/LOCAL_SESSION_SYNC_IMPLEMENTATION_PLAN.md", "docs/LOCAL_RELEASE_SOURCE_FREEZE.md",
    "docs/architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md",
    "docs/architecture/ADR-021_SHARED_TASK_SYNC_CORE.md",
)
FOUNDATIONS = {
    "docs/foundation/HYPERTEST_WHITEPAPER.md": "Local 产品交付增补（ADR-020/021）",
    "docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md": "46. ADR-020 LocalSyncCoordinator 与统一 Local 发行",
    "docs/protocol/TEST_MISSION_PROTOCOL.md": "47. ADR-020 Local Hooks 与显式 MCP 协作",
    "docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md": "52. ADR-020 Local 客户端不变量",
    "AGENTS.md": "Local 实现与独立发行增补",
    "README.md": "HyperTest Local",
    "docs/MVP_STATUS.md": "Local 交付状态",
}
ADDENDUM = """
本源码分支仅交付 Local（ADR-020）与 TaskSyncCore（ADR-021）的 Local 消费方。
统一包包含 MCP、私有客户端与原 journal、协调器、明确产物策略、三个宿主 adapter、
Hooks 入口及安装/诊断/恢复/升级/回退/卸载；不打包新的 Cloud SDK/Worker 或 Memory Gateway。
真实宿主、OS/架构/Python 目标与发行状态以 LOCAL_MODE_IMPLEMENTATION_STATUS.md、
LOCAL_MODE_RELEASE_BUILD.md、各宿主验收记录和确切 release manifest 为准。
源码或安装成功不等于宿主已接受，不自动启用未经验证的 Hooks。

原 ADR-018 全文、TMP §45 与领域 §50 保持本分支基线原文。原 API/profile、task:sync、
Project/actor owner、完整请求、expected_version 与历史语义不变；hypertest_sync_task 不是 PATCH。
同一真实父会话由一个有效 LocalSyncCoordinator 接受 Hook 触发与显式 MCP；子代理只回交父任务。
只在批准的产物策略内读取正式文件，不扫描聊天、推理、原始工具负载或认证目录。
冻结后保留完整请求/key/version；SENT/UNKNOWN/失答及 NOT_FOUND 只 GET 原 key，不自动再次 POST。
有效 ACK 后完整读回固定接受版本才确认本次同步；传输状态不重写 reported_result，Stop 不代表 PASS/COMPLETED。

Local 发行独立使用 local-vSEMVER，旧 mcp-v0.1.0/mcp-v0.2.0 历史不重标。
安装只复用既有私有 Project 授权，不申请 Operator key、签发 grant 或复制模型登录；
Hooks 需显式选择 workspace 或私有 approved artifact policy，版本匹配后启用。
升级/回退/卸载保留私有身份、账本、未决 key、源产物、用户项目与其他宿主配置。
Cloud/Local 共享 Project 的设计与任何外部 Cloud 实施进度不由本 Local 源码分支声称已交付。
"""
SHARED_HEADINGS = {
    "docs/architecture/HYPERTEST_TECHNICAL_ARCHITECTURE.md": "47. ADR-021 TaskSyncCore 的 Local 消费方",
    "docs/protocol/TEST_MISSION_PROTOCOL.md": "48. ADR-021 共享同步语义的 Local 约束",
    "docs/domain/HYPERTEST_DOMAIN_MODEL_AND_STATE_MACHINE.md": "53. ADR-021 私有同步记录与域隔离",
}
SHARED_ADDENDUM = """
TaskSyncCore 是内部可复用库，LocalSyncAdapter 保留 SessionTask 的原请求、身份、权限与版本规则。
共享语义是批准的结构化意图、完整基线、冻结请求、原 key 对账、回执验证与固定版本完整读回；
不增加通用 Task/API、跨模式 token、全局 journal 或服务端 fencing 字段。
Source binding、事件队列、snapshot 与 checkpoint 均为私有客户端记录，不是新的业务状态。
只合并未冻结新意图；显式 MCP 完整请求的空值不被自动推断为 omitted，传输失败不修改业务报告。
Cloud 消费方由独立 Cloud 设计/源码/验收拥有；本 Local 分支不包括或发布该实现。
"""


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE).strip()


def local_document_links(path: Path) -> tuple[str, list[str]]:
    """Keep independent design references readable without links to excluded Cloud docs."""
    external = []
    def replace(match):
        label, target = match.groups()
        if target.startswith(("https://", "http://", "#", "mailto:")):
            return match.group(0)
        selected = target.split("#", 1)[0]
        if not selected or (path.parent / selected).is_file():
            return match.group(0)
        external.append(target)
        return label + "（独立设计参考，本 Local 源码分支未包含该文档）"
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, path.read_text()), external


def approved_paths(source: Path) -> list[str]:
    paths = set(FILES)
    for name in DIRECTORIES:
        for path in (source / name).rglob("*"):
            if path.is_file() and path.suffix in {".py", ".js", ".mjs", ".cjs", ".ts", ".json"}:
                paths.add(str(path.relative_to(source)))
    for pattern in ("tests/test_local*.py", "tests/test_local*.mjs", "tests/test_local*.cjs",
                    "docs/LOCAL_*ACCEPTANCE*.md", "docs/local-acceptance/*.json"):
        paths.update(str(path.relative_to(source)) for path in source.glob(pattern) if path.is_file())
    missing = [name for name in FILES if not (source / name).is_file()]
    if missing:
        raise ValueError("Required Local source missing: " + ", ".join(missing))
    for name in paths:
        path = source / name
        if (path.is_symlink() or not path.resolve().is_relative_to(source.resolve())
                or path.stat().st_size > 5 * 1024 * 1024):
            raise ValueError("Invalid Local source file")
    return sorted(paths)


def prepare(source: Path, output: Path) -> dict:
    source, output = source.resolve(strict=True), output.absolute()
    if output.exists() or output.resolve().is_relative_to(source):
        raise ValueError("Use a new isolated directory outside the shared checkout")
    if git(source, "rev-parse", "--verify", BASE + "^{commit}") != BASE:
        raise ValueError("The reviewed fixed base is not available")
    paths = approved_paths(source)
    # --no-hardlinks isolates Git object writes too; no shared index or worktree.
    subprocess.run(["git", "clone", "--no-hardlinks", "--no-checkout", "--local", str(source), str(output)], check=True)
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(output),
                    "checkout", "-b", BRANCH, BASE], check=True)
    subprocess.run(["git", "-C", str(output), "remote", "set-url", "origin",
                    "https://github.com/ZhangLiangchen/hypertest-one.git"], check=True)
    for name in paths:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target, follow_symlinks=False)
    # Shared Cloud edits are intentionally never copied. Append Local-only text
    # to each unmodified base document, preserving normative historical sections.
    for name, heading in FOUNDATIONS.items():
        path = output / name
        path.write_text(path.read_text().rstrip() + "\n\n## " + heading + "\n\n" + ADDENDUM.strip() + "\n")
        if name in SHARED_HEADINGS:
            path.write_text(path.read_text() + "\n## " + SHARED_HEADINGS[name] + "\n\n" + SHARED_ADDENDUM.strip() + "\n")
    for name in ("docs/architecture/ADR-020_HOOK_DRIVEN_LOCAL_SESSION_SYNC.md",
                 "docs/architecture/ADR-021_SHARED_TASK_SYNC_CORE.md"):
        path = output / name
        lines = path.read_text().splitlines(keepends=True)
        lines.insert(1, "\n**Local 源码分支实现增补（2026-10-22）：Local 协调器、TaskSyncCore Local adapter、"
                     "三宿主入口和统一发行工具已实现源码；真实宿主与发行状态见 LOCAL_MODE_IMPLEMENTATION_STATUS.md "
                     "及确切目标验收记录。下文为初始设计原文，其中 NOT IMPLEMENTED 是当时状态，"
                     "不覆盖本段当前 Local 状态；本分支不包含 Cloud/Memory 的实现。**\n")
        path.write_text("".join(lines))
    pyproject = output / "pyproject.toml"
    body = pyproject.read_text()
    needle = "[project.scripts]\n"
    if body.count(needle) != 1 or "hypertest-local =" in body:
        raise ValueError("Review base project script layout before modifying")
    pyproject.write_text(body.replace(needle, needle + 'hypertest-local = "hypertest.local_sync.__main__:main"\n'))
    # Copy only the additive Local appendix; ADR-018's original operation body stays base-identical.
    sync_doc = output / "docs/CODEX_SESSION_TASK_SYNC.md"
    sync_doc.write_text(sync_doc.read_text().rstrip() + "\n\n## Local 统一发行与自动触发\n\n"
                        "原管理步骤与契约保持不变。新增 Local 协调器、三宿主接入及固定摘要安装入口见 "
                        "[Local 状态](LOCAL_MODE_IMPLEMENTATION_STATUS.md)与[发行构建](LOCAL_MODE_RELEASE_BUILD.md)。\n")
    external_refs = {}
    for name in paths:
        if name.startswith("docs/") and name.endswith(".md"):
            path = output / name
            body, refs = local_document_links(path)
            if refs:
                path.write_text(body)
                external_refs[name] = refs
    all_paths = sorted(set(paths) | set(FOUNDATIONS) | {"pyproject.toml", "docs/CODEX_SESSION_TASK_SYNC.md"})
    modified = set(git(output, "diff", "--name-only", BASE).splitlines())
    modified.update(git(output, "ls-files", "--others", "--exclude-standard").splitlines())
    if not modified <= set(all_paths):
        raise ValueError("Prepared checkout includes a path outside the Local allowlist")
    inventory = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in all_paths}
    receipt = {"schema_version": "hypertest.local-source-freeze/v1", "base_commit": BASE,
               "branch": BRANCH, "state": "PREPARED_UNCOMMITTED_UNPUBLISHED", "files": inventory,
               "external_design_refs_without_links": external_refs,
               "excluded": ["src/hypertest/cloud", "src/hypertest/deepseek_harness", "src/hypertest/config.py",
                            "src/hypertest/main.py", "src/hypertest/domain/models.py", "alembic/versions/0023_cloud_tasks.py",
                            ".github/workflows/ci.yml", "web/app/projects/[projectId]/page.tsx"]}
    (output / ".git/local-release-freeze.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.source, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Local source preparation BLOCKED: {exc}\n")
    print(json.dumps({"state": receipt["state"], "base_commit": BASE, "branch": BRANCH,
                      "files": len(receipt["files"]), "receipt": str(args.output / ".git/local-release-freeze.json")}))


if __name__ == "__main__":
    main()
