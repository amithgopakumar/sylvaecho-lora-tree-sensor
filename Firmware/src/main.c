/*
 * SylvaEcho: solar LoRa tree sensor
 *
 * Two triggers:
 *   - timer: every BIO_INTERVAL_S, record BIO_LISTEN_S of audio and report
 *     pollinator / bird activity, tilt and climate
 *   - WAKE_N: the piezo comparator (or IMU INT1) saw trunk vibration;
 *     confirm with trunk vibration RMS and LOGGING_CHECK_CLIPS of audio,
 *     and send a priority alert only when both agree
 */
#include <math.h>
#include <stdlib.h>
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/lora.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

#include "audio.h"
#include "config.h"
#include "features.h"
#include "payload.h"

LOG_MODULE_REGISTER(sylvaecho, LOG_LEVEL_INF);

#define USER DT_PATH(zephyr_user)

static const struct gpio_dt_spec wake = GPIO_DT_SPEC_GET(USER, wake_gpios);
static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(USER, led_gpios);
static const struct device *const exp = DEVICE_DT_GET(DT_NODELABEL(exp));

static const struct device *const lora = DEVICE_DT_GET(DT_ALIAS(lora0));
static const struct device *const imu = DEVICE_DT_GET(DT_ALIAS(imu0));
static const struct device *const env = DEVICE_DT_GET(DT_ALIAS(env0));

static K_SEM_DEFINE(wake_sem, 0, 1);
static struct gpio_callback wake_cb;
static uint16_t seq;
static float base_pitch, base_roll;

static void on_wake(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
	k_sem_give(&wake_sem);
}

/* ---------------------------------------------------------------- LoRa */

static int radio_send(const struct report *r, int8_t dbm)
{
	struct lora_modem_config c = {
		.frequency = LORA_FREQ_HZ,
		.bandwidth = LORA_BW,
		.datarate = LORA_SF,
		.coding_rate = LORA_CR,
		.preamble_len = 8,
		.tx_power = dbm,
		.tx = true,
	};
	uint8_t buf[32];
	size_t len = payload_pack(r, buf, sizeof(buf));
	int err = lora_config(lora, &c);

	if (err == 0) {
		err = lora_send(lora, buf, len);
	}
	LOG_INF("tx type %u seq %u len %u err %d", r->type, r->seq, len, err);
	return err;
}

/* ----------------------------------------------------------- Sensors */

static int read_tilt(float *pitch, float *roll)
{
	struct sensor_value a[3];

	if (sensor_sample_fetch_chan(imu, SENSOR_CHAN_ACCEL_XYZ) ||
	    sensor_channel_get(imu, SENSOR_CHAN_ACCEL_XYZ, a)) {
		return -EIO;
	}
	float x = sensor_value_to_float(&a[0]);
	float y = sensor_value_to_float(&a[1]);
	float z = sensor_value_to_float(&a[2]);

	*pitch = atan2f(x, sqrtf(y * y + z * z)) * 57.2958f;
	*roll = atan2f(y, sqrtf(x * x + z * z)) * 57.2958f;
	return 0;
}

/* Short high-rate burst: RMS of trunk acceleration in milli-g. */
static int vibration_rms_mg(void)
{
	struct sensor_value odr = { .val1 = 1666, .val2 = 0 };
	struct sensor_value a[3];
	static double acc[200][3]; /* static: too large for the main stack */
	double sum = 0.0, mean[3] = { 0 };
	int n = ARRAY_SIZE(acc);

	sensor_attr_set(imu, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	for (int i = 0; i < n; i++) {
		sensor_sample_fetch_chan(imu, SENSOR_CHAN_ACCEL_XYZ);
		sensor_channel_get(imu, SENSOR_CHAN_ACCEL_XYZ, a);
		for (int k = 0; k < 3; k++) {
			acc[i][k] = sensor_value_to_double(&a[k]);
			mean[k] += acc[i][k] / n;
		}
		k_busy_wait(600);
	}
	for (int i = 0; i < n; i++) {
		for (int k = 0; k < 3; k++) {
			double d = acc[i][k] - mean[k];

			sum += d * d;
		}
	}
	odr.val1 = 12;
	odr.val2 = 500000;
	sensor_attr_set(imu, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	/* m/s^2 to milli-g */
	return (int)(sqrt(sum / n) / 9.80665 * 1000.0);
}

static void read_climate(struct report *r)
{
	struct sensor_value t, h, p;

	if (sensor_sample_fetch(env)) {
		r->flags |= FLAG_SENSOR_FAULT;
		return;
	}
	sensor_channel_get(env, SENSOR_CHAN_AMBIENT_TEMP, &t);
	sensor_channel_get(env, SENSOR_CHAN_HUMIDITY, &h);
	sensor_channel_get(env, SENSOR_CHAN_PRESS, &p);
	r->temp_cx100 = (int16_t)(sensor_value_to_double(&t) * 100.0);
	r->rh_pct = (uint8_t)sensor_value_to_double(&h);
	r->press_hpa_x10 = (uint16_t)(sensor_value_to_double(&p) * 100.0); /* kPa to hPa x10 */

	/* The BQ25570 has no temperature input; flag charging outside 0-45 degC for review. */
	if (r->temp_cx100 < CHARGE_MIN_C_X100 || r->temp_cx100 > CHARGE_MAX_C_X100) {
		r->flags |= FLAG_TEMP_OUT_OF_CHARGE_RANGE;
	}
}

static void fill_tilt(struct report *r)
{
	float pitch, roll;

	if (read_tilt(&pitch, &roll) == 0) {
		r->tilt_x_dx10 = (int16_t)((pitch - base_pitch) * 10.0f);
		r->tilt_y_dx10 = (int16_t)((roll - base_roll) * 10.0f);
	} else {
		r->flags |= FLAG_SENSOR_FAULT;
	}
}

static void new_report(struct report *r, uint8_t type)
{
	*r = (struct report){ .type = type, .node_id = NODE_ID, .seq = seq++ };
}

/* ---------------------------------------------------------- Handlers */

static void biodiversity_window(void)
{
	struct audio_features f;
	struct report r;

	features_init(&f);
	audio_capture(&f, BIO_LISTEN_S * 1000);

	new_report(&r, MSG_REPORT);
	r.buzz_index = features_buzz_index(&f);
	r.bird_score = features_bird_score(&f);
	fill_tilt(&r);
	read_climate(&r);

	bool tilted = abs(r.tilt_x_dx10) > TILT_ALERT_DEG_X10 ||
		      abs(r.tilt_y_dx10) > TILT_ALERT_DEG_X10;
	if (tilted) {
		r.type = MSG_TILT;
	}
	radio_send(&r, tilted ? LORA_TX_DBM_ALERT : LORA_TX_DBM_REPORT);
}

static void logging_check(void)
{
	int vib = vibration_rms_mg();
	int hits = 0;
	uint8_t best = 0;

	LOG_INF("wake: vibration %d mg", vib);
	if (vib < VIB_RMS_MIN_MG) {
		return;
	}
	for (int i = 0; i < LOGGING_CHECK_CLIPS; i++) {
		struct audio_features f;

		features_init(&f);
		audio_capture(&f, 1000);
		uint8_t s = features_chainsaw_score(&f);

		best = MAX(best, s);
		if (s >= CHAINSAW_SCORE_MIN) {
			hits++;
		}
	}
	LOG_INF("chainsaw clips %d/%d, best %u", hits, LOGGING_CHECK_CLIPS, best);
	if (hits < LOGGING_CLIPS_NEEDED) {
		return;
	}

	struct report r;

	new_report(&r, MSG_LOGGING);
	r.saw_score = best;
	fill_tilt(&r);
	read_climate(&r);
	gpio_pin_set_dt(&led, 1);
	radio_send(&r, LORA_TX_DBM_ALERT);
	gpio_pin_set_dt(&led, 0);
}

/* -------------------------------------------------------------- Main */

int main(void)
{
	const struct device *devs[] = { lora, imu, env };

	for (size_t i = 0; i < ARRAY_SIZE(devs); i++) {
		if (!device_is_ready(devs[i])) {
			LOG_ERR("%s not ready", devs[i]->name);
		}
	}
	gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
	/* Unused expander pins P3, P4, P6, P7: drive low so they do not float. */
	if (device_is_ready(exp)) {
		const gpio_pin_t spare[] = { 3, 4, 6, 7 };

		for (size_t i = 0; i < ARRAY_SIZE(spare); i++) {
			gpio_pin_configure(exp, spare[i], GPIO_OUTPUT_INACTIVE);
		}
	}
	audio_init();

	gpio_pin_configure_dt(&wake, GPIO_INPUT);
	gpio_init_callback(&wake_cb, on_wake, BIT(wake.pin));
	gpio_add_callback(wake.port, &wake_cb);
	gpio_pin_interrupt_configure_dt(&wake, GPIO_INT_EDGE_TO_ACTIVE);

	/* Baseline tilt at install time; the BLE setup flow will re-zero it. */
	read_tilt(&base_pitch, &base_roll);

	struct report boot;

	new_report(&boot, MSG_BOOT);
	read_climate(&boot);
	radio_send(&boot, LORA_TX_DBM_REPORT);

	int64_t next_bio = k_uptime_get() + (int64_t)BIO_INTERVAL_S * 1000;

	while (1) {
		int64_t wait = next_bio - k_uptime_get();

		if (wait > 0 && k_sem_take(&wake_sem, K_MSEC(wait)) == 0) {
			logging_check();
			k_sleep(K_SECONDS(WAKE_HOLDOFF_S));
			k_sem_reset(&wake_sem);
			continue;
		}
		biodiversity_window();
		next_bio = k_uptime_get() + (int64_t)BIO_INTERVAL_S * 1000;
	}
	return 0;
}
