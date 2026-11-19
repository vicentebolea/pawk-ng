"""Reading the program from script files (-f)."""
import pytest

pytestmark = pytest.mark.integration

DATA = "ERROR disk full\nINFO started\nERROR timeout\nWARN slow\n"


@pytest.fixture
def script(tmp_path):
    def write(text, name="prog.awk", mode="w"):
        p = tmp_path / name
        p.write_text(text) if mode == "w" else p.write_bytes(text)
        return str(p)
    return write


@pytest.fixture
def data(tmp_path):
    p = tmp_path / "app.log"
    p.write_text(DATA)
    return str(p)


class TestScriptFile:
    def test_runs_the_program_in_the_file(self, cli, script, data):
        prog = script("$1 == 'ERROR' { print($2) }\n")
        assert cli("-f", prog, data).stdout == "disk\ntimeout\n"

    def test_reads_stdin_when_no_operand_files(self, cli, script):
        assert cli("-f", script("{ print(NR, $1) }\n"), stdin=DATA).stdout == \
            "1 ERROR\n2 INFO\n3 ERROR\n4 WARN\n"

    def test_operands_after_dash_f_are_all_files(self, cli, script, data, tmp_path):
        other = tmp_path / "b.log"
        other.write_text("FATAL x\n")
        r = cli("-f", script("END { print(NR) }"), data, str(other))
        assert r.stdout == "5\n"

    def test_first_operand_is_not_taken_as_the_program(self, cli, script, data):
        r = cli("-f", script("{ print($1) }"), "BEGIN { print('inline') }")
        assert r.returncode == 2 and "cannot open" in r.stderr

    def test_begin_main_and_end_in_a_script(self, cli, script, data):
        prog = script("BEGIN { n = 0 }\n/ERROR/ { n += 1 }\nEND { print(n) }\n")
        assert cli("-f", prog, data).stdout == "2\n"

    def test_comments_and_blank_lines(self, cli, script, data):
        prog = script("# count\n\n\nEND {\n    # inside\n    print(NR)  # trailing\n}\n\n# done\n")
        assert cli("-f", prog, data).stdout == "4\n"

    def test_shebang_line_is_a_comment(self, cli, script, data):
        prog = script("#!/usr/bin/env pawk -f\nEND { print(NR) }\n")
        assert cli("-f", prog, data).stdout == "4\n"

    def test_no_trailing_newline(self, cli, script, data):
        assert cli("-f", script("END { print(NR) }"), data).stdout == "4\n"

    def test_crlf_line_endings(self, cli, script, data):
        prog = script(b"BEGIN { x = 1 }\r\nEND {\r\n    print(x, NR)\r\n}\r\n", mode="wb")
        r = cli("-f", prog, data)
        assert (r.returncode, r.stdout) == (0, "1 4\n")

    def test_utf8_in_the_script(self, cli, script):
        prog = script("{ print('héllo', len($1)) }\n")
        assert cli("-f", prog, stdin="wörld\n").stdout == "héllo 5\n"

    def test_empty_script_does_nothing_and_succeeds(self, cli, script, data):
        r = cli("-f", script(""), data)
        assert (r.returncode, r.stdout, r.stderr) == (0, "", "")

    def test_comment_only_script(self, cli, script, data):
        assert cli("-f", script("# nothing\n"), data).stdout == ""

    def test_def_import_and_rules_together(self, cli, script, data):
        prog = script("import collections\n\n"
                      "def top(c):\n    return c.most_common(1)[0]\n\n"
                      "BEGIN { c = collections.Counter() }\n"
                      "{ c[$1] += 1 }\n"
                      "END { print(top(c)) }\n")
        assert cli("-f", prog, data).stdout == "('ERROR', 2)\n"

    def test_logs_grouped_by_severity_in_a_dict(self, cli, script, data):
        prog = script("BEGIN { logs = {} }\n\n"
                      "NF > 1 {\n    logs.setdefault($1, []).append($2)\n}\n\n"
                      "END {\n    for severity, messages in logs.items():\n"
                      "        print(severity, len(messages), messages)\n}\n")
        assert cli("-f", prog, data).stdout == (
            "ERROR 2 ['disk', 'timeout']\nINFO 1 ['started']\nWARN 1 ['slow']\n")


class TestSeveralScripts:
    def test_files_are_concatenated_in_order(self, cli, script):
        a = script("BEGIN { print('a') }", "a.awk")
        b = script("BEGIN { print('b') }", "b.awk")
        assert cli("-f", a, "-f", b).stdout == "a\nb\n"
        assert cli("-f", b, "-f", a).stdout == "b\na\n"

    def test_a_definition_in_one_file_is_usable_in_another(self, cli, script):
        lib = script("def double(x):\n    return x * 2\n", "lib.awk")
        main = script("BEGIN { print(double(21)) }", "main.awk")
        assert cli("-f", lib, "-f", main).stdout == "42\n"

    def test_state_is_shared_between_files(self, cli, script):
        a = script("BEGIN { x = 1 }", "a.awk")
        b = script("END { print(x) }", "b.awk")
        assert cli("-f", a, "-f", b, stdin="").stdout == "1\n"

    def test_a_file_without_trailing_newline_does_not_glue_to_the_next(self, cli, script):
        a = script("BEGIN { print(1) }", "a.awk")
        b = script("BEGIN { print(2) }", "b.awk")
        assert cli("-f", a, "-f", b).stdout == "1\n2\n"


class TestScriptWithOptions:
    def test_dash_v_is_visible_to_the_script(self, cli, script):
        assert cli("-v", "n=3", "-f", script("BEGIN { print(n * 2) }")).stdout == "6\n"

    def test_dash_F_applies_to_the_script(self, cli, script):
        assert cli("-F:", "-f", script("{ print($2) }"), stdin="a:b:c\n").stdout == "b\n"

    def test_fs_set_in_the_script_beats_nothing_and_dash_F_is_overridden(self, cli, script):
        prog = script("BEGIN { FS = ',' } { print($2) }")
        assert cli("-F:", "-f", prog, stdin="a,b:c\n").stdout == "b:c\n"

    def test_dash_m_module_is_available_to_the_script(self, cli, script):
        assert cli("-m", "math", "-f", script("BEGIN { print(floor(2.7)) }")).stdout == "2\n"

    def test_assignment_operand_after_a_script(self, cli, script):
        prog = script("END { print(v) }")
        assert cli("-f", prog, "v=9", stdin="x\n").stdout == "9\n"

    def test_exit_status_comes_from_the_script(self, cli, script):
        assert cli("-f", script("BEGIN { exit 7 }")).returncode == 7


class TestScriptFromStdin:
    def test_dash_means_read_the_program_from_stdin(self, cli):
        assert cli("-f", "-", stdin="BEGIN { print('from stdin') }\n").stdout == "from stdin\n"

    def test_the_input_is_then_empty(self, cli):
        assert cli("-f", "-", stdin="END { print(NR) }\n").stdout == "0\n"

    def test_input_can_come_from_files(self, cli, data):
        assert cli("-f", "-", data, stdin="END { print(NR) }\n").stdout == "4\n"


class TestScriptErrors:
    def test_missing_script(self, cli, tmp_path):
        r = cli("-f", str(tmp_path / "nope.awk"))
        assert r.returncode == 2 and "cannot read" in r.stderr and "Traceback" not in r.stderr

    def test_script_is_a_directory(self, cli, tmp_path):
        r = cli("-f", str(tmp_path))
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_syntax_error_in_the_script(self, cli, script):
        r = cli("-f", script("BEGIN { x = }\n"))
        assert r.returncode == 2 and "syntax error" in r.stderr and r.stdout == ""

    def test_unterminated_brace(self, cli, script):
        r = cli("-f", script("{ print(1)\n"))
        assert r.returncode == 2 and "Traceback" not in r.stderr

    def test_bare_print_in_a_script_is_rejected(self, cli, script):
        r = cli("-f", script("{ print }\n"))
        assert r.returncode == 2 and "print(...)" in r.stderr

    def test_runtime_error_in_the_script(self, cli, script):
        r = cli("-f", script("BEGIN { print(nope) }\n"))
        assert r.returncode == 2 and "NameError" in r.stderr

    def test_binary_script_is_a_clean_error(self, cli, script):
        r = cli("-f", script(b"\xff\xfe\x00BEGIN", mode="wb"))
        assert r.returncode == 2 and "Traceback" not in r.stderr
