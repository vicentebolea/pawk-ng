# pawk

An awk-style stream editor where the patterns and actions are plain Python 3.
You keep awk's execution model (`BEGIN`, `END`, pattern/action rules, range
patterns, `$1`/`$NF` fields and the awk variables `NR`, `NF`, `FS`, `OFS`, ...)
and drop awk's function library: you call Python (`len`, `str` methods, `re`,
`open`, `subprocess`, ...) and define your own functions with `def`.

## One-liners

    pawk '{ print }' file                        # cat
    pawk '{ print $1 }' file                     # first column
    pawk '{ print $NF, $1 }' file                # last column, then first
    pawk '{ print NR, $0 }' file                 # number the lines
    pawk 'NR == 2' file                          # second line
    pawk 'NR == 1, NR == 3' file                 # lines 1 to 3
    pawk '$2 > 28' file                          # numeric comparison on a column
    pawk '$3 == "NY"' file                       # string comparison on a column
    pawk '/NY$/' file                            # lines matching a regex
    pawk '!/NY/' file                            # lines not matching
    pawk 'NF' file                               # drop empty lines
    pawk 'END { print NR }' file                 # count lines
    pawk '{ print NF }' file                     # fields per line
    pawk '{ print $1, $2 * 2 }' file             # arithmetic on a column
    pawk '{ s += $2 } END { print s }' file      # sum a column
    pawk '{ s += $2 } END { print s / NR }' file # average a column
    pawk '{ print len($1), $1.upper() }' file    # Python len() and str methods
    pawk '{ print $1[:2] }' file                 # Python slicing
    pawk '{ print $NF.lower() }' file            # lowercase the last column
    pawk '{ $2 = ""; print }' file               # blank out a column
    pawk '{ $0 = re.sub("o", "0", $0); print }' file   # substitute with re
    pawk -v n=2 'NR == n' file                   # pass a variable
    pawk -F: '{ print $1 }' /etc/passwd          # field separator
    pawk 'BEGIN { OFS = "," } { $1 = $1; print }' file  # space to comma
    pawk '{ print(*reversed($0.split())) }' file # reverse the fields
    pawk '{ n[$3] += 1 } END { print dict(n) }' file    # count by column
    pawk 'BEGIN { print 2 ** 10, len("hello") }' # no input needed
    pawk '{ print(f"{F[1]:>8}|{int(F[2]):4d}") }' file  # f-string formatting

## Usage

    pawk [-F fs] [-v var=val] [-m module] [-f progfile] 'program' [file ...]

    def total(): return sum(F)          # top-level Python is allowed
    NR == 1, /stop/ && !/skip/ { print $1, total(); next }

## Language

* A program is a list of `[pattern] { python statements }` rules, plus
  top-level `def`/`import`/`class`. `BEGIN` and `END` may appear several
  times. A rule with no action prints the record.
* **Fields.** `$expr` is field access (`$1`, `$NF`, `$(NF-1)`, `$$1`); `F` is
  the record object (`F[0]` is `$0`, iterating yields the fields). `$` is
  rewritten before Python runs, so it does not work inside strings: in an
  f-string write `F[1]`.
* **Rewrites.** `&&`, `||`, `!`, `/regex/` (becomes `re.search(r, $0)`, so the
  regex is a Python regex), and bare `print`, `next`, `nextfile`, `exit [n]`.
* **Variables.** `NR NF FNR FS OFS RS ORS FILENAME SUBSEP OFMT ENVIRON ARGV
  ARGC`. Assigning `$n`, `$0` or `NF` rebuilds the record with `OFS`. `FS`/`RS`
  may be a single character or a regex (POSIX classes like `[[:digit:]]`
  work there); `RS = ""` is paragraph mode.
* **Numeric strings.** Fields compare as numbers when both sides look numeric
  (`$1 > $2`), do arithmetic as numbers (`$1 + 1`), and concatenate with plain
  strings (`"a" + $1`). Unassigned variables read as `""`/`0`, and subscripted
  names (`n[$3] += 1`) become dicts automatically. A name that is never
  assigned is still a `NameError`.
* **Output.** `print(*args, sep=OFS, end=ORS, file=stdout)` is Python's print
  with awk defaults: no arguments prints `$0`, and floats use `OFMT`. For
  files, pipes and commands use `open(...)` and `subprocess`; call
  `sys.stdout.flush()` before running a command that writes to the same output.
* `exit` in BEGIN skips input but runs END (as in POSIX awk).
* Not provided on purpose: awk's `length`, `substr`, `split`, `sub`, `gsub`,
  `match`, `printf`, `sprintf`, `getline`, `system`, `close`, `RSTART`,
  `RLENGTH` and friends. Use the Python equivalent.

## Tests

    python -m pytest              # unit, contract and integration
    python -m pytest -m contract

Integration tests also compare against the system `gawk`/`awk` when present.

## License

GPL-3.0-or-later. See `LICENSE`.
