"""
SylvaEcho dashboard backend (FastAPI + SQLite).

Reports arrive as the gateway's JSON (Gateway/src/decode.cpp, report_to_json):
  - HTTP POST /api/ingest            (Arduino gateway, HTTP_URL)
  - MQTT sylvaecho/+/+               (either gateway; set MQTT_HOST)
  - DEMO=1                           built-in simulator, marked "demo": true

The browser gets the current state from the REST API and live updates over /ws.

Run:  uvicorn app:app --port 8000          (add DEMO=1 to simulate three trees)
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).with_name("sylvaecho.db")))
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")
MQTT_HOST = os.getenv("MQTT_HOST", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEMO = os.getenv("DEMO", "0") == "1"
OFFLINE_AFTER_S = 75 * 60  # a node reports every 30 min; two missed reports = offline

# Invented names for the demo trees and for nodes that have no name yet.
NODE_NAMES = {1: "Teak Ridge", 2: "Rosewood Bend", 3: "Laurel Slope"}

DEFAULT_SETTINGS = {
    "risk_alert": 60,          # slope-risk index that raises a warning
    "rain_alert_mm_h": 10,     # matches the SC-1 default (50 tips per hour)
    "low_batt_pct": 15,
    "guard_armed": True,       # chainsaw alerts notify
    "energy_saver": False,
    "storm_watch": False,
}


# ------------------------------------------------------------------ storage
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


DB = db()
DB_LOCK = threading.Lock()
with DB_LOCK:
    DB.executescript(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            node INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            type TEXT NOT NULL,
            body TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS reports_node_ts ON reports(node, ts);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )


def get_settings() -> dict[str, Any]:
    with DB_LOCK:
        rows = DB.execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: json.loads(r["value"]) for r in rows})
    return s


def put_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with DB_LOCK:
        for k, v in patch.items():
            if k in DEFAULT_SETTINGS:
                DB.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, json.dumps(v)),
                )
        DB.commit()
    return get_settings()


# ------------------------------------------------------------------ derived values
def slope_risk(r: dict[str, Any]) -> int | None:
    """
    0-100 slope-risk index from antecedent rain, soil moisture and tree tilt.
    A screening heuristic for the dashboard, not a calibrated landslide model:
    rain in the last 24 h and 3 days, wet soil and tilt away from the
    installed baseline all push it up.
    """
    sc1 = r.get("sc1")
    if not sc1:
        return None
    rain = sc1.get("rain_mm") or {}
    r24 = min(float(rain.get("24h", 0)) / 120.0, 1.0)      # 120 mm/day = very heavy
    r72 = min(float(rain.get("3d", 0)) / 250.0, 1.0)
    soil = sc1.get("soil_pct")
    wet = 0.0 if soil is None else min(max((soil - 30) / 60.0, 0.0), 1.0)
    tilt = math.hypot(float(r.get("tilt_x", 0)), float(r.get("tilt_y", 0)))
    lean = min(tilt / 3.0, 1.0)                              # 3 degrees = alert level
    score = 100 * (0.35 * r24 + 0.25 * r72 + 0.2 * wet + 0.2 * lean)
    return int(round(score))


def decorate(row: sqlite3.Row) -> dict[str, Any]:
    body = json.loads(row["body"])
    body["ts"] = row["ts"]
    body["risk"] = slope_risk(body)
    return body


def store(report: dict[str, Any], ts: float | None = None) -> dict[str, Any] | None:
    """Save a gateway report. Returns the decorated report, or None for a duplicate."""
    if "node" not in report or "seq" not in report or "type" not in report:
        raise ValueError("not a SylvaEcho report")
    ts = ts or time.time()
    with DB_LOCK:
        dup = DB.execute(
            "SELECT 1 FROM reports WHERE node = ? AND seq = ? AND ts > ?",
            (report["node"], report["seq"], ts - 3600),
        ).fetchone()
        if dup:
            return None
        cur = DB.execute(
            "INSERT INTO reports(ts, node, seq, type, body) VALUES(?, ?, ?, ?, ?)",
            (ts, int(report["node"]), int(report["seq"]), str(report["type"]), json.dumps(report)),
        )
        DB.commit()
        row = DB.execute("SELECT * FROM reports WHERE id = ?", (cur.lastrowid,)).fetchone()
    return decorate(row)


def node_summary(node: int) -> dict[str, Any]:
    with DB_LOCK:
        row = DB.execute(
            "SELECT * FROM reports WHERE node = ? ORDER BY ts DESC LIMIT 1", (node,)
        ).fetchone()
        last_sc1 = DB.execute(
            "SELECT * FROM reports WHERE node = ? AND body LIKE '%\"sc1\"%' ORDER BY ts DESC LIMIT 1",
            (node,),
        ).fetchone()
        count = DB.execute("SELECT COUNT(*) FROM reports WHERE node = ?", (node,)).fetchone()[0]
    latest = decorate(row) if row else None
    age = time.time() - row["ts"] if row else None
    return {
        "node": node,
        "name": NODE_NAMES.get(node, f"Tree {node:02d}"),
        "online": age is not None and age < OFFLINE_AFTER_S,
        "age_s": age,
        "reports": count,
        "latest": latest,
        "latest_sc1": decorate(last_sc1) if last_sc1 else None,
    }


# ------------------------------------------------------------------ live push
class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def send(self, msg: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def send_threadsafe(self, msg: dict[str, Any]) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send(msg), self.loop)


HUB = Hub()


def accept(report: dict[str, Any], ts: float | None = None) -> dict[str, Any] | None:
    saved = store(report, ts)
    if saved:
        HUB.send_threadsafe({"event": "report", "report": saved})
    return saved


# ------------------------------------------------------------------ MQTT (optional)
def start_mqtt() -> None:
    if not MQTT_HOST:
        return
    import paho.mqtt.client as mqtt  # optional dependency

    def on_message(_c, _u, msg):
        try:
            accept(json.loads(msg.payload))
        except (ValueError, KeyError) as e:
            print(f"mqtt: skipped {msg.topic}: {e}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = lambda c, *_: c.subscribe("sylvaecho/+/+")
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    print(f"mqtt: subscribed to sylvaecho/+/+ on {MQTT_HOST}:{MQTT_PORT}")


# ------------------------------------------------------------------ demo simulator
class Sim:
    """Three trees reporting every few seconds with a 24 h day compressed into 12 min."""

    DAY_S = 720.0

    def __init__(self) -> None:
        self.seq = {n: random.randint(0, 500) for n in NODE_NAMES}
        self.soc = {1: 82.0, 2: 64.0, 3: 41.0}
        self.rain_hist = {n: [] for n in NODE_NAMES}  # (ts, mm)
        self.storm_until = 0.0

    def hour(self, t: float) -> float:
        return (t % self.DAY_S) / self.DAY_S * 24.0

    def report(self, node: int, t: float, kind: str = "report") -> dict[str, Any]:
        h = self.hour(t)
        sun = max(0.0, math.sin((h - 6) / 12 * math.pi))
        dawn = math.exp(-((h - 6.2) ** 2) / 0.8) + 0.6 * math.exp(-((h - 18.3) ** 2) / 0.8)
        storm = t < self.storm_until
        if not storm and random.random() < 0.004:
            self.storm_until = t + random.uniform(60, 150)
        mm = random.uniform(1.2, 4.0) if storm and node != 2 else (0.2 if random.random() < 0.03 else 0)
        self.rain_hist[node].append((t, mm))
        self.rain_hist[node] = [(a, b) for a, b in self.rain_hist[node] if t - a < self.DAY_S * 15]

        def rain_since(days: float) -> float:
            return round(sum(b for a, b in self.rain_hist[node] if t - a < days * self.DAY_S), 1)

        charging = sun > 0.2
        i_ma = -18.0 * sun + random.uniform(-1, 1) if charging else random.uniform(0.3, 1.8)
        self.soc[node] = max(5.0, min(100.0, self.soc[node] - i_ma * 0.02))
        temp = 22 + 7 * sun + random.uniform(-0.4, 0.4) - (3 if storm else 0)
        soil = min(95, 35 + 25 * (rain_since(1) / 40) + node * 4)
        tilt_base = {1: 0.3, 2: -0.2, 3: 1.4}[node]
        saw = random.randint(70, 92) if kind == "logging_alert" else random.randint(0, 8)
        self.seq[node] = (self.seq[node] + 1) % 65536
        return {
            "node": node,
            "seq": self.seq[node],
            "type": kind,
            "rssi": random.randint(-112, -88) - node * 3,
            "snr": round(random.uniform(-6, 9), 1),
            "flags": {"charge_temp": temp > 45, "sensor_fault": False},
            "buzz": int(min(100, 70 * sun * random.uniform(0.6, 1.1))),
            "bird": int(min(100, 25 + 70 * dawn * random.uniform(0.8, 1.1) + 10 * sun)),
            "saw": saw,
            "tilt_x": round(tilt_base + (0.02 * rain_since(3) if node == 3 else 0) + random.uniform(-0.05, 0.05), 1),
            "tilt_y": round(random.uniform(-0.2, 0.2), 1),
            "temp_c": round(temp, 2),
            "rh": int(min(99, 62 + 25 * (1 - sun) + (20 if storm else 0))),
            "press_hpa": round(1008 - (6 if storm else 0) + random.uniform(-0.5, 0.5), 1),
            "sc1": {
                "vbat_v": round(3.05 + 0.3 * self.soc[node] / 100 + (0.15 if charging else 0), 3),
                "ibat_ma": round(i_ma, 1),
                "soc": int(self.soc[node]),
                "status": 0,
                "cell_c": round(temp + 1.2, 2),
                "soil_c": round(24 + 2 * sun, 2),
                "soil_pct": int(soil),
                "borer": random.randint(0, 6) if node != 2 else random.randint(8, 30),
                "rain_mm": {
                    "1h": rain_since(1 / 24), "24h": rain_since(1), "3d": rain_since(3),
                    "5d": rain_since(5), "7d": rain_since(7), "15d": rain_since(15),
                },
                "alerts": {"rain": rain_since(1 / 24) >= 10, "low_batt": self.soc[node] < 15, "borer": False},
            },
            "demo": True,
        }

    def backfill(self) -> None:
        """Fill the last 24 compressed hours so charts and the timeline have data."""
        with DB_LOCK:
            have = DB.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        if have:
            return
        now = time.time()
        t = now - self.DAY_S
        while t < now:
            for n in NODE_NAMES:
                store(self.report(n, t), ts=t)
            t += 15.0

    def run(self) -> None:
        self.backfill()
        while True:
            t = time.time()
            for n in NODE_NAMES:
                kind = "report"
                if n == 1 and random.random() < 0.02:
                    kind = "logging_alert"
                accept(self.report(n, t, kind))
            time.sleep(5)


# ------------------------------------------------------------------ API
@asynccontextmanager
async def lifespan(_app: FastAPI):
    HUB.loop = asyncio.get_running_loop()
    start_mqtt()
    if DEMO:
        threading.Thread(target=Sim().run, daemon=True).start()
        print("demo: simulating 3 trees (DEMO=1)")
    yield


app = FastAPI(title="SylvaEcho dashboard API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/ingest")
async def ingest(report: dict[str, Any], authorization: str | None = Header(default=None)):
    if INGEST_TOKEN and authorization != f"Bearer {INGEST_TOKEN}":
        raise HTTPException(401, "bad token")
    try:
        saved = await asyncio.to_thread(accept, report)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"stored": saved is not None}


@app.get("/api/nodes")
def nodes():
    with DB_LOCK:
        ids = [r[0] for r in DB.execute("SELECT DISTINCT node FROM reports ORDER BY node")]
    return {
        "nodes": [node_summary(n) for n in ids],
        "demo": DEMO,
        "server_time": time.time(),
        # Length of one day in seconds: the demo compresses 24 h into 12 min.
        "day_s": Sim.DAY_S if DEMO else 86400,
        "settings": get_settings(),
    }


@app.get("/api/nodes/{node}/history")
def history(node: int, hours: float = 24, limit: int = 600):
    since = time.time() - hours * 3600
    with DB_LOCK:
        rows = DB.execute(
            "SELECT * FROM reports WHERE node = ? AND ts >= ? ORDER BY ts", (node, since)
        ).fetchall()
    step = max(1, len(rows) // limit)
    return {"node": node, "reports": [decorate(r) for r in rows[::step]]}


def classify(r: dict[str, Any]) -> tuple[str, str, str] | None:
    """(kind, title, detail) for a report worth listing in the soundscape, else None."""
    sc1 = r.get("sc1") or {}
    if r["type"] == "logging_alert":
        return "saw", "Chainsaw confirmed", f"saw score {r['saw']} · vibration + audio agree"
    if r["type"] == "tilt_alert":
        return "tilt", "Tree tilt alert", f"{r['tilt_x']:+.1f}° / {r['tilt_y']:+.1f}° from baseline"
    if sc1.get("borer", 0) >= 20:
        return "borer", "Borer clicks", f"index {sc1['borer']} · night listen"
    if (sc1.get("rain_mm") or {}).get("1h", 0) >= 4:
        return "rain", "Heavy rain", f"{sc1['rain_mm']['1h']} mm in the last hour"
    if r.get("bird", 0) >= 80:
        return "bird", "Dawn chorus", f"bird activity {r['bird']}"
    if r.get("buzz", 0) >= 60:
        return "buzz", "Pollinator buzz", f"wingbeat index {r['buzz']}"
    return None


@app.get("/api/events")
def events(limit: int = 30, node: int | None = None):
    """Recent acoustic and alert highlights, newest first, at most one per kind per node per 10 min."""
    q = "SELECT * FROM reports WHERE ts >= ?" + (" AND node = ?" if node else "") + " ORDER BY ts DESC"
    args: tuple = (time.time() - 86400 * 2,) + ((node,) if node else ())
    with DB_LOCK:
        rows = DB.execute(q, args).fetchall()
    out, last = [], {}
    for row in rows:
        r = decorate(row)
        c = classify(r)
        if not c:
            continue
        key = (r["node"], c[0])
        if key in last and last[key] - r["ts"] < 600:
            continue
        last[key] = r["ts"]
        out.append({"kind": c[0], "title": c[1], "detail": c[2], "node": r["node"],
                    "name": NODE_NAMES.get(r["node"], f"Tree {r['node']:02d}"), "ts": r["ts"],
                    "demo": r.get("demo", False)})
        if len(out) >= limit:
            break
    return {"events": out}


class SettingsPatch(BaseModel):
    risk_alert: int | None = None
    rain_alert_mm_h: float | None = None
    low_batt_pct: int | None = None
    guard_armed: bool | None = None
    energy_saver: bool | None = None
    storm_watch: bool | None = None


@app.get("/api/settings")
def settings_get():
    return get_settings()


@app.put("/api/settings")
async def settings_put(patch: SettingsPatch):
    s = put_settings({k: v for k, v in patch.model_dump().items() if v is not None})
    await HUB.send({"event": "settings", "settings": s})
    return s


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    HUB.clients.add(sock)
    try:
        while True:
            await sock.receive_text()  # keep-alive pings from the browser
    except WebSocketDisconnect:
        HUB.clients.discard(sock)
