"""Load KiCad library symbols, flatten `extends`, strip post-v8 tokens, list pins."""
import copy
import os
from sexpr import parse, Q, find, first, strip_new

LIBDIR = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols'
_cache = {}


def _lib(name):
    if name not in _cache:
        tree = parse(open(os.path.join(LIBDIR, name + '.kicad_sym')).read())[0]
        _cache[name] = {s[1]: s for s in find(tree, 'symbol')}
    return _cache[name]


def load(lib_id):
    """Return a flattened symbol definition named lib_id (e.g. 'Device:R')."""
    lib, name = lib_id.split(':')
    syms = _lib(lib)
    sym = copy.deepcopy(syms[name])
    ext = first(sym, 'extends')
    if ext:
        parent = copy.deepcopy(syms[ext[1]])
        pname = ext[1]
        child_props = {p[1]: p for p in find(sym, 'property')}
        out = [sym[0], Q(name)]
        for x in parent[2:]:
            if isinstance(x, list) and x[0] == 'property' and x[1] in child_props:
                out.append(child_props.pop(x[1]))
            elif isinstance(x, list) and x[0] == 'symbol':
                x[1] = Q(x[1].replace(pname + '_', name + '_', 1))
                out.append(x)
            else:
                out.append(x)
        # insert remaining child-only properties before first sub-symbol
        idx = next(i for i, x in enumerate(out) if isinstance(x, list) and x[0] == 'symbol')
        for p in child_props.values():
            out.insert(idx, p)
        sym = out
    sym = strip_new(sym)
    sym[1] = Q(lib_id)
    return sym


def pins(sym):
    """List of dicts: number, name, type, x, y, rot, unit."""
    name = sym[1].split(':')[1]
    res = []
    for sub in find(sym, 'symbol'):
        unit = int(sub[1].rsplit('_', 2)[1])
        for p in find(sub, 'pin'):
            at = first(p, 'at')
            res.append(dict(type=p[1], number=first(p, 'number')[1], name=first(p, 'name')[1],
                            x=float(at[1]), y=float(at[2]), rot=int(float(at[3])), unit=unit))
    return res


if __name__ == '__main__':
    import sys
    for lid in sys.argv[1:]:
        s = load(lid)
        print(lid, [(p['number'], p['name'], p['type'], p['unit']) for p in pins(s)])
