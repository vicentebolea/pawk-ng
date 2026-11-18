"""Awk value semantics: numeric strings, number/string conversion, regexes."""
import functools
import math
import re

_NUM_PREFIX = re.compile(r"\s*[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_NUM_FULL = re.compile(_NUM_PREFIX.pattern + r"\s*\Z")

OFMT = "%.6g"
_BLANKS = re.compile(r"[ \t\n]+")


def to_num(x):
    """Awk string->number: longest numeric prefix, 0 when there is none."""
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return x
    if x is None:
        return 0
    m = _NUM_PREFIX.match(str(x))
    if not m:
        return 0
    s = m.group().strip()
    try:
        return int(s)
    except ValueError:
        return float(s)


def looks_numeric(s):
    return _NUM_FULL.match(s) is not None


def to_str(x, ofmt=None):
    """Number->string the awk way: integral values print as integers."""
    if isinstance(x, str):
        return x
    if x is None:
        return ""
    if isinstance(x, bool):
        return str(int(x))
    if isinstance(x, float):
        if x != x:
            return "nan"
        if x in (float("inf"), float("-inf")):
            return "inf" if x > 0 else "-inf"
        if x == int(x):
            return str(int(x))
        return (ofmt or OFMT) % x
    return str(x)


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

    def _cmp_key(self, other):
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
        a, b = self._cmp_key(other)
        return a == b

    def __ne__(self, other):
        r = self.__eq__(other)
        return r if r is NotImplemented else not r

    def __lt__(self, other):
        a, b = self._cmp_key(other)
        return a < b

    def __le__(self, other):
        a, b = self._cmp_key(other)
        return a <= b

    def __gt__(self, other):
        a, b = self._cmp_key(other)
        return a > b

    def __ge__(self, other):
        a, b = self._cmp_key(other)
        return a >= b

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

    def __add__(self, o):
        if isinstance(o, str) and not isinstance(o, Field):
            return str.__add__(self, o)
        return to_num(self) + to_num(o)

    def __radd__(self, o):
        if isinstance(o, str) and not isinstance(o, Field):
            return str.__add__(o, self)
        return to_num(o) + to_num(self)

    def __sub__(self, o):
        return to_num(self) - to_num(o)

    def __rsub__(self, o):
        return to_num(o) - to_num(self)

    def __mul__(self, o):
        return to_num(self) * to_num(o)

    def __rmul__(self, o):
        return to_num(o) * to_num(self)

    def __truediv__(self, o):
        return to_num(self) / to_num(o)

    def __rtruediv__(self, o):
        return to_num(o) / to_num(self)

    def __mod__(self, o):
        return _fmod(to_num(self), to_num(o))

    def __pow__(self, o):
        return to_num(self) ** to_num(o)

    def __rpow__(self, o):
        return to_num(o) ** to_num(self)


class Uninit(Field):
    """Value of a never-assigned variable: "" as a string, 0 as a number."""

    __slots__ = ()
    is_num = True


def _fmod(a, b):
    r = math.fmod(a, b)
    return int(r) if isinstance(a, int) and isinstance(b, int) else r


_POSIX_CLASSES = {
    "alpha": "a-zA-Z", "digit": "0-9", "alnum": "a-zA-Z0-9",
    "upper": "A-Z", "lower": "a-z", "space": r" \t\n\r\f\v",
    "blank": r" \t", "punct": r"!-/:-@\[-`{-~", "xdigit": "0-9A-Fa-f",
    "print": r" -~", "graph": r"!-~", "cntrl": r"\x00-\x1f\x7f",
}


@functools.lru_cache(maxsize=512)
def regex(pat):
    """Compile an awk ERE (with POSIX bracket classes) into a Python regex."""
    if hasattr(pat, "search"):
        return pat
    pat = re.sub(r"\[:(\w+):\]",
                 lambda m: _POSIX_CLASSES.get(m.group(1), m.group(0)), str(pat))
    return re.compile(pat)


def _re_split(rx, text):
    """re.split that ignores capture groups and empty matches."""
    out, pos = [], 0
    for m in rx.finditer(text):
        if m.end() == m.start():
            continue
        out.append(text[pos:m.start()])
        pos = m.end()
    out.append(text[pos:])
    return out


def split_text(text, fs, paragraph=False):
    """Split ``text`` into fields according to awk's FS rules."""
    if fs == " ":
        return [x for x in _BLANKS.split(text) if x]
    if text == "":
        return []
    if fs == "":
        return list(text)
    if len(fs) == 1:
        if paragraph:
            return _re_split(regex("[" + re.escape(fs) + "\\n]"), text)
        return text.split(fs)
    if paragraph:
        return _re_split(regex("(?:" + fs + ")|\\n"), text)
    return _re_split(regex(fs), text)
