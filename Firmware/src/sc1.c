/*
 * SC-1 companion board driver: ATtiny1616 co-processor at 0x2A on the
 * main-board I2C bus (Qwiic J7). Register map: sc1_regs.h.
 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/byteorder.h>

#include "sc1.h"
#include "sc1_regs.h"

LOG_MODULE_REGISTER(sc1, LOG_LEVEL_INF);

static const struct device *const bus = DEVICE_DT_GET(DT_NODELABEL(xiao_i2c));
static bool present;

static int rd(uint8_t reg, uint8_t *buf, size_t len)
{
	/* The co-processor may be asleep: the address match wakes it, so retry once. */
	int err = i2c_write_read(bus, SC1_I2C_ADDR, &reg, 1, buf, len);

	if (err) {
		k_msleep(2);
		err = i2c_write_read(bus, SC1_I2C_ADDR, &reg, 1, buf, len);
	}
	return err;
}

bool sc1_init(void)
{
	uint8_t id[2];

	present = false;
	if (!device_is_ready(bus)) {
		return false;
	}
	if (rd(SC1_REG_ID, id, sizeof(id)) == 0 && id[0] == SC1_ID_VALUE) {
		present = true;
		LOG_INF("SC-1 found, firmware v%u", id[1]);
	} else {
		LOG_INF("SC-1 not fitted");
	}
	return present;
}

bool sc1_present(void)
{
	return present;
}

int sc1_status(uint8_t *status)
{
	return present ? rd(SC1_REG_STATUS, status, 1) : -ENODEV;
}

int sc1_command(uint8_t cmd)
{
	uint8_t buf[2] = { SC1_REG_CMD, cmd };

	if (!present) {
		return -ENODEV;
	}
	int err = i2c_write(bus, buf, sizeof(buf), SC1_I2C_ADDR);

	if (err) {
		k_msleep(2);
		err = i2c_write(bus, buf, sizeof(buf), SC1_I2C_ADDR);
	}
	return err;
}

int sc1_read(struct sc1_data *d)
{
	uint8_t a[16], b[16], st;
	int err;

	if (!present) {
		return -ENODEV;
	}
	/* Two 16-byte reads: the co-processor serves at most 16 bytes per transfer. */
	err = rd(SC1_REG_VBAT_MV, a, sizeof(a));
	if (!err) {
		err = rd(SC1_REG_RAIN_1H, b, sizeof(b));
	}
	if (!err) {
		err = rd(SC1_REG_STATUS, &st, 1);
	}
	if (err) {
		LOG_WRN("SC-1 read failed: %d", err);
		return err;
	}

#define A16(r) sys_get_le16(&a[(r) - SC1_REG_VBAT_MV])
#define B16(r) sys_get_le16(&b[(r) - SC1_REG_RAIN_1H])
	d->vbat_mv = A16(SC1_REG_VBAT_MV);
	d->ibat_ma_x10 = (int16_t)A16(SC1_REG_IBAT);
	d->soc_pct = a[SC1_REG_SOC - SC1_REG_VBAT_MV];
	d->status = st;
	d->temp_cell_cx100 = (int16_t)A16(SC1_REG_TEMP_CELL);
	d->temp_soil_cx100 = (int16_t)A16(SC1_REG_TEMP_SOIL);
	d->soil_pct = a[SC1_REG_SOIL_PCT - SC1_REG_VBAT_MV];
	d->borer_index = a[SC1_REG_BORER_IDX - SC1_REG_VBAT_MV];
	d->rain_1h = B16(SC1_REG_RAIN_1H);
	d->rain_24h = B16(SC1_REG_RAIN_24H);
	d->rain_3d = B16(SC1_REG_RAIN_3D);
	d->rain_5d = B16(SC1_REG_RAIN_5D);
	d->rain_7d = B16(SC1_REG_RAIN_7D);
	d->rain_15d = B16(SC1_REG_RAIN_15D);
#undef A16
#undef B16
	return 0;
}
