from __future__ import annotations
import os, psutil
from typing import List, Set

# ---------------------------------------------------------------------------
# Detect root process once per program
# ---------------------------------------------------------------------------

_ROOT_PID_ENV = "PROC_CLEANER_ROOT_PID"
if _ROOT_PID_ENV not in os.environ:
    os.environ[_ROOT_PID_ENV] = str(os.getpid())

def _running_in_root() -> bool:
    return os.getpid() == int(os.environ[_ROOT_PID_ENV])

# ---------------------------------------------------------------------------
# Static info about *this* interpreter and its ancestor chain
# ---------------------------------------------------------------------------

_ME          = psutil.Process(os.getpid())
_MY_STARTED  = _ME.create_time()
_GRACE_SEC   = 3.0

_ANCESTORS: Set[int] = {_ME.pid}
try:
    p = _ME.parent()
    while p:
        _ANCESTORS.add(p.pid)
        p = p.parent()
except psutil.Error:
    pass
# Now _ANCESTORS contains parent, grand-parent, … all the way to PID 1

# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def clean(timeout: float = _GRACE_SEC,
          extra_filters: List[str] | None = None) -> None:
    """Terminate *pre-existing* Python interpreters (see doc-string)."""
    if not _running_in_root():
        return                            # inside a spawned worker ➜ noop

    extra_filters = [s.lower() for s in (extra_filters or [])]
    victims = []

    for proc in psutil.process_iter(('pid', 'create_time', 'name', 'cmdline')):
        if proc.pid in _ANCESTORS:            # ➊ spare me & my ancestors
            continue
        if (proc.info['create_time'] or 0) >= _MY_STARTED:  # ➋ newer ➜ keep
            continue
        if not _looks_like_python(proc):      # ➌ not python ➜ keep
            continue
        if extra_filters and not _cmdline_contains(proc, extra_filters):
            continue
        victims.append(proc)

    if not victims:
        return

    for p in victims: _safe_terminate(p)
    gone, alive = psutil.wait_procs(victims, timeout=timeout)
    for p in alive: _safe_kill(p)

# ---------------------------------------------------------------------------
# Helper utilities (unchanged)
# ---------------------------------------------------------------------------

def _looks_like_python(proc: psutil.Process) -> bool:
    try:
        name = (proc.info.get('name') or '').lower()
        if name.startswith("python"):
            return True
        cmd = " ".join(proc.info.get('cmdline') or []).lower()
        return "python" in cmd
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def _cmdline_contains(proc: psutil.Process, needles: List[str]) -> bool:
    try:
        cmd = " ".join(proc.info.get('cmdline') or []).lower()
        return all(n in cmd for n in needles)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

def _safe_terminate(proc: psutil.Process) -> None:
    try: proc.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied): pass

def _safe_kill(proc: psutil.Process) -> None:
    try: proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied): pass
