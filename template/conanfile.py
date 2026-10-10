# pyright: reportAttributeAccessIssue=false, reportOptionalCall=false, reportArgumentType=false, reportCallIssue=false

from json import load as json_load
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

  exports = "deps.json"

  exports_sources = (
    "deps.json",
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

  # ---------------------------------------------------------------------------
  # Dependencies (deps.json): CRUD dependencies via 'pk dep add|set|rm|update'.
  # Schema and checks: cmake/projectkit/docs/PK_DEP.md.
  # ---------------------------------------------------------------------------

  _PK_DEP_TRAITS = ("headers", "libs", "run", "visible", "transitive_headers",
                    "transitive_libs", "force", "override")

  def _pk_deps(self):
    deps_json = path.join(self.recipe_folder, "deps.json")
    if not path.isfile(deps_json):
      return {}

    with open(deps_json, encoding="utf-8") as handle:
      data = json_load(handle)
    if data.get("schema") != 1:
      raise ValueError("deps.json: unsupported schema {!r}".format(
        data.get("schema")))

    return data.get("packages", {})

  def requirements(self):
    for name, dep in self._pk_deps().items():
      if dep.get("kind", "requires") != "requires":
        continue

      traits = dep.get("traits", {})
      unknown = sorted(set(traits) - set(self._PK_DEP_TRAITS))
      if unknown:
        raise ValueError("deps.json: '{}' has unknown traits {}".format(
          name, unknown))

      self.requires(dep["ref"], **traits)

  def build_requirements(self):
    for dep in self._pk_deps().values():
      kind = dep.get("kind", "requires")
      if kind == "test":
        self.test_requires(dep["ref"])
      elif kind == "tool":
        self.tool_requires(dep["ref"])

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
    for name, dep in self._pk_deps().items():
      for option, value in dep.get("options", {}).items():
        setattr(self.options[name], option, value)

  def layout(self):
    cmake_layout(self)

  def package(self):
    CMake(self).install()
