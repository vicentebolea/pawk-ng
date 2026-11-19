"""One test class per awk variable: its default and every way it can be set."""
import pytest

pytestmark = pytest.mark.contract

LINES = "a 1\nb 2\nc 3\n"


@pytest.fixture
def two_files(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a1\na2\n")
    b.write_text("b1\nb2\nb3\n")
    return str(a), str(b)


class TestNR:
    def test_default_is_zero_before_input(self, run_awk):
        assert run_awk("BEGIN { print(NR) }") == "0\n"

    def test_counts_records(self, run_awk):
        assert run_awk("{ print(NR) }", LINES) == "1\n2\n3\n"

    def test_end_value_is_the_total(self, run_awk):
        assert run_awk("END { print(NR) }", LINES) == "3\n"

    def test_set_in_begin_offsets_the_count(self, run_awk):
        assert run_awk("BEGIN { NR = 10 } { print(NR) }", LINES) == "11\n12\n13\n"

    def test_set_in_action_continues_from_new_value(self, run_awk):
        assert run_awk("NR == 2 { NR = 100 } { print(NR) }", LINES) == "1\n100\n101\n"

    def test_set_to_zero_restarts(self, run_awk):
        assert run_awk("NR == 2 { NR = 0 } { print(NR) }", LINES) == "1\n0\n1\n"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("{ print(NR) }", "x\n", assigns=["NR=5"]) == "6\n"

    def test_not_reset_between_files(self, run_awk, two_files):
        assert run_awk("{ print(NR) }", operands=list(two_files)) == "1\n2\n3\n4\n5\n"


class TestFNR:
    def test_default_is_zero_before_input(self, run_awk):
        assert run_awk("BEGIN { print(FNR) }") == "0\n"

    def test_resets_for_each_file(self, run_awk, two_files):
        assert run_awk("{ print(FNR) }", operands=list(two_files)) == "1\n2\n1\n2\n3\n"

    def test_equals_nr_for_a_single_stream(self, run_awk):
        assert run_awk("{ print(FNR == NR) }", LINES) == "True\nTrue\nTrue\n"

    def test_set_in_action_continues_from_new_value(self, run_awk):
        assert run_awk("FNR == 1 { FNR = 10 } { print(FNR) }", "x\ny\n") == "10\n11\n"

    def test_set_in_action_then_reset_on_new_file(self, run_awk, two_files):
        out = run_awk("FNR == 1 { FNR = 50 }\n{ print(FILENAME[-5:], FNR) }",
                      operands=list(two_files))
        assert out == "a.txt 50\na.txt 51\nb.txt 50\nb.txt 51\nb.txt 52\n"

    def test_set_in_begin_is_overwritten_when_the_file_opens(self, run_awk):
        assert run_awk("BEGIN { FNR = 7 } { print(FNR) }", "x\n") == "1\n"


class TestNF:
    def test_default_is_zero_in_begin(self, run_awk):
        assert run_awk("BEGIN { print(NF) }") == "0\n"

    def test_counts_fields_per_record(self, run_awk):
        assert run_awk("{ print(NF) }", "a b c\n\n  x  \n") == "3\n0\n1\n"

    def test_set_smaller_truncates(self, run_awk):
        assert run_awk("{ NF = 2; print($0) }", "a b c d\n") == "a b\n"

    def test_set_larger_pads_with_empty_fields(self, run_awk):
        assert run_awk("BEGIN { OFS = ',' } { NF = 5; print($0) }", "a b\n") == "a,b,,,\n"

    def test_set_to_zero_empties_the_record(self, run_awk):
        assert run_awk("{ NF = 0; print(repr($0), NF) }", "a b\n") == "'' 0\n"

    def test_set_is_visible_to_fields_immediately(self, run_awk):
        assert run_awk("{ NF = 1; print($2 == '', $1) }", "a b\n") == "True a\n"

    def test_set_to_a_numeric_string(self, run_awk):
        assert run_awk("{ NF = '2'; print($0) }", "a b c\n") == "a b\n"

    def test_negative_is_an_error(self, status_awk):
        import pawk_ng
        with pytest.raises(pawk_ng.PawkError):
            status_awk("{ NF = -1; print($0) }", "a b\n")

    def test_recomputed_for_the_next_record(self, run_awk):
        assert run_awk("NR == 1 { NF = 1 } { print(NF) }", "a b c\nd e f\n") == "1\n3\n"

    def test_updated_when_a_field_beyond_it_is_assigned(self, run_awk):
        assert run_awk("{ $4 = 'x'; print(NF) }", "a b\n") == "4\n"

    def test_updated_when_the_record_is_assigned(self, run_awk):
        assert run_awk("{ $0 = 'p q r s'; print(NF) }", "a\n") == "4\n"

    def test_set_in_begin_does_not_affect_input(self, run_awk):
        assert run_awk("BEGIN { NF = 9 } { print(NF) }", "a b\n") == "2\n"


class TestFS:
    def test_default_splits_on_runs_of_blanks(self, run_awk):
        assert run_awk("BEGIN { print(repr(FS)) } { print($1, $2) }", "  a \t b \n") == \
            "' '\na b\n"

    def test_set_in_begin(self, run_awk):
        assert run_awk("BEGIN { FS = ':' } { print($2) }", "a:b c:d\n") == "b c\n"

    def test_set_by_option_F(self, run_awk):
        assert run_awk("{ print($2) }", "a:b:c\n", fs=":") == "b\n"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("{ print($2) }", "a,b\n", assigns=["FS=,"]) == "b\n"

    def test_set_in_action_applies_from_the_next_record(self, run_awk):
        assert run_awk("{ FS = ':'; print($1) }", "a:b c\nd:e f\n") == "a:b\nd\n"

    def test_single_character_is_literal(self, run_awk):
        assert run_awk("BEGIN { FS = '|' } { print($2) }", "a|b|c\n") == "b\n"
        assert run_awk("BEGIN { FS = '.' } { print($2) }", "a.b\n") == "b\n"

    def test_regex(self, run_awk):
        assert run_awk("BEGIN { FS = '[0-9]+' } { print($1, $2, $3) }", "a1b22c\n") == "a b c\n"

    def test_regex_with_posix_class(self, run_awk):
        assert run_awk("BEGIN { FS = '[[:digit:]]' } { print($2) }", "a1b\n") == "b\n"

    def test_empty_splits_into_characters(self, run_awk):
        assert run_awk("BEGIN { FS = '' } { print(NF, $2) }", "abc\n") == "3 b\n"

    def test_escape_sequences_in_option_F(self, run_awk):
        assert run_awk("{ print($2) }", "a b\tc\n", fs="\\t") == "c\n"

    def test_leading_and_trailing_separators_make_empty_fields(self, run_awk):
        assert run_awk("BEGIN { FS = ':' } { print(NF) }", ":a:\n") == "3\n"

    def test_set_after_changing_record_does_not_resplit(self, run_awk):
        assert run_awk("{ FS = ':'; print($1) }", "a:b c\n") == "a:b\n"


class TestOFS:
    def test_default_is_a_space(self, run_awk):
        assert run_awk("BEGIN { print(repr(OFS)) }") == "' '\n"

    def test_set_in_begin_used_when_a_field_is_assigned(self, run_awk):
        assert run_awk("BEGIN { OFS = '-' } { $1 = $1; print($0) }", "a b c\n") == "a-b-c\n"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("{ $1 = $1; print($0) }", "a b\n", assigns=["OFS=:"]) == "a:b\n"

    def test_used_when_nf_is_assigned(self, run_awk):
        assert run_awk("BEGIN { OFS = '+' } { NF = 3; print($0) }", "a b\n") == "a+b+\n"

    def test_not_applied_to_an_untouched_record(self, run_awk):
        assert run_awk("BEGIN { OFS = '-' } { print($0) }", "a   b\n") == "a   b\n"

    def test_set_in_action_applies_to_later_rebuilds(self, run_awk):
        assert run_awk("{ OFS = '/'; $2 = 'X'; print($0) }", "a b c\n") == "a/X/c\n"

    def test_multi_character_value(self, run_awk):
        assert run_awk("BEGIN { OFS = ' | ' } { $1 = $1; print($0) }", "a b\n") == "a | b\n"

    def test_empty_value_joins_without_separator(self, run_awk):
        assert run_awk("BEGIN { OFS = '' } { $1 = $1; print($0) }", "a b\n") == "ab\n"

    def test_usable_explicitly_as_the_print_separator(self, run_awk):
        assert run_awk("BEGIN { OFS = ',' } { print($1, $2, sep=OFS) }", "a b\n") == "a,b\n"

    def test_print_itself_does_not_use_ofs(self, run_awk):
        assert run_awk("BEGIN { OFS = ',' } { print($1, $2) }", "a b\n") == "a b\n"


class TestRS:
    def test_default_is_newline(self, run_awk):
        assert run_awk("BEGIN { print(repr(RS)) } { print(NR, $0) }", "a\nb\n") == \
            "'\\n'\n1 a\n2 b\n"

    def test_single_character(self, run_awk):
        assert run_awk("BEGIN { RS = ';' } { print(NR, $0) }", "a;b;c") == "1 a\n2 b\n3 c\n"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("{ print($0) }", "a;b", assigns=["RS=;"]) == "a\nb\n"

    def test_regex(self, run_awk):
        assert run_awk("BEGIN { RS = '[0-9]+' } { print($0) }", "a1b22c\n") == "a\nb\nc\n\n"

    def test_empty_is_paragraph_mode(self, run_awk):
        assert run_awk("BEGIN { RS = '' } { print(NR, NF) }", "a b\nc\n\n\nd\n") == "1 3\n2 1\n"

    def test_paragraph_mode_ignores_leading_blank_lines(self, run_awk):
        assert run_awk("BEGIN { RS = '' } { print($1) }", "\n\n\na\n") == "a\n"

    def test_set_in_action_applies_to_later_reads(self, run_awk):
        assert run_awk("NR == 1 { RS = ';' } { print(repr($0)) }", "a\nb;c;d") == \
            "'a'\n'b'\n'c'\n'd'\n"

    def test_last_record_without_terminator_is_kept(self, run_awk):
        assert run_awk("BEGIN { RS = ';' } END { print(NR) }", "a;b") == "2\n"

    def test_trailing_terminator_does_not_add_an_empty_record(self, run_awk):
        assert run_awk("BEGIN { RS = ';' } END { print(NR) }", "a;b;") == "2\n"

    def test_empty_input_has_no_records(self, run_awk):
        assert run_awk("END { print(NR) }", "") == "0\n"


class TestORS:
    def test_default_is_newline(self, run_awk):
        assert run_awk("BEGIN { print(repr(ORS)) }") == "'\\n'\n"

    def test_set_in_begin_and_read_back(self, run_awk):
        assert run_awk("BEGIN { ORS = '|'; print(repr(ORS), end='') }") == "'|'"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("BEGIN { print(repr(ORS), end='') }", assigns=["ORS=;"]) == "';'"

    def test_usable_explicitly_as_the_print_terminator(self, run_awk):
        assert run_awk("BEGIN { ORS = '|' } { print($1, end=ORS) }", "a\nb\n") == "a|b|"

    def test_print_itself_does_not_use_ors(self, run_awk):
        assert run_awk("BEGIN { ORS = '|' } { print($1) }", "a\nb\n") == "a\nb\n"

    def test_set_in_action(self, run_awk):
        assert run_awk("{ ORS = '#'; print($1, end=ORS) }", "a\nb\n") == "a#b#"


class TestFILENAME:
    def test_empty_in_begin(self, run_awk, two_files):
        assert run_awk("BEGIN { print(repr(FILENAME)) }", operands=list(two_files)) == "''\n"

    def test_set_to_each_file_in_turn(self, run_awk, two_files):
        out = run_awk("FNR == 1 { print(FILENAME) }", operands=list(two_files))
        assert out == "\n".join(two_files) + "\n"

    def test_keeps_the_last_file_in_end(self, run_awk, two_files):
        assert run_awk("END { print(FILENAME) }", operands=list(two_files)) == two_files[1] + "\n"

    def test_empty_for_implicit_stdin(self, run_awk):
        assert run_awk("{ print(repr(FILENAME)) }", "x\n") == "''\n"

    def test_dash_operand_names_stdin(self, run_awk):
        assert run_awk("{ print(FILENAME) }", "x\n", operands=["-"]) == "-\n"

    def test_assignment_lasts_until_the_next_file_opens(self, run_awk, two_files):
        out = run_awk("{ FILENAME = 'custom'; print(FILENAME) }", operands=list(two_files))
        assert out == "custom\ncustom\ncustom\ncustom\ncustom\n"

    def test_reset_by_the_next_file(self, run_awk, two_files):
        out = run_awk("FNR == 1 { print(FILENAME[-5:]); FILENAME = 'x' }",
                      operands=list(two_files))
        assert out == "a.txt\nb.txt\n"


class TestSUBSEP:
    def test_default_is_the_awk_separator(self, run_awk):
        assert run_awk("BEGIN { print(repr(SUBSEP)) }") == "'\\x1c'\n"

    def test_set_and_read_back(self, run_awk):
        assert run_awk("BEGIN { SUBSEP = ':'; print(SUBSEP) }") == ":\n"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("BEGIN { print(SUBSEP) }", assigns=["SUBSEP=/"]) == "/\n"

    def test_builds_composite_keys(self, run_awk):
        prog = "BEGIN { SUBSEP = ',' }\n{ a[$1 + SUBSEP + $2] = 1 }\nEND { print(sorted(a)) }"
        assert run_awk(prog, "x y\nz w\n") == "['x,y', 'z,w']\n"

    def test_tuple_keys_work_without_subsep(self, run_awk):
        assert run_awk("{ a[$1, $2] = 1 } END { print(sorted(a)) }", "x y\n") == \
            "[('x', 'y')]\n"


class TestOFMT:
    def test_default(self, run_awk):
        assert run_awk("BEGIN { print(OFMT) }") == "%.6g\n"

    def test_formats_floats_assigned_to_fields(self, run_awk):
        assert run_awk("{ $1 = 1 / 3; print($0) }", "x\n") == "0.333333\n"

    def test_set_in_begin(self, run_awk):
        assert run_awk("BEGIN { OFMT = '%.2f' } { $1 = 1 / 3; print($0) }", "x\n") == "0.33\n"

    def test_set_by_dash_v(self, run_awk):
        assert run_awk("{ $1 = 3.14159; print($0) }", "x\n", assigns=["OFMT=%.3f"]) == "3.142\n"

    def test_integral_floats_print_as_integers(self, run_awk):
        assert run_awk("BEGIN { OFMT = '%.2f' } { $1 = 2.0; print($0) }", "x\n") == "2\n"

    def test_set_in_action_applies_to_later_assignments(self, run_awk):
        assert run_awk("{ OFMT = '%.1f'; $1 = 2.75; print($0) }", "x\n") == "2.8\n"

    def test_print_itself_does_not_use_ofmt(self, run_awk):
        assert run_awk("BEGIN { OFMT = '%.2f' } BEGIN { print(1 / 4) }") == "0.25\n"


class TestENVIRON:
    def test_holds_the_given_environment(self, run_awk):
        assert run_awk("BEGIN { print(ENVIRON['A'], ENVIRON['B']) }",
                       environ={"A": "1", "B": "x"}) == "1 x\n"

    def test_defaults_to_the_process_environment(self, run_awk, monkeypatch):
        monkeypatch.setenv("PAWK_TEST_VAR", "from-os")
        assert run_awk("BEGIN { print(ENVIRON['PAWK_TEST_VAR']) }") == "from-os\n"

    def test_values_are_numeric_strings(self, run_awk):
        assert run_awk("BEGIN { print(ENVIRON['N'] + 1, ENVIRON['N'] > 9) }",
                       environ={"N": "10"}) == "11 True\n"

    def test_can_be_set_and_read_back(self, run_awk):
        assert run_awk("BEGIN { ENVIRON['NEW'] = 'v'; print(ENVIRON['NEW']) }",
                       environ={}) == "v\n"

    def test_membership(self, run_awk):
        assert run_awk("BEGIN { print('A' in ENVIRON, 'Z' in ENVIRON) }",
                       environ={"A": "1"}) == "True False\n"

    def test_setting_does_not_change_the_real_environment(self, run_awk):
        import os
        run_awk("BEGIN { ENVIRON['PAWK_LEAK'] = '1' }")
        assert "PAWK_LEAK" not in os.environ


class TestARGV:
    def test_first_element_is_the_program_name(self, run_awk):
        assert run_awk("BEGIN { print(ARGV[0]) }") == "pawk\n"

    def test_holds_the_operands(self, run_awk):
        assert run_awk("BEGIN { print(ARGV) }", operands=["f1", "v=1"]) == \
            "['pawk', 'f1', 'v=1']\n"

    def test_a_file_can_be_appended_in_begin(self, run_awk, tmp_path):
        f = tmp_path / "f"
        f.write_text("data\n")
        assert run_awk(f"BEGIN {{ ARGV.append({str(f)!r}) }} {{ print($0) }}") == "data\n"

    def test_an_operand_can_be_replaced_in_begin(self, run_awk, two_files):
        a, b = two_files
        prog = f"BEGIN {{ ARGV[1] = {b!r} }} {{ print($0) }}"
        assert run_awk(prog, operands=[a]) == "b1\nb2\nb3\n"

    def test_an_operand_set_to_empty_is_skipped(self, run_awk, two_files):
        prog = "BEGIN { ARGV[1] = '' } { print($0) }"
        assert run_awk(prog, operands=list(two_files)) == "b1\nb2\nb3\n"

    def test_an_assignment_operand_sets_a_variable_when_reached(self, run_awk, two_files):
        a, b = two_files
        out = run_awk("FNR == 1 { print(v) }", operands=["v=1", a, "v=2", b])
        assert out == "1\n2\n"

    def test_a_variable_operand_can_be_added_in_begin(self, run_awk):
        assert run_awk("BEGIN { ARGV.append('v=9') } END { print(v) }", "x\n") == "9\n"


class TestARGC:
    def test_counts_the_program_name_and_operands(self, run_awk):
        assert run_awk("BEGIN { print(ARGC) }") == "1\n"
        assert run_awk("BEGIN { print(ARGC) }", operands=["a", "b"]) == "3\n"

    def test_matches_len_of_argv_initially(self, run_awk):
        assert run_awk("BEGIN { print(ARGC == len(ARGV)) }", operands=["a"]) == "True\n"

    def test_can_be_set_and_read_back(self, run_awk):
        assert run_awk("BEGIN { ARGC = 5; print(ARGC) }") == "5\n"

    def test_is_informational_the_input_comes_from_argv(self, run_awk, two_files):
        out = run_awk("BEGIN { ARGC = 1 } END { print(NR) }", operands=list(two_files))
        assert out == "5\n"
