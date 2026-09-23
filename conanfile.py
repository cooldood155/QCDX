# pyright: reportAttributeAccessIssue=false, reportOptionalCall=false, reportArgumentType=false, reportCallIssue=false

from os import path
from re import search, IGNORECASE
from conan import ConanFile
from conan.tools.cmake import cmake_layout, CMake, CMakeDeps, CMakeToolchain
from conan.tools.files import save, load

class QcdxRecipe(ConanFile):
  name = "qcdx"
  package_type = "library"
  settings = "os", "arch", "compiler", "build_type"
  languages = ("C", "C++")

  description = "Template project built on ProjectKit"
  license = "MIT"
  author = "Evan R. Reumann (evanrileyreumann@gmail.com)"
  url = "https://github.com/cooldood155/QCDX"

  options = {
    "shared": [True, False],
    "fPIC": [True, False]
  }
  default_options = {
    "shared": False,
    "fPIC": True
  }

  exports_sources = (
    "CMakeLists.txt",
    "cmake/*",
    "include/*",
    "src/*",
    "apps/*",
    "tools/*",
    "tests/*")

  def set_version(self):
    cmake_path = path.join(self.recipe_folder, "CMakeLists.txt")
    content = load(self, cmake_path)

    match = search(r"project\s*\([^)]*VERSION\s+(\d+\.\d+\.\d+)", content,
                   IGNORECASE)
    if match:
      self.version = match.group(1)
    else:
      raise LookupError("Could not find top-level CMake project version.")

  def package_info(self):
    self.cpp_info.set_property("cmake_file_name", "qcdx")
    self.cpp_info.set_property("cmake_target_name", "qcdx::qcdx")
    self.cpp_info.libs = ["qcdx-shared"] if self.options.shared else ["qcdx"]
    if not self.options.shared:
      self.cpp_info.defines.append("QCDX_STATIC_DEFINE")

  def generate(self):
    deps = CMakeDeps(self)
    deps.generate()

    tc = CMakeToolchain(self)
    tc.user_presets_path = False

    build_tests = not self.conf.get(
      "tools.build:skip_test", default=False, check_type=bool)

    tc.variables["QCDX_BUILD_TESTS"] = build_tests
    tc.cache_variables["QCDX_BUILD_TESTS"] = build_tests

    tc.generate()

    save(self, path.join(self.generators_folder, "qcdx_intent.cmake"),
      "set(QCDX_TOOLCHAIN_SHARED {})\n".format(
        "ON" if self.options.get_safe("shared") else "OFF"))

  def build_requirements(self):
    self.test_requires("catch2/[>=3.7.1]")
    self.tool_requires("cmake/[>=3.30]")

  def build(self):
    cmake = CMake(self)
    cmake.configure()
    cmake.build()
    cmake.ctest()

  def config_options(self):
    if self.settings.os == "Windows":
      del self.options.fPIC

  def configure(self):
    if self.options.shared:
      self.options.rm_safe("fPIC")

  def layout(self):
    cmake_layout(self)

  def package(self):
    CMake(self).install()
