cmake_minimum_required(VERSION 3.16)
project(wellhead_simulator CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

FetchContent_Declare(
  paho_mqtt_c
  GIT_REPOSITORY https://github.com/eclipse/paho.mqtt.c.git
  GIT_TAG v1.3.13
)
set(PAHO_WITH_SSL OFF CACHE BOOL "" FORCE)
set(PAHO_BUILD_STATIC ON CACHE BOOL "" FORCE)
set(PAHO_BUILD_SHARED OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(paho_mqtt_c)

add_executable(wellhead_simulator src/main.cpp)
target_link_libraries(wellhead_simulator PRIVATE paho-mqtt3c)
target_include_directories(wellhead_simulator PRIVATE ${paho_mqtt_c_SOURCE_DIR}/src)

if(MSVC)
  target_compile_definitions(wellhead_simulator PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
