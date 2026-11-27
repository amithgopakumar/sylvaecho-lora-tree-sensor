(async () => {
  // SC-1 v0.2 step 1: clear routing + pours, move passives to the spread placement, add a GND stub + via at each GND SMD pad.
  const MOVE = {"C4": [5314.963, -4271.656, 90, 2], "C1": [4625.987, -4173.231, 90, 2], "C2": [4665.357, -4015.75, 0, 2], "C3": [4153.546, -4291.341, 0, 2], "C10": [5669.294, -4271.656, 90, 2], "R2": [4330.711, -4291.341, 0, 2], "R3": [4704.727, -4389.766, 0, 2], "R17": [4448.821, -4291.341, 0, 1], "R4": [4862.207, -4271.656, 0, 2], "R5": [4822.837, -4114.175, 90, 2], "R6": [4625.987, -4547.247, 90, 2], "R7": [5196.853, -4271.656, 90, 2], "R8": [4881.892, -4389.766, 0, 2], "R11": [5511.814, -4232.286, 0, 2], "C12": [5551.184, -4389.766, 90, 2], "R13": [5669.294, -4448.821, 90, 2], "C13": [5649.609, -4606.302, 0, 2], "R15": [5039.373, -4271.656, 90, 2], "R16": [5059.058, -4429.136, 0, 2], "C5": [4980.318, -4094.49, 90, 2], "C6": [4862.207, -4015.75, 0, 1], "C7": [4783.467, -4507.876, 0, 2], "C8": [4783.467, -4625.987, 0, 2], "C9": [5236.223, -4429.136, 0, 2], "R12": [5433.074, -4389.766, 90, 2], "R9": [5492.129, -4566.932, 90, 2], "R14": [4980.318, -4586.617, 90, 2], "C15": [4665.357, -4015.75, 0, 1], "D2": [4940.948, -4685.042, 0, 1], "R10": [4763.782, -4685.042, 0, 1], "C11": [3996.065, -4271.656, 90, 2], "C14": [4724.412, -4251.971, 90, 2]};
  const K = 39.3701, BX0 = 100 * K, BX1 = 146 * K, BYT = -100 * K, BYB = -121 * K;
  const VIA_D = 0.6 * K, VIA_H = 0.3 * K, TRK = 10, CLR = 8, EDGE = 20;
  const out = { cleared: {}, moved: 0, moveErr: [], stubs: [], noStub: [], err: [] };
  try {
    const pours = await eda.pcb_PrimitivePour.getAll();
    if (pours.length) await eda.pcb_PrimitivePour.delete(pours.map(p => p.getState_PrimitiveId()));
    const lines = (await eda.pcb_PrimitiveLine.getAll()).filter(l => [1, 2].includes(l.getState_Layer()) && l.getState_Net());
    if (lines.length) await eda.pcb_PrimitiveLine.delete(lines.map(l => l.getState_PrimitiveId()));
    const arcs = (await eda.pcb_PrimitiveArc.getAll()).filter(a => [1, 2].includes(a.getState_Layer()) && a.getState_Net());
    if (arcs.length) await eda.pcb_PrimitiveArc.delete(arcs.map(a => a.getState_PrimitiveId()));
    const vias = await eda.pcb_PrimitiveVia.getAll();
    if (vias.length) await eda.pcb_PrimitiveVia.delete(vias.map(v => v.getState_PrimitiveId()));
    out.cleared = { pours: pours.length, lines: lines.length, arcs: arcs.length, vias: vias.length };
  } catch (e) { out.err.push('clear ' + e); }
  try {
    for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
      const m = MOVE[c.getState_Designator()]; if (!m) continue;
      try {
        if (c.getState_Layer() !== m[3]) await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), { layer: m[3] });
        await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(), { x: m[0], y: m[1], rotation: m[2] });
        out.moved++;
      } catch (e) { out.moveErr.push(c.getState_Designator() + ' ' + e); }
    }
  } catch (e) { out.err.push('move ' + e); }
  // ---- GND stubs (no tracks exist now: only pads + stubs/vias placed so far are obstacles)
  try {
    const rects = [], segs = [];
    for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
      const ref = c.getState_Designator(), cl = c.getState_Layer();
      for (const p of (await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId())) || []) {
        const bb = await eda.pcb_Primitive.getPrimitivesBBox([p.getState_PrimitiveId()]);
        if (!bb) continue;
        rects.push({ x0: bb.minX, y0: bb.minY, x1: bb.maxX, y1: bb.maxY, layer: p.getState_Layer(), net: p.getState_Net(),
          key: ref + '_' + p.getState_PadNumber(), cx: p.getState_X(), cy: p.getState_Y() });
      }
    }
    const onL = (a, L) => a === 12 || L === 12 || a === L;
    const dPS = (px, py, s) => { const dx = s.x2 - s.x1, dy = s.y2 - s.y1, L2 = dx * dx + dy * dy;
      let t = L2 ? ((px - s.x1) * dx + (py - s.y1) * dy) / L2 : 0; t = Math.max(0, Math.min(1, t));
      return Math.hypot(px - (s.x1 + t * dx), py - (s.y1 + t * dy)); };
    const cross = (a, b) => { const o = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
      return o([a.x1, a.y1], [a.x2, a.y2], [b.x1, b.y1]) * o([a.x1, a.y1], [a.x2, a.y2], [b.x2, b.y2]) < 0 &&
        o([b.x1, b.y1], [b.x2, b.y2], [a.x1, a.y1]) * o([b.x1, b.y1], [b.x2, b.y2], [a.x2, a.y2]) < 0; };
    const dSS = (a, b) => cross(a, b) ? 0 : Math.min(dPS(a.x1, a.y1, b), dPS(a.x2, a.y2, b), dPS(b.x1, b.y1, a), dPS(b.x2, b.y2, a));
    const rs = r => [[r.x0, r.y0, r.x1, r.y0], [r.x1, r.y0, r.x1, r.y1], [r.x1, r.y1, r.x0, r.y1], [r.x0, r.y1, r.x0, r.y0]]
      .map(q => ({ x1: q[0], y1: q[1], x2: q[2], y2: q[3] }));
    const inR = (x, y, r) => x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
    const dSR = (s, r) => (inR(s.x1, s.y1, r) || inR(s.x2, s.y2, r)) ? 0 : Math.min(...rs(r).map(e => dSS(s, e)));
    // via must clear ALL other pads (any net, so it never sits in a GND pad of another part) and other vias
    const clear = (s, hw, L, ownKey, viaCheck) => {
      for (const o of segs) if (onL(o.layer, L) && dSS(s, o) < hw + o.hw + CLR) { if (!(o.net === 'GND' && !viaCheck)) return false; }
      for (const r of rects) if (r.key !== ownKey && onL(r.layer, L) && dSR(s, r) < hw + CLR) { if (!(r.net === 'GND' && !viaCheck)) return false; }
      return true; };
    for (const pad of rects) {
      if (pad.net !== 'GND' || pad.layer === 12) continue;            // THT GND pads touch both pours already
      const L = pad.layer, half = Math.max(pad.x1 - pad.x0, pad.y1 - pad.y0) / 2;
      let done = false;
      for (let dist = half + VIA_D / 2 + 4; dist <= half + 80 && !done; dist += 3) {
        for (let k = 0; k < 24 && !done; k++) {
          const a = k * Math.PI / 12, vx = pad.cx + dist * Math.cos(a), vy = pad.cy + dist * Math.sin(a);
          if (vx < BX0 + EDGE || vx > BX1 - EDGE || vy > BYT - EDGE || vy < BYB + EDGE) continue;
          if (!clear({ x1: vx, y1: vy, x2: vx, y2: vy }, VIA_D / 2, 12, pad.key, true)) continue;
          const trk = { x1: pad.cx, y1: pad.cy, x2: vx, y2: vy };
          if (!clear(trk, TRK / 2, L, pad.key, false)) continue;
          await eda.pcb_PrimitiveVia.create('GND', vx, vy, VIA_H, VIA_D);
          await eda.pcb_PrimitiveLine.create('GND', L, pad.cx, pad.cy, vx, vy, TRK);
          segs.push({ x1: vx, y1: vy, x2: vx, y2: vy, hw: VIA_D / 2, layer: 12, net: 'GND' });
          segs.push({ ...trk, hw: TRK / 2, layer: L, net: 'GND' });
          out.stubs.push(pad.key); done = true;
        }
      }
      if (!done) out.noStub.push(pad.key);
    }
  } catch (e) { out.err.push('stub ' + e); }
  try { out.saved = await eda.pcb_Document.save(); } catch (e) { out.err.push('save ' + e); }
  await eda.sys_FileSystem.saveFile(new Blob([JSON.stringify(out)], { type: 'application/json' }), 'sc1_v2_apply.json');
  eda.sys_Dialog.showInformationMessage('cleared ' + JSON.stringify(out.cleared) + ' | moved ' + out.moved + ' | stubs ' + out.stubs.length +
    ' | no stub ' + out.noStub.join(',') + ' | err ' + out.err.concat(out.moveErr).join(' | '), 'SC-1');
})();
