"""Command line front end: ``pawk-ng [-F fs] [-v var=val] [-f file] 'prog' [file ...]``."""
import argparse
import io
import sys

from . import __version__
from .parser import ProgramError
from .runtime import PawkError, Runtime


def build_parser():
    p = argparse.ArgumentParser(
        prog="pawk-ng", description="awk-style stream editor with Python actions.")
    p.add_argument("-F", dest="fs", metavar="FS", help="field separator")
    p.add_argument("-v", dest="assigns", action="append", default=[],
                   metavar="VAR=VALUE", help="assign a variable before BEGIN")
    p.add_argument("-f", dest="progfiles", action="append", default=[],
                   metavar="FILE", help="read the program from FILE")
    p.add_argument("-m", dest="modules", action="append", default=[],
                   metavar="MODULE", help="'from MODULE import *' into the program")
    p.add_argument("--version", action="version", version="pawk-ng " + __version__)
    p.add_argument("operands", nargs="*", help="program text, then files/var=value")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    operands = list(args.operands)
    if args.progfiles:
        try:
            program = "\n".join(open(f, encoding="utf-8").read() for f in args.progfiles)
        except OSError as e:
            sys.stderr.write("pawk-ng: cannot read %s\n" % e.filename)
            return 2
    elif operands:
        program = operands.pop(0)
    else:
        sys.stderr.write("pawk-ng: no program given\n")
        return 2
    enc = dict(encoding="utf-8", errors="surrogateescape", newline="\n")
    stdin = io.TextIOWrapper(sys.stdin.buffer, **enc)
    stdout = io.TextIOWrapper(sys.stdout.buffer, write_through=False, **enc)
    try:
        for a in args.assigns:
            if "=" not in a:
                sys.stderr.write("pawk-ng: -v needs var=value, got %r\n" % a)
                return 2
        rt = Runtime(program, operands, fs=args.fs, assigns=args.assigns,
                     modules=args.modules, stdin=stdin, stdout=stdout)
        return rt.run()
    except ProgramError as e:
        sys.stderr.write("pawk-ng: syntax error: %s\n" % e)
        return 2
    except PawkError as e:
        sys.stderr.write("pawk-ng: error: %s\n" % e)
        return 2
    except BrokenPipeError:
        return 0
    finally:
        try:
            stdout.flush()
        except BrokenPipeError:
            pass


if __name__ == "__main__":
    sys.exit(main())
