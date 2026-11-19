# pawk-ng

[![PyPI](https://img.shields.io/pypi/v/pawk-ng)](https://pypi.org/project/pawk-ng/)
[![Python versions](https://img.shields.io/pypi/pyversions/pawk-ng)](https://pypi.org/project/pawk-ng/)
[![CI](https://github.com/vicentebolea/pawk-ng/actions/workflows/ci.yml/badge.svg)](https://github.com/vicentebolea/pawk-ng/actions/workflows/ci.yml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)

awk with Python as the language. You keep awk's model (`BEGIN`, `END`,
pattern/action rules, ranges, `$1`/`$NF`, `NR`, `NF`, `FS`, `OFS`, ...) and use
plain Python instead of awk's functions: `len`, `str` methods, `re`, `open`,
your own `def`s.

## Install

```sh
pip install pawk-ng
```

The package is `pawk-ng`, the command it installs is `pawk`. It conflicts with
the unrelated [alecthomas/pawk](https://github.com/alecthomas/pawk), so do not
install both in one environment.

## Examples

Fields are Python strings, so the whole language is available: methods, slicing,
`re`, and list/dict/generator comprehensions over `F` (the fields of the line).

```sh
pawk '{ print($1) }' file                                  # first column
pawk '{ print($NF, $1) }' file                             # last column, then first
pawk '{ print(NR, $0) }' file                              # number the lines
pawk 'NR == 2' file                                        # second line
pawk 'NR == 1, NR == 3' file                               # lines 1 to 3
pawk '$2 > 28' file                                        # numeric comparison
pawk '$3 == "NY"' file                                     # string comparison
pawk '/NY$/ && !/bob/' file                                # regex patterns
pawk 'NF' file                                             # drop empty lines
pawk 'END { print(NR) }' file                              # count lines
pawk '{ s += $2 } END { print(s / NR) }' file              # average a column
pawk '{ print(len($1), $1.upper(), $1[:2]) }' file         # Python len, methods, slicing
pawk '{ $0 = re.sub("o", "0", $0); print($0) }' file       # substitute with re
pawk '{ $2 = ""; print($0) }' file                         # blank out a column
pawk -F: '{ print($1) }' /etc/passwd                       # field separator
pawk -v n=2 'NR == n' file                                 # pass a variable
pawk 'BEGIN { OFS = "," } { $1 = $1; print($0) }' file     # space to comma
pawk '{ n[$3] += 1 } END { print(dict(n)) }' file          # count by column
pawk 'BEGIN { print(2 ** 10) }'                            # no input needed

pawk '{ print([f.upper() for f in F]) }' file              # list comprehension over the fields
pawk '{ print(sum(int(f) for f in F if f.is_num)) }' file  # generator: sum the numeric fields
pawk '{ print({f: len(f) for f in F}) }' file              # dict comprehension: field -> length
pawk '{ print("".join(f[0] for f in F)) }' file            # join: first letter of each field
# dict comprehension: repeated values
pawk '{ n[$3] += 1 } END { print({k: v for k, v in n.items() if v > 1}) }' file
# collect lines, then comprehend
pawk 'BEGIN { rows = [] } { rows.append($0) } END { print([r.split()[0] for r in rows if "NY" in r]) }' file
```

## `$` and `F`

`$n` and `F[n]` are the same thing. Before your program runs, pawk rewrites
every `$expr` into `F[expr]`, so use whichever reads better:

| awk style | Python style | meaning |
|---|---|---|
| `$0` | `F[0]` | the whole line |
| `$1`, `$2` | `F[1]`, `F[2]` | a field |
| `$NF` | `F[NF]` | the last field |
| `$(NF-1)` | `F[NF-1]` | a computed field |
| `$i` | `F[i]` | field number held in a variable |
| `$$1` | `F[F[1]]` | the field whose number is in field 1 |

`F` is also a regular Python object, which `$` is not:

```sh
pawk '{ print(len(F)) }' file              # same as NF
pawk '{ print(list(F)[1:]) }' file         # fields 1..NF as a list (F[0] is not included)
pawk '{ print([f.upper() for f in F]) }' file   # iterate over the fields
pawk '{ F[2] = "X"; print($0) }' file      # assigning rebuilds $0, just like $2 = "X"
```

Things to know:

* `$` is a text rewrite, so it only works in code, not inside strings. In an
  f-string write `F[1]`: `print(f"{F[1]:>8}")`.
* `$` binds tightly like in awk: `$NF-1` is `F[NF]-1`, and `$1.upper()` and
  `$1[:2]` are `F[1].upper()` and `F[1][:2]`.
* Reading a field past `NF` gives `""`. Assigning to one extends the line.
  Negative numbers are an error (use `$NF`, not `$-1`).
* Fields are numeric strings: `$1 > 5` and `$1 + $2` work on numbers when the
  text looks like one, and `$1.upper()` works as a string.

## Programs in a file

Rules can be mixed with ordinary Python (`import`, `def`, `class`). This
groups the messages of a log by severity in a dict:

```python
BEGIN { logs = {} }

NF > 1 {
    logs.setdefault($1, []).append($2)
}

END {
    for severity, messages in logs.items():
        print(severity, len(messages), messages)
}
```

```sh
pawk -f logs.awk app.log
```

```
ERROR 2 ['disk', 'timeout']
INFO 1 ['started']
WARN 1 ['slow']
```

Options: `-F fs`, `-v var=value`, `-f progfile`, `-m module` (`from module import *`).

## How it differs from awk

* **Python everywhere.** Actions are Python statements and patterns are Python
  expressions. `print` is Python's `print` and must be called with parentheses.
  There is no `length`, `substr`, `split`, `sub`, `gsub`, `match`, `printf`,
  `getline` or `system`: use the Python equivalent.
* **Fields.** `$1`, `$NF`, `$(NF-1)`, `$$1` are rewritten to `F[1]`, ...
  (`F[0]` is `$0`). This does not apply inside strings, so write `F[1]` in
  f-strings. Assigning `$n`, `$0` or `NF` rebuilds the record with `OFS`.
* **Other rewrites.** `&&`, `||`, `!`, `/regex/` (a Python regex, `re.search`
  on `$0`), and bare `next`, `nextfile`, `exit [n]`.
* **Numeric strings.** Fields compare and compute as numbers when they look
  numeric (`$1 > $2`, `$1 + 1`) and concatenate with plain strings.
* **Implicit variables.** Unassigned names read as `""`/`0`, and subscripted
  names (`n[$3] += 1`) become dicts. A name that is never assigned is a
  `NameError`.
* **Variables.** `NR NF FNR FS OFS RS ORS FILENAME SUBSEP OFMT ENVIRON ARGV
  ARGC`. `FS`/`RS` can be a character or a regex, and `RS = ""` is paragraph
  mode. `OFS` and `OFMT` apply when fields are assigned; `ORS` is only a
  variable (use `print(x, end=ORS)`).
* `exit` in `BEGIN` skips the input but still runs `END`.

## Tests

```sh
python -m pytest             # unit, contract and integration tests
python -m pytest -m contract
```

The integration tests also compare against the system `gawk`/`awk` when present.

## License

GPL-3.0-or-later. See `LICENSE`.

## Author

Vicente Adolfo Bolea Sanchez ([@vicentebolea](https://github.com/vicentebolea))
