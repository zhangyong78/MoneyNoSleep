from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mns.data.duckdb_store import DuckDBStore


def is_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def can_bind_port(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_available_port(host: str, preferred_port: int, max_tries: int = 20) -> int:
    for port in range(preferred_port, preferred_port + max_tries):
        if can_bind_port(host, port):
            return port
    raise RuntimeError(f"No available port found in range {preferred_port}-{preferred_port + max_tries - 1}.")


def wait_for_http(url: str, timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if 200 <= response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    return False


def build_streamlit_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def start_streamlit_ui(
    *,
    app_path: str | Path,
    db_path: str | Path,
    host: str = "127.0.0.1",
    preferred_port: int = 8501,
    log_root: str | Path = "data/logs",
) -> dict[str, str | int | bool]:
    app_path = Path(app_path).resolve()
    db_path = Path(db_path)
    log_root = Path(log_root)
    log_root.mkdir(parents=True, exist_ok=True)

    DuckDBStore(db_path).initialize()

    port = find_available_port(host, preferred_port)
    url = f"http://{host}:{port}"

    stdout_path = log_root / f"streamlit_{port}.out.log"
    stderr_path = log_root / f"streamlit_{port}.err.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "true",
        "--server.address",
        host,
        "--server.port",
        str(port),
    ]

    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    process = subprocess.Popen(
        command,
        cwd=str(app_path.parent.parent),
        env=build_streamlit_env(),
        stdout=stdout_handle,
        stderr=stderr_handle,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo,
        close_fds=False if os.name == "nt" else True,
    )

    started = wait_for_http(url)
    return {
        "pid": process.pid,
        "url": url,
        "host": host,
        "port": port,
        "started": started,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
