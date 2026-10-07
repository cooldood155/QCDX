"""ProjectKit package lifecycle: one entry point for the Conan 2 operations
needed, with the recipe as the source for name and version. Anything after
'--' is handed to conan unchanged."""

from __future__ import annotations

import json
import os
import shutil
from typing import Dict, List, Optional

from .common import (BUILD_TYPES, SCRIPTS_DIR, C, capture, confirm, entry, err, load_conf, native_path, out,
                     repo_root, run, setup_output, shown)

USAGE = """\
usage: {self} <command> [flag...] [-- conan args...]

commands:
  reference       print the name/version the recipe reports
  install         conan install, what the CMake presets consume
  create          conan create: build, package and run the test package
  build           conan build in the local folder
  export          export the recipe only, no build
  export-pkg      package an already built local tree
  list            list this package in the cache, or in --remote
  info            dependency graph for this recipe
  path            cache folder of the packaged binary
  editable        add | remove | list
  remove          delete this package from the cache, or from --remote
  upload          upload this package to --remote
  cache-clean     drop build and source folders of this package
  help            show this message

flags:
  --build_type=T[,T]  build type(s), default {types}
  --profile=NAME      build profile, a file under profiles/ or a named profile
  --host-profile=NAME host profile for cross packaging
  --remote=NAME       remote for list, remove and upload
  --version=X         override the version the recipe reports
  --test-folder=DIR   test package folder, "" disables the test stage
  --yes               do not ask before deleting
  --dry-run           print the conan commands without running them"""


class Package:
    def __init__(self, root: str) -> None:
        conf = load_conf(root, "scripts/helpers/package/package.conf")
        self.root = root
        self.profile = conf.get("PK_PROFILE")
        self.host_profile = conf.get("PK_HOST_PROFILE")
        self.remote = conf.get("PK_REMOTE")
        self.build_types = conf.get("PK_BUILD_TYPES", "Release").split()
        self.test_folder_conf = conf.get("PK_TEST_FOLDER")
        self.test_source = conf.get("PK_TEST_SOURCE")
        self.conan = conf.get("PK_CONAN", "conan")
        self.test_build_dir = conf.get("PK_TEST_BUILD_DIR", os.path.join(root, "build", "test_package"))
        self.version_override = ""
        self.test_folder: Optional[str] = None
        self.assume_yes = False
        self.dry_run = False
        self._recipe: Optional[Dict[str, object]] = None

    def die(self, message: str) -> None:
        err(f"{C.red}error{C.reset}  {message}")
        raise SystemExit(1)

    def note(self, message: str) -> None:
        out(f"{C.bold}--{C.reset} {message}")

    def run(self, argv: List[str]) -> int:
        out(f"{C.yellow}+{C.reset} {shown(argv)}")
        return 0 if self.dry_run else run(argv)

    def profile_path(self, name: str) -> str:
        native = os.path.join(self.root, "profiles", "native")
        if not name:
            return native if os.path.isfile(native) else "default"
        if os.path.isfile(name):
            return name
        candidate = os.path.join(self.root, "profiles", name)
        return candidate if os.path.isfile(candidate) else name

    def recipe_field(self, field: str) -> str:
        if self._recipe is None:
            code, text = capture([self.conan, "inspect", self.root, "--format=json"])
            try:
                data = json.loads(text) if code == 0 else {}
            except ValueError:
                data = {}
            self._recipe = data if isinstance(data, dict) else {}
        value = self._recipe.get(field)
        return value if isinstance(value, str) else ""

    def reference(self) -> str:
        name = self.recipe_field("name")
        if not name:
            self.die(f"the recipe in {self.root} reports no name")
        version = self.version_override or self.recipe_field("version")
        if not version:
            self.die(f"the recipe in {self.root} reports no version")
        return f"{name}/{version}"

    def test_folder_args(self) -> List[str]:
        if self.test_folder is not None:
            return [f"-tf={self.test_folder}"]
        if self.test_folder_conf:
            return [f"-tf={self.test_folder_conf}"]
        if os.path.isdir(os.path.join(self.root, "test_package")):
            return []
        kit_test = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "test_package"))
        return [f"-tf={kit_test}"] if os.path.isdir(kit_test) else []


def main(argv: List[str], root: Optional[str] = None) -> int:
    return entry(_main, argv, root)


def _main(argv: List[str], given_root: Optional[str]) -> int:
    root = repo_root(given_root, lambda d: os.path.isfile(os.path.join(d, "conanfile.py"))
                     or os.path.isfile(os.path.join(d, "conanfile.txt")),
                     "no conanfile.py found above {cwd}: set PK_REPO_ROOT")
    setup_output()
    pk = Package(root)
    self_name = "./scripts/package.py"

    def usage(write=out) -> None:
        write(USAGE.format(self=self_name, types=",".join(pk.build_types)))

    command = argv[0] if argv else "help"
    args = argv[1:]

    build_types_arg = ""
    profile_arg = ""
    host_profile_arg = ""
    subcommand = ""
    extra: List[str] = []

    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        key, sep, value = arg.partition("=")
        if sep and key == "--build_type":
            build_types_arg = value
        elif sep and key == "--profile":
            profile_arg = value
        elif sep and key == "--host-profile":
            host_profile_arg = value
        elif sep and key == "--remote":
            pk.remote = value
        elif sep and key == "--version":
            pk.version_override = value
        elif sep and key == "--test-folder":
            pk.test_folder = value
        elif arg in ("--yes", "-y"):
            pk.assume_yes = True
        elif arg == "--dry-run":
            pk.dry_run = True
        elif arg in ("--help", "-h"):
            usage()
            return 0
        elif arg == "--":
            extra = args[index:]
            break
        elif arg.startswith("-"):
            err(f"unknown option: {arg}\n")
            usage(err)
            return 2
        elif not subcommand:
            subcommand = arg
        else:
            err(f"unexpected argument: {arg}\n")
            usage(err)
            return 2

    if command in ("help", "--help", "-h"):
        usage()
        return 0

    if build_types_arg:
        pk.build_types = build_types_arg.replace(";", " ").replace(",", " ").split()
    for build_type in pk.build_types:
        if build_type not in BUILD_TYPES:
            pk.die(f"invalid build type: '{build_type}'")

    if not shutil.which(pk.conan):
        pk.die("conan is not on PATH")

    build_profile = pk.profile_path(profile_arg or pk.profile)
    if host_profile_arg or pk.host_profile:
        profiles = ["-pr:b", build_profile, "-pr:h", pk.profile_path(host_profile_arg or pk.host_profile)]
    else:
        profiles = ["-pr:a", build_profile]
    remote_args = ["-r", pk.remote] if pk.remote else []
    version_args = ["--version", pk.version_override] if pk.version_override else []
    if pk.test_source:
        os.environ["PK_TEST_SOURCE"] = pk.test_source

    conan = pk.conan
    status = 0

    def each_type(action: str, base: List[str], extra_args: List[str], with_build: bool = True) -> None:
        nonlocal status
        for build_type in pk.build_types:
            pk.note(f"{action} {build_type}")
            argv = [conan, *base, pk.root, *profiles, "-s", f"build_type={build_type}"]
            if with_build:
                argv.append("--build=missing")
            if pk.run(argv + extra_args + extra):
                status = 1

    if command == "reference":
        out(pk.reference())
    elif command == "install":
        each_type("install", ["install"], [])
    elif command == "create":
        test_args = pk.test_folder_args()
        test_conf = f"tools.cmake.cmake_layout:test_folder={native_path(pk.test_build_dir)}"
        for build_type in pk.build_types:
            pk.note(f"create {pk.reference()} {build_type}")
            if pk.run([conan, "create", pk.root, *profiles, "-s", f"build_type={build_type}",
                       "--build=missing", "-c", test_conf, *version_args, *test_args, *extra]):
                status = 1
    elif command == "build":
        each_type("build", ["build"], [])
    elif command == "export":
        status = 1 if pk.run([conan, "export", pk.root, *version_args, *extra]) else 0
    elif command == "export-pkg":
        each_type("export-pkg", ["export-pkg"], version_args, with_build=False)
    elif command == "list":
        status = 1 if pk.run([conan, "list", f"{pk.reference()}:*", *remote_args, *extra]) else 0
    elif command == "info":
        status = 1 if pk.run([conan, "graph", "info", pk.root, *profiles, "-s",
                              f"build_type={pk.build_types[0]}", *extra]) else 0
    elif command == "path":
        status = 1 if pk.run([conan, "cache", "path", pk.reference(), *extra]) else 0
    elif command == "editable":
        action = subcommand or "list"
        if action == "add":
            argv = [conan, "editable", "add", pk.root, *version_args, *extra]
        elif action == "remove":
            argv = [conan, "editable", "remove", pk.root, *extra]
        elif action == "list":
            argv = [conan, "editable", "list", *extra]
        else:
            pk.die(f"editable takes add, remove or list, not '{subcommand}'")
            return 1
        status = 1 if pk.run(argv) else 0
    elif command == "remove":
        reference = pk.reference()
        target = f"{reference} (remote {pk.remote})" if pk.remote else reference
        if pk.assume_yes or confirm(f"remove {target} from the cache?"):
            status = 1 if pk.run([conan, "remove", reference, "-c", *remote_args, *extra]) else 0
        else:
            pk.note("nothing removed")
    elif command == "upload":
        if not pk.remote:
            pk.die("upload needs --remote=NAME or PK_REMOTE")
        status = 1 if pk.run([conan, "upload", pk.reference(), "-r", pk.remote, "--confirm", *extra]) else 0
    elif command == "cache-clean":
        status = 1 if pk.run([conan, "cache", "clean", pk.reference(), *extra]) else 0
    else:
        err(f"unknown command: {command}\n")
        usage(err)
        return 2

    out(f"{C.green}ok{C.reset}" if status == 0 else f"{C.red}failed{C.reset}")
    return status
