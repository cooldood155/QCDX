#include <catch2/catch_test_macros.hpp>

#include <qcdx/core.hpp>

#include <string_view>

TEST_CASE("qcdx reports a version string", "[core]") {
    const std::string_view version{qcdx::version()};
    REQUIRE_FALSE(version.empty());
}
