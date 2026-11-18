"""Integration tests: the real CLI, files, pipes, and differential checks vs awk."""
import pytest

pytestmark = pytest.mark.integration

DATA = "alice 30 NY\nbob 25 LA\ncarol 35 NY\ndave 28 SF\n"


@pytest.fixture
def datafile(tmp_path):
    p = tmp_path / "data.txt"
    p.write_text(DATA)
    return p


class TestCli:
    def test_stdin(self, cli):
        r = cli("{ print($2) }", stdin=DATA)
        assert (r.returncode, r.stdout, r.stderr) == (0, "30\n25\n35\n28\n", "")

    def test_file_operand(self, cli, datafile):
        assert cli("NR == 1 { print($1) }", str(datafile)).stdout == "alice\n"

    def test_multiple_files_and_filename(self, cli, datafile, tmp_path):
        other = tmp_path / "o.txt"
        other.write_text("z 1 ZZ\n")
        r = cli("END { print(NR, FNR, FILENAME) }", str(datafile), str(other))
        assert r.stdout == f"5 1 {other}\n"

    def test_dash_F(self, cli):
        assert cli("-F:", "{ print($2) }", stdin="a:b:c\n").stdout == "b\n"
        assert cli("-F", ",", "{ print($2) }", stdin="a,b,c\n").stdout == "b\n"

    def test_dash_F_escape_and_regex(self, cli):
        assert cli("-F\\t", "{ print($2) }", stdin="a b\tc\n").stdout == "c\n"
        assert cli("-F", "[0-9]+", "{ print($2) }", stdin="a12b\n").stdout == "b\n"

    def test_dash_v(self, cli):
        r = cli("-v", "n=3", "-v", "s=hi\\tthere", "BEGIN { print(n + 1, s) }")
        assert r.stdout == "4 hi\tthere\n"

    def test_dash_v_value_is_strnum(self, cli):
        assert cli("-v", "n=10", "BEGIN { print(n > 9) }").stdout == "True\n"

    def test_dash_v_requires_equals(self, cli):
        r = cli("-v", "oops", "BEGIN{}")
        assert r.returncode == 2 and "var=value" in r.stderr

    def test_dash_f_program_file(self, cli, tmp_path):
        prog = tmp_path / "p.pawk"
        prog.write_text("# comment\nBEGIN { n = 0 }\n$2 > 26 { n += 1 }\nEND { print(n) }\n")
        assert cli("-f", str(prog), stdin=DATA).stdout == "3\n"

    def test_multiple_dash_f(self, cli, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_text("BEGIN { x = 1 }")
        b.write_text("END { print(x) }")
        assert cli("-f", str(a), "-f", str(b), stdin="").stdout == "1\n"

    def test_dash_f_with_files_following(self, cli, tmp_path, datafile):
        prog = tmp_path / "p"
        prog.write_text("END { print(NR) }")
        assert cli("-f", str(prog), str(datafile)).stdout == "4\n"

    def test_dash_m_imports_names(self, cli):
        r = cli("-m", "math", "BEGIN { print(floor(2.7), pi > 3) }")
        assert r.stdout == "2 True\n"

    def test_exit_status_propagates(self, cli):
        assert cli("BEGIN { exit 42 }").returncode == 42
        assert cli("{ exit 3 }", stdin="x\n").returncode == 3

    def test_version(self, cli):
        r = cli("--version")
        assert r.returncode == 0 and r.stdout.startswith("pawk-ng ")

    def test_no_program(self, cli):
        r = cli()
        assert r.returncode == 2 and "no program" in r.stderr

    def test_syntax_error_reports_and_exits_2(self, cli):
        r = cli("{ x = }")
        assert r.returncode == 2 and "syntax error" in r.stderr and r.stdout == ""

    def test_runtime_error_exits_2_with_context(self, cli):
        r = cli("{ print(nope) }", stdin="x\n")
        assert r.returncode == 2 and "NameError" in r.stderr and "record 1" in r.stderr

    def test_missing_file_warns_continues_and_exits_2(self, cli, datafile, tmp_path):
        r = cli("END { print(NR) }", str(tmp_path / "nope"), str(datafile))
        assert r.returncode == 2 and r.stdout == "4\n" and "cannot open" in r.stderr

    def test_missing_program_file(self, cli, tmp_path):
        r = cli("-f", str(tmp_path / "nope"))
        assert r.returncode == 2 and "cannot read" in r.stderr

    def test_unicode_roundtrip(self, cli):
        assert cli("{ print(len($1), $1.upper()) }", stdin="héllo wörld\n").stdout == \
            "5 HÉLLO\n"

    def test_invalid_utf8_bytes_survive(self, tmp_path):
        import subprocess
        import sys
        f = tmp_path / "bin"
        f.write_bytes(b"a\xff b\n")
        r = subprocess.run([sys.executable, "-m", "pawk_ng", "{ print($1) }", str(f)],
                           capture_output=True)
        assert r.stdout == b"a\xff\n"

    def test_crlf_preserved_in_last_field(self):
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "-m", "pawk_ng", "{ print($2) }"],
                           input=b"a b\r\n", capture_output=True)
        assert r.stdout == b"b\r\n"

    def test_large_input_streams(self, cli):
        n = 20000
        r = cli("{ s += $1 } END { print(s) }",
                stdin="".join(f"{i}\n" for i in range(n)))
        assert r.stdout == f"{n * (n - 1) // 2}\n"

    def test_closed_stdout_is_not_a_traceback(self, tmp_path):
        import subprocess
        import sys
        p = subprocess.run(
            f"{sys.executable} -m pawk_ng 'BEGIN {{ for i in range(100000): print(i) }}' | head -1",
            shell=True, capture_output=True, text=True)
        assert p.stdout == "0\n" and "Traceback" not in p.stderr

    def test_dollar_in_shell_quotes_end_to_end(self, cli):
        assert cli("{ print($NF) }", stdin="a b c\n").stdout == "c\n"


class TestPythonIO:
    """File, pipe and process I/O is plain Python, not awk redirection."""

    def test_print_to_file_object(self, cli, tmp_path):
        out = tmp_path / "o.txt"
        out.write_text("old\n")
        cli(f"BEGIN {{ f = open({str(out)!r}, 'w') }}\n{{ print($1, file=f) }}\n"
            "END { f.close() }", stdin="a\nb\n")
        assert out.read_text() == "a\nb\n"

    def test_append_mode(self, cli, tmp_path):
        out = tmp_path / "o.txt"
        out.write_text("old\n")
        cli(f"BEGIN {{ f = open({str(out)!r}, 'a') }}\n{{ print($1, file=f) }}\n"
            "END { f.close() }", stdin="a\n")
        assert out.read_text() == "old\na\n"

    def test_format_to_file_and_read_back(self, cli, tmp_path):
        out = tmp_path / "o.txt"
        prog = (f"BEGIN {{ f = {str(out)!r}\n"
                "  with open(f, 'w') as h: h.write('%d-%s\\n' % (7, 'x'))\n"
                "  print(open(f).read().strip()) }")
        assert cli(prog).stdout == "7-x\n"

    def test_output_through_subprocess_pipe(self, cli):
        prog = ("import subprocess\n"
                "BEGIN { p = subprocess.Popen(['sort', '-r'], stdin=subprocess.PIPE, text=True) }\n"
                "{ print($1, file=p.stdin) }\n"
                "END { p.stdin.close(); p.wait(); print('done') }")
        assert cli(prog, stdin="a\nc\nb\n").stdout == "c\nb\na\ndone\n"

    def test_subprocess_exit_status(self, cli):
        prog = ("import subprocess\n"
                "BEGIN { p = subprocess.Popen(['sh', '-c', 'cat >/dev/null; exit 3'],"
                " stdin=subprocess.PIPE); p.stdin.close(); print(p.wait()) }")
        assert cli(prog).stdout == "3\n"

    def test_read_another_file_while_processing(self, cli, datafile):
        prog = (f"BEGIN {{ for line in open({str(datafile)!r}): print(line.split()[0]) }}")
        assert cli(prog).stdout == "alice\nbob\ncarol\ndave\n"

    def test_capture_command_output(self, cli):
        prog = ("import subprocess\nBEGIN { out = subprocess.check_output("
                "['printf', '1\\\\n2\\\\n'], text=True).split(); print([int(x) * 2 for x in out]) }")
        assert cli(prog).stdout == "[2, 4]\n"

    def test_subprocess_output_ordering_with_flush(self, cli):
        prog = ("import subprocess\n"
                "BEGIN { print('a'); sys.stdout.flush(); rc = subprocess.call('echo b; exit 2', shell=True);"
                " print('c', rc) }")
        assert cli(prog).stdout == "a\nb\nc 2\n"

    def test_stderr_goes_to_stderr(self, cli):
        r = cli("{ print('oops', file=sys.stderr) }", stdin="x\n")
        assert r.stdout == "" and r.stderr == "oops\n"

    def test_environment_and_argv(self, cli, tmp_path):
        r = cli("BEGIN { print(ENVIRON['PAWK_T'], ARGV[1:]) }", "x=1",
                env={"PAWK_T": "v", "PATH": __import__("os").environ["PATH"]})
        assert r.stdout == "v ['x=1']\n"


class TestRealWorldPrograms:
    def test_group_and_sum(self, cli, datafile):
        prog = ("{ s[$3] += $2 }\n"
                "END { for k in sorted(s): print(k, s[k]) }")
        assert cli(prog, str(datafile)).stdout == "LA 25\nNY 65\nSF 28\n"

    def test_csv_to_tsv_with_header_skip(self, cli):
        r = cli("-F,", "BEGIN { OFS = '\\t' } NR > 1 { $1 = $1; print($0) }",
                stdin="h1,h2\na,b\nc,d\n")
        assert r.stdout == "a\tb\nc\td\n"

    def test_max_and_average(self, cli, datafile):
        prog = ("NR == 1 || $2 > mx { mx = $2; who = $1 }\n{ t += $2 }\n"
                "END { print(f'{who} {mx} {t / NR:.2f}') }")
        assert cli(prog, str(datafile)).stdout == "carol 35 29.50\n"

    def test_dedupe_preserving_order(self, cli):
        assert cli("{ seen = globals().setdefault('seen', set()) }\n"
                   "$0 not in seen { seen.add($0); print($0) }",
                   stdin="a\nb\na\nc\nb\n").stdout == "a\nb\nc\n"

    def test_reverse_fields(self, cli):
        assert cli("{ print(*reversed(list(F))) }", stdin="a b c\n").stdout == "c b a\n"

    def test_word_frequency_with_counter(self, cli):
        prog = ("import collections\nBEGIN { c = collections.Counter() }\n"
                "{ c.update(w.lower() for w in F) }\n"
                "END { for w, n in c.most_common(2): print(w, n) }")
        assert cli(prog, stdin="a B a\nb A\n").stdout == "a 3\nb 2\n"

    def test_gsub_in_place_then_print(self, cli):
        assert cli("{ $0 = re.sub('o', '0', $0); print($0) }", stdin="foo boo\n").stdout == "f00 b00\n"

    def test_sub_on_field_variable(self, cli):
        assert cli("{ $2 = re.sub('[0-9]', '#', $2); print($0) }", stdin="a 123\n").stdout == "a ###\n"

    def test_range_extract_block(self, cli):
        text = "x\n[start]\na\nb\n[end]\ny\n"
        assert cli("/\\[start\\]/, /\\[end\\]/ { if NR > 2 and not re.search('end', $0): print($0) }",
                   stdin=text).stdout == "a\nb\n"

    def test_empty_and_whitespace_only_lines(self, cli):
        assert cli("NF { n += 1 } END { print(n, NR) }", stdin="a\n\n  \nb\n").stdout == "2 4\n"


EQUIVALENT = [
    # (pawk program, awk program)
    ("{ print($2 * 2) }", "{ print $2 * 2 }"),
    ("$2 > 26 { print($1) }", "$2 > 26 { print $1 }"),
    ("{ s += $2 } END { print(s, NR) }", "{ s += $2 } END { print s, NR }"),
    ("NR % 2", "NR % 2"),
    ("NR == 2, NR == 3", "NR == 2, NR == 3"),
    ("/a/ && !/o/", "/a/ && !/o/"),
    ("{ print(NF, $NF, $(NF-1)) }", "{ print NF, $NF, $(NF-1) }"),
    ("BEGIN { OFS = '-' } { $1 = $1; print($0) }", "BEGIN { OFS = \"-\" } { $1 = $1; print }"),
    ("{ NF = 2; print($0) }", "{ NF = 2; print }"),
    ("{ $5 = 'x'; print($0); print(NF) }", "{ $5 = \"x\"; print; print NF }"),
    ("{ print(len($1), $1.upper(), $1[1:4], $1.find('a') + 1) }",
     "{ print length($1), toupper($1), substr($1, 2, 3), index($1, \"a\") }"),
    ("{ print('%-6s|%5.1f|%03d' % ($1, $2 / 3, int($2))) }",
     "{ printf \"%-6s|%5.1f|%03d\\n\", $1, $2 / 3, $2 }"),
    ("{ $0 = re.sub('[aeiou]', '<\\\\g<0>>', $0); print($0) }", "{ gsub(/[aeiou]/, \"<&>\"); print }"),
    ("$2 > $3 || $1 < 'c' { print($0) }", "$2 > $3 || $1 < \"c\" { print }"),
    ("END { print($0, NF) }", "END { print $0, NF }"),
    ("BEGIN { print(7 // 2, 2**10, 10 % 3) }", "BEGIN { print int(7/2), 2^10, 10 % 3 }"),
    ("{ m = re.search('a+', $0); print(m.start() + 1 if m else 0) }",
     "{ print match($0, /a+/) }"),
]


@pytest.mark.parametrize("prog,awk_prog", EQUIVALENT)
def test_matches_real_awk(cli, gawk, prog, awk_prog):
    text = "alpha 30 7\nbob 25 9\ncarol 35 2\n\nda ve 28 1 extra\n"
    assert cli(prog, stdin=text).stdout == gawk(awk_prog, text)


def test_matches_real_awk_with_fs_and_rs(cli, gawk):
    text = "a:b:c;d:e:f;g"
    assert cli("-F:", "BEGIN { RS = ';' } { print(NR, NF, $NF) }", stdin=text).stdout == \
        gawk("BEGIN { RS = \";\"; FS = \":\" } { print NR, NF, $NF }", text)


def test_matches_real_awk_paragraph_mode(cli, gawk):
    text = "a b\nc\n\n\nd e\nf g\n"
    assert cli("BEGIN { RS = '' } { print(NR, NF, $1, $NF) }", stdin=text).stdout == \
        gawk("BEGIN { RS = \"\" } { print NR, NF, $1, $NF }", text)
