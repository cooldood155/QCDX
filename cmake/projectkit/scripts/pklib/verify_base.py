"""Platform-neutral base for the ProjectKit verification.

Nothing here knows the project's name: it comes from PK_PROJECT, from the
top-level project() call, or from scripts/helpers/verify/verify.conf.

A caller sets only what its target needs, then calls run_stages(). The stage
lists are data, so a cross target that cannot execute what it builds names
fewer stages rather than setting skip flags everywhere.

  setup_stages   once, before anything is built
  type_stages    once per entry in build_types, as a pipeline
  final_stages   once, after every build type

Nothing is ever built in a build type that was not asked for.
"""

from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import tempfile
from typing import Callable, List, Optional, Tuple, Union

from . import targets
from .common import (C, Config, capture, detect_project, err, exe_suffix, have, load_conf, native_path, out,
                     remove, run, tee, walk_files)

CRITICAL_STAGES = ("environment", "workflow", "host_tools_for_cross", "cross_build")
Action = Union[List[str], Callable[[], bool]]


def make_prefix(project: str) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "_", project.upper())
    return prefix[:-1] if prefix.endswith("_") else prefix


class Verify:
    def __init__(self, root: str, conf: Optional[Config] = None) -> None:
        conf = conf or load_conf(root, "scripts/helpers/verify/verify.conf")
        self.root = root
        self.project = conf.get("PK_PROJECT") or detect_project(root)
        if not self.project:
            err("cannot determine the project name: set PK_PROJECT or add a")
            err(f"project() call to {os.path.join(root, 'CMakeLists.txt')}")
            raise SystemExit(2)

        self.package = conf.get("PK_PACKAGE", self.project)
        self.link_target = conf.get("PK_LINK_TARGET", f"{self.package}::{self.package}")
        self.consumer_source = conf.get("PK_CONSUMER_SOURCE")
        self.scratch_dir = conf.get("PK_SCRATCH_DIR", os.path.join(root, "src", self.project, "scratch"))
        self.prefix = make_prefix(self.project)
        self.consumer_dir = conf.get(
            "PK_CONSUMER_DIR", os.path.join(tempfile.gettempdir(), f"{self.project}-consumer"))
        self.platform_label = conf.get(
            "PK_PLATFORM_LABEL", f"{platform.system() or 'unknown'} {platform.machine() or 'unknown'}")
        self.build_profile = conf.get("PK_BUILD_PROFILE", os.path.join(root, "profiles", "native"))
        self.host_profile = conf.get("PK_HOST_PROFILE")
        self.build_types = conf.get("PK_BUILD_TYPES", "Debug Release").split()
        self.preset_prefix = conf.get("PK_PRESET_PREFIX", "native")
        self.host_tools_preset = conf.get("PK_HOST_TOOLS_PRESET", "host-tools")
        self.library_types = conf.get("PK_LIBRARY_TYPES", "STATIC SHARED STATIC+SHARED").split()
        self.required_tools = conf.get("PK_REQUIRED_TOOLS", "conan cmake ctest ninja git").split()
        self.setup_stages = conf.get("PK_SETUP_STAGES", "environment clean_slate").split()
        self.type_stages = conf.get("PK_TYPE_STAGES", " ".join(targets.DEFAULT_TYPE_STAGES)).split()
        self.final_stages = conf.get("PK_FINAL_STAGES", "reset").split()
        self.exe_suffix = conf.get("PK_EXE_SUFFIX") if conf.is_set("PK_EXE_SUFFIX") else exe_suffix()

        self.keep = False
        self.target_name = "unknown"
        self.build_type = ""
        self.preset = ""
        self.setup_failed = False
        self.stage_number = 0
        self.pass_count = 0
        self.skip_count = 0
        self.failures: List[str] = []
        self.results: List[Tuple[str, str, str]] = []
        self.on_result: Optional[Callable[[str, str], None]] = None
        self.platform_check: Callable[[], bool] = lambda: True

    def apply_target(self, name: str) -> bool:
        settings = targets.configure(name, self.root)
        if settings is None:
            err(f"unknown target: {name}")
            return False
        self.target_name = name
        for key, value in settings.items():
            setattr(self, key, value)

        def check() -> bool:
            result = targets.availability(name, self.root, "strict") or (False, "unknown target")
            if result[0]:
                self.ok(f"target {name} is available here")
                return True
            return self.fail(f"target {name} not available: {result[1]}")

        self.platform_check = check
        return True

    def preset_for(self, build_type: str) -> str:
        return f"{self.preset_prefix}-{build_type.lower()}"

    def clean_paths(self) -> List[str]:
        return [os.path.join(self.root, "build"), os.path.join(self.root, "stage"),
                os.path.join(self.root, "_install"), os.path.join(self.root, "compile_commands.json"),
                self.scratch_dir, self.consumer_dir]

    def cleanup(self) -> None:
        for path in self.clean_paths():
            remove(path)

    def expected_install_files(self) -> List[str]:
        package = self.package
        return [f"lib/cmake/{package}/{package}Config.cmake",
                f"lib/cmake/{package}/{package}ConfigVersion.cmake",
                f"lib/cmake/{package}/{package}Targets.cmake",
                f"lib/pkgconfig/{package}.pc"]

    def stage(self, title: str) -> None:
        tag = f"[{self.build_type}] " if self.build_type else ""
        self.stage_number += 1
        out(f"\n{C.bold}---- {self.stage_number}. {tag}{title} ----{C.reset}")

    def _notify(self, status: str, label: str) -> None:
        if self.on_result is not None:
            self.on_result(status, label)

    def ok(self, label: str) -> bool:
        out(f"{C.green}OK{C.reset}    {label}")
        self.pass_count += 1
        self._notify("pass", label)
        return True

    def fail(self, label: str) -> bool:
        out(f"{C.red}FAIL{C.reset}  {label}")
        self.failures.append(f"[{self.build_type}] {label}" if self.build_type else label)
        self._notify("fail", label)
        return False

    def skip(self, label: str) -> None:
        out(f"{C.yellow}SKIP{C.reset}  {label}")
        self.skip_count += 1
        self._notify("skip", label)

    def attempt(self, label: str, action: Action) -> bool:
        passed = action() if callable(action) else run(action) == 0
        return self.ok(label) if passed else self.fail(label)

    # Conan owns build/<BuildType>/ and CMake owns build/<presetName>/. Deleting
    # build/ therefore invalidates every preset's toolchainFile, so any stage
    # that does so must install again before configuring.
    def conan_install(self, build_type: str) -> List[str]:
        if self.host_profile:
            profiles = ["-pr:b", self.build_profile, "-pr:h", self.host_profile]
        else:
            profiles = ["-pr:a", self.build_profile]
        return ["conan", "install", self.root, *profiles, "-s", f"build_type={build_type}",
                "--build=missing"]

    def toolchain(self, build_type: str) -> str:
        return native_path(os.path.join(self.root, "build", build_type, "generators",
                                        "conan_toolchain.cmake"))

    # The host-tools preset fixes toolchainFile at build/Release/...; presets
    # have no macro for the build type, so both are overridden on the command
    # line, where a -D wins over the preset's value.
    def configure_host_tools(self) -> List[str]:
        return ["cmake", "--preset", self.host_tools_preset, f"-DCMAKE_BUILD_TYPE={self.build_type}",
                f"-DCMAKE_TOOLCHAIN_FILE={self.toolchain(self.build_type)}"]

    def stage_environment(self) -> bool:
        self.stage("Environment")
        out(f"target:   {self.platform_label}")
        out(f"build:    {os.path.basename(self.build_profile)}")
        if self.host_profile:
            out(f"host:     {os.path.basename(self.host_profile)}")
        out(f"types:    {' '.join(self.build_types)}")
        for tool in self.required_tools:
            if have(tool):
                self.ok(f"found {tool}")
            else:
                return self.fail(f"missing {tool}")
        return self.platform_check()

    def stage_clean_slate(self) -> bool:
        self.stage("Clean slate")
        self.cleanup()
        return self.ok("removed generated output")

    def stage_workflow(self) -> bool:
        self.stage("Workflow")
        log: List[str] = []

        def install() -> bool:
            code, text = tee(self.conan_install(self.build_type))
            log.append(text)
            return code == 0

        if not self.attempt(f"conan install ({self.build_type})", install):
            return False
        # tools.build:skip_test=True given to Conan in any way sets
        # <PREFIX>_BUILD_TESTS=OFF, which skips add_subdirectory(tests) and makes
        # ctest answer "No tests were found" instead of an error.
        if f"{self.prefix}_BUILD_TESTS=OFF" in log[0]:
            self.fail(f"{self.prefix}_BUILD_TESTS=OFF -- check tools.build:skip_test in your default profile")
        else:
            self.ok(f"{self.prefix}_BUILD_TESTS is ON")
        return self.attempt(f"workflow {self.preset}", ["cmake", "--workflow", "--preset", self.preset])

    # Host tools run on the build machine, so they always use the native
    # profile, built in the same type as the pass they belong to.
    def stage_host_tools_for_cross(self) -> bool:
        self.stage("Host tools for cross")
        if not self.attempt(f"conan install ({self.build_type}, native)", [
                "conan", "install", self.root, "-pr:a", os.path.join(self.root, "profiles", "native"),
                "-s", f"build_type={self.build_type}", "--build=missing"]):
            return False
        remove(os.path.join(self.root, "build", self.host_tools_preset))
        if not self.attempt(f"configure {self.host_tools_preset} ({self.build_type})",
                            self.configure_host_tools()):
            return False
        return self.attempt(f"build {self.host_tools_preset} ({self.build_type})",
                            ["cmake", "--build", f"build/{self.host_tools_preset}"])

    # Cross targets have no test preset and cannot run what they produce, so
    # they only configure and build.
    def stage_cross_build(self) -> bool:
        self.stage("Cross configure and build")
        if not self.attempt(f"conan install ({self.build_type})", self.conan_install(self.build_type)):
            return False
        if not self.attempt(f"configure {self.preset}", ["cmake", "--preset", self.preset]):
            return False
        return self.attempt(f"build {self.preset}", ["cmake", "--build", f"build/{self.preset}"])

    # Relies on workflow (native) or cross_build (cross) having already run
    # conan install for this build type.
    def stage_library_matrix(self) -> bool:
        self.stage("Library type matrix")
        for library_type in self.library_types:
            out(f"  -- {library_type} --")
            remove(os.path.join(self.root, "build", self.preset))
            if not self.attempt(f"configure {library_type}", [
                    "cmake", "--preset", self.preset, f"-D{self.prefix}_LIBRARY_TYPE={library_type}"]):
                continue
            if not self.attempt(f"build {library_type}", ["cmake", "--build", f"build/{self.preset}"]):
                continue
            if self.host_profile:
                self.skip(f"ctest {library_type} (cross target, binaries not runnable here)")
                continue
            self.attempt(f"ctest {library_type}",
                         ["ctest", "--test-dir", f"build/{self.preset}", "--output-on-failure"])
        return True

    def stage_auto_discovery(self) -> bool:
        self.stage("Auto-discovery")
        os.makedirs(self.scratch_dir, exist_ok=True)
        with open(os.path.join(self.scratch_dir, "probe.cpp"), "w", newline="\n") as file:
            file.write("int pk_scratch_probe() { return 1; }\n")

        _code, log = capture(["cmake", "--build", f"build/{self.preset}"], merge=True)
        out(log.rstrip("\n"))
        if "probe.cpp" in log:
            self.ok("new source compiled without editing CMake")
        else:
            self.fail("probe.cpp was not picked up -- CONFIGURE_DEPENDS is not working")

        remove(self.scratch_dir)
        return self.attempt("rebuild after removing the probe", ["cmake", "--build", f"build/{self.preset}"])

    # Reconfigured from scratch because library_matrix left this tree set to
    # its last library type.
    def stage_install(self) -> bool:
        self.stage("Install and package metadata")
        stage = os.path.join(self.root, "stage")
        remove(os.path.join(self.root, "build", self.preset))
        remove(stage)

        if not self.attempt(f"configure {self.preset}", ["cmake", "--preset", self.preset]):
            return False
        if not self.attempt(f"build {self.preset}", ["cmake", "--build", f"build/{self.preset}"]):
            return False
        if not self.attempt(f"install {self.preset}", [
                "cmake", "--install", f"build/{self.preset}", "--prefix", native_path(stage)]):
            return False

        for path in sorted(walk_files(stage)):
            out(path)
        for expected in self.expected_install_files():
            if os.path.isfile(os.path.join(stage, *expected.split("/"))):
                self.ok(f"installed {expected}")
            else:
                self.fail(f"missing {expected}")

        pc_dir = os.path.join(stage, "lib", "pkgconfig")
        pc = os.path.join(pc_dir, f"{self.package}.pc")
        if os.path.isfile(pc):
            with open(pc, encoding="utf-8", errors="replace") as file:
                out(file.read().rstrip("\n"))
            if have("pkg-config"):
                env = dict(os.environ, PKG_CONFIG_PATH=native_path(pc_dir))
                self.attempt(f"pkg-config reads {self.package}.pc", lambda: run(
                    ["pkg-config", "--cflags", "--libs", self.package], env=env) == 0)
            else:
                self.skip("pkg-config not installed")
        return True

    # The consumer project only ever sees installed files.
    def stage_consumer(self) -> bool:
        self.stage("Consumer project")
        stage = os.path.join(self.root, "stage")
        config = os.path.join(stage, "lib", "cmake", self.package, f"{self.package}Config.cmake")
        if not os.path.isfile(config):
            self.skip(f"no {self.package}Config.cmake was installed")
            return True

        consumer = self.consumer_dir
        remove(consumer)
        os.makedirs(consumer, exist_ok=True)
        with open(os.path.join(consumer, "CMakeLists.txt"), "w", newline="\n") as file:
            file.write("cmake_minimum_required(VERSION 3.30)\n"
                       "project(consumer LANGUAGES CXX)\n"
                       f"find_package({self.package} REQUIRED)\n"
                       "add_executable(consumer main.cpp)\n"
                       f"target_link_libraries(consumer PRIVATE {self.link_target})\n")

        main_cpp = os.path.join(consumer, "main.cpp")
        if self.consumer_source:
            if not os.path.isfile(self.consumer_source):
                return self.fail(f"PK_CONSUMER_SOURCE does not exist: {self.consumer_source}")
            shutil.copyfile(self.consumer_source, main_cpp)
        else:
            with open(main_cpp, "w", newline="\n") as file:
                file.write("int main() { return 0; }\n")

        build = os.path.join(consumer, "b")
        if not self.attempt(f"configure consumer ({self.build_type})", [
                "cmake", "-S", native_path(consumer), "-B", native_path(build), "-G", "Ninja",
                f"-DCMAKE_BUILD_TYPE={self.build_type}",
                f"-DCMAKE_TOOLCHAIN_FILE={self.toolchain(self.build_type)}",
                f"-DCMAKE_PREFIX_PATH={native_path(stage)}"]):
            return False
        if not self.attempt(f"build consumer ({self.build_type})", ["cmake", "--build", native_path(build)]):
            return False
        return self.attempt(f"run consumer ({self.build_type})",
                            [os.path.join(build, f"consumer{self.exe_suffix}")])

    def stage_cpack(self) -> bool:
        self.stage("CPack")
        build_dir = os.path.join(self.root, "build", self.preset)
        if not os.path.isdir(build_dir):
            self.skip(f"no build tree for {self.preset}")
            return True
        if (run(["cpack"], cwd=build_dir) == 0
                and run(["cpack", "--config", "CPackSourceConfig.cmake"], cwd=build_dir) == 0):
            self.ok(f"cpack binary and source packages ({self.preset})")
            for package in sorted(glob.glob(os.path.join(build_dir, "*.tar.gz"))
                                  + glob.glob(os.path.join(build_dir, "*.zip"))):
                out(package)
            return True
        return self.fail(f"cpack ({self.preset})")

    # Makes sure <PREFIX>_LIBRARY_TYPE=NONE is properly guarded in the project.
    def stage_host_tools(self) -> bool:
        self.stage("Host tools only")
        remove(os.path.join(self.root, "build", self.host_tools_preset))
        if not self.attempt(f"configure {self.host_tools_preset} ({self.build_type})",
                            self.configure_host_tools()):
            return False
        return self.attempt(f"build {self.host_tools_preset} ({self.build_type})",
                            ["cmake", "--build", f"build/{self.host_tools_preset}"])

    def stage_reset(self) -> bool:
        self.stage("Reset")
        if self.keep:
            out("--keep given: leaving generated output in place.")
            return True
        self.cleanup()
        return self.ok("removed generated output")

    def summary(self) -> bool:
        out(f"\n{C.bold}---- {self.platform_label} ----{C.reset}")
        out(f"passed: {self.pass_count}  skipped: {self.skip_count}")
        for build_type in self.build_types:
            if self.setup_failed:
                result = "not run"
            else:
                count = sum(1 for f in self.failures if f.startswith(f"[{build_type}] "))
                result = "passed" if count == 0 else f"failed ({count})"
            out(f"  {build_type:<16} {result}")
            self.results.append((self.target_name, build_type, result))

        if self.failures:
            out(f"{C.red}failures:{C.reset}")
            for failure in self.failures:
                out(f"  - {failure}")
            return False
        out(f"{C.green}all stages passed{C.reset}")
        return True

    # Returns False when a stage that later stages depend on fails, skipping
    # the rest of the list.
    def run_stage_list(self, stages: List[str]) -> bool:
        for name in stages:
            method = getattr(self, f"stage_{name}", None)
            if method is None:
                self.fail(f"unknown stage '{name}'")
                continue
            if not method() and name in CRITICAL_STAGES:
                self.skip(f"remaining {self.build_type or 'setup'} stages: {name} failed")
                return False
        return True

    def run_stages(self) -> bool:
        os.chdir(self.root)
        if self.run_stage_list(self.setup_stages):
            for build_type in self.build_types:
                self.build_type = build_type
                self.preset = self.preset_for(build_type)
                self.run_stage_list(self.type_stages)
            self.build_type = ""
            self.preset = ""
            self.run_stage_list(self.final_stages)
        else:
            self.setup_failed = True
        return self.summary()
