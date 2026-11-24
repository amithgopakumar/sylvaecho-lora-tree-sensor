#ifndef SYLVAECHO_FEATURES_H
#define SYLVAECHO_FEATURES_H

#include <stdint.h>
#include <stddef.h>

/*
 * Band-energy features computed block by block while audio streams in.
 * These stand in for the Edge Impulse / TFLite Micro classifier until the
 * dataset is collected; the interface stays the same when the model lands.
 */
struct band_filter {
	float b0, b1, b2, a1, a2;
	float z1, z2;
};

struct audio_features {
	struct band_filter buzz;     /* 150-400 Hz: pollinator wingbeat */
	struct band_filter bird;     /* 1-6 kHz: bird song */
	struct band_filter saw;      /* 100-1000 Hz: chainsaw harmonics */
	double e_total, e_buzz, e_bird, e_saw;
	uint32_t n;
};

void features_init(struct audio_features *f);
void features_push(struct audio_features *f, const int16_t *pcm, size_t count);

/* 0-100 scores for the samples pushed since features_init(). */
uint8_t features_buzz_index(const struct audio_features *f);
uint8_t features_bird_score(const struct audio_features *f);
uint8_t features_chainsaw_score(const struct audio_features *f);

#endif
