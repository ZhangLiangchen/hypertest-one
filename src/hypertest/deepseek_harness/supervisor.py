"""Own a local POSIX process group; remote/detached processes need other fencing."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .errors import AdapterError
from .models import StopObservation

MAX_CONTROL_FRAME = 65_536


def clean_environment(root: Path) -> dict[str, str]:
    """Build from zero, not os.environ; never inherit platform or personal auth."""
    return {
        "PATH": os.defpath,
        "HOME": str(root / "private-home"),
        "XDG_CONFIG_HOME": str(root / "private-home" / ".config"),
        "XDG_CACHE_HOME": str(root / "private-home" / ".cache"),
        "TMPDIR": str(root / "tmp"),
        "DSH_HOME": str(root / "dsh-home"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        # Source-tree support uses our known module root, never ambient PYTHONPATH.
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }


class ProcessSupervisor:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._proc: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, object] | AdapterError] = queue.Queue(maxsize=4)
        self._request_lock = threading.Lock()
        self._sequence = 0
        self._stop: StopObservation | None = None
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if os.name != "posix":
            raise AdapterError("PROCESS_SUPERVISION_UNSUPPORTED")
        if self._proc is not None or self._stop is not None:
            raise AdapterError("RUNTIME_RESTART_FORBIDDEN")
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "hypertest.deepseek_harness._worker"],
                cwd=self.root,
                env=clean_environment(self.root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                start_new_session=True,
            )
        except OSError:
            raise AdapterError("SUPERVISOR_START_FAILED") from None
        self._reader = threading.Thread(target=self._read, daemon=True, name="hypertest-dsh-control")
        self._reader.start()

    def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        stream = self._proc.stdout
        try:
            while True:
                line = stream.readline(MAX_CONTROL_FRAME + 1)
                if not line:
                    break
                if len(line) > MAX_CONTROL_FRAME or not line.endswith("\n"):
                    raise AdapterError("INVALID_CONTROL_FRAME")
                response = json.loads(line)
                if not isinstance(response, dict):
                    raise AdapterError("INVALID_CONTROL_FRAME")
                self._responses.put_nowait(response)
        except (OSError, ValueError, queue.Full, AdapterError):
            self._deliver_error("INVALID_CONTROL_FRAME")
            return
        self._deliver_error("RUNTIME_PROCESS_EXITED")

    def _deliver_error(self, code: str) -> None:
        try:
            self._responses.put_nowait(AdapterError(code))
        except queue.Full:
            pass

    def request(self, command: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
        with self._request_lock:
            proc = self._proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                raise AdapterError("RUNTIME_PROCESS_EXITED")
            self._sequence += 1
            sequence = self._sequence
            frame = json.dumps({"sequence": sequence, "command": command, "payload": payload}) + "\n"
            if len(frame.encode("utf-8")) > MAX_CONTROL_FRAME:
                raise AdapterError("CONTROL_FRAME_TOO_LARGE")
            try:
                proc.stdin.write(frame)
                proc.stdin.flush()
                result = self._responses.get(timeout=timeout)
            except queue.Empty:
                self.stop()
                raise AdapterError("SDK_TIMEOUT") from None
            except (OSError, ValueError):
                self.stop()
                raise AdapterError("SDK_TRANSPORT_FAILED") from None
            if isinstance(result, AdapterError):
                raise result
            if result.get("sequence") != sequence:
                raise AdapterError("INVALID_CONTROL_FRAME")
            error = result.get("error")
            if error is not None:
                # Worker emits a closed vocabulary. Never propagate runtime text.
                allowed = {"SDK_TIMEOUT", "SDK_OPERATION_FAILED", "SDK_PROTOCOL_UNSUPPORTED", "SDK_IMPORT_FAILED"}
                raise AdapterError(error if isinstance(error, str) and error in allowed else "SDK_OPERATION_FAILED")
            data = result.get("result")
            if not isinstance(data, dict):
                raise AdapterError("INVALID_CONTROL_FRAME")
            return data

    def stop(self) -> StopObservation:
        if self._stop is not None:
            return self._stop
        proc = self._proc
        if proc is None:
            self._stop = StopObservation(True, True)
            return self._stop
        # The helper is the session/group leader. Kill the whole group even if
        # that leader already exited: delegated children can still be resident.
        for signum in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, signum)
            except ProcessLookupError:
                break
            except PermissionError:
                break
            try:
                proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                continue
            if not self._group_exists(proc.pid):
                break
        try:
            proc.wait(timeout=1.0)
            root_reaped = True
        except subprocess.TimeoutExpired:
            root_reaped = False
        deadline = time.monotonic() + 0.5
        while self._group_exists(proc.pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        self._stop = StopObservation(root_reaped, not self._group_exists(proc.pid))
        if self._reader is not None:
            self._reader.join(timeout=0.2)
        # Never wait on a buffered-reader lock held by a lingering descendant.
        # Probe-created processes should remain in our group; an escaped process
        # is outside this supervisor's proof, and cannot block the caller here.
        streams = [proc.stdin]
        if self._reader is None or not self._reader.is_alive():
            streams.append(proc.stdout)
        for stream in streams:
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        return self._stop

    @staticmethod
    def _group_exists(pgid: int) -> bool:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
