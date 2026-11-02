"""Launch the notebook's UI stage without putting web-server code in the cells."""
import os
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path
from IPython.display import HTML, display
from stages import STAGES

ROOT = Path(__file__).resolve().parent
_process = globals().get("_process")
_log = globals().get("_log")


def stop_ui():
    """Stop only the server process started by this notebook kernel."""
    global _process, _log
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)
    _process = None
    if _log is not None:
        _log.close()
        _log = None


def update_ui(stage, port=8504):
    """Update the product to this chapter and display its browser link.

    No model call is made until a task is submitted in the browser.
    Changing stages starts a fresh workspace. Earlier-stage conversations live
    in memory; Persistence uses persistent SQLite storage. Notebook edits to
    shared helpers should also be saved in agent.py before opening the UI.
    """
    global _process, _log
    stage = {"ongoing": "persistence"}.get(stage, stage)
    if stage not in STAGES:
        raise ValueError(f"Choose one of {STAGES}")
    stop_ui()
    import socket
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                port = available.getsockname()[1]
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    _log = (runtime / "interface.log").open("a")
    environment = dict(os.environ, NSWORK_STAGE=stage, NSWORK_PORT=str(port))
    _process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT,
                                env=environment, stdout=_log, stderr=_log)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if _process.poll() is not None:
            stop_ui()
            raise RuntimeError("The interface stopped. Inspect .runtime/interface.log.")
        try:
            with urllib.request.urlopen(url + "/api/config", timeout=1) as response:
                config = json.load(response)
            if config.get("stage") == stage:
                link = f"{url}/?stage={stage}&v={time.time_ns()}"
                display(HTML(
                    f'<div style="padding:16px 0"><a href="{link}" target="nswork" '
                    f'style="font-size:20px;font-weight:600">Open NS Work · {stage.title()} ↗</a>'
                    '</div>'
                ))
                return None
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    stop_ui()
    raise RuntimeError("The interface did not start in time. Inspect .runtime/interface.log.")

# Compatibility for older notebook kernels and saved launcher calls.
show_ui = update_ui
