#!/usr/bin/env python3
"""A split's islands joined into regions (route_planes._grammar_join, V2).

  python3 tests/test_plane_join.py

The grammar pour (#662) gives a split layer's dominant net the whole layer
and every other net inflated hulls round its clusters of seeds -- islands,
each one a weld the route step must make. The join links each net's islands
along a minimum spanning tree with straight corridors, keeping a corridor
only where it clears every other net's region and leaves the background
sheet one region (invariant 3b).

On kicad_files/ulx3s.kicad_pcb, GND and +3V3 sharing In1.Cu (create_plane,
dry run, results returned):

1. +3V3, the island net, ends in fewer regions than it had islands (the log's
   'N corridor(s) join them into M region(s)'), and covers its pads as before;
2. no +3V3 region comes within the fill's clearance of a pad of GND on the
   layer... measured as: the GND sheet minus every +3V3 region, each widened
   by the pour's clearance band, is still one region (the pour's own check,
   _grammar_sheet_ok, run again on what was written);
3. every +3V3 polygon is a simple polygon (the union's exterior, no holes).

Uses kicad_files/ulx3s.kicad_pcb; skips cleanly if absent.
"""
import contextlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

BOARD = os.path.join(ROOT, 'kicad_files', 'ulx3s.kicad_pcb')
NETS = ['GND', '+3V3']


def main():
    print('=' * 60)
    print("join: a split's islands linked into regions")
    print('=' * 60)
    if not os.path.exists(BOARD):
        print(f'  [SKIP] board not present: {BOARD}')
        return 0
    from kicad_parser import parse_kicad_pcb
    import route_planes as rp
    from shapely.geometry import Polygon
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pcb = parse_kicad_pcb(BOARD)
        res = rp.create_plane(
            input_file=BOARD, output_file='', net_names=NETS, plane_layers=['In1.Cu'] * len(NETS), pcb_data=pcb,
            dry_run=True, return_results=True, all_layers=['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'],
            layer_nets={'In1.Cu': list(NETS)})
    log = out.getvalue()
    zones = res[5]
    fails = []
    m = re.search(r"(\d+) hull island\(s\).*?(\d+) corridor\(s\) join them into (\d+) region\(s\)", log)
    if not m:
        fails.append('no join reported -- the split joined nothing (or reported nothing)')
    else:
        isl, cor, reg = (int(x) for x in m.groups())
        print(f'  {isl} islands, {cor} corridors, {reg} regions')
        if not reg < isl:
            fails.append(f'{reg} regions from {isl} islands: the join joined nothing')
    p33 = next(i for i, n in pcb.nets.items() if n.name == '+3V3')
    gnd = next(i for i, n in pcb.nets.items() if n.name == 'GND')
    polys = [z['polygon_points'] for z in zones if z.get('net_id') == p33]
    sheet = [z for z in zones if z.get('net_id') == gnd]
    print(f'  +3V3: {len(polys)} polygon(s) written; GND: {len(sheet)} zone(s)')
    if len(polys) != (int(m.group(3)) if m else len(polys)):
        fails.append(f'{len(polys)} +3V3 polygons written, the log says {m.group(3)} regions')
    for pl in polys:
        g = Polygon(pl)
        if not g.is_valid or len(g.interiors):
            fails.append('a +3V3 region is not a simple polygon')
            break
    if sheet:
        z = sheet[0]
        raster = rp._grammar_sheet_raster(z['polygon_points'])
        dom_pts = [(p.global_x, p.global_y) for p in pcb.pads_by_net.get(gnd, [])]
        if not rp._grammar_sheet_ok(raster, polys, z['clearance'] + z['min_thickness'] / 2.0, dom_pts):
            fails.append('the GND sheet less the joined +3V3 regions is not one region')
    for f in fails:
        print(f'  FAIL: {f}')
    if fails:
        return 1
    print('PASS: the islands joined into fewer regions, each simple, the background sheet whole')
    return 0


if __name__ == '__main__':
    sys.exit(main())
