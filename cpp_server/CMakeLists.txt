cmake_minimum_required(VERSION 3.14)
project(rbcheck CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Drogon CONFIG REQUIRED)

add_executable(rbcheck
    main.cc
    controllers/TransactionController.cc
    services/SmsParser.cc
    services/BackfillService.cc
)

target_include_directories(rbcheck PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/include   # obfuscate.h
)

# ── Security hardening (all configurations) ──────────────────────────────────
target_compile_options(rbcheck PRIVATE
    -fstack-protector-strong
    -fPIE
    -Wformat
    -Wformat-security
)

# ── Release hardening ─────────────────────────────────────────────────────────
# -fno-rtti is intentionally omitted: Drogon uses dynamic_cast/typeid internally
# and the build fails with it enabled. RTTI must stay on.
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    target_compile_definitions(rbcheck PRIVATE
        NDEBUG            # kills assert() __FILE__ path leaks
        _FORTIFY_SOURCE=2 # bounds-checked libc (requires -O1+)
    )
    target_compile_options(rbcheck PRIVATE
        -O2
        -fvisibility=hidden
        -fvisibility-inlines-hidden
    )
    # Strip local symbols on macOS Mach-O (arm64).
    # strip -x removes locals but keeps exported symbols; for an executable
    # with -fvisibility=hidden there are effectively none left after linking.
    add_custom_command(TARGET rbcheck POST_BUILD
        COMMAND strip -x $<TARGET_FILE:rbcheck>
        COMMENT "Stripping local symbols (Release)"
    )
endif()

# ── O-MVLL control-flow obfuscation (optional, default OFF) ──────────────────
# Install O-MVLL for AArch64/Mach-O and set OMVLL_LIB to the plugin path, then
# reconfigure with -DENABLE_OMVLL=ON. See cpp_server/omvll_config.py.
option(ENABLE_OMVLL "Apply O-MVLL control-flow obfuscation (requires plugin)" OFF)
if(ENABLE_OMVLL)
    if(NOT DEFINED OMVLL_LIB OR NOT EXISTS "${OMVLL_LIB}")
        message(FATAL_ERROR
            "ENABLE_OMVLL=ON but OMVLL_LIB is not set or does not exist.\n"
            "Set -DOMVLL_LIB=/path/to/omvll.dylib.\n"
            "See https://obfuscator.re/omvll for install instructions.")
    endif()
    target_compile_options(rbcheck PRIVATE
        -fpass-plugin=${OMVLL_LIB}
        -mllvm -omvll-config=${CMAKE_CURRENT_SOURCE_DIR}/omvll_config.py
    )
    message(STATUS "O-MVLL enabled: ${OMVLL_LIB}")
endif()

target_link_libraries(rbcheck
    PRIVATE
    Drogon::Drogon
    sqlite3
)
