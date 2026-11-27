/* Report authentication (see auth.h). Plain C, no Zephyr dependency, so the
 * same code is unit-tested on a PC against Python's hmac module. */
#include <string.h>

#include "auth.h"
#include "payload.h"

/* ------------------------------------------------------------ SHA-256 */
struct sha256 {
	uint32_t h[8];
	uint64_t len;
	uint8_t buf[64];
	size_t n;
};

static const uint32_t K[64] = {
	0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
	0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
	0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
	0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
	0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
	0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
	0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha_block(struct sha256 *s, const uint8_t *p)
{
	uint32_t w[64], a, b, c, d, e, f, g, h;

	for (int i = 0; i < 16; i++) {
		w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 |
		       (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
	}
	for (int i = 16; i < 64; i++) {
		uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
		uint32_t s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);

		w[i] = w[i - 16] + s0 + w[i - 7] + s1;
	}
	a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
	e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
	for (int i = 0; i < 64; i++) {
		uint32_t t1 = h + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
		uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));

		h = g; g = f; f = e; e = d + t1;
		d = c; c = b; b = a; a = t1 + t2;
	}
	s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
	s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha_init(struct sha256 *s)
{
	static const uint32_t iv[8] = {
		0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
	};

	memcpy(s->h, iv, sizeof(iv));
	s->len = 0;
	s->n = 0;
}

static void sha_update(struct sha256 *s, const uint8_t *p, size_t len)
{
	s->len += len;
	while (len--) {
		s->buf[s->n++] = *p++;
		if (s->n == 64) {
			sha_block(s, s->buf);
			s->n = 0;
		}
	}
}

static void sha_final(struct sha256 *s, uint8_t out[32])
{
	uint64_t bits = s->len * 8;
	uint8_t pad = 0x80;

	sha_update(s, &pad, 1);
	pad = 0;
	while (s->n != 56) {
		sha_update(s, &pad, 1);
	}
	for (int i = 7; i >= 0; i--) {
		uint8_t b = (uint8_t)(bits >> (8 * i));

		sha_update(s, &b, 1);
	}
	for (int i = 0; i < 8; i++) {
		out[4 * i] = s->h[i] >> 24;
		out[4 * i + 1] = s->h[i] >> 16;
		out[4 * i + 2] = s->h[i] >> 8;
		out[4 * i + 3] = s->h[i];
	}
}

void hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len,
		 uint8_t out[32])
{
	uint8_t k[64] = { 0 }, pad[64], inner[32];
	struct sha256 s;

	if (key_len > 64) {
		sha_init(&s);
		sha_update(&s, key, key_len);
		sha_final(&s, k);
	} else {
		memcpy(k, key, key_len);
	}
	for (int i = 0; i < 64; i++) {
		pad[i] = k[i] ^ 0x36;
	}
	sha_init(&s);
	sha_update(&s, pad, 64);
	sha_update(&s, msg, msg_len);
	sha_final(&s, inner);
	for (int i = 0; i < 64; i++) {
		pad[i] = k[i] ^ 0x5c;
	}
	sha_init(&s);
	sha_update(&s, pad, 64);
	sha_update(&s, inner, 32);
	sha_final(&s, out);
}

/* ----------------------------------------------------------- sealing */
static uint8_t key[32];
static size_t key_len;
static uint32_t epoch, counter;

static int hexval(char c)
{
	if (c >= '0' && c <= '9') return c - '0';
	if (c >= 'a' && c <= 'f') return c - 'a' + 10;
	if (c >= 'A' && c <= 'F') return c - 'A' + 10;
	return -1;
}

int auth_init(const char *hex_key, uint32_t boot_epoch)
{
	size_t n = hex_key ? strlen(hex_key) : 0;

	key_len = 0;
	if (n != 64) {
		return -1;
	}
	for (size_t i = 0; i < 32; i++) {
		int hi = hexval(hex_key[2 * i]), lo = hexval(hex_key[2 * i + 1]);

		if (hi < 0 || lo < 0) {
			return -1;
		}
		key[i] = (uint8_t)(hi << 4 | lo);
	}
	key_len = 32;
	epoch = boot_epoch;
	counter = 0;
	return 0;
}

static void put32(uint8_t *p, uint32_t v)
{
	p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

size_t auth_seal(uint8_t *buf, size_t len, size_t cap)
{
	uint8_t mac[32];

	if (!key_len || len < PAYLOAD_BASE_LEN || len + AUTH_TRAILER_LEN > cap) {
		return len;
	}
	buf[18] |= EXT_AUTH;
	put32(&buf[len], epoch);
	put32(&buf[len + 4], ++counter);
	hmac_sha256(key, key_len, buf, len + 8, mac);
	memcpy(&buf[len + 8], mac, AUTH_TAG_LEN);
	return len + AUTH_TRAILER_LEN;
}
