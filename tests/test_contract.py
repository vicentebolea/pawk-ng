"""Contract tests: the documented behaviour of BEGIN/END and awk variables."""
import pytest

pytestmark = pytest.mark.contract

LINES = "alpha 1\nbeta 2\ngamma 3\n"


class TestBeginEnd:
    def test_begin_runs_before_input_and_end_after(self, run_awk):
        assert run_awk('BEGIN { print("b") }\n{ print($1) }\nEND { print("e") }',
                       "x\ny\n") == "b\nx\ny\ne\n"

    def test_begin_only_program_does_not_read_input(self, run_awk):
        # would hang/consume stdin otherwise
        assert run_awk('BEGIN { print("hi") }', "ignored\n") == "hi\n"

    def test_end_only_program_reads_all_input(self, run_awk):
        assert run_awk("END { print(NR) }", LINES) == "3\n"

    def test_multiple_begin_and_end_run_in_source_order(self, run_awk):
        prog = "BEGIN{print(1)} END{print(3)} BEGIN{print(2)} END{print(4)}"
        assert run_awk(prog, "x\n") == "1\n2\n3\n4\n"

    def test_begin_sees_empty_record_variables(self, run_awk):
        assert run_awk("BEGIN { print(NR, NF, FNR, repr(FILENAME), repr(str(F))) }") == \
            "0 0 0 '' ''\n"

    def test_end_keeps_last_record_and_nf(self, run_awk):
        assert run_awk("END { print($0, NF, $1) }", LINES) == "gamma 3 2 gamma\n"

    def test_end_with_empty_input(self, run_awk):
        assert run_awk("END { print(NR) }", "") == "0\n"

    def test_state_flows_from_begin_through_rules_to_end(self, run_awk):
        prog = "BEGIN { total = 0 }\n{ total += $2 }\nEND { print(total) }"
        assert run_awk(prog, LINES) == "6\n"

    def test_rule_with_no_action_prints_record(self, run_awk):
        assert run_awk("NR % 2", LINES) == "alpha 1\ngamma 3\n"

    def test_empty_action_does_nothing(self, run_awk):
        assert run_awk("{}", LINES) == ""

    def test_all_matching_rules_run_in_order(self, run_awk):
        assert run_awk("{ print('a') }\n{ print('b') }", "x\n") == "a\nb\n"


class TestExitAndNext:
    def test_next_skips_remaining_rules_for_the_record(self, run_awk):
        prog = "$2 == 2 { next }\n{ print($1) }"
        assert run_awk(prog, LINES) == "alpha\ngamma\n"

    def test_next_inside_nested_python_control_flow(self, run_awk):
        prog = "{\n  for i in range(3):\n    if i == 1: next\n  print('unreached')\n}\nEND{print(NR)}"
        assert run_awk(prog, "a\nb\n") == "2\n"

    def test_exit_in_main_runs_end_and_stops_reading(self, status_awk):
        st, out, _ = status_awk("NR == 2 { exit 5 }\n{ print($1) }\nEND { print('end', NR) }",
                                LINES)
        assert (st, out) == (5, "alpha\nend 2\n")

    def test_exit_in_begin_skips_input_but_runs_end(self, status_awk):
        st, out, _ = status_awk("BEGIN { print('b'); exit 3 }\n{ print('main') }\n"
                                "END { print('e') }", "x\n")
        assert (st, out) == (3, "b\ne\n")

    def test_exit_in_end_stops_other_end_rules(self, status_awk):
        st, out, _ = status_awk("END { print(1); exit 4 }\nEND { print(2) }", "x\n")
        assert (st, out) == (4, "1\n")

    def test_exit_without_code_in_end_keeps_earlier_code(self, status_awk):
        st, _, _ = status_awk("{ exit 7 }\nEND { exit }", "x\n")
        assert st == 7

    def test_exit_code_of_end_overrides(self, status_awk):
        st, _, _ = status_awk("{ exit 7 }\nEND { exit 1 }", "x\n")
        assert st == 1

    def test_default_status_is_zero(self, status_awk):
        assert status_awk("{ }", "x\n")[0] == 0

    def test_exit_as_function_call(self, status_awk):
        assert status_awk("BEGIN { exit(9) }")[0] == 9

    def test_exit_string_code_is_numeric(self, status_awk):
        assert status_awk("BEGIN { exit '4' }")[0] == 4

    def test_nextfile_skips_rest_of_file(self, run_awk, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_text("a1\na2\na3\n")
        b.write_text("b1\nb2\n")
        prog = "FNR == 2 { nextfile }\n{ print($0) }"
        assert run_awk(prog, operands=[str(a), str(b)]) == "a1\nb1\n"

    def test_next_in_begin_is_an_error(self, status_awk):
        import pawk
        with pytest.raises(pawk.PawkError):
            status_awk("BEGIN { next }")


class TestVariables:
    def test_nr_counts_across_files_fnr_resets(self, run_awk, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_text("1\n2\n")
        b.write_text("3\n")
        out = run_awk("{ print(NR, FNR, FILENAME.split('/')[-1]) }",
                      operands=[str(a), str(b)])
        assert out == "1 1 a\n2 2 a\n3 1 b\n"

    def test_nf_tracks_field_count(self, run_awk):
        assert run_awk("{ print(NF) }", "a b c\n\n  x  \n") == "3\n0\n1\n"

    def test_default_fs_collapses_whitespace(self, run_awk):
        assert run_awk("{ print($1, $2) }", "  a \t  b  \n") == "a b\n"

    def test_fs_change_applies_from_next_record(self, run_awk):
        prog = "BEGIN { FS = ':' }\n{ print($1) }"
        assert run_awk(prog, "a:b c\n") == "a\n"
        prog = "NR == 1 { FS = ':' }\n{ print($1) }"
        assert run_awk(prog, "a:b c\nd:e f\n") == "a:b\nd\n"

    def test_fs_single_char_is_literal_not_regex(self, run_awk):
        assert run_awk("BEGIN{FS='|'} {print($2)}", "a|b|c\n") == "b\n"
        assert run_awk("BEGIN{FS='.'} {print($2)}", "a.b\n") == "b\n"

    def test_fs_regex(self, run_awk):
        assert run_awk("BEGIN{FS='[,;] *'} {print($3)}", "a, b;c\n") == "c\n"

    def test_fs_tab_keeps_empty_fields(self, run_awk):
        assert run_awk("BEGIN{FS='\\t'} {print(NF, $2 == '')}", "a\t\tb\n") == "3 True\n"

    def test_ofs_applies_when_the_record_is_rebuilt(self, run_awk):
        assert run_awk("BEGIN{OFS='-'} {$1 = $1; print($0)}", "a b\nc d\n") == "a-b\nc-d\n"

    def test_print_is_pythons_so_ofs_ors_are_opt_in(self, run_awk):
        assert run_awk("BEGIN{OFS='-'; ORS='|'} {print($1, $2)}", "a b\n") == "a b\n"
        assert run_awk("BEGIN{OFS='-'; ORS='|'} {print($1, $2, sep=OFS, end=ORS)}",
                       "a b\n") == "a-b|"

    def test_assigning_field_rebuilds_with_ofs(self, run_awk):
        assert run_awk("BEGIN{OFS=':'} {$1 = $1; print($0)}", "a b c\n") == "a:b:c\n"

    def test_print_dollar0_does_not_rebuild_untouched_record(self, run_awk):
        assert run_awk("BEGIN{OFS=':'} {print($0)}", "a   b\n") == "a   b\n"

    def test_assigning_nf_truncates_record(self, run_awk):
        assert run_awk("{ NF = 2; print($0) }", "a b c d\n") == "a b\n"

    def test_assigning_nf_extends_record(self, run_awk):
        assert run_awk("BEGIN{OFS=','} { NF = 4; print($0) }", "a b\n") == "a,b,,\n"

    def test_assigning_dollar0_resplits(self, run_awk):
        assert run_awk("{ $0 = 'x y z'; print(NF, $3) }", "a\n") == "3 z\n"

    def test_assigning_beyond_nf_extends(self, run_awk):
        assert run_awk("{ $5 = 'e'; print(NF); print($0) }", "a b\n") == "5\na b   e\n"

    def test_dollar_nf_and_computed_fields(self, run_awk):
        assert run_awk("{ print($NF, $(NF-1), $(1+1)) }", "a b c\n") == "c b b\n"

    def test_indirect_field(self, run_awk):
        assert run_awk("{ print($$1) }", "2 x y\n") == "x\n"

    def test_dollar_beyond_nf_is_empty_and_does_not_change_nf(self, run_awk):
        assert run_awk("{ print(repr($9), NF) }", "a b\n") == "'' 2\n"

    def test_rs_single_char(self, run_awk):
        assert run_awk("BEGIN{RS=';'} {print(NR, $0)}", "a;b;c") == "1 a\n2 b\n3 c\n"

    def test_rs_empty_is_paragraph_mode_and_newline_separates_fields(self, run_awk):
        out = run_awk("BEGIN{RS=''} {print(NR, NF, $1, $NF)}", "a b\nc\n\n\nd e\nf g\n")
        assert out == "1 3 a c\n2 4 d g\n"

    def test_rs_regex(self, run_awk):
        assert run_awk("BEGIN{RS='[0-9]+'} {print($0)}", "a1b22c") == "a\nb\nc\n"

    def test_subsep_default(self, run_awk):
        assert run_awk("BEGIN { print(repr(SUBSEP)) }") == "'\\x1c'\n"

    def test_environ(self, run_awk):
        assert run_awk("BEGIN { print(ENVIRON['HOME'] if 'HOME' in ENVIRON else 'x') }",
                       environ={"HOME": "/h"}) == "/h\n"

    def test_environ_values_are_numeric_strings(self, run_awk):
        assert run_awk("BEGIN { print(ENVIRON['N'] > 9) }", environ={"N": "10"}) == "True\n"

    def test_argv_argc(self, run_awk):
        out = run_awk("BEGIN { print(ARGC, ARGV[0], ARGV[1]) }", operands=["f1"])
        assert out == "2 pawk f1\n"

    def test_argv_can_be_edited_in_begin(self, run_awk, tmp_path):
        f = tmp_path / "f"
        f.write_text("data\n")
        assert run_awk(f"BEGIN {{ ARGV.append({str(f)!r}) }}\n{{ print($0) }}") == "data\n"

    def test_dash_means_stdin(self, run_awk):
        assert run_awk("{ print(FILENAME, $0) }", "x\n", operands=["-"]) == "- x\n"

    def test_filename_empty_for_implicit_stdin(self, run_awk):
        assert run_awk("{ print(repr(FILENAME)) }", "x\n") == "''\n"

    def test_ofmt_formats_floats_assigned_to_fields(self, run_awk):
        assert run_awk("BEGIN { OFMT = '%.2f' } { $2 = 3.14159; $3 = 2.0; print($0) }",
                       "a b c\n") == "a 3.14 2\n"

    def test_no_awk_functions_are_defined(self, run_awk):
        prog = "BEGIN { print([n in globals() for n in ('length', 'substr', 'gsub', 'RSTART')]) }"
        assert run_awk(prog) == "[False, False, False, False]\n"

    def test_user_variables_persist_between_records(self, run_awk):
        assert run_awk("{ n = (n if 'n' in globals() else 0) + 1 }\nEND{print(n)}",
                       "a\nb\n") == "2\n"

    def test_command_line_assignments_between_files(self, run_awk, tmp_path):
        f = tmp_path / "f"
        f.write_text("x\n")
        out = run_awk("{ print(v, $0) }", operands=["v=1", str(f), "v=2", str(f)])
        assert out == "1 x\n2 x\n"

    def test_assignment_operand_visible_in_end(self, run_awk):
        assert run_awk("END { print(v) }", "x\n", operands=["v=7"]) == "7\n"

    def test_nr_is_assignable(self, run_awk):
        assert run_awk("NR == 1 { NR = 10 }\n{ print(NR) }", "a\nb\n") == "10\n11\n"


class TestPatterns:
    def test_expression_pattern(self, run_awk):
        assert run_awk("$2 >= 2", LINES) == "beta 2\ngamma 3\n"

    def test_numeric_string_comparison_like_awk(self, run_awk):
        assert run_awk("$1 > $2", "10 9\nabc abd\n10 9a\n") == "10 9\n"

    def test_regex_pattern(self, run_awk):
        assert run_awk("/a 1$/", LINES) == "alpha 1\n"

    def test_regex_pattern_matches_anywhere(self, run_awk):
        assert run_awk("/ta/", LINES) == "beta 2\n"

    def test_negated_regex(self, run_awk):
        assert run_awk("!/a/", "x\nabc\ny\n") == "x\ny\n"

    def test_awk_logical_operators(self, run_awk):
        assert run_awk("/a/ && $2 > 1 || NR == 1", LINES) == "alpha 1\nbeta 2\ngamma 3\n"
        assert run_awk("!($2 > 1)", LINES) == "alpha 1\n"

    def test_regex_with_escaped_slash(self, run_awk):
        assert run_awk(r"/^\d+\/\d+$/", "1/2\na/b\n") == "1/2\n"

    def test_range_inclusive(self, run_awk):
        assert run_awk("NR == 2, NR == 3", "1\n2\n3\n4\n") == "2\n3\n"

    def test_range_with_regexes(self, run_awk):
        assert run_awk("/start/, /stop/", "a\nstart\nb\nstop\nc\n") == "start\nb\nstop\n"

    def test_range_end_checked_on_same_record(self, run_awk):
        assert run_awk("/a/, /a/", "a\nb\na\n") == "a\na\n"

    def test_range_unterminated_runs_to_eof(self, run_awk):
        assert run_awk("/b/, /zzz/", "a\nb\nc\n") == "b\nc\n"

    def test_range_can_restart(self, run_awk):
        assert run_awk("/s/, /e/", "s\ne\nx\ns\ne\n") == "s\ne\ns\ne\n"

    def test_range_pattern_with_action(self, run_awk):
        assert run_awk("NR==2, NR==3 { print(NR, '!') }", "a\nb\nc\nd\n") == "2 !\n3 !\n"

    def test_truthiness_of_field_patterns(self, run_awk):
        assert run_awk("$1", "0\n1\n\nabc\n0.0\n") == "1\nabc\n"

    def test_pattern_with_string_containing_braces(self, run_awk):
        assert run_awk('$1 == "{" { print("ok") }', "{\n") == "ok\n"


class TestPython:
    def test_def_functions_are_visible_to_rules(self, run_awk):
        prog = "def twice(x):\n    return x * 2\n\n$2 > 1 { print(twice($2)) }"
        assert run_awk(prog, LINES) == "4\n6\n"

    def test_def_functions_can_use_builtins_and_fields(self, run_awk):
        prog = "def last():\n    return $NF\n{ print(last()) }"
        assert run_awk(prog, "a b\nc d\n") == "b\nd\n"

    def test_def_function_can_modify_globals(self, run_awk):
        prog = "def bump():\n    global n\n    n += 1\nBEGIN { n = 0 }\n{ bump() }\nEND { print(n) }"
        assert run_awk(prog, "a\nb\nc\n") == "3\n"

    def test_import_and_dict_counting(self, run_awk):
        prog = ("import collections\nBEGIN { c = collections.Counter() }\n"
                "{ c[$1] += 1 }\nEND { print(sorted(c.items())) }")
        assert run_awk(prog, "a\nb\na\n") == "[('a', 2), ('b', 1)]\n"

    def test_multiline_python_in_action(self, run_awk):
        prog = "{\n  total = 0\n  for f in F:\n    total += f\n  print(total)\n}"
        assert run_awk(prog, "1 2 3\n4 5\n") == "6\n9\n"

    def test_list_comprehension_and_fstrings(self, run_awk):
        assert run_awk("{ print(f'{NF}:' + ','.join(x.upper() for x in F)) }",
                       "a b\n") == "2:A,B\n"

    def test_print_numbers_like_python(self, run_awk):
        assert run_awk("BEGIN { print(1/4, 6/3, 1/3, 10 ** 2, 2 ** 0.5) }") == \
            "0.25 2.0 0.3333333333333333 100 1.4142135623730951\n"

    def test_print_is_the_python_builtin(self, run_awk):
        assert run_awk("BEGIN { import builtins; builtins.print('real') }") == "real\n"

    def test_awk_style_statements(self, run_awk):
        assert run_awk("{ print($2, $1); n = NF } END { print(n) }", "a b\n") == "b a\n2\n"

    def test_runtime_error_is_wrapped_with_context(self, status_awk):
        import pawk
        with pytest.raises(pawk.PawkError, match=r"NameError.*record 1"):
            status_awk("{ print(undefined_name) }", "x\n")

    def test_runtime_error_in_pattern(self, status_awk):
        import pawk
        with pytest.raises(pawk.PawkError, match="ZeroDivisionError"):
            status_awk("1/0 { }", "x\n")


class TestImplicitVariables:
    """Awk lets programs use variables and arrays without declaring them."""

    def test_uninitialized_is_zero_and_empty(self, run_awk):
        assert run_awk("BEGIN { print(x + 1, x == 0, x == ''); x = 1 }") == "1 True True\n"

    def test_accumulate_without_initialization(self, run_awk):
        assert run_awk("{ s += $2 } END { print(s) }", LINES) == "6\n"

    def test_array_autovivification(self, run_awk):
        assert run_awk("{ n[str($1)[0]] += 1 } END { print(sorted(n.items())) }",
                       "ab\nac\nba\n") == "[('a', 2), ('b', 1)]\n"

    def test_array_read_creates_element_like_awk(self, run_awk):
        assert run_awk("BEGIN { x = a['k']; print(len(a), repr(x)) }") == "1 ''\n"

    def test_multi_index_keys(self, run_awk):
        assert run_awk("{ a[$1, $2] = NR } END { print(a['x', 'y'], len(a)) }",
                       "x y\nx z\nx y\n") == "3 2\n"

    def test_delete_and_membership(self, run_awk):
        prog = "{ a[$1] = 1 } END { del a['x']; print('x' in a, 'y' in a) }"
        assert run_awk(prog, "x\ny\n") == "False True\n"

    def test_never_assigned_name_is_still_a_name_error(self, status_awk):
        import pawk
        with pytest.raises(pawk.PawkError, match="NameError"):
            status_awk("BEGIN { print(typo) }")

    def test_builtins_are_not_shadowed_by_uninit(self, run_awk):
        assert run_awk("BEGIN { x = len('abc'); print(x, sorted([3, 1])) }") == "3 [1, 3]\n"

    def test_assignment_from_command_line_beats_uninit(self, run_awk):
        assert run_awk("BEGIN { print(v + 1) }\nBEGIN { v = 0 }", operands=[]) == "1\n"

    def test_dash_v_assigned_name(self, run_awk):
        assert run_awk("BEGIN { print(v * 2) }", assigns=["v=21"]) == "42\n"

    def test_functions_see_implicit_globals(self, run_awk):
        prog = "def bump():\n    global n\n    n += 1\n{ bump() }\nEND { print(n) }"
        assert run_awk(prog, "a\nb\n") == "2\n"


class TestPythonInsteadOfAwkFunctions:
    def test_string_methods_and_len(self, run_awk):
        assert run_awk("{ print(len($1), $1.upper(), $1[1:3], $1.find('l') + 1) }",
                       "hello\n") == "5 HELLO el 3\n"

    def test_re_for_substitution_edits_the_record(self, run_awk):
        assert run_awk("{ $0 = re.sub('o', '0', $0); print(NF, $0) }", "foo boo\n") == "2 f00 b00\n"

    def test_re_for_a_single_field(self, run_awk):
        assert run_awk("{ $2 = re.sub(r'\\d', '#', $2); print($0) }", "a 123\n") == "a ###\n"

    def test_split_is_str_split(self, run_awk):
        assert run_awk("{ print(len($0.split(':'))) }", "a:b:c\n") == "3\n"

    def test_formatting_with_fstrings_and_percent(self, run_awk):
        assert run_awk("{ print(f'{F[1]:>6}|{float(F[2]):5.1f}|' + '%03d' % int($2)) }",
                       "ab 3.14159\n") == "    ab|  3.1|003\n"

    def test_print_accepts_sep_and_end(self, run_awk):
        assert run_awk("{ print($1, $2, sep='-', end='!\\n') }", "a b\n") == "a-b!\n"

    def test_print_to_a_file_object(self, run_awk, tmp_path):
        out = tmp_path / "o"
        run_awk(f"BEGIN {{ f = open({str(out)!r}, 'w') }}\n{{ print($1, file=f) }}\nEND {{ f.close() }}",
                "a\nb\n")
        assert out.read_text() == "a\nb\n"

    def test_regex_pattern_uses_python_syntax(self, run_awk):
        assert run_awk(r"/^(?:ab|cd)\d$/", "ab1\nxx\ncd2\nab\n") == "ab1\ncd2\n"
