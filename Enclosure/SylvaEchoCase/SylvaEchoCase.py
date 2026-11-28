# SylvaEcho tree-mount enclosure, built with the Fusion API.
# Units in this file are millimetres; Fusion works in cm, so every value goes through cm().
# Axes: X = width, Y = height (up), Z = depth (front of the case is +Z, tree is -Z).

import adsk.core, adsk.fusion, traceback, math, os, json

# Outputs go to the Enclosure/ folder that holds this script's folder.
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB_STEP = OUT + '/ref/SylvaEcho_PCB2.step'  # export the rev 0.4 board STEP from EasyEDA Pro here (not in the repo, 33 MB)
LOG = OUT + '/fusion_log.txt'

# ---------------- main dimensions (mm) ----------------
W, H = 80.0, 72.0          # outer width / height (18500 cell)
R_CORNER = 10.0            # vertical corner radius
D_BASE = 38.0              # base depth (z 0..38)
LID_T = 4.5                # lid thickness (z 38..42.5)
WALL = 2.5
PCB_W, PCB_H, PCB_T = 60.0, 45.0, 1.6
PCB_CY = -3.0              # board centre Y in the case
PCB_Z = 25.0               # board back face Z
BOSS = [(-34.5, -30.5), (34.5, -30.5), (-34.5, 30.5), (34.5, 30.5)]
TILT = 25.0                # solar panel tilt, degrees toward the front
POD_C = (10.0, 52.0, 24.0)
RENDER = False             # set True for photo-real renders (slow)
TRUNK_R = 150.0
TRUNK_CZ = -6.0 - TRUNK_R - 0.2

_log = []
def log(*a):
    _log.append(' '.join(str(x) for x in a))
    with open(LOG, 'w') as f:
        f.write('\n'.join(_log))

def cm(v): return v / 10.0
def P(x, y, z): return adsk.core.Point3D.create(cm(x), cm(y), cm(z))
def V(x, y, z): return adsk.core.Vector3D.create(x, y, z)
def VI(v): return adsk.core.ValueInput.createByReal(cm(v))
def coll(items):
    c = adsk.core.ObjectCollection.create()
    for i in items: c.add(i)
    return c

app = adsk.core.Application.get()
tbm = adsk.fusion.TemporaryBRepManager.get()

# ---------------- geometry helpers ----------------
def xy_plane(comp, z):
    if abs(z) < 1e-9:
        return comp.xYConstructionPlane
    pi = comp.constructionPlanes.createInput()
    pi.setByOffset(comp.xYConstructionPlane, VI(z))
    return comp.constructionPlanes.add(pi)

def rrect_sketch(comp, cx, cy, w, h, r, z):
    sk = comp.sketches.add(xy_plane(comp, z))
    L = sk.sketchCurves.sketchLines
    A = sk.sketchCurves.sketchArcs
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    p = lambda x, y: adsk.core.Point3D.create(cm(x), cm(y), 0)
    L.addByTwoPoints(p(x0 + r, y0), p(x1 - r, y0))
    L.addByTwoPoints(p(x1, y0 + r), p(x1, y1 - r))
    L.addByTwoPoints(p(x1 - r, y1), p(x0 + r, y1))
    L.addByTwoPoints(p(x0, y1 - r), p(x0, y0 + r))
    A.addByCenterStartSweep(p(x1 - r, y0 + r), p(x1 - r, y0), math.pi / 2)
    A.addByCenterStartSweep(p(x1 - r, y1 - r), p(x1, y1 - r), math.pi / 2)
    A.addByCenterStartSweep(p(x0 + r, y1 - r), p(x0 + r, y1), math.pi / 2)
    A.addByCenterStartSweep(p(x0 + r, y0 + r), p(x0, y0 + r), math.pi / 2)
    return sk

def biggest_profile(sk):
    best, area = None, -1
    for pr in sk.profiles:
        a = pr.areaProperties().area
        if a > area: best, area = pr, a
    return best

def rrect_body(comp, cx, cy, w, h, r, z0, z1, name):
    sk = rrect_sketch(comp, cx, cy, w, h, r, z0)
    ext = comp.features.extrudeFeatures.addSimple(biggest_profile(sk), VI(z1 - z0),
                                                  adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    b = ext.bodies.item(0); b.name = name
    return b

def add_temp(comp, tb, name):
    b = comp.bRepBodies.add(tb); b.name = name
    return b

def cyl(p1, r1, p2, r2=None):
    return tbm.createCylinderOrCone(P(*p1), cm(r1), P(*p2), cm(r1 if r2 is None else r2))

def box(c, l, w, h, ldir=(1, 0, 0), wdir=(0, 1, 0)):
    obb = adsk.core.OrientedBoundingBox3D.create(P(*c), V(*ldir), V(*wdir), cm(l), cm(w), cm(h))
    return tbm.createBox(obb)

def tb_union(a, b): tbm.booleanOperation(a, b, adsk.fusion.BooleanTypes.UnionBooleanType); return a
def tb_cut(a, b): tbm.booleanOperation(a, b, adsk.fusion.BooleanTypes.DifferenceBooleanType); return a

def combine(comp, target, tools, op):
    ci = comp.features.combineFeatures.createInput(target, coll(tools))
    ci.operation = op
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)

CUT = adsk.fusion.FeatureOperations.CutFeatureOperation
JOIN = adsk.fusion.FeatureOperations.JoinFeatureOperation

def fillet(comp, edges, r):
    if not edges: return
    fi = comp.features.filletFeatures.createInput()
    try:
        fi.edgeSetInputs.addConstantRadiusEdgeSet(coll(edges), VI(r), True)
    except Exception:
        fi.addConstantRadiusEdgeSet(coll(edges), VI(r), True)
    comp.features.filletFeatures.add(fi)

def edges_at_z(body, z, tol=0.01):
    out = []
    for e in body.edges:
        bb = e.boundingBox
        if abs(bb.minPoint.z - cm(z)) < tol and abs(bb.maxPoint.z - cm(z)) < tol:
            out.append(e)
    return out

def face_at_z(body, z, tol=0.01):
    for f in body.faces:
        bb = f.boundingBox
        if abs(bb.minPoint.z - cm(z)) < tol and abs(bb.maxPoint.z - cm(z)) < tol:
            return f
    return None

def safe(label, fn):
    try:
        r = fn(); log('ok', label); return r
    except Exception:
        log('FAIL', label, traceback.format_exc().splitlines()[-1]); return None

# ---------------- appearances ----------------
def find_appearance(words):
    for lib in app.materialLibraries:
        try:
            for a in lib.appearances:
                n = a.name.lower()
                if all(w in n for w in words):
                    return a
        except Exception:
            pass
    return None

def make_app(design, name, base_words, rgb):
    ex = design.appearances.itemByName(name)
    if ex: return ex
    base = None
    for words in base_words:
        base = find_appearance(words)
        if base: break
    if not base:
        log('no base appearance for', name); return None
    a = design.appearances.addByCopy(base, name)
    if rgb is not None:
        for p in a.appearanceProperties:
            if p.name in ('Color', 'Base Color', 'Diffuse Color') and p.objectType == adsk.core.ColorProperty.classType():
                try:
                    p.value = adsk.core.Color.create(rgb[0], rgb[1], rgb[2], 255)
                except Exception:
                    pass
    return a

def paint(body, a):
    if body and a:
        try: body.appearance = a
        except Exception: pass

# ---------------- build ----------------
def build(design):
    comp = design.rootComponent
    A = {
        'olive': make_app(design, 'SE Olive ASA', [['plastic', 'matte'], ['plastic']], (104, 120, 90)),
        'black': make_app(design, 'SE Black TPU', [['rubber'], ['plastic', 'matte']], (28, 29, 28)),
        'white': make_app(design, 'SE White Print', [['plastic', 'matte'], ['plastic']], (236, 236, 232)),
        'led':   make_app(design, 'SE LED Green', [['plastic', 'glossy'], ['plastic']], (60, 235, 110)),
        'cell':  make_app(design, 'SE Solar Cell', [['glass'], ['plastic', 'glossy']], (18, 30, 62)),
        'silver': make_app(design, 'SE Busbar', [['aluminum', 'polished'], ['aluminum'], ['steel']], None),
        'gold':  make_app(design, 'SE Gold', [['gold'], ['brass']], None),
        'bark':  make_app(design, 'SE Bark', [['bark'], ['walnut'], ['oak'], ['pine'], ['cherry'], ['wood'], ['leather']], None),
        'strap': make_app(design, 'SE Strap', [['fabric'], ['rubber'], ['plastic', 'matte']], (24, 24, 26)),
        'batt':  make_app(design, 'SE Cell Wrap', [['plastic', 'glossy'], ['plastic']], (40, 90, 160)),
    }
    log('appearances', {k: (v.name if v else None) for k, v in A.items()})
    parts = {}

    # ----- housing (base) -----
    def housing():
        b = rrect_body(comp, 0, 0, W, H, R_CORNER, 0, D_BASE, 'Housing')
        fillet(comp, edges_at_z(b, 0), 3.0)
        front = face_at_z(b, D_BASE)
        si = comp.features.shellFeatures.createInput(coll([front]), False)
        si.insideThickness = VI(WALL)
        comp.features.shellFeatures.add(si)
        b = comp.bRepBodies.itemByName('Housing')
        tools = []
        for (x, y) in BOSS:                          # lid screw bosses
            tools.append(add_temp(comp, cyl((x, y, 1), 3.6, (x, y, D_BASE)), 'boss'))
        for (px, py) in [(-26.5, 19), (26.5, 19), (-26.5, -19), (26.5, -19)]:   # PCB standoffs
            tools.append(add_temp(comp, cyl((px, PCB_CY + py, 1), 3.0, (px, PCB_CY + py, PCB_Z)), 'standoff'))
        for x in (-18.0, 18.0):                      # battery saddles
            s = box((x, 0, 6.0), 4, 24, 8)
            tb_cut(s, cyl((x - 3, 0, 13.5), 9.6, (x + 3, 0, 13.5)))
            tools.append(add_temp(comp, s, 'saddle'))
        combine(comp, b, tools, JOIN)
        holes = []
        for (x, y) in BOSS:
            holes.append(add_temp(comp, cyl((x, y, 12), 1.3, (x, y, D_BASE + 1)), 'h'))
        for (px, py) in [(-26.5, 19), (26.5, 19), (-26.5, -19), (26.5, -19)]:
            holes.append(add_temp(comp, cyl((px, PCB_CY + py, 15), 1.3, (px, PCB_CY + py, PCB_Z + 1)), 'h'))
        holes.append(add_temp(comp, cyl((-26, 31, 19), 3.25, (-26, 40, 19)), 'sma'))        # SMA bulkhead
        holes.append(add_temp(comp, cyl((10, 31, 12), 2.5, (10, 40, 12)), 'solar_cable'))  # panel cable grommet
        holes.append(add_temp(comp, cyl((-18, -40, 19), 6.25, (-18, -31, 19)), 'gland_piezo'))
        holes.append(add_temp(comp, cyl((20, -40, 19), 6.25, (20, -31, 19)), 'gland_vent'))
        for (x, y) in [(-26, -22), (26, -22), (-26, 22), (26, 22)]:                         # mount screws
            holes.append(add_temp(comp, cyl((x, y, -1), 2.1, (x, y, 3)), 'h'))
        combine(comp, b, holes, CUT)
        paint(b, A['olive']); parts['Housing'] = b
    safe('housing', housing)

    # ----- lid -----
    def lid():
        z0, z1 = D_BASE, D_BASE + LID_T
        b = rrect_body(comp, 0, 0, W, H, R_CORNER, z0, z1, 'Lid')
        fillet(comp, edges_at_z(b, z1), 2.5)
        lip = rrect_body(comp, 0, 0, W - 2 * WALL - 0.6, H - 2 * WALL - 0.6, R_CORNER - WALL - 0.3, z0 - 3, z0, 'lip')
        inner = rrect_body(comp, 0, 0, W - 2 * WALL - 4.6, H - 2 * WALL - 4.6, R_CORNER - WALL - 2.3, z0 - 3.5, z0 + 0.01, 'lipcut')
        combine(comp, lip, [inner], CUT)
        combine(comp, b, [lip], JOIN)
        b = comp.bRepBodies.itemByName('Lid')
        pocket = rrect_body(comp, 0, 0, W - 16, H - 16, 6, z1 - 0.8, z1 + 1, 'pocket')
        cuts = [pocket]
        for (x, y) in BOSS:
            cuts.append(add_temp(comp, cyl((x, y, z0 - 1), 1.7, (x, y, z1 + 1)), 'h'))
            cuts.append(add_temp(comp, cyl((x, y, z1 - 2), 3.2, (x, y, z1 + 1)), 'cb'))
        led = (38.26 - 30.0, PCB_CY + 22.5 - 25.68)
        cuts.append(add_temp(comp, cyl((led[0], led[1], z0 - 4), 1.6, (led[0], led[1], z1 + 1)), 'ledhole'))
        combine(comp, b, cuts, CUT)
        paint(b, A['olive']); parts['Lid'] = b
        pipe = add_temp(comp, cyl((led[0], led[1], PCB_Z + PCB_T + 0.9), 1.5, (led[0], led[1], z1 - 0.8)), 'LightPipe')
        paint(pipe, A['led']); parts['LightPipe'] = pipe
        # logo text, raised 0.6 mm on the pocket floor
        sk = comp.sketches.add(xy_plane(comp, z1 - 0.8))
        ti = sk.sketchTexts.createInput2('SylvaEcho', cm(7.5))
        ti.setAsMultiLine(adsk.core.Point3D.create(cm(-30), cm(-27), 0), adsk.core.Point3D.create(cm(30), cm(-14), 0),
                          adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
                          adsk.core.VerticalAlignments.MiddleVerticalAlignment, 0)
        st = sk.sketchTexts.add(ti)
        ext = comp.features.extrudeFeatures.addSimple(st, VI(0.6), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        for i in range(ext.bodies.count):
            ext.bodies.item(i).name = 'Logo'; paint(ext.bodies.item(i), A['white'])
    safe('lid', lid)

    # ----- gasket seam, side bumpers -----
    def trims():
        g = rrect_body(comp, 0, 0, W + 0.8, H + 0.8, R_CORNER + 0.4, D_BASE - 0.4, D_BASE + 0.4, 'Gasket')
        gi = rrect_body(comp, 0, 0, W - 1, H - 1, R_CORNER - 0.5, D_BASE - 0.5, D_BASE + 0.5, 'gcut')
        combine(comp, g, [gi], CUT)
        paint(comp.bRepBodies.itemByName('Gasket'), A['black'])
        for s in (-1, 1):
            bb = add_temp(comp, box((s * (W / 2 + 1.0), 0, 21), 3.2, 44, 12), 'Bumper_' + ('L' if s < 0 else 'R'))
            try:
                fillet(comp, [e for e in bb.edges], 1.2)
            except Exception:
                pass
            bb = comp.bRepBodies.itemByName('Bumper_' + ('L' if s < 0 else 'R'))
            paint(bb, A['black']); parts[bb.name] = bb
    safe('trims', trims)

    # ----- tree mount plate with trunk saddle and strap channel -----
    def mount():
        plate = rrect_body(comp, 0, 0, 104, 64, 8, -12, 0, 'TreeMount')
        try: fillet(comp, edges_at_z(plate, -12), 2.0)
        except Exception: pass
        plate = comp.bRepBodies.itemByName('TreeMount')
        trunk_cut = add_temp(comp, cyl((0, -60, TRUNK_CZ), TRUNK_R + 0.2, (0, 60, TRUNK_CZ)), 'tc')
        ring = cyl((0, -19.5, TRUNK_CZ), TRUNK_R + 2.6, (0, 19.5, TRUNK_CZ))
        tb_cut(ring, cyl((0, -21, TRUNK_CZ), TRUNK_R - 1, (0, 21, TRUNK_CZ)))
        ring_b = add_temp(comp, ring, 'strapcut')
        holes = [trunk_cut, ring_b]
        for (x, y) in [(-26, -22), (26, -22), (-26, 22), (26, 22)]:
            holes.append(add_temp(comp, cyl((x, y, -13), 2.1, (x, y, 1)), 'h'))
        combine(comp, plate, holes, CUT)
        paint(plate, A['black']); parts['TreeMount'] = plate
    safe('mount', mount)

    # ----- solar pod (tilted frame on a stand) -----
    def pod():
        a = math.radians(TILT)
        u = (1, 0, 0); d = (0, -math.sin(a), math.cos(a)); n = (0, math.cos(a), math.sin(a))
        c = POD_C
        add = lambda p, v, k: (p[0] + v[0] * k, p[1] + v[1] * k, p[2] + v[2] * k)
        frame = box(c, 58, 61, 6, u, d)
        tb_cut(frame, box(add(c, n, 3 - 1.1), 53, 56, 2.21, u, d))
        stand = box((c[0], 36 + 15, c[2] - 2), 36, 30, 30)
        tb_cut(stand, box(add(c, n, -3 + 50), 300, 300, 100, u, d))
        tb_union(frame, stand)
        b = add_temp(comp, frame, 'SolarPod'); paint(b, A['olive']); parts['SolarPod'] = b
        cell = add_temp(comp, box(add(c, n, 1.9), 52, 55, 2, u, d), 'SolarCell'); paint(cell, A['cell'])
        for k in (-13.5, 0, 13.5):
            bus = add_temp(comp, box(add(add(c, n, 2.93), u, k), 0.8, 51, 0.08, u, d), 'Busbar'); paint(bus, A['silver'])
        for k in range(-24, 25, 4):
            fing = add_temp(comp, box(add(add(c, n, 2.92), d, k), 51, 0.15, 0.06, u, d), 'Finger'); paint(fing, A['silver'])
    safe('pod', pod)

    # ----- antenna (868 MHz, SMA, tilt knuckle) -----
    def antenna():
        x, z = -26.0, 19.0
        y = H / 2
        parts_ = [('SMA_Nut', cyl((x, y, z), 4.6, (x, y + 2.2, z)), A['gold']),
                  ('SMA_Body', cyl((x, y + 2.2, z), 3.2, (x, y + 9, z)), A['gold']),
                  ('Ant_Knuckle', cyl((x, y + 9, z), 5.0, (x, y + 22, z)), A['black']),
                  ('Ant_Whip', cyl((x, y + 22, z), 4.6, (x, y + 118, z), 3.4), A['black']),
                  ('Ant_Tip', cyl((x, y + 118, z), 3.4, (x, y + 121, z), 2.2), A['black'])]
        for nm, t, ap in parts_:
            paint(add_temp(comp, t, nm), ap)
    safe('antenna', antenna)

    # ----- cable glands -----
    def glands():
        for nm, x in (('Gland_Piezo', -18.0), ('Vent_Membrane', 22.0)):
            y = -H / 2
            g = cyl((x, y, 19), 8.6, (x, y - 2.6, 19))
            tb_union(g, cyl((x, y - 2.6, 19), 7.4, (x, y - 9, 19)))
            tb_union(g, cyl((x, y - 9, 19), 7.0, (x, y - 14, 19), 4.0))
            paint(add_temp(comp, g, nm), A['black'])
        cable = cyl((-18, -H / 2 - 14, 19), 2.2, (-18, -H / 2 - 70, 19))
        paint(add_temp(comp, cable, 'Piezo_Cable'), A['black'])
    safe('glands', glands)

    # ----- internals: battery, holder, PCB -----
    def internals():
        hold = box((0, 0, 11.5), 63, 22, 18)
        tb_cut(hold, box((0, 0, 14.5), 55, 19, 18))
        paint(add_temp(comp, hold, 'BatteryHolder'), A['black'])
        paint(add_temp(comp, cyl((-25.25, 0, 13.5), 9.2, (25.25, 0, 13.5)), 'LiFePO4_IFR18500'), A['batt'])
    safe('internals', internals)

    def pcb():
        if not os.path.exists(PCB_STEP):
            log('no PCB step'); return
        occ = comp.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        occ.component.name = 'PCB2'
        im = app.importManager
        opt = im.createSTEPImportOptions(PCB_STEP)
        im.importToTarget(opt, occ.component)
        bb = occ.boundingBox
        log('pcb bbox cm', bb.minPoint.x, bb.minPoint.y, bb.minPoint.z, bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z)
        sx, sy, sz = bb.maxPoint.x - bb.minPoint.x, bb.maxPoint.y - bb.minPoint.y, bb.maxPoint.z - bb.minPoint.z
        m = adsk.core.Matrix3D.create()
        # assume board in XY with parts on +Z; move board back face to PCB_Z and centre it
        tx = cm(0) - (bb.minPoint.x + bb.maxPoint.x) / 2
        ty = cm(PCB_CY) - (bb.minPoint.y + bb.maxPoint.y) / 2
        tz = cm(PCB_Z) - bb.minPoint.z
        m.translation = adsk.core.Vector3D.create(tx, ty, tz)
        try: occ.transform2 = m
        except Exception: occ.transform = m
        log('pcb size cm', sx, sy, sz)
    safe('pcb', pcb)

    # ----- scene: trunk and strap -----
    def scene():
        t = add_temp(comp, cyl((0, -380, TRUNK_CZ), TRUNK_R, (0, 380, TRUNK_CZ)), 'Trunk')
        paint(t, A['bark'])
        ring = cyl((0, -19, TRUNK_CZ), TRUNK_R + 1.6, (0, 19, TRUNK_CZ))
        tb_cut(ring, cyl((0, -20, TRUNK_CZ), TRUNK_R + 0.1, (0, 20, TRUNK_CZ)))
        paint(add_temp(comp, ring, 'Strap'), A['strap'])
    # no tree trunk or strap in the scene: the case is shown on its own
    return parts

# ---------------- outputs ----------------
def export(design, parts):
    em = design.exportManager
    os.makedirs(OUT + '/print', exist_ok=True)
    for nm in ('Housing', 'Lid', 'TreeMount', 'SolarPod', 'Bumper_L', 'Bumper_R', 'LightPipe'):
        b = parts.get(nm)
        if not b: continue
        try:
            o = em.createSTLExportOptions(b, OUT + '/print/SylvaEcho_' + nm + '.stl')
            o.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
            em.execute(o); log('stl', nm)
        except Exception:
            log('FAIL stl', nm, traceback.format_exc().splitlines()[-1])
    safe('step', lambda: em.execute(em.createSTEPExportOptions(OUT + '/SylvaEcho_Enclosure.step', design.rootComponent)))
    safe('f3d', lambda: em.execute(em.createFusionArchiveExportOptions(OUT + '/SylvaEcho_Enclosure.f3d', design.rootComponent)))

def shots(design):
    vp = app.activeViewport
    try: vp.visualStyle = adsk.core.VisualStyles.ShadedVisualStyle
    except Exception: pass
    views = {
        'hero_3q':  ((215, 135, 330), (4, 18, 12)),
        'front':    ((0, 10, 420), (0, 10, 20)),
        'side':     ((420, 40, 60), (0, 20, 0)),
        'top_back': ((-180, 260, -60), (0, 20, 0)),
    }
    try:
        cam = vp.camera; cam.isSmoothTransition = False; cam.isFitView = False
        cam.eye = P(215, 135, 330); cam.target = P(4, 18, 12); cam.upVector = V(0, 1, 0)
        vp.camera = cam; vp.refresh(); adsk.doEvents()
    except Exception:
        pass
    for nm, (eye, tgt) in views.items():
        try:
            cam = vp.camera
            cam.isSmoothTransition = False
            cam.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
            cam.eye = P(*eye); cam.target = P(*tgt); cam.upVector = V(0, 1, 0)
            cam.isFitView = False
            vp.camera = cam; vp.refresh()
            adsk.doEvents()
            vp.saveAsImageFile(OUT + '/renders/viewport_' + nm + '.png', 2400, 1800)
            log('shot', nm)
        except Exception:
            log('FAIL shot', nm, traceback.format_exc().splitlines()[-1])
    # report the render API surface for the next step
    try:
        log('design render attrs', [a for a in dir(design) if 'ender' in a])
        rm = getattr(design, 'renderManager', None)
        if rm:
            log('renderManager attrs', [a for a in dir(rm) if not a.startswith('_')])
    except Exception:
        pass

def set_cam(eye, tgt, fov=None):
    vp = app.activeViewport
    cam = vp.camera
    cam.isSmoothTransition = False
    cam.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
    cam.isFitView = False
    cam.eye = P(*eye); cam.target = P(*tgt); cam.upVector = V(0, 1, 0)
    if fov:
        try: cam.perspectiveAngle = math.radians(fov)
        except Exception: pass
    vp.camera = cam; vp.refresh(); adsk.doEvents()
    return vp.camera

def render(design):
    import time
    rm = design.renderManager
    r = rm.rendering
    sc = rm.sceneSettings
    log('rendering attrs', [a for a in dir(r) if not a.startswith('_')])
    log('scene attrs', [a for a in dir(sc) if not a.startswith('_')])
    envs = []
    try:
        for i in range(rm.renderEnvironments.count):
            envs.append(rm.renderEnvironments.item(i).name)
    except Exception:
        log('env list fail', traceback.format_exc().splitlines()[-1])
    log('environments', envs)
    log('enums', [a for a in dir(adsk.fusion) if 'Render' in a or 'AspectRatio' in a or 'Resolution' in a])
    want = None
    for pref in ('Field', 'Plaza', 'Dry lake bed', 'Tranquility', 'Photo Booth'):
        for i in range(rm.renderEnvironments.count):
            e = rm.renderEnvironments.item(i)
            if pref.lower() in e.name.lower():
                want = e; break
        if want: break
    for attr in ('backgroundEnvironment', 'environment', 'activeEnvironment', 'renderEnvironment'):
        if want and hasattr(sc, attr):
            try: setattr(sc, attr, want); log('env set', attr, want.name); break
            except Exception: log('env set fail', attr, traceback.format_exc().splitlines()[-1])
    try:
        bt = adsk.fusion.RenderSceneBackgroundTypes
        env_type = [getattr(bt, x) for x in dir(bt) if 'Environment' in x]
        if env_type: sc.backgroundType = env_type[0]; log('background type set')
    except Exception:
        log('bg type fail', traceback.format_exc().splitlines()[-1])
    for attr, val in (('isGroundDisplayed', True), ('isGroundReflections', False), ('isGroundFlattened', True)):
        if hasattr(sc, attr):
            try: setattr(sc, attr, val)
            except Exception: pass
    # resolution / quality: try the largest named options that exist
    try:
        for a in dir(adsk.fusion):
            if 'RenderResolution' in a or 'RenderAspect' in a or 'RenderQuality' in a:
                enum = getattr(adsk.fusion, a)
                log(a, [x for x in dir(enum) if not x.startswith('_')])
    except Exception:
        pass
    for attr in ('resolutionWidth',):
        if hasattr(r, attr):
            try: r.resolutionWidth = 1920; r.resolutionHeight = 1280; log('res set')
            except Exception: log('res fail', traceback.format_exc().splitlines()[-1])
    for attr in ('renderQuality',):
        if hasattr(r, attr):
            try: r.renderQuality = 60; log('quality set')
            except Exception: log('quality fail', traceback.format_exc().splitlines()[-1])
    shots_ = {
        'render_hero': ((205, 120, 300), (4, 15, 10), 28),
        'render_front': ((60, 40, 300), (2, 10, 20), 24),
        'render_back': ((-260, 140, -300), (0, 10, 0), 28),
    }
    starter = None
    for a in dir(r):
        if 'local' in a.lower() and 'start' in a.lower():
            starter = getattr(r, a)
    if not starter:
        log('no local render method'); return
    for nm, (eye, tgt, fov) in shots_.items():
        path = OUT + '/renders/' + nm + '.png'
        try:
            if os.path.exists(path): os.remove(path)
            cam = set_cam(eye, tgt, fov)
            try: fut = starter(path, cam)
            except TypeError: fut = starter(path)
            t0 = time.time(); last = ''
            while time.time() - t0 < 600:
                adsk.doEvents(); time.sleep(0.5)
                st = ''
                try: st = str(fut.renderState)
                except Exception: pass
                if st != last: log('render', nm, 'state', st); last = st
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    try:
                        if 'fail' in st.lower(): break
                    except Exception: pass
                    time.sleep(2); break
            log('render done', nm, os.path.exists(path))
        except Exception:
            log('FAIL render', nm, traceback.format_exc().splitlines()[-1])

def run(context):
    try:
        log('start')
        doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.DirectDesignType
        try: design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
        except Exception: pass
        parts = build(design)
        export(design, parts)
        shots(design)
        if RENDER:
            safe('render', lambda: render(design))
        log('done')
    except Exception:
        log('FATAL', traceback.format_exc())
