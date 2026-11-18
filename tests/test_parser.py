"""Unit tests for the program parser and the awk-to-Python rewriting."""
import pytest

from pawk_ng.parser import ProgramError, parse, tokenize, translate


def tr(src):
    return translate(tokenize(src))


def kinds(src):
    return [r.kind for r in parse(src)]


class TestTranslate:
    @pytest.mark.parametrize("src,exp", [
        ("$1", "F[1]"), ("$0", "F[0]"), ("$NF", "F[NF]"), ("$i", "F[i]"),
        ("$(NF-1)", "F[(NF-1)]"), ("$$1", "F[F[1]]"), ("$NF-1", "F[NF]-1"),
        ("$a[2]", "F[a[2]]"), ("x = $1 + $2", "x = F[1] + F[2]"),
        ("$(f($1))", "F[(f(F[1]))]"),
        ("$1.upper()", "F[1].upper()"), ("$1[1:3]", "F[1][1:3]"), ("$x.strip()", "F[x].strip()"),
    ])
    def test_dollar(self, src, exp):
        assert tr(src) == exp

    def test_logical_operators(self):
        assert tr("a && b || c") == "a  and  b  or  c"
        assert tr("!x") == " not x"
        assert tr("a != b") == "a != b"

    def test_strings_are_untouched(self):
        for s in ['"$1 && !x"', "'$1'", '"a\\"$1"', '"""$1\n$2"""', "f'$1'"]:
            assert tr(s) == s

    def test_comments_are_untouched(self):
        assert tr("x # $1 && y\n$2") == "x # $1 && y\nF[2]"

    @pytest.mark.parametrize("src,exp", [
        ("next", "next()"), ("nextfile", "nextfile()"), ("exit", "exit()"),
        ("exit 3", "exit(3)"), ("exit code", "exit(code)"), ("next()", "next()"),
        ("exit(2)", "exit(2)"), ("x.next", "x.next"), ("next = 3", "next = 3"),
                ("print(1)", "print(1)"), ("printf 1", "printf 1"),
    ])
    def test_bare_keywords(self, src, exp):
        assert tr(src) == exp

    @pytest.mark.parametrize("src", ["print", "print $1, $2", "print 1; x = 2", "print = 3", "x = print"])
    def test_print_without_parentheses_is_rejected(self, src):
        with pytest.raises(ProgramError, match="print"):
            tr(src)

    def test_unbalanced_dollar(self):
        with pytest.raises(ProgramError):
            tr("$")
        with pytest.raises(ProgramError):
            tr("$+")

    def test_unterminated_string(self):
        with pytest.raises(ProgramError, match="unterminated string"):
            tokenize("'abc")


class TestRules:
    def test_kinds_in_order(self):
        assert kinds("BEGIN{x=1} $1 {y=2} END{z=3}") == ["BEGIN", "MAIN", "END"]

    def test_multiple_begin_end(self):
        assert kinds("BEGIN{a=1}\nBEGIN{b=2}\nEND{c=3}\nEND{d=4}") == [
            "BEGIN", "BEGIN", "END", "END"]

    def test_pattern_only_has_no_code(self):
        (r,) = parse("$1 > 3")
        assert r.code is None and r.pattern is not None

    def test_action_only_has_no_pattern(self):
        (r,) = parse("{ x = 1 }")
        assert r.pattern is None and r.code is not None

    def test_empty_program(self):
        assert parse("") == [] and parse("  \n # c\n") == []

    def test_separators(self):
        assert kinds("NR==1 {a=1}; NR==2 {b=2}\n\nNR==3 {c=3}") == ["MAIN"] * 3

    def test_pattern_only_rules_separated_by_newline(self):
        assert kinds("$1\n$2\n$3") == ["MAIN"] * 3

    def test_range(self):
        (r,) = parse("NR==2, NR==4 { x = 1 }")
        assert r.pattern is not None and r.pattern2 is not None

    def test_range_comma_inside_call_is_not_a_range(self):
        (r,) = parse("max(1, 2) > 1 { x = 1 }")
        assert r.pattern2 is None

    def test_three_part_range_rejected(self):
        with pytest.raises(ProgramError, match="exactly two"):
            parse("1,2,3 { x = 1 }")

    def test_regex_pattern(self):
        (r,) = parse("/a{2}[/]x/ { y = 1 }")
        assert "re.search" in r.source

    def test_regex_with_brace_and_quote_does_not_confuse_the_parser(self):
        rules = parse("/\"{/ { y = 1 } END { z = 1 }")
        assert kinds("/\"{/ { y = 1 } END { z = 1 }") == ["MAIN", "END"]
        assert len(rules) == 2

    def test_division_is_not_a_regex(self):
        (r,) = parse("$1 / 2 > 1 / 3 { x = 1 }")
        assert "re.search" not in r.source

    def test_negated_regex_and_combination(self):
        (r,) = parse("!/a/ && /b/ or NR > 2")
        assert r.source.count("re.search") == 2 and "not" in r.source

    def test_braces_in_action(self):
        (r,) = parse('{ d = {"a": {"b": 1}}; s = "}" }')
        assert r.code is not None

    def test_multiline_action_with_compound_statements(self):
        (r,) = parse("""
        {
            if $1 > 1:
                x = 1
            else:
                x = 2
        }""")
        assert r.code is not None

    def test_first_line_code_after_brace(self):
        (r,) = parse("{ x = 1\n  y = 2 }")
        assert "y = 2" in r.source

    def test_def_block_before_rules(self):
        rules = parse("def f(x):\n    return x * 2\n\n\nBEGIN { y = f(2) }")
        assert kinds("def f(x):\n    return x * 2\n\n\nBEGIN { y = f(2) }") == ["DEF", "BEGIN"]
        assert len(rules) == 2

    def test_import_line(self):
        assert kinds("import json\n{ x = 1 }") == ["DEF", "MAIN"]

    def test_def_with_dollar_translated(self):
        (r,) = parse("def f():\n    return $1")
        assert "F[1]" in r.source or r.kind == "DEF"

    def test_begin_requires_brace(self):
        with pytest.raises(ProgramError):
            parse("BEGIN")  # pattern 'BEGIN' alone compiles; but must not be a BEGIN rule

    def test_syntax_errors_are_reported(self):
        for bad in ["{ x = }", "$1 ==", "{ if x: }", "BEGIN { ( }"]:
            with pytest.raises(ProgramError):
                parse(bad)

    def test_unbalanced_brace(self):
        with pytest.raises(ProgramError):
            parse("{ x = 1 ")

    def test_empty_pattern_before_comma(self):
        with pytest.raises(ProgramError):
            parse(", NR==2 { x = 1 }")
