"""Interpreter: records, fields, awk variables and the awk built-ins."""
import math
import os
import random
import re
import subprocess
import sys
import time

from .parser import parse
from .values import Field, Uninit, regex, split_text, to_num, to_str


class PawkError(Exception):
    """A runtime failure inside a user's action or pattern."""


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

    def set_nf(self, n):
        if n < 0:
            raise PawkError("NF cannot be negative: %d" % n)
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
    SPECIAL = ("FS", "OFS", "RS", "ORS", "NF", "NR", "FNR", "FILENAME", "SUBSEP",
               "RSTART", "RLENGTH", "OFMT")

    def __init__(self, program, operands=(), fs=None, assigns=(), modules=(),
                 stdin=None, stdout=None, stderr=None, environ=None):
        self.rules = parse(program) if isinstance(program, str) else program
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.status = 0
        self.outputs, self.readers, self.procs = {}, {}, {}
        self.active_ranges = {}
        self._reader = None
        self._argi = 1
        self._used_input = False
        self._seed = 0
        env = os.environ if environ is None else environ
        ns = self.ns = Namespace({
            "FS": " ", "OFS": " ", "RS": "\n", "ORS": "\n", "NF": 0, "NR": 0,
            "FNR": 0, "FILENAME": "", "SUBSEP": "\x1c", "RSTART": 0,
            "RLENGTH": -1, "OFMT": "%.6g",
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
        return to_str(self.ns[name])

    def assign(self, text):
        name, _, value = text.partition("=")
        self.ns[name] = Field(unescape(value))

    def sync_nf(self):
        n = int(to_num(self.ns["NF"]))
        if n != len(self.record.fields):
            self.record.set_nf(n)

    # -- input ---------------------------------------------------------
    def _open_next(self):
        argv = self.ns["ARGV"]
        while self._argi < len(argv):
            arg = to_str(argv[self._argi])
            self._argi += 1
            if arg == "":
                continue
            if re.match(r"[A-Za-z_]\w*=", arg):
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
            self.print_()
        else:
            self._guard(lambda: exec(rule.code, self.ns), rule)

    def run(self):
        begin = [r for r in self.rules if r.kind == "BEGIN"]
        main = [r for r in self.rules if r.kind == "MAIN"]
        end = [r for r in self.rules if r.kind == "END"]
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
        for name in list(self.outputs) + list(self.readers):
            self.close(name)

    # -- output --------------------------------------------------------
    def _stream(self, to=None, append=False, pipe=None):
        if to is None and pipe is None:
            return self.stdout
        key = pipe if pipe is not None else to
        if key not in self.outputs:
            if pipe is not None:
                self.stdout.flush()
                p = subprocess.Popen(pipe, shell=True, stdin=subprocess.PIPE,
                                     text=True, errors="surrogateescape")
                self.procs[key] = p
                self.outputs[key] = p.stdin
            else:
                self.outputs[key] = open(to, "a" if append else "w",
                                         encoding="utf-8", errors="surrogateescape",
                                         newline="\n")
        return self.outputs[key]

    def print_(self, *args, to=None, append=False, pipe=None):
        self.sync_nf()
        ofmt = self.var("OFMT")
        text = (self.var("OFS").join(to_str(a, ofmt) for a in args)
                if args else self.record.text)
        self._stream(to, append, pipe).write(text + self.var("ORS"))

    def printf(self, fmt, *args, to=None, append=False, pipe=None):
        self._stream(to, append, pipe).write(self.sprintf(fmt, *args))

    _FMT = re.compile(r"%(?:%|([-+ #0]*)(\*|\d+)?(?:\.(\*|\d+))?([diouxXeEfFgGcs]))")

    def sprintf(self, fmt, *args):
        args = list(args)

        def nxt():
            return args.pop(0) if args else ""

        def one(m):
            if m.group() == "%%":
                return "%"
            flags, width, prec, conv = m.groups()
            if width == "*":
                width = str(int(to_num(nxt())))
            if prec == "*":
                prec = str(int(to_num(nxt())))
            spec = "%" + flags + (width or "") + ("." + prec if prec is not None else "")
            a = nxt()
            if conv in "di":
                return (spec + "d") % int(to_num(a))
            if conv in "ouxX":
                return (spec + ("d" if conv == "u" else conv)) % int(to_num(a))
            if conv in "eEfFgG":
                return (spec + conv) % float(to_num(a))
            if conv == "c":
                numeric = isinstance(a, (int, float)) or (isinstance(a, Field) and a.is_num)
                return (spec + "s") % (chr(int(to_num(a))) if numeric else to_str(a)[:1])
            return (spec + "s") % to_str(a, self.var("OFMT"))

        return self._FMT.sub(one, to_str(fmt))

    def close(self, name):
        name = to_str(name)
        found, status = False, 0
        if name in self.outputs:
            found = True
            self.outputs.pop(name).close()
        if name in self.readers:
            found = True
            r = self.readers.pop(name)
            r.f.close()
        p = self.procs.pop(name, None)
        if p is not None:
            status = p.wait()
        return status if found else -1

    def fflush(self, name=None):
        if name is None:
            self.stdout.flush()
        elif name in self.outputs:
            self.outputs[name].flush()
        return 0

    def system(self, cmd):
        self.stdout.flush()
        for f in self.outputs.values():
            f.flush()
        return subprocess.call(to_str(cmd), shell=True)

    # -- input built-ins -----------------------------------------------
    def getline(self):
        text = self.next_record()
        if text is None:
            return 0
        self.record.set_text(text)
        return 1

    def getline_from(self, path):
        path = to_str(path)
        if path not in self.readers:
            try:
                f = open(path, encoding="utf-8", errors="surrogateescape", newline="\n")
            except OSError:
                return None
            self.readers[path] = RecordReader(f)
        return self._read_from(self.readers[path])

    def getline_cmd(self, cmd):
        cmd = to_str(cmd)
        if cmd not in self.readers:
            self.stdout.flush()
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, text=True,
                                 errors="surrogateescape")
            self.procs[cmd] = p
            self.readers[cmd] = RecordReader(p.stdout)
        return self._read_from(self.readers[cmd])

    def _read_from(self, reader):
        text = reader.read(self.var("RS"))
        return None if text is None else Field(text)

    # -- string built-ins ----------------------------------------------
    def matches(self, pat, s=None):
        s = str(self.record) if s is None else to_str(s)
        return regex(pat).search(s) is not None

    def match(self, s, pat):
        m = regex(pat).search(to_str(s))
        self.ns["RSTART"] = m.start() + 1 if m else 0
        self.ns["RLENGTH"] = m.end() - m.start() if m else -1
        return self.ns["RSTART"]

    @staticmethod
    def _subst(pat, repl, text, count):
        repl = to_str(repl)

        def expand(m):
            out, i = [], 0
            while i < len(repl):
                c = repl[i]
                if c == "\\" and i + 1 < len(repl) and repl[i + 1] in "&\\":
                    out.append(repl[i + 1])
                    i += 1
                elif c == "&":
                    out.append(m.group(0))
                else:
                    out.append(c)
                i += 1
            return "".join(out)

        return regex(pat).subn(expand, text, count=count)

    def _sub(self, pat, repl, target, count):
        if target is None:
            new, n = self._subst(pat, repl, str(self.record), count)
            if n:
                self.record[0] = new
            return n
        return Field(self._subst(pat, repl, to_str(target), count)[0])

    def sub(self, pat, repl, target=None):
        """Replace the first match.  Returns the count when working on $0,
        otherwise the new string for ``target``."""
        return self._sub(pat, repl, target, 1)

    def gsub(self, pat, repl, target=None):
        return self._sub(pat, repl, target, 0)

    def split(self, s, sep=None):
        sep = self.var("FS") if sep is None else to_str(sep)
        return [Field(x) for x in split_text(to_str(s), sep)]

    def length(self, x=None):
        if x is None:
            return len(str(self.record))
        if isinstance(x, (list, dict, tuple, set)):
            return len(x)
        return len(to_str(x, self.var("OFMT")))

    @staticmethod
    def substr(s, m, n=None):
        s = to_str(s)
        start = round(to_num(m))
        end = len(s) + 1 if n is None else start + round(to_num(n))
        start, end = max(start, 1), min(end, len(s) + 1)
        return Field(s[start - 1:end - 1]) if end > start else Field("")

    @staticmethod
    def index(s, t):
        return to_str(s).find(to_str(t)) + 1

    def srand(self, seed=None):
        prev, self._seed = self._seed, int(time.time()) if seed is None else to_num(seed)
        random.seed(self._seed)
        return prev

    def _exit(self, code=None):
        raise Exit(None if code is None else int(to_num(code)))

    def _next(self):
        raise NextRecord()

    def _nextfile(self):
        raise NextFile()

    def _install_builtins(self):
        ns = self.ns
        ns.update({
            "print": self.print_, "printf": self.printf, "sprintf": self.sprintf,
            "length": self.length, "substr": self.substr, "index": self.index,
            "split": self.split, "match": self.match, "matches": self.matches,
            "sub": self.sub, "gsub": self.gsub,
            "tolower": lambda s: Field(to_str(s).lower()),
            "toupper": lambda s: Field(to_str(s).upper()),
            "num": to_num, "str": to_str,
            "rand": random.random, "srand": self.srand,
            "system": self.system, "close": self.close, "fflush": self.fflush,
            "getline": self.getline, "getline_from": self.getline_from,
            "getline_cmd": self.getline_cmd,
            "next": self._next, "nextfile": self._nextfile, "exit": self._exit,
            "math": math, "re": re, "os": os, "sys": sys,
        })
