"""Records and fields: reading records from a stream and splitting them."""
# Two classes, one for each half of the job: `RecordReader` cuts a stream
# into records, `Record` is the current record and its fields (the `F`
# object).
#
# ## Why the reader is not just `for line in file`
#
# awk lets the program change `RS` *while it runs*, and the very next record
# must obey the new separator.  So the reader cannot be a fixed iterator: it
# is asked for one record at a time, and told the separator each time.
#
# The common case (`RS` is a newline) streams line by line.  Any other
# separator needs to look ahead, so the rest of the stream is read into a
# buffer on first use.
import re

from .errors import PawkError
from .namespace import Namespace
from .values import Field, regex, split_text, to_num, to_str

MAX_FIELDS = 10_000_000  # a guard against `NF = 10**12` exhausting memory


class RecordReader:
    """Reads records separated by `RS`, which may change between reads."""

    def __init__(self, stream):
        self.stream = stream
        self.buffer = ""
        self.stream_is_buffered = False

    def read(self, record_separator):
        """The next record, or None at the end of the stream."""
        if record_separator == "\n" and not self.buffer:
            line = self.stream.readline()
            if not line:
                return None
            return line[:-1] if line.endswith("\n") else line
        if not self.stream_is_buffered:
            self.buffer += self.stream.read()
            self.stream_is_buffered = True
        if record_separator == "":
            return self._read_paragraph()
        return self._read_up_to_separator(record_separator)

    def _read_paragraph(self):
        """`RS = ""`: records are blocks of lines separated by blank lines."""
        text = self.buffer.lstrip("\n")
        if not text:
            self.buffer = ""
            return None
        blank_lines = re.search(r"\n\n+", text)
        if blank_lines:
            self.buffer = text[blank_lines.end():]
            return text[:blank_lines.start()]
        self.buffer = ""
        return text.rstrip("\n")

    def _read_up_to_separator(self, record_separator):
        """A one-character separator is literal, a longer one is a regex."""
        text = self.buffer
        if text == "":
            return None
        if len(record_separator) == 1:
            separator_start, separator_length = text.find(record_separator), 1
        else:
            non_empty_match = next((match for match in regex(record_separator).finditer(text)
                                    if match.end() > match.start()), None)
            if non_empty_match:
                separator_start = non_empty_match.start()
                separator_length = non_empty_match.end() - non_empty_match.start()
            else:
                separator_start, separator_length = -1, 0
        if separator_start < 0:
            self.buffer = ""
            return text
        self.buffer = text[separator_start + separator_length:]
        return text[:separator_start]


class Record:
    """The current record: the `F` object.  `F[0]` is `$0`, `F[1]` is `$1`, ...

    `NF` is an ordinary variable in the program's namespace, so the user
    can write `NF = 2` and expect the record to shrink.  The record
    cannot know the moment that happens, so every access first calls
    :meth:`apply_nf_assignment`, which compares `NF` with the real number
    of fields and resizes the record if they differ.  This is the one place
    where the variable and the object are reconciled.
    """

    def __init__(self, namespace: Namespace):
        self.namespace = namespace
        self.text = ""
        self.fields = []

    def set_text(self, text):
        """Make ``text`` the current record and split it with the current `FS`."""
        self.text = text
        in_paragraph_mode = self.namespace.text("RS") == ""
        self.fields = [Field(piece) for piece in
                       split_text(text, self.namespace.text("FS"), in_paragraph_mode)]
        self.namespace["NF"] = len(self.fields)

    def apply_nf_assignment(self):
        """Resize the record if the user's code assigned a new value to `NF`."""
        wanted_count = int(to_num(self.namespace["NF"]))
        self.namespace["NF"] = wanted_count
        if wanted_count != len(self.fields):
            self._resize_to(wanted_count)

    def _check_field_count(self, count):
        if count < 0:
            raise PawkError("NF cannot be negative: %d" % count)
        if count > MAX_FIELDS:
            raise PawkError("too many fields: %d (limit %d)" % (count, MAX_FIELDS))

    def _resize_to(self, count):
        self._check_field_count(count)
        del self.fields[count:]
        self.fields.extend(Field("") for _ in range(count - len(self.fields)))
        self._rebuild_text_from_fields()

    def _rebuild_text_from_fields(self):
        """Recompute `$0` from the fields, joined with `OFS`."""
        self.text = self.namespace.text("OFS").join(self.fields)
        self.namespace["NF"] = len(self.fields)

    def _field_number(self, index):
        self.apply_nf_assignment()
        number = int(to_num(index))
        if number < 0:
            raise PawkError("attempt to access field %d" % number)
        return number

    def __getitem__(self, index):
        number = self._field_number(index)
        if number == 0:
            return Field(self.text)
        return self.fields[number - 1] if number <= len(self.fields) else Field("")

    def __setitem__(self, index, value):
        number = self._field_number(index)
        value = to_str(value, self.namespace.text("OFMT"))
        if number == 0:
            self.set_text(value)
            return
        self._check_field_count(number)
        self.fields.extend(Field("") for _ in range(number - len(self.fields)))
        self.fields[number - 1] = Field(value)
        self._rebuild_text_from_fields()

    def __len__(self):
        self.apply_nf_assignment()
        return len(self.fields)

    def __iter__(self):
        self.apply_nf_assignment()
        return iter(list(self.fields))

    def __str__(self):
        self.apply_nf_assignment()
        return self.text
