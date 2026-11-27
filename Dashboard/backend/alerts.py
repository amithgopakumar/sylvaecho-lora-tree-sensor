"""
Phone alerts through ntfy (https://ntfy.sh, or a self-hosted ntfy server).

Set NTFY_URL to a topic URL, e.g. https://ntfy.sh/sylvaecho-<long-random-name>,
and subscribe to the same topic in the ntfy phone app. Anyone who knows a
public topic name can read it, so use a long random name or your own server
(NTFY_TOKEN for an access token). Leave NTFY_URL empty to switch alerts off.

Uses only the standard library; sends in a background thread and never blocks
report ingest.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request

NTFY_URL = os.getenv("NTFY_URL", "")
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "")
REPEAT_S = int(os.getenv("ALERT_REPEAT_S", "600"))  # same alert, same node: at most every 10 min

_last: dict[tuple[int, str], float] = {}
_lock = threading.Lock()
sent_log: list[dict] = []  # last few alerts, for the dashboard and tests


def enabled() -> bool:
    return bool(NTFY_URL)


def _post(title: str, message: str, priority: str, tags: str) -> None:
    req = urllib.request.Request(NTFY_URL, data=message.encode(), method="POST")
    # ntfy headers must be ASCII
    req.add_header("Title", title.encode("ascii", "replace").decode())
    req.add_header("Priority", priority)
    req.add_header("Tags", tags)
    if NTFY_TOKEN:
        req.add_header("Authorization", f"Bearer {NTFY_TOKEN}")
    try:
        urllib.request.urlopen(req, timeout=8).close()
    except Exception as e:  # network down: log and move on
        print(f"alert: ntfy send failed: {e}")


def notify(node: int, kind: str, title: str, message: str, priority: str = "high", tags: str = "warning") -> bool:
    """Queue a phone alert. Returns False when rate-limited."""
    now = time.time()
    with _lock:
        if now - _last.get((node, kind), 0) < REPEAT_S:
            return False
        _last[(node, kind)] = now
        sent_log.append({"ts": now, "node": node, "kind": kind, "title": title, "message": message})
        del sent_log[:-50]
    print(f"alert: [{kind}] {title}: {message}")
    if enabled():
        threading.Thread(target=_post, args=(title, message, priority, tags), daemon=True).start()
    return True
