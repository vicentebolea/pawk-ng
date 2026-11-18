"""pawk: awk's BEGIN/END/pattern-action model with Python 3 as the language."""
import io

from .parser import ProgramError, parse
from .runtime import PawkError, Runtime
from .values import Field, to_num, to_str

__all__ = ["run", "awk", "parse", "ProgramError", "PawkError", "Field",
           "to_num", "to_str"]
__version__ = "0.1.0"


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
