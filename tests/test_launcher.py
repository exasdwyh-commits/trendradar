"""Launcher preflight must work without launching or modifying the application."""

import importlib.util
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest


@pytest.fixture()
def launcher():
    path = Path(__file__).resolve().parents[1] / "scripts" / "launch.py"
    spec = importlib.util.spec_from_file_location("launcher_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_preflight():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "launch.py"), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TrendRadar" in result.stdout
    assert "Preflight passed" in result.stdout


def test_build_cache_detects_changed_added_and_deleted_sources(tmp_path, launcher):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "dist").mkdir()
    source = frontend / "src" / "page.tsx"
    source.write_text("export default Page", encoding="utf-8")
    (frontend / "dist" / "index.html").write_text("built", encoding="utf-8")
    assert launcher.needs_build(tmp_path)
    (tmp_path / ".tmp_launch").mkdir()
    stamp = tmp_path / ".tmp_launch" / "build.json"
    stamp.write_text("[]", encoding="utf-8")
    assert launcher.needs_build(tmp_path)

    def mark_built():
        stamp.write_text(
            json.dumps({"fingerprint": launcher.frontend_fingerprint(tmp_path)}), encoding="utf-8"
        )

    mark_built()
    assert not launcher.needs_build(tmp_path)
    source.write_text("export default ChangedPage", encoding="utf-8")
    assert launcher.needs_build(tmp_path)
    mark_built()
    extra = frontend / "src" / "new.tsx"
    extra.write_text("new", encoding="utf-8")
    assert launcher.needs_build(tmp_path)
    mark_built()
    extra.unlink()
    assert launcher.needs_build(tmp_path)


def test_port_probe_rejects_unrelated_services_and_distinguishes_a_free_port(launcher, monkeypatch):
    monkeypatch.setattr(launcher.socket, "create_connection", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(launcher, "get_json", lambda url: {"ok": True, "service": "something else"})
    assert launcher.service_state(8787) == "occupied"
    monkeypatch.setattr(launcher, "get_json", lambda url: {"ok": True, "schema_version": 7, "counts": None})
    assert launcher.service_state(8787) == "occupied"
    monkeypatch.setattr(
        launcher, "get_json", lambda url: {"ok": True, "schema_version": 7, "counts": {"documents": 0}}
    )
    assert launcher.service_state(8787) == "ready"

    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(launcher.socket, "create_connection", unavailable)
    assert launcher.service_state(8787) == "absent"


def test_running_app_is_reused_without_spawning_another_server(launcher, monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "service_state", lambda port: "ready")
    monkeypatch.setattr(launcher, "check_workbench", lambda url: None)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    def should_not_spawn(*args, **kwargs):
        pytest.fail("Reusing a service must not start a second server")

    monkeypatch.setattr(launcher.subprocess, "Popen", should_not_spawn)
    assert launcher.run_server(8787, no_browser=False, smoke_test=False) == 0
    assert opened == ["http://127.0.0.1:8787"]
