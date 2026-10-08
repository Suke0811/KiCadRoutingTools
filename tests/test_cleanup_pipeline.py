#!/usr/bin/env python3
"""The #319 restructure's two load-bearing invariants:

1. The GENERALIZED soft-joint guard: a subtractive pass must never manufacture
   a soft joint. The original guard only caught a removal whose OWN two
   endpoints formed the new joint; the confirmed glasgow B1 butterfly shape --
   a removal that turns a NEIGHBOUR endpoint into a dangle which then
   cap-overlaps a THIRD dangle elsewhere -- slipped through, which is why
   mirroring the sweep into pcb_data used to let close_soft_joints plant a
   chain-perturbing bridge. Pre-existing (router-born) joints must NOT trigger
   restores -- they are close_soft_joints' repair work.

2. The uniform mutation contract: every cleanup pass mirrors its removals into
   pcb_data, so pcb_data == the write model (original input copper - strips +
   emitted results) at the end of the pipeline. verify_board_file_parity
   (KICAD_BOARD_LEDGER=1) is the audit; it must pass on a swept board and must
   FAIL loudly when a removal is made on one side only.

    python3 tests/test_cleanup_pipeline.py
"""
import io
import os
import sys
import contextlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'py_router'))  # #522
sys.path.insert(0, os.path.join(REPO, 'py_tools'))  # #522

import env_knobs

from kicad_parser import Segment
from pcb_modification import _restore_soft_joint_bridges, sweep_dead_ends
import cleanup_pipeline as cleanup


def _seg(x1, y1, x2, y2, w=0.1, net=1, layer='F.Cu'):
    return Segment(start_x=x1, start_y=y1, end_x=x2, end_y=y2,
                   width=w, layer=layer, net_id=net)


fails = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def run_guard_checks():
    # --- shape 1 (pre-#319 guard already caught this): the removed segment IS
    # the coincident bridge between two pieces; its own endpoints become the
    # cap-overlapping dangles.
    a = _seg(0, 0, 1.0, 0)
    bridge = _seg(1.0, 0, 1.05, 0)
    b = _seg(1.05, 0, 2.0, 0)
    kept, removed = _restore_soft_joint_bridges([a, b], [bridge], [], [])
    check("own-endpoints bridge removal is restored",
          bridge in kept and not removed)

    # --- shape 2 (glasgow B1, the old guard MISSED this): removing a spur
    # turns its junction into a dangle that soft-joints with a THIRD dangle.
    a = _seg(0, 0, 1.0, 0)          # kept; its (1,0) end is a junction...
    spur = _seg(1.0, 0, 1.5, 0.5)   # ...because of this spur (the removal)
    c = _seg(1.06, 0, 2.0, 0)       # third piece; (1.06,0) always dangles
    kept, removed = _restore_soft_joint_bridges([a, c], [spur], [], [])
    check("neighbour-dangle removal (glasgow B1 shape) is restored",
          spur in kept and not removed)

    # --- pre-existing joint: the same dangle pair exists BEFORE the removal,
    # so a far-away dead-end removal must NOT be restored for it.
    a = _seg(0, 0, 1.0, 0)          # (1,0) dangles even with everything kept
    c = _seg(1.06, 0, 2.0, 0)       # pre-existing soft joint with a's end
    far = _seg(5, 0, 6, 0)          # unrelated dead end
    kept, removed = _restore_soft_joint_bridges([a, c], [far], [], [])
    check("pre-existing (router-born) joint does not block a removal",
          far in removed and far not in kept)

    # --- coincident joints are not soft joints: removing a spur off a shared
    # vertex whose remaining ends are COINCIDENT must not restore anything.
    a = _seg(0, 0, 1.0, 0)
    b = _seg(1.0, 0, 2.0, 0)        # coincident with a at (1,0)
    spur = _seg(1.0, 0, 1.4, 0.4)
    kept, removed = _restore_soft_joint_bridges([a, b], [spur], [], [])
    check("removal at a coincident junction stays removed",
          spur in removed)


class _FakePCB:
    """Minimal pcb_data stand-in for sweep_dead_ends + the ledger."""
    def __init__(self, segments, vias=None, pads_by_net=None, zones=None):
        self.segments = list(segments)
        self.vias = list(vias or [])
        self.pads_by_net = pads_by_net or {}
        self.zones = zones or []
        self.nets = {}


def run_contract_checks():
    from cleanup_pipeline import verify_board_file_parity

    # A net with a routed dead-end spur: original input trunk (0,0)-(2,0) plus
    # this run's route (2,0)-(3,0) and a dead-end spur off it. Two pads anchor
    # the trunk ends so the spur is prunable copper.
    class _Pad:
        def __init__(self, x, y):
            self.global_x, self.global_y = x, y
            self.size_x = self.size_y = 0.4
            self.layers = ['F.Cu']
            self.drill = 0
            self.net_id = 1
            self.shape = 'rect'
            self.rect_rotation = 0.0
            self.component_ref = 'U1'
            self.pad_number = '1'

    orig = _seg(0, 0, 2.0, 0)
    routed_main = _seg(2.0, 0, 3.0, 0)
    routed_spur = _seg(2.5, 0, 2.5, 0.8)   # dead end (removal keeps net whole)
    pcb = _FakePCB([orig, routed_main, routed_spur],
                   pads_by_net={1: [_Pad(0, 0), _Pad(3.0, 0)]})
    results = [{'new_segments': [routed_main, routed_spur], 'new_vias': []}]

    segs_removed, vias_removed, strip = sweep_dead_ends(results, pcb, {1})
    check("sweep removed the routed spur from the write-list",
          routed_spur not in results[0]['new_segments'], f"removed={segs_removed}")
    check("sweep mirrored the removal into pcb_data (uniform contract)",
          routed_spur not in pcb.segments)
    check("routed removal is not in the input strip list", not strip)

    # Ledger must agree: board == orig - strips + emitted.
    os.environ['KICAD_BOARD_LEDGER'] = '1'
    env_knobs.refresh()
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = verify_board_file_parity(pcb, {1}, {1: [orig]}, results, strip)
        check("ledger passes on the swept board", ok, buf.getvalue().strip())

        # Now break the contract on purpose: remove a segment from pcb_data
        # only (a pass that forgot to sync the write-list). The ledger must
        # catch it -- this is the B1 class of bug.
        pcb.segments.remove(routed_main)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = verify_board_file_parity(pcb, {1}, {1: [orig]}, results, strip)
        check("ledger FAILS when board and write model diverge", not ok)
    finally:
        del os.environ['KICAD_BOARD_LEDGER']
        env_knobs.refresh()


def run_post_smooth_order_check():
    """Smoothing must be followed by the existing subtractive invariants."""
    calls = []
    originals = {}

    def replace(name, fn):
        originals[name] = getattr(cleanup, name)
        setattr(cleanup, name, fn)

    replace('nudge_grazing_microshift',
            lambda *a, **k: (0, 0, [], None))
    replace('prune_redundant_cycles',
            lambda *a, **k: (calls.append('cycles') or 0, 0, []))
    replace('collapse_strict_redundant',
            lambda *a, **k: (calls.append('strict') or 0, []))
    replace('remove_orphan_islands',
            lambda *a, **k: (0, 0, [], []))
    replace('sweep_dead_ends', lambda *a, **k: (0, 0, []))
    replace('trim_dangles_past_body_anchor', lambda *a, **k: (0, []))

    def fake_smooth(*args, **kwargs):
        calls.append('smooth')
        return 1, 1, [], [], {'spans': 1, 'saved_mm': 0.1}

    replace('smooth_octolinear_chains', fake_smooth)
    replace('close_soft_joints',
            lambda *a, **k: calls.append('close') or 0)

    class _Config:
        clearance = 0.2
        grid_step = 0.1
        guide_corridor_enabled = False
        net_clearances = None
        board_edge_clearance = 0.0

    pcb = _FakePCB([])
    old_smooth = env_knobs.SMOOTH_ROUTE
    env_knobs.SMOOTH_ROUTE = ''
    try:
        outcome = cleanup.run_post_route_cleanup(
            [], pcb, {1}, _Config(), snap=False, phantom=False,
            graze=False, octolinear=False, via_nudge=False, neck=False,
            cycles=True, smooth=True)
        check("post-smooth cycle/strict passes run before soft-joint close",
              calls == ['cycles', 'strict', 'smooth', 'cycles', 'strict',
                        'close'], f"calls={calls}")
        check("post-smooth cleanup counts are reported",
              outcome.counts.get('post_smooth_cycles_pruned') == 0
              and outcome.counts.get('post_smooth_strict_collapsed') == 0)
    finally:
        env_knobs.SMOOTH_ROUTE = old_smooth
        for name, fn in originals.items():
            setattr(cleanup, name, fn)


def main():
    print("=" * 60)
    print("cleanup pipeline invariants (#319 restructure)")
    print("=" * 60)
    run_guard_checks()
    run_contract_checks()
    run_post_smooth_order_check()
    print("=" * 60)
    if fails:
        print(f"\n{len(fails)} failure(s): {fails}")
        return 1
    print("\nALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
