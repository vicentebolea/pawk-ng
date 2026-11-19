"""Stage 3: turn program text into a list of rules.

    BEGIN { python statements }
    pattern { python statements }
    /regex/, $1 == "stop" { ... }
    END { ... }
    def helper(x): ...            # top-level Python definitions
"""
# A *rule* is the unit the interpreter runs.  This module is the only place
# that knows awk's rule grammar; it leans on the lexer to find boundaries and
# on the translator to turn each piece into Python, then hands the pieces to
# `compile()`.
#
# The grammar, in full:
#
#     program    := item*
#     item       := definition | "BEGIN" body | "END" body | rule
#     definition := a top-level `def`, `class`, `import`, `from`, `async`
#                   or decorator, plus the indented lines that follow it
#     rule       := [pattern ["," pattern]] [body]
#     body       := "{" python statements "}"
#
# A rule without a pattern runs for every record; a rule without a body
# prints the record; two patterns make a range.
import ast
import textwrap
from dataclasses import dataclass

from .errors import ProgramError
from .lexer import index_of_closing_bracket, index_of_next_significant, tokenize
from .translate import translate

__all__ = ["ProgramError", "Rule", "find_implicit_names", "parse", "tokenize", "translate"]

_KEYWORDS_THAT_START_A_DEFINITION = ("def", "class", "import", "from", "async", "@")


@dataclass(slots=True, repr=False)
class Rule:
    """One rule of the program, already compiled."""

    kind: str                      # BEGIN, END, MAIN or DEF
    pattern: object = None         # compiled eval code, or None (always runs)
    range_end_pattern: object = None  # second pattern of a range rule
    code: object = None            # compiled exec code, None means "print $0"
    source: str = ""               # translated source, for error messages
    # Names assigned / subscripted anywhere in the *whole* program; filled in
    # by `parse` so the interpreter can create awk's implicit variables.
    assigned_names: frozenset = frozenset()
    array_names: frozenset = frozenset()

    def __repr__(self):
        return "Rule(%s, %r)" % (self.kind, self.source)


def _dedent_action_body(body):
    """Remove the common indentation of a multi-line action body.

    The first line sits right after the `{`, so it is stripped on its own."""
    if "\n" not in body:
        return body.strip()
    first_line, other_lines = body.split("\n", 1)
    return (first_line.strip() + "\n" + textwrap.dedent(other_lines)).strip("\n")


class _RuleParser:
    """Recursive-descent reader over the token list of the whole program."""

    def __init__(self, program_text):
        self.tokens = tokenize(program_text, regex_mode=True)
        self.position = 0
        self.compiled_sources = []  # (python source, ast mode) of everything compiled

    # -- cursor helpers ------------------------------------------------
    def peek_token(self):
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return ("eof", "")

    def skip_blank_tokens(self):
        while self.peek_token()[0] in ("ws", "nl", "comment") or (
                self.peek_token() == ("op", ";")):
            self.position += 1

    def is_at_line_start(self):
        return self.position == 0 or self.tokens[self.position - 1][0] == "nl"

    def next_token_is_open_brace(self):
        following = index_of_next_significant(self.tokens, self.position)
        return following < len(self.tokens) and self.tokens[following] == ("op", "{")

    def compile_python(self, source, mode, what):
        """Compile translated source, remembering it for `find_implicit_names`."""
        self.compiled_sources.append((source, mode))
        try:
            return compile(source, "<%s>" % what, mode)
        except SyntaxError as error:
            raise ProgramError(
                "%s: %s (in %r)" % (what, error.msg, source.strip())) from None

    # -- the grammar ---------------------------------------------------
    def parse_program(self):
        rules = []
        while True:
            self.skip_blank_tokens()
            kind, text = self.peek_token()
            if kind == "eof":
                return rules
            starts_definition = self.is_at_line_start() and (
                (kind == "word" and text in _KEYWORDS_THAT_START_A_DEFINITION)
                or (kind, text) == ("op", "@"))
            if starts_definition:
                rules.append(self.parse_definition())
            elif kind == "word" and text in ("BEGIN", "END") and self.next_token_is_open_brace():
                self.position += 1
                code, source = self.parse_action_body()
                rules.append(Rule(text, code=code, source=source))
            elif kind == "word" and text in ("BEGIN", "END"):
                raise ProgramError("%s requires an action" % text)
            else:
                rules.append(self.parse_rule())

    def parse_definition(self):
        """A top-level `def`/`class`/`import`: the line and its indented block."""
        start = self.position
        while self.position < len(self.tokens):
            kind = self.tokens[self.position][0]
            self.position += 1
            if kind == "nl":
                if self.peek_token()[0] in ("ws", "nl", "comment"):
                    continue  # still inside the indented block
                break
        source = "".join(text for _, text in self.tokens[start:self.position]).rstrip()
        code = self.compile_python(translate(tokenize(source)) + "\n", "exec", "definition")
        return Rule("DEF", code=code, source=source)

    def parse_action_body(self):
        """Consume `{ ... }`; return its compiled code and translated source."""
        self.skip_blank_tokens()
        if self.peek_token() != ("op", "{"):
            raise ProgramError("expected '{'")
        close = index_of_closing_bracket(self.tokens, self.position)
        # Inside an action `/` is always a division, so give regex tokens back
        # their slashes and re-tokenize without regex mode.
        raw_body = "".join(text if kind != "regex" else "/%s/" % text
                           for kind, text in self.tokens[self.position + 1:close])
        self.position = close + 1
        source = _dedent_action_body(translate(tokenize(raw_body)))
        return self.compile_python(source + "\n", "exec", "action"), source

    def parse_rule(self):
        """`[pattern [, pattern]] [{ body }]`."""
        pattern_texts = self.parse_patterns()
        code = body_source = None
        if self.peek_token() == ("op", "{"):
            code, body_source = self.parse_action_body()
        compiled = [self.compile_python("(%s)" % text, "eval", "pattern")
                    for text in pattern_texts]
        patterns_text = ", ".join(pattern_texts)
        return Rule(
            "MAIN",
            pattern=compiled[0] if compiled else None,
            range_end_pattern=compiled[1] if len(compiled) > 1 else None,
            code=code,
            source=(patterns_text if body_source is None
                    else "%s { %s }" % (patterns_text, body_source)))

    def parse_patterns(self):
        """Read up to two comma-separated patterns, as translated Python text.

        The pattern ends at the `{` of the body, a `;`, a newline or the end,
        always outside any brackets."""
        pattern_parts, current_pattern, depth = [], [], 0
        while True:
            kind, text = self.peek_token()
            if kind == "eof" or (kind == "nl" and depth == 0):
                break
            if kind == "op":
                if text in ("{", ";") and depth == 0:
                    break
                if text in "([{":
                    depth += 1
                elif text in ")]}":
                    depth -= 1
                elif text == "," and depth == 0:
                    pattern_parts.append(current_pattern)
                    current_pattern = []
                    self.position += 1
                    continue
            current_pattern.append((kind, text))
            self.position += 1
        pattern_parts.append(current_pattern)
        if len(pattern_parts) > 2:
            raise ProgramError("a range pattern has exactly two parts")
        pattern_texts = [translate(part).strip() for part in pattern_parts]
        if any(not text for text in pattern_texts):
            if len(pattern_parts) == 1 and self.peek_token() == ("op", "{"):
                return []          # no pattern at all: runs for every record
            raise ProgramError("empty pattern")
        return pattern_texts


# ## Implicit variables
#
# awk programs use variables and arrays without declaring them.  Python
# would raise `NameError`, so after compiling we ask the `ast` module which
# names the program *assigns* and which it *subscripts*; those are the only
# names the interpreter will create on demand (as `""`/`0` and as an empty
# array).  A name that is never assigned stays a `NameError`, so typos are
# still caught.

def find_implicit_names(tree):
    """Return (names assigned, names used as subscripted containers)."""
    assigned, subscripted = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            assigned.add(node.id)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            assigned.update(node.names)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            subscripted.add(node.value.id)
    return assigned, subscripted


def parse(program_text):
    """Parse a program into rules.  Names the program assigns or subscripts
    are recorded on every rule: they are awk's implicit variables/arrays."""
    parser = _RuleParser(program_text)
    rules = parser.parse_program()
    assigned, subscripted = set(), set()
    for source, mode in parser.compiled_sources:
        more_assigned, more_subscripted = find_implicit_names(ast.parse(source, mode=mode))
        assigned |= more_assigned
        subscripted |= more_subscripted
    for rule in rules:
        rule.assigned_names = frozenset(assigned)
        rule.array_names = frozenset(subscripted)
    return rules
