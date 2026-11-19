"""Interpreter: records, fields, awk variables and the awk built-ins."""
import math
import os
import re
import sys

from .errors import PawkError
from .parser import parse
from .values import Field, Uninit, regex, split_text, to_num, to_str


class Exit(BaseException):
    def __init__(self, code=None):
        self.code = code


class NextRecord(BaseException):
    pass


class NextFile(BaseException):
    pass


def unescape(s):
    """Process the backslash escapes awk applies to -v / -F / ARGV values."""
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                                       "/": "/", '"': '"', "a": "\a", "b": "\b",
                                       "f": "\f", "v": "\v"}.get(m.group(1), m.group(0)),
                  s)


MAX_FIELDS = 10_000_000
_IDENT = re.compile(r"[A-Za-z_]\w*")
_ASSIGN = re.compile(r"[A-Za-z_]\w*=")


class Array(dict):
    """Awk array: reading a missing key creates it as an uninitialized value."""

    def __missing__(self, key):
        value = self[key] = Uninit()
        return value


class Namespace(dict):
    """Globals of the program.  A name the program assigns somewhere reads as
    awk's uninitialized value ("" or 0) until it is first assigned, and a name
    it subscripts reads as an empty :class:`Array`."""

    assigned = arrays = frozenset()

    def __missing__(self, name):
        if name in self.arrays:
            value = self[name] = Array()
            return value
        if name in self.assigned:
            return Uninit()
        raise KeyError(name)


class RecordReader:
    """Reads records separated by RS, which may change between reads."""

    def __init__(self, f):
        self.f, self.buf, self.slurped = f, "", False

    def read(self, rs):
        if rs == "\n" and not self.buf:
            line = self.f.readline()
            if not line:
                return None
            return line[:-1] if line.endswith("\n") else line
        if not self.slurped:
            self.buf += self.f.read()
            self.slurped = True
        buf = self.buf
        if rs == "":
            buf = buf.lstrip("\n")
            m = re.search(r"\n\n+", buf)
            if not buf:
                self.buf = ""
                return None
            if m:
                self.buf = buf[m.end():]
                return buf[:m.start()]
            self.buf = ""
            return buf.rstrip("\n")
        if buf == "":
            return None
        if len(rs) == 1:
            i = buf.find(rs)
            sep_len = 1
        else:
            m = next((m for m in regex(rs).finditer(buf) if m.end() > m.start()), None)
            i, sep_len = (m.start(), m.end() - m.start()) if m else (-1, 0)
        if i < 0:
            self.buf = ""
            return buf
        self.buf = buf[i + sep_len:]
        return buf[:i]


class Record:
    """The ``F`` object: F[0] is $0, F[1] is $1, ...  NF is kept in sync."""

    def __init__(self, rt):
        self.rt, self.text, self.fields = rt, "", []

    def set_text(self, text):
        rt = self.rt
        self.text = text
        self.fields = [Field(x) for x in
                       split_text(text, rt.var("FS"), rt.var("RS") == "")]
        rt.ns["NF"] = len(self.fields)

    def _check_size(self, n):
        if n < 0:
            raise PawkError("NF cannot be negative: %d" % n)
        if n > MAX_FIELDS:
            raise PawkError("too many fields: %d (limit %d)" % (n, MAX_FIELDS))

    def set_nf(self, n):
        self._check_size(n)
        del self.fields[n:]
        self.fields.extend(Field("") for _ in range(n - len(self.fields)))
        self._rebuild()

    def _rebuild(self):
        self.text = self.rt.var("OFS").join(self.fields)
        self.rt.ns["NF"] = len(self.fields)

    def _index(self, i):
        self.rt.sync_nf()
        i = int(to_num(i))
        if i < 0:
            raise PawkError("attempt to access field %d" % i)
        return i

    def __getitem__(self, i):
        i = self._index(i)
        if i == 0:
            return Field(self.text)
        return self.fields[i - 1] if i <= len(self.fields) else Field("")

    def __setitem__(self, i, value):
        i = self._index(i)
        value = to_str(value, self.rt.var("OFMT"))
        if i == 0:
            self.set_text(value)
            return
        self._check_size(i)
        self.fields.extend(Field("") for _ in range(i - len(self.fields)))
        self.fields[i - 1] = Field(value)
        self._rebuild()

    def __len__(self):
        self.rt.sync_nf()
        return len(self.fields)

    def __iter__(self):
        self.rt.sync_nf()
        return iter(list(self.fields))

    def __str__(self):
        self.rt.sync_nf()
        return self.text


class Runtime:
    def __init__(self, program, operands=(), fs=None, assigns=(), modules=(),
                 stdin=None, stdout=None, stderr=None, environ=None):
        self.rules = parse(program) if isinstance(program, str) else program
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.status = 0
        self.active_ranges = {}
        self._reader = None
        self._argi = 1
        self._used_input = False
        env = os.environ if environ is None else environ
        ns = self.ns = Namespace({
            "FS": " ", "OFS": " ", "RS": "\n", "ORS": "\n", "NF": 0, "NR": 0,
            "FNR": 0, "FILENAME": "", "SUBSEP": "\x1c", "OFMT": "%.6g",
            "ENVIRON": {k: Field(v) for k, v in env.items()},
            "ARGV": ["pawk"] + list(operands), "ARGC": 1 + len(operands),
        })
        ns.assigned = frozenset().union(*(r.assigned for r in self.rules))
        ns.arrays = frozenset().union(*(r.arrays for r in self.rules))
        self.record = ns["F"] = Record(self)
        self._install_builtins()
        if fs is not None:
            ns["FS"] = unescape(fs)
        for a in assigns:
            self.assign(a)
        for mod in modules:
            exec("from %s import *" % mod, ns)

    # -- variables -----------------------------------------------------
    def var(self, name):
        """A variable as a plain string (never a Field, whose % is numeric)."""
        return str(to_str(self.ns[name]))

    def assign(self, text):
        name, _, value = text.partition("=")
        if not _IDENT.fullmatch(name):
            raise PawkError("invalid variable name in assignment %r" % text)
        self.ns[name] = Field(unescape(value))

    def sync_nf(self):
        n = int(to_num(self.ns["NF"]))
        self.ns["NF"] = n
        if n != len(self.record.fields):
            self.record.set_nf(n)

    # -- input ---------------------------------------------------------
    def _open_next(self):
        argv = self.ns["ARGV"]
        if not isinstance(argv, (list, tuple)):
            raise PawkError("ARGV must be a list, not %s" % type(argv).__name__)
        while self._argi < len(argv):
            arg = to_str(argv[self._argi])
            self._argi += 1
            if arg == "":
                continue
            if _ASSIGN.match(arg):
                self.assign(arg)
                continue
            self._used_input = True
            if arg == "-":
                f = self.stdin
            else:
                try:
                    f = open(arg, encoding="utf-8", errors="surrogateescape",
                             newline="\n")
                except OSError as e:
                    self.stderr.write("pawk: cannot open %s (%s)\n" % (arg, e.strerror))
                    self.status = 2
                    continue
            self.ns["FILENAME"], self.ns["FNR"] = arg, 0
            self._reader = RecordReader(f)
            return True
        if not self._used_input:
            self._used_input = True
            self._reader = RecordReader(self.stdin)
            self.ns["FNR"] = 0
            return True
        return False

    def _close_current(self):
        self._reader = None

    def next_record(self):
        while True:
            if self._reader is None and not self._open_next():
                return None
            rec = self._reader.read(self.var("RS"))
            if rec is None:
                self._close_current()
                continue
            self.ns["NR"] = to_num(self.ns["NR"]) + 1
            self.ns["FNR"] = to_num(self.ns["FNR"]) + 1
            return rec

    # -- execution -----------------------------------------------------
    def _guard(self, fn, rule):
        try:
            return fn()
        except (Exit, NextRecord, NextFile, PawkError):
            raise
        except Exception as e:
            raise PawkError("%s: %s (in %r, record %s)" % (
                type(e).__name__, e, rule.source, self.ns["NR"])) from e

    def _eval(self, code, rule):
        return self._guard(lambda: eval(code, self.ns), rule)

    def _matches(self, rule):
        if rule.pattern is None:
            return True
        if rule.pattern2 is None:
            return bool(self._eval(rule.pattern, rule))
        key = id(rule)
        if not self.active_ranges.get(key):
            if not self._eval(rule.pattern, rule):
                return False
            self.active_ranges[key] = True
        if self._eval(rule.pattern2, rule):
            self.active_ranges[key] = False
        return True

    def _act(self, rule):
        if rule.code is None:
            self.sync_nf()
            print(self.record.text, file=self.stdout)
        else:
            self._guard(lambda: exec(rule.code, self.ns), rule)
            self._guard(self.sync_nf, rule)  # apply an NF assignment now

    def run(self):
        begin = [r for r in self.rules if r.kind == "BEGIN"]
        main = [r for r in self.rules if r.kind == "MAIN"]
        end = [r for r in self.rules if r.kind == "END"]
        real_stdout, sys.stdout = sys.stdout, self.stdout  # builtin print writes here
        try:
            try:
                for r in self.rules:
                    if r.kind == "DEF":
                        self._guard(lambda: exec(r.code, self.ns), r)
                for r in begin:
                    self._act(r)
                if main or end:
                    self._main_loop(main)
            except Exit as e:
                self._set_exit(e)
            try:
                for r in end:
                    self._act(r)
            except Exit as e:
                self._set_exit(e)
        except (NextRecord, NextFile):
            raise PawkError("next/nextfile used outside a main rule")
        finally:
            sys.stdout = real_stdout
            self._cleanup()
        return self.status

    def _set_exit(self, e):
        if e.code is not None:
            self.status = e.code

    def _main_loop(self, main):
        while True:
            text = self.next_record()
            if text is None:
                return
            self.record.set_text(text)
            for rule in main:
                try:
                    if self._matches(rule):
                        self._act(rule)
                except NextRecord:
                    break
                except NextFile:
                    self._close_current()
                    break

    def _cleanup(self):
        try:
            self.stdout.flush()
        except Exception:
            pass

    def _exit(self, code=None):
        raise Exit(None if code is None else int(to_num(code)))

    def _next(self):
        raise NextRecord()

    def _nextfile(self):
        raise NextFile()

    def _install_builtins(self):
        self.ns.update({
            "next": self._next, "nextfile": self._nextfile,
            "exit": self._exit, "math": math, "re": re, "os": os, "sys": sys,
        })
