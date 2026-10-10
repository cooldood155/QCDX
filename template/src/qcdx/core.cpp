#include <qcdx/core.hpp>

#ifndef QCDX_VERSION_STRING
#  define QCDX_VERSION_STRING "0.0.0"
#endif

namespace qcdx {

const char* version() noexcept {
    return QCDX_VERSION_STRING;
}

} // namespace qcdx
