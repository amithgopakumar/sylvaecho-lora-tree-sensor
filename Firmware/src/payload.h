#ifndef SYLVAECHO_PAYLOAD_H
#define SYLVAECHO_PAYLOAD_H

#include <stdint.h>
#include <stddef.h>

enum msg_type {
	MSG_REPORT = 0x01,     /* scheduled biodiversity + climate report */
	MSG_LOGGING = 0x02,    /* confirmed vibration + chainsaw alert */
	MSG_TILT = 0x03,       /* tilt beyond threshold */
	MSG_BOOT = 0x04,
};

enum msg_flags {
	FLAG_TEMP_OUT_OF_CHARGE_RANGE = 0x01,
	FLAG_SENSOR_FAULT = 0x02,
};

struct report {
	uint8_t type;
	uint8_t flags;
	uint16_t node_id;
	uint8_t buzz_index;     /* 0-100 */
	uint8_t bird_score;     /* 0-100 */
	uint8_t saw_score;      /* 0-100 */
	int16_t tilt_x_dx10;    /* degrees x10 from baseline */
	int16_t tilt_y_dx10;
	int16_t temp_cx100;     /* degC x100 */
	uint8_t rh_pct;
	uint16_t press_hpa_x10;
	uint16_t seq;
};

/* Little-endian, 19 bytes. Returns length written. */
size_t payload_pack(const struct report *r, uint8_t *out, size_t cap);

#endif
