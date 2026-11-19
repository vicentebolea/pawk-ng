"""The variables of a running program.

All awk variables (`NR`, `FS`, ...) and all of the user's variables live in
one dictionary, which is also the *globals* that `exec` and `eval` run the
user's code in.
"""
# Using the interpreter's own globals is the central design decision of
# pawk: the user's code is real Python, so `x = 1` in one rule and `x` in
# another share a variable for free, functions defined with `def` see the
# same variables, and there is no separate "awk variable table" to keep in
# sync.  The price is that the interpreter has to *read* its own variables
# (`FS`, `OFS`, `NF`, ...) out of that dictionary whenever it needs them.
#
# Two small subclasses of `dict` add the awk behaviour on top.
import re

from .errors import PawkError
from .values import Field, Uninit, to_str

_VARIABLE_NAME = re.compile(r"[A-Za-z_]\w*")
_ESCAPE_SEQUENCES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "/": "/", '"': '"',
            "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def unescape(text):
    """Process the backslash escapes awk applies to `-v`, `-F` and `ARGV` values."""
    return re.sub(r"\\(.)", lambda match: _ESCAPE_SEQUENCES.get(match.group(1), match.group(0)),
                  text)


class Array(dict):
    """An awk array.  Reading a missing key creates it as an uninitialized value."""

    def __missing__(self, key):
        self[key] = Uninit()
        return self[key]


class Namespace(dict):
    """Globals of the program.

    A name the program assigns somewhere reads as awk's uninitialized value
    (`""` as a string, `0` as a number) until it is first assigned, and a
    name it subscripts reads as an empty :class:`Array`.  Python calls
    `__missing__` exactly when a global is not found, which is the hook
    that makes this possible without touching the user's code.
    """

    assigned_names = array_names = frozenset()

    def __missing__(self, name):
        if name in self.array_names:
            self[name] = Array()
            return self[name]
        if name in self.assigned_names:
            return Uninit()
        raise KeyError(name)

    @classmethod
    def with_awk_defaults(cls, operands, environ, assigned_names, array_names):
        """A namespace holding the awk variables with their startup values."""
        namespace = cls({
            "FS": " ", "OFS": " ", "RS": "\n", "ORS": "\n", "NF": 0, "NR": 0,
            "FNR": 0, "FILENAME": "", "SUBSEP": "\x1c", "OFMT": "%.6g",
            "ENVIRON": {k: Field(v) for k, v in environ.items()},
            "ARGV": ["pawk"] + list(operands), "ARGC": 1 + len(operands),
        })
        namespace.assigned_names, namespace.array_names = assigned_names, array_names
        return namespace

    def text(self, name):
        """A variable as a plain string.

        Never a :class:`Field`: a `Field` overrides `%` to mean arithmetic,
        which would break `OFMT % number`."""
        return str(to_str(self[name]))

    def assign_from_text(self, assignment):
        """Apply a `name=value` assignment (from `-v` or from the operands)."""
        name, _, value = assignment.partition("=")
        if not _VARIABLE_NAME.fullmatch(name):
            raise PawkError("invalid variable name in assignment %r" % assignment)
        self[name] = Field(unescape(value))
