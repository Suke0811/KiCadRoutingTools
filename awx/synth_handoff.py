#!/usr/bin/env python3
"""synth_handoff.py -- the whole route's trunk-to-ring HANDOFF on generated cases, in every situation (#622).

  python3 synth_handoff.py [--only TAG,..] [--jobs N] [--outdir DIR] [--list]

Each case is a synth_bus.py bus whose destination takes some of its lanes on its north and/or south face (--ring-n /
--ring-s), so the whole route hands them from its trunk to a ring round the destination's corner; with 0402s at that
corner (--hcap): beside the facing column as zynq's C98 stands by U2, just past the corner in the ring's path, two
stacked, on F or on B, either way round; the facing column's lanes packed against the corner or centred
(--w-align); the destination straight across the channel or moved across it, so the bus arrives at an angle
(--dst-dy); the lanes in order or crossing; a pair among them. And the obstacles round them (--part): a passive whose
two pads a lane must pass between, a row of them a lane's gap apart (and one with no gap), a passive square in front
of a berth's or a tooth's stub, PTH header rows across the channel, in the ring's path and in front of the facing
column, mounting holes, rows of via-sized barrels, and all of it at once. make_bench.py prepares it and whole_route.py routes it
(BASE = the bench, DEST = SD1), and each case is graded on the route -- connected, DRC, open nets, vias, from the
route's own WHOLE line -- and on the handoff itself, read off the round that laid the result (its last geometry):

  rings  the classes the solve saw; a case with no ring lane tests nothing here, and FAILS
  gap    the largest jump between two consecutive pieces of any lane: 0 when every join is drawn
  turn   the sharpest turn of any lane, in degrees: a lane stepping past a corner and back turns near 180 (a lane
         turns 90 into a berth's stub)
  hold   what the geometry PAID holding a ring lane's trunk end on its ring's side of the ring's start (`ringside`)
  static what it paid keeping lanes off parts (reported, not graded: a part a lane cannot be kept off goes back to
         the solve as a cut)

A case PASSES when it is connected, DRC-clean, has no open net, has ring lanes, gap 0, turn under 135 and nothing
paid on the hold. The table goes to OUTDIR/handoff.tsv (default tmp/synth_handoff); each case's files to OUTDIR/TAG.
"""
KRT_TOOL = {'scope': [], 'kind': 'actor'}   # #937: a research tool (awx), catalogued, shown at no door

import argparse
import concurrent.futures
import glob
import json
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# every case: K, then its synth_bus.py arguments (the destination 8 columns wide: 6 balls a ring face)
B = ['--dst-cols', '8']
C98 = ['--hcap', 'sw:1.8:-1.0:F:v']                   # beside the facing column, a ball row above the corner
SW = B + ['--ring-s', '4', '--w-align', 'south']       # 4 lanes to the south face, the facing column's packed south
CASES = [
    ('s4', 12, B + ['--ring-s', '4']),
    ('n4', 12, B + ['--ring-n', '4']),
    ('ns3', 12, B + ['--ring-n', '3', '--ring-s', '3']),
    ('s4_c98F', 12, B + ['--ring-s', '4', '--w-align', 'south'] + C98),
    ('s4_c98B', 12, B + ['--ring-s', '4', '--w-align', 'south', '--hcap', 'sw:1.8:-1.0:B:v']),
    ('s4_c98h', 12, B + ['--ring-s', '4', '--w-align', 'south', '--hcap', 'sw:1.8:-1.0:F:h']),
    ('s4_pathF', 12, B + ['--ring-s', '4', '--w-align', 'south', '--hcap', 'sw:1.0:0.8:F:h']),
    ('s4_pathB', 12, B + ['--ring-s', '4', '--w-align', 'south', '--hcap', 'sw:1.0:0.8:B:h']),
    ('s4_tight', 12, B + ['--ring-s', '4', '--w-align', 'south', '--hcap', 'sw:1.1:-0.5:F:h']),
    ('s4_two', 12, B + ['--ring-s', '4', '--w-align', 'south'] + C98 + ['--hcap', 'sw:1.8:-2.2:F:v']),
    ('n4_c98F', 12, B + ['--ring-n', '4', '--w-align', 'north', '--hcap', 'nw:1.8:-1.0:F:v']),
    ('ns3_caps', 12, B + ['--ring-n', '3', '--ring-s', '3', '--hcap', 'nw:1.8:-1.0:F:v', '--hcap', 'sw:1.8:-1.0:B:v']),
    ('s4_dyS', 12, B + ['--ring-s', '4', '--w-align', 'south', '--dst-dy', '4'] + C98),
    ('s4_dyN', 12, B + ['--ring-s', '4', '--w-align', 'south', '--dst-dy', '-4'] + C98),
    ('s4_blocks', 12, B + ['--ring-s', '4', '--w-align', 'south', '--pattern', 'blocks', '--blocks', '2'] + C98),
    ('s6_full', 12, B + ['--ring-s', '6', '--w-align', 'south'] + C98),
    ('s4_pairs', 12, B + ['--ring-s', '4', '--w-align', 'south', '--pairs', '2'] + C98),
    ('ns5_k20', 20, B + ['--ring-n', '5', '--ring-s', '5', '--hcap', 'nw:1.8:-1.0:F:v', '--hcap', 'sw:1.8:-1.0:F:v']),
    # the ring's lanes leave the source on the far side of the bundle and cross every other lane to reach their ring
    # (in K44 the south ring's lanes ran inside the bundle and ended their trunk inside the ring's start)
    ('s3_rev', 8, B + ['--ring-s', '3', '--pattern', 'reversed'] + C98),
    ('s3_rev_path', 8, B + ['--ring-s', '3', '--pattern', 'reversed', '--hcap', 'sw:1.0:0.8:F:h']),
    ('ns3_rev', 10, B + ['--ring-n', '3', '--ring-s', '3', '--pattern', 'reversed'] + C98),
    ('s4_shuf1', 12, B + ['--ring-s', '4', '--w-align', 'south', '--pattern', 'shuffle', '--seed', '1'] + C98),
    ('s4_shuf2', 12, B + ['--ring-s', '4', '--w-align', 'south', '--pattern', 'shuffle', '--seed', '2', '--hcap',
                          'sw:1.0:0.8:B:h']),
    # two caps inside the hull's margin at the corner, a lane's gap between them: the ring starts outside both, and a
    # lane cutting between them is shorter (K44's DQ12 and DQ1 between C98's pads)
    ('s4_bulge', 12, B + ['--ring-s', '4', '--w-align', 'south', '--pattern', 'blocks', '--blocks', '2',
                          '--hcap', 'sw:0.9:0.6:F:v', '--hcap', 'sw:0.9:1.95:F:v']),
    ('s4_bulgeW', 12, B + ['--ring-s', '4', '--w-align', 'south', '--pattern', 'blocks', '--blocks', '2',
                           '--hcap', 'sw:1.3:-0.3:F:v', '--hcap', 'sw:1.3:-1.65:F:v']),
    # BETWEEN PADS: with the facing column's lanes packed south (K12, ring-s 4), its ball rows stand at y -1.2, -0.4,
    # .. 4.4 from the destination's middle (dw's V). A 0402 on end centred on a row: the row's lane goes straight
    # between its pads (0.42 mm apart), its neighbours' 0.05 mm past them
    ('btw_0402', 12, SW + ['--part', 'c0402@dw:1.0:1.2:F:v']),
    ('btw_0402B', 12, SW + ['--part', 'c0402@dw:1.0:1.2:B:v']),
    ('btw_0603', 12, SW + ['--part', 'c0603@dw:1.2:1.6:F:v']),           # 0.65 mm between its pads: two lanes
    # a row of 0402s across the facing column's lanes, a lane's gap between caps (pitch 1.0: 0.36 mm) -- and none
    # (pitch 0.9: 0.26 mm)
    ('btw_row', 12, SW + ['--part', 'row@dw:1.8:1.6:F:v:n5:p1.0']),
    ('btw_row_tight', 12, SW + ['--part', 'row@dw:1.8:1.6:F:v:n5:p0.9']),
    ('btw_row_ring', 12, SW + ['--part', 'row@ds:2.0:1.2:F:h:n4:p1.0']),  # under the south face, across the ring
    # PADS IN FRONT OF STUBS: an 0402 square in front of a berth (row y 2.0), on its layer and on the other; one in
    # front of a source tooth; a row along the source's face
    ('front_dst', 12, SW + ['--part', 'c0402@dw:1.1:2.0:F:h']),
    ('front_dstB', 12, SW + ['--part', 'c0402@dw:1.1:2.0:B:h']),
    ('front_dst2', 12, SW + ['--part', 'c0402@dw:1.1:2.0:F:h', '--part', 'c0402@dw:1.1:3.6:F:h']),
    ('front_src', 12, SW + ['--part', 'c0402@sf:0.9:0.4:F:v']),
    ('front_src_row', 12, SW + ['--part', 'row@sf:1.5:0.0:F:v:n6:p1.0']),
    # PTH HEADER ROWS (1.7 mm pads, 2.54 pitch: 0.84 mm between pins, two lanes): across the channel, in the ring's
    # path past the corner, in front of the facing column
    ('pth_ch', 12, SW + ['--part', 'pth@ch:6:0:v:n5']),
    ('pth_corner', 12, SW + ['--part', 'pth@sw:1.5:2.2:h:n4']),
    ('pth_dw', 12, SW + ['--part', 'pth@dw:2.6:1.6:v:n3']),
    # HOLES: a 3.2 mm mounting hole mid-channel, a 2.2 at the corner in the ring's path, one under the south face
    ('npth_ch', 12, SW + ['--part', 'npth@ch:6:0']),
    ('npth_corner', 12, SW + ['--part', 'npth@sw:2.0:2.4:d2.2']),
    ('npth_ring', 12, SW + ['--part', 'npth@ds:2.4:2.6:d2.2']),
    # VIA-SIZED BARRELS (0.6 mm, both layers): across the corner, a stitching row under the south face
    ('vias_corner', 12, SW + ['--part', 'vias@sw:1.2:1.2:h:n4:p0.8']),
    ('vias_ds', 12, SW + ['--part', 'vias@ds:0.8:1.3:h:n6:p1.0']),
    # ALL AT ONCE, zynq-like: both rings, the bus at an angle, a cap pair beside each corner, a decoupling row along
    # the facing column, a stitching row under the south face, a hole in the channel
    ('mix', 16, B + ['--ring-n', '3', '--ring-s', '5', '--dst-dy', '3', '--pattern', 'blocks', '--blocks', '2',
                     '--hcap', 'sw:1.8:-1.0:F:v', '--hcap', 'sw:1.8:-2.2:F:v', '--hcap', 'nw:1.8:-1.0:B:v',
                     '--part', 'row@dw:1.4:0:F:v:n4:p1.0', '--part', 'vias@ds:1.0:1.4:h:n5:p1.0',
                     '--part', 'npth@ch:5:-2:d2.2']),
]


def run(argv, log, env=None, timeout=None):
    with open(log, 'w') as fh:
        try:
            return subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=HERE, env=env, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            fh.write(f'\nTIMEOUT after {timeout} s\n')
            return -1


def handoff_marks(geo):
    """(largest jump between consecutive pieces of a lane, sharpest turn in degrees) over every lane of a geometry"""
    gap, turn = 0.0, 0.0
    for L in geo['lanes'].values():
        pcs = [p for p in L['pieces'] if math.hypot(p[2] - p[0], p[3] - p[1]) > 1e-9]
        for a, b in zip(pcs, pcs[1:]):
            gap = max(gap, math.hypot(b[0] - a[2], b[1] - a[3]))
            d1, d2 = (a[2] - a[0], a[3] - a[1]), (b[2] - b[0], b[3] - b[1])
            c = (d1[0] * d2[0] + d1[1] * d2[1]) / (math.hypot(*d1) * math.hypot(*d2))
            turn = max(turn, math.degrees(math.acos(max(-1.0, min(1.0, c)))))
    return gap, turn


def one(tag, K, args, outdir, timeout):
    d = os.path.join(outdir, tag)
    os.makedirs(d, exist_ok=True)
    raw, bench = os.path.join(d, 'raw.kicad_pcb'), os.path.join(d, 'bench.kicad_pcb')
    row = {'tag': tag, 'k': K, 'args': ' '.join(args)}
    if run([PY, 'synth_bus.py', raw, '--k', str(K)] + args, os.path.join(d, 'gen.log')):
        return dict(row, verdict='GEN FAILED')
    if run([PY, 'make_bench.py', raw, 'SU1', 'SD1', bench], os.path.join(d, 'bench.log')) or not os.path.isfile(bench):
        return dict(row, verdict='BENCH FAILED')
    t0 = time.time()
    rc = run([PY, 'whole_route.py', str(K), os.path.join(d, 'run')], os.path.join(d, 'run.log'),
             env=dict(os.environ, BASE=bench, DEST='SD1'), timeout=timeout)
    row['secs'] = round(time.time() - t0)
    whole = [ln for ln in open(os.path.join(d, 'run.log')) if ln.startswith('WHOLE')]
    if not whole:
        return dict(row, verdict=f'NO RESULT (rc {rc})')
    w = dict(re.findall(r'(\w+)=(\S+)', whole[-1]))
    row.update({k: w.get(k) for k in ('round', 'lanes', 'vias', 'connected', 'drc', 'open')})
    cl = [ln for ln in open(os.path.join(d, 'run', 'r1', 'solve.log')) if ln.startswith('classes:')] \
        if os.path.isfile(os.path.join(d, 'run', 'r1', 'solve.log')) else []
    row['rings'] = re.sub(r'\s+', '', cl[0].split('}')[0].split(':', 1)[1] + '}') if cl else '?'
    gs = sorted(glob.glob(os.path.join(d, 'run', f'r{w.get("round", 1)}', 'loop', 'g*.json')),
                key=lambda p: int(re.sub(r'\D', '', os.path.basename(p)) or 0))
    if gs:
        gap, turn = handoff_marks(json.load(open(gs[-1])))
        paid = open(gs[-1].replace('.json', '.log')).read() if os.path.isfile(gs[-1].replace('.json', '.log')) else ''
        m = re.search(r'PAID ringside (\d+)', paid)
        st = re.search(r'PAID static (\d+)', paid)
        row.update(gap=round(gap, 3), turn=round(turn, 1), hold=int(m.group(1)) if m else 0,
                   static=int(st.group(1)) if st else 0)
    ok = (w.get('connected') == '1' and w.get('drc') == '1' and w.get('open') == '0' and ("'S'" in row['rings']
          or "'N'" in row['rings']) and row.get('gap', 1) < 1e-6 and row.get('turn', 180) < 135 and row.get('hold', 1) == 0)
    return dict(row, verdict='PASS' if ok else 'FAIL')


COLS = ('tag', 'k', 'verdict', 'rings', 'round', 'lanes', 'vias', 'connected', 'drc', 'open', 'gap', 'turn', 'hold',
        'static', 'secs', 'args')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--only', help='comma-separated case tags')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--outdir', default=os.path.join(HERE, 'tmp', 'synth_handoff'))
    ap.add_argument('--timeout', type=int, default=1800, help='each whole route, s')
    ap.add_argument('--list', action='store_true', help='print the cases and stop')
    a = ap.parse_args(argv)
    cases = [c for c in CASES if not a.only or c[0] in a.only.split(',')]
    if a.list:
        for tag, K, args in cases:
            print(f'{tag:10s} K={K:2d} {" ".join(args)}')
        return 0
    os.makedirs(a.outdir, exist_ok=True)
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(one, tag, K, args, os.path.abspath(a.outdir), a.timeout): tag for tag, K, args in cases}
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            rows.append(r)
            print('  '.join(f'{c}={r.get(c)}' for c in COLS if c != 'args'), flush=True)
    order = {c[0]: i for i, c in enumerate(CASES)}
    rows.sort(key=lambda r: order[r['tag']])
    with open(os.path.join(a.outdir, 'handoff.tsv'), 'w') as fh:
        fh.write('\t'.join(COLS) + '\n')
        for r in rows:
            fh.write('\t'.join(str(r.get(c, '')) for c in COLS) + '\n')
    n_pass = sum(r['verdict'] == 'PASS' for r in rows)
    print(f'\n{n_pass}/{len(rows)} PASS -- {os.path.join(a.outdir, "handoff.tsv")}')
    return 0 if n_pass == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
