#ifndef SYLVAECHO_SC1_H
#define SYLVAECHO_SC1_H

#include <stdbool.h>
#include <stdint.h>

/* Snapshot of the SC-1 companion board, as carried in the report extension. */
struct sc1_data {
	uint16_t vbat_mv;
	int16_t ibat_ma_x10;     /* + = discharging */
	uint8_t soc_pct;
	uint8_t status;          /* SC1_ST_* bits */
	int16_t temp_cell_cx100; /* SC1_TEMP_INVALID if no probe */
	int16_t temp_soil_cx100;
	uint8_t soil_pct;        /* 0xFF if no probe */
	uint8_t borer_index;
	uint16_t rain_1h;        /* tips, 0.2 mm each */
	uint16_t rain_24h;
	uint16_t rain_3d;
	uint16_t rain_5d;
	uint16_t rain_7d;
	uint16_t rain_15d;
};

/* Probe for the add-on at boot. Everything else is a no-op when it is absent. */
bool sc1_init(void);
bool sc1_present(void);

/* Read the status byte only (cheap; use first after a WAKE_N edge). */
int sc1_status(uint8_t *status);

/* Read all measurements. */
int sc1_read(struct sc1_data *d);

/* Commands: see SC1_CMD_* in sc1_regs.h. */
int sc1_command(uint8_t cmd);

#endif
