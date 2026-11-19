"""Bogus values: garbage assigned to awk variables must give a defined result
or a clean error (never a traceback, a hang or runaway memory)."""
import pytest

import pawk_ng

pytestmark = pytest.mark.contract


def fails(status_awk, prog, text="a b c\n", match=None, **kw):
    with pytest.raises(pawk_ng.PawkError, match=match):
        status_awk(prog, text, **kw)


class TestNFBogus:
    @pytest.mark.parametrize("value,expected", [
        ("'abc'", "0"), ("''", "0"), ("None", "0"), ("'2x'", "2"), ("1.7", "1"),
        ("'2'", "2"), ("True", "1"), ("-0.5", "0"),
    ])
    def test_non_integer_values_are_converted_like_awk(self, run_awk, value, expected):
        prog = "{ NF = %s; print(len(F), NF) }" % value  # len(F) applies the assignment
        assert run_awk(prog, "a b c\n") == "%s %s\n" % (expected, expected)

    def test_negative_is_an_error(self, status_awk):
        fails(status_awk, "{ NF = -3 }", match="negative")

    def test_absurdly_large_is_an_error_not_memory_exhaustion(self, status_awk):
        fails(status_awk, "{ NF = 10 ** 12 }", match="too many fields")

    def test_assigning_a_far_field_is_an_error_too(self, status_awk):
        fails(status_awk, "{ $999999999999 = 1 }", match="too many fields")

    def test_a_list_counts_as_zero(self, run_awk):
        assert run_awk("{ NF = [1]; print(len(F)) }", "a b\n") == "0\n"


class TestFieldIndexBogus:
    @pytest.mark.parametrize("index,expected", [
        ("1.9", "a"), ("'2'", "b"), ("True", "a"), ("None", "a b c"), ("'abc'", "a b c"),
        ("''", "a b c"), ("100", ""),
    ])
    def test_index_is_converted_like_a_number(self, run_awk, index, expected):
        assert run_awk("{ print(F[%s]) }" % index, "a b c\n") == expected + "\n"

    def test_negative_index_is_an_error(self, status_awk):
        fails(status_awk, "{ print(F[-1]) }", match="field -1")

    def test_assigning_none_gives_an_empty_field(self, run_awk):
        assert run_awk("{ F[1] = None; print(F[0]) }", "a b\n") == " b\n"

    def test_dollar_needs_a_number_or_name(self, status_awk):
        with pytest.raises(pawk_ng.ProgramError):
            status_awk("{ print($'x') }")
        with pytest.raises(pawk_ng.ProgramError):
            status_awk("{ print($) }")


class TestNRAndFNRBogus:
    def test_non_numeric_nr_counts_from_zero(self, run_awk):
        assert run_awk("NR == 1 and not done { done = 1; NR = 'x' } { print(NR) }",
                       "a\nb\n") == "x\n1\n"

    def test_numeric_prefix_is_used(self, run_awk):
        assert run_awk("NR == 1 { NR = '7abc' } { print(NR) }", "a\nb\n") == "7abc\n8\n"

    def test_fnr_garbage_counts_from_zero(self, run_awk):
        assert run_awk("FNR == 1 and not done { done = 1; FNR = 'z' } { print(FNR) }",
                       "a\nb\n") == "z\n1\n"

    def test_float_nr(self, run_awk):
        assert run_awk("NR == 1 { NR = 1.5 } { print(NR) }", "a\nb\n") == "1.5\n2.5\n"


class TestSeparatorsBogus:
    @pytest.mark.parametrize("var", ["FS", "OFS", "RS", "ORS", "SUBSEP"])
    def test_non_string_values_become_strings(self, run_awk, var):
        assert run_awk("BEGIN { %s = 5; print(repr(%s)) }" % (var, var)) == "5\n"

    def test_fs_number_is_a_literal_separator(self, run_awk):
        assert run_awk("BEGIN { FS = 5 } { print(NF) }", "a5b5c\n") == "3\n"

    def test_fs_none_splits_characters(self, run_awk):
        assert run_awk("BEGIN { FS = None } { print(NF) }", "abc\n") == "3\n"

    def test_ofs_number_joins_with_it(self, run_awk):
        assert run_awk("BEGIN { OFS = 5 } { $1 = $1; print($0) }", "a b c\n") == "a5b5c\n"

    def test_rs_number_is_a_literal_separator(self, run_awk):
        assert run_awk("BEGIN { RS = 5 } { print($0) }", "a5b") == "a\nb\n"

    def test_rs_none_means_paragraph_mode(self, run_awk):
        assert run_awk("BEGIN { RS = None } { print(NR) }", "a\nb\n\nc\n") == "1\n2\n"

    @pytest.mark.parametrize("var,flag", [("FS", "fs"), ("RS", "assigns")])
    def test_invalid_regex_is_a_clean_error(self, status_awk, var, flag):
        kw = {"fs": "[a"} if flag == "fs" else {"assigns": ["RS=[a"]}
        fails(status_awk, "{ print($1) }", match="invalid regular expression", **kw)

    def test_invalid_regex_assigned_in_begin(self, status_awk):
        fails(status_awk, "BEGIN { FS = '(a' } { print($1) }", match="invalid regular expression")

    def test_single_bracket_is_a_literal_not_a_bad_regex(self, run_awk):
        assert run_awk("{ print($2) }", "a[b\n", fs="[") == "b\n"

    def test_lone_backslash_is_a_literal(self, run_awk):
        assert run_awk("BEGIN { FS = '\\\\' } { print($2) }", "a\\b\n") == "b\n"


class TestOFMTBogus:
    def test_text_without_a_conversion_is_an_error(self, status_awk):
        fails(status_awk, "BEGIN { OFMT = 'abc' } { $1 = 1.5 }", "x\n", match="TypeError")

    def test_too_many_conversions_is_an_error(self, status_awk):
        fails(status_awk, "BEGIN { OFMT = '%s %s' } { $1 = 1.5 }", "x\n", match="TypeError")

    def test_integer_conversion_truncates(self, run_awk):
        assert run_awk("BEGIN { OFMT = '%d' } { $1 = 1.5; print($0) }", "x\n") == "1\n"

    def test_unused_bogus_ofmt_is_harmless(self, run_awk):
        assert run_awk("BEGIN { OFMT = 'abc' } { $1 = 2; print($0) }", "x\n") == "2\n"

    def test_dash_v_ofmt_works_although_it_is_a_numeric_looking_string(self, run_awk):
        assert run_awk("{ $1 = 3.14159; print($0) }", "x\n", assigns=["OFMT=%.3f"]) == "3.142\n"


class TestCommandLineBogus:
    def test_dash_v_without_equals(self, cli):
        r = cli("-v", "novalue", "BEGIN { }")
        assert r.returncode == 2 and "var=value" in r.stderr and "Traceback" not in r.stderr

    @pytest.mark.parametrize("assignment", ["1x=3", "a b=3", "=3", "a-b=3", "$x=3"])
    def test_dash_v_with_an_invalid_name(self, cli, assignment):
        r = cli("-v", assignment, "BEGIN { }")
        assert r.returncode == 2 and "invalid variable name" in r.stderr
        assert "Traceback" not in r.stderr

    def test_empty_value_is_fine(self, run_awk):
        assert run_awk("BEGIN { print(repr(v)) }", assigns=["v="]) == "''\n"

    def test_value_with_equals_signs(self, run_awk):
        assert run_awk("BEGIN { print(v) }", assigns=["v=a=b"]) == "a=b\n"

    def test_bogus_escape_is_kept_literally(self, run_awk):
        assert run_awk("BEGIN { print(v) }", assigns=["v=a\\qb"]) == "a\\qb\n"

    def test_dash_F_empty_splits_characters(self, run_awk):
        assert run_awk("{ print(NF) }", "abc\n", fs="") == "3\n"

    def test_missing_operand_file_warns_and_exits_2(self, status_awk, tmp_path):
        st, out, err = status_awk("END { print(NR) }", "", [str(tmp_path / "nope")])
        assert (st, out) == (2, "") or st == 2
        assert "cannot open" in err

    def test_directory_operand_does_not_crash(self, cli, tmp_path):
        r = cli("END { print(NR) }", str(tmp_path))
        assert "Traceback" not in r.stderr

    def test_unknown_option(self, cli):
        r = cli("--bogus", "BEGIN { }")
        assert r.returncode == 2 and "Traceback" not in r.stderr


class TestARGVAndENVIRONBogus:
    def test_argv_none_is_an_error(self, status_awk):
        fails(status_awk, "BEGIN { ARGV = None } { print($0) }", "x\n", match="ARGV must be a list")

    def test_argv_string_is_an_error(self, status_awk):
        fails(status_awk, "BEGIN { ARGV = 'file' } { print($0) }", "x\n", match="ARGV")

    def test_argv_number_element_is_used_as_a_file_name(self, status_awk):
        st, _out, err = status_awk("BEGIN { ARGV.append(5) } END { print(NR) }", "")
        assert st == 2 and "cannot open 5" in err

    def test_argv_none_element_is_skipped(self, run_awk):
        assert run_awk("BEGIN { ARGV.append(None) } END { print(NR) }", "x\n") == "1\n"

    def test_argv_shrunk_to_nothing_reads_stdin_once(self, run_awk):
        assert run_awk("BEGIN { del ARGV[1:] } END { print(NR) }", "x\ny\n",
                       operands=["/nonexistent"]) == "2\n"

    def test_environ_missing_key_is_a_clean_error(self, status_awk):
        fails(status_awk, "BEGIN { print(ENVIRON['NOPE']) }", "", match="KeyError")

    def test_environ_get_gives_a_default(self, run_awk):
        assert run_awk("BEGIN { print(ENVIRON.get('NOPE', 'dflt')) }", environ={}) == "dflt\n"

    def test_environ_replaced_by_garbage(self, status_awk):
        fails(status_awk, "BEGIN { ENVIRON = None; print(ENVIRON['A']) }", "", match="TypeError")

    def test_argc_garbage_is_harmless(self, run_awk):
        assert run_awk("BEGIN { ARGC = 'x' } END { print(NR) }", "a\n") == "1\n"


class TestRecordBogus:
    def test_assigning_dollar0_none(self, run_awk):
        assert run_awk("{ $0 = None; print(NF, repr($0)) }", "a b\n") == "0 ''\n"

    def test_assigning_dollar0_a_number(self, run_awk):
        assert run_awk("{ $0 = 12.5; print(NF, $1 + 1) }", "a\n") == "1 13.5\n"

    def test_assigning_a_field_a_list_is_formatted(self, run_awk):
        assert run_awk("{ F[1] = [1, 2]; print(F[0]) }", "a b\n") == "[1, 2] b\n"

    def test_binary_garbage_survives(self, tmp_path):
        import subprocess
        import sys
        f = tmp_path / "bin"
        f.write_bytes(b"\xff\xfe a\x00b\n")
        import os
        env = {**os.environ, "PYTHONPATH": str(__import__("conftest").ROOT)}
        r = subprocess.run([sys.executable, "-m", "pawk_ng", "{ print(NF, len($1)) }", str(f)],
                           capture_output=True, env=env)
        assert r.returncode == 0 and r.stdout == b"2 2\n"

    def test_very_long_line(self, run_awk):
        assert run_awk("{ print(NF, len($0)) }", "a " * 200000 + "\n") == "200000 400000\n"
