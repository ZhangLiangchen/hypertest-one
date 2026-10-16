from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from hypertest.domain.enums import CaseResult


@dataclass(frozen=True)
class NodeResult:
    result: CaseResult
    duration_ms: int = 0
    summary: str | None = None


def parse_junit(content: bytes, nodeids: list[str]) -> dict[str, NodeResult]:
    if len(content) > 16 * 1024 * 1024 or b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise ValueError("JUnit exceeds limits or contains prohibited XML declarations")
    root = ET.fromstring(content)
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("JUnit document has no testsuite root")
    matched: dict[str, list[NodeResult]] = {nodeid: [] for nodeid in nodeids}
    for case in root.iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "")
        candidates = []
        for nodeid in nodeids:
            path, *symbols = nodeid.split("::")
            expected_class = ".".join([path[:-3].replace("/", "."), *symbols[:-1]])
            if classname == expected_class and (
                name == symbols[-1] or name.startswith(symbols[-1] + "[")
            ):
                candidates.append(nodeid)
        if len(candidates) != 1:
            continue
        result = CaseResult.PASS
        summary = None
        for tag, state in [
            ("skipped", CaseResult.SKIPPED),
            ("failure", CaseResult.FAIL),
            ("error", CaseResult.ERROR),
        ]:
            child = case.find(tag)
            if child is not None:
                result, summary = state, (child.get("message") or child.text or "")[:8192]
        seconds = float(case.get("time", "0"))
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("JUnit contains an invalid test duration")
        matched[candidates[0]].append(NodeResult(result, int(seconds * 1000), summary))
    priority = {
        CaseResult.PASS: 0,
        CaseResult.SKIPPED: 1,
        CaseResult.FAIL: 2,
        CaseResult.ERROR: 3,
        CaseResult.NOT_RUN: 4,
        CaseResult.BLOCKED: 5,
    }
    results = {}
    for nodeid, cases in matched.items():
        if not cases:
            results[nodeid] = NodeResult(
                CaseResult.NOT_RUN, summary="Expected test was not collected"
            )
            continue
        worst = max(cases, key=lambda item: priority[item.result])
        results[nodeid] = NodeResult(
            worst.result, sum(case.duration_ms for case in cases), worst.summary
        )
    return results
