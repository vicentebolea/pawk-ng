"""Parse an awk-shaped program whose patterns and actions are Python.

    BEGIN { python statements }
    pattern { python statements }
    /regex/, $1 == "stop" { ... }
    END { ... }
    def helper(x): ...            # top-level Python definitions

The source is tokenized just enough to find rule boundaries and to rewrite
the few awk-isms that are not valid Python: ``$expr`` (field access),
``&&``, ``||``, ``!``, ``/regex/`` patterns and bare ``next``/``exit``.
"""
import ast
import re
import textwrap


class ProgramError(Exception):
    """Raised for a syntactically invalid program."""


class Rule:
    __slots__ = ("kind", "pattern", "pattern2", "code", "source", "assigned", "arrays")

    def __init__(self, kind, pattern=None, pattern2=None, code=None, source=""):
        self.kind = kind          # BEGIN, END, MAIN or DEF
        self.pattern = pattern    # compiled eval code, or None
        self.pattern2 = pattern2  # second pattern of a range rule
        self.code = code          # compiled exec code, None means "print $0"
        self.source = source
        # filled in by parse(): names assigned / subscripted anywhere in the program
        self.assigned = self.arrays = frozenset()

    def __repr__(self):
        return "Rule(%s, %r)" % (self.kind, self.source)


_INT = re.compile(r"\d+")
_WORD = re.compile(r"[A-Za-z_]\w*")
_NUM = re.compile(r"(?:\d|\.\d)[\w.]*")
_WS = re.compile(r"(?:[ \t\r\f]|\\\n)+")
_REGEX_OK_AFTER = {"(", ",", "!", "&&", "||", "and", "or", "not"}
_DEF_WORDS = ("def", "class", "import", "from", "async", "@")


def _string_end(text, i):
    q = text[i]
    quote = q * 3 if text.startswith(q * 3, i) else q
    j = i + len(quote)
    while j < len(text):
        if text[j] == "\\":
            j += 2
        elif text.startswith(quote, j):
            return j + len(quote)
        elif len(quote) == 1 and text[j] == "\n":
            break
        else:
            j += 1
    raise ProgramError("unterminated string: %s" % text[i:i + 20].split("\n")[0])


def _regex_end(text, i):
    """Index of the closing '/' of the regex literal starting at ``i``."""
    j, in_br = i + 1, False
    while j < len(text) and text[j] != "\n":
        c = text[j]
        if c == "\\":
            j += 1
        elif c == "[":
            in_br = True
        elif c == "]":
            in_br = False
        elif c == "/" and not in_br:
            return j
        j += 1
    raise ProgramError("unterminated regular expression: %s" % text[i:i + 20])


def tokenize(text, regex_mode=False):
    """Return a list of (kind, text) tokens.  Concatenating the text of every
    token except 'regex' ones gives back the input."""
    toks, i, n = [], 0, len(text)
    allowed = True
    while i < n:
        c = text[i]
        m = _WS.match(text, i)
        if m:
            toks.append(("ws", m.group()))
            i = m.end()
            continue
        if c == "\n":
            toks.append(("nl", c))
            i += 1
            continue
        if c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            toks.append(("comment", text[i:j]))
            i = j
            continue
        if c in "'\"":
            j = _string_end(text, i)
            toks.append(("str", text[i:j]))
            i, allowed = j, False
            continue
        if c == "/" and regex_mode and allowed:
            j = _regex_end(text, i)
            toks.append(("regex", text[i + 1:j].replace("\\/", "/")))
            i, allowed = j + 1, False
            continue
        m = (_INT if toks and toks[-1] == ("op", "$") else _NUM).match(text, i)
        if m:
            toks.append(("num", m.group()))
            i, allowed = m.end(), False
            continue
        m = _WORD.match(text, i)
        if m:
            w = m.group()
            toks.append(("word", w))
            i, allowed = m.end(), w in _REGEX_OK_AFTER
            continue
        op = text[i:i + 2] if text[i:i + 2] in ("&&", "||", "!=") else c
        toks.append(("op", op))
        i += len(op)
        allowed = op in _REGEX_OK_AFTER
    return toks


def _next_sig(toks, k):
    k += 1
    while k < len(toks) and toks[k][0] in ("ws", "comment"):
        k += 1
    return k


def _group_end(toks, k):
    """Index of the token closing the bracket opened at toks[k]."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    depth = 0
    for j in range(k, len(toks)):
        kind, t = toks[j]
        if kind == "op" and t in pairs:
            depth += 1
        elif kind == "op" and t in pairs.values():
            depth -= 1
            if depth == 0:
                return j
    raise ProgramError("unbalanced brackets")


def _dollar(toks, k):
    """Translate the ``$operand`` starting at toks[k]; return (code, next k)."""
    k += 1
    if k >= len(toks):
        raise ProgramError("'$' needs an operand")
    kind, t = toks[k]
    if kind == "op" and t == "$":
        inner, k = _dollar(toks, k - 0)
        return "F[%s]" % inner, k
    if kind == "op" and t == "(":
        e = _group_end(toks, k)
        return "F[(%s)]" % translate(toks[k + 1:e]), e + 1
    if kind in ("word", "num"):
        code, k = t, k + 1
        while kind == "word" and k < len(toks) and toks[k] == ("op", "["):
            e = _group_end(toks, k)
            code += "[%s]" % translate(toks[k + 1:e])
            k = e + 1
        return "F[%s]" % code, k
    raise ProgramError("'$' needs a field number or variable, got %r" % t)


def _next_tok(toks, k):
    j = _next_sig(toks, k)
    return toks[j] if j < len(toks) else ("nl", "")


def _bare(toks, k, out):
    """True when the word at toks[k] is used awk-style, without a call."""
    j = _next_sig(toks, k)
    nxt = toks[j] if j < len(toks) else ("nl", "")
    return not (out and out[-1].endswith(".")) and nxt not in (("op", "("), ("op", "="))


def translate(toks):
    out, k = [], 0
    while k < len(toks):
        kind, t = toks[k]
        if kind == "op":
            if t == "$":
                code, k = _dollar(toks, k)
                out.append(code)
                continue
            out.append({"&&": " and ", "||": " or ", "!": " not "}.get(t, t))
        elif kind == "regex":
            out.append("re.search(%r, F[0])" % t)
        elif kind == "word" and t == "print" and _next_tok(toks, k) != ("op", "("):
            raise ProgramError("print is Python's print: write print(...) with parentheses")
        elif kind == "word" and t in ("next", "nextfile", "exit"):
            prev = out[-1] if out else ""
            j = _next_sig(toks, k)
            nxt = toks[j] if j < len(toks) else ("nl", "")
            if prev.endswith(".") or nxt == ("op", "(") or nxt == ("op", "="):
                out.append(t)
            elif t == "exit" and nxt[0] in ("num", "word", "str"):
                out.append("exit(%s)" % nxt[1])
                k = j
            else:
                out.append(t + "()")
        else:
            out.append(t)
        k += 1
    return "".join(out)


def _dedent(body):
    if "\n" not in body:
        return body.strip()
    first, rest = body.split("\n", 1)
    return (first.strip() + "\n" + textwrap.dedent(rest)).strip("\n")


def _compile(src, mode, what, sources):
    try:
        sources.append((src, mode))
        return compile(src, "<%s>" % what, mode)
    except SyntaxError as e:
        raise ProgramError("%s: %s (in %r)" % (what, e.msg, src.strip())) from None


class _Parser:
    def __init__(self, src):
        self.toks = tokenize(src, regex_mode=True)
        self.src = src
        self.k = 0
        self.sources = []  # (python source, ast mode) of everything compiled

    def peek(self):
        return self.toks[self.k] if self.k < len(self.toks) else ("eof", "")

    def skip_blank(self):
        while self.peek()[0] in ("ws", "nl", "comment") or self.peek() == ("op", ";"):
            self.k += 1

    def at_line_start(self):
        return self.k == 0 or self.toks[self.k - 1][0] == "nl"

    def parse(self):
        rules = []
        while True:
            self.skip_blank()
            kind, t = self.peek()
            if kind == "eof":
                return rules
            if self.at_line_start() and (
                    (kind == "word" and t in _DEF_WORDS) or (kind, t) == ("op", "@")):
                rules.append(self.definition())
            elif kind == "word" and t in ("BEGIN", "END") and self._brace_next():
                self.k += 1
                rules.append(self.action_rule(t))
            elif kind == "word" and t in ("BEGIN", "END"):
                raise ProgramError("%s requires an action" % t)
            else:
                rules.append(self.main_rule())

    def _brace_next(self):
        j = _next_sig(self.toks, self.k)
        return j < len(self.toks) and self.toks[j] == ("op", "{")

    def definition(self):
        start = self.k
        while self.k < len(self.toks):
            kind, t = self.toks[self.k]
            self.k += 1
            if kind == "nl":
                nxt = self.peek()
                if nxt[0] in ("ws",) or nxt[0] == "nl":
                    continue
                if nxt[0] == "comment":
                    continue
                break
        src = "".join(t for _, t in self.toks[start:self.k]).rstrip()
        code = _compile(translate(tokenize(src)) + "\n", "exec", "definition", self.sources)
        return Rule("DEF", code=code, source=src)

    def body(self):
        """Consume '{' ... '}' and return its translated, compiled body."""
        self.skip_blank()
        if self.peek() != ("op", "{"):
            raise ProgramError("expected '{'")
        e = _group_end(self.toks, self.k)
        raw = "".join(t if kd != "regex" else "/%s/" % t
                      for kd, t in self.toks[self.k + 1:e])
        self.k = e + 1
        src = _dedent(translate(tokenize(raw)))
        return _compile(src + "\n", "exec", "action", self.sources), src

    def action_rule(self, kind):
        code, src = self.body()
        return Rule(kind, code=code, source=src)

    def main_rule(self):
        parts, cur, depth = [], [], 0
        while True:
            kind, t = self.peek()
            if kind == "eof" or kind == "nl" and depth == 0:
                break
            if kind == "op":
                if t == "{" and depth == 0:
                    break
                if t == ";" and depth == 0:
                    break
                if t in "([{":
                    depth += 1
                elif t in ")]}":
                    depth -= 1
                elif t == "," and depth == 0:
                    parts.append(cur)
                    cur = []
                    self.k += 1
                    continue
            cur.append((kind, t))
            self.k += 1
        parts.append(cur)
        if len(parts) > 2:
            raise ProgramError("a range pattern has exactly two parts")
        exprs = [translate(p).strip() for p in parts]
        if any(not e for e in exprs):
            if len(parts) == 1 and self.peek() == ("op", "{"):
                exprs = []
            else:
                raise ProgramError("empty pattern")
        pats = [_compile("(%s)" % e, "eval", "pattern", self.sources) for e in exprs]
        code = src = None
        if self.peek() == ("op", "{"):
            code, src = self.body()
        text = ", ".join(exprs)
        return Rule("MAIN", pats[0] if pats else None,
                    pats[1] if len(pats) > 1 else None, code,
                    "%s { %s }" % (text, src) if src is not None else text)


def analyze(tree):
    """Return (names assigned, names used as subscripted containers)."""
    names, arrays = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            arrays.add(node.value.id)
    return names, arrays


def parse(src):
    """Parse a program into rules.  Names the program assigns or subscripts
    are recorded on every rule: they are awk's implicit variables/arrays."""
    parser = _Parser(src)
    rules = parser.parse()
    names, arrays = set(), set()
    for code_src, mode in parser.sources:
        n, a = analyze(ast.parse(code_src, mode=mode))
        names |= n
        arrays |= a
    for r in rules:
        r.assigned, r.arrays = frozenset(names), frozenset(arrays)
    return rules
