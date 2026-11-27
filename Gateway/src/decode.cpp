#include "decode.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static uint16_t u16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static int16_t s16(const uint8_t *p) { return (int16_t)u16(p); }

static const size_t BASE_LEN = 19;
static const size_t SC1_LEN = 24;
static const uint8_t EXT_SC1 = 0x01;
static const uint8_t EXT_AUTH = 0x02;
static const size_t AUTH_LEN = 16;
static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

bool decode_report(const uint8_t *p, size_t len, Report *r)
{
	if (len < BASE_LEN || p[0] < MSG_REPORT || p[0] > MSG_SC1_EVENT) {
		return false;
	}
	r->type = p[0];
	r->flags = p[1];
	r->node_id = u16(&p[2]);
	r->buzz_index = p[4];
	r->bird_score = p[5];
	r->saw_score = p[6];
	r->tilt_x_dx10 = s16(&p[7]);
	r->tilt_y_dx10 = s16(&p[9]);
	r->temp_cx100 = s16(&p[11]);
	r->rh_pct = p[13];
	r->press_hpa_x10 = u16(&p[14]);
	r->seq = u16(&p[16]);
	r->ext = p[18];
	r->raw = p;
	r->raw_len = len;
	r->has_auth = (r->ext & EXT_AUTH) && len >= BASE_LEN + AUTH_LEN;
	size_t body = r->has_auth ? len - AUTH_LEN : len;
	if (r->has_auth) {
		r->auth_epoch = u32(&p[body]);
		r->auth_counter = u32(&p[body + 4]);
		memcpy(r->auth_tag, &p[body + 8], 8);
	}
	r->has_sc1 = (r->ext & EXT_SC1) && body >= BASE_LEN + SC1_LEN;

	if (r->has_sc1) {
		const uint8_t *q = &p[BASE_LEN];
		Sc1Block &s = r->sc1;

		s.vbat_mv = u16(&q[0]);
		s.ibat_ma_x10 = s16(&q[2]);
		s.soc_pct = q[4];
		s.status = q[5];
		s.temp_cell_cx100 = s16(&q[6]);
		s.temp_soil_cx100 = s16(&q[8]);
		s.soil_pct = q[10];
		s.borer_index = q[11];
		s.rain_1h = u16(&q[12]);
		s.rain_24h = u16(&q[14]);
		s.rain_3d = u16(&q[16]);
		s.rain_5d = u16(&q[18]);
		s.rain_7d = u16(&q[20]);
		s.rain_15d = u16(&q[22]);
	}
	return true;
}

const char *msg_type_name(uint8_t type)
{
	switch (type) {
	case MSG_REPORT: return "report";
	case MSG_LOGGING: return "logging_alert";
	case MSG_TILT: return "tilt_alert";
	case MSG_BOOT: return "boot";
	case MSG_SC1_EVENT: return "sc1_alert";
	default: return "unknown";
	}
}

/* Small bounded appender: keeps writing after an overflow but reports it. */
struct Out {
	char *buf;
	size_t cap, len;
	bool overflow;

	void add(const char *fmt, ...)
	{
		va_list ap;

		va_start(ap, fmt);
		int n = vsnprintf(buf + len, len < cap ? cap - len : 0, fmt, ap);
		va_end(ap);
		if (n < 0 || len + (size_t)n >= cap) {
			overflow = true;
			len = cap;
		} else {
			len += (size_t)n;
		}
	}
};

static void temp(Out &o, const char *key, int16_t cx100)
{
	if (cx100 == TEMP_INVALID) {
		o.add(",\"%s\":null", key);
	} else {
		o.add(",\"%s\":%.2f", key, cx100 / 100.0);
	}
}

size_t report_to_json(const Report &r, int rssi, float snr, char *out, size_t cap)
{
	Out o{out, cap, 0, false};

	o.add("{\"node\":%u,\"seq\":%u,\"type\":\"%s\"", r.node_id, r.seq, msg_type_name(r.type));
	o.add(",\"rssi\":%d,\"snr\":%.1f", rssi, snr);
	o.add(",\"flags\":{\"charge_temp\":%s,\"sensor_fault\":%s}",
	      (r.flags & 0x01) ? "true" : "false", (r.flags & 0x02) ? "true" : "false");
	o.add(",\"buzz\":%u,\"bird\":%u,\"saw\":%u", r.buzz_index, r.bird_score, r.saw_score);
	o.add(",\"tilt_x\":%.1f,\"tilt_y\":%.1f", r.tilt_x_dx10 / 10.0, r.tilt_y_dx10 / 10.0);
	o.add(",\"temp_c\":%.2f,\"rh\":%u,\"press_hpa\":%.1f", r.temp_cx100 / 100.0, r.rh_pct,
	      r.press_hpa_x10 / 10.0);

	if (r.has_sc1) {
		const Sc1Block &s = r.sc1;

		o.add(",\"sc1\":{\"vbat_v\":%.3f,\"ibat_ma\":%.1f,\"soc\":%u,\"status\":%u",
		      s.vbat_mv / 1000.0, s.ibat_ma_x10 / 10.0, s.soc_pct, s.status);
		temp(o, "cell_c", s.temp_cell_cx100);
		temp(o, "soil_c", s.temp_soil_cx100);
		if (s.soil_pct == 0xFF) {
			o.add(",\"soil_pct\":null");
		} else {
			o.add(",\"soil_pct\":%u", s.soil_pct);
		}
		o.add(",\"borer\":%u", s.borer_index);
		o.add(",\"rain_mm\":{\"1h\":%.1f,\"24h\":%.1f,\"3d\":%.1f,\"5d\":%.1f,\"7d\":%.1f,\"15d\":%.1f}",
		      s.rain_1h * RAIN_MM_PER_TIP, s.rain_24h * RAIN_MM_PER_TIP, s.rain_3d * RAIN_MM_PER_TIP,
		      s.rain_5d * RAIN_MM_PER_TIP, s.rain_7d * RAIN_MM_PER_TIP, s.rain_15d * RAIN_MM_PER_TIP);
		o.add(",\"alerts\":{\"rain\":%s,\"low_batt\":%s,\"borer\":%s}}",
		      (s.status & 0x02) ? "true" : "false", (s.status & 0x04) ? "true" : "false",
		      (s.status & 0x08) ? "true" : "false");
	}
	if (r.has_auth) {
		o.add(",\"auth\":{\"epoch\":%lu,\"counter\":%lu}", (unsigned long)r.auth_epoch,
		      (unsigned long)r.auth_counter);
	}
	if (r.raw && r.raw_len) {
		o.add(",\"raw\":\"");
		for (size_t i = 0; i < r.raw_len; i++) {
			o.add("%02x", r.raw[i]);
		}
		o.add("\"");
	}
	o.add("}");
	return o.overflow ? 0 : o.len;
}
