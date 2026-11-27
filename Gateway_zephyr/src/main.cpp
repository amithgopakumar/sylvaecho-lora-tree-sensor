/*
 * SylvaEcho gateway, Zephyr version (XIAO ESP32S3 + Wio-SX1262)
 *
 * - LoRa: continuous receive with lora_recv_async() on the node's channel.
 *   The callback only queues the packet; the main thread decodes it.
 * - Every report becomes one JSON line on the console (USB serial).
 * - With Wi-Fi and an MQTT broker configured (secrets.conf), each report is
 *   published to sylvaecho/<node>/<type>, QoS 0.
 *
 * Radio settings must match Firmware/src/config.h on the node: SF10, BW 125 kHz,
 * CR 4/5, preamble 8, private sync word (public_network = false), CRC on.
 */
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/lora.h>
#include <zephyr/logging/log.h>
#include <zephyr/net/dhcpv4.h>
#include <zephyr/net/mqtt.h>
#include <zephyr/net/net_if.h>
#include <zephyr/net/net_mgmt.h>
#include <zephyr/net/socket.h>
#include <zephyr/net/wifi_mgmt.h>
#include <zephyr/version.h>

#include "decode.h"

LOG_MODULE_REGISTER(gateway, LOG_LEVEL_INF);

/* --------------------------------------------------------------- LoRa */

struct rx_packet {
	uint8_t len;
	int16_t rssi;
	int8_t snr;
	uint8_t data[64];
};

K_MSGQ_DEFINE(rx_q, sizeof(struct rx_packet), 8, 4);

static const struct device *const lora = DEVICE_DT_GET(DT_ALIAS(lora0));
static uint32_t rx_count, rx_bad, rx_dup, rx_drop;

static void on_lora_rx(const struct device *dev, uint8_t *data, uint16_t size, int16_t rssi,
		       int8_t snr, void *user_data)
{
	struct rx_packet p;

	ARG_UNUSED(dev);
	ARG_UNUSED(user_data);
	p.len = size > sizeof(p.data) ? sizeof(p.data) : size;
	p.rssi = rssi;
	p.snr = snr;
	memcpy(p.data, data, p.len);
	if (k_msgq_put(&rx_q, &p, K_NO_WAIT) != 0) {
		rx_drop++;
	}
}

static int lora_start(void)
{
	struct lora_modem_config c = {};

	if (!device_is_ready(lora)) {
		LOG_ERR("SX1262 not ready: check the Wio-SX1262 board and overlay");
		return -ENODEV;
	}
	c.frequency = CONFIG_GW_LORA_FREQ_HZ;
	c.bandwidth = BW_125_KHZ;
	c.datarate = SF_10;
	c.coding_rate = CR_4_5;
	c.preamble_len = 8;
	c.tx_power = 14;
	c.tx = false;
	c.iq_inverted = false;
	c.public_network = false;

	int err = lora_config(lora, &c);

	if (!err) {
		err = lora_recv_async(lora, on_lora_rx, NULL);
	}
	LOG_INF("LoRa: listening on %u Hz SF10 BW125 (%d)", CONFIG_GW_LORA_FREQ_HZ, err);
	return err;
}

/* Duplicate filter: last sequence number per node. */
struct seen {
	uint16_t node, seq;
	bool used;
};
static struct seen seen_tab[16];

static bool is_duplicate(uint16_t node, uint16_t seq)
{
	struct seen *free_slot = NULL;

	for (struct seen &s : seen_tab) {
		if (s.used && s.node == node) {
			bool dup = s.seq == seq;

			s.seq = seq;
			return dup;
		}
		if (!s.used && !free_slot) {
			free_slot = &s;
		}
	}
	struct seen *slot = free_slot ? free_slot : &seen_tab[node % ARRAY_SIZE(seen_tab)];

	*slot = {node, seq, true};
	return false;
}

/* ------------------------------------------------------------ Wi-Fi */

#if KERNEL_VERSION_NUMBER >= ZEPHYR_VERSION(4, 2, 0)
typedef uint64_t mgmt_event_t;
#else
typedef uint32_t mgmt_event_t;
#endif

static struct net_mgmt_event_callback wifi_cb, ip_cb;
static struct net_if *iface;
static volatile bool wifi_up, ip_up;
static int64_t wifi_retry_at;

static bool wifi_configured(void)
{
	return strlen(CONFIG_GW_WIFI_SSID) > 0;
}

static void wifi_connect(void)
{
	struct wifi_connect_req_params p = {};

	p.ssid = (const uint8_t *)CONFIG_GW_WIFI_SSID;
	p.ssid_length = strlen(CONFIG_GW_WIFI_SSID);
	p.psk = (const uint8_t *)CONFIG_GW_WIFI_PSK;
	p.psk_length = strlen(CONFIG_GW_WIFI_PSK);
	p.security = p.psk_length ? WIFI_SECURITY_TYPE_PSK : WIFI_SECURITY_TYPE_NONE;
	p.channel = WIFI_CHANNEL_ANY;
	p.band = WIFI_FREQ_BAND_2_4_GHZ;
	p.mfp = WIFI_MFP_OPTIONAL;

	int err = net_mgmt(NET_REQUEST_WIFI_CONNECT, iface, &p, sizeof(p));

	LOG_INF("Wi-Fi: connecting to %s (%d)", CONFIG_GW_WIFI_SSID, err);
	wifi_retry_at = k_uptime_get() + 20000; /* retry if no result in 20 s */
}

static void on_wifi_event(struct net_mgmt_event_callback *cb, mgmt_event_t event,
			  struct net_if *ifc)
{
	ARG_UNUSED(ifc);
	if (event == NET_EVENT_WIFI_CONNECT_RESULT) {
		const struct wifi_status *st = (const struct wifi_status *)cb->info;

		if (st->status == 0) {
			wifi_up = true;
			wifi_retry_at = 0;
			LOG_INF("Wi-Fi: connected, requesting an address");
			net_dhcpv4_start(iface);
		} else {
			LOG_WRN("Wi-Fi: connect failed (%d)", st->status);
			wifi_retry_at = k_uptime_get() + 10000;
		}
	} else if (event == NET_EVENT_WIFI_DISCONNECT_RESULT) {
		wifi_up = false;
		ip_up = false;
		LOG_WRN("Wi-Fi: disconnected");
		wifi_retry_at = k_uptime_get() + 5000;
	}
}

static void on_ip_event(struct net_mgmt_event_callback *cb, mgmt_event_t event,
			struct net_if *ifc)
{
	ARG_UNUSED(cb);
	ARG_UNUSED(ifc);
	if (event == NET_EVENT_IPV4_ADDR_ADD) {
		ip_up = true;
		LOG_INF("Wi-Fi: got an IPv4 address");
	}
}

static void wifi_start(void)
{
	if (!wifi_configured()) {
		LOG_INF("Wi-Fi: no SSID set, serial output only");
		return;
	}
	iface = net_if_get_default();
	net_mgmt_init_event_callback(&wifi_cb, on_wifi_event,
				     NET_EVENT_WIFI_CONNECT_RESULT | NET_EVENT_WIFI_DISCONNECT_RESULT);
	net_mgmt_add_event_callback(&wifi_cb);
	net_mgmt_init_event_callback(&ip_cb, on_ip_event, NET_EVENT_IPV4_ADDR_ADD);
	net_mgmt_add_event_callback(&ip_cb);
	wifi_connect();
}

static void wifi_service(void)
{
	if (wifi_configured() && !wifi_up && wifi_retry_at && k_uptime_get() >= wifi_retry_at) {
		wifi_connect();
	}
}

/* ------------------------------------------------------------- MQTT */

static struct mqtt_client client;
static struct sockaddr_storage broker;
static uint8_t mqtt_rx_buf[256];
static uint8_t mqtt_tx_buf[1024];
static char client_id[32];
static struct mqtt_utf8 mqtt_user, mqtt_pass;
static bool mqtt_connected, mqtt_open;
static int64_t mqtt_retry_at;
static uint16_t msg_id = 1;

static bool mqtt_configured(void)
{
	return strlen(CONFIG_GW_MQTT_HOST) > 0;
}

static void mqtt_evt(struct mqtt_client *c, const struct mqtt_evt *evt)
{
	ARG_UNUSED(c);
	switch (evt->type) {
	case MQTT_EVT_CONNACK:
		mqtt_connected = evt->result == 0;
		LOG_INF("MQTT: %s", mqtt_connected ? "connected" : "refused");
		break;
	case MQTT_EVT_DISCONNECT:
		mqtt_connected = false;
		mqtt_open = false;
		LOG_WRN("MQTT: disconnected");
		break;
	default:
		break;
	}
}

static int resolve_broker(void)
{
	struct zsock_addrinfo hints = {};
	struct zsock_addrinfo *res = NULL;
	char port[8];

	hints.ai_family = AF_INET;
	hints.ai_socktype = SOCK_STREAM;
	snprintf(port, sizeof(port), "%d", CONFIG_GW_MQTT_PORT);

	int err = zsock_getaddrinfo(CONFIG_GW_MQTT_HOST, port, &hints, &res);

	if (err || !res) {
		LOG_WRN("MQTT: cannot resolve %s (%d)", CONFIG_GW_MQTT_HOST, err);
		return -EHOSTUNREACH;
	}
	memcpy(&broker, res->ai_addr, res->ai_addrlen);
	zsock_freeaddrinfo(res);
	return 0;
}

static void mqtt_start(void)
{
	if (resolve_broker() != 0) {
		return;
	}
	mqtt_client_init(&client);
	snprintf(client_id, sizeof(client_id), "sylvaecho-gw-%08x", (unsigned)sys_rand32_get());
	client.broker = &broker;
	client.evt_cb = mqtt_evt;
	client.client_id.utf8 = (const uint8_t *)client_id;
	client.client_id.size = strlen(client_id);
	client.protocol_version = MQTT_VERSION_3_1_1;
	client.rx_buf = mqtt_rx_buf;
	client.rx_buf_size = sizeof(mqtt_rx_buf);
	client.tx_buf = mqtt_tx_buf;
	client.tx_buf_size = sizeof(mqtt_tx_buf);
	client.transport.type = MQTT_TRANSPORT_NON_SECURE;
	if (strlen(CONFIG_GW_MQTT_USER)) {
		mqtt_user.utf8 = (const uint8_t *)CONFIG_GW_MQTT_USER;
		mqtt_user.size = strlen(CONFIG_GW_MQTT_USER);
		mqtt_pass.utf8 = (const uint8_t *)CONFIG_GW_MQTT_PASS;
		mqtt_pass.size = strlen(CONFIG_GW_MQTT_PASS);
		client.user_name = &mqtt_user;
		client.password = &mqtt_pass;
	}

	int err = mqtt_connect(&client);

	if (err) {
		LOG_WRN("MQTT: connect to %s failed (%d)", CONFIG_GW_MQTT_HOST, err);
		return;
	}
	mqtt_open = true;
}

static void mqtt_service(void)
{
	if (!mqtt_configured() || !ip_up) {
		return;
	}
	if (!mqtt_open) {
		if (k_uptime_get() >= mqtt_retry_at) {
			mqtt_retry_at = k_uptime_get() + 5000;
			mqtt_start();
		}
		return;
	}

	struct zsock_pollfd fds = { .fd = client.transport.tcp.sock, .events = ZSOCK_POLLIN };

	if (zsock_poll(&fds, 1, 0) > 0) {
		if (mqtt_input(&client) != 0) {
			mqtt_abort(&client);
			mqtt_open = mqtt_connected = false;
			return;
		}
	}
	if (mqtt_connected) {
		mqtt_live(&client);
	}
}

static void mqtt_send(const char *topic, const char *payload, size_t len)
{
	if (!mqtt_connected) {
		return;
	}
	struct mqtt_publish_param p = {};

	p.message.topic.qos = MQTT_QOS_0_AT_MOST_ONCE;
	p.message.topic.topic.utf8 = (const uint8_t *)topic;
	p.message.topic.topic.size = strlen(topic);
	p.message.payload.data = (uint8_t *)payload;
	p.message.payload.len = len;
	p.message_id = msg_id++;

	int err = mqtt_publish(&client, &p);

	if (err) {
		LOG_WRN("MQTT: publish failed (%d)", err);
	}
}

/* ------------------------------------------------------------- main */

static void handle(const struct rx_packet *p)
{
	Report r;
	static char json[640];

	rx_count++;
	if (!decode_report(p->data, p->len, &r)) {
		rx_bad++;
		printk("# foreign packet, %u bytes (rssi %d)\n", p->len, p->rssi);
		return;
	}
	if (is_duplicate(r.node_id, r.seq)) {
		rx_dup++;
		return;
	}

	size_t n = report_to_json(r, p->rssi, (float)p->snr, json, sizeof(json));

	if (n == 0) {
		printk("# json buffer too small\n");
		return;
	}
	printk("%s\n", json);

	char topic[48];

	snprintf(topic, sizeof(topic), "sylvaecho/%u/%s", r.node_id, msg_type_name(r.type));
	mqtt_send(topic, json, n);
}

int main(void)
{
	printk("# SylvaEcho gateway (Zephyr %s)\n", KERNEL_VERSION_STRING);

	if (lora_start() != 0) {
		return 0;
	}
	wifi_start();

	int64_t next_stats = k_uptime_get() + 600000;

	while (true) {
		struct rx_packet p;

		if (k_msgq_get(&rx_q, &p, K_MSEC(200)) == 0) {
			handle(&p);
		}
		wifi_service();
		mqtt_service();

		if (k_uptime_get() >= next_stats) {
			char s[160];

			next_stats += 600000;
			snprintf(s, sizeof(s),
				 "{\"gateway\":\"stats\",\"rx\":%u,\"bad\":%u,\"dup\":%u,\"dropped\":%u,"
				 "\"wifi\":%s,\"uptime_s\":%u}",
				 rx_count, rx_bad, rx_dup, rx_drop, ip_up ? "true" : "false",
				 (unsigned)(k_uptime_get() / 1000));
			printk("%s\n", s);
			mqtt_send("sylvaecho/gateway/stats", s, strlen(s));
		}
	}
	return 0;
}
