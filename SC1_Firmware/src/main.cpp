/*
 * SylvaEcho SC-1 companion board firmware (ATtiny1616, megaTinyCore)
 *
 * The co-processor sleeps in power-down most of the time. It wakes on:
 *   - the RTC periodic interrupt (1 s): time keeping, scheduled sampling
 *   - a rain-gauge tip on PA2 (fully asynchronous pin)
 *   - its own I2C address on the main bus (TWI slave address match)
 *
 * Pin map (SC-1 v0.2 schematic)
 *   PA2  RAIN       reed switch to GND, 1M pull-up, 10 nF
 *   PA3  NTC_CELL   AIN3, 10k NTC to GND, 10k to NTC_PWR
 *   PA4  NTC_SOIL   AIN4, same divider
 *   PA5  SOIL_ADC   AIN5, capacitive soil probe output
 *   PA6  PZ_ADC     AIN6, piezo amplifier output (mid-rail biased)
 *   PA7  WAKE_OUT   open-drain pulse to the main-board WAKE_N (optional TP1 wire)
 *   PB5  SNS_PWR    INA219 supply and its I2C pull-ups
 *   PB4  SOIL_PWR   soil probe supply
 *   PB3  NTC_PWR    NTC divider supply
 *   PB2  AMP_PWR    MCP6001 amplifier supply
 *   PB1  SDA, PB0 SCL   main I2C bus (slave 0x2A)
 *   PC0  ISDA, PC1 ISCL private bit-banged I2C to the INA219 (0x40)
 *   PC2  LED
 *   PA0  UPDI
 */
#include <Arduino.h>
#include <Wire.h>
#include <avr/eeprom.h>
#include <avr/sleep.h>
#include <util/atomic.h>
#include <math.h>
#include <string.h>

#include "sc1_regs.h"

/* ------------------------------------------------------------- pins */
#define P_RAIN      PIN_PA2
#define P_NTC_CELL  PIN_PA3
#define P_NTC_SOIL  PIN_PA4
#define P_SOIL      PIN_PA5
#define P_PZ        PIN_PA6
#define P_WAKE      PIN_PA7
#define P_SNS_PWR   PIN_PB5
#define P_SOIL_PWR  PIN_PB4
#define P_NTC_PWR   PIN_PB3
#define P_AMP_PWR   PIN_PB2
#define P_ISDA      PIN_PC0
#define P_ISCL      PIN_PC1
#define P_LED       PIN_PC2

/* ---------------------------------------------------- battery model */
#define SHUNT_MOHM          220     /* R1 0.22 ohm */
#define INA219_ADDR         0x40
#define VBAT_LOW_MV         3000
#define VBAT_FULL_MV        3550    /* LiFePO4 at the end of charge */
#define I_TAPER_MA_X10      (-50)   /* charging current below 5 mA at full voltage */
#define REST_MA_X10         20      /* |I| under 2 mA counts as resting */
#define REST_FOR_OCV_S      1800    /* rest this long before trusting the OCV */

/* --------------------------------------------------- borer listening */
#define PZ_RATE_HZ          8000
#define PZ_FRAME            32      /* 4 ms frames */
#define CLICK_RATIO         8       /* frame energy over noise floor */
#define CLICK_MIN_ENERGY    400     /* absolute floor, ADC counts^2 x frame */
#define CLICK_REFRACT       5       /* frames (20 ms) */

/* ------------------------------------------------------------ state */
static volatile uint8_t regs[SC1_REG_COUNT];
static volatile uint8_t reg_ptr;
static volatile uint8_t pending_cmd;
static volatile uint32_t seconds;
static volatile uint16_t rain_pending;
static volatile uint16_t last_tip_tick;

struct config {
	uint16_t magic;
	uint8_t bytes[SC1_REG_COUNT - SC1_CONFIG_FIRST];
};
#define CONFIG_MAGIC 0x5C01
static struct config EEMEM ee_config;

/* Rain history: 6 ten-minute bins for the last hour, 360 hourly bins for 15 days. */
static uint16_t rain_10m[6];
static uint16_t rain_hour[360];
static uint8_t rain_10m_idx;
static uint16_t rain_hour_idx;
static bool rain_alert_sent;

static int32_t used_mas;            /* charge drawn since full, mA*s (x10 scale below) */
static uint32_t rest_since;
static uint32_t next_batt, next_field;
static uint8_t status;

/* --------------------------------------------------- register helpers */
static uint16_t rd16(uint8_t r) { return regs[r] | ((uint16_t)regs[r + 1] << 8); }
static void wr16(uint8_t r, uint16_t v) { regs[r] = v & 0xff; regs[r + 1] = v >> 8; }
static void wr32(uint8_t r, uint32_t v)
{
	for (uint8_t i = 0; i < 4; i++) {
		regs[r + i] = (v >> (8 * i)) & 0xff;
	}
}

static void config_defaults(void)
{
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		wr16(SC1_REG_CAPACITY, 1000);
		wr16(SC1_REG_BATT_PERIOD, 60);
		wr16(SC1_REG_FIELD_PERIOD, 1800);
		wr16(SC1_REG_SOIL_DRY, 2730);
		wr16(SC1_REG_SOIL_WET, 1240);
		wr16(SC1_REG_RAIN_ALERT, 50);
		regs[SC1_REG_LOW_BATT] = 15;
		regs[SC1_REG_BORER_ALERT] = 50;
		regs[SC1_REG_LISTEN_S] = 20;
		regs[SC1_REG_WAKE_MASK] = SC1_ST_RAIN_ALERT | SC1_ST_LOW_BATT | SC1_ST_BORER_ALERT;
	}
}

static void config_load(void)
{
	struct config c;

	eeprom_read_block(&c, &ee_config, sizeof(c));
	if (c.magic != CONFIG_MAGIC) {
		config_defaults();
		return;
	}
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		for (uint8_t i = 0; i < sizeof(c.bytes); i++) {
			regs[SC1_CONFIG_FIRST + i] = c.bytes[i];
		}
	}
}

static void config_save(void)
{
	struct config c;

	c.magic = CONFIG_MAGIC;
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		for (uint8_t i = 0; i < sizeof(c.bytes); i++) {
			c.bytes[i] = regs[SC1_CONFIG_FIRST + i];
		}
	}
	eeprom_update_block(&c, &ee_config, sizeof(c));
}

/* Publish STATUS and pulse WAKE for newly raised bits that are in the wake mask. */
static void set_status(uint8_t bits)
{
	uint8_t raised;

	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		raised = bits & ~regs[SC1_REG_STATUS];
		regs[SC1_REG_STATUS] |= bits;
		status = regs[SC1_REG_STATUS];
	}
	if (raised & regs[SC1_REG_WAKE_MASK]) {
		/* Open-drain: drive low for 2 ms, then release. Never drive high. */
		digitalWrite(P_WAKE, LOW);
		pinMode(P_WAKE, OUTPUT);
		delay(2);
		pinMode(P_WAKE, INPUT);
	}
}

static void clr_status(uint8_t bits)
{
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		regs[SC1_REG_STATUS] &= ~bits;
		status = regs[SC1_REG_STATUS];
	}
}

/* ------------------------------------------------- I2C slave (main bus) */
static void on_receive(int n)
{
	if (n < 1) {
		return;
	}
	reg_ptr = Wire.read() % SC1_REG_COUNT;
	while (Wire.available()) {
		uint8_t v = Wire.read();

		if (reg_ptr == SC1_REG_CMD) {
			pending_cmd = v;
		} else if (reg_ptr >= SC1_CONFIG_FIRST) {
			regs[reg_ptr] = v;
		}
		reg_ptr = (reg_ptr + 1) % SC1_REG_COUNT;
	}
}

static void on_request(void)
{
	uint8_t n = SC1_REG_COUNT - reg_ptr;

	if (n > 16) {
		n = 16;
	}
	for (uint8_t i = 0; i < n; i++) {
		Wire.write(regs[reg_ptr + i]);
	}
}

/* ------------------------------------------------ bit-banged I2C (INA219) */
static void i_sda(bool high) { pinMode(P_ISDA, high ? INPUT : OUTPUT); }
static void i_scl(bool high) { pinMode(P_ISCL, high ? INPUT : OUTPUT); delayMicroseconds(5); }

static void i_start(void) { i_sda(true); i_scl(true); i_sda(false); delayMicroseconds(5); i_scl(false); }
static void i_stop(void) { i_sda(false); i_scl(true); i_sda(true); delayMicroseconds(5); }

static bool i_write(uint8_t b)
{
	for (uint8_t m = 0x80; m; m >>= 1) {
		i_sda(b & m);
		i_scl(true);
		i_scl(false);
	}
	i_sda(true);
	i_scl(true);
	bool ack = digitalRead(P_ISDA) == LOW;
	i_scl(false);
	return ack;
}

static uint8_t i_read(bool ack)
{
	uint8_t b = 0;

	i_sda(true);
	for (uint8_t i = 0; i < 8; i++) {
		i_scl(true);
		b = (b << 1) | (digitalRead(P_ISDA) == HIGH);
		i_scl(false);
	}
	i_sda(!ack);
	i_scl(true);
	i_scl(false);
	i_sda(true);
	return b;
}

static bool ina_write(uint8_t reg, uint16_t v)
{
	i_start();
	bool ok = i_write(INA219_ADDR << 1) && i_write(reg) && i_write(v >> 8) && i_write(v & 0xff);
	i_stop();
	return ok;
}

static bool ina_read(uint8_t reg, uint16_t *v)
{
	i_start();
	bool ok = i_write(INA219_ADDR << 1) && i_write(reg);
	i_stop();
	if (!ok) {
		return false;
	}
	i_start();
	ok = i_write((INA219_ADDR << 1) | 1);
	if (ok) {
		uint8_t hi = i_read(true);
		uint8_t lo = i_read(false);

		*v = ((uint16_t)hi << 8) | lo;
	}
	i_stop();
	return ok;
}

/* Power the INA219 for one triggered conversion. Both pins are pulled up to SNS_PWR,
 * so they stay as inputs (low output latch) while the sensor is off: no back-powering. */
static bool ina_measure(int16_t *shunt_10uv, uint16_t *bus_mv)
{
	uint16_t bus = 0, sh = 0;
	bool ok;

	digitalWrite(P_SNS_PWR, HIGH);
	delay(2);
	/* 16 V range, PGA /1 (+-40 mV), bus 12-bit, shunt 12-bit x128 average, shunt+bus triggered */
	ok = ina_write(0x00, 0x01FB);
	if (ok) {
		delay(75);
		for (uint8_t i = 0; i < 10 && ok; i++) {
			ok = ina_read(0x02, &bus);
			if (bus & 0x0002) {
				break;
			}
			delay(5);
		}
		ok = ok && ina_read(0x01, &sh);
	}
	digitalWrite(P_SNS_PWR, LOW);
	pinMode(P_ISDA, INPUT);
	pinMode(P_ISCL, INPUT);
	*shunt_10uv = (int16_t)sh;
	*bus_mv = (bus >> 3) * 4;
	return ok;
}

/* -------------------------------------------------------------- ADC */
static uint16_t adc12(uint8_t pin)
{
	uint16_t sum = 0;

	analogRead(pin); /* discard: the mux just moved */
	for (uint8_t i = 0; i < 16; i++) {
		sum += analogRead(pin); /* 10-bit */
	}
	return sum >> 2; /* 16 x 10-bit -> 12-bit */
}

static int16_t ntc_cx100(uint16_t raw)
{
	/* 10k pull-up to NTC_PWR, 10k B3950 NTC to GND, ratiometric to VDD. */
	if (raw < 40 || raw > 4055) {
		return SC1_TEMP_INVALID;
	}
	float r = 10000.0f * raw / (4095.0f - raw);
	float t = 1.0f / (1.0f / 298.15f + logf(r / 10000.0f) / 3950.0f) - 273.15f;

	return (int16_t)(t * 100.0f);
}

/* ------------------------------------------------------- measurements */
static const struct { uint16_t mv; uint8_t pct; } ocv[] = {
	/* LiFePO4 rested open-circuit voltage. Only trusted near the ends of the flat plateau. */
	{ 2900, 0 }, { 3100, 5 }, { 3200, 10 }, { 3220, 20 }, { 3250, 30 }, { 3270, 40 },
	{ 3280, 50 }, { 3290, 60 }, { 3300, 70 }, { 3320, 80 }, { 3340, 90 }, { 3400, 100 },
};

static uint8_t ocv_soc(uint16_t mv)
{
	if (mv <= ocv[0].mv) {
		return 0;
	}
	for (uint8_t i = 1; i < sizeof(ocv) / sizeof(ocv[0]); i++) {
		if (mv <= ocv[i].mv) {
			uint16_t span = ocv[i].mv - ocv[i - 1].mv;

			return ocv[i - 1].pct + (uint32_t)(mv - ocv[i - 1].mv) * (ocv[i].pct - ocv[i - 1].pct) / span;
		}
	}
	return 100;
}

static void sample_battery(uint16_t dt_s)
{
	int16_t sh;
	uint16_t mv;

	if (!ina_measure(&sh, &mv)) {
		set_status(SC1_ST_INA_FAULT);
		return;
	}
	clr_status(SC1_ST_INA_FAULT);

	/* I = V_shunt / R: 10 uV per LSB over 0.22 ohm = 45.45 uA per LSB. In 0.1 mA: x 0.4545. */
	int16_t i_x10 = (int16_t)((int32_t)sh * 10000 / (SHUNT_MOHM * 100));
	int32_t cap_mas = (int32_t)rd16(SC1_REG_CAPACITY) * 3600;

	/* Coulomb count in 0.1 mA*s, assuming the current held for the whole interval. */
	used_mas += (int32_t)i_x10 * dt_s;
	if (used_mas < 0) {
		used_mas = 0;
	}
	if (used_mas > cap_mas * 10) {
		used_mas = cap_mas * 10;
	}
	if (mv >= VBAT_FULL_MV && i_x10 < 0 && i_x10 > I_TAPER_MA_X10) {
		used_mas = 0; /* charge has tapered at full voltage */
	}

	uint32_t now = seconds;

	if (i_x10 > REST_MA_X10 || i_x10 < -REST_MA_X10) {
		rest_since = now;
	} else if (now - rest_since >= REST_FOR_OCV_S) {
		uint8_t o = ocv_soc(mv);

		if (o <= 20 || o >= 90) {
			used_mas = (int32_t)(100 - o) * cap_mas / 10; /* x10 scale, /100 percent */
		}
	}

	int32_t soc = 100 - used_mas / (cap_mas / 10);

	if (soc < 0) {
		soc = 0;
	}
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		wr16(SC1_REG_VBAT_MV, mv);
		wr16(SC1_REG_IBAT, (uint16_t)i_x10);
		regs[SC1_REG_SOC] = (uint8_t)soc;
		wr32(SC1_REG_USED_MAH, (uint32_t)(used_mas / 360)); /* 0.1 mA*s -> 0.01 mAh */
	}
	if (soc <= regs[SC1_REG_LOW_BATT] || mv < VBAT_LOW_MV) {
		set_status(SC1_ST_LOW_BATT | SC1_ST_NEW_DATA);
	} else {
		clr_status(SC1_ST_LOW_BATT);
		set_status(SC1_ST_NEW_DATA);
	}
}

static void sample_field(void)
{
	/* NTC dividers: 10k x 100 nF settles in ~5 ms. */
	digitalWrite(P_NTC_PWR, HIGH);
	delay(10);
	int16_t t_cell = ntc_cx100(adc12(P_NTC_CELL));
	int16_t t_soil = ntc_cx100(adc12(P_NTC_SOIL));

	digitalWrite(P_NTC_PWR, LOW);

	/* Capacitive soil probe: about 5 mA for ~100 ms. */
	digitalWrite(P_SOIL_PWR, HIGH);
	delay(100);
	uint16_t soil = adc12(P_SOIL);

	digitalWrite(P_SOIL_PWR, LOW);

	uint16_t dry = rd16(SC1_REG_SOIL_DRY), wet = rd16(SC1_REG_SOIL_WET);
	uint8_t pct = 0xFF;

	/* A missing probe reads near 0 (R6/C8 to GND). */
	if (soil > 200 && dry > wet) {
		int32_t p = (int32_t)(dry - (int32_t)soil) * 100 / (dry - wet);

		pct = (uint8_t)(p < 0 ? 0 : (p > 100 ? 100 : p));
	}
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		wr16(SC1_REG_TEMP_CELL, (uint16_t)t_cell);
		wr16(SC1_REG_TEMP_SOIL, (uint16_t)t_soil);
		wr16(SC1_REG_SOIL_RAW, soil);
		regs[SC1_REG_SOIL_PCT] = pct;
	}
	set_status(SC1_ST_NEW_DATA);
}

/*
 * Borer listening: count short impulsive events ("clicks") in the 0.5-3.4 kHz band
 * from the trunk piezo. Larval feeding gives trains of clicks; wind and rain give
 * steady broadband energy that the adaptive noise floor absorbs.
 * The thresholds are placeholders until recordings from infested and healthy palms
 * are available.
 */
static void borer_listen(void)
{
	uint8_t secs = regs[SC1_REG_LISTEN_S];
	uint32_t frames = (uint32_t)secs * (PZ_RATE_HZ / PZ_FRAME);
	uint32_t floor_e = 0;
	uint16_t clicks = 0;
	uint8_t refract = 0;
	int32_t mean = 512L << 6; /* mid-rail, x64 */

	set_status(SC1_ST_LISTENING);
	digitalWrite(P_AMP_PWR, HIGH);
	delay(300); /* bias network and high-pass settle */
	analogRead(P_PZ);

	uint32_t t = micros();

	for (uint32_t f = 0; f < frames; f++) {
		uint32_t e = 0;

		for (uint8_t s = 0; s < PZ_FRAME; s++) {
			while ((uint32_t)(micros() - t) < (1000000UL / PZ_RATE_HZ)) {
			}
			t += 1000000UL / PZ_RATE_HZ;
			int16_t x = analogRead(P_PZ);

			mean += x - (mean >> 6);
			int16_t d = x - (int16_t)(mean >> 6);

			e += (int32_t)d * d;
		}
		if (floor_e == 0) {
			floor_e = e + 1;
		}
		if (refract) {
			refract--;
		} else if (e > floor_e * CLICK_RATIO && e > CLICK_MIN_ENERGY) {
			clicks++;
			refract = CLICK_REFRACT;
			continue; /* keep clicks out of the noise floor */
		}
		floor_e += ((int32_t)e - (int32_t)floor_e) / 64;
		if (floor_e < 1) {
			floor_e = 1;
		}
	}
	digitalWrite(P_AMP_PWR, LOW);

	uint16_t cpm = secs ? (uint32_t)clicks * 60 / secs : 0;
	uint8_t idx = cpm / 10 > 100 ? 100 : cpm / 10;

	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		wr16(SC1_REG_BORER_CPM, cpm);
		regs[SC1_REG_BORER_IDX] = idx;
	}
	clr_status(SC1_ST_LISTENING);
	set_status(idx >= regs[SC1_REG_BORER_ALERT] ? (SC1_ST_BORER_ALERT | SC1_ST_NEW_DATA)
						     : SC1_ST_NEW_DATA);
}

/* --------------------------------------------------------------- rain */
static uint16_t sum_hours(uint16_t n)
{
	uint32_t s = 0;

	for (uint16_t i = 0; i < n; i++) {
		s += rain_hour[(rain_hour_idx + 360 - i) % 360];
	}
	return s > 0xFFFF ? 0xFFFF : (uint16_t)s;
}

static void rain_update(uint32_t now)
{
	static uint32_t last_10m = 0, last_hour = 0;
	uint16_t tips;

	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		tips = rain_pending;
		rain_pending = 0;
	}
	while (now - last_10m >= 600) {
		last_10m += 600;
		rain_10m_idx = (rain_10m_idx + 1) % 6;
		rain_10m[rain_10m_idx] = 0;
	}
	while (now - last_hour >= 3600) {
		last_hour += 3600;
		rain_hour_idx = (rain_hour_idx + 1) % 360;
		rain_hour[rain_hour_idx] = 0;
	}
	if (tips) {
		rain_10m[rain_10m_idx] += tips;
		rain_hour[rain_hour_idx] += tips;
		set_status(SC1_ST_RAIN_TIP);
	}

	uint16_t h1 = 0;

	for (uint8_t i = 0; i < 6; i++) {
		h1 += rain_10m[i];
	}
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		wr16(SC1_REG_RAIN_1H, h1);
		wr16(SC1_REG_RAIN_24H, sum_hours(24));
		wr16(SC1_REG_RAIN_3D, sum_hours(72));
		wr16(SC1_REG_RAIN_5D, sum_hours(120));
		wr16(SC1_REG_RAIN_7D, sum_hours(168));
		wr16(SC1_REG_RAIN_15D, sum_hours(360));
	}
	uint16_t limit = rd16(SC1_REG_RAIN_ALERT);

	if (limit && h1 >= limit) {
		if (!rain_alert_sent) {
			set_status(SC1_ST_RAIN_ALERT);
			rain_alert_sent = true;
		}
	} else if (h1 < limit / 2) {
		rain_alert_sent = false; /* hysteresis: re-arm once the rate halves */
	}
}

/* ------------------------------------------------- interrupts & clocks */
ISR(RTC_PIT_vect)
{
	RTC.PITINTFLAGS = RTC_PI_bm;
	seconds++;
}

ISR(PORTA_PORT_vect)
{
	uint8_t f = PORTA.INTFLAGS;

	PORTA.INTFLAGS = f;
	if (f & PIN2_bm) {
		uint16_t now = RTC.CNT;

		/* Reed switches bounce: ignore edges within ~100 ms (RTC at 1.024 kHz). */
		if ((uint16_t)(now - last_tip_tick) > 100) {
			rain_pending++;
		}
		last_tip_tick = now;
	}
}

static void rtc_init(void)
{
	while (RTC.STATUS > 0) {
	}
	RTC.CLKSEL = RTC_CLKSEL_INT1K_gc;  /* 1.024 kHz from the 32 kHz ULP oscillator */
	RTC.PER = 0xFFFF;
	RTC.CTRLA = RTC_PRESCALER_DIV1_gc | RTC_RTCEN_bm | RTC_RUNSTDBY_bm;
	while (RTC.PITSTATUS > 0) {
	}
	RTC.PITINTCTRL = RTC_PI_bm;
	RTC.PITCTRLA = RTC_PERIOD_CYC1024_gc | RTC_PITEN_bm; /* 1 Hz */
}

/* -------------------------------------------------------- setup/loop */
void setup(void)
{
	const uint8_t outs[] = { P_SNS_PWR, P_SOIL_PWR, P_NTC_PWR, P_AMP_PWR, P_LED };

	for (uint8_t i = 0; i < sizeof(outs); i++) {
		digitalWrite(outs[i], LOW);
		pinMode(outs[i], OUTPUT);
	}
	pinMode(P_WAKE, INPUT);       /* released; output latch stays low */
	pinMode(P_ISDA, INPUT);
	pinMode(P_ISCL, INPUT);
	digitalWrite(P_ISDA, LOW);    /* open-drain emulation: OUT=0, toggle DIR */
	digitalWrite(P_ISCL, LOW);
	pinMode(P_RAIN, INPUT);       /* R7 is the pull-up */
	PORTA.PIN2CTRL = PORT_ISC_FALLING_gc; /* PA2 is fully asynchronous: wakes from power-down */

	/* Unused pins (PA1, PC3): input with pull-up so they do not float. */
	pinMode(PIN_PA1, INPUT_PULLUP);
	pinMode(PIN_PC3, INPUT_PULLUP);

	analogReference(VDD);
	regs[SC1_REG_ID] = SC1_ID_VALUE;
	regs[SC1_REG_FW] = SC1_FW_VERSION;
	wr16(SC1_REG_TEMP_CELL, (uint16_t)SC1_TEMP_INVALID);
	wr16(SC1_REG_TEMP_SOIL, (uint16_t)SC1_TEMP_INVALID);
	regs[SC1_REG_SOIL_PCT] = 0xFF;
	regs[SC1_REG_SOC] = 100;      /* until the first full/OCV correction */
	config_load();

	rtc_init();
	Wire.begin(SC1_I2C_ADDR);
	Wire.onReceive(on_receive);
	Wire.onRequest(on_request);

	digitalWrite(P_LED, HIGH);
	delay(100);
	digitalWrite(P_LED, LOW);

	sample_battery(0);
	sample_field();
	next_batt = rd16(SC1_REG_BATT_PERIOD);
	next_field = rd16(SC1_REG_FIELD_PERIOD);
	set_sleep_mode(SLEEP_MODE_PWR_DOWN);
}

void loop(void)
{
	static uint32_t last_batt = 0;
	uint32_t now;
	uint8_t cmd;

	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		now = seconds;
		cmd = pending_cmd;
		pending_cmd = 0;
	}
	wr32(SC1_REG_UPTIME, now);

	switch (cmd) {
	case SC1_CMD_MEASURE:
		sample_battery(now - last_batt);
		last_batt = now;
		sample_field();
		break;
	case SC1_CMD_CLEAR:
		clr_status(SC1_ST_EVENTS);
		break;
	case SC1_CMD_BATT_FULL:
		used_mas = 0;
		regs[SC1_REG_SOC] = 100;
		break;
	case SC1_CMD_LISTEN:
		borer_listen();
		break;
	case SC1_CMD_SAVE:
		config_save();
		break;
	case SC1_CMD_DEFAULTS:
		config_defaults();
		break;
	default:
		break;
	}

	rain_update(now);

	if (now >= next_batt) {
		sample_battery(now - last_batt);
		last_batt = now;
		next_batt = now + max(rd16(SC1_REG_BATT_PERIOD), (uint16_t)10);
	}
	if (now >= next_field) {
		sample_field();
		next_field = now + max(rd16(SC1_REG_FIELD_PERIOD), (uint16_t)60);
	}

	/* Stay awake while an I2C transaction may still be in progress. */
	delay(3);
	if (TWI0.SSTATUS & (TWI_CLKHOLD_bm | TWI_APIF_bm | TWI_DIF_bm)) {
		return;
	}
	if (pending_cmd) {
		return;
	}
	sleep_enable();
	sleep_cpu();
	sleep_disable();
}
