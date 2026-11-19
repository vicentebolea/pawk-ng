"""Stage 1 of reading a program: cut the text into tokens."""
# pawk programs are Python with a few awk-isms.  Python's own tokenizer
# cannot read them (`$1` and `/regex/` are not Python), and a full parser
# would be overkill: all we need to know is *where strings, comments and
# brackets are*, so that the translator can safely rewrite the awk-isms and
# the rule parser can find where one rule ends and the next begins.
#
# The lexer therefore produces a flat list of `(kind, text)` pairs.  The
# kinds are `ws`, `nl`, `comment`, `str`, `regex`, `num`, `word` and `op`.
# Joining the text of all tokens gives the source back (a `regex` token
# keeps only the pattern, without its slashes).
import re

from .errors import ProgramError

# ## Token shapes
#
# A number right after `$` is only digits (`$1.upper()` is field 1, then
# `.upper()`), anywhere else it is a Python-ish number (`1e5`, `0x1f`).
_FIELD_NUMBER = re.compile(r"\d+")
_NUMBER = re.compile(r"(?:\d|\.\d)[\w.]*")
_NAME = re.compile(r"[A-Za-z_]\w*")
_WHITESPACE = re.compile(r"(?:[ \t\r\f]|\\\n)+")

# ## Is a `/` a regex or a division?
#
# The one genuinely ambiguous character.  A `/` starts a regex literal only
# where a *value* may begin: at the start of the program, after a newline,
# or after one of these tokens.  After a name, a number, a string or a
# closing bracket it is a division.
TOKENS_THAT_ALLOW_A_REGEX_NEXT = {
    "(", ",", "!", "&&", "||", "and", "or", "not", "{", "}", ";",
}
_TWO_CHARACTER_OPERATORS = ("&&", "||", "!=")


def end_of_string(text, start):
    """Index just past the string literal that starts at ``text[start]``."""
    quote_char = text[start]
    quote = quote_char * 3 if text.startswith(quote_char * 3, start) else quote_char
    position = start + len(quote)
    while position < len(text):
        if text[position] == "\\":
            position += 2
        elif text.startswith(quote, position):
            return position + len(quote)
        elif len(quote) == 1 and text[position] == "\n":
            break
        else:
            position += 1
    raise ProgramError("unterminated string: %s" % text[start:start + 20].split("\n")[0])


def end_of_regex(text, start):
    """Index of the closing '/' of the regex literal starting at ``start``.

    A `/` inside a bracket expression (`[/]`) or after a backslash does not
    close the regex."""
    position, inside_brackets = start + 1, False
    while position < len(text) and text[position] != "\n":
        char = text[position]
        if char == "\\":
            position += 1
        elif char == "[":
            inside_brackets = True
        elif char == "]":
            inside_brackets = False
        elif char == "/" and not inside_brackets:
            return position
        position += 1
    raise ProgramError("unterminated regular expression: %s" % text[start:start + 20])


def tokenize(text, regex_mode=False):
    """Return a list of `(kind, text)` tokens for ``text``.

    ``regex_mode`` turns on `/regex/` literals.  It is used for the program
    as a whole, where a rule may start with a regex pattern; inside an
    action every `/` is a division."""
    tokens, position = [], 0
    regex_may_start_here = True
    while position < len(text):
        char = text[position]
        match = _WHITESPACE.match(text, position)
        if match:
            tokens.append(("ws", match.group()))
            position = match.end()
            continue
        if char == "\n":
            tokens.append(("nl", char))
            position += 1
            regex_may_start_here = True  # a new line starts a statement or a rule
            continue
        if char == "#":
            end = text.find("\n", position)
            end = len(text) if end < 0 else end
            tokens.append(("comment", text[position:end]))
            position = end
            continue
        if char in "'\"":
            end = end_of_string(text, position)
            tokens.append(("str", text[position:end]))
            position, regex_may_start_here = end, False
            continue
        if char == "/" and regex_mode and regex_may_start_here:
            end = end_of_regex(text, position)
            tokens.append(("regex", text[position + 1:end].replace("\\/", "/")))
            position, regex_may_start_here = end + 1, False
            continue
        after_dollar = bool(tokens) and tokens[-1] == ("op", "$")
        match = (_FIELD_NUMBER if after_dollar else _NUMBER).match(text, position)
        if match:
            tokens.append(("num", match.group()))
            position, regex_may_start_here = match.end(), False
            continue
        match = _NAME.match(text, position)
        if match:
            name = match.group()
            tokens.append(("word", name))
            position = match.end()
            regex_may_start_here = name in TOKENS_THAT_ALLOW_A_REGEX_NEXT
            continue
        two_chars = text[position:position + 2]
        operator = two_chars if two_chars in _TWO_CHARACTER_OPERATORS else char
        tokens.append(("op", operator))
        position += len(operator)
        regex_may_start_here = operator in TOKENS_THAT_ALLOW_A_REGEX_NEXT
    return tokens


# ## Walking a token list
#
# Small helpers shared by the translator and the rule parser.

def index_of_next_significant(tokens, index):
    """Index of the first token after ``index`` that is not whitespace or a comment."""
    index += 1
    while index < len(tokens) and tokens[index][0] in ("ws", "comment"):
        index += 1
    return index


def next_significant_token(tokens, index):
    """The first significant token after ``index``, or a harmless newline at the end."""
    following = index_of_next_significant(tokens, index)
    return tokens[following] if following < len(tokens) else ("nl", "")


def index_of_closing_bracket(tokens, opening_index):
    """Index of the token closing the bracket opened at ``tokens[opening_index]``."""
    closers = {"(": ")", "[": "]", "{": "}"}
    depth = 0
    for index in range(opening_index, len(tokens)):
        kind, text = tokens[index]
        if kind == "op" and text in closers:
            depth += 1
        elif kind == "op" and text in closers.values():
            depth -= 1
            if depth == 0:
                return index
    raise ProgramError("unbalanced brackets")
