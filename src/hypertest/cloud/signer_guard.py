"""Fixed child-process confinement for a private native project signer.

Runs only inside the trusted Linux Worker. The parent verifies the frozen
source files and controls all arguments and stdin; no Agent supplies paths.
The guard cannot grant network or read access to Worker-private ledgers.
"""
from __future__ import annotations

import ctypes
import os
import resource
import sys
from pathlib import Path

_LAUNCHER = "/snapshot/node/node_modules/@deepseek-ai/node-addon-system-linux-arm64/bin/landlock-run"
_BOOTSTRAP = ("import runpy,sys;sys.path.insert(0,sys.argv[1]);"
              "runpy.run_path(sys.argv[2],run_name='__main__')")
_DENY = ("socket", "socketpair", "connect", "bind", "listen", "accept", "accept4", "sendto", "sendmsg",
         "sendmmsg", "recvfrom", "recvmsg", "recvmmsg", "ptrace", "process_vm_readv", "process_vm_writev",
         "pidfd_open", "pidfd_getfd", "pidfd_send_signal", "bpf", "perf_event_open", "io_uring_setup",
         "io_uring_enter", "io_uring_register", "open_by_handle_at", "name_to_handle_at", "mount", "umount2",
         "unshare", "setns", "clone", "clone3", "fork", "vfork", "kill", "tkill", "tgkill")


def _seccomp():
    lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW; inherited Docker profile remains in force.
    if not ctx:
        raise ValueError
    try:
        for name in _DENY:
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and lib.seccomp_rule_add(ctx, 0x00050001, number, 0) != 0:  # ERRNO(EPERM)
                raise ValueError
        if lib.seccomp_load(ctx) != 0:
            raise ValueError
    finally:
        lib.seccomp_release(ctx)


def main() -> int:
    try:
        if sys.platform != "linux" or os.geteuid() == 0 or not sys.flags.isolated or len(sys.argv) != 4:
            raise ValueError
        source, import_root, adapter = map(Path, sys.argv[1:])
        if (not source.is_absolute() or source.resolve(strict=True) != source
                or not import_root.is_absolute() or import_root.resolve(strict=True) != import_root
                or not adapter.is_absolute() or adapter.resolve(strict=True) != adapter
                or not import_root.is_relative_to(source) or not adapter.is_relative_to(import_root)
                or not adapter.is_file() or not Path(_LAUNCHER).is_file()):
            raise ValueError
        # Fixed limits and one process; outer Worker/Attempt resource limits
        # continue to apply. The parent enforces the wall-clock deadline.
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        _seccomp()
        grants = []
        for value in ("/usr", "/lib", "/lib64", "/opt/hypertest-cloud/venv", str(source), "/dev/urandom"):
            if Path(value).exists():
                grants.extend(["--ro", value])
        if Path("/dev/null").exists():
            grants.extend(["--rw", "/dev/null"])
        os.execv(_LAUNCHER, [_LAUNCHER, *grants, "--", sys.executable, "-I", "-c", _BOOTSTRAP,
                             str(import_root), str(adapter)])
    except Exception:
        # Never include argv, environment, source text, credentials, or stderr.
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
