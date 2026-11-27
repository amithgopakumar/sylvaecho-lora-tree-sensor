/*
 * Decoder for SylvaEcho node reports (Firmware/src/payload.h).
 * Plain C++ with no Arduino dependency, so it can be unit-tested on a PC.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

struct Sc1Block {
	uint16_t vbat_mv;
	int16_t ibat_ma_x10;
	uint8_t soc_pct;
	uint8_t status;
	int16_t temp_cell_cx100;
	int16_t temp_soil_cx100;
	uint8_t soil_pct;
	uint8_t borer_index;
	uint16_t rain_1h, rain_24h, rain_3d, rain_5d, rain_7d, rain_15d;
};

struct Report {
	uint8_t type;
	uint8_t flags;
	uint16_t node_id;
	uint8_t buzz_index;
	uint8_t bird_score;
	uint8_t saw_score;
	int16_t tilt_x_dx10;
	int16_t tilt_y_dx10;
	int16_t temp_cx100;
	uint8_t rh_pct;
	uint16_t press_hpa_x10;
	uint16_t seq;
	uint8_t ext;
	bool has_sc1;
	Sc1Block sc1;
};

enum : uint8_t {
	MSG_REPORT = 0x01,
	MSG_LOGGING = 0x02,
	MSG_TILT = 0x03,
	MSG_BOOT = 0x04,
	MSG_SC1_EVENT = 0x05,
};

static const int16_t TEMP_INVALID = (int16_t)0x8000;
static const float RAIN_MM_PER_TIP = 0.2f;

/* Returns false for a packet that is not a SylvaEcho report. */
bool decode_report(const uint8_t *p, size_t len, Report *r);

const char *msg_type_name(uint8_t type);

/*
 * Write the report as one JSON object into `out` (no newline). `rssi` and
 * `snr` describe the received packet. Returns the length, or 0 if `cap` is too small.
 */
size_t report_to_json(const Report &r, int rssi, float snr, char *out, size_t cap);
