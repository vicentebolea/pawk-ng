# pawk-ng

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

```sh
pawk '{ print($1) }' file                                # first column
pawk '{ print($NF, $1) }' file                           # last column, then first
pawk '{ print(NR, $0) }' file                            # number the lines
pawk 'NR == 2' file                                      # second line
pawk 'NR == 1, NR == 3' file                             # lines 1 to 3
pawk '$2 > 28' file                                      # numeric comparison
pawk '$3 == "NY"' file                                   # string comparison
pawk '/NY$/ && !/bob/' file                              # regex patterns
pawk 'NF' file                                           # drop empty lines
pawk 'END { print(NR) }' file                            # count lines
pawk '{ s += $2 } END { print(s / NR) }' file            # average a column
pawk '{ print(len($1), $1.upper(), $1[:2]) }' file       # Python len, methods, slicing
pawk '{ $0 = re.sub("o", "0", $0); print($0) }' file     # substitute with re
pawk '{ $2 = ""; print($0) }' file                       # blank out a column
pawk -F: '{ print($1) }' /etc/passwd                     # field separator
pawk -v n=2 'NR == n' file                               # pass a variable
pawk 'BEGIN { OFS = "," } { $1 = $1; print($0) }' file   # space to comma
pawk '{ n[$3] += 1 } END { print(dict(n)) }' file        # count by column
pawk 'BEGIN { print(2 ** 10) }'                          # no input needed
```

## Comprehensions

Fields are Python strings, so list, dict and generator expressions work
directly on `F` (the fields of the current line):

```sh
# list comprehension: uppercase every field
pawk '{ print([f.upper() for f in F]) }' file

# generator expression: sum the numeric fields of each line
pawk '{ print(sum(int(f) for f in F if f.is_num)) }' file

# dict comprehension: field -> length
pawk '{ print({f: len(f) for f in F}) }' file

# join a comprehension: the first letter of each field
pawk '{ print("".join(f[0] for f in F)) }' file

# filter a dict built across the whole input: values that repeat
pawk '{ n[$3] += 1 } END { print({k: v for k, v in n.items() if v > 1}) }' file

# collect lines in a list, then comprehend over it at the end
pawk 'BEGIN { rows = [] } { rows.append($0) } END { print([r.split()[0] for r in rows if "NY" in r]) }' file
```

## Programs in a file

Rules can be mixed with ordinary Python (`import`, `def`, `class`):

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
