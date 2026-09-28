#!/usr/bin/env python3
"""#1070: new vias must keep the DRILL hole-to-hole minimum from vias of their
OWN net, and the route step's rescue must space its fanout drills at the run's
--hole-to-hole-clearance rather than the board's min_hole_to_hole.

THE DEFECT. Every same-net via ring -- the one stamped for a net's existing
vias (`obstacle_map.add_same_net_via_clearance`, and its in-place twin in
`routing_context.prepare_obstacles_inplace`) and the one Phase 3 stamps around
the vias the net has just placed (`single_ended_routing`'s in-progress ring) --
was sized `via_size + clearance` only. That is the COPPER spacing. The drill
rule, `(d1 + d2) / 2 + hole_to_hole`, applies to every pair of holes whatever
their nets, and on fine vias it is the larger one:

    0.25 / 0.15 via, clearance 0.09, h2h 0.3:  copper 0.34, drill 0.45

so the rings left sites open 0.34-0.36 mm from the net's own barrels, the
0.351-0.369 mm pairs the issue measured. On standard vias the copper rule is
the larger (0.5/0.3, clearance 0.25, h2h 0.2: 0.75 vs 0.5), which is why the
rings must stay cell-for-cell identical there -- asserted below against the
old formula, not against a recorded number.

THE RESCUE HALF. `net_rescue`'s bare-ball escape rung runs
`bga_fanout.generate_bga_fanout`, whose engines read the drill floor from the
board (`board_floor(..., explicit=None)`) and so printed "Hole-to-hole 0.25mm
(from the board's own min_hole_to_hole)" under --hole-to-hole-clearance 0.3.
The engine now takes `hole_to_hole_clearance` (None keeps the board read), the
rescue passes the run's value, and it re-checks its escape's own vias against
each other (they are not on the board yet when the escape is checked).

No end-to-end board is used: routed on main at the issue's geometry
(0.25/0.15, clearance 0.09, h2h 0.3), glasgow (with and without inner planes
and the #670 env), splitflap_driver, esp_prog, cap_chain, sonde_u and tigard
all shipped ZERO sub-h2h added-via pairs, so a board-level assertion would
pass on the defect too and discriminate nothing. The rings are asserted
directly instead, on the real functions.

Every check names the mutation that must fail it.
"""
import ast
import contextlib
import io
import json
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, os.path.join(ROOT, 'rust_router'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np                                               # noqa: E402

from routing_config import GridRouteConfig, GridCoord            # noqa: E402
import obstacle_map                                              # noqa: E402
from obstacle_map import (add_same_net_via_clearance,            # noqa: E402
                          same_net_via_ring_mm, same_net_new_via_drill)
from single_ended_routing import inprogress_via_ring_cells       # noqa: E402
from synth import make_via, make_pcb                             # noqa: E402

FAILS = []


def check(name, ok, detail=''):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ''))
    if not ok:
        FAILS.append(name)


def cfg(via_size, via_drill, clearance, h2h, grid, **kw):
    return GridRouteConfig(track_width=0.1, clearance=clearance,
                           via_size=via_size, via_drill=via_drill,
                           grid_step=grid, hole_to_hole_clearance=h2h, **kw)


class Recorder:
    """The via-map calls add_same_net_via_clearance makes, per rung. A plain
    recorder rather than a Rust map, so the ring's CELL SET is what is read."""

    def __init__(self, rungs=1, populated=()):
        self.rungs = {r: ([(9999, 9999)] if r in populated else [])
                      for r in range(rungs)}

    def rung_count(self):
        return len(self.rungs)

    def rung_len(self, r):
        return len(self.rungs.get(r, []))

    def add_blocked_vias_batch(self, arr):
        self.rungs[0].extend(map(tuple, np.asarray(arr).tolist()))

    def add_blocked_vias_small_batch(self, arr):
        self.rungs.setdefault(1, []).extend(map(tuple, np.asarray(arr).tolist()))

    def add_blocked_vias_rung_batch(self, r, arr):
        self.rungs.setdefault(r, []).extend(map(tuple, np.asarray(arr).tolist()))


def nearest_open(cells, x, y, step, reach=1.0):
    """Distance (mm) from the TRUE via centre (x, y) to the nearest grid cell
    NOT in `cells` -- the closest site a new via could still take."""
    blocked = set(cells)
    gx0, gy0 = round(x / step), round(y / step)
    R = int(math.ceil(reach / step)) + 2
    best = math.inf
    for dx in range(-R, R + 1):
        for dy in range(-R, R + 1):
            c = (gx0 + dx, gy0 + dy)
            if c in blocked:
                continue
            best = min(best, math.hypot(c[0] * step - x, c[1] * step - y))
    return best


def legacy_ring(vias, net_id, config):
    """The ring exactly as main stamped it before #1070 (copper only)."""
    coord = GridCoord(config.grid_step)
    out = []
    e = max(1.0, (config.via_size + config.clearance) * coord.inv_step)
    for v in vias:
        if v.net_id != net_id:
            continue
        gx, gy = coord.to_grid(v.x, v.y)
        off = math.hypot(v.x - gx * coord.grid_step,
                         v.y - gy * coord.grid_step) / coord.grid_step
        r = e + off
        rng = int(math.ceil(r))
        for ex in range(-rng, rng + 1):
            for ey in range(-rng, rng + 1):
                if ex * ex + ey * ey <= r * r:
                    out.append((gx + ex, gy + ey))
    return out


def legacy_inprogress(v, config):
    coord = GridCoord(config.grid_step)
    vgx, vgy = coord.to_grid(v.x, v.y)
    off = math.hypot(v.x - vgx * coord.grid_step,
                     v.y - vgy * coord.grid_step) / coord.grid_step
    r = (config.via_size + config.clearance) * coord.inv_step + off
    rng = int(math.ceil(r))
    return [(vgx + ex, vgy + ey) for ex in range(-rng, rng + 1)
            for ey in range(-rng, rng + 1) if 0 < ex * ex + ey * ey <= r * r]


# Via centres: on-grid, and off-grid (a BGA via-in-pad) -- the ring must hold
# from the TRUE centre, not the rounded cell (#70).
CENTRES = ((10.0, 10.0), (10.0131, 9.9927))


def test_existing_via_ring_fine():
    print("\n1. existing same-net via ring at the issue's geometry")
    for step in (0.1, 0.05, 0.025):
        c = cfg(0.25, 0.15, 0.09, 0.3, step)
        need = 0.15 / 2 + 0.15 / 2 + 0.3          # 0.45
        for (x, y) in CENTRES:
            v = make_via(x, y, net_id=7, size=0.25, drill=0.15)
            rec = Recorder()
            add_same_net_via_clearance(rec, make_pcb(vias=[v]), 7, c)
            d = nearest_open(rec.rungs[0], x, y, step)
            # Mutation: revert the ring to via_size + clearance -> 0.34-0.36.
            check(f"grid {step} via ({x},{y}): nearest open site >= 0.45",
                  d >= need - 1e-9, f"{d:.4f} mm")
            # ...and not vacuously: the ring must not swallow the neighbourhood.
            check(f"grid {step} via ({x},{y}): ...but within one cell of it",
                  d <= need + 1.5 * step, f"{d:.4f} mm")


def test_existing_via_ring_default_unchanged():
    print("\n2. standard geometry: the ring is the old ring, cell for cell")
    arms = [(0.5, 0.3, 0.25, 0.2), (0.6, 0.3, 0.2, 0.25), (0.45, 0.2, 0.1, 0.2)]
    for (vs, vd, cl, h2h) in arms:
        for step in (0.1, 0.05):
            c = cfg(vs, vd, cl, h2h, step)
            vias = [make_via(x, y, net_id=3, size=vs, drill=vd) for x, y in CENTRES]
            vias.append(make_via(10.5, 10.2, net_id=4, size=vs, drill=vd))   # foreign
            rec = Recorder()
            add_same_net_via_clearance(rec, make_pcb(vias=vias), 3, c)
            old = legacy_ring(vias, 3, c)
            # Mutation: any change to the copper term, the sub-grid growth or
            # the <= boundary moves this set on standard boards.
            check(f"{vs}/{vd} clr {cl} h2h {h2h} grid {step}: identical cells",
                  sorted(rec.rungs[0]) == sorted(old),
                  f"{len(rec.rungs[0])} vs {len(old)} rows")


def test_ring_uses_the_nets_own_drill():
    print("\n3. a net routed at its own (#530) via class sizes the ring by it")
    c = cfg(0.25, 0.15, 0.09, 0.3, 0.05, net_via_sizes={9: (1.0, 0.7)})
    # Mutation: size the ring by config.via_drill only -> 0.45 instead of 0.725.
    check("new-via drill is the net's own 0.7, not the run's 0.15",
          abs(same_net_new_via_drill(c, 9) - 0.7) < 1e-12,
          f"{same_net_new_via_drill(c, 9)}")
    check("...and the run's for a net without a class of its own",
          abs(same_net_new_via_drill(c, 8) - 0.15) < 1e-12)
    ring = same_net_via_ring_mm(c, 9, 0.15)
    check("ring for a 0.15 barrel = (0.15 + 0.7)/2 + 0.3", abs(ring - 0.725) < 1e-12,
          f"{ring:.4f}")


def test_ring_mirrored_into_populated_rungs():
    print("\n4. the ring reaches the populated rung maps, and only those")
    c = cfg(0.25, 0.15, 0.09, 0.3, 0.05)
    v = make_via(10.0, 10.0, net_id=7, size=0.25, drill=0.15)
    rec = Recorder(rungs=3, populated=(2,))     # rung 1 allocated but EMPTY
    add_same_net_via_clearance(rec, make_pcb(vias=[v]), 7, c)
    ring = sorted(rec.rungs[0])
    # Mutation: drop the mirror -> a net searched at its own (#530) via class
    # reads rung 2 and sees no same-net ring.
    check("a populated rung carries the same ring as rung 0",
          len(ring) > 0 and sorted(rec.rungs[2]) == sorted(ring + [(9999, 9999)]),
          f"{len(rec.rungs[2]) - 1} of {len(ring)} rows")
    # Mutation: mirror into every allocated rung -> the EMPTY rung 1 fills with
    # the ring alone, and its searches stop falling back to rung 0's copper.
    check("an unpopulated rung is left unpopulated", rec.rungs[1] == [],
          f"{len(rec.rungs[1])} rows")
    try:
        from grid_router import GridObstacleMap
    except ImportError:
        check("grid_router importable", False, "Rust router not built")
        return
    obs = GridObstacleMap(2)
    obs.add_blocked_via(230, 200)     # foreign copper 1.5 mm off, rung 0 only
    obs.add_blocked_via_rung(2, 9999, 9999)        # rung 1 allocated, empty
    add_same_net_via_clearance(obs, make_pcb(vias=[v]), 7, c)
    check("real map: rung 1 still falls back to rung 0 (foreign block seen)",
          obs.rung_len(1) == 0 and obs.is_via_blocked_rung(230, 200, 1))
    check("real map: rung 2 sees the same-net ring",
          obs.is_via_blocked_rung(208, 200, 2))


def test_inprogress_ring():
    print("\n5. the Phase-3 in-progress via ring")
    for step in (0.1, 0.05, 0.025):
        c = cfg(0.25, 0.15, 0.09, 0.3, step)
        coord = GridCoord(step)
        for (x, y) in CENTRES:
            v = make_via(x, y, net_id=7, size=0.25, drill=0.15)
            cells = inprogress_via_ring_cells(v, 7, c, coord)
            own = coord.to_grid(x, y)
            # the via's own cell stays open for reuse -- measure the others
            d = nearest_open(cells + [own], x, y, step)
            check(f"grid {step} via ({x},{y}): nearest fresh site >= 0.45",
                  d >= 0.45 - 1e-9, f"{d:.4f} mm")
            check(f"grid {step} via ({x},{y}): own cell left open for reuse",
                  own not in cells)
    for (vs, vd, cl, h2h) in [(0.5, 0.3, 0.25, 0.2), (0.6, 0.3, 0.2, 0.25)]:
        for step in (0.1, 0.05):
            c = cfg(vs, vd, cl, h2h, step)
            coord = GridCoord(step)
            for (x, y) in CENTRES:
                v = make_via(x, y, net_id=7, size=vs, drill=vd)
                check(f"{vs}/{vd} grid {step} ({x},{y}): identical to the old ring",
                      inprogress_via_ring_cells(v, 7, c, coord)
                      == legacy_inprogress(v, c))


def test_inplace_prepare_restore_balanced():
    print("\n6. prepare_obstacles_inplace: ring in the map, restore balanced")
    try:
        from grid_router import GridObstacleMap
    except ImportError:
        check("grid_router importable", False, "Rust router not built")
        return
    from routing_context import prepare_obstacles_inplace, restore_obstacles_inplace
    from obstacle_map import build_layer_map
    from kicad_parser import BoardInfo
    step = 0.05
    c = cfg(0.25, 0.15, 0.09, 0.3, step)
    c.layers = ['F.Cu', 'B.Cu']
    v = make_via(10.0, 10.0, net_id=7, size=0.25, drill=0.15)
    pcb = make_pcb(vias=[v], board_info=BoardInfo(layers={0: 'F.Cu', 2: 'B.Cu'},
                                                  copper_layers=['F.Cu', 'B.Cu']))
    obs = GridObstacleMap(2)
    has_rungs = hasattr(obs, 'add_blocked_via_rung')
    if has_rungs:                       # allocate two per-net rung maps
        obs.add_blocked_via_rung(1, 9999, 9999)
        obs.add_blocked_via_rung(2, 9999, 9999)
    before = [obs.rung_len(r) for r in range(obs.rung_count())] if has_rungs else None
    cache = {}
    with contextlib.redirect_stdout(io.StringIO()):
        _stubs, cells = prepare_obstacles_inplace(
            obs, pcb, c, 7, [7], [], {}, build_layer_map(c.layers), cache)
    gx, gy = 200, 200                   # the via's cell at 0.05
    # 0.40 mm east: legal on the copper rule (0.34), illegal on the drill (0.45)
    probe = (gx + 8, gy)
    check("rung 0 blocks a site 0.40 mm from the net's own via",
          obs.is_via_blocked(*probe))
    if has_rungs:
        for r in range(1, obs.rung_count()):
            # Mutation: drop the per-net rung mirror in prepare (or, for the
            # #568 small rung when it is armed, its mirror).
            check(f"rung {r} blocks it too", obs.is_via_blocked_rung(probe[0], probe[1], r))
    with contextlib.redirect_stdout(io.StringIO()):
        restore_obstacles_inplace(obs, 7, cache, cells)
    check("restore clears the site again", not obs.is_via_blocked(*probe))
    if has_rungs:
        after = [obs.rung_len(r) for r in range(obs.rung_count())]
        # Mutation: drop the registry-driven removal -> the rung maps keep
        # the ring forever (a stale keep-out over every later net).
        check("every rung's refcounts are back where they were",
              after == before, f"{before} -> {after}")


def test_rescue_passes_the_run_h2h():
    print("\n7. net_rescue hands the run's h2h to the fanout engine")
    src = open(os.path.join(ROOT, 'py_router', 'net_rescue.py'), encoding='utf-8').read()
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'generate_bga_fanout']
    ok = []
    for n in calls:
        kw = {k.arg: k.value for k in n.keywords}
        val = kw.get('hole_to_hole_clearance')
        ok.append(isinstance(val, ast.Attribute) and val.attr == 'hole_to_hole_clearance'
                  and getattr(val.value, 'id', None) == 'config')
    # Mutation: drop the kwarg from either call -> the escape re-reads the
    # board's min_hole_to_hole and prints "from the board's own".
    check("every generate_bga_fanout call passes config.hole_to_hole_clearance",
          len(calls) >= 2 and all(ok), f"{sum(ok)}/{len(calls)} calls")
    from net_rescue import _drills_too_close
    a = make_via(0.0, 0.0, drill=0.15)
    b = make_via(0.36, 0.0, drill=0.15)
    far = make_via(0.46, 0.0, drill=0.15)
    check("two escape drills 0.36 mm apart are refused at h2h 0.3",
          _drills_too_close([a, b], 0.3))
    check("...0.46 mm apart are accepted", not _drills_too_close([a, far], 0.3))
    check("...and a lone via is never refused", not _drills_too_close([a], 0.3))


ULX3S = os.path.join(ROOT, 'kicad_files', 'ulx3s.kicad_pcb')


def test_bga_engine_takes_explicit_h2h():
    print("\n8. generate_bga_fanout spaces its drills at an EXPLICIT h2h")
    if not os.path.exists(ULX3S):
        check("ulx3s fixture present", False, ULX3S)
        return
    from kicad_parser import parse_kicad_pcb
    from bga_fanout import generate_bga_fanout
    # test_bga_fanout_underpad's #Q7 arm: plane_drop 'auto' so the underpad
    # engine's _via_site_conflict governs the via sites.
    params = dict(track_width=0.12, clearance=0.1, via_size=0.35, via_drill=0.2,
                  escape_method='underpad')
    layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]

    def run(explicit):
        with tempfile.TemporaryDirectory() as tmp:
            b = os.path.join(tmp, 'u.kicad_pcb')
            shutil.copyfile(ULX3S, b)
            with open(os.path.splitext(b)[0] + '.kicad_pro', 'w', encoding='utf-8') as f:
                json.dump({'board': {'design_settings': {
                    'rules': {'min_hole_to_hole': 0.25}}}}, f)
            pcb = parse_kicad_pcb(b)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _t, vias, _vr, failed = generate_bga_fanout(
                    pcb.footprints["U1"], pcb, layers=layers,
                    hole_to_hole_clearance=explicit, **params)
            gap = min((math.hypot(a['x'] - c['x'], a['y'] - c['y'])
                       - (a.get('drill', 0.2) + c.get('drill', 0.2)) / 2
                       for i, a in enumerate(vias) for c in vias[i + 1:]),
                      default=None)
            return len(vias), gap, buf.getvalue()

    n_none, gap_none, said_none = run(None)
    n_exp, gap_exp, said_exp = run(0.4)
    # CONTROL: None keeps reading the board (0.25) and says so.
    check("None: the board's own 0.25 is read and announced",
          "Hole-to-hole 0.25mm (from the board's own" in said_none,
          'announced' if 'from the board' in said_none else 'silent')
    check("None: some drill pair sits below 0.4 (the explicit arm can move it)",
          gap_none is not None and gap_none < 0.4 - 1e-9, f"gap {gap_none}")
    # Mutation: pass None to board_floor instead of the explicit value.
    check("explicit 0.4: every drill pair keeps 0.4", gap_exp is not None
          and gap_exp >= 0.4 - 1e-9, f"gap {gap_exp}")
    check("explicit 0.4: the board's 0.25 is not announced",
          "from the board's own" not in said_exp)
    check("explicit 0.4: vias still placed", n_exp > 0, f"{n_exp} vs {n_none}")


def main():
    print("=" * 60)
    print("#1070: new vias keep hole-to-hole from their own net's vias")
    print("=" * 60)
    test_existing_via_ring_fine()
    test_existing_via_ring_default_unchanged()
    test_ring_uses_the_nets_own_drill()
    test_ring_mirrored_into_populated_rungs()
    test_inprogress_ring()
    test_inplace_prepare_restore_balanced()
    test_rescue_passes_the_run_h2h()
    test_bga_engine_takes_explicit_h2h()
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s)")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
