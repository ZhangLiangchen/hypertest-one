"""The root SDK prompt must never start without its per-invocation guard."""
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from hypertest.cloud import native_sdk_driver as driver


@pytest.mark.parametrize("mode", ["missing", "bad_nonce", "bad_root", "malformed", "selection_failure", "ok"])
def test_prompt_requires_fresh_registered_guard(monkeypatch, tmp_path, mode):
    calls = []
    module = ModuleType("deepseek_harness")

    class Config:
        def __init__(self, **values):
            self.values = values

    class Subscription:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def drain(self, observe): pass

    class Client:
        def __init__(self, config): self.env = config.values["env"]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def initialize(self, **kwargs):
            if mode != "missing":
                marker = Path(self.env["DSH_SDK_CORDIS_HANDSHAKE"])
                payload = {"phase": "registered", "nonce": self.env["DSH_SDK_CORDIS_NONCE"],
                           "root": self.env["DSH_SDK_CORDIS_ROOT"]}
                if mode == "bad_nonce":
                    payload["nonce"] = "wrong"
                if mode == "bad_root":
                    payload["root"] = "wrong"
                marker.write_text("not json" if mode == "malformed" else json.dumps(payload))
            return SimpleNamespace(serverInfo=SimpleNamespace(name="deepseek-harness-sdk-runtime", version="0.0.1"))
        def subscribe_notifications(self): return Subscription()
        def session_prompt(self, *args, **kwargs):
            calls.append("prompt")
            if mode == "selection_failure":
                raise RuntimeError("preset rejected")
            return "initial-message"
        def request(self, *args, **kwargs): calls.append("wait")

    module.HarnessConfig, module.HarnessClient = Config, Client
    monkeypatch.setitem(sys.modules, "deepseek_harness", module)
    overlay = ModuleType("hypertest.cloud.native_cordis")
    def prepare(directory, *, title):
        assert title == "任务标题"
        return directory / "overlay.yml"
    overlay.prepare_cordis_overlay = prepare
    monkeypatch.setitem(sys.modules, "hypertest.cloud.native_cordis", overlay)
    def read_selection(**kwargs):
        return {"provider": "x", "model": "y"}
    monkeypatch.setattr(driver, "read_native_selection", read_selection)
    config = {"workspace": str(tmp_path), "dsh_home": str(tmp_path), "session_id": "root-1", "title": "任务标题", "prompt": "test"}
    if mode == "ok":
        driver.run(config, lambda value: None)
        assert calls == ["prompt", "wait"]
    elif mode == "selection_failure":
        with pytest.raises(RuntimeError, match="preset rejected"):
            driver.run(config, lambda value: None)
        assert calls == ["prompt"]
    else:
        with pytest.raises(ValueError, match="preset guard"):
            driver.run(config, lambda value: None)
        assert not calls
