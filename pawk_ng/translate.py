"""Stage 2: rewrite the awk-isms in a token list into plain Python."""
# After this stage the text is ordinary Python that `compile()` accepts.
# The rewrites are deliberately few, and each one is a *text* substitution
# on tokens, never a semantic change:
#
# | awk-ism           | becomes                    |
# |-------------------|----------------------------|
# | `$expr`           | `F[expr]`                  |
# | `&&`, `||`, `!`   | ` and `, ` or `, ` not `   |
# | `/regex/`         | `re.search('regex', F[0])` |
# | `next`, `nextfile`| `next()`, `nextfile()`     |
# | `exit`, `exit N`  | `exit()`, `exit(N)`        |
#
# Because strings and comments are single tokens, nothing inside them is
# ever touched -- which is also why `$1` does not work inside an f-string.
from .errors import ProgramError
from .lexer import index_of_closing_bracket, index_of_next_significant, next_significant_token

_LOGICAL_OPERATORS = {"&&": " and ", "||": " or ", "!": " not "}


def translate_field_reference(tokens, dollar_index):
    """Translate the ``$operand`` at ``tokens[dollar_index]``.

    Returns ``(python_code, index_after_the_operand)``.

    The operand binds like awk's: `$NF-1` is `F[NF]-1`, `$(i+1)` is
    `F[(i+1)]`, `$$1` is `F[F[1]]`, and a subscript only belongs to a *name*
    (`$a[1]` is `F[a[1]]`) never to a number (`$1[:2]` is `F[1][:2]`)."""
    operand_index = dollar_index + 1
    if operand_index >= len(tokens):
        raise ProgramError("'$' needs an operand")
    kind, text = tokens[operand_index]
    if kind == "op" and text == "$":
        inner, after = translate_field_reference(tokens, operand_index)
        return "F[%s]" % inner, after
    if kind == "op" and text == "(":
        close = index_of_closing_bracket(tokens, operand_index)
        return "F[(%s)]" % translate(tokens[operand_index + 1:close]), close + 1
    if kind in ("word", "num"):
        code, after = text, operand_index + 1
        while kind == "word" and after < len(tokens) and tokens[after] == ("op", "["):
            close = index_of_closing_bracket(tokens, after)
            code += "[%s]" % translate(tokens[after + 1:close])
            after = close + 1
        return "F[%s]" % code, after
    raise ProgramError("'$' needs a field number or variable, got %r" % text)


def translate(tokens):
    """Return the Python source for a token list."""
    output, index = [], 0
    while index < len(tokens):
        kind, text = tokens[index]
        if kind == "op":
            if text == "$":
                code, index = translate_field_reference(tokens, index)
                output.append(code)
                continue
            output.append(_LOGICAL_OPERATORS.get(text, text))
        elif kind == "regex":
            output.append("re.search(%r, F[0])" % text)
        elif kind == "word" and text == "print" and (
                next_significant_token(tokens, index) != ("op", "(")):
            raise ProgramError("print is Python's print: write print(...) with parentheses")
        elif kind == "word" and text in ("next", "nextfile", "exit"):
            code, index = translate_statement_keyword(tokens, index, output)
            output.append(code)
            continue
        else:
            output.append(text)
        index += 1
    return "".join(output)


def translate_statement_keyword(tokens, index, output_so_far):
    """`next`, `nextfile` and `exit [value]` written without parentheses.

    Left alone when they are already a call (`exit(2)`), an attribute
    (`x.next`) or being assigned (`next = 3`).  Returns
    ``(python_code, index_after_it)``."""
    keyword = tokens[index][1]
    previous_text = output_so_far[-1] if output_so_far else ""
    next_index = index_of_next_significant(tokens, index)
    following = tokens[next_index] if next_index < len(tokens) else ("nl", "")
    if previous_text.endswith(".") or following in (("op", "("), ("op", "=")):
        return keyword, index + 1
    if keyword == "exit" and following[0] in ("num", "word", "str"):
        return "exit(%s)" % following[1], next_index + 1
    return keyword + "()", index + 1
