#include <zephyr/kernel.h>
#include <zephyr/audio/dmic.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/pm/device.h>
#include <zephyr/logging/log.h>

#include "audio.h"
#include "config.h"

LOG_MODULE_REGISTER(audio, LOG_LEVEL_INF);

#define BLOCK_BYTES (AUDIO_BLOCK_SAMPLES * sizeof(int16_t))
#define BLOCK_COUNT 4

K_MEM_SLAB_DEFINE_STATIC(audio_slab, BLOCK_BYTES, BLOCK_COUNT, 4);

static const struct device *const dmic = DEVICE_DT_GET(DT_ALIAS(dmic0));
static const struct gpio_dt_spec mic_en =
	GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), mic_en_gpios);

static struct pcm_stream_cfg stream = {
	.pcm_rate = AUDIO_RATE_HZ,
	.pcm_width = 16,
	.block_size = BLOCK_BYTES,
	.mem_slab = &audio_slab,
};

static struct dmic_cfg cfg = {
	.io = {
		.min_pdm_clk_freq = 1000000,
		.max_pdm_clk_freq = 3500000,
		.min_pdm_clk_dc = 40,
		.max_pdm_clk_dc = 60,
	},
	.streams = &stream,
	.channel = {
		.req_num_streams = 1,
		.req_num_chan = 1,
	},
};

int audio_init(void)
{
	if (!device_is_ready(dmic) || !gpio_is_ready_dt(&mic_en)) {
		LOG_ERR("mic devices not ready");
		return -ENODEV;
	}
	cfg.channel.req_chan_map_lo = dmic_build_channel_map(0, 0, PDM_CHAN_LEFT);
	gpio_pin_configure_dt(&mic_en, GPIO_OUTPUT_INACTIVE);
	/* Keep the PDM pins parked while the mic rail is off. */
	pm_device_action_run(dmic, PM_DEVICE_ACTION_SUSPEND);
	return 0;
}

int audio_capture(struct audio_features *f, int ms)
{
	int blocks = ms / AUDIO_BLOCK_MS;
	int err;

	gpio_pin_set_dt(&mic_en, 1);
	pm_device_action_run(dmic, PM_DEVICE_ACTION_RESUME);
	k_msleep(MIC_SETTLE_MS);

	err = dmic_configure(dmic, &cfg);
	if (err == 0) {
		err = dmic_trigger(dmic, DMIC_TRIGGER_START);
	}
	if (err) {
		LOG_ERR("dmic start failed: %d", err);
		goto off;
	}

	/* Drop the first block: PDM mics need a few ms to settle. */
	for (int i = 0; i <= blocks; i++) {
		void *buf;
		uint32_t size;

		err = dmic_read(dmic, 0, &buf, &size, AUDIO_BLOCK_MS * 2);
		if (err) {
			LOG_ERR("dmic read failed: %d", err);
			break;
		}
		if (i > 0) {
			features_push(f, buf, size / sizeof(int16_t));
		}
		k_mem_slab_free(&audio_slab, buf);
	}

	dmic_trigger(dmic, DMIC_TRIGGER_STOP);
off:
	pm_device_action_run(dmic, PM_DEVICE_ACTION_SUSPEND);
	gpio_pin_set_dt(&mic_en, 0);
	return err;
}
