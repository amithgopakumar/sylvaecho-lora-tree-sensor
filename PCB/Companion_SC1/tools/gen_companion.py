"""SylvaEcho Companion Board SC-1 schematic (KiCad 8 format, EasyEDA-safe: every net drawn with labels).

Hand-soldered build (Lion Circuits): 0805 passives, SOIC / SOT-23 / through-hole connectors only.
Run:  python3 gen_companion.py   -> ../companion/sc1.kicad_sch + expected_nets.json
"""
import json
import math
import os
import shutil
import textwrap
import uuid

from sexpr import Q, dump
from libload import load, pins

OUT = os.path.join(os.path.dirname(__file__), '..', 'companion')
NAME = 'sc1'
ROOT = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sylvaecho-sc1-root'))
_n = [0]


def uid():
    _n[0] += 1
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sylvaecho-sc1-%d' % _n[0]))


def g(v):
    return round(v / 1.27) * 1.27


def font(size=1.27, hide=False, justify=None, bold=False):
    f = ['font', ['size', str(size), str(size)]]
    if bold:
        f.append(['bold', 'yes'])
    e = ['effects', f]
    if justify:
        e.append(['justify'] + justify.split())
    if hide:
        e.append(['hide', 'yes'])
    return e


# ------------------------------------------------------------------ footprints (hand-solder)
R08 = 'Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder'
C08 = 'Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder'
LED08 = 'LED_SMD:LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder'
PH = 'Connector_JST:JST_PH_B%dB-PH-K_1x%02d_P2.00mm_Vertical'
SH4 = 'Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal'
TPTHT = 'TestPoint:TestPoint_THTPad_1.5x1.5mm_Drill0.7mm'


def R(ref, val, a, b):
    return (ref, 'Device:R', val, R08, {'1': a, '2': b})


def C(ref, val, a, b):
    return (ref, 'Device:C', val, C08, {'1': a, '2': b})


def conn(ref, val, nets):
    n = len(nets)
    return (ref, 'Connector_Generic:Conn_01x%02d' % n, val, PH % (n, n), {str(i + 1): x for i, x in enumerate(nets)})


# ------------------------------------------------------------------ parts: (ref, lib, value, footprint, {pin: net})
PARTS = [
    # 1 battery gauge
    conn('J1', 'BAT_IN (cell)', ['CELL_P', 'GND']),
    conn('J2', 'BAT_OUT (to main J2)', ['VBAT', 'GND']),
    R('R1', '0.22R 1% shunt', 'CELL_P', 'VBAT'),
    ('U2', 'Sensor_Energy:INA219AxDCN', 'INA219AIDCNR (0x40)', 'Package_TO_SOT_SMD:SOT-23-8_Handsoldering',
     {'1': 'CELL_P', '2': 'VBAT', '3': 'GND', '4': 'SNS_PWR', '5': 'ISCL', '6': 'ISDA', '7': 'GND', '8': 'GND'}),
    R('R2', '4.7k', 'SNS_PWR', 'ISDA'),
    R('R3', '4.7k', 'SNS_PWR', 'ISCL'),
    C('C3', '100nF', 'SNS_PWR', 'GND'),
    # 2 co-processor
    ('U1', 'MCU_Microchip_ATtiny:ATtiny1616-S', 'ATtiny1616-SN (I2C 0x2A)', 'Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm',
     {'1': '3V3', '20': 'GND', '16': 'UPDI', '18': 'RAIN', '19': 'NTC_CELL', '2': 'NTC_SOIL', '3': 'SOIL_ADC',
      '4': 'PZ_ADC', '5': 'WAKE_OUT', '6': 'SNS_PWR', '7': 'SOIL_PWR', '8': 'NTC_PWR', '9': 'AMP_PWR',
      '10': 'SDA', '11': 'SCL', '12': 'ISDA', '13': 'ISCL', '14': 'LED'}),
    C('C1', '100nF', '3V3', 'GND'),
    C('C2', '10uF', '3V3', 'GND'),
    ('J9', 'Connector_Generic:Conn_01x03', 'UPDI (prog)', 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
     {'1': 'UPDI', '2': '3V3', '3': 'GND'}),
    R('R16', '1k', 'LED', 'LED_A'),
    ('D2', 'Device:LED', 'GREEN', LED08, {'1': 'GND', '2': 'LED_A'}),
    R('R17', '1k', 'WAKE_OUT', 'WAKE'),
    ('TP1', 'Connector:TestPoint', 'WAKE (to main TP6)', TPTHT, {'1': 'WAKE'}),
    ('TP2', 'Connector:TestPoint', 'GND', TPTHT, {'1': 'GND'}),
    # 3 main bus + secure element
    ('J5', 'Connector_Generic:Conn_01x04', 'QWIIC_IN (main J7)', SH4, {'1': 'GND', '2': '3V3', '3': 'SDA', '4': 'SCL'}),
    ('U3', 'Security:ATECC608B-SSHDA', 'ATECC608B-SSHDA (0x60)', 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
     {'4': 'GND', '5': 'SDA', '6': 'SCL', '8': '3V3'}),
    C('C4', '100nF', '3V3', 'GND'),
    # 4 field sensors
    conn('J7', 'FIELD: soil + rain', ['SOIL_PWR', 'SOIL_AOUT', 'NTC_SOIL', 'RAIN_EXT', 'GND']),
    conn('J8', 'CELL_NTC 10k', ['NTC_CELL', 'GND']),
    R('R4', '10k 1%', 'NTC_PWR', 'NTC_CELL'),
    R('R5', '10k 1%', 'NTC_PWR', 'NTC_SOIL'),
    C('C5', '100nF', 'NTC_CELL', 'GND'),
    C('C6', '100nF', 'NTC_SOIL', 'GND'),
    R('R6', '1k', 'SOIL_AOUT', 'SOIL_ADC'),
    C('C8', '10nF', 'SOIL_ADC', 'GND'),
    C('C7', '1uF', 'SOIL_PWR', 'GND'),
    R('R7', '1M', '3V3', 'RAIN'),
    R('R8', '1k', 'RAIN_EXT', 'RAIN'),
    C('C9', '10nF', 'RAIN', 'GND'),
    # 5 trunk-sound amplifier
    conn('J3', 'PIEZO_IN (disc)', ['PIEZO', 'GND']),
    conn('J4', 'PIEZO_OUT (to main J5)', ['PIEZO', 'GND']),
    R('R11', '1M', 'PIEZO', 'PZ_A'),
    ('D1', 'Diode:BAT54S', 'BAT54S', 'Package_TO_SOT_SMD:SOT-23_Handsoldering', {'1': 'GND', '2': 'AMP_PWR', '3': 'PZ_A'}),
    C('C12', '330pF C0G', 'PZ_A', 'PZ_P'),
    R('R12', '1M', 'PZ_P', 'VMID'),
    R('R9', '1M', 'AMP_PWR', 'VMID'),
    R('R10', '1M', 'VMID', 'GND'),
    C('C11', '100nF', 'VMID', 'GND'),
    ('U4', 'Amplifier_Operational:MCP6001-OT', 'MCP6001T-I/OT', 'Package_TO_SOT_SMD:SOT-23-5_HandSoldering',
     {'1': 'AMP_OUT', '2': 'GND', '3': 'PZ_P', '4': 'PZ_N', '5': 'AMP_PWR'}),
    C('C10', '100nF', 'AMP_PWR', 'GND'),
    R('R13', '100k', 'AMP_OUT', 'PZ_N'),
    C('C13', '470pF C0G', 'AMP_OUT', 'PZ_N'),
    R('R14', '1k', 'PZ_N', 'PZ_G'),
    C('C14', '1uF', 'PZ_G', 'GND'),
    R('R15', '1k', 'AMP_OUT', 'PZ_ADC'),
    C('C15', '10nF', 'PZ_ADC', 'GND'),
]

# ------------------------------------------------------------------ sheet layout (A2, mm)
BLOCKS = [
    ('gauge', '1  BATTERY GAUGE (replaces MAX17260)', 15.24, 15.24, 279.4, 101.6, [
        'Cell -> J1 -> R1 shunt (high side) -> J2 -> main board J2.  INA219 reads VBAT (IN- to GND) and the cell current '
        'both ways: +/-40 mV range = +/-182 mA, 45 uA per step.',
        'U2 is powered from U1 (SNS_PWR) only while sampling, so it draws nothing in between (its own power-down mode '
        'still takes about 6 uA).  Private bit-banged I2C (ISDA/ISCL) so the main bus never back-powers it.',
        'Battery % = U1 coulomb count, corrected from the resting voltage at night (LiFePO4 OCV table).']),
    ('mcu', '2  CO-PROCESSOR  ATtiny1616  (I2C slave 0x2A on the main bus)', 304.8, 15.24, 274.32, 172.72, [
        'Every sensor block is powered from a U1 pin and switched off between readings.  PA7 drives WAKE as open-drain '
        '(low or Hi-Z only): optional wire from TP1 to main-board TP6 (WAKE_N).',
        'J9: UPDI programming (SerialUPDI: USB-serial adapter + 4.7k).  PA1 and PC3 spare.']),
    ('bus', '3  MAIN I2C BUS & SECURE ELEMENT', 15.24, 127.0, 279.4, 76.2, [
        'J5 from main-board J7 (Qwiic: GND, 3V3_AON, SDA, SCL; pull-ups are on the main board).  Chain more Qwiic sensors with a splitter cable.  '
        'U3 ATECC608B stores the per-node keys; default address 0x60 (confirm for the ordered variant).']),
    ('field', '4  FIELD SENSORS: SOIL MOISTURE, SOIL TEMPERATURE, RAIN, CELL TEMPERATURE', 15.24, 213.36, 279.4, 193.04, [
        'J7: capacitive soil probe (power from SOIL_PWR, 5 mA, on for about 100 ms), 10k NTC soil probe, tipping-bucket '
        'rain gauge (reed to GND, 0.2 mm per tip, wakes U1 on PA2).  J8: 10k NTC taped to the cell.',
        'NTC dividers are powered from NTC_PWR only while reading.']),
    ('amp', '5  WIDE-BAND TRUNK SOUND (RED PALM WEEVIL / BORER MODE)', 304.8, 198.12, 274.32, 208.28, [
        'Piezo passes J3 -> J4 to the main board unchanged; R11 1M taps it (no load on the main comparator).  '
        'C12/R12 high-pass about 480 Hz, gain 1 + R13/R14 = 101, R13/C13 low-pass about 3.4 kHz, R15/C15 anti-alias.',
        'U4 and its bias run from AMP_PWR only in the night listening window.  D1 clamps the tap to the amplifier rail.']),
]

P = {}


def row(refs, dx, dy, pitch=20.32, rot=0):
    for i, r in enumerate(refs):
        P[r] = (dx + i * pitch, dy, rot)


P['J1'] = (30.48, 55.88, 0)
P['J2'] = (30.48, 83.82, 0)
P['U2'] = (127.0, 66.04, 0)
row(['R1', 'R2', 'R3', 'C3'], 190.5, 68.58)
P['U1'] = (101.6, 99.06, 0)
P['J9'] = (215.9, 50.8, 0)
row(['C1', 'C2'], 200.66, 96.52)
P['R16'] = (241.3, 96.52, 0)
P['D2'] = (241.3, 129.54, 90)
P['R17'] = (205.74, 139.7, 0)
row(['TP1', 'TP2'], 205.74, 157.48, 25.4)
P['J5'] = (30.48, 45.72, 0)
P['U3'] = (167.64, 45.72, 0)
P['C4'] = (233.68, 45.72, 0)
P['J7'] = (30.48, 66.04, 0)
P['J8'] = (30.48, 116.84, 0)
row(['R4', 'R5', 'C5', 'C6', 'R6', 'C8'], 106.68, 63.5, 25.4)
row(['C7', 'R7', 'R8', 'C9'], 106.68, 129.54, 25.4)
P['J3'] = (30.48, 60.96, 0)
P['J4'] = (30.48, 101.6, 0)
row(['R11', 'C12', 'R12', 'R9', 'R10', 'C11', 'C10'], 81.28, 55.88, 25.4)
P['U4'] = (124.46, 114.3, 0)
P['D1'] = (215.9, 114.3, 0)
row(['R13', 'C13', 'R14', 'C14', 'R15', 'C15'], 81.28, 170.18, 25.4)

BLOCK_OF = {}
for key, refs in {
    'gauge': ['J1', 'J2', 'U2', 'R1', 'R2', 'R3', 'C3'],
    'mcu': ['U1', 'J9', 'C1', 'C2', 'R16', 'D2', 'R17', 'TP1', 'TP2'],
    'bus': ['J5', 'U3', 'C4'],
    'field': ['J7', 'J8', 'R4', 'R5', 'C5', 'C6', 'R6', 'C8', 'C7', 'R7', 'R8', 'C9'],
    'amp': ['J3', 'J4', 'R11', 'C12', 'R12', 'R9', 'R10', 'C11', 'C10', 'U4', 'D1', 'R13', 'C13', 'R14', 'C14', 'R15', 'C15'],
}.items():
    for r in refs:
        BLOCK_OF[r] = key

STUB = 2.54


def xf(px, py, rot):
    x, y = px, -py
    a = math.radians(rot)
    c, s = round(math.cos(a)), round(math.sin(a))
    return x * c + y * s, -x * s + y * c


OUTWARD = {0: (-1, 0), 180: (1, 0), 90: (0, -1), 270: (0, 1)}


def outward(pin_rot, sym_rot):
    vx, vy = OUTWARD[pin_rot]
    return xf(vx, vy, sym_rot)


def dirname(v):
    return {(1, 0): 'R', (-1, 0): 'L', (0, -1): 'U', (0, 1): 'D'}[(round(v[0]), round(v[1]))]


LABEL_ANG = {'R': (0, 'left'), 'U': (90, 'left'), 'L': (180, 'right'), 'D': (270, 'right')}


def wire(x1, y1, x2, y2):
    return ['wire', ['pts', ['xy', '%.2f' % x1, '%.2f' % y1], ['xy', '%.2f' % x2, '%.2f' % y2]],
            ['stroke', ['width', '0'], ['type', 'default']], ['uuid', Q(uid())]]


def text(s, x, y, size=1.5, bold=False):
    return ['text', Q(s), ['exclude_from_sim', 'no'], ['at', '%.2f' % x, '%.2f' % y, '0'],
            font(size, bold=bold, justify='left'), ['uuid', Q(uid())]]


def rect(x1, y1, x2, y2, width=0.35):
    return ['rectangle', ['start', '%.2f' % x1, '%.2f' % y1], ['end', '%.2f' % x2, '%.2f' % y2],
            ['stroke', ['width', str(width)], ['type', 'default']], ['fill', ['type', 'none']], ['uuid', Q(uid())]]


def line(x1, y1, x2, y2, width=0.25):
    return ['polyline', ['pts', ['xy', '%.2f' % x1, '%.2f' % y1], ['xy', '%.2f' % x2, '%.2f' % y2]],
            ['stroke', ['width', str(width)], ['type', 'default']], ['fill', ['type', 'none']], ['uuid', Q(uid())]]


def instance(lid, ref, val, fp, x, y, rot, pinlist, ref_at, val_at):
    fa = {90: '270', 270: '90'}.get(rot, '0')
    inst = ['symbol', ['lib_id', Q(lid)], ['at', '%.2f' % x, '%.2f' % y, str(rot)], ['unit', '1'],
            ['exclude_from_sim', 'no'], ['in_bom', 'yes'], ['on_board', 'yes'], ['dnp', 'no'], ['uuid', Q(uid())],
            ['property', Q('Reference'), Q(ref), ['at', '%.2f' % ref_at[0], '%.2f' % ref_at[1], fa],
             font(1.27, justify=ref_at[2] if len(ref_at) > 2 else None)],
            ['property', Q('Value'), Q(val), ['at', '%.2f' % val_at[0], '%.2f' % val_at[1], fa],
             font(1.27, justify=val_at[2] if len(val_at) > 2 else None)],
            ['property', Q('Footprint'), Q(fp), ['at', '%.2f' % x, '%.2f' % y, '0'], font(hide=True)],
            ['property', Q('Datasheet'), Q(''), ['at', '%.2f' % x, '%.2f' % y, '0'], font(hide=True)]]
    seen = set()
    for p in pinlist:
        if p['number'] not in seen:
            seen.add(p['number'])
            inst.append(['pin', Q(p['number']), ['uuid', Q(uid())]])
    inst.append(['instances', ['project', Q(NAME), ['path', Q('/' + ROOT), ['reference', Q(ref)], ['unit', '1']]]])
    return inst


def build():
    os.makedirs(OUT, exist_ok=True)
    libsyms, items, labels, nocs, expected = {}, [], [], [], {}
    parts = {p[0]: p for p in PARTS}
    assert set(parts) == set(BLOCK_OF) == set(P), (set(parts) ^ set(BLOCK_OF), set(parts) ^ set(P))
    for key, title, bx, by, bw, bh, notes in BLOCKS:
        items += [rect(bx, by, bx + bw, by + bh), text(title, bx + 3.81, by + 6.35, 2.54, bold=True),
                  line(bx, by + 10.16, bx + bw, by + 10.16)]
        ny = by + 15.24
        for n in notes:
            for ln in textwrap.wrap(n, int(bw / 1.05)):
                items.append(text(ln, bx + 3.81, ny, 1.27))
                ny += 2.29
        for ref in [r for r in parts if BLOCK_OF[r] == key]:
            _, lid, val, fp, nets = parts[ref]
            if lid not in libsyms:
                libsyms[lid] = load(lid)
            sym = libsyms[lid]
            dx, dy, rot = P[ref]
            x, y = g(bx + dx), g(by + dy)
            pl = [q for q in pins(sym) if q['unit'] in (0, 1)]
            pts = [xf(q['x'], q['y'], rot) for q in pl] or [(0, 0)]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if len(pl) == 2 and all(abs(p[0]) < 0.01 for p in pts):
                ref_at, val_at = (x + 2.54, y - 1.27, 'left'), (x + 2.54, y + 1.27, 'left')
            elif lid == 'Connector:TestPoint':
                ref_at, val_at = (x, y - 6.35), (x, y - 3.81)
            elif lid == 'Mechanical:MountingHole':
                ref_at, val_at = (x, y - 5.08), (x, y + 5.08)
            else:
                dirs = {dirname(outward(q['rot'], rot)) for q in pl if nets.get(q['number'])}
                ref_at = (x, y + min(min(ys), -5.08) - (STUB + 12.7 if 'U' in dirs else 3.81))
                val_at = (x, y + max(max(ys), 5.08) + (STUB + 12.7 if 'D' in dirs else 3.81))
            items.append(instance(lid, ref, val, fp, x, y, rot, pins(sym), ref_at, val_at))
            done = set()
            for q in pl:
                ox, oy = xf(q['x'], q['y'], rot)
                px, py = g(x + ox), g(y + oy)
                if (px, py) in done:
                    continue
                done.add((px, py))
                net = nets.get(q['number'])
                if not net:
                    nocs.append(['no_connect', ['at', '%.2f' % px, '%.2f' % py], ['uuid', Q(uid())]])
                    continue
                expected['%s.%s' % (ref, q['number'])] = net
                v = outward(q['rot'], rot)
                d = dirname(v)
                sx, sy = g(px + v[0] * STUB), g(py + v[1] * STUB)
                items.append(wire(px, py, sx, sy))
                ang, just = LABEL_ANG[d]
                labels.append(['label', Q(net), ['at', '%.2f' % sx, '%.2f' % sy, str(ang)],
                               ['effects', ['font', ['size', '1.27', '1.27']], ['justify', just, 'bottom']],
                               ['uuid', Q(uid())]])
    sch = ['kicad_sch', ['version', '20231120'], ['generator', Q('eeschema')], ['generator_version', Q('8.0')],
           ['uuid', Q(ROOT)], ['paper', Q('A2')],
           ['title_block', ['title', Q('SylvaEcho Companion Board SC-1 (battery gauge, security, field sensors)')],
            ['date', Q('2026-11-27')], ['rev', Q('0.1')], ['company', Q('EasyEDA Spark 2026')],
            ['comment', '1', Q('ATtiny1616, INA219, ATECC608B, MCP6001. Plugs into SylvaEcho rev 0.4 with no board change')],
            ['comment', '2', Q('Hand-soldered build: 0805 passives, SOIC / SOT-23, JST-PH through-hole')]],
           ['lib_symbols'] + list(libsyms.values())]
    sch += items + labels + nocs
    sch.append(['sheet_instances', ['path', Q('/'), ['page', Q('1')]]])
    with open(os.path.join(OUT, NAME + '.kicad_sch'), 'w') as f:
        f.write(dump(sch) + '\n')
    with open(os.path.join(OUT, NAME + '.kicad_pro'), 'w') as f:
        json.dump({'meta': {'filename': NAME + '.kicad_pro', 'version': 1}}, f)
    with open(os.path.join(OUT, 'expected_nets.json'), 'w') as f:
        json.dump(expected, f, indent=1, sort_keys=True)
    with open(os.path.join(OUT, 'parts.json'), 'w') as f:
        json.dump([{'ref': p[0], 'lib': p[1], 'value': p[2], 'fp': p[3], 'nets': p[4]} for p in PARTS], f, indent=1)
    print('parts', len(PARTS), 'labels', len(labels), 'nc', len(nocs), 'pins', len(expected))


if __name__ == '__main__':
    build()
