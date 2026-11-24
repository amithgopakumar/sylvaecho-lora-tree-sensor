#include <math.h>
#include "features.h"
#include "config.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* RBJ biquad band-pass (constant 0 dB peak gain). */
static void bandpass(struct band_filter *bf, float f_lo, float f_hi)
{
	float f0 = sqrtf(f_lo * f_hi);
	float bw_oct = log2f(f_hi / f_lo);
	float w0 = 2.0f * (float)M_PI * f0 / AUDIO_RATE_HZ;
	float alpha = sinf(w0) * sinhf(logf(2.0f) / 2.0f * bw_oct * w0 / sinf(w0));
	float a0 = 1.0f + alpha;

	bf->b0 = alpha / a0;
	bf->b1 = 0.0f;
	bf->b2 = -alpha / a0;
	bf->a1 = -2.0f * cosf(w0) / a0;
	bf->a2 = (1.0f - alpha) / a0;
	bf->z1 = bf->z2 = 0.0f;
}

static inline float run(struct band_filter *bf, float x)
{
	float y = bf->b0 * x + bf->z1;

	bf->z1 = bf->b1 * x - bf->a1 * y + bf->z2;
	bf->z2 = bf->b2 * x - bf->a2 * y;
	return y;
}

void features_init(struct audio_features *f)
{
	bandpass(&f->buzz, 150.0f, 400.0f);
	bandpass(&f->bird, 1000.0f, 6000.0f);
	bandpass(&f->saw, 100.0f, 1000.0f);
	f->e_total = f->e_buzz = f->e_bird = f->e_saw = 0.0;
	f->n = 0;
}

void features_push(struct audio_features *f, const int16_t *pcm, size_t count)
{
	for (size_t i = 0; i < count; i++) {
		float x = (float)pcm[i] / 32768.0f;
		float yb = run(&f->buzz, x);
		float yr = run(&f->bird, x);
		float ys = run(&f->saw, x);

		f->e_total += (double)(x * x);
		f->e_buzz += (double)(yb * yb);
		f->e_bird += (double)(yr * yr);
		f->e_saw += (double)(ys * ys);
	}
	f->n += count;
}

static uint8_t ratio_score(double band, double total)
{
	if (total <= 1e-12) {
		return 0;
	}
	double r = band / total;

	if (r > 1.0) {
		r = 1.0;
	}
	return (uint8_t)(r * 100.0 + 0.5);
}

uint8_t features_buzz_index(const struct audio_features *f)
{
	return ratio_score(f->e_buzz, f->e_total);
}

uint8_t features_bird_score(const struct audio_features *f)
{
	return ratio_score(f->e_bird, f->e_total);
}

uint8_t features_chainsaw_score(const struct audio_features *f)
{
	/* A running saw puts most energy into 100-1000 Hz at a high level. */
	double rms = f->n ? sqrt(f->e_total / f->n) : 0.0;
	uint8_t share = ratio_score(f->e_saw, f->e_total);

	return (rms > 0.02) ? share : share / 4;
}
