# pyright: reportAttributeAccessIssue=false
"""The QCDX kit (ProjectKit) as a Conan package, for projects that do not
vendor it:

    conan create .                                  # from this repository
    tool_requires = "qcdx/[>=0.1 <0.2]"             # in the consuming recipe

    find_package(QCDX REQUIRED)                     # in its CMakeLists.txt
    include(ProjectKit)

Projects made with 'pk new' vendor the kit and do not need this package.
"""

from os import path

from conan import ConanFile
from conan.tools.files import copy, load


class QcdxRecipe(ConanFile):
    name = "qcdx"
    package_type = "build-scripts"
    description = "ProjectKit: CMake modules and scripts for C and C++ projects"
    license = "MIT"
    url = "https://github.com/cooldood155/QCDX"
    homepage = "https://github.com/cooldood155/QCDX"
    topics = ("cmake", "conan", "project-template", "c", "cpp", "build-system")

    exports_sources = ("LICENSE", "cmake/QCDXConfig.cmake", "cmake/QCDXConfigVersion.cmake",
                       "cmake/projectkit/*", "!*/__pycache__/*", "!*.pyc")
    no_copy_source = True
    test_package_folder = "conan/test_package"

    def set_version(self):
        self.version = load(self, path.join(self.recipe_folder, "cmake", "projectkit", "VERSION")).strip()

    def package_id(self):
        self.info.clear()

    def package(self):
        copy(self, "LICENSE", self.source_folder, path.join(self.package_folder, "licenses"))
        copy(self, "QCDXConfig*.cmake", path.join(self.source_folder, "cmake"),
             path.join(self.package_folder, "share", "qcdx", "cmake"))
        copy(self, "*", path.join(self.source_folder, "cmake", "projectkit"),
             path.join(self.package_folder, "share", "qcdx", "cmake", "projectkit"))

    def package_info(self):
        self.cpp_info.includedirs = []
        self.cpp_info.libdirs = []
        self.cpp_info.bindirs = []
        # CMakeToolchain puts builddirs on CMAKE_PREFIX_PATH and CMAKE_MODULE_PATH,
        # so both find_package(QCDX) and a bare include(ProjectKit) work.
        self.cpp_info.builddirs = ["share/qcdx/cmake", "share/qcdx/cmake/projectkit"]
        self.cpp_info.set_property("cmake_find_mode", "none")
