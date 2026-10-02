#!/usr/bin/env python3
"""pk dep: manage deps.json, conan.lock and dependency reports.

'deps.json' and 'manifest' are used interchangeably; most anything interacting
with deps.json will contain "manifest" in its identity.

deps.json is the source for third-party packages: conanfile.py reads it to know
what to install, projectkit's CMake reads it to know what to find and link, and
this tool is how it gets edited (CRUD+ operations). Every change is
transactional: deps.json and conan.lock are restored if any step fails, always
leaving you with a clean tree!

Run 'pk dep help' for the commands.
Documentation: cmake/projectkit/docs/PK_DEP.md

Standard library only, Python 3.8+ because Conan already guarantees Python.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

SCHEMA = 1
KINDS = ("requires", "test", "tool")
TRAITS = ("headers", "libs", "run", "visible", "transitive_headers",
          "transitive_libs", "force", "override")
ENTRY_KEYS = ("ref", "kind", "options", "traits", "cmake", "notes")
CMAKE_KEYS = ("package", "version", "components", "targets", "extra_targets")
NAME_RE = re.compile(r"^[a-z0-9_][a-z0-9_.+-]*$")
REF_RE = re.compile(r"^([a-z0-9_][a-z0-9_.+-]*)/(\S(?:.*\S)?)$")
LOCK_REF_RE = re.compile(r"^([^/]+)/([^#@%]+)")

SCAN_SKIP_DIRS = {".git", "build", "stage", "_install", "node_modules",
                  ".cache", "out"}
SCAN_COMMANDS = {
    "pk_create_library": "LIBRARY",
    "pk_create_app": "APPLICATION",
    "pk_create_test": "TEST",
    "pk_deps_find": "FIND",
    "pk_deps_link": "LINK",
}
DEPS_KEYWORDS = {"DEPS", "DEPS_PUBLIC", "DEPS_PRIVATE", "DEPS_INTERFACE",
                 "PUBLIC", "PRIVATE", "INTERFACE"}

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code, text):
    return "\033[{}m{}\033[0m".format(code, text) if _COLOR else text


def step(text):
    print("\n{} {}".format(_c("32", "==>"), _c("1", text)))


def info(text):
    print(_c("2", "  " + text))


def warn(text):
    print("{} {}".format(_c("33", "warning:"), text), file=sys.stderr)


class PkDepError(Exception):
    """A failure the user can act on; printed without a traceback."""


def show_command(cmd):
    print("{} {}".format(_c("33", "+"), " ".join(shlex.quote(a) for a in cmd)))


# -----------------------------------------------------------------------------
# Repository & manifest & lockfile
# -----------------------------------------------------------------------------


def version_key(text):
    """Sort key for versions: numeric parts compare as numbers (2.10 > 2.9)."""
    parts = re.split(r"[.+-]", text.split(" ", 1)[0])
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts]


def find_root():
    root = os.environ.get("PK_REPO_ROOT")
    if root:
        return os.path.abspath(root)

    here = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(here, "conanfile.py")) and \
           os.path.isfile(os.path.join(here, "CMakeLists.txt")):
            return here

        parent = os.path.dirname(here)
        if parent == here:
            raise PkDepError("no conanfile.py + CMakeLists.txt above {}; set "
                             "PK_REPO_ROOT".format(os.getcwd()))
        here = parent


def _dump_json(value, indent=0):
    """json.dumps using short scalar arrays all on one line (ASCII only)."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"

        items = ["{}  {}: {}".format(pad, json.dumps(k), _dump_json(v, indent + 1))
                 for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"

    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            return "[" + ", ".join(json.dumps(v) for v in value) + "]"

        items = ["{}  {}".format(pad, _dump_json(v, indent + 1)) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return json.dumps(value)


def write_atomic(path, text):
    tmp = path + ".pk-tmp"
    with open(tmp, "w", encoding="ascii", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


class Repo:
    def __init__(self, root, profiles, dry_run):
        self.root = root
        self.manifest_path = os.path.join(root, "deps.json")
        self.lock_path = os.path.join(root, "conan.lock")
        self.dry_run = dry_run
        self.conan = os.environ.get("PK_CONAN", "conan")
        self.native = os.environ.get("PK_NATIVE_PROFILE", "native")
        self.profiles = profiles or [self.native]
        self.scratch = os.path.join(root, "build", ".pk-dep")

    #-{ manifest }-------------------------------------------------------------

    def load_manifest(self, required=True):
        if not os.path.isfile(self.manifest_path):
            if required:
                raise PkDepError("no deps.json in {}; 'pk dep add <ref>' creates "
                                 "one".format(self.root))
            return {"schema": SCHEMA, "packages": {}}

        with open(self.manifest_path, encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except ValueError as exc:
                raise PkDepError("deps.json is not valid JSON: {}".format(exc))

        errors = validate_manifest(data)
        if errors:
            raise PkDepError("deps.json is invalid:\n  " + "\n  ".join(errors))
        return data

    def save_manifest(self, data):
        errors = validate_manifest(data)
        if errors:
            raise PkDepError("refusing to write an invalid deps.json:\n  " +
                             "\n  ".join(errors))

        packages = data["packages"]
        ordered = {}
        for name in sorted(packages):
            entry = packages[name]
            clean = {k: entry[k] for k in ENTRY_KEYS if k in entry}
            if isinstance(clean.get("cmake"), dict):
                clean["cmake"] = {k: clean["cmake"][k] for k in CMAKE_KEYS
                                  if k in clean["cmake"]}
            ordered[name] = clean

        text = _dump_json({"schema": SCHEMA, "packages": ordered}) + "\n"
        if self.dry_run:
            info("would write deps.json:")
            for line in text.splitlines():
                info("  " + line)
            return
        write_atomic(self.manifest_path, text)

    #-{ lockfile }-------------------------------------------------------------

    def load_lock(self):
        if not os.path.isfile(self.lock_path):
            return None
        with open(self.lock_path, encoding="utf-8") as handle:
            return json.load(handle)

    def locked_versions(self, revisions=False):
        """{name: sorted versions} across every lockfile section; if
        revisions=True each entry is then 'version (rev abcdef1)'."""
        lock = self.load_lock()
        found = {}
        if not lock:
            return found

        for section in ("requires", "build_requires", "python_requires"):
            for ref in lock.get(section, []):
                match = LOCK_REF_RE.match(ref)
                if not match:
                    continue

                value = match.group(2)
                if revisions and "#" in ref:
                    value += " (rev {})".format(ref.split("#", 1)[1].split("%", 1)[0][:7])
                found.setdefault(match.group(1), set()).add(value)
        return {k: sorted(v, key=version_key) for k, v in found.items()}

    def locked_refs(self, name):
        """Full lockfile entries for one package, with their section."""
        lock = self.load_lock() or {}
        refs = []
        for section in ("requires", "build_requires"):
            for ref in lock.get(section, []):
                match = LOCK_REF_RE.match(ref)
                if match and match.group(1) == name:
                    refs.append((section, ref.split("%", 1)[0]))
        return refs

    #-{ conan }----------------------------------------------------------------

    def profile_args(self, profile):
        def resolve(name):
            candidate = os.path.join("profiles", name)
            if os.path.isfile(os.path.join(self.root, candidate)):
                return candidate
            return name

        if profile == self.native:
            return ["-pr:a", resolve(profile)]
        return ["-pr:b", resolve(self.native), "-pr:h", resolve(profile)]

    def _exec(self, args, capture, check, quiet):
        cmd = [self.conan] + args
        if not quiet:
            show_command(cmd)

        try:
            proc = subprocess.run(cmd, cwd=self.root, universal_newlines=True,
                                  stdout=subprocess.PIPE if capture else None,
                                  stderr=subprocess.PIPE if capture else None)
        except OSError as exc:
            raise PkDepError("could not run {}: {}".format(self.conan, exc))

        if check and proc.returncode != 0:
            detail = ""
            if capture and proc.stderr:
                detail = "\n" + "\n".join(proc.stderr.strip().splitlines()[-15:])
            raise PkDepError("'{} {}' failed{}".format(self.conan, args[0], detail))
        return proc

    def run(self, args, check=True, quiet=False):
        """Conan command run for its side effects; --dry-run only prints it."""
        if self.dry_run:
            if not quiet:
                show_command([self.conan] + args)
            return
        self._exec(args, False, check, quiet)

    def capture(self, args, check=True, quiet=False):
        """Conan command run for its output, even under --dry-run."""
        return self._exec(args, True, check, quiet)

    def lock_create(self, update=False, clean=False):
        """Create or extend conan.lock; already-locked packages keep their pins.
        One lock covers all profiles via their graph."""
        for index, profile in enumerate(self.profiles):
            args = ["lock", "create", "."] + self.profile_args(profile)
            args += ["-c", "tools.graph:skip_test=False"]
            if index > 0 or os.path.isfile(self.lock_path):
                args += ["--lockfile=conan.lock", "--lockfile-partial"]
            else:
                args += ["--lockfile="]

            args += ["--lockfile-out=conan.lock"]
            if update:
                args.append("--update")

            # Only the first pass cleans; one profile cleaning would drop
            # entries that only another profile needs.
            if clean and index == 0:
                args.append("--lockfile-clean")
            self.run(args)

    def lock_remove(self, names):
        if not os.path.isfile(self.lock_path) or not names:
            return

        args = ["lock", "remove", "--lockfile=conan.lock", "--lockfile-out=conan.lock"]
        for name in names:
            args += ["--requires=" + name + "/*", "--build-requires=" + name + "/*"]
        self.run(args)

    def graph(self, profile=None):
        """Conan's dependency graph for the project, cached per input state."""
        profile = profile or self.profiles[0]
        digest = hashlib.sha1()

        for rel in ("conanfile.py", "deps.json", "conan.lock",
                    os.path.join("profiles", self.native),
                    os.path.join("profiles", profile)):
            path = os.path.join(self.root, rel)
            if os.path.isfile(path):
                with open(path, "rb") as handle:
                    digest.update(handle.read())

        digest.update(profile.encode())
        cache = os.path.join(self.scratch, "graph-{}.json".format(digest.hexdigest()[:16]))
        if os.path.isfile(cache):
            with open(cache, encoding="utf-8") as handle:
                return json.load(handle)

        args = ["graph", "info", "."] + self.profile_args(profile)
        args += ["-c", "tools.graph:skip_test=False", "--format=json"]
        info("reading the Conan graph ({})".format(profile))
        proc = self.capture(args, quiet=True)
        data = json.loads(proc.stdout)
        os.makedirs(self.scratch, exist_ok=True)

        for old in os.listdir(self.scratch):
            if old.startswith("graph-"):
                os.remove(os.path.join(self.scratch, old))

        with open(cache, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return data


class Transaction:
    """Restores deps.json and conan.lock if the block does not complete."""

    def __init__(self, repo):
        self.repo = repo
        self.saved = {}

    def __enter__(self):
        for path in (self.repo.manifest_path, self.repo.lock_path):
            if os.path.isfile(path):
                with open(path, "rb") as handle:
                    self.saved[path] = handle.read()
            else:
                self.saved[path] = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None or self.repo.dry_run:
            return False

        for path, content in self.saved.items():
            if content is None:
                if os.path.isfile(path):
                    os.remove(path)
            else:
                with open(path, "wb") as handle:
                    handle.write(content)
        warn("rolled back deps.json and conan.lock")
        return False


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def validate_manifest(data):
    errors = []
    if not isinstance(data, dict):
        return ["the top level must be an object"]

    if data.get("schema") != SCHEMA:
        errors.append("'schema' must be {}".format(SCHEMA))
    packages = data.get("packages")
    if not isinstance(packages, dict):
        return errors + ["'packages' must be an object"]

    owners = {}
    for name, entry in packages.items():
        where = "package '{}'".format(name)
        if not NAME_RE.match(name):
            errors.append("{}: names are lowercase Conan package names".format(where))
        if not isinstance(entry, dict):
            errors.append("{}: must be an object".format(where))
            continue

        for key in entry:
            if key not in ENTRY_KEYS:
                errors.append("{}: unknown key '{}' (known: {})".format(
                    where, key, ", ".join(ENTRY_KEYS)))

        ref = entry.get("ref")
        match = REF_RE.match(ref) if isinstance(ref, str) else None
        if not match or match.group(1) != name:
            errors.append("{}: 'ref' must look like '{}/<version-or-range>'".format(
                where, name))

        kind = entry.get("kind", "requires")
        if kind not in KINDS:
            errors.append("{}: 'kind' must be one of {}".format(where, ", ".join(KINDS)))

        options = entry.get("options", {})
        if not isinstance(options, dict) or any(
                isinstance(v, (dict, list)) for v in options.values()):
            errors.append("{}: 'options' must map names to plain values".format(where))

        traits = entry.get("traits", {})
        if not isinstance(traits, dict):
            errors.append("{}: 'traits' must be an object".format(where))
        else:
            for trait in traits:
                if trait not in TRAITS:
                    errors.append("{}: unknown trait '{}' (known: {})".format(
                        where, trait, ", ".join(TRAITS)))
            if traits and kind != "requires":
                errors.append("{}: traits only apply to kind 'requires'".format(where))

        cmake = entry.get("cmake", None)
        if kind == "tool":
            if cmake not in (None, False):
                errors.append("{}: tool packages have no 'cmake' section".format(where))
        elif cmake is None:
            errors.append("{}: needs 'cmake' (or \"cmake\": false); 'pk dep set {} "
                          "--discover' fills it".format(where, name))
        elif cmake is not False:
            if not isinstance(cmake, dict):
                errors.append("{}: 'cmake' must be an object or false".format(where))
                continue

            for key in cmake:
                if key not in CMAKE_KEYS:
                    errors.append("{}: unknown cmake key '{}'".format(where, key))

            if not isinstance(cmake.get("package"), str) or not cmake.get("package"):
                errors.append("{}: 'cmake.package' is required".format(where))
            if not _is_str_list(cmake.get("targets")) or not cmake.get("targets"):
                errors.append("{}: 'cmake.targets' must be a non-empty list".format(where))

            for key in ("components", "extra_targets"):
                if key in cmake and not _is_str_list(cmake[key]):
                    errors.append("{}: 'cmake.{}' must be a list of strings".format(
                        where, key))

            if "version" in cmake and not isinstance(cmake["version"], str):
                errors.append("{}: 'cmake.version' must be a string".format(where))

            for target in list(cmake.get("targets") or []) + list(cmake.get("extra_targets") or []):
                if not isinstance(target, str):
                    continue
                if target in owners and owners[target] != name:
                    errors.append("{}: target '{}' is also claimed by '{}'".format(
                        where, target, owners[target]))
                owners[target] = name

        if "notes" in entry and not isinstance(entry["notes"], str):
            errors.append("{}: 'notes' must be a string".format(where))
    return errors


def parse_value(text):
    """Option and trait values: true/false/numbers become JSON types."""
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"

    if re.match(r"^-?\d+$", text):
        return int(text)
    return text


def parse_pairs(pairs, what):
    result = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise PkDepError("{} '{}' must be key=value".format(what, pair))
        key, value = pair.split("=", 1)
        result[key.strip()] = parse_value(value.strip())
    return result


# -----------------------------------------------------------------------------
# CMake name discovery
# -----------------------------------------------------------------------------


def discover_cmake(repo, name, entry):
    """Installs one package the way the project would and reads back the
    generated CMakeDeps names, then confirms the files exist."""
    versions = repo.locked_versions().get(name)
    if not versions:
        raise PkDepError("'{}' is not in conan.lock, cannot discover it".format(name))

    ref = "{}/{}".format(name, versions[-1])
    out_dir = os.path.join(repo.scratch, "discover", name)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    rel_out = os.path.relpath(out_dir, repo.root)

    args = ["install", "--requires=" + ref] + repo.profile_args(repo.profiles[0])
    args += ["-g", "CMakeDeps", "--output-folder=" + rel_out, "--build=missing",
             "--lockfile=conan.lock", "--lockfile-partial", "--format=json"]
    for option, value in (entry.get("options") or {}).items():
        if isinstance(value, bool):
            value = "True" if value else "False"
        args += ["-o", "{}/*:{}={}".format(name, option, value)]

    step("discover CMake names for {} (builds the binary if it is missing)".format(ref))
    proc = repo.capture(args)
    graph = json.loads(proc.stdout)
    node = None
    for candidate in graph["graph"]["nodes"].values():
        match = LOCK_REF_RE.match(candidate.get("ref") or "")
        if match and match.group(1) == name:
            node = candidate
            break
    if node is None:
        raise PkDepError("conan install did not report '{}' in its graph".format(name))

    cpp_info = node.get("cpp_info") or {}
    root_props = (cpp_info.get("root") or {}).get("properties") or {}
    if root_props.get("cmake_find_mode") == "none":
        raise PkDepError("'{}' sets cmake_find_mode=none: it generates no CMake "
                         "config. Use --no-cmake, or --no-discover with explicit "
                         "--cmake-package/--target.".format(name))

    file_name = root_props.get("cmake_file_name") or name
    root_target = root_props.get("cmake_target_name") or "{}::{}".format(name, name)
    component_targets = []
    for comp_name, comp in cpp_info.items():
        if comp_name == "root" or not isinstance(comp, dict):
            continue
        props = comp.get("properties") or {}
        component_targets.append(props.get("cmake_target_name") or
                                 "{}::{}".format(name, comp_name))

    generated = ""
    for fname in os.listdir(out_dir):
        if fname.endswith(".cmake"):
            with open(os.path.join(out_dir, fname), encoding="utf-8", errors="replace") as handle:
                generated += handle.read()

    config_names = ("{}-config.cmake".format(file_name), "{}Config.cmake".format(file_name),
                    "{}-config.cmake".format(file_name.lower()),
                    "Find{}.cmake".format(file_name))
    if not any(os.path.isfile(os.path.join(out_dir, c)) for c in config_names):
        raise PkDepError("expected CMakeDeps to generate {}Config.cmake for '{}', "
                         "found none in {}".format(file_name, name, rel_out))

    for target in [root_target] + component_targets:
        if target not in generated:
            raise PkDepError("CMakeDeps output for '{}' never mentions target '{}'".format(
                name, target))

    cmake = {"package": file_name, "targets": [root_target]}
    extra = [t for t in component_targets if t != root_target]
    if extra:
        cmake["extra_targets"] = extra
    info("found find_package({}) providing {}".format(file_name, ", ".join([root_target] + extra)))
    return cmake


# -----------------------------------------------------------------------------
# Sources scan: discover which CMake calls use which manifest names
# -----------------------------------------------------------------------------


def _cmake_files(root):
    for here, dirs, files in os.walk(root):
        rel = os.path.relpath(here, root)
        dirs[:] = [d for d in dirs if d not in SCAN_SKIP_DIRS
                   and not d.startswith("cmake-build")
                   and os.path.join(rel, d).replace("\\", "/") not in ("cmake/projectkit", "./cmake/projectkit")]

        for fname in files:
            if fname == "CMakeLists.txt" or fname.endswith(".cmake"):
                yield os.path.join(here, fname)


def _cmake_calls(text):
    """Yields (command, line, [tokens]) for every command invoked."""
    i, line, n = 0, 1, len(text)
    while i < n:
        ch = text[i]
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            continue

        match = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*\(").match(text, i)
        if not match or (i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")):
            i += 1
            continue

        command = match.group(0).split("(")[0].strip().lower()
        start_line = line
        i = match.end()
        depth, tokens, current = 1, [], ""
        while i < n and depth:
            ch = text[i]
            if ch == "\n":
                line += 1
            if ch == '"':
                j = i + 1
                while j < n and text[j] != '"':
                    if text[j] == "\\":
                        j += 1
                    if j < n and text[j] == "\n":
                        line += 1
                    j += 1
                current += text[i + 1:j]
                i = j + 1
                continue
            if ch == "#":
                while i < n and text[i] != "\n":
                    i += 1
                continue

            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break

            if ch.isspace() or ch in "()":
                if current:
                    tokens.append(current)
                    current = ""
            else:
                current += ch
            i += 1
        if current:
            tokens.append(current)
        i += 1
        yield command, start_line, tokens


def scan_sources(root):
    """[{file, line, command, role, keyword, name}] for every manifest-style use."""
    uses = []
    finds = []
    for path in _cmake_files(root):
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()

        rel = os.path.relpath(path, root).replace("\\", "/")
        for command, line, tokens in _cmake_calls(text):
            if command == "find_package" and tokens:
                finds.append({"file": rel, "line": line, "package": tokens[0]})

            role = SCAN_COMMANDS.get(command)
            if not role:
                continue
            if command == "pk_deps_find":
                for token in tokens:
                    uses.append({"file": rel, "line": line, "command": command,
                                 "role": role, "keyword": "", "name": token})
                continue

            if command == "pk_deps_link" and "ROLE" in tokens:
                at = tokens.index("ROLE")
                if at + 1 < len(tokens):
                    role = tokens[at + 1]

            keyword = None
            for token in tokens:
                if re.match(r"^[A-Z][A-Z0-9_]*$", token):
                    keyword = token if token in DEPS_KEYWORDS else None
                    if command != "pk_deps_link" and keyword in ("PUBLIC", "PRIVATE", "INTERFACE"):
                        keyword = None
                    continue
                if keyword:
                    uses.append({"file": rel, "line": line, "command": command,
                                 "role": role, "keyword": keyword, "name": token})
    return uses, finds


# -----------------------------------------------------------------------------
# Usage reports (written by configuration)
# -----------------------------------------------------------------------------


def load_usage(repo, tree=None):
    """Newest build/**/pk-deps-usage.json (or the one in --tree if given)."""
    candidates = []
    if tree:
        path = os.path.join(tree, "pk-deps-usage.json")
        if not os.path.isfile(path):
            raise PkDepError("no pk-deps-usage.json in {} (configure it first)".format(tree))
        candidates.append(path)
    else:
        build = os.path.join(repo.root, "build")
        for here, dirs, files in os.walk(build):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "CMakeFiles"]
            if "pk-deps-usage.json" in files:
                candidates.append(os.path.join(here, "pk-deps-usage.json"))

    if not candidates:
        return None, None
    path = max(candidates, key=os.path.getmtime)
    with open(path, encoding="utf-8") as handle:
        usage = json.load(handle)

    stamp = os.path.getmtime(path)
    newer = [rel for rel in ["deps.json"] if os.path.isfile(os.path.join(repo.root, rel))
             and os.path.getmtime(os.path.join(repo.root, rel)) > stamp]
    for cmake_file in _cmake_files(repo.root):
        if os.path.getmtime(cmake_file) > stamp:
            newer.append(os.path.relpath(cmake_file, repo.root))
    if newer:
        warn("{} is older than {}; run 'pk configure' for current usage".format(
            os.path.relpath(path, repo.root), ", ".join(newer[:3]) +
            (" ..." if len(newer) > 3 else "")))
    return usage, os.path.relpath(path, repo.root)


def users_of(usage, name):
    direct, effective = [], []
    for target, data in sorted((usage or {}).get("targets", {}).items()):
        if name in data.get("direct", {}):
            direct.append((target, data["direct"][name], data.get("role", "")))
        elif name in data.get("effective", {}):
            effective.append((target, data["effective"][name], data.get("role", "")))
    return direct, effective


# -----------------------------------------------------------------------------
# Graph helpers
# -----------------------------------------------------------------------------


def _ref_label(ref):
    """'name/version' from a lockfile ref OR ref itself."""
    match = LOCK_REF_RE.match(ref)
    return match.group(0) if match else ref


def graph_index(graph):
    nodes = graph["graph"]["nodes"]
    by_id = {}
    for node_id, node in nodes.items():
        match = LOCK_REF_RE.match(node.get("ref") or "")
        label = "{}/{}".format(match.group(1), match.group(2)) if match else node.get("ref")
        by_id[node_id] = {"name": match.group(1) if match else "",
                          "label": label,
                          "context": node.get("context", "host"),
                          "children": [(cid, dep) for cid, dep in
                                       (node.get("dependencies") or {}).items()
                                       if dep.get("direct")]}
    return by_id


def render_tree(by_id, node_id, prefix, seen, lines, show_build):
    children = [(cid, dep) for cid, dep in by_id[node_id]["children"]
                if show_build or not dep.get("build")]
    for index, (cid, dep) in enumerate(children):
        last = index == len(children) - 1
        tags = []
        if dep.get("build"):
            tags.append("build")
        if dep.get("test"):
            tags.append("test")

        tag = " [{}]".format(", ".join(tags)) if tags else ""
        repeat = " (see above)" if cid in seen else ""
        lines.append("{}{}{}{}{}".format(prefix, "`-- " if last else "|-- ",
                                        by_id[cid]["label"], tag, repeat))
        if cid in seen:
            continue

        seen.add(cid)
        render_tree(by_id, cid, prefix + ("    " if last else "|   "), seen, lines, show_build)


def paths_to(by_id, target_name):
    """Every chain of direct edges from the root to nodes' target_name."""
    results = []

    def walk(node_id, chain):
        for cid, _dep in by_id[node_id]["children"]:
            if cid in chain:
                continue
            if by_id[cid]["name"] == target_name:
                results.append(chain[1:] + [cid])
            walk(cid, chain + [cid])
    walk("0", ["0"])
    return results


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------


def _table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]

    out = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
    out.append("  ".join("-" * w for w in widths))
    for row in rows:
        out.append("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    return "\n".join(out)


def cmd_ls(repo, args):
    manifest = repo.load_manifest(required=False)
    locked = repo.locked_versions()
    usage, usage_path = load_usage(repo, args.tree)
    packages = manifest["packages"]

    if args.json:
        out = {}
        for name, entry in packages.items():
            direct, effective = users_of(usage, name)
            out[name] = dict(entry, locked=locked.get(name, []),
                             direct_users={t: v for t, v, _ in direct},
                             effective_users={t: v for t, v, _ in effective})
        print(json.dumps({"packages": out, "usage_file": usage_path}, indent=2))
        return 0

    rows = []
    for name, entry in sorted(packages.items()):
        kind = entry.get("kind", "requires")
        range_part = entry["ref"].split("/", 1)[1]
        cmake = entry.get("cmake")
        cmake_col = cmake["package"] if isinstance(cmake, dict) else "-"
        if kind == "tool":
            used = "(build tool)"
        elif usage is None:
            used = "?"
        elif kind == "test" and not any(t.get("role") == "TEST" for t in
                                        usage.get("targets", {}).values()):
            used = "(tests not configured)"
        else:
            direct, effective = users_of(usage, name)
            parts = ["{} ({})".format(t, v.lower()) for t, v, _ in direct]
            parts += ["{} (via)".format(t) for t, _, _ in effective]
            used = ", ".join(parts) if parts else "nothing"
        rows.append([name, kind, range_part, ", ".join(locked.get(name, [])) or "NOT LOCKED",
                     cmake_col, used])

    if args.all:
        for name in sorted(set(locked) - set(packages)):
            rows.append([name, "transitive", "-", ", ".join(locked[name]), "-",
                         "see 'pk dep why {}'".format(name)])

    if not rows:
        print("deps.json has no packages. Add one with: pk dep add <name>/<range>")
        return 0

    print(_table(rows, ["NAME", "KIND", "RANGE", "LOCKED", "CMAKE", "USED BY"]))
    print()
    if not os.path.isfile(repo.lock_path):
        warn("no conan.lock: versions are not pinned. Run 'pk dep lock'.")
    else:
        missing = [n for n in packages if n not in locked]
        if missing:
            warn("not in conan.lock: {}. Run 'pk dep lock'.".format(", ".join(missing)))

    if usage is not None:
        info("usage from {}".format(usage_path))
        unmanaged = sorted({u for t in usage.get("targets", {}).values()
                            for u in t.get("unmanaged", [])})
        if unmanaged:
            info("imported targets not from deps.json: {}".format(", ".join(unmanaged)))
    else:
        info("no usage report yet; 'pk configure' writes one")
    return 0


def _check_new_ref(ref):
    match = REF_RE.match(ref)
    if not match:
        raise PkDepError("'{}' is not a reference like name/1.2.3 or "
                         "'name/[>=1.2 <2]'".format(ref))
    return match.group(1)


def _apply_edits(entry, args):
    if getattr(args, "kind", None):
        entry["kind"] = args.kind

    options = dict(entry.get("options") or {})
    options.update(parse_pairs(getattr(args, "option", None), "--option"))
    for key in getattr(args, "unset_option", None) or []:
        options.pop(key, None)

    if options:
        entry["options"] = options
    else:
        entry.pop("options", None)

    traits = dict(entry.get("traits") or {})
    traits.update(parse_pairs(getattr(args, "trait", None), "--trait"))
    for key in getattr(args, "unset_trait", None) or []:
        traits.pop(key, None)

    if traits:
        entry["traits"] = traits
    else:
        entry.pop("traits", None)

    if getattr(args, "notes", None) is not None:
        if args.notes:
            entry["notes"] = args.notes
        else:
            entry.pop("notes", None)


def _explicit_cmake(entry, args):
    """--cmake-package/--target/... given by hand; None when none given."""
    given = any([args.cmake_package, args.target, args.extra_target,
                 args.component, args.cmake_version is not None])
    if not given:
        return None

    cmake = dict(entry.get("cmake") or {}) if isinstance(entry.get("cmake"), dict) else {}
    if args.cmake_package:
        cmake["package"] = args.cmake_package
    if args.target:
        cmake["targets"] = args.target
    if args.extra_target:
        cmake["extra_targets"] = args.extra_target
    if args.component:
        cmake["components"] = args.component
    if args.cmake_version is not None:
        if args.cmake_version:
            cmake["version"] = args.cmake_version
        else:
            cmake.pop("version", None)
    return cmake


def _link_hint(name, kind):
    if kind == "requires":
        info("link it:  pk_create_library(... DEPS_PRIVATE {})  or  pk_create_app(... DEPS {})".format(name, name))
        info("then:     pk build")
    elif kind == "test":
        info("link it:  pk_create_test(... DEPS {})".format(name))


def _report_lock_changes(before, after, names=None):
    changed = False
    for name in sorted(set(before) | set(after)):
        if names and name not in names and name in before and name in after \
           and before[name] == after[name]:
            continue

        old, new = before.get(name), after.get(name)
        if old == new:
            continue

        changed = True
        print("  {:<20} {} -> {}".format(name, ", ".join(old or ["-"]), ", ".join(new or ["-"])))

    if not changed:
        info("no version changes")


def cmd_add(repo, args):
    name = _check_new_ref(args.ref)
    manifest = repo.load_manifest(required=False)
    if name in manifest["packages"]:
        raise PkDepError("'{}' is already in deps.json; change it with 'pk dep set {}'".format(
            name, name))

    entry = {"ref": args.ref, "kind": args.kind or "requires"}
    _apply_edits(entry, args)
    kind = entry["kind"]
    explicit = _explicit_cmake(entry, args)
    if kind == "tool" and (explicit or args.no_cmake):
        raise PkDepError("tool packages have no CMake names")

    if args.no_cmake:
        entry["cmake"] = False
    elif explicit is not None:
        entry["cmake"] = explicit
    elif kind != "tool" and args.no_discover:
        raise PkDepError("--no-discover needs --cmake-package and --target (or --no-cmake)")

    with Transaction(repo):
        step("add {} ({})".format(args.ref, kind))
        pending = dict(entry)
        if kind != "tool" and "cmake" not in pending:
            pending["cmake"] = False
        manifest["packages"][name] = pending

        repo.save_manifest(manifest)
        before = repo.locked_versions(revisions=True)
        repo.lock_create(update=True)
        if repo.dry_run:
            return 0

        if kind != "tool" and "cmake" not in entry:
            entry["cmake"] = discover_cmake(repo, name, entry)
            manifest["packages"][name] = entry
            repo.save_manifest(manifest)
        step("locked")
        _report_lock_changes(before, repo.locked_versions(revisions=True))

    _link_hint(name, kind)
    return 0


def cmd_set(repo, args):
    manifest = repo.load_manifest()
    name = args.name
    if name not in manifest["packages"]:
        raise PkDepError("'{}' is not in deps.json (known: {})".format(
            name, ", ".join(sorted(manifest["packages"])) or "none"))

    entry = dict(manifest["packages"][name])
    old = dict(entry)

    if args.ref and args.range:
        raise PkDepError("give --ref or --range, not both")
    if args.range:
        entry["ref"] = "{}/{}".format(name, args.range)
    if args.ref:
        if _check_new_ref(args.ref) != name:
            raise PkDepError("--ref must keep the name '{}'; renaming is 'pk dep rm' + "
                             "'pk dep add'".format(name))
        entry["ref"] = args.ref

    _apply_edits(entry, args)
    explicit = _explicit_cmake(entry, args)
    if args.no_cmake:
        entry["cmake"] = False
    elif explicit is not None:
        entry["cmake"] = explicit

    if entry.get("kind") == "tool":
        entry.pop("cmake", None)
    if entry == old and not args.discover:
        info("nothing to change")
        return 0

    # Only a new ref/range can change the locked version.
    ref_changed = entry["ref"] != old["ref"]
    kind_changed = entry.get("kind", "requires") != old.get("kind", "requires")
    relock = ref_changed or kind_changed or any(
        entry.get(k) != old.get(k) for k in ("options", "traits"))

    with Transaction(repo):
        step("set {}".format(name))
        if args.discover and entry.get("kind") != "tool":
            entry.setdefault("cmake", False)

        manifest["packages"][name] = entry
        repo.save_manifest(manifest)
        before = repo.locked_versions(revisions=True)
        if relock:
            pinned = repo.locked_refs(name)
            if ref_changed or kind_changed:
                repo.lock_remove([name])
            if kind_changed and not ref_changed and pinned:
                flag = "--build-requires=" if entry.get("kind") == "tool" else "--requires="
                repo.run(["lock", "add", "--lockfile=conan.lock",
                          "--lockfile-out=conan.lock"] + [flag + ref for _, ref in pinned])
            repo.lock_create(update=ref_changed)

        if repo.dry_run:
            return 0

        if args.discover and entry.get("kind") != "tool":
            entry["cmake"] = discover_cmake(repo, name, entry)
            manifest["packages"][name] = entry
            repo.save_manifest(manifest)
        if relock:
            step("locked")
            _report_lock_changes(before, repo.locked_versions(revisions=True), [name])
    return 0


def cmd_rm(repo, args):
    manifest = repo.load_manifest()
    name = args.name
    if name not in manifest["packages"]:
        raise PkDepError("'{}' is not in deps.json".format(name))

    entry = manifest["packages"][name]
    uses, _finds = scan_sources(repo.root)
    blockers = ["{}:{}: {} {} {}".format(u["file"], u["line"], u["command"],
                                           u["keyword"], name).replace("  ", " ")
                for u in uses if u["name"] == name]
    cmake = entry.get("cmake")
    if isinstance(cmake, dict):
        wanted = list(cmake.get("targets", [])) + list(cmake.get("extra_targets", []))
        for path in _cmake_files(repo.root):
            with open(path, encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    code = line.split("#", 1)[0]
                    for target in wanted:
                        if target in code:
                            blockers.append("{}:{}: links {} by hand".format(
                                os.path.relpath(path, repo.root).replace("\\", "/"),
                                number, target))

    if blockers and not args.force:
        raise PkDepError("'{}' is still used; remove these first (or --force):\n  {}".format(
            name, "\n  ".join(blockers)))

    with Transaction(repo):
        step("remove {}".format(name))
        del manifest["packages"][name]
        repo.save_manifest(manifest)
        before = repo.locked_versions(revisions=True)
        if os.path.isfile(repo.lock_path):
            repo.lock_create(clean=True)
        if repo.dry_run:
            return 0
        step("locked")
        _report_lock_changes(before, repo.locked_versions(revisions=True))

    if blockers:
        warn("removed while still referenced; the next configure will fail until "
             "these are fixed:\n  " + "\n  ".join(blockers))
    return 0


def cmd_update(repo, args):
    manifest = repo.load_manifest()
    names = args.names
    unknown = [n for n in names if n not in manifest["packages"]]
    if unknown:
        raise PkDepError("not in deps.json: {}".format(", ".join(unknown)))

    with Transaction(repo):
        before = repo.locked_versions(revisions=True)
        if names:
            step("update {}".format(", ".join(names)))
            repo.lock_remove(names)
            repo.lock_create(update=True)
        else:
            step("update everything (a fresh lock, newest versions in every range)")
            if os.path.isfile(repo.lock_path) and not repo.dry_run:
                os.remove(repo.lock_path)
            repo.lock_create(update=True)

        if repo.dry_run:
            return 0

        step("locked")
        _report_lock_changes(before, repo.locked_versions(revisions=True))

    info("rebuild and test before committing conan.lock: pk test")
    return 0


def cmd_lock(repo, args):
    repo.load_manifest()

    with Transaction(repo):
        before = repo.locked_versions(revisions=True)
        step("lock ({})".format(", ".join(repo.profiles)))
        repo.lock_create(clean=args.clean)

        if repo.dry_run:
            return 0

        _report_lock_changes(before, repo.locked_versions(revisions=True))
    return 0


def cmd_check(repo, args):
    problems, notes = [], []
    try:
        manifest = repo.load_manifest()
    except PkDepError as exc:
        print(str(exc))
        return 1
    packages = manifest["packages"]

    step("deps.json")
    info("{} packages, schema valid".format(len(packages)))
    step("CMake sources")

    uses, finds = scan_sources(repo.root)
    used_names = set()
    for use in uses:
        name = use["name"]
        where = "{}:{}".format(use["file"], use["line"])
        if name not in packages:
            problems.append("{}: '{}' is not in deps.json".format(where, name))
            continue
        used_names.add(name)
        kind = packages[name].get("kind", "requires")
        if kind == "tool":
            problems.append("{}: '{}' is a tool dependency and cannot be used from "
                            "CMake".format(where, name))
        elif kind == "test" and use["role"] not in ("TEST", "FIND"):
            problems.append("{}: '{}' is a test dependency used by a {} target".format(
                where, name, use["role"].lower()))

    by_cmake = {e["cmake"]["package"]: n for n, e in packages.items()
                if isinstance(e.get("cmake"), dict)}

    for found in finds:
        if found["package"] in by_cmake:
            notes.append("{}:{}: find_package({}) by hand; pk_deps_find({}) keeps it "
                         "in step with deps.json".format(found["file"], found["line"],
                                                         found["package"],
                                                         by_cmake[found["package"]]))

    for name, entry in sorted(packages.items()):
        kind = entry.get("kind", "requires")
        if kind == "requires" and name not in used_names:
            cmake = entry.get("cmake")
            linked_by_hand = False

            if isinstance(cmake, dict):
                wanted = cmake.get("targets", []) + cmake.get("extra_targets", [])
                for path in _cmake_files(repo.root):
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        text = handle.read()
                    if any(t in text for t in wanted):
                        linked_by_hand = True
                        break

            if not linked_by_hand:
                (problems if args.strict else notes).append(
                    "'{}' is in deps.json but nothing uses it".format(name))

    info("{} uses scanned".format(len(uses)))
    step("conan.lock")

    if not os.path.isfile(repo.lock_path):
        problems.append("no conan.lock; run 'pk dep lock' and commit it")
    else:
        locked = repo.locked_versions()
        for name in sorted(packages):
            if name not in locked:
                problems.append("'{}' is in deps.json but not in conan.lock; run "
                                "'pk dep lock'".format(name))

        lock_refs = set()
        for section in ("requires", "build_requires"):
            lock_refs |= {r.split("%", 1)[0] for r in (repo.load_lock() or {}).get(section, [])}
        used_refs = set()

        for profile in repo.profiles:
            probe = ["graph", "info", "."] + repo.profile_args(profile)
            probe += ["-c", "tools.graph:skip_test=False", "--lockfile=conan.lock",
                      "--format=json"]
            proc = repo.capture(probe, check=False)

            if proc.returncode != 0:
                errors = [l for l in (proc.stderr or "").splitlines() if "ERROR" in l]
                problems.append("conan.lock does not satisfy deps.json for profile '{}': "
                                "{}\n    fix: 'pk dep lock' (keeps other pins) or 'pk dep "
                                "update <name>'".format(profile, " ".join(errors[-2:]) or
                                                        "conan graph info failed"))
                continue

            for node in json.loads(proc.stdout)["graph"]["nodes"].values():
                ref = node.get("ref") or ""
                if "#" in ref:
                    used_refs.add(ref)

        stale = sorted(lock_refs - used_refs)
        if stale and used_refs:
            notes.append("conan.lock has entries {} not used by profile(s) {} (fine if "
                         "another profile needs them; 'pk dep lock --clean' prunes)".format(
                             ", ".join(_ref_label(r) for r in stale),
                             ", ".join(repo.profiles)))
        if not problems:
            info("every package resolves from conan.lock")

    for note in notes:
        print("  note: " + note)

    if problems:
        print()
        for problem in problems:
            print(_c("31", "  problem: ") + problem)
        print("\n{} problem(s)".format(len(problems)))
        return 1

    print("\n" + _c("32", "ok") + ": deps.json, CMake sources and conan.lock agree")
    return 0


def cmd_why(repo, args):
    manifest = repo.load_manifest(required=False)
    packages = manifest["packages"]
    name = args.name
    usage, usage_path = load_usage(repo, args.tree)
    locked = repo.locked_versions()

    print(_c("1", name))
    if name in packages:
        entry = packages[name]
        print("  declared in deps.json: {} (kind {})".format(entry["ref"], entry.get("kind", "requires")))
        if entry.get("notes"):
            print("  notes: {}".format(entry["notes"]))
    print("  locked: {}".format(", ".join(locked.get(name, [])) or "not in conan.lock"))

    graph = repo.graph()
    by_id = graph_index(graph)
    chains = paths_to(by_id, name)
    tops = []
    if chains:
        print("  pulled in by Conan:")
        for chain in chains:
            labels = [by_id[c]["label"] for c in chain]
            print("    {} -> {}".format(graph["graph"]["nodes"]["0"].get("label") or "(project)",
                                        " -> ".join(labels)))

            top = by_id[chain[0]]["name"]
            if top not in tops:
                tops.append(top)
    elif name not in packages:
        print("  not in the Conan graph for profile '{}'".format(repo.profiles[0]))
        return 1

    if usage is None:
        print("  targets: unknown, configure first ('pk configure')")
        return 0

    for top in tops or [name]:
        direct, effective = users_of(usage, top)
        label = "" if top == name else " (through {})".format(top)
        if not direct and not effective:
            kind = packages.get(top, {}).get("kind", "requires")
            if kind == "tool":
                print("  targets{}: none, it is a build tool".format(label))
            else:
                print("  targets{}: none in {}".format(label, usage_path))
            continue

        print("  targets{}:".format(label))

        for target, vis, role in direct:
            print("    {:<28} {} {} (links it directly)".format(target, role.lower(), vis.lower()))
        for target, via, role in effective:
            print("    {:<28} {} via {}".format(target, role.lower(), via))
    return 0


def cmd_tree(repo, args):
    graph = repo.graph()
    by_id = graph_index(graph)
    top_ids = {by_id[cid]["name"]: cid for cid, _ in by_id["0"]["children"]}

    if args.packages:
        lines = ["(project)"]
        render_tree(by_id, "0", "", set(), lines, args.build)
        print("\n".join(lines))
        return 0

    usage, usage_path = load_usage(repo, args.tree)
    if usage is None:
        raise PkDepError("no usage report yet; run 'pk configure' first "
                         "(or 'pk dep tree --packages' for the Conan graph alone)")

    targets = usage.get("targets", {})
    wanted = args.targets or sorted(targets)
    missing = [t for t in wanted if t not in targets]
    if missing:
        raise PkDepError("no target(s) {} in {} (known: {})".format(
            ", ".join(missing), usage_path, ", ".join(sorted(targets))))

    for target in wanted:
        data = targets[target]
        print("{} ({})".format(_c("1", target), data.get("role", "").lower()))
        direct = data.get("direct", {})
        rows = [(name, "direct, " + vis.lower()) for name, vis in sorted(direct.items())]
        rows += [(name, "via " + " -> ".join(via.split(" -> ")[1:]))
                 for name, via in sorted(data.get("effective", {}).items())
                 if name not in direct]
        if not rows:
            print("`-- (no packages)")

        for index, (name, why) in enumerate(rows):
            last = index == len(rows) - 1
            cid = top_ids.get(name)
            label = by_id[cid]["label"] if cid else name
            print("{}{}  [{}]".format("`-- " if last else "|-- ", label, why))
            if cid:
                lines = []
                render_tree(by_id, cid, "    " if last else "|   ", set(), lines, args.build)
                if lines:
                    print("\n".join(lines))

        for imported in data.get("unmanaged", []):
            print("    note: also links {} (not from deps.json)".format(imported))
        print()
    return 0


HELP = """\
pk dep - manage third-party packages (deps.json + conan.lock)

  pk dep ls [--all] [--json]           packages, locked versions, users
  pk dep add <name>/<range> [...]      add, lock, discover CMake names
  pk dep set <name> [...]              change range, kind, options, traits, names
  pk dep rm <name> [--force]           remove (refuses while still used)
  pk dep update [<name>...]            newest versions within the ranges
  pk dep lock [--clean]                create or extend conan.lock
  pk dep check [--strict]              deps.json, CMake and conan.lock agree
  pk dep why <name>                    who pulls a package in, who uses it
  pk dep tree [<target>...]            per-target dependency trees
  pk dep tree --packages               the Conan graph on its own

Common flags: -n/--dry-run, --profile NAME (repeatable, default native)
Details: pk dep <command> --help, cmake/projectkit/docs/PK_DEP.md
"""


def build_parser():
    parser = argparse.ArgumentParser(prog="pk dep", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-n", "--dry-run", action="store_true",
                        help="print what would change and the Conan commands, change nothing")
    common.add_argument("--profile", action="append", default=[],
                        help="host profile under profiles/ (repeatable; default: native)")
    sub = parser.add_subparsers(dest="command")

    def edit_flags(p, adding):
        p.add_argument("--kind", choices=KINDS,
                       help="requires (default for add), test or tool")
        p.add_argument("--option", action="append", metavar="KEY=VALUE",
                       help="Conan option for this package, e.g. shared=False")
        p.add_argument("--trait", action="append", metavar="KEY=VALUE",
                       help="requirement trait, e.g. transitive_headers=true")
        if not adding:
            p.add_argument("--unset-option", action="append", metavar="KEY")
            p.add_argument("--unset-trait", action="append", metavar="KEY")
        p.add_argument("--cmake-package", help="find_package() name (skips discovery)")
        p.add_argument("--cmake-version", help="version passed to find_package(), '' clears")
        p.add_argument("--component", action="append", help="find_package() COMPONENTS")
        p.add_argument("--target", action="append", help="imported target(s) DEPS links")
        p.add_argument("--extra-target", action="append",
                       help="other imported targets the package creates")
        p.add_argument("--no-cmake", action="store_true",
                       help="not used through find_package() (\"cmake\": false)")
        p.add_argument("--notes", help="free text kept in deps.json ('' clears)")

    p = sub.add_parser("ls", aliases=["list"], parents=[common])
    p.add_argument("--all", action="store_true", help="also list transitive packages")
    p.add_argument("--json", action="store_true")
    p.add_argument("--tree", help="build tree whose usage report to read")

    p = sub.add_parser("add", parents=[common])
    p.add_argument("ref", help="name/version or 'name/[>=1.2 <2]'")
    edit_flags(p, True)
    p.add_argument("--no-discover", action="store_true",
                   help="do not install to discover CMake names")

    p = sub.add_parser("set", parents=[common])
    p.add_argument("name")
    p.add_argument("--ref", help="a new full reference, same name")
    p.add_argument("--range", help="a new version or range, e.g. '[>=3.46 <4]'")
    p.add_argument("--discover", action="store_true",
                   help="refresh CMake names from what Conan generates")
    edit_flags(p, False)

    p = sub.add_parser("rm", aliases=["remove"], parents=[common])
    p.add_argument("name")
    p.add_argument("--force", action="store_true", help="remove even while referenced")

    p = sub.add_parser("update", aliases=["up"], parents=[common])
    p.add_argument("names", nargs="*", help="packages to update (default: all)")

    p = sub.add_parser("lock", parents=[common])
    p.add_argument("--clean", action="store_true", help="drop entries nothing needs")

    p = sub.add_parser("check", parents=[common])
    p.add_argument("--strict", action="store_true", help="unused packages are errors")

    p = sub.add_parser("why", parents=[common])
    p.add_argument("name")
    p.add_argument("--tree", help="build tree whose usage report to read")

    p = sub.add_parser("tree", parents=[common])
    p.add_argument("targets", nargs="*")
    p.add_argument("--packages", action="store_true", help="Conan graph only")
    p.add_argument("--build", action="store_true", help="include build requirements")
    p.add_argument("--tree", help="build tree whose usage report to read")
    return parser


COMMANDS = {"ls": cmd_ls, "list": cmd_ls, "add": cmd_add, "set": cmd_set,
            "rm": cmd_rm, "remove": cmd_rm, "update": cmd_update, "up": cmd_update,
            "lock": cmd_lock, "check": cmd_check, "why": cmd_why, "tree": cmd_tree}


def main(argv):
    if not argv or argv[0] in ("help", "-h", "--help"):
        if len(argv) > 1:
            build_parser().parse_args([argv[1], "--help"])
        print(HELP, end="")
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.help or not args.command:
        print(HELP, end="")
        return 0

    try:
        repo = Repo(find_root(), args.profile, args.dry_run)
        return COMMANDS[args.command](repo, args)
    except PkDepError as exc:
        print("{} {}".format(_c("31", "error:"), exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
