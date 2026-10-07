"""Master verification entry point.

The -possible commands widen what is listed and queued, never what is built:
every target still re-checks its environment strictly before compiling, so a
CLANG64 target queued from a UCRT64 shell stops at the environment stage and
won't attempt to build against the wrong toolchain.

Each target gets its own Verify object, so its configuration and its pass/fail
counters cannot overwrite each other.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

from . import targets
from .common import (BUILD_TYPES, C, entry, err, has_file, host_arch, host_platform, load_conf, out,
                     repo_root, run, setup_output)
from .verify_base import Verify

USAGE = """\
usage: {self} [command] [flag...] [target...]

commands:
  list              list targets that can run in this shell right now
  list-possible     list targets this machine could host, ignoring which MSYS2
                    environment is active and which toolchains are installed
  run               verify targets that can run right now (default)
  run-possible      queue every target this machine could host; each still
                    refuses to build unless its environment is actually active
  clean             remove generated output only, verify nothing
  help              show this message

flags for commands 'run' and 'run-possible':
  --native          only native targets
  --cross           only cross targets
  --all             both (the default)
  --keep            leave generated output in place
  --build_type=T    build type(s) to verify, separated by ',' or ';'
                    (default: Debug,Release). Every build stage runs once per
                    type and nothing is built in a type not listed. Quote a
                    ';' list, the shell treats a bare ';' as a command end.
                    Valid: Debug, Release, RelWithDebInfo, MinSizeRel

  Naming one or more targets selects exactly those, ignoring the filters
  above and running them even when unavailable.

examples:
  {self} list
  {self} run
  {self} run --cross
  {self} run --build_type=Debug
  {self} run --build_type='Debug;RelWithDebInfo'
  {self} run-possible
  {self} run windows-ucrt64 cross-x86_64-mingw-w64"""

SELF = "./scripts/verify.py"


def usage(write: Callable[[str], None] = out) -> None:
    write(USAGE.format(self=SELF))


def list_targets(root: str, mode: str, write: Callable[[str], None] = out) -> None:
    host = f"host: {host_platform()} {host_arch()}"
    if os.environ.get("MSYSTEM"):
        host += f" (MSYSTEM={os.environ['MSYSTEM']})"
    write(host)
    write(f"mode: {mode}\n")
    write(f"{'TARGET':<30} {'KIND':<7} {'RUN':<4} NOTE")
    for name, kind, *_rest, description in targets.RECORDS:
        passed, reason = targets.availability(name, root, mode) or (False, "")
        write(f"{name:<30} {kind:<7} {'yes' if passed else 'no':<4} {description if passed else reason}")


def parse_build_types(value: str) -> List[str]:
    types = value.replace(";", " ").replace(",", " ").split()
    for build_type in types:
        if build_type not in BUILD_TYPES:
            err(f"invalid build type: '{build_type}'")
            err("expected Debug, Release, RelWithDebInfo or MinSizeRel")
            raise SystemExit(2)
    if not types:
        err("empty value for --build_type")
        raise SystemExit(2)
    return types


def main(argv: List[str], root: Optional[str] = None) -> int:
    return entry(_main, argv, root)


def _main(argv: List[str], given_root: Optional[str]) -> int:
    root = repo_root(given_root, has_file("CMakeLists.txt"),
                     "no CMakeLists.txt found above {cwd}: set PK_REPO_ROOT")
    setup_output()
    conf = load_conf(root, "scripts/helpers/verify/verify.conf")
    base = Verify(root, conf)

    command = argv[0] if argv else "run"
    args = argv[1:]
    write_err: Callable[[str], None] = err

    if command in ("list", "list-possible"):
        list_targets(root, "strict" if command == "list" else "possible")
        return 0
    if command == "clean":
        base.cleanup()
        out("cleaned.")
        return 0
    if command in ("help", "--help", "-h"):
        usage()
        return 0
    if command not in ("run", "run-possible"):
        err(f"unknown command: {command}\n")
        usage(write_err)
        return 2
    mode = "strict" if command == "run" else "possible"

    kind_filter = ""
    keep = False
    named: List[str] = []
    build_types = ["Debug", "Release"]

    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in ("--native", "--cross", "--all"):
            if kind_filter:
                err("only one of --native, --cross, --all may be given")
                return 2
            kind_filter = "any" if arg == "--all" else arg[2:]
        elif arg == "--keep":
            keep = True
        elif arg in ("--help", "-h"):
            usage()
            return 0
        elif arg == "--build_type":
            if index >= len(args):
                err("missing value for --build_type\n")
                usage(write_err)
                return 2
            build_types = parse_build_types(args[index])
            index += 1
        elif arg.startswith("--build_type="):
            build_types = parse_build_types(arg.split("=", 1)[1])
        elif arg.startswith("-"):
            err(f"unknown option: {arg}\n")
            usage(write_err)
            return 2
        else:
            result = targets.availability(arg, root, mode)
            if result is None:
                err(f"unknown target: {arg}\n")
                list_targets(root, "possible", write_err)
                return 2
            if not result[0]:
                err(f"warning: {arg} is not available here: {result[1]} -- only use if absolutely necessary")
                err("running it anyway because it was named explicitly.\n")
            named.append(arg)

    kind_filter = kind_filter or "any"
    if named:
        selected = named
    else:
        selected = [r[0] for r in targets.RECORDS
                    if (kind_filter == "any" or r[1] == kind_filter) and targets.runnable(r[0], root, mode)]

    if not selected:
        err(f"no targets selected (host {host_platform()} {host_arch()}, mode {mode}, filter {kind_filter}).\n")
        list_targets(root, mode, write_err)
        err(f"\nTry: {SELF} run-possible")
        return 2

    out(f"{C.bold}======== {base.project} verification ========{C.reset}")
    out(f"host:    {host_platform()} {host_arch()}")
    out(f"command: {command}")
    out(f"types:   {' '.join(build_types)}")
    out("targets:")
    for target in selected:
        out(f"  - {target}")

    results: List[Tuple[str, str, str]] = []
    any_failed = False
    for target in selected:
        out(f"\n{C.bold}================ {target} [{' '.join(build_types)}] ================{C.reset}")
        verify = Verify(root, conf)
        verify.keep = keep
        verify.build_types = build_types
        passed = verify.apply_target(target) and verify.run_stages()
        results.extend(verify.results)
        if not passed:
            any_failed = True
            if not any(row[0] == target for row in verify.results):
                results.append((target, "-", "failed before any stage ran"))

    out(f"\n{C.bold}======== Overall ========{C.reset}")
    out(f"{'TARGET':<30} {'BUILD TYPE':<16} RESULT")
    for target, build_type, result in results:
        color = C.green if result == "passed" else C.yellow if result == "not run" else C.red
        out(f"{target:<30} {build_type:<16} {color}{result}{C.reset}")

    out("\nTracked-file changes still present (should be only your own edits):")
    run(["git", "-C", root, "status", "--short"])
    out("\nUntracked files git clean -fd WOULD remove (nothing deleted yet):")
    run(["git", "-C", root, "clean", "-nd"])
    return 1 if any_failed else 0
