#include "payload.h"

#define PAYLOAD_LEN 19

static void put16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)(v & 0xff);
	p[1] = (uint8_t)(v >> 8);
}

size_t payload_pack(const struct report *r, uint8_t *out, size_t cap)
{
	if (cap < PAYLOAD_LEN) {
		return 0;
	}
	out[0] = r->type;
	out[1] = r->flags;
	put16(&out[2], r->node_id);
	out[4] = r->buzz_index;
	out[5] = r->bird_score;
	out[6] = r->saw_score;
	put16(&out[7], (uint16_t)r->tilt_x_dx10);
	put16(&out[9], (uint16_t)r->tilt_y_dx10);
	put16(&out[11], (uint16_t)r->temp_cx100);
	out[13] = r->rh_pct;
	put16(&out[14], r->press_hpa_x10);
	put16(&out[16], r->seq);
	out[18] = 0; /* reserved */
	return PAYLOAD_LEN;
}
