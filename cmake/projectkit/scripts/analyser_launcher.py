#!/usr/bin/env python3
"""Launcher used as CXX_CLANG_TIDY / CXX_CPPCHECK: analyser findings land in a
per-source report and on the console.

  analyser_launcher.py <report-dir> <analyser> [analyser args...]

CMake appends the source file and the compile command (the arguments are not
known here); everything after <report-dir> is executed unchanged.
"""

import os
import shutil
import subprocess
import sys
import zlib

SOURCES = (".c", ".cc", ".cpp", ".cxx", ".C")


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("analyser_launcher.py: usage: analyser_launcher.py <report-dir> <analyser> [args...]\n")
        return 2
    report_dir, command = argv[0], argv[1:]
    try:
        os.makedirs(report_dir, exist_ok=True)
    except OSError as error:
        sys.stderr.write(f"analyser_launcher.py: {report_dir}: {error.strerror}\n")
        return 1

    source = previous = ""
    for argument in command:
        if argument == "--":
            source = previous
        elif argument.endswith(SOURCES) and not source:
            source = argument
        previous = argument

    if source:
        tag = zlib.crc32(source.encode("utf-8"))
        report = os.path.join(report_dir, f"{os.path.basename(source)}.{tag}.log")
    else:
        report = os.path.join(report_dir, f"unknown-source.{os.getpid()}.log")

    try:
        result = subprocess.run([shutil.which(command[0]) or command[0], *command[1:]],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as error:
        sys.stderr.write(f"analyser_launcher.py: {command[0]}: {error.strerror}\n")
        return 127

    sys.stdout.buffer.write(result.stdout)
    sys.stdout.flush()
    if result.stdout:
        header = (f"command: {' '.join(command)}\nsource:  {source or 'unknown'}\n"
                  f"status:  {result.returncode}\n\n").encode("utf-8")
        with open(report, "wb") as file:
            file.write(header + result.stdout)
    elif os.path.exists(report):
        os.remove(report)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
