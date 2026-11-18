"""Unit tests: numeric strings, conversions, regex translation, splitting."""
import pytest

from pawk.values import Field, looks_numeric, regex, split_text, to_num, to_str


@pytest.mark.parametrize("s,exp", [
    ("12", 12), ("  12  ", 12), ("-3", -3), ("+4", 4), ("3.5", 3.5), (".5", 0.5),
    ("1e3", 1000.0), ("12abc", 12), ("abc", 0), ("", 0), ("0x1A", 0), ("1.5.2", 1.5),
])
def test_to_num(s, exp):
    assert to_num(s) == exp


def test_to_num_passthrough_and_none():
    assert to_num(None) == 0 and to_num(7) == 7 and to_num(2.5) == 2.5
    assert to_num(True) == 1


def test_to_num_int_vs_float_type():
    assert isinstance(to_num("12"), int)
    assert isinstance(to_num("12.0"), float)


@pytest.mark.parametrize("s,exp", [
    ("12", True), (" 12 ", True), ("1e3", True), ("-.5", True), ("", False),
    ("12a", False), ("a", False), ("0x10", False), (".", False),
])
def test_looks_numeric(s, exp):
    assert looks_numeric(s) is exp


@pytest.mark.parametrize("x,exp", [
    (3, "3"), (3.0, "3"), (0.1, "0.1"), (1 / 3, "0.333333"), (1e20, "100000000000000000000"),
    (None, ""), ("s", "s"), (True, "1"), (False, "0"), (-0.0, "0"),
    (float("inf"), "inf"), (float("-inf"), "-inf"), (float("nan"), "nan"),
])
def test_to_str(x, exp):
    assert to_str(x) == exp


def test_to_str_custom_ofmt():
    assert to_str(3.14159, "%.2f") == "3.14"
    assert to_str(3.0, "%.2f") == "3"


class TestField:
    def test_is_str(self):
        assert isinstance(Field("a"), str)
        assert Field("a") + "b" == "ab" and isinstance("a" + Field("b"), str)

    def test_numeric_comparison(self):
        assert Field("10") > Field("9")           # string compare would say no
        assert Field("10") > 9 and Field("2.0") == 2 and Field(" 2 ") == Field("2.0")
        assert Field("9") < 10 and Field("9") <= 9 and Field("9") >= 9

    def test_string_comparison_when_not_numeric(self):
        assert Field("abc") < Field("abd")
        assert Field("10") < Field("9a")          # one side non numeric -> string
        assert Field("abc") != 0 and Field("abc") == "abc"
        assert Field("10") == "10" and Field("10") != "10.0"

    def test_number_against_non_numeric_field_uses_string(self):
        assert Field("a") > 1                     # "a" > "1"
        assert not (Field("") == 0)               # empty is not numeric

    def test_arithmetic(self):
        a, b = Field("7"), Field("2")
        assert a + b == 9 and a - b == 5 and a * b == 14 and a / b == 3.5
        assert a % b == 1 and a ** b == 49 and -a == -7 and +a == 7 and abs(Field("-3")) == 3
        assert 10 - a == 3 and 10 / b == 5 and 2 * a == 14 and 2 ** b == 4 and 1 + a == 8
        assert Field("abc") + 1 == 1 and Field("3x") * 2 == 6

    def test_mod_float(self):
        assert Field("7.5") % 2 == 1.5

    def test_str_format_operator_not_hijacked(self):
        assert "%s-%s" % (Field("a"), Field("b")) == "a-b"

    @pytest.mark.parametrize("s,truth", [
        ("0", False), ("1", True), ("", False), ("abc", True), ("0.0", False),
        (" 0 ", False), ("00", False), ("0a", True),
    ])
    def test_truthiness(self, s, truth):
        assert bool(Field(s)) is truth

    def test_int_float_conversion(self):
        assert int(Field("3.9")) == 3 and float(Field("3.5")) == 3.5 and int(Field("x")) == 0

    def test_hashable_as_dict_key(self):
        d = {}
        d[Field("a")] = 1
        d[Field("a")] += 1
        assert d == {"a": 2}

    def test_eq_with_other_types_not_implemented(self):
        assert Field("1") != None  # noqa: E711
        assert Field("1") != [1]


class TestRegex:
    def test_posix_classes(self):
        assert regex("^[[:digit:]]+$").match("123")
        assert regex("[[:alpha:]]+").search("12ab").group() == "ab"
        assert regex("[[:upper:][:digit:]]+").fullmatch("AB12")
        assert regex("^[[:space:]]+$").match(" \t")
        assert regex("[[:punct:]]").search("a,b").group() == ","

    def test_compiled_passthrough_and_cache(self):
        r = regex("a+")
        assert regex(r) is r and regex("a+") is r

    def test_non_str_pattern(self):
        assert regex(Field("a.c")).search("abc")


class TestSplit:
    def test_default_whitespace(self):
        assert split_text("  a \t b\n c ", " ") == ["a", "b", "c"]
        assert split_text("   ", " ") == []

    def test_single_char_is_literal(self):
        assert split_text("a|b||c", "|") == ["a", "b", "", "c"]
        assert split_text("a.b", ".") == ["a", "b"]
        assert split_text("a\\b", "\\") == ["a", "b"]

    def test_tab(self):
        assert split_text("a\t\tb", "\t") == ["a", "", "b"]

    def test_regex_fs(self):
        assert split_text("a1b22c", "[0-9]+") == ["a", "b", "c"]
        assert split_text("a, b,c", ", *") == ["a", "b", "c"]

    def test_regex_with_groups_does_not_leak_captures(self):
        assert split_text("a-1b-2c", "(-)[0-9]") == ["a", "b", "c"]

    def test_empty_fs_splits_chars(self):
        assert split_text("abc", "") == ["a", "b", "c"]

    def test_empty_text(self):
        assert split_text("", ":") == []

    def test_leading_and_trailing_separators_make_empty_fields(self):
        assert split_text(":a:", ":") == ["", "a", ""]

    def test_paragraph_mode_newline_also_separates(self):
        assert split_text("a:b\nc", ":", paragraph=True) == ["a", "b", "c"]
        assert split_text("a::b\nc", "::", paragraph=True) == ["a", "b", "c"]


class TestDefaultSplitting:
    def test_only_space_tab_newline_separate(self):
        assert split_text("a\r b\xa0c\x0b d", " ") == ["a\r", "b\xa0c\x0b", "d"]


class TestUninit:
    def test_acts_as_empty_string_and_zero(self):
        from pawk.values import Uninit
        u = Uninit()
        assert u == "" and u == 0 and not u and u + 1 == 1 and u + "x" == "x"
        assert u < 1 and u > -1 and u == Field("0") and u != Field("a")
        assert to_num(u) == 0 and to_str(u) == ""
