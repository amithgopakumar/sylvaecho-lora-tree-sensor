#ifndef SYLVAECHO_PAYLOAD_H
#define SYLVAECHO_PAYLOAD_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#include "sc1.h"

enum msg_type {
	MSG_REPORT = 0x01,     /* scheduled biodiversity + climate report */
	MSG_LOGGING = 0x02,    /* confirmed vibration + chainsaw alert */
	MSG_TILT = 0x03,       /* tilt beyond threshold */
	MSG_BOOT = 0x04,
	MSG_SC1_EVENT = 0x05,  /* SC-1 raised rain, low-battery or borer alert */
};

enum msg_flags {
	FLAG_TEMP_OUT_OF_CHARGE_RANGE = 0x01,
	FLAG_SENSOR_FAULT = 0x02,
};

/* Byte 18 of the base report: which extension blocks follow. */
enum ext_flags {
	EXT_SC1 = 0x01,        /* 24-byte SC-1 block at offset 19 */
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

	bool has_sc1;
	struct sc1_data sc1;
};

#define PAYLOAD_BASE_LEN 19
#define PAYLOAD_SC1_LEN  24
#define PAYLOAD_MAX_LEN  (PAYLOAD_BASE_LEN + PAYLOAD_SC1_LEN)

/*
 * Little-endian. 19-byte base report (unchanged from v1, so old gateways still
 * parse it), then the SC-1 block when byte 18 has EXT_SC1 set:
 *   19 u16 vbat_mv        21 s16 ibat 0.1 mA    23 u8 soc %     24 u8 SC-1 status
 *   25 s16 cell 0.01 C    27 s16 soil 0.01 C    29 u8 soil %    30 u8 borer index
 *   31 u16 rain 1 h       33 u16 rain 24 h      35 u16 rain 3 d 37 u16 rain 5 d
 *   39 u16 rain 7 d       41 u16 rain 15 d      (rain in 0.2 mm tips)
 * Returns the length written, 0 if `cap` is too small.
 */
size_t payload_pack(const struct report *r, uint8_t *out, size_t cap);

#endif
