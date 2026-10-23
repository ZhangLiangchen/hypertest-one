"""Bounded report consistency checks, explicitly independent of provenance trust."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import Counter


def parity_report(content: bytes) -> dict[str, str]:
    entries = [json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip()]
    scenarios = [r for r in entries if r.get("type") == "scenario"]
    summaries = [r for r in entries if r.get("type") == "summary"]
    if len(summaries) != 1 or not scenarios or entries[-1].get("type") != "summary":
        raise ValueError("report needs scenarios and one final summary")
    results = {r["name"]: "SKIPPED" if r["verdict"] == "SKIP" else r["verdict"] for r in scenarios}
    if len(results) != len(scenarios) or any(v not in {"PASS", "FAIL", "ERROR", "SKIPPED"} for v in results.values()):
        raise ValueError("duplicate scenario identity or unsupported verdict")
    for step in (r for r in entries if r.get("type") == "step"):
        if step.get("scenario") not in results or step.get("verdict") not in {"PASS", "FAIL", "ERROR", "SKIPPED"}:
            raise ValueError("step verdict or scenario reference is invalid")
        if step["verdict"] in {"FAIL", "ERROR"} and results[step["scenario"]] == "PASS":
            raise ValueError("step failure contradicts scenario result")
        if step.get("mismatches") and step["verdict"] == "PASS":
            raise ValueError("assertion mismatches contradict step verdict")
    for error in (r for r in entries if r.get("type") == "scenario_error"):
        if error.get("name") not in results or results[error["name"]] == "PASS":
            raise ValueError("scenario error contradicts terminal verdict")
    counts, summary = Counter(results.values()), summaries[0]
    expected = {"passed": counts["PASS"], "failed": counts["FAIL"], "errors": counts["ERROR"],
                "skipped": counts["SKIPPED"], "selected": len(results)}
    if any(type(summary.get(k)) is not int or summary[k] != v for k, v in expected.items()):
        raise ValueError("scenario results contradict summary")
    # acceptanceConclusion UNKNOWN/NOT_ACCEPTED in step payloads is product
    # behavior under test. Only the framework assertion verdict is counted.
    return results


def junit_report(content: bytes) -> dict[str, str]:
    source = content.decode("utf-8")
    if "\x00" in source or "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
        raise ValueError("XML declarations are unsupported")
    root = ET.fromstring(source)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("unsupported JUnit root")
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("JUnit report needs a testsuite")
    results = {}
    for suite in suites:
        counts = Counter()
        for case in suite.findall("testcase"):
            key = case.attrib["classname"] + "#" + case.attrib["name"]
            if key in results:
                raise ValueError("duplicate JUnit native identifier")
            value = ("ERROR" if case.find("error") is not None else
                     "FAIL" if case.find("failure") is not None else
                     "SKIPPED" if case.find("skipped") is not None else "PASS")
            results[key] = value
            counts[value] += 1
        for name, value in {"tests": sum(counts.values()), "failures": counts["FAIL"],
                            "errors": counts["ERROR"], "skipped": counts["SKIPPED"]}.items():
            if int(suite.attrib[name]) != value:
                raise ValueError("JUnit counters contradict testcase elements")
    if not results:
        raise ValueError("JUnit report contains no testcases")
    if root.tag == "testsuites":
        counts = Counter(results.values())
        for name, value in {"tests": len(results), "failures": counts["FAIL"],
                            "errors": counts["ERROR"], "skipped": counts["SKIPPED"]}.items():
            if name in root.attrib and int(root.attrib[name]) != value:
                raise ValueError("JUnit aggregate counters contradict testcase elements")
    return results


def verify_reports(materials: list[tuple[str, bytes]], observations: dict[str, str], exit_code: int) -> dict:
    reports: dict[str, str] = {}
    issues = []
    supported = 0
    for format_name, content in materials:
        if format_name == "TEXT":
            continue
        supported += 1
        try:
            parsed = parity_report(content) if format_name == "CONSUMER_PARITY_JSONL" else junit_report(content)
            if set(parsed) & set(reports):
                raise ValueError("native identifier repeats across reports")
            reports.update(parsed)
        except (ValueError, KeyError, TypeError, AttributeError, ET.ParseError, UnicodeError):
            issues.append("REPORT_STRUCTURE_OR_COUNTS_INVALID")
    if supported:
        if reports != observations:
            issues.append("REPORT_CASE_MAPPING_MISMATCH")
        if exit_code == 0 and any(v in {"FAIL", "ERROR"} for v in reports.values()):
            issues.append("EXIT_CODE_CONTRADICTS_REPORT")
    return {"integrity": "CHECKED", "report_consistency":
            "INVALID" if issues else "CONSISTENT" if supported else "UNSUPPORTED",
            "issues": sorted(set(issues)), "reported_case_count": len(reports),
            "provenance": "UNVERIFIED", "limitations": [
                "Content checks do not prove execution occurrence, source or environment.",
                "Local observations cannot create trusted Evidence or a native PASS."]}
