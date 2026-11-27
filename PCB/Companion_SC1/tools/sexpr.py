"""Minimal S-expression reader/writer for KiCad files."""
import re

class Q(str):
    """A quoted string token."""

_tok = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')


def parse(text):
    pos, stack, cur = 0, [], []
    while True:
        m = _tok.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        o, c, q, a = m.groups()
        if o:
            stack.append(cur)
            cur = []
        elif c:
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif q is not None:
            cur.append(Q(q.replace('\\"', '"').replace('\\\\', '\\')))
        else:
            cur.append(a)
    return cur


def dump(node, indent=0):
    if isinstance(node, Q):
        return '"' + node.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(node, str):
        return node
    simple = all(not isinstance(x, list) for x in node)
    if simple:
        return '(' + ' '.join(dump(x) for x in node) + ')'
    pad = '\t' * (indent + 1)
    head = [dump(x) for x in node if not isinstance(x, list)]
    out = '(' + ' '.join(head)
    for x in node:
        if isinstance(x, list):
            out += '\n' + pad + dump(x, indent + 1)
    return out + '\n' + '\t' * indent + ')'


def find(node, head):
    return [x for x in node if isinstance(x, list) and x and x[0] == head]


def first(node, head):
    r = find(node, head)
    return r[0] if r else None


NEW_TOKENS = {'in_pos_files', 'duplicate_pin_numbers_are_jumpers', 'show_name',
              'do_not_autoplace', 'embedded_fonts', 'jumper_pin_groups'}


def strip_new(node):
    if not isinstance(node, list):
        return node
    return [strip_new(x) for x in node
            if not (isinstance(x, list) and x and x[0] in NEW_TOKENS)]
