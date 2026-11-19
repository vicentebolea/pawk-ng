"""The public face of the package: two functions and a few types.

`pawk` (the command) is `cli.main`; this module is for using it from Python.
"""
# `run` executes a program and returns its exit status; `awk` is the same
# with a string in and a string out, which is handy in tests and notebooks.
# Everything else exported here is a type a caller may need to catch or
# build: `ProgramError` for a bad program, `PawkError` for a failure while
# running, `Field` for values that behave like awk's numeric strings.
import io

from .errors import PawkError
from .parser import ProgramError, parse
from .runtime import Runtime
from .values import Field, to_num, to_str

__all__ = [
    "Field",
    "PawkError",
    "ProgramError",
    "awk",
    "parse",
    "run",
    "to_num",
    "to_str",
]
__version__ = "2.0.0"


def run(program, operands=(), **kw):
    """Run ``program`` over ``operands`` (files and var=value assignments)
    and return the exit status.  Keyword arguments go to :class:`Runtime`."""
    return Runtime(program, operands, **kw).run()


def awk(program, text="", operands=(), **kw):
    """Run ``program`` on ``text`` (as stdin) and return what it printed."""
    out = io.StringIO()
    kw.setdefault("stdin", io.StringIO(text))
    kw.setdefault("stderr", io.StringIO())
    run(program, operands, stdout=out, **kw)
    return out.getvalue()
