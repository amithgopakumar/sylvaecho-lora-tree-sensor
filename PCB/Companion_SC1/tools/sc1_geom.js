(async () => {
  // Dump all copper geometry (tracks, vias, pads with bbox) + GND ratlines for offline analysis.
  const out = { lines: [], vias: [], pads: [], rat: [], err: [] };
  try {
    for (const l of await eda.pcb_PrimitiveLine.getAll()) out.lines.push({ id: l.getState_PrimitiveId(), net: l.getState_Net(), L: l.getState_Layer(),
      x1: l.getState_StartX(), y1: l.getState_StartY(), x2: l.getState_EndX(), y2: l.getState_EndY(), w: l.getState_LineWidth() });
    for (const v of await eda.pcb_PrimitiveVia.getAll()) out.vias.push({ id: v.getState_PrimitiveId(), net: v.getState_Net(),
      x: v.getState_X(), y: v.getState_Y(), d: v.getState_Diameter(), h: v.getState_HoleDiameter() });
    for (const c of await eda.pcb_PrimitiveComponent.getAll()) {
      const ref = c.getState_Designator();
      for (const p of (await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId())) || []) {
        const bb = await eda.pcb_Primitive.getPrimitivesBBox([p.getState_PrimitiveId()]);
        out.pads.push({ id: p.getState_PrimitiveId(), key: ref + '_' + p.getState_PadNumber(), net: p.getState_Net(), L: p.getState_Layer(),
          x: p.getState_X(), y: p.getState_Y(), bb });
      }
    }
    let cursor; do { const pg = await eda.pcb_Document.getRatlines(cursor ? { cursor } : {}); out.rat.push(...(pg.items || []));
      cursor = pg.hasMore ? pg.nextCursor : null; } while (cursor);
  } catch (e) { out.err.push(String(e)); }
  await eda.sys_FileSystem.saveFile(new Blob([JSON.stringify(out)], { type: 'application/json' }), 'sc1_geom.json');
  eda.sys_Dialog.showInformationMessage('lines ' + out.lines.length + ' vias ' + out.vias.length + ' pads ' + out.pads.length + ' rat ' + out.rat.length + ' err ' + out.err.join('|'), 'SC-1');
})();
