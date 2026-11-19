"""Unit tests: RecordReader, Record/NF, and the awk built-in functions."""
import io

import pytest

import pawk_ng as pawk
from pawk_ng.runtime import RecordReader, Runtime, unescape


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


class TestStdout:
    def test_builtin_print_goes_to_the_program_stdout_and_is_restored(self):
        import sys
        before = sys.stdout
        out = io.StringIO()
        pawk.run("BEGIN { print('hi', 1.0, sep='-') }", stdout=out)
        assert out.getvalue() == "hi-1.0\n" and sys.stdout is before

    def test_stdout_restored_after_an_error(self):
        import sys
        before = sys.stdout
        with pytest.raises(pawk.PawkError):
            pawk.run("BEGIN { 1 / 0 }", stdout=io.StringIO())
        assert sys.stdout is before

    def test_ofmt_used_when_assigning_floats_to_fields(self):
        rt = runtime()
        rt.ns["OFMT"] = "%.2f"
        rt.record.set_text("x y")
        rt.record[1] = 3.14159
        assert str(rt.record) == "3.14 y"


class TestNamespace:
    def test_no_awk_functions_only_python(self):
        rt = runtime()
        for name in ("length", "substr", "index", "split", "sub", "gsub", "match",
                     "sprintf", "printf", "tolower", "toupper", "getline", "system",
                     "close", "RSTART", "RLENGTH", "print"):
            assert name not in rt.ns

    def test_awk_variables_and_statements_present(self):
        rt = runtime()
        for name in ("NR", "NF", "FNR", "FS", "OFS", "RS", "ORS", "FILENAME", "SUBSEP",
                     "OFMT", "ENVIRON", "ARGV", "ARGC", "F", "next", "exit",
                     "nextfile"):
            assert name in rt.ns
