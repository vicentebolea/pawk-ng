"""The interpreter: run the rules of a program over the input.

    BEGIN rules  ->  for each record: matching MAIN rules  ->  END rules
"""
# This is the top of the pipeline, and it is deliberately short.  Everything
# it needs is built by the modules before it:
#
#     parser    -> the list of `Rule`s (already compiled)
#     namespace -> the variables, and the globals the rules run in
#     records   -> the current record, `F`
#     inputs    -> the stream of records coming from `ARGV`
#
# The interpreter itself only decides *when* each rule runs.
#
# ## Control flow by exception
#
# `next`, `nextfile` and `exit` can be called from anywhere in user code, so
# they are implemented as exceptions (see `errors.py`).  The main loop
# catches `NextRecord` and `NextFile` per record, and `run` catches `Exit`
# around the whole BEGIN/main phase and again around END, which gives awk's
# rule that `exit` in BEGIN or in a main rule still runs END, but `exit` in
# END stops at once.
import math
import os
import re
import sys

from .errors import Exit, NextFile, NextRecord, PawkError
from .inputs import InputStream
from .namespace import Namespace, unescape
from .parser import parse
from .records import Record, RecordReader
from .values import to_num

__all__ = ["Exit", "NextFile", "NextRecord", "Record", "RecordReader", "Runtime", "unescape"]


class Runtime:
    def __init__(self, program, operands=(), fs=None, assigns=(), modules=(),
                 stdin=None, stdout=None, stderr=None, environ=None):
        self.rules = parse(program) if isinstance(program, str) else program
        self.stdout = stdout if stdout is not None else sys.stdout
        self.status = 0
        self.ranges_in_progress = {}   # range rules that are currently "on"
        self.ns = Namespace.with_awk_defaults(
            operands,
            os.environ if environ is None else environ,
            assigned_names=frozenset().union(*(rule.assigned_names for rule in self.rules)),
            array_names=frozenset().union(*(rule.array_names for rule in self.rules)))
        self.record = self.ns["F"] = Record(self.ns)
        self.inputs = InputStream(
            self.ns,
            stdin if stdin is not None else sys.stdin,
            stderr if stderr is not None else sys.stderr,
            on_unreadable_file=self._remember_input_failure)
        self.ns.update({
            "next": self._raise_next, "nextfile": self._raise_nextfile,
            "exit": self._raise_exit,
            "math": math, "re": re, "os": os, "sys": sys,
        })
        if fs is not None:
            self.ns["FS"] = unescape(fs)
        for assignment in assigns:
            self.ns.assign_from_text(assignment)
        for module in modules:
            exec("from %s import *" % module, self.ns)

    # -- the three phases ---------------------------------------------
    def run(self):
        """Run the program and return the exit status."""
        rules_of_kind = {kind: [rule for rule in self.rules if rule.kind == kind]
                         for kind in ("DEF", "BEGIN", "MAIN", "END")}
        real_stdout, sys.stdout = sys.stdout, self.stdout  # builtin print writes here
        try:
            try:
                for rule in rules_of_kind["DEF"]:
                    self._run_user_code(lambda rule=rule: exec(rule.code, self.ns), rule)
                for rule in rules_of_kind["BEGIN"]:
                    self._run_action(rule)
                if rules_of_kind["MAIN"] or rules_of_kind["END"]:
                    self._main_loop(rules_of_kind["MAIN"])
            except Exit as exit_signal:
                self._remember_exit_status(exit_signal)
            try:
                for rule in rules_of_kind["END"]:
                    self._run_action(rule)
            except Exit as exit_signal:
                self._remember_exit_status(exit_signal)
        except (NextRecord, NextFile):
            raise PawkError("next/nextfile used outside a main rule") from None
        finally:
            sys.stdout = real_stdout
            self._flush_stdout()
        return self.status

    def _main_loop(self, main_rules):
        """The implicit loop: one pass over the rules for every record."""
        while (record_text := self.inputs.next_record()) is not None:
            self.record.set_text(record_text)
            for rule in main_rules:
                try:
                    if self._rule_applies(rule):
                        self._run_action(rule)
                except NextRecord:
                    break
                except NextFile:
                    self.inputs.skip_file()
                    break

    # -- running one rule ---------------------------------------------
    def _rule_applies(self, rule):
        """Does ``rule`` apply to the current record?  Handles range patterns."""
        if rule.pattern is None:
            return True
        if rule.range_end_pattern is None:
            return bool(self._evaluate_pattern(rule.pattern, rule))
        key = id(rule)
        if not self.ranges_in_progress.get(key):
            if not self._evaluate_pattern(rule.pattern, rule):
                return False
            self.ranges_in_progress[key] = True
        if self._evaluate_pattern(rule.range_end_pattern, rule):  # may end on this very record
            self.ranges_in_progress[key] = False
        return True

    def _run_action(self, rule):
        """Run the action of ``rule``; a rule without one prints the record."""
        if rule.code is None:
            self.record.apply_nf_assignment()
            print(self.record.text, file=self.stdout)
        else:
            self._run_user_code(lambda: exec(rule.code, self.ns), rule)
            self._run_user_code(self.record.apply_nf_assignment, rule)  # NF = n takes effect now

    def _evaluate_pattern(self, code, rule):
        return self._run_user_code(lambda: eval(code, self.ns), rule)

    def _run_user_code(self, run, rule):
        """Call ``run()``, turning any error in user code into a `PawkError`
        that says which rule and which record it happened in.  The
        control-flow signals and a closed pipe pass through untouched."""
        try:
            return run()
        except (Exit, NextRecord, NextFile, PawkError, BrokenPipeError):
            raise
        except Exception as error:
            raise PawkError("%s: %s (in %r, record %s)" % (
                type(error).__name__, error, rule.source, self.ns["NR"])) from error

    # -- pieces of the surrounding machinery ---------------------------
    def next_record(self):
        return self.inputs.next_record()

    def _remember_input_failure(self):
        self.status = 2

    def _remember_exit_status(self, exit_signal):
        if exit_signal.code is not None:
            self.status = exit_signal.code

    def _flush_stdout(self):
        try:
            self.stdout.flush()
        except Exception:
            pass

    @staticmethod
    def _raise_exit(code=None):
        raise Exit(None if code is None else int(to_num(code)))

    @staticmethod
    def _raise_next():
        raise NextRecord()

    @staticmethod
    def _raise_nextfile():
        raise NextFile()
