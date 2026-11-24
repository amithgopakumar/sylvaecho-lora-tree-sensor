#ifndef SYLVAECHO_AUDIO_H
#define SYLVAECHO_AUDIO_H

#include "features.h"

int audio_init(void);

/* Switch the mic rail on, stream `ms` of audio into `f`, switch it off. */
int audio_capture(struct audio_features *f, int ms);

#endif
