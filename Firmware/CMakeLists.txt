# SylvaEcho firmware (Zephyr / nRF Connect SDK)
# Build:  west build -b xiao_ble/nrf52840 Firmware                       (rev 0.4, BME680)
#         west build -b xiao_ble/nrf52840 Firmware -- -DSENSOR=bme280      (rev 0.3, BME280)
cmake_minimum_required(VERSION 3.20.0)

# Environment sensor variant: bme680 (board rev 0.4, default) or bme280 (board rev 0.3)
set(SENSOR bme680 CACHE STRING "Environment sensor: bme680 or bme280")
set_property(CACHE SENSOR PROPERTY STRINGS bme680 bme280)
if(NOT SENSOR MATCHES "^(bme680|bme280)$")
  message(FATAL_ERROR "SENSOR must be bme680 or bme280, got '${SENSOR}'")
endif()
list(APPEND EXTRA_DTC_OVERLAY_FILE ${CMAKE_CURRENT_SOURCE_DIR}/variants/${SENSOR}.overlay)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(sylvaecho)

target_sources(app PRIVATE
    src/main.c
    src/audio.c
    src/features.c
    src/payload.c
    src/sc1.c
)
