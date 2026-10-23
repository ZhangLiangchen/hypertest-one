#!/usr/bin/python3
"""Immutable fixture-only diagnostic. No arguments, network or source execution."""

import json
import os
import stat

descriptor = os.open("/opt/hypertest-ssh/fixture/deployment.json", os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(descriptor, "rb") as source:
    info = os.fstat(source.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o222 or info.st_size > 4096:
        raise SystemExit(2)
    value = json.loads(source.read(4097))
if (set(value) != {"fixture", "build_id"} or value["fixture"] != "hypertest-ssh-readonly-v1"
        or not isinstance(value["build_id"], str) or len(value["build_id"]) > 128):
    raise SystemExit(2)
print(json.dumps(value, sort_keys=True))
