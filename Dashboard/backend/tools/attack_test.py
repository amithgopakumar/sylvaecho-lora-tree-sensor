"""
Attack test for the EP5C video: replay, forge and strip a real signed packet,
and show the server rejecting each one.

    .venv/bin/python tools/attack_test.py --node 1 [--url http://localhost:8000] [--password ...] [--ingest-token ...]

Uses only the standard library. It takes the node's last accepted packet (what
an attacker could record over the air) and sends:
  1. the same packet again                 -> 409 replay
  2. the packet with one byte changed      -> 403 bad_tag   (forged chainsaw alert)
  3. the packet with the signature removed -> 403 unsigned
"""
import argparse
import json
import urllib.error
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("--node", type=int, default=1)
p.add_argument("--url", default="http://localhost:8000")
p.add_argument("--password", default="")
p.add_argument("--ingest-token", default="")
a = p.parse_args()


def call(method, path, body=None, token=""):
    req = urllib.request.Request(a.url + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("content-type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


session = ""
if a.password:
    code, body = call("POST", "/api/login", {"password": a.password})
    session = body.get("token", "")
code, pkt = call("GET", f"/api/nodes/{a.node}/last-packet", token=session)
if code != 200:
    raise SystemExit(f"no captured packet for node {a.node}: {code} {pkt}")
raw = bytes.fromhex(pkt["raw"])
print(f"captured packet from node {a.node}: {len(raw)} bytes")
# The server ignores the same packet heard twice within 10 s (two gateways), so wait
# like a real attacker would before replaying it.
import time
print("waiting 12 s before replaying ...")
time.sleep(12)

forged = bytearray(raw)
forged[0] = 0x02        # type -> logging_alert
forged[6] = 99          # saw score 99
stripped = bytearray(raw[:-16])
stripped[18] &= ~0x02

tests = [
    ("replay the same packet", raw, 409),
    ("forge a chainsaw alert (2 bytes changed)", bytes(forged), 403),
    ("strip the signature", bytes(stripped), 403),
]
ok = True
for name, data, want in tests:
    code, body = call("POST", "/api/ingest", {"raw": data.hex(), "rssi": -95, "snr": 4.0}, token=a.ingest_token)
    detail = body.get("detail", body)
    reason = detail.get("reason") if isinstance(detail, dict) else detail
    good = code == want
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  {name:42s} -> HTTP {code} {reason}")
print("all attacks rejected" if ok else "SOME ATTACKS WERE NOT REJECTED")
raise SystemExit(0 if ok else 1)
