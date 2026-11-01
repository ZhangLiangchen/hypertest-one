"""Run the official bundled Harness CLI against the dedicated cloud home."""
import os
import sys

from deepseek_harness_runtime import resolve_bundled_launch_args

command = [*resolve_bundled_launch_args(), *sys.argv[1:]]
os.execv(command[0], command)
