"""Build the placed (unrouted) SC-1 PCB, 46 x 21 mm, 2-layer, from companion/parts.json.

Run with KiCad's Python:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 build_companion_pcb.py
Top side: connectors, ICs and the INA219 network.  Bottom side: 0805 passives (hand-soldered).
"""
import json
import os
import sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
OUTD = os.path.join(HERE, '..', 'companion')
FPDIR = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/'
W, H = 46.0, 21.0
OX, OY = 100.0, 100.0          # board top-left in KiCad mm
EDGE = 0.25                    # courtyard keep-in from the board edge

# ref: (x, y, rotation, side)  board coordinates, y down
PL = {
    # top: connectors (THT) and ICs
    'J1': (2.7, 2.5, 0, 'T'), 'J2': (9.9, 2.5, 0, 'T'), 'J3': (31.8, 2.5, 0, 'T'), 'J4': (39.0, 2.5, 0, 'T'),
    'J7': (12.7, 18.5, 180, 'T'), 'J8': (33.0, 18.5, 180, 'T'), 'J5': (41.5, 17.5, 0, 'T'),
    'U1': (22.0, 10.5, 0, 'T'), 'U2': (8.0, 8.5, 0, 'T'), 'U3': (32.4, 9.6, 0, 'T'),
    'U4': (42.6, 8.3, 0, 'T'), 'D1': (42.0, 12.2, 0, 'T'),
    'R1': (3.4, 8.5, 90, 'T'), 'R2': (12.2, 8.5, 90, 'T'), 'R3': (14.6, 8.5, 90, 'T'), 'C4': (38.3, 8.3, 90, 'T'),
    'J9': (8.6, 12.7, 90, 'T'), 'TP1': (1.6, 12.7, 0, 'T'), 'TP2': (4.4, 12.7, 0, 'T'),
}
# bottom-side 0805 grid slots
COLS_U1, ROWS_U1 = (18.0, 22.0, 26.0), (5.2, 7.6, 10.0, 12.4, 14.8, 17.2, 19.6)
under_u1 = [(x, y) for y in ROWS_U1 for x in COLS_U1]
for ref, (x, y) in zip(['C1', 'C2', 'R16', 'D2', 'R17', 'R4', 'R5', 'C5', 'C6', 'R6', 'C7', 'C8', 'C3'], under_u1):
    PL[ref] = (x, y, 0, 'B')
for ref, (x, y) in zip(['R7', 'R8', 'C9'], [(2.1, 7.2), (6.1, 7.2), (10.1, 7.2)]):
    PL[ref] = (x, y, 0, 'B')
right = [(x, y) for y in (7.2, 9.6, 12.0) for x in (30.6, 34.6, 38.6, 42.6)] + [(38.6, 16.0), (42.6, 16.0)]
for ref, (x, y) in zip(['R11', 'C12', 'R12', 'R9', 'R10', 'C11', 'C10', 'R13', 'C13', 'R14', 'C14', 'R15', 'C15'], right):
    PL[ref] = (x, y, 0, 'B')

# v0.2: spread placement computed by place_companion.py overrides the grid slots above
_OVR = os.path.join(OUTD, 'placement_v2.json')
if os.path.exists(_OVR) and os.environ.get('NO_V2') != '1':
    for _r, _v in json.load(open(_OVR)).items():
        PL[_r] = tuple(_v)

LABELS = [  # silkscreen text: (text, x, y, size, layer)
    ('BAT IN', 3.7, 6.6, 0.7, 'F.SilkS'), ('BAT OUT', 10.9, 6.6, 0.7, 'F.SilkS'),
    ('PZ IN', 32.8, 6.6, 0.7, 'F.SilkS'), ('PZ OUT', 40.0, 6.6, 0.7, 'F.SilkS'),
    ('FIELD', 8.7, 14.6, 0.7, 'F.SilkS'), ('CELL NTC', 31.9, 14.6, 0.7, 'F.SilkS'), ('QWIIC', 41.5, 13.6 + 0.2, 0.7, 'F.SilkS'),
    ('WAKE GND', 3.0, 14.9, 0.6, 'F.SilkS'),
    ('SylvaEcho SC-1 v0.1', 7.5, 17.0, 0.9, 'B.SilkS'),
]


def mm(v):
    return pcbnew.FromMM(v)


def main():
    parts = json.load(open(os.path.join(OUTD, 'parts.json')))
    missing = [p['ref'] for p in parts if p['ref'] not in PL]
    assert not missing, missing
    board = pcbnew.CreateEmptyBoard()
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    nets = {}
    for p in parts:
        for n in p['nets'].values():
            if n not in nets:
                ni = pcbnew.NETINFO_ITEM(board, n)
                board.Add(ni)
                nets[n] = ni
    boxes = []
    for p in parts:
        lib, name = p['fp'].split(':')
        fp = pcbnew.FootprintLoad(FPDIR + lib + '.pretty', name)
        fp.SetReference(p['ref'])
        fp.SetValue(p['value'])
        x, y, rot, side = PL[p['ref']]
        fp.SetPosition(pcbnew.VECTOR2I(mm(OX + x), mm(OY + y)))
        board.Add(fp)
        if side == 'B':
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            n = p['nets'].get(pad.GetNumber())
            if n:
                pad.SetNet(nets[n])
        fp.Value().SetVisible(False)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.7), mm(0.7)))
        fp.Reference().SetTextThickness(mm(0.12))
        cy = fp.GetCourtyard(pcbnew.B_CrtYd if side == 'B' else pcbnew.F_CrtYd)
        bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
        tht = any(pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for pd in fp.Pads())
        b = (pcbnew.ToMM(bb.GetLeft()) - OX, pcbnew.ToMM(bb.GetTop()) - OY,
             pcbnew.ToMM(bb.GetRight()) - OX, pcbnew.ToMM(bb.GetBottom()) - OY)
        boxes.append((p['ref'], side, tht, b))
    # outline
    pts = [(0, 0), (W, 0), (W, H), (0, H)]
    for i in range(4):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        a, b = pts[i], pts[(i + 1) % 4]
        s.SetStart(pcbnew.VECTOR2I(mm(OX + a[0]), mm(OY + a[1])))
        s.SetEnd(pcbnew.VECTOR2I(mm(OX + b[0]), mm(OY + b[1])))
        board.Add(s)
    for t, x, y, sz, layer in LABELS:
        tx = pcbnew.PCB_TEXT(board)
        tx.SetText(t)
        tx.SetLayer(pcbnew.F_SilkS if layer == 'F.SilkS' else pcbnew.B_SilkS)
        tx.SetTextSize(pcbnew.VECTOR2I(mm(sz), mm(sz)))
        tx.SetTextThickness(mm(0.12))
        tx.SetPosition(pcbnew.VECTOR2I(mm(OX + x), mm(OY + y)))
        if layer.startswith('B'):
            tx.SetMirrored(True)
        board.Add(tx)
    # checks: inside board, no courtyard overlap on the same side (THT parts block both sides)
    errs = []
    for ref, side, tht, (l, t, r, btm) in boxes:
        if l < EDGE - 0.3 or t < EDGE - 0.3 or r > W - EDGE + 0.3 or btm > H - EDGE + 0.3:
            errs.append('EDGE %s %s' % (ref, [round(v, 2) for v in (l, t, r, btm)]))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[1] != b[1] and not (a[2] or b[2]):
                continue
            (l1, t1, r1, b1), (l2, t2, r2, b2) = a[3], b[3]
            ox, oy = min(r1, r2) - max(l1, l2), min(b1, b2) - max(t1, t2)
            if ox > 0.02 and oy > 0.02:
                errs.append('OVERLAP %s/%s %.2f x %.2f' % (a[0], b[0], ox, oy))
    print('\n'.join(errs) or 'placement OK: no overlaps, all inside the board')
    board.Save(os.path.join(OUTD, 'sc1.kicad_pcb'))
    json.dump({r: [s, t, [round(v, 2) for v in b]] for r, s, t, b in boxes},
              open(os.path.join(OUTD, 'placement_boxes.json'), 'w'), indent=0)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
