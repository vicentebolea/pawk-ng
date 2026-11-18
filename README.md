# pawk

An awk-style stream editor where the patterns and actions are Python 3.
BEGIN, END, range patterns, `NR NF FNR FS OFS RS ORS FILENAME SUBSEP RSTART
RLENGTH OFMT ENVIRON ARGV ARGC`, `$0 $1 $NF`, `next`, `nextfile` and `exit`
all work as in awk. Functions are Python `def`s.

    pawk [-F fs] [-v var=val] [-m module] [-f progfile] 'program' [file ...]

    pawk -F: 'BEGIN { print "user shells" } $3 >= 1000 { n[$7] += 1 } END { print(sorted(n.items())) }' /etc/passwd

    def total(): return sum(F)          # top-level Python is allowed
    NR == 1, /stop/ && !/skip/ { print $1, total(); next }

## Language

* A program is a list of `[pattern] { python statements }` rules, plus
  top-level `def`/`import`/`class`. `BEGIN`/`END` may appear several times.
* `$expr` is field access (`$NF`, `$(NF-1)`, `$$1`); `F` is the record object
  (`F[0]` is `$0`, iterating yields the fields). `&&`, `||`, `!`, `/regex/`
  patterns and bare `print`, `next`, `exit [n]` are rewritten to Python.
* Fields are numeric strings: `$1 > $2` compares as numbers when both look
  numeric, `$1 + 1` is arithmetic, `"a" + $1` is concatenation.
* Assigning `$n`, `$0` or `NF` rebuilds the record using `OFS`.
* Unassigned variables read as `""`/`0`; subscripted names are auto-created
  arrays (dicts). A name that is never assigned is still a `NameError`.
* Built-ins: `print printf sprintf length substr index split match sub gsub
  tolower toupper rand srand system close fflush getline getline_from
  getline_cmd matches num`. `print`/`printf` accept `to=path`, `append=True`
  or `pipe=cmd`. `sub`/`gsub` edit `$0` (returning the count) unless a target
  string is given, in which case they return the new string.
* `exit` in BEGIN skips input but runs END (as in POSIX awk).

## Tests

    python -m pytest              # unit, contract and integration
    python -m pytest -m contract

Integration tests also compare against the system `gawk`/`awk` when present.

## License

GPL-3.0-or-later. See `LICENSE`.
