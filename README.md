# pawk-ng

An awk-style stream editor where the patterns and actions are plain Python 3.
You keep awk's execution model (`BEGIN`, `END`, pattern/action rules, range
patterns, `$1`/`$NF` fields and the awk variables `NR`, `NF`, `FS`, `OFS`, ...)
and drop awk's function library: you call Python (`len`, `str` methods, `re`,
`open`, `subprocess`, ...) and define your own functions with `def`.

## Install

```sh
pip install pawk-ng
```

The project is called pawk-ng, the command it installs is `pawk`. (The
unrelated [alecthomas/pawk](https://github.com/alecthomas/pawk) package
installs a command with the same name, so do not install both in one
environment.)

## One-liners

```sh
pawk '{ print($0) }' file                               # cat
pawk '{ print($1) }' file                               # first column
pawk '{ print($NF, $1) }' file                          # last column, then first
pawk '{ print(NR, $0) }' file                           # number the lines
pawk 'NR == 2' file                                     # second line
pawk 'NR == 1, NR == 3' file                            # lines 1 to 3
pawk '$2 > 28' file                                     # numeric comparison on a column
pawk '$3 == "NY"' file                                  # string comparison on a column
pawk '/NY$/' file                                       # lines matching a regex
pawk '!/NY/' file                                       # lines not matching
pawk 'NF' file                                          # drop empty lines
pawk 'END { print(NR) }' file                           # count lines
pawk '{ print(NF) }' file                               # fields per line
pawk '{ print($1, $2 * 2) }' file                       # arithmetic on a column
pawk '{ s += $2 } END { print(s) }' file                # sum a column
pawk '{ s += $2 } END { print(s / NR) }' file           # average a column
pawk '{ print(len($1), $1.upper()) }' file              # Python len() and str methods
pawk '{ print($1[:2]) }' file                           # Python slicing
pawk '{ print($NF.lower()) }' file                      # lowercase the last column
pawk '{ $2 = ""; print($0) }' file                      # blank out a column
pawk '{ $0 = re.sub("o", "0", $0); print($0) }' file    # substitute with re
pawk -v n=2 'NR == n' file                              # pass a variable
pawk -F: '{ print($1) }' /etc/passwd                    # field separator
pawk 'BEGIN { OFS = "," } { $1 = $1; print($0) }' file  # space to comma
pawk '{ print(*reversed($0.split())) }' file            # reverse the fields
pawk '{ n[$3] += 1 } END { print(dict(n)) }' file       # count by column
pawk 'BEGIN { print(2 ** 10, len("hello")) }'           # no input needed
pawk '{ print(f"{F[1]:>8}|{int(F[2]):4d}") }' file      # f-string formatting
```

## Usage

```sh
pawk [-F fs] [-v var=val] [-m module] [-f progfile] 'program' [file ...]
```

A program can be a file (`-f report.awk`) that mixes rules with ordinary
Python definitions and imports:

```python
import collections

def top(counts, n=3):
    return counts.most_common(n)

BEGIN { counts = collections.Counter() }

$3 != "" && !/^#/ {
    counts[$3] += 1
}

END {
    for city, n in top(counts):
        print(city, n)
}
```

```sh
pawk -f report.awk people.txt
```

## Language

* A program is a list of `[pattern] { python statements }` rules, plus
  top-level `def`/`import`/`class`. `BEGIN` and `END` may appear several
  times. A rule with only a pattern prints the record.
* **Fields.** `$expr` is field access (`$1`, `$NF`, `$(NF-1)`, `$$1`); `F` is
  the record object (`F[0]` is `$0`, iterating yields the fields). `$` is
  rewritten before Python runs, so it does not work inside strings: in an
  f-string write `F[1]`.
* **Rewrites.** `&&`, `||`, `!`, `/regex/` (becomes `re.search(r, $0)`, so the
  regex is a Python regex), and bare `next`, `nextfile`, `exit [n]`.
* **Variables.** `NR NF FNR FS OFS RS ORS FILENAME SUBSEP OFMT ENVIRON ARGV
  ARGC`. Assigning `$n`, `$0` or `NF` rebuilds the record with `OFS`. `FS`/`RS`
  may be a single character or a regex (POSIX classes like `[[:digit:]]`
  work there); `RS = ""` is paragraph mode.
* **Numeric strings.** Fields compare as numbers when both sides look numeric
  (`$1 > $2`), do arithmetic as numbers (`$1 + 1`), and concatenate with plain
  strings (`"a" + $1`). Unassigned variables read as `""`/`0`, and subscripted
  names (`n[$3] += 1`) become dicts automatically. A name that is never
  assigned is still a `NameError`.
* **Output.** `print` is Python's builtin `print`: `sep`, `end` and `file`
  work as usual and numbers print the Python way (`print(6 / 3)` is `2.0`).
  Always call it with parentheses: a bare `print` or `print $1, $2` is
  rejected as a syntax error. `OFS` is applied when a record is rebuilt after you
  assign a field or `NF`, `OFMT` formats floats assigned to fields, and `ORS`
  is only a variable: pass it yourself (`print(x, end=ORS)`) if you want it.
  Files, pipes and commands are `open(...)` and `subprocess`; call
  `sys.stdout.flush()` before a command that writes to the same output.
* `exit` in BEGIN skips input but runs END (as in POSIX awk).
* Not provided on purpose: awk's `length`, `substr`, `split`, `sub`, `gsub`,
  `match`, `printf`, `sprintf`, `getline`, `system`, `close`, `RSTART`,
  `RLENGTH` and friends. Use the Python equivalent.

## Tests

```sh
python -m pytest              # unit, contract and integration
python -m pytest -m contract
```

Integration tests also compare against the system `gawk`/`awk` when present.

## License

GPL-3.0-or-later. See `LICENSE`.
