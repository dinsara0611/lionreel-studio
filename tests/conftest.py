"""
Sandbox guard for the whole test suite.

Every test run is redirected to a sandbox root before any project module is
imported, and the run aborts if the project code would resolve to production
storage. Tests must never read or write C:\\LionReel or the Drive output folder.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_ROOT = os.environ.get("LIONREEL_ROOT") or os.path.join(tempfile.gettempdir(), "lionreel_test_root")
os.environ["LIONREEL_ROOT"] = _ROOT
os.environ["LIONREEL_DATA_DIR"] = os.path.join(_ROOT, "data")
os.environ["LIONREEL_CACHE_DIR"] = os.path.join(_ROOT, "cache")
os.environ["IS_TEST"] = "1"
for _sub in ("data", "cache", "work", "models"):
    os.makedirs(os.path.join(_ROOT, _sub), exist_ok=True)

import lion_paths  # noqa: E402


def pytest_configure(config):
    if lion_paths.is_production_root():
        pytest.exit("Refusing to run: LIONREEL_ROOT points at production storage.", returncode=3)
    if os.path.normcase(_PROJECT_ROOT).startswith(os.path.normcase(r"G:\My Drive")):
        pytest.exit(
            "Refusing to run from the Drive project folder: tests write under the project "
            "directory (finished/, output/). Run scripts/run_all_tests.ps1, which syncs the "
            "code to the sandbox first.",
            returncode=3,
        )


TEST_PORT = 8100


def _port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session", autouse=True)
def sandbox_server():
    """Serves the sandbox copy on TEST_PORT. Port 8000 is the live dashboard: tests never use it."""
    if _port_open(TEST_PORT):
        yield
        return
    env = dict(os.environ, PORT=str(TEST_PORT), NO_BROWSER="1", PYTHONUTF8="1")
    log = open(os.path.join(_ROOT, "sandbox_server.log"), "ab")
    proc = subprocess.Popen([sys.executable, "web_server.py"], cwd=_PROJECT_ROOT, env=env, stdout=log, stderr=log)
    deadline = time.time() + 30
    while time.time() < deadline and proc.poll() is None and not _port_open(TEST_PORT):
        time.sleep(0.25)
    yield
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    log.close()


@pytest.fixture(autouse=True)
def _production_ledger_never_touched():
    import clip_ledger
    assert not os.path.normcase(clip_ledger.get_ledger_db_path()).startswith(
        os.path.normcase(lion_paths.PRODUCTION_ROOT + os.sep)
    ), "test resolved the production ledger"
    yield
