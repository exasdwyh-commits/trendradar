"""Launch the local writing desk, build changed UI, and open it when ready.

No scheduler, collection, demo seeding or model calls are started by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "fastapi",
    "uvicorn",
    "httpx",
    "numpy",
    "pydantic_settings",
    "yaml",
    "feedparser",
    "bs4",
    "dotenv",
    "markdown_it",
)
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(message: str) -> None:
    print(message, flush=True)


def frontend_fingerprint(root: Path) -> str:
    frontend = root / "frontend"
    paths = list((frontend / "src").rglob("*")) + list((frontend / "public").rglob("*"))
    paths += [
        frontend / name for name in ("index.html", "package.json", "package-lock.json", "vite.config.ts")
    ]
    paths += list(frontend.glob("tsconfig*.json"))
    entries = []
    for path in sorted(p for p in paths if p.is_file()):
        stat = path.stat()
        entries.append(f"{path.relative_to(frontend).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def needs_build(root: Path) -> bool:
    if not (root / "frontend" / "dist" / "index.html").is_file():
        return True
    try:
        stamp = json.loads((root / ".tmp_launch" / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return not isinstance(stamp, dict) or stamp.get("fingerprint") != frontend_fingerprint(root)


def missing_modules() -> list[str]:
    return [name for name in MODULES if importlib.util.find_spec(name) is None]


def ensure_environment() -> int | None:
    """Use the project venv, installing runtime dependencies only if missing."""
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        say("首次启动：正在创建项目 Python 环境…")
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    if Path(sys.executable).resolve() != python.resolve():
        return subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT)
    if missing_modules():
        say("首次启动：正在安装后端依赖（需要联网）…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=ROOT, check=True)
    env_example = ROOT / ".env.example"
    if not (ROOT / ".env").exists() and env_example.is_file():
        shutil.copyfile(env_example, ROOT / ".env")
    return None


def build_frontend(force: bool = False) -> None:
    if not force and not needs_build(ROOT):
        say("前端没有变化，使用现有构建。")
        return
    node = shutil.which("node")
    if not node:
        raise RuntimeError("需要 Node.js 20 或更高版本来构建前端。安装后重新双击启动。")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 20:
        raise RuntimeError(f"当前 Node.js {version}，请使用 20 或更高版本。")
    frontend = ROOT / "frontend"
    tsc = frontend / "node_modules" / "typescript" / "bin" / "tsc"
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    if not tsc.is_file() or not vite.is_file():
        # Prefer the bundled npm CLI; global npm shims can point at a broken installation.
        npm_cli = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if npm_cli.is_file():
            command = [node, str(npm_cli), "ci"]
        elif npm:
            command = [npm, "ci"]
        else:
            raise RuntimeError("找不到 npm。请修复 Node.js 安装后重新启动。")
        say("首次启动：正在安装前端依赖（需要联网）…")
        subprocess.run(command, cwd=frontend, check=True)
    say("正在构建前端…")
    subprocess.run([node, str(tsc), "-b"], cwd=frontend, check=True)
    subprocess.run([node, str(vite), "build"], cwd=frontend, check=True)
    stamp = ROOT / ".tmp_launch" / "build.json"
    stamp.parent.mkdir(exist_ok=True)
    stamp.write_text(json.dumps({"fingerprint": frontend_fingerprint(ROOT)}), encoding="utf-8")


def get_json(url: str) -> dict:
    with HTTP.open(url, timeout=2) as response:
        body = json.loads(response.read(1_000_000))
    if not isinstance(body, dict):
        raise ValueError("Unexpected response")
    return body


def service_state(port: int) -> str:
    """Never reuse or stop an unrelated service occupying the configured port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            pass
    except OSError:
        return "absent"
    try:
        data = get_json(f"http://127.0.0.1:{port}/api/health")
        counts = data.get("counts")
        if (
            data.get("ok") is True
            and "schema_version" in data
            and isinstance(counts, dict)
            and "documents" in counts
        ):
            return "ready"
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return "occupied"


def check_workbench(url: str) -> None:
    try:
        data = get_json(url + "/api/studio/overview")
        if "resume" not in data or "counts" not in data:
            raise ValueError("Missing workbench")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError("检测到旧版或未就绪的服务。请先停止原服务，再重新双击启动。") from exc


def run_server(port: int, *, no_browser: bool, smoke_test: bool) -> int:
    url = f"http://127.0.0.1:{port}"
    state = service_state(port)
    if state == "occupied":
        raise RuntimeError(f"端口 {port} 被其他程序占用。可用 --port 8788 指定其他端口。")
    if state == "ready":
        check_workbench(url)
        say(f"写作台已在运行：{url}（复用服务）")
        if not no_browser and not smoke_test:
            webbrowser.open(url)
        return 0
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(prefix="trendradar-launch-") as scratch:
        if smoke_test:
            environment["DATA_DIR"] = scratch
            for slot in ("FAST_MODEL", "ANALYSIS_MODEL", "WRITING_MODEL", "EMBEDDING_MODEL", "MODEL"):
                for suffix in ("API_KEY", "BASE_URL", "MODEL"):
                    environment[f"{slot}_{suffix}"] = ""
        process = subprocess.Popen(
            [sys.executable, "-m", "trendradar.cli", "serve", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=environment,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("服务启动失败，请查看上方错误信息。")
                if service_state(port) == "ready":
                    check_workbench(url)
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("等待服务就绪超时，请查看上方日志。")
            say(f"\n写作台已就绪：{url}")
            if smoke_test:
                with HTTP.open(url, timeout=3) as response:
                    if b'<div id="root"' not in response.read(100_000):
                        raise RuntimeError("前端页面没有正确提供。")
                say("Smoke test passed (health + workbench + frontend; isolated database).")
                return 0
            if not no_browser:
                if not webbrowser.open(url):
                    say("浏览器未自动打开，请访问上方地址。")
            say("保持此窗口打开即可使用；结束时按 Ctrl+C 停止服务。")
            return process.wait()
        except KeyboardInterrupt:
            # The child receives Ctrl+C in the same console and can finish its shutdown.
            say("\n正在停止写作台…")
            with suppress(subprocess.TimeoutExpired, KeyboardInterrupt):
                process.wait(timeout=8)
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=8)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true", help="read-only environment diagnostics")
    parser.add_argument(
        "--smoke-test", action="store_true", help="start, verify and stop using an isolated database"
    )
    args = parser.parse_args()
    say("TrendRadar 写作台")
    if sys.version_info < (3, 11):  # noqa: UP036 - the bootstrap may be run before a supported Python is installed
        raise RuntimeError("需要 Python 3.11 或更高版本。")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "src"))
    if args.check:
        missing = missing_modules()
        say(f"Python: {sys.version.split()[0]} ({sys.executable})")
        say(f"Node: {shutil.which('node') or 'not installed; needed for a frontend rebuild'}")
        say(f"Frontend: {'build required' if needs_build(ROOT) else 'up to date'}")
        if missing:
            raise RuntimeError("后端依赖缺失：" + ", ".join(missing))
        say("Preflight passed (Python runtime ready; no service was started).")
        return 0
    redirected = ensure_environment()
    if redirected is not None:
        return redirected
    from trendradar.core.settings import get_settings

    build_frontend(args.rebuild)
    return run_server(
        args.port or get_settings().port, no_browser=args.no_browser, smoke_test=args.smoke_test
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        say(f"\n启动失败：{error}")
        sys.exit(1)
