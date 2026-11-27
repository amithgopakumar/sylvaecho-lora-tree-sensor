"""
SylvaEcho report format, in Python (mirror of Firmware/src/payload.c, auth.c
and Gateway/src/decode.cpp).

  19-byte base report
  + 24-byte SC-1 block            when byte 18 has EXT_SC1
  + 16-byte auth trailer (last)   when byte 18 has EXT_AUTH:
        u32 boot epoch, u32 counter, 8-byte HMAC-SHA256 tag over all bytes before it
"""
from __future__ import annotations

import hashlib
import hmac
import struct
from typing import Any

EXT_SC1 = 0x01
EXT_AUTH = 0x02
BASE_LEN, SC1_LEN, AUTH_LEN, TAG_LEN = 19, 24, 16, 8
TYPES = {1: "report", 2: "logging_alert", 3: "tilt_alert", 4: "boot", 5: "sc1_alert"}
TYPE_IDS = {v: k for k, v in TYPES.items()}
TEMP_INVALID = -32768
RAIN_MM_PER_TIP = 0.2


def decode(raw: bytes) -> dict[str, Any]:
    """Raw packet -> the same dict shape the gateway produces (without rssi/snr)."""
    if len(raw) < BASE_LEN or raw[0] not in TYPES:
        raise ValueError("not a SylvaEcho report")
    (typ, flags, node, buzz, bird, saw, tx, ty, temp, rh, press, seq, ext) = struct.unpack_from(
        "<BBHBBBhhhBHHB", raw, 0
    )
    r: dict[str, Any] = {
        "node": node, "seq": seq, "type": TYPES[typ],
        "flags": {"charge_temp": bool(flags & 1), "sensor_fault": bool(flags & 2)},
        "buzz": buzz, "bird": bird, "saw": saw,
        "tilt_x": round(tx / 10, 1), "tilt_y": round(ty / 10, 1),
        "temp_c": round(temp / 100, 2), "rh": rh, "press_hpa": round(press / 10, 1),
    }
    body = len(raw)
    if ext & EXT_AUTH and len(raw) >= BASE_LEN + AUTH_LEN:
        body -= AUTH_LEN
        epoch, counter = struct.unpack_from("<II", raw, body)
        r["auth"] = {"epoch": epoch, "counter": counter}
    if ext & EXT_SC1 and body >= BASE_LEN + SC1_LEN:
        (vb, ib, soc, st, tc, ts, soil, borer, *rain) = struct.unpack_from("<HhBBhhBB6H", raw, BASE_LEN)
        r["sc1"] = {
            "vbat_v": vb / 1000, "ibat_ma": ib / 10, "soc": soc, "status": st,
            "cell_c": None if tc == TEMP_INVALID else tc / 100,
            "soil_c": None if ts == TEMP_INVALID else ts / 100,
            "soil_pct": None if soil == 0xFF else soil,
            "borer": borer,
            "rain_mm": dict(zip(["1h", "24h", "3d", "5d", "7d", "15d"], [round(t * RAIN_MM_PER_TIP, 1) for t in rain])),
            "alerts": {"rain": bool(st & 2), "low_batt": bool(st & 4), "borer": bool(st & 8)},
        }
    return r


def tag_ok(raw: bytes, key: bytes) -> bool:
    if not raw[18] & EXT_AUTH or len(raw) < BASE_LEN + AUTH_LEN:
        return False
    expect = hmac.new(key, raw[:-TAG_LEN], hashlib.sha256).digest()[:TAG_LEN]
    return hmac.compare_digest(expect, raw[-TAG_LEN:])


def pack(r: dict[str, Any]) -> bytes:
    """Gateway-style dict -> packet bytes without the auth trailer (used by the demo simulator)."""
    flags = (1 if r.get("flags", {}).get("charge_temp") else 0) | (2 if r.get("flags", {}).get("sensor_fault") else 0)
    sc1 = r.get("sc1")
    out = struct.pack(
        "<BBHBBBhhhBHHB", TYPE_IDS[r["type"]], flags, r["node"], r["buzz"], r["bird"], r["saw"],
        round(r["tilt_x"] * 10), round(r["tilt_y"] * 10), round(r["temp_c"] * 100), r["rh"],
        round(r["press_hpa"] * 10), r["seq"], EXT_SC1 if sc1 else 0,
    )
    if sc1:
        rain = [round(sc1["rain_mm"][k] / RAIN_MM_PER_TIP) for k in ["1h", "24h", "3d", "5d", "7d", "15d"]]
        out += struct.pack(
            "<HhBBhhBB6H", round(sc1["vbat_v"] * 1000), round(sc1["ibat_ma"] * 10), sc1["soc"], sc1["status"],
            TEMP_INVALID if sc1["cell_c"] is None else round(sc1["cell_c"] * 100),
            TEMP_INVALID if sc1["soil_c"] is None else round(sc1["soil_c"] * 100),
            0xFF if sc1["soil_pct"] is None else sc1["soil_pct"], sc1["borer"], *rain,
        )
    return out


def seal(body: bytes, key: bytes, epoch: int, counter: int) -> bytes:
    """Append the auth trailer, exactly like auth_seal() on the node."""
    b = bytearray(body)
    b[18] |= EXT_AUTH
    b += struct.pack("<II", epoch, counter)
    b += hmac.new(key, bytes(b), hashlib.sha256).digest()[:TAG_LEN]
    return bytes(b)
