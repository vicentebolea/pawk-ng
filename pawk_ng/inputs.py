"""Where records come from: the operands of the command line."""
# An `InputStream` turns `ARGV` into a sequence of records, maintaining
# `NR`, `FNR` and `FILENAME` on the way.
#
# awk reads `ARGV` *lazily*, one operand at a time, while the program runs.
# That is why a `BEGIN` rule can append a file to `ARGV` and have it read,
# and why a `var=value` operand between two files takes effect exactly
# between them.  The stream therefore keeps an index into the live `ARGV`
# list instead of copying it.
import re

from .errors import PawkError
from .namespace import Namespace
from .records import RecordReader
from .values import to_num, to_str

_VARIABLE_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")


class InputStream:
    def __init__(self, namespace: Namespace, stdin, stderr, on_unreadable_file=lambda: None):
        self.namespace = namespace
        self.stdin = stdin
        self.stderr = stderr
        self.on_unreadable_file = on_unreadable_file
        self._reader = None
        self._next_operand_index = 1       # ARGV[0] is the program name
        self._opened_any_input = False     # has any file (or stdin) been opened yet?

    def next_record(self):
        """The text of the next record, or None when all input is consumed."""
        while True:
            if self._reader is None and not self._open_next_operand():
                return None
            record_text = self._reader.read(self.namespace.text("RS"))
            if record_text is None:
                self.skip_file()
                continue
            self.namespace["NR"] = to_num(self.namespace["NR"]) + 1
            self.namespace["FNR"] = to_num(self.namespace["FNR"]) + 1
            return record_text

    def skip_file(self):
        """Stop reading the current file (end of file, or `nextfile`)."""
        if self._reader is not None and self._reader.stream is not self.stdin:
            self._reader.stream.close()
        self._reader = None

    def _open_next_operand(self):
        """Advance through `ARGV` to the next readable file.  False when done."""
        argv = self.namespace["ARGV"]
        if not isinstance(argv, (list, tuple)):
            raise PawkError("ARGV must be a list, not %s" % type(argv).__name__)
        while self._next_operand_index < len(argv):
            operand = to_str(argv[self._next_operand_index])
            self._next_operand_index += 1
            if operand == "":
                continue                                  # an emptied operand is skipped
            if _VARIABLE_ASSIGNMENT.match(operand):
                self.namespace.assign_from_text(operand)  # var=value between files
                continue
            self._opened_any_input = True
            stream = self._open_file(operand)
            if stream is None:
                continue
            self.namespace["FILENAME"], self.namespace["FNR"] = operand, 0
            self._reader = RecordReader(stream)
            return True
        if not self._opened_any_input:                    # no file operands: read stdin
            self._opened_any_input = True
            self._reader = RecordReader(self.stdin)
            self.namespace["FNR"] = 0
            return True
        return False

    def _open_file(self, name):
        if name == "-":
            return self.stdin
        try:
            return open(name, encoding="utf-8", errors="surrogateescape", newline="\n")
        except OSError as error:
            self.stderr.write("pawk: cannot open %s (%s)\n" % (name, error.strerror))
            self.on_unreadable_file()
            return None
