"""SC-1 v0.2 placer: spread the 0805 passives so the router has channels.

Keeps connectors / ICs where they are, re-places every movable passive greedily: each part goes to the free
spot (0.5 mm grid, rotation 0 or 90, top or bottom) that minimises the distance from its pads to the nearest
same-net pads already placed, with >= GAP mm between courtyards.  Writes companion/placement_v2.json.
Run with KiCad's Python.
"""
import json
import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['NO_V2'] = '1'
import build_companion_pcb as B  # noqa: E402

GAP = float(os.environ.get('GAP', 0.9))
EDGE = 0.4
W, H = B.W, B.H
MOVABLE = [r for r, v in B.PL.items() if (r[0] in 'RC' or r == 'D2') and r not in ('R1',)]
TOP_OK = set(MOVABLE)  # any passive may sit on top

parts = {p['ref']: p for p in json.load(open(os.path.join(B.OUTD, 'parts.json')))}


def fp_geom(ref):
    """courtyard half-sizes and pad offsets (mm) at rotation 0, plus pad nets"""
    lib, name = parts[ref]['fp'].split(':')
    f = pcbnew.FootprintLoad(B.FPDIR + lib + '.pretty', name)
    cy = f.GetCourtyard(pcbnew.F_CrtYd)
    bb = cy.BBox() if cy.OutlineCount() else f.GetBoundingBox(False)
    hx = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
    hy = None
    pads = [(pd.GetNumber(), pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)) for pd in f.Pads()]
    tht = any(pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for pd in f.Pads())
    return hx, hy, pads, tht


G = {r: fp_geom(r) for r in parts}


def placed_box(ref, x, y, rot):
    l, t, r, b = G[ref][0]
    a = math.radians(rot)
    pts = [(px * math.cos(a) + py * math.sin(a), -px * math.sin(a) + py * math.cos(a)) for px, py in ((l, t), (r, t), (l, b), (r, b))]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (x + min(xs), y + min(ys), x + max(xs), y + max(ys))


def pad_pos(ref, x, y, rot):
    out = []
    a = math.radians(rot)
    for n, px, py in G[ref][2]:
        # KiCad: positive orientation is counter-clockwise on screen (y down)
        rx = px * math.cos(a) + py * math.sin(a)
        ry = -px * math.sin(a) + py * math.cos(a)
        out.append((n, x + rx, y + ry))
    return out


fixed = {r: v for r, v in B.PL.items() if r not in MOVABLE}
boxes = []      # (box, side, tht)
pads_xy = {}    # net -> [(x, y)]


def add(ref, x, y, rot, side):
    boxes.append((placed_box(ref, x, y, rot), side, G[ref][3]))
    for n, px, py in pad_pos(ref, x, y, rot):
        net = parts[ref]['nets'].get(n)
        if net:
            pads_xy.setdefault(net, []).append((px, py))


for r, (x, y, rot, side) in fixed.items():
    add(r, x, y, rot, side)


def free(box, side):
    l, t, r_, b = box
    if l < EDGE or t < EDGE or r_ > W - EDGE or b > H - EDGE:
        return False
    for (l2, t2, r2, b2), s2, tht in boxes:
        if s2 != side and not tht:
            continue
        if l < r2 + GAP and l2 < r_ + GAP and t < b2 + GAP and t2 < b + GAP:
            return False
    return True


# decoupling caps: distance to their IC power pin only (weighted), not to any pad of the net
ANCHOR = {'C1': ('U1', '1'), 'C2': ('U1', '1'), 'C3': ('U2', '4'), 'C4': ('U3', '8'), 'C10': ('U4', '5')}


def pin_xy(ref, num):
    x, y, rot, side = fixed[ref]
    return [(px, py) for n, px, py in pad_pos(ref, x, y, rot) if n == num][0]


def cost(ref, x, y, rot, side):
    if ref in ANCHOR:
        ax, ay = pin_xy(*ANCHOR[ref])
        return 3 * min(math.hypot(px - ax, py - ay) for _, px, py in pad_pos(ref, x, y, rot)) + (0.8 if side == 'T' else 0)
    c = 0.0
    for n, px, py in pad_pos(ref, x, y, rot):
        net = parts[ref]['nets'].get(n)
        if not net or net == 'GND':
            continue   # GND goes to the pour
        pts = pads_xy.get(net)
        if pts:
            c += min(math.hypot(px - qx, py - qy) for qx, qy in pts)
        else:
            c += 3.0
    return c + (0.8 if side == 'T' else 0)     # mild preference for the bottom


# order: parts with most connections to already-fixed pads first
def anchor_count(ref):
    return sum(1 for n in parts[ref]['nets'].values() if n != 'GND' and n in pads_xy)


result = {}
todo = list(MOVABLE)
while todo:
    todo.sort(key=lambda r: (r not in ANCHOR, -anchor_count(r)))
    ref = todo.pop(0)
    best = None
    sides = ['B', 'T'] if ref in TOP_OK else ['B']
    for side in sides:
        for rot in (0, 90):
            for iy in range(int(H / 0.5) + 1):
                for ix in range(int(W / 0.5) + 1):
                    x, y = ix * 0.5, iy * 0.5
                    bx = placed_box(ref, x, y, rot)
                    if not free(bx, side):
                        continue
                    c = cost(ref, x, y, rot, side)
                    if best is None or c < best[0]:
                        best = (c, x, y, rot, side)
    if best is None and GAP > 0.4:
        g0 = GAP; GAP = 0.4
        for side in sides:
            for rot in (0, 90):
                for iy in range(int(H / 0.5) + 1):
                    for ix in range(int(W / 0.5) + 1):
                        x, y = ix * 0.5, iy * 0.5
                        if free(placed_box(ref, x, y, rot), side):
                            c = cost(ref, x, y, rot, side)
                            if best is None or c < best[0]:
                                best = (c, x, y, rot, side)
        GAP = g0
        print('  (tight 0.4 mm gap for', ref + ')')
    if best is None:
        print('NO SPOT for', ref); sys.exit(1)
    c, x, y, rot, side = best
    add(ref, x, y, rot, side)
    result[ref] = [x, y, rot, side]
    print('%-4s -> (%5.1f, %5.1f) rot %3d %s  cost %.1f' % (ref, x, y, rot, side, c))

json.dump(result, open(os.path.join(B.OUTD, 'placement_v2.json'), 'w'), indent=0)
print('wrote placement_v2.json,', len(result), 'parts')
