"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Ic from "./icons";
import {
  API, ago, clamp, getJSON, hhmm, hourLabel, hourOf, nightness, putSettings, sampleAt,
  type EventItem, type NodeSummary, type Report, type Settings,
} from "./lib";

/* ------------------------------------------------------------ metrics */
type MetricId = "risk" | "rain" | "power" | "sound" | "climate";
type Metric = {
  id: MetricId; title: string; tip: string; unit: string; min: number; max: number;
  setting?: keyof Pick<Settings, "risk_alert" | "rain_alert_mm_h" | "low_batt_pct">;
  tmin?: number; tmax?: number; below?: boolean; icon: () => React.JSX.Element;
};
const METRICS: Metric[] = [
  { id: "risk", title: "Slope risk", tip: "Slope risk", unit: "", min: 0, max: 100, setting: "risk_alert", tmin: 20, tmax: 95, icon: Ic.Mountain },
  { id: "rain", title: "Rainfall", tip: "Rain", unit: " mm/h", min: 0, max: 40, setting: "rain_alert_mm_h", tmin: 2, tmax: 40, icon: Ic.Rain },
  { id: "power", title: "Battery", tip: "Power", unit: "%", min: 0, max: 100, setting: "low_batt_pct", tmin: 5, tmax: 50, below: true, icon: Ic.Battery },
  { id: "sound", title: "Bird activity", tip: "Soundscape", unit: "", min: 0, max: 100, icon: Ic.Wave },
  { id: "climate", title: "Air temperature", tip: "Climate", unit: "°", min: 0, max: 50, icon: Ic.Thermo },
];

function metricValue(id: MetricId, reps: Report[]): number | null {
  const vals = reps.map((r) => {
    switch (id) {
      case "risk": return r.risk;
      case "rain": return r.sc1?.rain_mm["1h"] ?? null;
      case "power": return r.sc1?.soc ?? null;
      case "sound": return r.bird;
      case "climate": return r.temp_c;
    }
  }).filter((v): v is number => v != null);
  if (!vals.length) return null;
  if (id === "power") return Math.min(...vals);
  if (id === "risk" || id === "rain") return Math.max(...vals);
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/* ------------------------------------------------------- small helpers */
function useAnimated(target: number, ms = 700) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  const cur = useRef(target);
  useEffect(() => {
    from.current = cur.current;
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const k = clamp((t - t0) / ms, 0, 1); /* rAF time can precede t0 */
      const e = 1 - Math.pow(1 - k, 3);
      cur.current = from.current + (target - from.current) * e;
      setV(cur.current);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    /* Frames stop in background tabs: make sure the value still lands. */
    const done = setTimeout(() => { cancelAnimationFrame(raf); cur.current = target; setV(target); }, ms + 80);
    return () => { cancelAnimationFrame(raf); clearTimeout(done); };
  }, [target, ms]);
  return v;
}

const A0 = -135, A1 = 135, R = 104, C = 130;
const pt = (deg: number, r = R) => {
  const a = (deg * Math.PI) / 180;
  return [C + r * Math.sin(a), C - r * Math.cos(a)] as const;
};
const arc = (d0: number, d1: number) => {
  const [x0, y0] = pt(d0), [x1, y1] = pt(d1);
  return `M${x0} ${y0} A${R} ${R} 0 ${d1 - d0 > 180 ? 1 : 0} 1 ${x1} ${y1}`;
};

const ART: Record<string, [string, string, () => React.JSX.Element]> = {
  bird: ["#e3fbb0", "#3cc4b4", Ic.Note],
  buzz: ["#fff1a8", "#8ef0d6", Ic.Sun],
  saw: ["#ffb25e", "#ff5e5e", Ic.Saw],
  rain: ["#a8d8ff", "#3c7bc4", Ic.Rain],
  borer: ["#d9c3a0", "#7a5c3c", Ic.Wave],
  tilt: ["#ffd08a", "#c46c3c", Ic.Mountain],
};

function Art({ kind, seed }: { kind: string; seed: number }) {
  const [a, b, Icon] = ART[kind] ?? ART.bird;
  const blobs = Array.from({ length: 5 }, (_, i) => {
    const s = Math.sin(seed * 9.3 + i * 4.1);
    return { x: 50 + 40 * s, y: 50 + 40 * Math.cos(seed * 3.7 + i * 2.3), r: 18 + 14 * Math.abs(s) };
  });
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`g${seed}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={a} /><stop offset="1" stopColor={b} /></linearGradient>
        <filter id={`b${seed}`}><feGaussianBlur stdDeviation="7" /></filter>
      </defs>
      <rect width="100" height="100" fill={`url(#g${seed})`} />
      <g filter={`url(#b${seed})`} opacity="0.55">
        {blobs.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={p.r} fill={i % 2 ? "#fff" : b} />)}
      </g>
      <svg x="30" y="30" width="40" height="40" color="#12261f" opacity="0.85"><Icon /></svg>
    </svg>
  );
}

/* ================================================================ page */
export default function Dashboard() {
  const [nodes, setNodes] = useState<NodeSummary[]>([]);
  const [hist, setHist] = useState<Record<number, Report[]>>({});
  const [events, setEvents] = useState<EventItem[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [dayS, setDayS] = useState(86400);
  const [demo, setDemo] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const [tab, setTab] = useState(0);
  const [metric, setMetric] = useState<MetricId>("risk");
  const [scrub, setScrub] = useState(20);
  const [dragging, setDragging] = useState(false);
  const [thrDrag, setThrDrag] = useState<number | null>(null);
  const [muted, setMuted] = useState(false);
  const [camBig, setCamBig] = useState(false);
  const [swap, setSwap] = useState(0);
  const [dip, setDip] = useState(false);
  const [spin, setSpin] = useState(false);
  const [ripple, setRipple] = useState<{ x: number; y: number; k: number } | null>(null);
  const [alarmUntil, setAlarmUntil] = useState(0);
  const [toast, setToast] = useState<{ msg: string; warn?: boolean; k: number } | null>(null);
  const [ready, setReady] = useState(false);

  const [ev, setEv] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [dwell, setDwell] = useState(0);

  const tabsRef = useRef<HTMLDivElement>(null);
  const [ind, setInd] = useState({ left: 6, width: 120 });
  const roomRef = useRef<HTMLDivElement>(null);
  const uiRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const settingsRef = useRef<Settings | null>(null);
  settingsRef.current = settings;
  const mutedRef = useRef(muted);
  mutedRef.current = muted;

  const rec = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("rec");

  /* ---------------------------------------------------------- toast */
  const say = useCallback((msg: string, warn = false) => setToast({ msg, warn, k: Date.now() }), []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast((x) => (x && x.k === toast.k ? null : x)), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  /* --------------------------------------------------------- loading */
  const loadNodes = useCallback(async () => {
    try {
      const d = await getJSON<{ nodes: NodeSummary[]; demo: boolean; day_s: number; settings: Settings; server_time: number }>("/api/nodes");
      setNodes(d.nodes);
      setDemo(d.demo);
      setDayS(d.day_s);
      setSettings(d.settings);
      setOnline(true);
      return d.nodes;
    } catch {
      setOnline(false);
      return null;
    }
  }, []);

  const loadHist = useCallback(async (list: NodeSummary[], day: number) => {
    const out: Record<number, Report[]> = {};
    await Promise.all(list.map(async (n) => {
      try {
        out[n.node] = (await getJSON<{ reports: Report[] }>(`/api/nodes/${n.node}/history?hours=${day / 3600}`)).reports;
      } catch { /* keep going */ }
    }));
    setHist(out);
  }, []);

  const loadEvents = useCallback(async () => {
    try { setEvents((await getJSON<{ events: EventItem[] }>("/api/events?limit=24")).events); } catch { /* offline */ }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const list = await loadNodes();
      if (list && alive) {
        const d = await getJSON<{ day_s: number }>("/api/nodes").catch(() => ({ day_s: 86400 }));
        loadHist(list, d.day_s);
        loadEvents();
      }
    })();
    const t1 = setInterval(async () => { const l = await loadNodes(); if (l) loadHist(l, dayS); }, 60000);
    const t2 = setInterval(loadEvents, 30000);
    const t3 = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => { alive = false; clearInterval(t1); clearInterval(t2); clearInterval(t3); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ------------------------------------------------------ live socket */
  useEffect(() => {
    let ws: WebSocket | null = null, ping: ReturnType<typeof setInterval>, retry: ReturnType<typeof setTimeout>;
    let refresh: ReturnType<typeof setTimeout> | null = null;
    const open = () => {
      ws = new WebSocket(API.replace(/^http/, "ws") + "/ws");
      ws.onopen = () => { ping = setInterval(() => ws?.readyState === 1 && ws.send("ping"), 20000); };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.event === "settings") setSettings(msg.settings);
        if (msg.event !== "report") return;
        const r: Report = msg.report;
        setHist((h) => ({ ...h, [r.node]: [...(h[r.node] ?? []), r].slice(-800) }));
        if (!refresh) refresh = setTimeout(() => { refresh = null; loadNodes(); }, 1500);
        if (r.type === "logging_alert" && settingsRef.current?.guard_armed) {
          setAlarmUntil(Date.now() + 120000);
          loadEvents();
          if (!mutedRef.current) say(`Chainsaw confirmed at ${r.node === 1 ? "Teak Ridge" : `node ${r.node}`}`, true);
        }
      };
      ws.onclose = () => { clearInterval(ping); retry = setTimeout(open, 3000); };
      ws.onerror = () => ws?.close();
    };
    open();
    return () => { clearTimeout(retry); clearInterval(ping); if (ws) { ws.onclose = null; ws.close(); } };
  }, [loadNodes, loadEvents, say]);

  /* ---------------------------------------------------------- intro */
  useEffect(() => {
    const t = setTimeout(() => setReady(true), 80);
    const t2 = setTimeout(() => setScrub(100), 1500);
    return () => { clearTimeout(t); clearTimeout(t2); };
  }, []);

  /* --------------------------------------------------------- parallax */
  useEffect(() => {
    if (rec) document.body.classList.add("rec");
    /* ?shot: flat, still layout for screenshots (no 3D tilt, no parallax). */
    const shot = new URLSearchParams(location.search).has("shot");
    if (shot) { document.body.classList.add("shot"); return; }
    let tx = 0, ty = 0, sx = 0, sy = 0, raf = 0;
    const move = (e: PointerEvent) => { tx = (e.clientX / innerWidth) * 2 - 1; ty = (e.clientY / innerHeight) * 2 - 1; };
    const loop = () => {
      sx += (tx - sx) * 0.05; sy += (ty - sy) * 0.05;
      const flat = innerWidth <= 900;
      if (roomRef.current) roomRef.current.style.transform = flat ? "" : `scale(1.04) translate(${sx * 18}px, ${sy * 12}px)`;
      if (uiRef.current) uiRef.current.style.transform = flat ? "" : `rotateY(${sx * 4}deg) rotateX(${-sy * 3}deg) translate(${sx * -14}px, ${sy * -10}px)`;
      raf = requestAnimationFrame(loop);
    };
    addEventListener("pointermove", move);
    raf = requestAnimationFrame(loop);
    return () => { removeEventListener("pointermove", move); cancelAnimationFrame(raf); };
  }, [rec]);

  /* ------------------------------------------------------- tab bar */
  const tabs = useMemo(() => [{ id: 0, name: "All trees" }, ...nodes.map((n) => ({ id: n.node, name: n.name }))], [nodes]);
  useEffect(() => {
    const place = () => {
      const el = tabsRef.current?.querySelector<HTMLElement>(`[data-tab="${tab}"]`);
      if (el) setInd({ left: el.offsetLeft, width: el.offsetWidth });
    };
    place();
    addEventListener("resize", place);
    return () => removeEventListener("resize", place);
  }, [tab, tabs.length]);

  const pickTab = (id: number) => {
    if (id === tab) return;
    setTab(id);
    setSwap((s) => s + 1);
    setDip(true);
    setTimeout(() => setDip(false), 650);
    const n = nodes.find((x) => x.node === id);
    say(id === 0 ? `All trees · ${nodes.filter((x) => x.online).length} of ${nodes.length} online`
      : `${n?.name} · ${n?.online ? "online" : "offline"}, last report ${ago(n?.age_s ?? null)}`);
  };

  /* ------------------------------------------------------------ view */
  const live = scrub >= 99.5;
  const scrubTs = now - (1 - scrub / 100) * dayS;
  const shown = tab === 0 ? nodes : nodes.filter((n) => n.node === tab);
  const reps: Report[] = shown.map((n) => {
    if (live) return n.latest;
    return sampleAt(hist[n.node] ?? [], scrubTs) ?? n.latest;
  }).filter((r): r is Report => !!r);
  const sc1Reps: Report[] = shown.map((n, i) => (reps[i]?.sc1 ? reps[i] : n.latest_sc1)).filter((r): r is Report => !!r?.sc1);
  const focus = tab === 0 ? null : shown[0] ?? null;
  const rep = reps[0] ?? null;
  const sc1 = (tab === 0 ? [...sc1Reps].sort((a, b) => (a.sc1!.soc - b.sc1!.soc))[0] : sc1Reps[0])?.sc1 ?? null;
  const anyOnline = shown.some((n) => n.online);

  const M = METRICS.find((m) => m.id === metric)!;
  const raw = metricValue(metric, metric === "power" || metric === "rain" ? sc1Reps : reps);
  const value = raw ?? M.min;
  const thr = M.setting && settings ? (thrDrag ?? (settings[M.setting] as number)) : null;
  const shownVal = useAnimated(ready ? value : M.min);
  const frac = clamp((shownVal - M.min) / (M.max - M.min), 0, 1);
  const tfrac = thr != null ? clamp((thr - M.min) / (M.max - M.min), 0, 1) : null;

  let chip: [string, string] = ["Stable", "var(--m2)"];
  if (online === false) chip = ["Backend offline", "#9aa39a"];
  else if (!shown.length) chip = ["Waiting for nodes", "#9aa39a"];
  else if (muted) chip = ["Alerts muted", "#9aa39a"];
  else if (live && !anyOnline) chip = ["Offline", "#9aa39a"];
  else if (metric === "risk" && thr != null) chip = value >= thr ? ["Warning", "var(--warn)"] : value >= thr * 0.66 ? ["Watch", "var(--m1)"] : ["Stable", "var(--m2)"];
  else if (metric === "rain" && thr != null) chip = value >= thr ? ["Heavy rain", "var(--warn)"] : value > 0 ? ["Raining", "var(--m1)"] : ["Dry", "var(--m2)"];
  else if (metric === "power" && thr != null) chip = value <= thr ? ["Low battery", "var(--warn)"] : (sc1?.ibat_ma ?? 0) < 0 ? ["Charging", "var(--m2)"] : ["Draining", "var(--m1)"];
  else if (metric === "sound") chip = value >= 80 ? ["Dawn chorus", "var(--m1)"] : value >= 40 ? ["Active", "var(--m2)"] : ["Quiet", "#9aa39a"];
  else if (metric === "climate") chip = value >= 40 ? ["Hot", "var(--warn)"] : ["Normal", "var(--m2)"];

  /* ------------------------------------------------------- dial drag */
  const ringRef = useRef<HTMLDivElement>(null);
  const angleToThr = (e: React.PointerEvent) => {
    const b = ringRef.current!.getBoundingClientRect();
    const dx = e.clientX - (b.left + b.width / 2), dy = e.clientY - (b.top + b.height / 2);
    let a = (Math.atan2(dx, -dy) * 180) / Math.PI;
    if (a > A1 || a < A0) a = Math.abs(a - A1) < Math.abs(a - A0 - 360) && a > 0 ? A1 : a > 0 ? A1 : A0;
    const f = (clamp(a, A0, A1) - A0) / (A1 - A0);
    const v = M.min + f * (M.max - M.min);
    return Math.round(clamp(v, M.tmin ?? M.min, M.tmax ?? M.max));
  };
  const ringDown = (e: React.PointerEvent) => {
    if (!M.setting || muted || !settings) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setThrDrag(angleToThr(e));
  };
  const ringMove = (e: React.PointerEvent) => { if (thrDrag != null) setThrDrag(angleToThr(e)); };
  const ringUp = async () => {
    if (thrDrag == null || !M.setting) return;
    const v = thrDrag;
    try {
      setSettings(await putSettings({ [M.setting]: v }));
      say(`${M.title} alert set to ${v}${M.unit}`);
    } catch { say("Could not save: backend offline", true); }
    setThrDrag(null);
  };

  /* ------------------------------------------------------ timeline */
  const sliderDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    setScrub(clamp(((e.clientX - b.left) / b.width) * 100, 0, 100));
  };
  const hourNow = hourOf(live ? now : scrubTs, dayS);
  const night = nightness(hourNow);

  /* ----------------------------------------------------- spectrogram */
  const repRef = useRef(rep);
  repRef.current = rep;
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d")!;
    let raf = 0, t = 0;
    const W = 420, H = 90, BINS = 30;
    cv.width = W; cv.height = H;
    const draw = () => {
      t++;
      if (t % 2 === 0) {
        const img = ctx.getImageData(2, 0, W - 2, H);
        ctx.putImageData(img, 0, 0);
        ctx.clearRect(W - 2, 0, 2, H);
        const r = repRef.current;
        for (let i = 0; i < BINS; i++) {
          const f = i / BINS; // 0 = low frequency (bottom)
          let e = 0.08 + Math.random() * 0.12;
          if (r) {
            e += (r.buzz / 100) * Math.exp(-((f - 0.12) ** 2) / 0.004) * (0.6 + Math.random() * 0.6);
            e += (r.bird / 100) * Math.exp(-((f - 0.62) ** 2) / 0.02) * (Math.random() < 0.35 ? 1.2 : 0.3);
            e += (r.saw / 100) * Math.exp(-((f - 0.25) ** 2) / 0.03) * 1.2;
          }
          ctx.fillStyle = `rgba(${Math.round(142 + 85 * (1 - f))}, 240, ${Math.round(176 + 40 * f)}, ${clamp(e, 0, 1) * 0.85})`;
          ctx.fillRect(W - 2, H - (i + 1) * (H / BINS), 2, H / BINS - 0.5);
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

  /* ----------------------------------------------------- soundscape */
  const evList = tab === 0 ? events : events.filter((e) => e.node === tab);
  const cur = evList.length ? evList[ev % evList.length] : null;
  const DWELL = 6;
  useEffect(() => {
    if (!playing || !evList.length) return;
    const t = setInterval(() => setDwell((d) => {
      if (d + 1 >= DWELL) { setEv((i) => (i + 1) % evList.length); return 0; }
      return d + 1;
    }), 1000);
    return () => clearInterval(t);
  }, [playing, evList.length]);
  const nextEv = () => { setEv((i) => (i + 1) % Math.max(1, evList.length)); setDwell(0); };
  const prevEv = () => { if (dwell > 2) setDwell(0); else { setEv((i) => (i - 1 + evList.length) % Math.max(1, evList.length)); setDwell(0); } };

  /* --------------------------------------------------------- actions */
  const stormOn = settings?.storm_watch ?? false;
  const storm = async (e: React.MouseEvent) => {
    const b = (e.currentTarget.closest(".scene") as HTMLElement).getBoundingClientRect();
    setRipple({ x: e.clientX - b.left, y: e.clientY - b.top, k: Date.now() });
    setSpin(true);
    setTimeout(() => setSpin(false), 2400);
    try {
      if (!stormOn) {
        setSettings(await putSettings({ storm_watch: true, rain_alert_mm_h: 6, risk_alert: 45 }));
        setMetric("rain");
        setScrub(100);
        setMuted(false);
        say("Storm watch · rain alert 6 mm/h, risk alert 45, live view");
      } else {
        setSettings(await putSettings({ storm_watch: false, rain_alert_mm_h: 10, risk_alert: 60 }));
        say("Storm watch off · thresholds back to 10 mm/h and 60");
      }
    } catch { say("Could not save: backend offline", true); }
  };
  const toggle = async (k: "guard_armed" | "energy_saver") => {
    if (!settings) return;
    try {
      const s = await putSettings({ [k]: !settings[k] });
      setSettings(s);
      if (k === "guard_armed") say(s.guard_armed ? "Chainsaw guard armed" : "Chainsaw guard off: alerts are still logged", !s.guard_armed);
      else say(s.energy_saver ? "Energy saver on · gateway asks nodes to report less often" : "Energy saver off");
    } catch { say("Could not save: backend offline", true); }
  };

  const lastSaw = events.find((e) => e.kind === "saw" && (tab === 0 || e.node === tab));
  const alarm = Date.now() < alarmUntil && !!settings?.guard_armed;
  const clock = hhmm(new Date(now * 1000), true);
  const charging = (sc1?.ibat_ma ?? 0) < 0;
  const scrubLabel = live ? "Now" : hourLabel(hourNow);

  /* --------------------------------------------------- ?rec cursor */
  const [cur2, setCur2] = useState({ x: -100, y: -100, hot: false, down: false });
  useEffect(() => {
    if (!rec) return;
    const mv = (e: PointerEvent) => setCur2((c) => ({ ...c, x: e.clientX, y: e.clientY, hot: !!(e.target as HTMLElement).closest("button,.ring,.slider,.cam") }));
    const dn = () => setCur2((c) => ({ ...c, down: true }));
    const up = () => setCur2((c) => ({ ...c, down: false }));
    addEventListener("pointermove", mv); addEventListener("pointerdown", dn); addEventListener("pointerup", up);
    return () => { removeEventListener("pointermove", mv); removeEventListener("pointerdown", dn); removeEventListener("pointerup", up); };
  }, [rec]);

  /* ============================================================ render */
  return (
    <main className={ready ? "ready" : ""}>
      <div id="room" ref={roomRef}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="still" src="/forest.jpg" alt="" />
        <div className="rays" style={{ opacity: 0.35 * (1 - night) }} />
        <div className="sun" style={{ opacity: 1 - night }} />
        {Array.from({ length: 14 }, (_, i) => (
          <i key={i} className="mote" style={{ left: `${(i * 37) % 100}%`, top: `${40 + ((i * 53) % 55)}%`, animationDuration: `${9 + (i % 5) * 2}s`, animationDelay: `${-i * 1.3}s`, opacity: 1 - night }} />
        ))}
        <div className="vignette" />
        <div className="dim" style={{ opacity: night * 0.62 }} />
      </div>

      <div id="stage">
        <div id="ui" ref={uiRef}>
          <div className="brand"><i><Ic.Leaf /></i><div>SylvaEcho<small>Canopy · forest guardian</small></div></div>
          <div className={`mode glass ${online ? "" : "off"}`}>
            <span className="dot" />{online === false ? "Backend offline" : demo ? "Demo data" : "Live gateway"}
          </div>

          <nav className="tabs glass" ref={tabsRef}>
            <span className="ind" style={{ left: ind.left, width: ind.width }} />
            {tabs.map((t) => {
              const n = nodes.find((x) => x.node === t.id);
              return (
                <button key={t.id} data-tab={t.id} className={`tab ${tab === t.id ? "on" : ""}`} onClick={() => pickTab(t.id)}>
                  {t.id === 0 ? <Ic.Leaf /> : <Ic.Tree />}
                  {t.name}
                  {n && <span className={`live ${n.online ? "" : "off"}`} />}
                </button>
              );
            })}
            <button className="tab add" aria-label="Add node" onClick={() => say("New nodes appear here as soon as the gateway hears them")}><Ic.Plus /></button>
          </nav>

          <div className="rail glass">
            {METRICS.map((m) => (
              <button key={m.id} className={metric === m.id ? "on" : ""} onClick={() => { setMetric(m.id); setThrDrag(null); }} aria-label={m.tip}>
                <m.icon />
                <span className="tip glass">{m.tip}</span>
              </button>
            ))}
          </div>

          <section className={`win glass ${dip ? "dip" : ""}`}>
            {/* 6.1 node view */}
            <div className={`card cam ${camBig ? "big" : ""} ${tab === 0 ? "overview" : ""}`} onClick={() => setCamBig((b) => !b)}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="feed" src="/forest.jpg" alt="Node on a tree" key={`f${swap}`} />
              <canvas ref={canvasRef} />
              <div className="scan" /><div className="grad" />
              <div className="curtain go" key={`c${swap}`} />
              <span className="chip tl" style={{ ["--c" as string]: live ? (anyOnline ? "var(--m2)" : "#9aa39a") : "var(--m1)" }}>
                <span className="dot" />{live ? (anyOnline ? "Live" : "Offline") : `Replay · ${scrubLabel}`}
              </span>
              <span className="tr">RX · {clock}</span>
              <div className="bl">
                <div className="t"><span className="roll" key={`n${swap}`}>{focus ? focus.name : "All trees"}</span></div>
                <div className="s">
                  {focus && rep ? `Node ${String(focus.node).padStart(2, "0")} · ${rep.rssi} dBm · SNR ${rep.snr} · ${ago(focus.age_s)}`
                    : `${nodes.length} nodes · soundscape from the trunk microphones`}
                </div>
              </div>
              {tab === 0 && (
                <div className="nodes">
                  {nodes.map((n) => (
                    <span key={n.node} className="chip" style={{ ["--c" as string]: n.online ? "var(--m2)" : "#9aa39a" }}><span className="dot" />{n.name}</span>
                  ))}
                </div>
              )}
            </div>

            {/* 6.2 dial */}
            <div className="card dial">
              <div className="hd">
                <div>
                  <div className="t"><span className="roll" key={`d${swap}${metric}`}>{M.title} · {raw == null ? "—" : M.id === "rain" || M.id === "climate" ? `${value.toFixed(1)}${M.id === "climate" ? "°" : " mm"}` : `${Math.round(value)}${M.id === "power" ? "%" : ""}`}</span></div>
                  <span className="chip" style={{ ["--c" as string]: chip[1] }}><span className="dot" />{chip[0]}</span>
                </div>
                <button className="round gear" aria-label="Thresholds" onClick={() => say(M.setting ? "Drag the white knob on the ring to set the alert level" : `${M.title} has no alert level`)}><Ic.Gear /></button>
              </div>

              <div ref={ringRef} className={`ring ${M.setting ? "" : "ro"} ${muted ? "muted" : ""}`}
                onPointerDown={ringDown} onPointerMove={ringMove} onPointerUp={ringUp} onPointerCancel={ringUp}>
                <svg viewBox="0 0 260 260">
                  <defs>
                    <linearGradient id="dg" x1="0" y1="1" x2="1" y2="0">
                      <stop offset="0" stopColor="#3cc4b4" /><stop offset=".55" stopColor="#8ef0d6" /><stop offset="1" stopColor="#e3fbb0" />
                    </linearGradient>
                    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9" /></filter>
                  </defs>
                  <path d={arc(A0, A1)} stroke="rgba(30,40,34,.45)" strokeWidth="22" fill="none" strokeLinecap="round" />
                  {frac > 0.002 && <>
                    <path d={arc(A0, A0 + 270 * frac)} stroke="url(#dg)" strokeWidth="22" fill="none" strokeLinecap="round" filter="url(#glow)" opacity=".55" />
                    <path d={arc(A0, A0 + 270 * frac)} stroke="url(#dg)" strokeWidth="22" fill="none" strokeLinecap="round" />
                  </>}
                  {Array.from({ length: 31 }, (_, i) => {
                    const a = A0 + (270 * i) / 30;
                    const [x0, y0] = pt(a, i % 5 ? 82 : 78), [x1, y1] = pt(a, 88);
                    return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} stroke={i / 30 <= frac ? "#fff" : "rgba(255,255,255,.22)"} strokeWidth={i % 5 ? 1.5 : 2.4} strokeLinecap="round" />;
                  })}
                  {tfrac != null ? (() => {
                    const [x, y] = pt(A0 + 270 * tfrac);
                    return <g className="knob"><circle cx={x} cy={y} r="14" fill="#fff" /><circle cx={x} cy={y} r="5" fill={M.below ? "var(--warn)" : "#ff9a6b"} /></g>;
                  })() : (() => {
                    const [x, y] = pt(A0 + 270 * frac);
                    return <circle className="knob" cx={x} cy={y} r="12" fill="#fff" />;
                  })()}
                </svg>
                <button className={`power ${muted ? "" : "on"}`} aria-label={muted ? "Unmute alerts" : "Mute alerts"}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => { setMuted(!muted); say(muted ? "Alerts on" : "Alerts muted on this screen"); }}>
                  <Ic.Power />
                </button>
              </div>

              <div className="val">
                <b>{raw == null ? "—" : M.id === "climate" ? `${shownVal.toFixed(1)}°` : M.id === "rain" ? shownVal.toFixed(1) : `${Math.round(shownVal)}${M.unit.trim() === "%" ? "%" : ""}`}</b>
                <div className="s">{M.id === "rain" ? "Rain, last hour (mm)" : M.id === "risk" ? "Rain + soil + tilt index" : M.id === "power" ? "Lowest battery" : M.id === "sound" ? "Bird song, 1-6 kHz" : "Air, enclosure sensor"}</div>
              </div>
              <div className="side">
                {thr != null && <div>Alert {M.below ? "below" : "at"} <b>{thr}{M.unit}</b></div>}
                {rep && <div>Humidity <b>{rep.rh}%</b> · <b>{rep.press_hpa}</b> hPa</div>}
                {rep && <div>Tilt <b>{rep.tilt_x > 0 ? "+" : ""}{rep.tilt_x}°</b> / <b>{rep.tilt_y > 0 ? "+" : ""}{rep.tilt_y}°</b></div>}
              </div>
            </div>

            {/* 6.3 storm watch */}
            <div className={`card scene ${stormOn ? "on" : ""}`}>
              {ripple && <span className="ripple" key={ripple.k} style={{ left: ripple.x, top: ripple.y }} />}
              <span className={`ic ${spin ? "spin" : ""}`}><Ic.Storm /></span>
              <div className="tx"><div className="t">Storm watch</div><div className="s">{stormOn ? "Active · tighter alerts" : "Scene"}</div></div>
              <button className="round" aria-label="Storm watch" onClick={storm}>{stormOn ? <Ic.Pause /> : <Ic.Play />}</button>
            </div>

            {/* 6.4 chainsaw guard */}
            <div className={`card guard ${settings?.guard_armed ? "armed" : ""} ${alarm ? "alarm" : ""}`}>
              <div className="top">
                <span className="round"><Ic.Saw /></span>
                <span className="round light"><Ic.Shield /></span>
                <span className="st">{alarm ? "Alert!" : settings?.guard_armed ? "Armed" : "Off"}</span>
              </div>
              <div className={`bar ${settings?.guard_armed ? "" : "off"}`}><i /></div>
              <div className="ft">
                <div>
                  <div className="t"><span className="roll" key={`g${swap}`}>Chainsaw guard</span></div>
                  <div className="s">{lastSaw ? `Last ${hhmm(new Date(lastSaw.ts * 1000))} · ${lastSaw.name}` : "No chainsaw in 48 h"}</div>
                </div>
                <button className={`toggle ${settings?.guard_armed ? "on" : ""}`} aria-label="Arm chainsaw guard" onClick={() => toggle("guard_armed")} />
              </div>
            </div>

            {/* 6.5 battery */}
            <div className={`card batt ${sc1 ? "dark" : ""}`}>
              <div className="top">
                <span className="bulb" style={{ boxShadow: sc1 ? `0 0 ${(sc1.soc / 100) * 4}rem rgba(255,236,160,.9)` : "none" }}><Ic.Battery /></span>
                <span className="st">{sc1 ? (charging ? "Charging" : "Draining") : "—"}</span>
              </div>
              {sc1 && <div className="gauge"><i style={{ width: `${sc1.soc}%` }} /></div>}
              <div className="ft">
                <div>
                  <div className="t"><span className="roll" key={`b${swap}`}>{tab === 0 ? "Weakest battery" : "Battery"}</span></div>
                  <div className="s">{sc1 ? `${sc1.soc}% · ${charging ? "+" : "−"}${Math.abs(sc1.ibat_ma).toFixed(1)} mA · ${sc1.cell_c == null ? "no cell probe" : `cell ${sc1.cell_c.toFixed(1)}°`}` : "SC-1 board not fitted"}</div>
                </div>
                <button className={`toggle ${settings?.energy_saver ? "on" : ""}`} aria-label="Energy saver" onClick={() => toggle("energy_saver")} />
              </div>
            </div>

            {/* 6.6 timeline */}
            <div className={`card slider ${dragging ? "drag" : ""}`}
              onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); setDragging(true); sliderDrag(e); }}
              onPointerMove={(e) => dragging && sliderDrag(e)}
              onPointerUp={(e) => {
                setDragging(false);
                const b = e.currentTarget.getBoundingClientRect();
                const f = clamp((e.clientX - b.left) / b.width, 0, 1);
                if (f >= 0.995) say("Back to live");
                else say(`Replaying ${hourLabel(hourOf(now - (1 - f) * dayS, dayS))} · ${tab === 0 ? "all trees" : focus?.name}`);
              }}>
              <div className="fill" style={{ width: `calc(${Math.max(18, scrub)}% - 1.4rem)` }} />
              <div className="lbl">
                {night > 0.5 ? <Ic.Moon /> : <Ic.Sun />}
                <span>{scrubLabel}</span>
                <span className="r"><small>{demo ? "demo day" : "24 h"}</small>{Math.round(scrub)}%</span>
              </div>
            </div>

            {/* 6.7 soundscape */}
            <div className="card player">
              <div className="art">
                {cur ? <div className="wipe" key={`${cur.ts}${cur.node}`}><Art kind={cur.kind} seed={Math.round(cur.ts) % 97} /></div> : <Art kind="bird" seed={3} />}
              </div>
              <div className="rt">
                <div className="row">
                  <span className="chip"><span className="note"><Ic.Note /></span>Now hearing<span className={`eq ${playing ? "" : "paused"}`}><i /><i /><i /></span></span>
                  <span className="time">{cur ? `0:0${dwell} / 0:0${DWELL}` : "0:00 / 0:00"}</span>
                </div>
                {cur ? (
                  <div className="ttl" key={`t${cur.ts}${cur.node}`}>
                    <div className="t"><span className="roll">{cur.title}</span></div>
                    <div className="s"><span className="roll">{cur.name} · {hhmm(new Date(cur.ts * 1000))} · {cur.detail}</span></div>
                  </div>
                ) : <div className="empty">No highlights yet: bird chorus, pollinators, rain and alerts appear here.</div>}
                <div className="prog" onClick={(e) => {
                  if (!evList.length) return;
                  const b = e.currentTarget.getBoundingClientRect();
                  setEv(Math.floor(((e.clientX - b.left) / b.width) * evList.length)); setDwell(0);
                }}>
                  <i style={{ width: evList.length ? `${(((ev % evList.length) + dwell / DWELL) / evList.length) * 100}%` : "0%" }} />
                </div>
                <div className="ctl">
                  <button className="round" aria-label="Previous" onClick={prevEv}><Ic.Prev /></button>
                  <button className="round play" aria-label={playing ? "Pause" : "Play"} onClick={() => setPlaying(!playing)}>{playing ? <Ic.Pause /> : <Ic.Play />}</button>
                  <button className="round" aria-label="Next" onClick={nextEv}><Ic.Next /></button>
                </div>
              </div>
            </div>
          </section>

          {online === false && <div className="banner">Start the backend: <code>cd Dashboard/backend &amp;&amp; DEMO=1 .venv/bin/uvicorn app:app</code></div>}
        </div>
      </div>

      <div className={`toast glass ${toast ? "show" : ""} ${toast?.warn ? "warn" : ""}`} role="status">
        <span className="ok">{toast?.warn ? <Ic.Bang /> : <Ic.Check />}</span>{toast?.msg}
      </div>
      {rec && <div className={`cursor ${cur2.hot ? "hot" : ""} ${cur2.down ? "down" : ""}`} style={{ left: cur2.x, top: cur2.y }} />}
    </main>
  );
}
