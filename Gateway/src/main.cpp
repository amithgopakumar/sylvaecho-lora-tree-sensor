/*
 * SylvaEcho gateway: XIAO ESP32S3 + Wio-SX1262
 *
 * Listens continuously on the node's LoRa P2P channel, decodes each report and
 * forwards it as JSON to:
 *   - USB serial (always, one line per packet)
 *   - MQTT  sylvaecho/<node>/<type>   (if MQTT_HOST is set)
 *   - HTTP POST                       (if HTTP_URL is set)
 *
 * Radio settings must match Firmware/src/config.h on the node.
 */
#include <Arduino.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <RadioLib.h>
#include <SPI.h>
#include <WiFi.h>

#include "decode.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#warning "src/secrets.h missing: using secrets.example.h (serial output only)"
#include "secrets.example.h"
#endif

/* ---- radio: same channel as the node (IN865 example) ---- */
static const float LORA_FREQ_MHZ = 865.0625f;
static const float LORA_BW_KHZ = 125.0f;
static const uint8_t LORA_SF = 10;
static const uint8_t LORA_CR = 5;            /* 4/5 */
static const uint8_t LORA_SYNC = 0x12;       /* private network, Zephyr default */
static const uint16_t LORA_PREAMBLE = 8;
static const float LORA_TCXO_V = 1.8f;

/* ---- Wio-SX1262 on the XIAO ESP32S3 B2B connector (Meshtastic seeed_xiao_s3 variant) ---- */
static const int PIN_SCK = 7, PIN_MISO = 8, PIN_MOSI = 9;
static const int PIN_NSS = 41, PIN_DIO1 = 39, PIN_RST = 42, PIN_BUSY = 40, PIN_RXEN = 38;
static const int PIN_LED = LED_BUILTIN;      /* XIAO user LED, active low */

static SX1262 radio = new Module(PIN_NSS, PIN_DIO1, PIN_RST, PIN_BUSY);
static volatile bool rx_flag;

static WiFiClient wifi_client;
static PubSubClient mqtt(wifi_client);

/* Duplicate filter: the node may repeat alerts; keep the last seq per node. */
struct Seen {
	uint16_t node, seq;
	bool used;
};
static Seen seen[16];

static uint32_t rx_count, rx_bad, rx_dup;

static void IRAM_ATTR on_dio1(void)
{
	rx_flag = true;
}

static bool is_duplicate(uint16_t node, uint16_t seq)
{
	Seen *free_slot = nullptr;

	for (Seen &s : seen) {
		if (s.used && s.node == node) {
			if (s.seq == seq) {
				return true;
			}
			s.seq = seq;
			return false;
		}
		if (!s.used && !free_slot) {
			free_slot = &s;
		}
	}
	Seen *slot = free_slot ? free_slot : &seen[node % 16];

	*slot = {node, seq, true};
	return false;
}

/* ------------------------------------------------------------- network */
static void wifi_begin(void)
{
	if (strlen(WIFI_SSID) == 0) {
		return;
	}
	WiFi.mode(WIFI_STA);
	WiFi.setAutoReconnect(true);
	WiFi.begin(WIFI_SSID, WIFI_PASS);
	Serial.printf("# wifi: connecting to %s\n", WIFI_SSID);
}

static void mqtt_service(void)
{
	static uint32_t last_try;

	if (strlen(MQTT_HOST) == 0 || WiFi.status() != WL_CONNECTED) {
		return;
	}
	if (!mqtt.connected() && millis() - last_try > 5000) {
		last_try = millis();
		String id = "sylvaecho-gw-" + String((uint32_t)ESP.getEfuseMac(), HEX);
		bool ok = strlen(MQTT_USER) ? mqtt.connect(id.c_str(), MQTT_USER, MQTT_PASS)
					    : mqtt.connect(id.c_str());

		Serial.printf("# mqtt: %s %s\n", MQTT_HOST, ok ? "connected" : "failed");
		if (ok) {
			mqtt.publish("sylvaecho/gateway/status", "online");
		}
	}
	mqtt.loop();
}

static void forward(const Report &r, const char *json, size_t len)
{
	if (WiFi.status() != WL_CONNECTED) {
		return;
	}
	if (strlen(MQTT_HOST) && mqtt.connected()) {
		char topic[64];

		snprintf(topic, sizeof(topic), "sylvaecho/%u/%s", r.node_id, msg_type_name(r.type));
		if (!mqtt.publish(topic, (const uint8_t *)json, len, false)) {
			Serial.println("# mqtt: publish failed");
		}
	}
	if (strlen(HTTP_URL)) {
		HTTPClient http;

		http.setTimeout(4000);
		if (http.begin(HTTP_URL)) {
			http.addHeader("Content-Type", "application/json");
			if (strlen(HTTP_TOKEN)) {
				http.addHeader("Authorization", String("Bearer ") + HTTP_TOKEN);
			}
			int code = http.POST((uint8_t *)json, len);

			if (code < 200 || code >= 300) {
				Serial.printf("# http: POST returned %d\n", code);
			}
			http.end();
		}
	}
}

/* --------------------------------------------------------------- radio */
static void radio_begin(void)
{
	SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_NSS);
	int st = radio.begin(LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_SYNC, 14,
			     LORA_PREAMBLE, LORA_TCXO_V, false);

	if (st != RADIOLIB_ERR_NONE) {
		Serial.printf("# radio: init failed (%d); check the Wio-SX1262 board\n", st);
		while (true) {
			digitalWrite(PIN_LED, !digitalRead(PIN_LED));
			delay(200);
		}
	}
	radio.setDio2AsRfSwitch(true);
	radio.setRfSwitchPins(PIN_RXEN, RADIOLIB_NC);
	radio.setCRC(true);
	radio.setRxBoostedGainMode(true);
	radio.setPacketReceivedAction(on_dio1);
	st = radio.startReceive();
	Serial.printf("# radio: listening %.4f MHz SF%u BW%.0f (%d)\n", LORA_FREQ_MHZ, LORA_SF,
		      LORA_BW_KHZ, st);
}

static void handle_packet(void)
{
	uint8_t buf[64];
	size_t len = radio.getPacketLength();
	int st;

	if (len > sizeof(buf)) {
		len = sizeof(buf);
	}
	st = radio.readData(buf, len);
	int rssi = (int)radio.getRSSI();
	float snr = radio.getSNR();

	radio.startReceive();
	rx_count++;

	if (st != RADIOLIB_ERR_NONE) {
		rx_bad++;
		Serial.printf("# rx error %d (rssi %d)\n", st, rssi);
		return;
	}

	Report r;

	if (!decode_report(buf, len, &r)) {
		rx_bad++;
		Serial.printf("# foreign packet, %u bytes (rssi %d)\n", (unsigned)len, rssi);
		return;
	}
	if (is_duplicate(r.node_id, r.seq)) {
		rx_dup++;
		return;
	}

	char json[1024];
	size_t n = report_to_json(r, rssi, snr, json, sizeof(json));

	if (n == 0) {
		Serial.println("# json buffer too small");
		return;
	}
	digitalWrite(PIN_LED, LOW);
	Serial.println(json);
	forward(r, json, n);
	digitalWrite(PIN_LED, HIGH);
}

/* --------------------------------------------------------- setup/loop */
void setup(void)
{
	pinMode(PIN_LED, OUTPUT);
	digitalWrite(PIN_LED, HIGH);
	Serial.begin(115200);
	delay(1500);
	Serial.println("# SylvaEcho gateway");

	radio_begin();
	wifi_begin();
	if (strlen(MQTT_HOST)) {
		mqtt.setServer(MQTT_HOST, MQTT_PORT);
		mqtt.setBufferSize(1280);
	}
}

void loop(void)
{
	static uint32_t last_stats;

	if (rx_flag) {
		rx_flag = false;
		handle_packet();
	}
	mqtt_service();

	if (millis() - last_stats > 600000UL) {
		last_stats = millis();
		char s[160];

		snprintf(s, sizeof(s),
			 "{\"gateway\":\"stats\",\"rx\":%lu,\"bad\":%lu,\"dup\":%lu,\"wifi\":%s,\"uptime_s\":%lu}",
			 (unsigned long)rx_count, (unsigned long)rx_bad, (unsigned long)rx_dup,
			 WiFi.status() == WL_CONNECTED ? "true" : "false", (unsigned long)(millis() / 1000));
		Serial.println(s);
		if (strlen(MQTT_HOST) && mqtt.connected()) {
			mqtt.publish("sylvaecho/gateway/stats", s);
		}
	}
	delay(2);
}
