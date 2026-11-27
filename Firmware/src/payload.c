#include "payload.h"

static void put16(uint8_t *p, uint16_t v)
{
	p[0] = (uint8_t)(v & 0xff);
	p[1] = (uint8_t)(v >> 8);
}

size_t payload_pack(const struct report *r, uint8_t *out, size_t cap)
{
	size_t len = PAYLOAD_BASE_LEN + (r->has_sc1 ? PAYLOAD_SC1_LEN : 0);

	if (cap < len) {
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
	out[18] = r->has_sc1 ? EXT_SC1 : 0;

	if (r->has_sc1) {
		const struct sc1_data *s = &r->sc1;
		uint8_t *p = &out[PAYLOAD_BASE_LEN];

		put16(&p[0], s->vbat_mv);
		put16(&p[2], (uint16_t)s->ibat_ma_x10);
		p[4] = s->soc_pct;
		p[5] = s->status;
		put16(&p[6], (uint16_t)s->temp_cell_cx100);
		put16(&p[8], (uint16_t)s->temp_soil_cx100);
		p[10] = s->soil_pct;
		p[11] = s->borer_index;
		put16(&p[12], s->rain_1h);
		put16(&p[14], s->rain_24h);
		put16(&p[16], s->rain_3d);
		put16(&p[18], s->rain_5d);
		put16(&p[20], s->rain_7d);
		put16(&p[22], s->rain_15d);
	}
	return len;
}
