#!/usr/bin/env python3
"""The joint escape: the under-pad engine laying a whole-array plan (joint=True).

  python3 tests/test_622_joint_escape_engine.py

generate_bga_fanout(escape_method='jointescape') is how awx's joint fanout
(route_bus --joint-fanout, awx/joint_escape.py) lays its plan: the under-pad
engine with `joint` on, the plan's plane-ball drops laid before anything else
(part 0), and the bus's nets held to their layers (`bus` -> net_layers). This
pins both on kicad_files/ulx3s.kicad_pcb U1, with one signal net fanned
(AUDIO_V2, ball F5) and GND a plane net dropped by the drop pass -- about a
second a run.

1. BASELINE, the liveness check: with no plan GND K10's drop via goes to the
   drop pass's own gap site, which is not the one the plan asks below, and
   AUDIO_V2 escapes on F.Cu. If either stops being so, the arms below test
   nothing, and the test says so rather than passing.
2. PART 0: a plan asking K10's drop in another diagonal gap gets it there,
   the via exactly at the site and its stub on F.Cu from the ball.
3. CONTROL: the same plan through the dog-bone engine (the same engine,
   `joint` off) is not read as a drop -- K10's via stays at the drop pass's
   site. Only the joint escape takes a plan's drops.
4. NET LAYERS: AUDIO_V2 held to In1.Cu escapes on In1.Cu alone.

Uses kicad_files/ulx3s.kicad_pcb; skips cleanly if absent.
"""
import contextlib
import io
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from bga_fanout import generate_bga_fanout  # noqa: E402

BOARD = os.path.join(ROOT, 'kicad_files', 'ulx3s.kicad_pcb')
LAYERS = ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu']
SIGNAL, PLANE = 'F5', 'K10'


def run(method='jointescape', hints=None, hold=None):
    """(the signal ball, the plane ball, tracks, vias, failed) of one fanout of U1: SIGNAL's net fanned, the rest
    either a plane net (dropped) or left alone"""
    with contextlib.redirect_stdout(io.StringIO()):
        pcb = parse_kicad_pcb(BOARD)
        fp = pcb.footprints['U1']
        sig = next(p for p in fp.pads if p.pad_number == SIGNAL)
        pln = next(p for p in fp.pads if p.pad_number == PLANE)
        bus = {'net_layers': {sig.net_name: hold}, 'priority': [sig.net_name]} if hold else None
        tracks, vias, _vr, failed = generate_bga_fanout(
            fp, pcb, layers=LAYERS, track_width=0.12, clearance=0.1, via_size=0.35, via_drill=0.2,
            net_filter=[sig.net_name], escape_method=method, plane_drop='auto', escape_dir_hints=hints, bus=bus)
    return sig, pln, tracks, vias, failed


def drop_site(p, vias):
    """p's nearest same-net via within a pitch, or None"""
    vs = [(v['x'], v['y']) for v in vias
          if v['net_id'] == p.net_id and math.hypot(v['x'] - p.global_x, v['y'] - p.global_y) < 0.7]
    return min(vs, key=lambda s: math.hypot(s[0] - p.global_x, s[1] - p.global_y), default=None)


def at(a, b):
    return a is not None and b is not None and math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-6


def layers_of(p, tracks):
    return sorted({t['layer'] for t in tracks if t['net_id'] == p.net_id})


def main():
    print('=' * 60)
    print('joint escape: the plan\'s drops and the bus\'s layers')
    print('=' * 60)
    if not os.path.exists(BOARD):
        print(f'  [SKIP] board not present: {BOARD}')
        return 0
    checks = []
    sig, pln, t0, v0, f0 = run()
    s0 = drop_site(pln, v0)
    # the plan's site: the diagonal gap up and to the left of the ball (the drop pass takes another)
    site = (round(pln.global_x - 0.4, 6), round(pln.global_y + 0.4, 6))
    key = (round(pln.global_x, 3), round(pln.global_y, 3))
    plan = {key: {'kind': 'drop', 'site': site, 'layer': 'F.Cu', 'inpad': False, 'strict': True}}
    print(f'  {PLANE} ({pln.net_name}): drop pass site {s0}, the plan asks {site}; '
          f'{SIGNAL} ({sig.net_name}) on {layers_of(sig, t0)}')
    live = s0 is not None and not at(s0, site) and layers_of(sig, t0) == ['F.Cu'] and not f0
    checks.append(('baseline: the drop pass takes another site, the signal escapes on F.Cu', live))
    if not live:
        print('  [FAIL] baseline moved -- the arms below would test nothing')
        return 1

    _s, _p, t1, v1, _f = run(hints=plan)
    got = drop_site(pln, v1)
    stub = any(t['net_id'] == pln.net_id and t['layer'] == 'F.Cu'
               and {tuple(map(lambda c: round(c, 6), t['start'])), tuple(map(lambda c: round(c, 6), t['end']))}
               == {(round(pln.global_x, 6), round(pln.global_y, 6)), site} for t in t1)
    checks.append(('part 0: the planned drop is laid at its site', at(got, site)))
    checks.append(('part 0: its stub runs on F.Cu from the ball to the site', stub))

    _s, _p, _t2, v2, _f = run(method='dogbone', hints=plan)
    checks.append(('control: the dog-bone engine does not read the plan\'s drop', at(drop_site(pln, v2), s0)))

    _s, _p, t3, _v3, f3 = run(hold=['In1.Cu'])
    checks.append(('net layers: held to In1.Cu, it escapes on In1.Cu alone',
                   layers_of(sig, t3) == ['In1.Cu'] and not f3))
    print(f'    planned drop laid at {got}; dog-bone laid it at {drop_site(pln, v2)}; '
          f'held, {SIGNAL} on {layers_of(sig, t3)} (failed {f3})')

    fails = 0
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += not ok
    print(f'\n{len(checks) - fails}/{len(checks)} checks passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
