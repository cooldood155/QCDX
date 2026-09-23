import os

from conan import ConanFile
from conan.tools.build import can_run
from conan.tools.cmake import CMake, CMakeToolchain, cmake_layout


class ProjectKitTestPackage(ConanFile):
  settings = "os", "arch", "compiler", "build_type"
  generators = "CMakeDeps", "VirtualRunEnv"
  test_type = "explicit"

  def requirements(self):
    self.requires(self.tested_reference_str)

  def layout(self):
    cmake_layout(self)

  def generate(self):
    tc = CMakeToolchain(self)
    tc.user_presets_path = False
    tc.cache_variables["PK_TESTED_PACKAGE"] = self.tested_reference_str.split("/")[0]

    source = os.environ.get("PK_TEST_SOURCE", "")
    if source:
      tc.cache_variables["PK_TEST_SOURCE"] = source.replace("\\", "/")

    tc.generate()

  def build(self):
    cmake = CMake(self)
    cmake.configure()
    cmake.build()

  def test(self):
    if not can_run(self):
      return

    executable = os.path.normpath(
      os.path.join(self.build_folder, self.cpp.build.bindir, "test_package"))

    self.run(executable, env="conanrun")
