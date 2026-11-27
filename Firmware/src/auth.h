/*
 * Report authentication: every packet ends with a 16-byte trailer
 *
 *   u32 epoch    random at each boot (replay window resets safely on reboot)
 *   u32 counter  increments with every packet in this epoch
 *   u8  tag[8]   HMAC-SHA256(key, all bytes before the tag), truncated
 *
 * Byte 18 of the report gets EXT_AUTH. The server rejects a bad tag (forged or
 * altered) and any (epoch, counter) it has already accepted (replayed).
 *
 * The key is a per-node 32-byte secret, set in secrets.conf
 * (CONFIG_SYLVAECHO_AUTH_KEY, 64 hex digits). Next step: hold it in the
 * ATECC608B on SC-1 and use its HMAC command and monotonic counter, so the key
 * never sits in MCU flash.
 */
#ifndef SYLVAECHO_AUTH_H
#define SYLVAECHO_AUTH_H

#include <stddef.h>
#include <stdint.h>

#define AUTH_TRAILER_LEN 16
#define AUTH_TAG_LEN     8

/* Parse the hex key and pick the boot epoch. Returns 0, or -1 if no key (unsigned mode). */
int auth_init(const char *hex_key, uint32_t epoch);

/* Append the trailer to a packed report. Returns the new length, or `len` unchanged
 * when authentication is off or `cap` is too small. */
size_t auth_seal(uint8_t *buf, size_t len, size_t cap);

/* Exposed for tests. */
void hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len,
		 uint8_t out[32]);

#endif
