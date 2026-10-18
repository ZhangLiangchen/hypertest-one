#!/usr/bin/env python3
"""Protect one Compose bridge; never flush or replace existing firewall rules."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from stack import read_env, validate


def canonical_rule(tokens: list[str]) -> list[tuple[str, str, bool]]:
    """Normalize module ordering without losing which option `!` negates."""
    options = []
    while tokens:
        negated = tokens[0] == "!"
        if negated:
            tokens = tokens[1:]
        if len(tokens) < 2 or tokens[0] not in {"-i", "-o", "-m", "--comment", "--ctstate", "-j"}:
            return []
        option, value, *tokens = tokens
        if option == "--ctstate":
            value = ",".join(sorted(value.split(",")))
        options.append((option, value, negated))
    return sorted(options)


def inspect_guard(values: dict[str, str]) -> tuple[dict, list[str]]:
    version = subprocess.check_output(["docker", "info", "--format", "{{.ServerVersion}}"], text=True).strip()
    match = re.match(r"(\d+)\.", version)
    if not match:
        raise ValueError("cannot determine Docker version")
    name = values["HYPERTEST_STACK_NAME"] + "_backend"
    network = json.loads(subprocess.check_output(["docker", "network", "inspect", name], text=True))[0]
    if network["Driver"] != "bridge" or network.get("Labels", {}).get("com.docker.compose.project") != values["HYPERTEST_STACK_NAME"]:
        raise ValueError("network is not this Compose project's bridge")
    if network.get("EnableIPv6"):
        raise ValueError("IPv6 bridge requires a separately verified firewall policy")
    bridge = network.get("Options", {}).get("com.docker.network.bridge.name") or "br-" + network["Id"][:12]
    if not re.fullmatch(r"br-[a-f0-9]{12}", bridge):
        raise ValueError("only an explicitly owned Docker bridge interface is supported")
    comment = "hypertest:" + values["HYPERTEST_STACK_NAME"] + ":loopback-only"
    rule = ["-m", "comment", "--comment", comment, "!", "-i", bridge, "-o", bridge,
            "-m", "conntrack", "!", "--ctstate", "RELATED,ESTABLISHED", "-j", "DROP"]
    return {"docker_version": version, "required": int(match[1]) < 28, "network": name,
            "network_id": network["Id"], "bridge": bridge, "comment": comment}, rule


def guard(values: dict[str, str], action: str = "check") -> dict:
    details, rule = inspect_guard(values)
    # Refuse missing/non-iptables backends; do not create broad chains or policies.
    def first_rule_matches() -> bool:
        chain = subprocess.check_output(["iptables", "-w", "5", "-S", "DOCKER-USER"], text=True)
        rules = [shlex.split(line) for line in chain.splitlines() if line.startswith("-A DOCKER-USER ")]
        return bool(rules and canonical_rule(rules[0][2:]) == canonical_rule(rule))

    def present() -> bool:
        result = subprocess.run(["iptables", "-w", "5", "-C", "DOCKER-USER", *rule],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode not in (0, 1):
            raise ValueError("cannot inspect Docker ingress guard")
        return result.returncode == 0

    installed = present()
    if action != "check" and os.geteuid() != 0:
        raise ValueError("firewall changes require the host operator")
    first = first_rule_matches()
    if action == "install" and (not installed or not first):
        while present():
            subprocess.run(["iptables", "-w", "5", "-D", "DOCKER-USER", *rule], check=True)
        subprocess.run(["iptables", "-w", "5", "-I", "DOCKER-USER", "1", *rule], check=True)
    elif action == "remove" and installed:
        # Exact rule + owned network identity + our comment; never flush the chain.
        while present():
            subprocess.run(["iptables", "-w", "5", "-D", "DOCKER-USER", *rule], check=True)
    installed = present()
    first = first_rule_matches()
    if action != "remove" and (not installed or not first):
        raise ValueError("Docker ingress requires the scoped ingress guard as its first rule before starting containers")
    return {**details, "protected": installed and first, "first_rule": first, "action": action,
            "reboot_persistence_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("action", choices=("check", "install", "remove"))
    args = parser.parse_args()
    values = read_env(args.env)
    validate(values, live=False)
    print(json.dumps(guard(values, args.action), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"network guard failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
