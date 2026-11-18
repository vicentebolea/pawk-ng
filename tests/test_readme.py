"""Every example in README.md is executed and its output is pinned here.

The table below is checked against the README in both directions, so an
example cannot be added, changed or removed in the README without updating
a test.
"""
import os
import re
import shlex

import pytest

from conftest import ROOT

README = (ROOT / "README.md").read_text()

FILE = "alice 30 NY\nbob 25 LA\ncarol 35 NY\n"
PASSWD = "root:x:0:0\nbob:x:1000:1000\n"
PEOPLE = "alice 30 NY\nbob 25 LA\n# c x\ncarol 35 NY\n"

# command exactly as written in the README -> expected stdout
EXPECTED = {
    "pawk '{ print($1) }' file":
        'alice\nbob\ncarol\n',
    "pawk '{ print($NF, $1) }' file":
        'NY alice\nLA bob\nNY carol\n',
    "pawk '{ print(NR, $0) }' file":
        '1 alice 30 NY\n2 bob 25 LA\n3 carol 35 NY\n',
    "pawk 'NR == 2' file":
        'bob 25 LA\n',
    "pawk 'NR == 1, NR == 3' file":
        'alice 30 NY\nbob 25 LA\ncarol 35 NY\n',
    "pawk '$2 > 28' file":
        'alice 30 NY\ncarol 35 NY\n',
    'pawk \'$3 == "NY"\' file':
        'alice 30 NY\ncarol 35 NY\n',
    "pawk '/NY$/ && !/bob/' file":
        'alice 30 NY\ncarol 35 NY\n',
    "pawk 'NF' file":
        'alice 30 NY\nbob 25 LA\ncarol 35 NY\n',
    "pawk 'END { print(NR) }' file":
        '3\n',
    "pawk '{ s += $2 } END { print(s / NR) }' file":
        '30.0\n',
    "pawk '{ print(len($1), $1.upper(), $1[:2]) }' file":
        '5 ALICE al\n3 BOB bo\n5 CAROL ca\n',
    'pawk \'{ $0 = re.sub("o", "0", $0); print($0) }\' file':
        'alice 30 NY\nb0b 25 LA\ncar0l 35 NY\n',
    'pawk \'{ $2 = ""; print($0) }\' file':
        'alice  NY\nbob  LA\ncarol  NY\n',
    "pawk -F: '{ print($1) }' /etc/passwd":
        'root\nbob\n',
    "pawk -v n=2 'NR == n' file":
        'bob 25 LA\n',
    'pawk \'BEGIN { OFS = "," } { $1 = $1; print($0) }\' file':
        'alice,30,NY\nbob,25,LA\ncarol,35,NY\n',
    "pawk '{ n[$3] += 1 } END { print(dict(n)) }' file":
        "{'NY': 2, 'LA': 1}\n",
    "pawk 'BEGIN { print(2 ** 10) }'":
        '1024\n',
    "pawk '{ print(len(F)) }' file":
        '3\n3\n3\n',
    "pawk '{ print(list(F)[1:]) }' file":
        "['30', 'NY']\n['25', 'LA']\n['35', 'NY']\n",
    "pawk '{ print([f.upper() for f in F]) }' file":
        "['ALICE', '30', 'NY']\n['BOB', '25', 'LA']\n['CAROL', '35', 'NY']\n",
    'pawk \'{ F[2] = "X"; print($0) }\' file':
        'alice X NY\nbob X LA\ncarol X NY\n',
    "pawk '{ print(sum(int(f) for f in F if f.is_num)) }' file":
        '30\n25\n35\n',
    "pawk '{ print({f: len(f) for f in F}) }' file":
        "{'alice': 5, '30': 2, 'NY': 2}\n{'bob': 3, '25': 2, 'LA': 2}\n{'carol': 5, '35': 2, 'NY': 2}\n",
    'pawk \'{ print("".join(f[0] for f in F)) }\' file':
        'a3N\nb2L\nc3N\n',
    "pawk '{ n[$3] += 1 } END { print({k: v for k, v in n.items() if v > 1}) }' file":
        "{'NY': 2}\n",
    'pawk \'BEGIN { rows = [] } { rows.append($0) } END { print([r.split()[0] for r in rows if "NY" in r]) }\' file':
        "['alice', 'carol']\n",
}


def readme_commands():
    cmds = []
    for block in re.findall(r"```sh\n(.*?)```", README, re.S):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("pawk ") and "-f report.awk" not in line:
                cmds.append(re.split(r"\s{2,}#", line)[0].rstrip())
    return cmds


def readme_program():
    block = re.search(r"```python\n(def top.*?)```", README, re.S)
    return block.group(1)


@pytest.fixture
def workdir(tmp_path):
    (tmp_path / "file").write_text(FILE)
    (tmp_path / "passwd").write_text(PASSWD)
    (tmp_path / "people.txt").write_text(PEOPLE)
    return tmp_path


@pytest.fixture
def pawk(cli, workdir):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}

    def run(command):
        command = command.replace("/etc/passwd", "passwd")
        args = shlex.split(command)[1:]
        return cli(*args, cwd=workdir, env=env)
    return run


def test_table_covers_exactly_the_readme_examples():
    assert sorted(set(readme_commands())) == sorted(EXPECTED)


@pytest.mark.parametrize("command", list(EXPECTED))
def test_readme_example(pawk, command):
    r = pawk(command)
    assert (r.returncode, r.stderr) == (0, "")
    assert r.stdout == EXPECTED[command]


def test_program_file_example(cli, workdir):
    (workdir / "report.awk").write_text(readme_program())
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    r = cli("-f", "report.awk", "people.txt", cwd=workdir, env=env)
    assert (r.returncode, r.stderr, r.stdout) == (0, "", "NY 2\nLA 1\n")


class TestDollarVersusF:
    """The `$` and `F` section of the README."""

    @pytest.mark.parametrize("dollar,f", [
        ("$0", "F[0]"), ("$1", "F[1]"), ("$2", "F[2]"), ("$NF", "F[NF]"),
        ("$(NF-1)", "F[NF-1]"), ("$i", "F[i]"), ("$$1", "F[F[1]]"),
        ("$NF-1", "F[NF]-1"), ("$1.upper()", "F[1].upper()"), ("$1[:2]", "F[1][:2]"),
    ])
    def test_dollar_is_the_same_as_F(self, run_awk, dollar, f):
        prog = "BEGIN { i = 2 } { print(repr(%s)) }"
        text = "2 bb 3\n"
        assert run_awk(prog % dollar, text) == run_awk(prog % f, text)

    def test_len_of_F_is_nf(self, run_awk):
        assert run_awk("{ print(len(F) == NF) }", "a b c\n\n") == "True\nTrue\n"

    def test_list_of_F_skips_field_zero(self, run_awk):
        assert run_awk("{ print(list(F)) }", "a b\n") == "['a', 'b']\n"

    def test_assigning_F_rebuilds_the_record(self, run_awk):
        assert run_awk("{ F[2] = 'X'; print(F[0], NF) }", "a b c\n") == "a X c 3\n"

    def test_dollar_is_not_rewritten_inside_strings(self, run_awk):
        assert run_awk("{ print('$1', f'{F[1]}') }", "a\n") == "$1 a\n"

    def test_dollar_in_an_fstring_is_a_syntax_error(self, status_awk):
        import pawk_ng
        with pytest.raises(pawk_ng.ProgramError):
            status_awk("{ print(f'{$1}') }", "a\n")

    def test_past_nf_reads_empty_and_assigning_extends(self, run_awk):
        assert run_awk("{ print(repr($9), NF); $5 = 'e'; print($0) }", "a\n") == \
            "'' 1\na    e\n"

    def test_negative_field_is_an_error(self, status_awk):
        import pawk_ng
        with pytest.raises(pawk_ng.PawkError):
            status_awk("{ print(F[-1]) }", "a\n")

    def test_fields_are_numeric_strings_and_strings(self, run_awk):
        assert run_awk("{ print($1 > 5, $1 + $2, $1.upper()) }", "10 x\n") == "True 10 10\n"
