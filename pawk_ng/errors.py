"""Errors and control-flow signals.

Everything that can interrupt a pawk run lives here, so that every other
module can import it without creating a cycle.
"""
# Two kinds of things go wrong, and one kind of thing is not wrong at all.
#
# * `ProgramError` -- the *program text* is invalid.  It is raised while the
#   program is being read, before any input is touched.
# * `PawkError` -- the program was fine but something failed *while running*:
#   a bad variable value, an invalid regex in `FS`, an exception in the
#   user's own code.
# * `Exit`, `NextRecord`, `NextFile` -- not errors but *signals*.  awk's
#   `exit`, `next` and `nextfile` unwind the interpreter from the middle of
#   user code, which is exactly what an exception does.  They derive from
#   `BaseException` so that a user's own `except Exception:` cannot swallow
#   them by accident.


class ProgramError(Exception):
    """The program text is not valid."""


class PawkError(Exception):
    """A runtime failure: bad variable value, bad regex, error in user code."""


class Exit(BaseException):
    """`exit [code]`: stop reading input and run END (once)."""

    def __init__(self, code=None):
        self.code = code


class NextRecord(BaseException):
    """`next`: abandon the current record and start on the next one."""


class NextFile(BaseException):
    """`nextfile`: abandon the current file and start on the next one."""
