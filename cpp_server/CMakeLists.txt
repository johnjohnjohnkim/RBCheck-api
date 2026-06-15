cmake_minimum_required(VERSION 3.14)
project(rbcheck CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Drogon CONFIG REQUIRED)
find_package(SQLite3 REQUIRED)

add_executable(rbcheck
    main.cc
    controllers/TransactionController.cc
    services/SmsParser.cc
    services/BackfillService.cc
)

target_include_directories(rbcheck PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

target_link_libraries(rbcheck
    PRIVATE
    Drogon::Drogon
    SQLite::SQLite3
)
