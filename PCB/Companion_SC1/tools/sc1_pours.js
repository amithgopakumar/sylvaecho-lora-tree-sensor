(async () => {
  // SC-1: (re)create GND pours on top + bottom over the whole board, rebuild, DRC, save. Report -> Downloads/sc1_pours.json
  const K = 39.3701, X0 = 100 * K, X1 = 146 * K, YT = -100 * K, YB = -121 * K;
  const out = { pours: [], err: [] };
  try {
    const old = await eda.pcb_PrimitivePour.getAll();
    if (old.length) await eda.pcb_PrimitivePour.delete(old.map(p => p.getState_PrimitiveId()));
    for (const layer of [1, 2]) {
      const poly = eda.pcb_MathPolygon.createPolygon(['R', X0, YT, X1 - X0, YT - YB, 0, 0]);
      const p = await eda.pcb_PrimitivePour.create('GND', layer, poly, 'solid', false, 'GND_L' + layer, 5, 10, false);
      out.pours.push(p ? p.getState_PrimitiveId() : 'fail');
    }
    const f = await eda.pcb_PrimitivePour.rebuildAllCopperRegions(); out.filled = f ? f.length : 0;
  } catch (e) { out.err.push('pour ' + e); }
  try { out.drc = await eda.pcb_Drc.check(true, false, true); } catch (e) { out.err.push('drc ' + e); }
  try { out.saved = await eda.pcb_Document.save(); } catch (e) { out.err.push('save ' + e); }
  await eda.sys_FileSystem.saveFile(new Blob([JSON.stringify(out)], { type: 'application/json' }), 'sc1_pours.json');
  eda.sys_Dialog.showInformationMessage('pours ' + out.pours.length + ' filled ' + out.filled + ' | saved ' + out.saved + ' | err ' + out.err.join(' | '), 'SC-1');
})();
