"""Awk's idea of a value: numeric strings, conversions, regexes, field splitting.

This module has no dependency on the rest of pawk (except the error type), so
it is the best place to start reading.
"""
# awk has no separate types for text and numbers.  Everything read from the
# input is a *string*, and a string that **looks like a number** takes part
# in numeric comparisons and arithmetic as one.  Python has no such thing, so
# this module supplies it:
#
# * `to_num` / `to_str` convert the awk way (`"12abc"` is 12, `3.0` prints
#   as `3`);
# * `Field` is a `str` that compares and computes like awk's "strnum";
# * `Uninit` is the value of a variable that was never assigned;
# * `regex` and `split_text` give awk's regex dialect and field-splitting
#   rules (`FS`) on top of Python's `re`.
import functools
import math
import re

from .errors import PawkError

_LEADING_NUMBER = re.compile(r"\s*[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_WHOLE_NUMBER = re.compile(_LEADING_NUMBER.pattern + r"\s*\Z")

OFMT = "%.6g"
_BLANK_RUNS = re.compile(r"[ \t\n]+")


# ## Converting between strings and numbers

def to_num(value):
    """Awk string->number: longest numeric prefix, 0 when there is none."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if value is None:
        return 0
    match = _LEADING_NUMBER.match(str(value))
    if not match:
        return 0
    number_text = match.group().strip()
    try:
        return int(number_text)
    except ValueError:
        return float(number_text)


def looks_numeric(text):
    """Is the whole of ``text`` a number (surrounding blanks allowed)?"""
    return _WHOLE_NUMBER.match(text) is not None


def to_str(value, number_format=None):
    """Number->string the awk way: integral values print as integers."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value in (float("inf"), float("-inf")):
            return "inf" if value > 0 else "-inf"
        if value == int(value):
            return str(int(value))
        return (number_format or OFMT) % value
    return str(value)


# ## Fields: strings that behave like numbers when they look like numbers
#
# `$1 > $2` must compare *numerically* when both fields look numeric
# (`10 > 9`) and as text otherwise (`"abc" > "abd"`).  `Field` makes that
# decision per comparison.  It overrides arithmetic and ordering, but keeps
# `str` behaviour for everything else, so `$1.upper()` and `$1[:2]` work.
# Adding a plain `str` still concatenates (`"a" + $1`), and `%` is numeric on
# the left (`$1 % 2`) but untouched on the right (`"%s" % $1`).

class Field(str):
    """A string that behaves as an awk "strnum".

    It compares numerically with numbers and with other numeric-looking
    fields, and does arithmetic numerically.  Adding a plain ``str`` still
    concatenates, so ``"a" + F[1]`` works as in Python.
    """

    __slots__ = ()

    @property
    def is_num(self):
        return looks_numeric(self)

    def _comparable_pair(self, other):
        """Return a pair of comparable values."""
        if isinstance(other, (int, float)) and not isinstance(other, bool):
            if self.is_num:
                return to_num(self), other
            return str(self), to_str(other)
        if isinstance(other, Field):
            if self.is_num and other.is_num:
                return to_num(self), to_num(other)
            return str(self), str(other)
        return str(self), str(other)

    def __eq__(self, other):
        if not isinstance(other, (str, int, float)):
            return NotImplemented
        left, right = self._comparable_pair(other)
        return left == right

    def __ne__(self, other):
        equal = self.__eq__(other)
        return equal if equal is NotImplemented else not equal

    def __lt__(self, other):
        left, right = self._comparable_pair(other)
        return left < right

    def __le__(self, other):
        left, right = self._comparable_pair(other)
        return left <= right

    def __gt__(self, other):
        left, right = self._comparable_pair(other)
        return left > right

    def __ge__(self, other):
        left, right = self._comparable_pair(other)
        return left >= right

    __hash__ = str.__hash__

    def __bool__(self):
        if self.is_num:
            return to_num(self) != 0
        return len(self) > 0

    def __int__(self):
        return int(to_num(self))

    def __float__(self):
        return float(to_num(self))

    def __neg__(self):
        return -to_num(self)

    def __pos__(self):
        return to_num(self)

    def __abs__(self):
        return abs(to_num(self))

    def __add__(self, other):
        if isinstance(other, str) and not isinstance(other, Field):
            return str.__add__(self, other)
        return to_num(self) + to_num(other)

    def __radd__(self, other):
        if isinstance(other, str) and not isinstance(other, Field):
            return str.__add__(other, self)
        return to_num(other) + to_num(self)

    def __sub__(self, other):
        return to_num(self) - to_num(other)

    def __rsub__(self, other):
        return to_num(other) - to_num(self)

    def __mul__(self, other):
        return to_num(self) * to_num(other)

    def __rmul__(self, other):
        return to_num(other) * to_num(self)

    def __truediv__(self, other):
        return to_num(self) / to_num(other)

    def __rtruediv__(self, other):
        return to_num(other) / to_num(self)

    def __floordiv__(self, other):
        return to_num(self) // to_num(other)

    def __rfloordiv__(self, other):
        return to_num(other) // to_num(self)

    def __mod__(self, other):
        return _remainder_like_awk(to_num(self), to_num(other))

    def __pow__(self, other):
        return to_num(self) ** to_num(other)

    def __rpow__(self, other):
        return to_num(other) ** to_num(self)


# ## The value of a variable that was never assigned
#
# awk says an unset variable is both `""` and `0`.  `Uninit` is a `Field`
# that always counts as numeric, which gives exactly that.

class Uninit(Field):
    """Value of a never-assigned variable: "" as a string, 0 as a number."""

    __slots__ = ()
    is_num = True


def _remainder_like_awk(dividend, divisor):
    """`%` as awk has it: the sign follows the dividend, ints stay ints."""
    remainder = math.fmod(dividend, divisor)
    both_ints = isinstance(dividend, int) and isinstance(divisor, int)
    return int(remainder) if both_ints else remainder


_POSIX_BRACKET_CLASSES = {
    "alpha": "a-zA-Z", "digit": "0-9", "alnum": "a-zA-Z0-9",
    "upper": "A-Z", "lower": "a-z", "space": r" \t\n\r\f\v",
    "blank": r" \t", "punct": r"!-/:-@\[-`{-~", "xdigit": "0-9A-Fa-f",
    "print": r" -~", "graph": r"!-~", "cntrl": r"\x00-\x1f\x7f",
}


# ## Regular expressions and field splitting
#
# awk uses POSIX extended regexes; Python's `re` is close enough except for
# bracket classes like `[[:digit:]]`, which are translated.  `FS` (and `RS`)
# follow awk's rules: a single space splits on runs of blanks, any other
# single character is *literal* (so `FS = "|"` just works), and a longer
# value is a regex.

@functools.lru_cache(maxsize=512)
def regex(pattern):
    """Compile an awk ERE (with POSIX bracket classes) into a Python regex."""
    if hasattr(pattern, "search"):
        return pattern
    pattern = re.sub(r"\[:(\w+):\]",
                     lambda match: _POSIX_BRACKET_CLASSES.get(match.group(1), match.group(0)),
                     str(pattern))
    try:
        return re.compile(pattern)
    except re.error as error:
        raise PawkError("invalid regular expression %r: %s" % (pattern, error)) from None


def _split_on_regex(compiled, text):
    """`re.split` that ignores capture groups and empty matches."""
    pieces, piece_start = [], 0
    for match in compiled.finditer(text):
        if match.end() == match.start():
            continue
        pieces.append(text[piece_start:match.start()])
        piece_start = match.end()
    pieces.append(text[piece_start:])
    return pieces


def split_text(text, field_separator, paragraph=False):
    """Split ``text`` into fields according to awk's `FS` rules.

    ``paragraph`` is paragraph mode (`RS = ""`), where a newline separates
    fields in addition to ``field_separator``."""
    if field_separator == " ":
        return [piece for piece in _BLANK_RUNS.split(text) if piece]
    if text == "":
        return []
    if field_separator == "":
        return list(text)
    if len(field_separator) == 1:
        if paragraph:
            return _split_on_regex(regex("[" + re.escape(field_separator) + "\\n]"), text)
        return text.split(field_separator)
    if paragraph:
        return _split_on_regex(regex("(?:" + field_separator + ")|\\n"), text)
    return _split_on_regex(regex(field_separator), text)
