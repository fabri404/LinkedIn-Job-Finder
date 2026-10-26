"""loop_control.py - Encuentra, arranca y detiene el loop (main.py) para el dashboard.

El loop corre como proceso aparte (sesión propia): cerrar el dashboard no lo corta.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path

from config import BASE_DIR

PROC_DIR = Path("/proc")
INHIBIT = ["systemd-inhibit", "--what=idle:sleep", "--who=LinkedIn Job Finder", "--why=Loop de postulaciones"]
STOP_TIMEOUT_S = 40


class LoopMode(str, Enum):
    CONTINUOUS = "loop"   # 24/7, sin ventana
    ONCE = "once"         # una sola vuelta, sin ventana
    VISIBLE = "visible"   # con ventana de Chrome, para iniciar sesión o resolver una verificación


def is_loop_cmdline(args: list[str]) -> bool:
    """`python3 main.py [...]`: el intérprete y main.py como primer argumento."""
    return len(args) >= 2 and Path(args[0]).name.startswith("python") and Path(args[1]).name == "main.py"


def _cmdline(pid_dir: Path) -> list[str]:
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _cwd(pid_dir: Path) -> Path | None:
    try:
        return Path(os.readlink(pid_dir / "cwd"))
    except OSError:
        return None


def find_loop_pid(proc_dir: Path = PROC_DIR) -> int | None:
    """PID del loop de este proyecto, lo haya lanzado el dashboard o la terminal."""
    for pid_dir in proc_dir.iterdir():
        if pid_dir.name.isdigit() and is_loop_cmdline(_cmdline(pid_dir)) and _cwd(pid_dir) == BASE_DIR.resolve():
            return int(pid_dir.name)
    return None


def loop_command(mode: LoopMode) -> list[str]:
    once = ["--once"] if mode is LoopMode.ONCE else []
    return [*INHIBIT, sys.executable, "main.py", *once]


def start_loop(mode: LoopMode) -> int:
    """Arranca el loop si no está corriendo; devuelve su PID."""
    running = find_loop_pid()
    if running:
        return running
    env = {**os.environ, "CHROME_HEADLESS": "0" if mode is LoopMode.VISIBLE else "1"}
    process = subprocess.Popen(loop_command(mode), cwd=BASE_DIR, env=env, start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process.pid


def stop_loop() -> bool:
    """SIGTERM (el loop cierra Chrome y guarda el estado) y espera a que termine."""
    pid = find_loop_pid()
    if pid is None:
        return True
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT_S
    while time.monotonic() < deadline:
        if find_loop_pid() is None:
            return True
        time.sleep(1)
    return False
