"""Unit tests: RecordReader, Record/NF, and the awk built-in functions."""
import io

import pytest

import pawk
from pawk.runtime import Record, RecordReader, Runtime, unescape


def reader(text):
    return RecordReader(io.StringIO(text))


def drain(r, rs="\n"):
    out = []
    while (x := r.read(rs)) is not None:
        out.append(x)
    return out


class TestRecordReader:
    def test_newline_records(self):
        assert drain(reader("a\nb\nc\n")) == ["a", "b", "c"]

    def test_no_trailing_newline(self):
        assert drain(reader("a\nb")) == ["a", "b"]

    def test_empty_input(self):
        assert drain(reader("")) == []

    def test_blank_lines_are_records(self):
        assert drain(reader("a\n\nb\n")) == ["a", "", "b"]

    def test_single_char_rs(self):
        assert drain(reader("a;b;c"), ";") == ["a", "b", "c"]
        assert drain(reader("a;b;"), ";") == ["a", "b"]

    def test_single_char_rs_keeps_trailing_newline_in_last_record(self):
        assert drain(reader("a;b\n"), ";") == ["a", "b\n"]

    def test_regex_rs(self):
        assert drain(reader("a12b345c"), "[0-9]+") == ["a", "b", "c"]

    def test_paragraph_mode(self):
        assert drain(reader("a\nb\n\n\n\nc\nd\n"), "") == ["a\nb", "c\nd"]
        assert drain(reader("\n\na\n"), "") == ["a"]
        assert drain(reader("\n\n"), "") == []

    def test_rs_can_change_between_reads(self):
        r = reader("a b\nc;d;e\n")
        assert r.read("\n") == "a b"
        assert r.read(";") == "c"
        assert r.read(";") == "d"
        assert r.read("\n") == "e"
        assert r.read("\n") is None

    def test_crlf_is_not_translated(self):
        assert drain(reader("a\r\nb\r\n")) == ["a\r", "b\r"]


class TestUnescape:
    @pytest.mark.parametrize("s,exp", [
        ("a\\tb", "a\tb"), ("a\\nb", "a\nb"), ("\\\\", "\\"), ("\\q", "\\q"),
        ("plain", "plain"), ('\\"', '"'),
    ])
    def test_unescape(self, s, exp):
        assert unescape(s) == exp


def runtime():
    return Runtime("", stdin=io.StringIO(""), stdout=io.StringIO(), stderr=io.StringIO())


class TestRecord:
    def test_set_text_splits_and_sets_nf(self):
        rt = runtime()
        rt.record.set_text("a b c")
        assert rt.ns["NF"] == 3 and rt.record[2] == "b" and rt.record[0] == "a b c"

    def test_out_of_range_field_is_empty(self):
        rt = runtime()
        rt.record.set_text("a")
        assert rt.record[5] == "" and rt.ns["NF"] == 1   # reading never extends

    def test_assign_field_rebuilds_record_with_ofs(self):
        rt = runtime()
        rt.ns["OFS"] = "-"
        rt.record.set_text("a b c")
        rt.record[2] = "X"
        assert rt.record[0] == "a-X-c"

    def test_assign_beyond_nf_pads(self):
        rt = runtime()
        rt.record.set_text("a")
        rt.record[4] = "d"
        assert rt.ns["NF"] == 4 and rt.record[0] == "a   d"

    def test_assign_record_resplits(self):
        rt = runtime()
        rt.record.set_text("a b")
        rt.record[0] = "x y z"
        assert rt.ns["NF"] == 3 and rt.record[3] == "z"

    def test_nf_assignment_truncates_and_extends(self):
        rt = runtime()
        rt.record.set_text("a b c")
        rt.ns["NF"] = 2
        assert str(rt.record) == "a b"
        rt.ns["NF"] = 4
        assert str(rt.record) == "a b  " and rt.record[4] == ""

    def test_negative_index_and_nf(self):
        rt = runtime()
        rt.record.set_text("a")
        with pytest.raises(pawk.PawkError):
            rt.record[-1]
        rt.ns["NF"] = -1
        with pytest.raises(pawk.PawkError):
            len(rt.record)

    def test_iter_and_len_skip_field_zero(self):
        rt = runtime()
        rt.record.set_text("a b c")
        assert list(rt.record) == ["a", "b", "c"] and len(rt.record) == 3

    def test_non_string_assignment_is_formatted(self):
        rt = runtime()
        rt.record.set_text("a b")
        rt.record[1] = 2.0
        rt.record[2] = 0.5
        assert str(rt.record) == "2 0.5"

    def test_fields_are_Field_instances(self):
        rt = runtime()
        rt.record.set_text("10 abc")
        assert rt.record[1] > 9 and rt.record[1].is_num and not rt.record[2].is_num

    def test_index_can_be_a_field(self):
        rt = runtime()
        rt.record.set_text("2 x y")
        assert rt.record[rt.record[1]] == "x"


@pytest.fixture
def rt():
    return runtime()


class TestStringBuiltins:
    @pytest.mark.parametrize("s,m,n,exp", [
        ("hello", 2, 3, "ell"), ("hello", 2, None, "ello"), ("hello", 0, 3, "he"),
        ("hello", -1, 3, "h"), ("hello", 4, 10, "lo"), ("hello", 6, 1, ""),
        ("hello", 1, 0, ""), ("hello", 1, -1, ""), ("hello", 1.5, 1, "e"),
        ("hello", "2", "2", "el"), ("", 1, 1, ""),
    ])
    def test_substr(self, rt, s, m, n, exp):
        assert rt.substr(s, m, n) == exp

    def test_index(self, rt):
        assert rt.index("hello", "l") == 3 and rt.index("hello", "z") == 0
        assert rt.index("hello", "") == 1

    def test_length(self, rt):
        rt.record.set_text("abcd")
        assert rt.length() == 4 and rt.length("xy") == 2 and rt.length(12345) == 5
        assert rt.length([1, 2, 3]) == 3 and rt.length({}) == 0

    def test_split(self, rt):
        assert rt.split("a:b:c", ":") == ["a", "b", "c"]
        assert rt.split("a  b") == ["a", "b"]
        assert rt.split("") == []
        assert rt.split("a1b", "[0-9]") == ["a", "b"]

    def test_split_uses_current_fs(self, rt):
        rt.ns["FS"] = ","
        assert rt.split("a,b c") == ["a", "b c"]

    def test_split_results_are_strnums(self, rt):
        assert rt.split("10 9")[0] > rt.split("10 9")[1]

    def test_match_sets_rstart_rlength(self, rt):
        assert rt.match("foobar", "o+") == 2
        assert (rt.ns["RSTART"], rt.ns["RLENGTH"]) == (2, 2)
        assert rt.match("foobar", "z") == 0
        assert (rt.ns["RSTART"], rt.ns["RLENGTH"]) == (0, -1)

    def test_match_posix_class(self, rt):
        assert rt.match("ab12", "[[:digit:]]+") == 3

    def test_sub_on_target_returns_string(self, rt):
        assert rt.sub("a", "X", "banana") == "bXnana"
        assert rt.gsub("a", "X", "banana") == "bXnXnX"

    def test_ampersand_and_escapes_in_replacement(self, rt):
        assert rt.gsub("[aeiou]", "<&>", "hello") == "h<e>ll<o>"
        assert rt.gsub("[aeiou]", "\\&", "hello") == "h&ll&"
        assert rt.sub("l", "\\\\", "hello") == "he\\lo"

    def test_gsub_empty_match(self, rt):
        assert rt.gsub("x*", "-", "abc") == "-a-b-c-"

    def test_sub_without_target_edits_record(self, rt):
        rt.record.set_text("foo foo")
        assert rt.sub("foo", "bar") == 1 and str(rt.record) == "bar foo"
        assert rt.gsub("foo|bar", "z") == 2 and str(rt.record) == "z z"
        assert rt.ns["NF"] == 2

    def test_sub_no_match_leaves_record_and_returns_zero(self, rt):
        rt.record.set_text("a b")
        assert rt.gsub("z", "y") == 0 and str(rt.record) == "a b"

    def test_matches(self, rt):
        rt.record.set_text("hello world")
        assert rt.matches("wor") and not rt.matches("^wor") and rt.matches("^w", "wx")

    def test_case_functions(self, rt):
        assert rt.ns["toupper"]("abC") == "ABC" and rt.ns["tolower"]("ABc") == "abc"


class TestSprintf:
    @pytest.mark.parametrize("fmt,args,exp", [
        ("%d", ("42",), "42"), ("%d", (3.9,), "3"), ("%d", ("abc",), "0"),
        ("%5d|", (42,), "   42|"), ("%-5d|", (42,), "42   |"), ("%05d", (42,), "00042"),
        ("%+d", (5,), "+5"), ("%x", (255,), "ff"), ("%X", (255,), "FF"),
        ("%o", (8,), "10"), ("%u", (7,), "7"), ("%i", (7,), "7"),
        ("%.2f", (3.14159,), "3.14"), ("%8.3f|", (3.14159,), "   3.142|"),
        ("%e", (1234.5,), "1.234500e+03"), ("%g", (0.0001,), "0.0001"),
        ("%s", ("x",), "x"), ("%5s|", ("ab",), "   ab|"), ("%-5s|", ("ab",), "ab   |"),
        ("%.2s", ("abcdef",), "ab"), ("%c", (65,), "A"), ("%c", ("hello",), "h"),
        ("%c", ("",), ""), ("%%", (), "%"), ("100%%", (), "100%"),
        ("%s %s", ("a",), "a "), ("%d", (), "0"), ("%*d", (4, 7), "   7"),
        ("%.*f", (1, 2.75), "2.8"), ("%s", (1.0,), "1"), ("%s", (0.5,), "0.5"),
        ("no format", (), "no format"), ("%5%", (), "%5%"), ("%z", (1,), "%z"),
    ])
    def test_sprintf(self, rt, fmt, args, exp):
        assert rt.sprintf(fmt, *args) == exp

    def test_c_with_numeric_field(self, rt):
        assert rt.sprintf("%c", pawk.Field("66")) == "B"

    def test_extra_args_ignored(self, rt):
        assert rt.sprintf("%d", 1, 2, 3) == "1"
