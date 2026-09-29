#!/usr/bin/env python3
"""#1074 -- the Edge.Cuts chainer dropped finely tessellated rings.

A footprint-carried cut-out window (a reverse-mount LED's body relief: a
rounded rectangle with r=0.1mm corners) tessellates each corner arc into the
16-chord floor of `_arc_to_segments`, 0.0098mm per chord. The chainer matched
endpoints with a SQUARE tol box (0.01mm, so up to 0.0141mm on the diagonal) and
took the FIRST candidate the bucket order reached; with the chord shorter than
the box, a neighbouring chord's endpoint also matched, the walk latched onto
it, dead-ended, and the whole ring was discarded. `board_cutouts` came back
empty, so the router, the plane fill and check_drc were all blind to copper
crossing the window -- check_drc reported the board clean while KiCad's own
DRC flagged copper_edge_clearance.

The fix takes the NEAREST matching endpoint. A real tessellation's shared
endpoints coincide exactly, so the true continuation always wins.

    python3 tests/test_1074_fine_arc_cutout_chain.py
"""
import math
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

import kicad_parser as K                                         # noqa: E402
from check_drc import run_drc                                    # noqa: E402

# Window: 2.8 x 2.0mm rounded rectangle centred on the footprint at (110, 110).
A, B = 1.3, 0.9
CX, CY = 110.0, 110.0
WINDOW_BBOX = (CX - A - 0.1, CY - B - 0.1, CX + A + 0.1, CY + B + 0.1)


def _window(r):
    """(arcs, lines) of the window in footprint-local coordinates."""
    c = r * math.cos(math.pi / 4)
    arcs = [((A + r, B), (A + c, B + c), (A, B + r)),
            ((-A, B + r), (-(A + c), B + c), (-(A + r), B)),
            ((-(A + r), -B), (-(A + c), -(B + c)), (-A, -(B + r))),
            ((A, -(B + r)), (A + c, -(B + c)), (A + r, -B))]
    lines = [((-A, B + r), (A, B + r)), ((A + r, -B), (A + r, B)),
             ((A, -(B + r)), (-A, -(B + r))), ((-(A + r), B), (-(A + r), -B))]
    return arcs, lines


def _num(v):
    return ('%.6f' % v).rstrip('0').rstrip('.')


def _board_text(r=0.1):
    arcs, lines = _window(r)
    fp = ''
    for i, (s, m, e) in enumerate(arcs):
        fp += ('\t\t(fp_arc (start %s %s) (mid %s %s) (end %s %s) '
               '(stroke (width 0.05) (type default)) (layer "Edge.Cuts") '
               '(uuid "00000000-0000-0000-0000-0000000001%02d"))\n'
               % (_num(s[0]), _num(s[1]), _num(m[0]), _num(m[1]),
                  _num(e[0]), _num(e[1]), i))
    for i, (s, e) in enumerate(lines):
        fp += ('\t\t(fp_line (start %s %s) (end %s %s) '
               '(stroke (width 0.05) (type default)) (layer "Edge.Cuts") '
               '(uuid "00000000-0000-0000-0000-0000000002%02d"))\n'
               % (_num(s[0]), _num(s[1]), _num(e[0]), _num(e[1]), i))
    outline = ''
    pts = [(100, 100), (120, 100), (120, 120), (100, 120)]
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        outline += ('\t(gr_line (start %d %d) (end %d %d) '
                    '(stroke (width 0.05) (type default)) (layer "Edge.Cuts") '
                    '(uuid "00000000-0000-0000-0000-00000000030%d"))\n'
                    % (a[0], a[1], b[0], b[1], i))
    return ('(kicad_pcb\n\t(version 20240108)\n\t(generator "test_1074")\n'
            '\t(general (thickness 1.6))\n\t(paper "A4")\n'
            '\t(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))\n'
            '\t(net 0 "")\n\t(net 1 "CROSSES_WINDOW")\n'
            + outline +
            '\t(footprint "test:window"\n\t\t(layer "F.Cu")\n'
            '\t\t(uuid "00000000-0000-0000-0000-000000000400")\n'
            '\t\t(at %s %s)\n'
            '\t\t(property "Reference" "LED1" (at 0 0 0) (layer "F.SilkS") '
            '(uuid "00000000-0000-0000-0000-000000000401") '
            '(effects (font (size 1.27 1.27))))\n' % (_num(CX), _num(CY))
            + fp +
            '\t)\n'
            '\t(segment (start 106 110) (end 114 110) (width 0.25) (layer "F.Cu") '
            '(net 1) (uuid "00000000-0000-0000-0000-000000000500"))\n)\n')


def _window_segments(r):
    """The window's Edge.Cuts segments in board coordinates, as the parser
    tessellates them (6-decimal coordinates, like a saved file)."""
    arcs, lines = _window(r)
    g = lambda p: (round(p[0] + CX, 6), round(p[1] + CY, 6))
    segs = []
    for s, m, e in arcs:
        segs += K._arc_to_segments(g(s), g(m), g(e))
    return segs + [(g(s), g(e)) for s, e in lines]


_fails = []


def check(label, cond, detail=''):
    print(f"  {'ok ' if cond else 'FAIL'}  {label}"
          + (f"   {detail}" if detail and not cond else ''))
    if not cond:
        _fails.append(label)


def main():
    text = _board_text()
    segs = K._collect_edge_cuts_segments(text)
    ring = 4 * 16 + 4
    check('the window and the outline are collected (72 segments)',
          len(segs) == ring + 4, f'got {len(segs)}')

    contours = K._chain_segments_into_contours(segs)
    lens = sorted(len(c) for c in contours)
    check('the window ring chains closed alongside the outline',
          lens == [4, ring], f'contour sizes {lens}')

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'window.kicad_pcb')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

        cutouts = K.parse_kicad_pcb(path).board_info.board_cutouts
        check('board_cutouts carries the window', len(cutouts) == 1,
              f'{len(cutouts)} cutouts')
        if cutouts:
            xs = [p[0] for p in cutouts[0]]
            ys = [p[1] for p in cutouts[0]]
            got = (min(xs), min(ys), max(xs), max(ys))
            check('the cut-out is the window, not some other ring',
                  all(abs(a - b) < 1e-3 for a, b in zip(got, WINDOW_BBOX)),
                  f'bbox {got} vs {WINDOW_BBOX}')

        v = run_drc(path, clearance=0.2, quiet=True, board_edge_clearance=0.2,
                    print_summary=False)
        edge = [x for x in v if 'board-edge' in x['type']
                and x.get('net1') == 'CROSSES_WINDOW']
        check('check_drc flags the track crossing the window', len(edge) == 1,
              f'{len(edge)} board-edge violations on CROSSES_WINDOW')

    # The pick must not depend on segment order or direction: the old walk
    # took whatever the bucket iteration reached first. Radii span chords
    # from 2um to 20um, i.e. both sides of the 0.0141mm tol-box diagonal.
    rng = random.Random(1074)
    for r in (0.02, 0.05, 0.08, 0.1, 0.15, 0.2):
        base = _window_segments(r)
        bad = 0
        for _ in range(20):
            s = list(base)
            rng.shuffle(s)
            s = [(b, a) if rng.random() < 0.5 else (a, b) for a, b in s]
            if [len(c) for c in K._chain_segments_into_contours(s)] != [len(base)]:
                bad += 1
        check(f'r={r}mm (chord {2 * r * math.sin(math.pi / 64):.4f}mm): '
              f'closes in every order', bad == 0, f'{bad}/20 orders dropped it')

    print('=' * 60)
    if _fails:
        print(f'{len(_fails)} failure(s)')
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
