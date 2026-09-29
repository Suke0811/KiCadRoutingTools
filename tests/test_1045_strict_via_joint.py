#!/usr/bin/env python3
"""A track that ends inside a via's barrel is one fragment in the strict view (#1045).

route.py reported watchy's SCL `open_single` (FRAGMENT SWEEP) on a board that
check_connected and kicad-cli both graded connected. `prune_grazing_segments`
had dropped the short connector from a B.Cu track into a via, leaving the
track's end (81.75, 83.575) 0.146 mm from the via centre (81.875, 83.5): via
0.3, track 0.0889. The end is INSIDE the barrel.

Three connectivity views disagreed about that joint:

  * the grader credits any copper overlap: 0.15 + 0.044 = 0.194 > 0.146;
  * the prune's strict twin (#322) clamps tracks to COINCIDENCE_TOL and keeps
    the via full size: 0.15 + 0.01 = 0.16 > 0.146, so the prune saw no
    worsening and dropped the connector;
  * the strict-fragment view demanded a STRICT_JOINT_OVERLAP (0.05) lens:
    0.194 - 0.05 = 0.144 < 0.146, so the sweep counted two fragments.

check_net_connectivity documents the strict view as sitting BETWEEN the grader
and the removal twin. For a via joint with a track under 0.12 mm it was stricter
than the twin, so a removal the twin allowed became a split the sweep reported.
The strict view already credits a track end inside a PAD's copper (the exact pad
rules); a via now gets the same: a centreline inside the barrel is joined,
however thin the track.

The negative control keeps the fix from collapsing into the grader: a thin
track ending OUTSIDE the barrel with a lens under STRICT_JOINT_OVERLAP still
splits in the strict view.

    python3 tests/test_1045_strict_via_joint.py
"""
import math
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TESTS)
for p in (ROOT, _TESTS, os.path.join(ROOT, 'py_router'), os.path.join(ROOT, 'py_tools')):
    if p not in sys.path:
        sys.path.insert(0, p)

from synth import make_pad, make_seg, make_via
from check_connected import (check_net_connectivity, net_copper_fragments,
                             STRICT_JOINT_OVERLAP)
from pcb_modification import _strict_conn_graph

FAILS = []

# watchy SCL, as the ledger trace recorded it.
VIA_X, VIA_Y, VIA_SIZE = 81.875, 83.5, 0.3
TIP_X, TIP_Y = 81.75, 83.575
TRACK_W = 0.0889


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))


def _net(tip_x, tip_y, width=TRACK_W):
    """pad A (B.Cu) -- B.Cu track ending at the tip -- via -- F.Cu track -- pad B.

    The B.Cu track runs along the tip's own y, so its end is the only part of
    it near the via."""
    pads = [make_pad(1, tip_x - 3.0, tip_y, num='1', layers=('B.Cu',)),
            make_pad(1, VIA_X + 3.0, VIA_Y, num='2', layers=('F.Cu',))]
    segs = [make_seg(tip_x - 3.0, tip_y, tip_x, tip_y, layer='B.Cu', width=width),
            make_seg(VIA_X, VIA_Y, VIA_X + 3.0, VIA_Y, layer='F.Cu', width=width)]
    vias = [make_via(VIA_X, VIA_Y, size=VIA_SIZE, drill=0.15)]
    return segs, vias, pads


def _views(segs, vias, pads):
    grader = check_net_connectivity(1, segs, vias, pads, [])['connected']
    twin = _strict_conn_graph(1, segs, vias, pads, [])[0]['connected']
    strict = check_net_connectivity(1, segs, vias, pads, [],
                                    strict_fragments=True)['connected']
    return grader, twin, strict


def t_the_watchy_joint_is_one_fragment():
    segs, vias, pads = _net(TIP_X, TIP_Y)
    d = math.hypot(TIP_X - VIA_X, TIP_Y - VIA_Y)
    check('the fixture tip is inside the barrel, with a lens under the strict overlap',
          d < VIA_SIZE / 2 and VIA_SIZE / 2 + TRACK_W / 2 - d < STRICT_JOINT_OVERLAP,
          f'tip {d:.4f} from centre, radius {VIA_SIZE / 2}')
    grader, twin, strict = _views(segs, vias, pads)
    check('the grader joins it', grader)
    check("the prune's strict twin joins it", twin)
    check('the strict-fragment view joins it', strict)
    frag = net_copper_fragments(1, segs, vias, pads, [])
    check('net_copper_fragments counts one fragment', frag['fragments'] == 1,
          f"fragments={frag['fragments']}")


def t_a_thin_tip_outside_the_barrel_still_splits():
    # 0.17 from the centre: 0.02 outside the barrel, lens 0.194 - 0.17 = 0.024.
    d = 0.17
    segs, vias, pads = _net(VIA_X - d, VIA_Y)
    grader, twin, strict = _views(segs, vias, pads)
    check('outside the barrel: the grader still joins it', grader)
    check('outside the barrel: the strict view still splits it', not strict)


def t_the_strict_view_sits_between_grader_and_twin_for_vias():
    """Every tip inside the barrel is joined in the strict view, and the strict
    view never joins what the grader splits -- across the fab-floor widths."""
    r = VIA_SIZE / 2
    bad_inside, bad_order = [], []
    for w in (0.0762, 0.0889, 0.1, 0.127, 0.15, 0.25):
        steps = int(round((r + w / 2 + 0.01) / 0.001))
        for k in range(steps + 1):
            d = k * 0.001
            segs, vias, pads = _net(VIA_X - d, VIA_Y, width=w)
            grader, twin, strict = _views(segs, vias, pads)
            if d < r - 1e-9 and not strict:
                bad_inside.append((w, round(d, 4)))
            if strict and not grader:
                bad_order.append((w, round(d, 4)))
    check('every tip inside the barrel is joined in the strict view',
          not bad_inside, f'(width, tip distance) split: {bad_inside[:6]}')
    check('the strict view never joins what the grader splits',
          not bad_order, f'{bad_order[:6]}')


def main():
    t_the_watchy_joint_is_one_fragment()
    t_a_thin_tip_outside_the_barrel_still_splits()
    t_the_strict_view_sits_between_grader_and_twin_for_vias()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {', '.join(FAILS)}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
