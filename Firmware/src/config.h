#ifndef SYLVAECHO_CONFIG_H
#define SYLVAECHO_CONFIG_H

/* Schedule */
#define BIO_INTERVAL_S          (30 * 60)  /* biodiversity window every 30 min */
#define BIO_LISTEN_S            10         /* seconds of audio per window */
#define LOGGING_CHECK_CLIPS     3          /* 1 s clips checked after a wake */
#define LOGGING_CLIPS_NEEDED    2          /* clips that must look like a chainsaw */
#define WAKE_HOLDOFF_S          60         /* ignore new wakes this long after a check */

/* Audio */
#define AUDIO_RATE_HZ           16000
#define AUDIO_BLOCK_MS          100
#define AUDIO_BLOCK_SAMPLES     (AUDIO_RATE_HZ * AUDIO_BLOCK_MS / 1000)
#define MIC_SETTLE_MS           50

/* Detection thresholds: placeholders until the classifier is trained */
#define CHAINSAW_SCORE_MIN      60         /* 0-100 */
#define VIB_RMS_MIN_MG          25         /* trunk vibration RMS during a check */
#define TILT_ALERT_DEG_X10      30         /* 3.0 degrees from the installed baseline */

/* Battery protection by temperature (BQ25570 has no NTC input) */
#define CHARGE_MIN_C_X100       0
#define CHARGE_MAX_C_X100       4500

/* LoRa (P2P). IN865 example channel; change for EU868 / US915. */
#define LORA_FREQ_HZ            865062500
#define LORA_SF                 SF_10
#define LORA_BW                 BW_125_KHZ
#define LORA_CR                 CR_4_5
#define LORA_TX_DBM_REPORT      14
#define LORA_TX_DBM_ALERT       20
#define NODE_ID                 0x0001

#endif
