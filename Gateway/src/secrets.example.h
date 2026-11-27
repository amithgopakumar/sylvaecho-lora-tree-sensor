/*
 * Copy to secrets.h (git-ignored) and fill in. Leave a host or URL empty to
 * switch that uplink off; the gateway always prints JSON on USB serial.
 */
#pragma once

#define WIFI_SSID      "your-wifi"
#define WIFI_PASS      "your-password"

/* MQTT: topic sylvaecho/<node_id>/<message type>, retained = false */
#define MQTT_HOST      ""            /* e.g. "192.168.1.10" or "broker.example.org" */
#define MQTT_PORT      1883
#define MQTT_USER      ""
#define MQTT_PASS      ""

/* HTTP: JSON POST of every packet, e.g. "http://192.168.1.10:8000/api/ingest" */
#define HTTP_URL       ""
#define HTTP_TOKEN     ""            /* sent as "Authorization: Bearer <token>" if set */
