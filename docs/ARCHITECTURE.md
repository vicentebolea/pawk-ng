# Architecture review

This document reviews the architecture of pawk-ng, records what was changed
and why, and compares the architectural paradigms that could make the code
easier to read and maintain.

## What pawk-ng has to do

1. Read an awk-shaped program whose actions are Python.
2. Rewrite the few awk-isms (`$1`, `/re/`, `&&`, `next`) into Python.
3. Run the rules for every record of the input, keeping awk's variables
   (`NR`, `NF`, `FS`, ...) and its value semantics (numeric strings,
   uninitialized variables).

## Before: two big modules

```text
cli ──► runtime (370 lines) ──► parser (369 lines) ──► errors
              │  ▲
              └──┘ Record <-> Runtime call each other
            values
```

| Finding | Where | Why it hurts |
|---|---|---|
| `Runtime` is a god class | `runtime.py` | It owns the variable table, the `ARGV` input walk, record reading, rule execution, exit handling and the built-ins. A change to any of them means reading all of them. |
| `Record` and `Runtime` depend on each other | `Record.__init__(rt)`, `rt.var`, `rt.sync_nf` | A cycle: `Record` cannot be tested or understood without a whole `Runtime`; tests had to build one just to split a line. |
| `parser.py` has three jobs | lexer, translator and rule grammar in one file | Three reasons to change in one place; the private helpers (`_next_sig`, `_group_end`) were shared by all three. |
| Control-flow signals live in `runtime.py` | `Exit`, `NextRecord`, `NextFile` | The parser's errors and the runtime's signals were defined in different modules, so nothing could import them without importing the interpreter. |
| `ProgramError` was defined in the parser | `parser.py` | The CLI imported the parser only for an exception type. |
| `Rule` was a hand-written `__slots__` class | `parser.py` | Boilerplate, and the optional fields were assigned after construction. |
| Input handling was spread across methods and flags | `_open_next`, `_used_input`, `_argi`, `_reader` | The rules for `ARGV` (assignments between files, skipped empty operands, implicit stdin) were hard to find. |

## After: a pipeline of small modules

```text
errors ◄── values
   ▲          ▲
   │          │
 lexer ──► translate ──► parser ───────────────┐
                                                ▼
 namespace ──► records ──► inputs ──────────► runtime ──► cli
```

Text flows left to right through stages that each know only about the stages
before them.

| Module | Lines | Single responsibility |
|---|---|---|
| `errors` | 40 | Error types and control-flow signals |
| `values` | 279 | awk's value semantics: numeric strings, conversions, regexes, field splitting |
| `lexer` | 161 | Program text to tokens |
| `translate` | 90 | Tokens to Python text (`$1` to `F[1]`, ...) |
| `parser` | 238 | Tokens to compiled `Rule`s; analysis of implicit variables |
| `namespace` | 83 | The variables (the globals the user's code runs in) |
| `records` | 163 | `RecordReader` (cut a stream into records) and `Record` (the `F` object) |
| `inputs` | 84 | `ARGV` to a stream of records, maintaining `NR`/`FNR`/`FILENAME` |
| `runtime` | 177 | When each rule runs: BEGIN, the implicit loop, END |
| `cli` | 91 | The process boundary: options, encodings, exit codes |

Concrete changes:

* `Record` now depends on a `Namespace`, not on the whole `Runtime`. The `NF`
  reconciliation is `Record.apply_nf_assignment()`, in one place.
* `InputStream` owns everything about `ARGV`; `Runtime` only asks it for the
  next record or tells it to skip a file.
* The lexer's helpers are public functions with descriptive names
  (`index_of_next_significant`, `index_of_closing_bracket`) instead of shared
  underscore-prefixed ones.
* Errors and signals moved to `errors.py`; `Rule` is a dataclass; `RecordReader.read`
  is split into `_paragraph` and `_separated`; `Runtime.run` groups rules by
  kind once.
* The public API (`pawk_ng.run`, `awk`, `parse`, the error types) and the
  command line are unchanged, and so are all existing tests.

### The dependency rule

Imports may only point **backwards** along the pipeline. This is not just a
convention: `tests/test_architecture.py` parses every module and fails if an
import is added that breaks the table of allowed dependencies or creates a
cycle. The table doubles as an up-to-date map of the system.

## Naming: literate programming as a guide

Literate programming is used here only as a guide to naming and commenting,
not as a tool: the `.py` files are the only source, and nothing is generated.
The idea is that the code should read like prose, so a reader does not need
a comment to know what a name means.

* **Functions are verbs, predicates are questions.** `parse_definition`,
  `translate_field_reference`, `index_of_closing_bracket`, `_open_next_operand`;
  `_rule_applies`, `looks_numeric`, `is_at_line_start`.
* **No single-letter names** except for a loop index over a few lines. `toks`,
  `k`, `m`, `e` and `rs` became `tokens`, `position`, `match`, `error` and
  `record_separator`.
* **A name says what it holds, not its type.** `ranges_in_progress` instead of
  `active_ranges`, `opened_any_input` instead of `used_input`, `range_end_pattern`
  instead of `pattern2`, `stream_is_buffered` instead of `slurped`.
* **Verbs say the effect.** `Record.apply_nf_assignment` instead of `sync`,
  `Namespace.assign_from_text` instead of `assign`, `_run_user_code` instead of
  `_guard`, `_remember_exit_status` instead of `_set_exit`.
* **Each module opens with why it exists**, in its docstring, followed by the
  few paragraphs of reasoning that the code cannot express (why `RS` is read
  per record, why `NF` is reconciled on access). Ordinary `#` comments explain
  *why*, never *what*.
* Names that tests and the public API depend on (`Runtime`, `parse`,
  `tokenize`, `translate`, `RecordReader.read`, `Record.set_text`, `to_num`,
  `to_str`, `Field`) were left alone.

## Paradigms considered

| Paradigm | What it would look like here | Verdict |
|---|---|---|
| **Pipeline / layered** | Each stage is a module that transforms the output of the previous one. | **Adopted.** It matches the problem (text in, records through rules) and gives every module one reason to change. |
| **Functional core, imperative shell** | Pure functions for lexing, translating, splitting and conversion; all I/O at the edges (`cli`, `inputs`). | **Adopted where free.** `lexer`, `translate`, `values` and `RecordReader`'s parsing are already pure or nearly so; I/O is confined to `cli`, `inputs` and the `print` target. The interpreter's state (variables, current record) is inherently mutable, so a pure core would mean threading it through every call. |
| **Hexagonal (ports and adapters)** | `InputStream` and the output stream as ports with file, stdin and in-memory adapters. | **Partially.** `Runtime` already takes `stdin`, `stdout`, `stderr` as parameters, which is the useful half; a formal port class would add indirection with a single real implementation. Revisit if inputs other than files appear. |
| **Interpreter pattern with a real AST** | Parse the program with `ast`, transform `$n` and `next` with a `NodeTransformer`. | **Rejected for now.** Python's parser cannot read `$1` or `/re/`, so a textual pass is unavoidable, and it would then have to be followed by the AST pass. The token rewrites are 90 lines and cover everything. Revisit if the rewrites grow past a handful or need scoping information. |
| **Generator pipeline for records** | `records(ns)` as a generator that the main loop iterates. | **Not adopted.** `RS` can change between two reads and `ARGV` is read lazily while the program runs; an explicit `next_record()` makes both visible, while a generator hides them. `InputStream` could grow an `__iter__` wrapper if a caller wants one. |
| **Observer / reactive variables** | The namespace notifies the record when `NF` (or `FS`) is assigned. | **Rejected.** Python's `exec` with a dict subclass gives no assignment hook for module-level code, and functions defined by the user bypass it. The explicit `Record.apply_nf_assignment()` on every access is simple and always correct. |
| **Dataclasses and typed boundaries** | `Rule` as a dataclass; type hints on the module interfaces. | **Adopted for `Rule`.** Full type hints would add noise for a codebase this size; revisit with a type checker in CI. |
| **Plugin / strategy for built-ins** | Register awk-style functions (`length`, `substr`, ...) through a registry. | **Rejected by design.** The project's premise is that Python's own functions replace awk's; there is nothing to register. |

## Remaining weak spots (not changed here)

* The user's code runs in the same dictionary the interpreter reads its own
  variables from. This is the core trade-off of the design (shared variables
  with no copying) and it explains `Record.apply_nf_assignment()`, but a user who assigns
  garbage to `FS` is only caught when the next record is split.
* `$` is a text rewrite, so it does not work inside strings or f-strings.
* A record separator other than a newline reads the whole stream into memory.
* `ORS`, `SUBSEP` and `ARGC` are plain variables with no effect of their own;
  this is documented in the README and pinned by tests.
