# SylvaEcho gateway, Zephyr version (XIAO ESP32S3 + Wio-SX1262)
#
# Build:  west build -b xiao_esp32s3/esp32s3/procpu Gateway_zephyr
# Flash:  west flash
#
# Wi-Fi and MQTT settings: copy secrets.conf.example to secrets.conf (git-ignored);
# it is picked up automatically.
cmake_minimum_required(VERSION 3.20.0)

if(EXISTS ${CMAKE_CURRENT_LIST_DIR}/secrets.conf)
  list(APPEND EXTRA_CONF_FILE ${CMAKE_CURRENT_LIST_DIR}/secrets.conf)
endif()

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(sylvaecho_gateway)

# Same decoder as the Arduino gateway, so both always agree on the report format.
set(SHARED ${CMAKE_CURRENT_SOURCE_DIR}/../Gateway/src)
target_include_directories(app PRIVATE ${SHARED})
target_sources(app PRIVATE
    src/main.cpp
    ${SHARED}/decode.cpp
)
