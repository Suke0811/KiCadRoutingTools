#!/usr/bin/env python3
"""A single lane's exit priced by what stands in front of it (whole_ends.exit_front).

  python3 tests/test_622_exit_front.py

The ends model prices a single lane's tooth or berth by its straight run out, FRONT_REACH along its escape direction on
its layer, against copper outside the run (a pair leg's menu keeps only exits with room for the pair there,
fanout_from_plan.pair_exit_clear). On a board of its own -- an exit at the origin heading down on B.Cu, a two-pad
capacitor on B.Cu with a pad straight in front of it -- this pins:

1. the capacitor beyond the reach: clear (0);
2. the capacitor near enough to block the run, far enough for a via before it: 1 (FRONT_VIA);
3. the capacitor too near for a via before it: 2 (FRONT_BLOCKED);
4. the capacitor on the OTHER layer, near: clear -- the run is on B.Cu (a via, were it needed, would not fit there,
   but none is);
5. the capacitor's pads beside the run, not in front: clear;
6. an exit heading AWAY from the capacitor: clear;
7. the run straight BETWEEN the capacitor's two pads, the gap wide enough for a track (a track and a clearance to each
   pad): clear -- a passive is no wall where a track threads it;
8. the same with the gap a little too narrow for one: blocked (a via fitting before it, 1).
"""
import os
import sys
import tempfile
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'awx'))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
os.environ.pop('AWX_RULES', None)        # (the default rules: the test's distances are drawn from them)

import whole_ends as we  # noqa: E402
import braid as bd  # noqa: E402
from kicad_parser import parse_kicad_pcb  # noqa: E402

BOARD = """(kicad_pcb (version 20240108) (generator "test")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
  (net 1 "LANE")
  (net 2 "VCC")
  (net 3 "GND")
  (footprint "C0402" (layer "{layer}") (at 0 {y})
    (property "Reference" "C1" (at 0 0) (layer "B.SilkS"))
    (pad "1" smd rect (at {p1} 0) (size 0.5 0.5) (layers "{layer}") (net 2 "VCC"))
    (pad "2" smd rect (at {p2} 0) (size 0.5 0.5) (layers "{layer}") (net 3 "GND"))
  )
  (gr_line (start -10 -10) (end 10 -10) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 10 -10) (end 10 10) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 10 10) (end -10 10) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start -10 10) (end -10 -10) (layer "Edge.Cuts") (width 0.1))
)
"""


def level(td, name, near_edge, x=0.0, layer='B.Cu', direction='down', gap=None):
    """exit_front for an exit at the origin heading `direction` on B.Cu, the capacitor's pads (0.5 mm square) with
    their near edges `near_edge` mm below the exit: pad 1 centred at `x`, pad 2 a millimetre to its right -- or, with
    `gap`, the two either side of the run, `gap` mm apart edge to edge"""
    p = os.path.join(td, f'{name}.kicad_pcb')
    p1, p2 = (x, x + 1.0) if gap is None else (-(gap / 2 + 0.25), gap / 2 + 0.25)
    open(p, 'w').write(BOARD.format(layer=layer, p1=p1, p2=p2, y=near_edge + 0.25))
    pcb = parse_kicad_pcb(p)
    if len([q for f in pcb.footprints.values() for q in f.pads]) != 2:
        raise SystemExit(f'BROKEN TEST: the board {name} parsed without its capacitor\'s two pads')
    m = NS(exit_pt=(0.0, 0.0), direction=direction, layer='B.Cu')
    return we.exit_front(pcb, 1, m, set())


def main():
    print('=' * 60)
    print('a single lane\'s exit priced by what stands in front of it')
    print('=' * 60)
    via = bd.VIA_SIZE / 2 + bd.CLEAR                  # a via's centre from the pad's edge
    run = bd.CLEAR + bd.TRACK / 2                      # a track's centre from it
    if not via > run + 0.06:
        raise SystemExit(f'BROKEN TEST: a via ({via:.3f}) needs no more room than a track ({run:.3f}) here')
    fails = []
    with tempfile.TemporaryDirectory() as td:
        for what, kw, want in (
                ('beyond the reach', dict(near_edge=we.FRONT_REACH + run + 0.3), 0),
                ('a via fits before it', dict(near_edge=via + 0.1), 1),
                ('too near for a via', dict(near_edge=run + 0.03), 2),
                ('on the other layer', dict(near_edge=run + 0.03, layer='F.Cu'), 0),
                ('beside the run, not in front', dict(near_edge=0.3, x=2.0), 0),
                ('the exit heading away', dict(near_edge=via + 0.1, direction='up'), 0),
                ('between the pads, room for a track', dict(near_edge=via + 0.1, gap=2 * run + 0.04), 0),
                ('between the pads, too narrow for one', dict(near_edge=via + 0.1, gap=2 * run - 0.04), 1)):
            got = level(td, what.replace(' ', '_').replace(',', ''), **kw)
            if got != want:
                fails.append(f'{what}: {got}, want {want}')
    for f in fails:
        print(f'  FAIL: {f}')
    if fails:
        return 1
    print(f'PASS: clear beyond the reach, on the other layer, beside the run, heading away and threading the pads '
          f'(a gap of {2 * run + 0.04:.3f}); blocked by a gap of {2 * run - 0.04:.3f} and with a via\'s room before it, '
          f'1; blocked with none, 2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
