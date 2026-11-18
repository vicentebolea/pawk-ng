import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pawk

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def run_awk():
    """run_awk(prog, text) -> stdout, via the library API."""
    return pawk.awk


@pytest.fixture
def status_awk():
    """status_awk(prog, text, operands) -> (status, stdout, stderr)."""
    def go(prog, text="", operands=(), **kw):
        out, err = io.StringIO(), io.StringIO()
        st = pawk.run(prog, operands, stdin=io.StringIO(text), stdout=out,
                      stderr=err, **kw)
        return st, out.getvalue(), err.getvalue()
    return go


@pytest.fixture
def cli():
    """cli(*args, stdin="") -> CompletedProcess from a real subprocess."""
    def go(*args, stdin="", cwd=None, env=None):
        return subprocess.run([sys.executable, "-m", "pawk", *args], input=stdin,
                              capture_output=True, text=True, cwd=cwd or ROOT,
                              env=env, timeout=30)
    return go


@pytest.fixture
def gawk():
    path = shutil.which("gawk") or shutil.which("awk")
    if not path:
        pytest.skip("no awk available")

    def go(prog, stdin="", *args):
        return subprocess.run([path, *args, prog], input=stdin, capture_output=True,
                              text=True, timeout=30).stdout
    return go
