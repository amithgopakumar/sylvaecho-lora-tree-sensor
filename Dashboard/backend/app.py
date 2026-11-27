"""
SylvaEcho dashboard backend (FastAPI + SQLite).

Reports arrive as the gateway's JSON (Gateway/src/decode.cpp, report_to_json):
  - HTTP POST /api/ingest            (Arduino gateway, HTTP_URL)
  - MQTT sylvaecho/+/+               (either gateway; set MQTT_HOST)
  - DEMO=1                           built-in simulator, marked "demo": true

Security
  - Signed reports: the gateway forwards the raw packet ("raw" hex). For every
    node with a key in keys.json the server checks the HMAC-SHA256 tag and the
    (boot epoch, counter) pair, and rejects unsigned, forged and replayed
    packets (protocol.py). Rejections go to /api/security, the live socket and
    the phone.
  - Phone alerts through ntfy (alerts.py, NTFY_URL).
  - DASH_PASSWORD protects the dashboard API and live socket; INGEST_TOKEN
    protects /api/ingest. Serve over HTTPS with the Caddyfile in Dashboard/.

The browser gets the current state from the REST API and live updates over /ws.

Run:  uvicorn app:app --port 8000          (add DEMO=1 to simulate three trees)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import random
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import alerts
import protocol

DB_PATH = Path(os.getenv("DB_PATH", Path(__file__).with_name("sylvaecho.db")))
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")
MQTT_HOST = os.getenv("MQTT_HOST", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
DEMO = os.getenv("DEMO", "0") == "1"
KEYS_PATH = Path(os.getenv("KEYS_PATH", Path(__file__).with_name("keys.json")))
DASH_PASSWORD = os.getenv("DASH_PASSWORD", "")
SESSION_S = 7 * 86400
DUP_WINDOW_S = 10  # the same packet heard twice within seconds (two gateways) is a duplicate, not an attack
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
        CREATE TABLE IF NOT EXISTS auth_state (node INTEGER PRIMARY KEY, epoch INTEGER, counter INTEGER,
                                               last_raw TEXT, last_ts REAL);
        CREATE TABLE IF NOT EXISTS auth_epochs (node INTEGER, epoch INTEGER, PRIMARY KEY (node, epoch));
        CREATE TABLE IF NOT EXISTS security (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, node INTEGER,
                                             reason TEXT, detail TEXT, raw TEXT, demo INTEGER);
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


# ------------------------------------------------------------------ report signing
def load_keys() -> dict[int, bytes]:
    """keys.json: {"1": "<64 hex digits>", ...}. Same key as the node's secrets.conf."""
    keys: dict[int, bytes] = {}
    if KEYS_PATH.exists():
        for node, hexkey in json.loads(KEYS_PATH.read_text()).items():
            keys[int(node)] = bytes.fromhex(hexkey)
    return keys


KEYS = load_keys()


def demo_key(node: int) -> bytes:
    """Fixed, public keys for the simulator only. Never use them on real nodes."""
    return hashlib.sha256(f"sylvaecho-demo-key-{node}".encode()).digest()


class Rejected(Exception):
    def __init__(self, reason: str, detail: str, status: int):
        super().__init__(detail)
        self.reason, self.detail, self.status = reason, detail, status


class Duplicate(Exception):
    pass


def verify(report: dict[str, Any]) -> dict[str, Any]:
    """
    Check a gateway report. Returns the report to store, rebuilt from the raw
    bytes when they are present (the raw bytes are what the tag protects).
    Raises Rejected for unsigned/forged/replayed packets from keyed nodes and
    Duplicate for the same packet heard twice.
    """
    raw_hex = report.get("raw")
    node = report.get("node")
    if raw_hex:
        try:
            raw = bytes.fromhex(raw_hex)
            decoded = protocol.decode(raw)
        except ValueError as e:
            raise Rejected("malformed", f"raw packet does not decode: {e}", 422)
        node = decoded["node"]
        merged = {**decoded, **{k: report[k] for k in ("rssi", "snr", "demo") if k in report}}
    else:
        raw, merged = None, dict(report)
    key = KEYS.get(node) if node is not None else None
    if key is None and DEMO and node in NODE_NAMES:
        key = demo_key(node)  # the simulated trees always sign, so attacks on them are caught
    if key is None:
        merged["verified"] = False
        return merged

    if raw is None or "auth" not in merged:
        raise Rejected("unsigned", "unsigned packet from a node that has a key", 403)
    if not protocol.tag_ok(raw, key):
        raise Rejected("bad_tag", "authentication tag does not match (forged or altered)", 403)

    epoch, counter = merged["auth"]["epoch"], merged["auth"]["counter"]
    now = time.time()
    with DB_LOCK:
        st = DB.execute("SELECT * FROM auth_state WHERE node = ?", (node,)).fetchone()
        if st and st["last_raw"] == raw_hex and now - st["last_ts"] < DUP_WINDOW_S:
            raise Duplicate()
        if st and epoch == st["epoch"]:
            if counter <= st["counter"]:
                raise Rejected("replay", f"counter {counter} already used (last {st['counter']})", 409)
        else:
            seen = DB.execute("SELECT 1 FROM auth_epochs WHERE node = ? AND epoch = ?", (node, epoch)).fetchone()
            if seen:
                raise Rejected("replay", f"packet from an earlier boot (epoch {epoch})", 409)
            if st:
                print(f"auth: node {node} rebooted (epoch {st['epoch']} -> {epoch})")
        DB.execute("INSERT OR IGNORE INTO auth_epochs(node, epoch) VALUES(?, ?)", (node, epoch))
        DB.execute(
            "INSERT INTO auth_state(node, epoch, counter, last_raw, last_ts) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(node) DO UPDATE SET epoch=excluded.epoch, counter=excluded.counter, "
            "last_raw=excluded.last_raw, last_ts=excluded.last_ts",
            (node, epoch, counter, raw_hex, now),
        )
        DB.commit()
    merged["verified"] = True
    return merged


def record_security(rej: Rejected, report: dict[str, Any]) -> dict[str, Any]:
    node = report.get("node")
    if report.get("raw"):
        try:
            node = protocol.decode(bytes.fromhex(report["raw"]))["node"]
        except ValueError:
            pass
    ev = {"ts": time.time(), "node": node, "reason": rej.reason, "detail": rej.detail,
          "demo": bool(report.get("demo"))}
    with DB_LOCK:
        DB.execute("INSERT INTO security(ts, node, reason, detail, raw, demo) VALUES(?, ?, ?, ?, ?, ?)",
                   (ev["ts"], node, rej.reason, rej.detail, report.get("raw"), int(ev["demo"])))
        DB.commit()
    HUB.send_threadsafe({"event": "security", "security": ev})
    name = NODE_NAMES.get(node, f"node {node}") if isinstance(node, int) else "unknown node"
    label = {"replay": "Replayed packet rejected", "bad_tag": "Forged packet rejected",
             "unsigned": "Unsigned packet rejected", "malformed": "Malformed packet rejected"}.get(rej.reason, "Packet rejected")
    alerts.notify(node if isinstance(node, int) else -1, f"security-{rej.reason}",
                  f"{'[demo] ' if ev['demo'] else ''}{label}", f"{name}: {rej.detail}", "high", "lock")
    print(f"security: {label} ({name}): {rej.detail}")
    return ev


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


LAST_RISK: dict[int, int] = {}


def phone_alerts(r: dict[str, Any]) -> None:
    """Send phone alerts for this report (rate-limited per node and kind in alerts.py)."""
    node, name = r["node"], NODE_NAMES.get(r["node"], f"Tree {r['node']:02d}")
    demo = "[demo] " if r.get("demo") else ""
    s = get_settings()
    if r["type"] == "logging_alert" and s["guard_armed"]:
        alerts.notify(node, "saw", f"{demo}Chainsaw at {name}",
                      f"Vibration and sound agree (saw score {r['saw']}). Signal {r.get('rssi')} dBm.", "urgent", "rotating_light")
    elif r["type"] == "tilt_alert":
        alerts.notify(node, "tilt", f"{demo}Tree tilt at {name}",
                      f"{r['tilt_x']:+.1f} / {r['tilt_y']:+.1f} degrees from the installed position.", "high", "warning")
    sc1 = r.get("sc1") or {}
    a = sc1.get("alerts") or {}
    if a.get("rain"):
        alerts.notify(node, "rain", f"{demo}Heavy rain at {name}", f"{sc1['rain_mm']['1h']} mm in the last hour.", "high", "cloud_with_rain")
    if a.get("low_batt"):
        alerts.notify(node, "batt", f"{demo}Low battery at {name}", f"{sc1['soc']}% ({sc1['vbat_v']} V).", "default", "battery")
    if a.get("borer"):
        alerts.notify(node, "borer", f"{demo}Borer activity at {name}", f"Borer index {sc1['borer']}.", "high", "bug")
    risk = r.get("risk")
    if risk is not None:
        prev = LAST_RISK.get(node, 0)
        LAST_RISK[node] = risk
        if prev < s["risk_alert"] <= risk:
            alerts.notify(node, "risk", f"{demo}Slope risk {risk} at {name}",
                          f"Above the alert level {s['risk_alert']}: rain {sc1.get('rain_mm', {}).get('24h', '?')} mm in 24 h, soil {sc1.get('soil_pct')}%.",
                          "high", "warning")


def accept(report: dict[str, Any], ts: float | None = None) -> dict[str, Any] | None:
    """Verify, store and push a report. Raises Rejected for a bad packet."""
    try:
        report = verify(report)
    except Duplicate:
        return None
    except Rejected as rej:
        record_security(rej, report)
        raise
    report.pop("raw", None)
    saved = store(report, ts)
    if saved:
        HUB.send_threadsafe({"event": "report", "report": saved})
        phone_alerts(saved)
    return saved


# ------------------------------------------------------------------ MQTT (optional)
def start_mqtt() -> None:
    if not MQTT_HOST:
        return
    import paho.mqtt.client as mqtt  # optional dependency

    def on_message(_c, _u, msg):
        try:
            accept(json.loads(msg.payload))
        except Rejected:
            pass  # already logged as a security event
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
        self.epoch = {n: secrets.randbits(32) for n in NODE_NAMES}  # a fresh "boot" per run
        self.counter = {n: 0 for n in NODE_NAMES}

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
                "status": (2 if rain_since(1 / 24) >= 10 else 0) | (4 if self.soc[node] < 15 else 0),
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

    def signed(self, rep: dict[str, Any]) -> dict[str, Any]:
        """Pack and sign like a real node, so the demo goes through the same checks."""
        n = rep["node"]
        self.counter[n] += 1
        raw = protocol.seal(protocol.pack(rep), demo_key(n), self.epoch[n], self.counter[n])
        return {**rep, "raw": raw.hex()}

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
                try:
                    accept(self.signed(self.report(n, t, kind)))
                except Rejected:
                    pass
            time.sleep(5)


# ------------------------------------------------------------------ login
SESSIONS: dict[str, float] = {}


def session_ok(token: str | None) -> bool:
    if not DASH_PASSWORD:
        return True
    exp = SESSIONS.get(token or "")
    return exp is not None and exp > time.time()


def require_user(authorization: str | None = Header(default=None)) -> None:
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    if not session_ok(token):
        raise HTTPException(401, "login required")


# ------------------------------------------------------------------ API
@asynccontextmanager
async def lifespan(_app: FastAPI):
    HUB.loop = asyncio.get_running_loop()
    start_mqtt()
    if DEMO:
        threading.Thread(target=Sim().run, daemon=True).start()
        print("demo: simulating 3 trees (DEMO=1), packets signed with public demo keys")
    print(f"auth: {len(KEYS)} node key(s) loaded from {KEYS_PATH.name}")
    print(f"login: {'password required' if DASH_PASSWORD else 'OFF (set DASH_PASSWORD)'}; "
          f"phone alerts: {'ntfy on' if alerts.enabled() else 'off (set NTFY_URL)'}")
    yield


app = FastAPI(title="SylvaEcho dashboard API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class Login(BaseModel):
    password: str


@app.get("/api/session")
def session(authorization: str | None = Header(default=None)):
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    return {"auth_required": bool(DASH_PASSWORD), "ok": session_ok(token)}


@app.post("/api/login")
async def login(body: Login):
    if not DASH_PASSWORD:
        return {"token": "", "expires_in": 0}
    if not hmac.compare_digest(body.password.encode(), DASH_PASSWORD.encode()):
        await asyncio.sleep(1.0)  # slow down guessing
        raise HTTPException(401, "wrong password")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = time.time() + SESSION_S
    return {"token": token, "expires_in": SESSION_S}


@app.post("/api/logout", dependencies=[Depends(require_user)])
def logout(authorization: str | None = Header(default=None)):
    SESSIONS.pop((authorization or "")[7:], None)
    return {"ok": True}


@app.post("/api/ingest")
async def ingest(report: dict[str, Any], authorization: str | None = Header(default=None)):
    if INGEST_TOKEN and not hmac.compare_digest((authorization or "").encode(), f"Bearer {INGEST_TOKEN}".encode()):
        raise HTTPException(401, "bad token")
    try:
        saved = await asyncio.to_thread(accept, report)
    except Rejected as rej:
        raise HTTPException(rej.status, {"stored": False, "reason": rej.reason, "detail": rej.detail})
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"stored": saved is not None, "verified": bool(saved and saved.get("verified"))}


@app.get("/api/security", dependencies=[Depends(require_user)])
def security(limit: int = 30):
    with DB_LOCK:
        rows = DB.execute("SELECT ts, node, reason, detail, demo FROM security ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        counts = dict(DB.execute("SELECT reason, COUNT(*) FROM security GROUP BY reason").fetchall())
    return {"events": [dict(r) | {"demo": bool(r["demo"])} for r in rows], "counts": counts,
            "keys": sorted(KEYS), "alerts": {"ntfy": alerts.enabled(), "recent": alerts.sent_log[-10:]}}


@app.get("/api/nodes", dependencies=[Depends(require_user)])
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


@app.get("/api/nodes/{node}/last-packet", dependencies=[Depends(require_user)])
def last_packet(node: int):
    """The last accepted signed packet, as an attacker could record it over the air (for tools/attack_test.py)."""
    with DB_LOCK:
        st = DB.execute("SELECT last_raw, last_ts FROM auth_state WHERE node = ?", (node,)).fetchone()
    if not st:
        raise HTTPException(404, "no signed packet from this node yet")
    return {"node": node, "raw": st["last_raw"], "ts": st["last_ts"]}


@app.get("/api/nodes/{node}/history", dependencies=[Depends(require_user)])
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


@app.get("/api/events", dependencies=[Depends(require_user)])
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
    # Rejected packets are part of the story too.
    with DB_LOCK:
        sec = DB.execute("SELECT ts, node, reason, detail, demo FROM security WHERE ts >= ? ORDER BY ts DESC LIMIT 10",
                         (time.time() - 86400 * 2,)).fetchall()
    for e in sec:
        if node and e["node"] != node:
            continue
        out.append({"kind": "security", "title": {"replay": "Replay blocked", "bad_tag": "Forgery blocked"}.get(e["reason"], "Packet blocked"),
                    "detail": e["detail"], "node": e["node"], "name": NODE_NAMES.get(e["node"], f"node {e['node']}"),
                    "ts": e["ts"], "demo": bool(e["demo"])})
    out.sort(key=lambda x: -x["ts"])
    return {"events": out[:limit]}


class SettingsPatch(BaseModel):
    risk_alert: int | None = None
    rain_alert_mm_h: float | None = None
    low_batt_pct: int | None = None
    guard_armed: bool | None = None
    energy_saver: bool | None = None
    storm_watch: bool | None = None


@app.get("/api/settings", dependencies=[Depends(require_user)])
def settings_get():
    return get_settings()


@app.put("/api/settings", dependencies=[Depends(require_user)])
async def settings_put(patch: SettingsPatch):
    s = put_settings({k: v for k, v in patch.model_dump().items() if v is not None})
    await HUB.send({"event": "settings", "settings": s})
    return s


@app.websocket("/ws")
async def ws(sock: WebSocket):
    if not session_ok(sock.query_params.get("token")):
        await sock.close(code=4401)
        return
    await sock.accept()
    HUB.clients.add(sock)
    try:
        while True:
            await sock.receive_text()  # keep-alive pings from the browser
    except WebSocketDisconnect:
        HUB.clients.discard(sock)
