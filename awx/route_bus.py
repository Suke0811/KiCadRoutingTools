#!/usr/bin/env python3
"""route_bus.py -- the bus step: an array pair's bus routed on the board as it is.

    python3 route_bus.py BOARD.kicad_pcb OUT.kicad_pcb --src U1 --dest U2 [--k K] [--rounds R] [--inproc]

route_bus() takes a board as the chain hands it on and writes it back with the bus laid, in the board's own frame:

1. The bus: every net between SRC and DEST the ladder admits (make_bench.pair_nets). Their copper, if any, is
   stripped: the step lays both ends of every lane.
2. SRC is fanned out for them (make_bench.fanout_source), the project floor stamped, and the ladder written: the
   plan's rivers, largest first.
3. The board is turned into the flow frame (flow_frame.py): the quarter turn that points the pair's source-to-
   destination direction along +x, about a point on the 0.1 mm lattice, so the turn is exact both ways.
4. The whole route (whole_route.chain) on the ladder's first K nets, the whole ladder by default.
5. The routed board is turned back into the board's own frame and written to OUT, its project beside it, and
   graded there: the bus's nets connected (check_connected) and the whole board DRC-clean (check_drc).

A board with inner copper layers is taken as it is: the lanes run on F.Cu and B.Cu, and a via is a through via
that passes the inner layers. The caches are off. Everything the step writes goes in OUT's work directory,
<OUT stem>.bus/, beside OUT.

Exits 0 when the bus is routed, connected and the board DRC-clean; 1 when it is not; 2 on a usage error.
"""

KRT_TOOL = {'scope': [], 'kind': 'actor'}   # #937: a research tool (awx), catalogued, shown at no door
import argparse
import contextlib
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'py_router'))

# the caches are a harness's (awx-caches-off-by-default): the step runs every stage without them
STEP_SETTINGS = {'TAUT_MEMO': '0', 'PROBE_MEMO': '0', 'STAGE_CACHE': '0'}


def route_bus(board, out, src, dest, k=None, rounds=3, inproc=False, log=print):
    """Route the bus between `src` and `dest` on `board`, writing `out`. Returns (exit code, grade line)."""
    import make_bench as mb
    import flow_frame as ff
    import whole_route as wr
    from coherent_nets import coherent_nets
    from kicad_parser import parse_kicad_pcb
    from fix_kicad_drc_settings import fix_project_for_output
    import braid as te
    import source_realize as sr
    import rules as _rules

    t0 = time.time()
    board, out = os.path.abspath(board), os.path.abspath(out)
    if not out.endswith('.kicad_pcb'):
        out += '.kicad_pcb'
    work = out[:-len('.kicad_pcb')] + '.bus'
    os.makedirs(work, exist_ok=True)
    with contextlib.redirect_stdout(sys.stderr):
        pcb = parse_kicad_pcb(board)
    for r in (src, dest):
        if r not in pcb.footprints:
            log(f'route_bus: no footprint {r} on the board')
            return 2, None
    log(f'route_bus: {os.path.basename(board)}, copper layers {pcb.board_info.copper_layers}, {src} -> {dest}')

    # 1. the bus, its copper stripped
    names = mb.pair_nets(pcb, src, dest)
    log(f'  {len(names)} nets between {src} and {dest}')
    refused = waypoint_pairs(pcb, names, src, dest)
    if refused:
        names = [n for n in names if n.split('/')[-1] not in refused]
        log('  refused, left to the rest of the chain with their copper as it is: '
            + ', '.join(f'{leg} (through {part})' for leg, part in sorted(refused.items()))
            + ' -- a pair that passes through a termination part between the arrays; the whole route lays no '
              'waypoint')
    txt, n_cut = mb.strip_pair_copper(open(board, encoding='utf-8').read(), pcb, names)
    if n_cut:
        log(f'  their copper stripped ({n_cut} chars)')
    base = os.path.join(work, 'base.kicad_pcb')
    with open(base, 'w', encoding='utf-8') as f:
        f.write(txt)
    import fanout_from_plan as fp
    fp.copy_pro(board, base)

    # 2. the source fanned out, the project floor, the ladder
    _r = _rules.install_defaults()
    log(f'  rules: clearance {te.SPEC_CLEARANCE}, track {te.TRACK}, fanout {sr.FAN_TRACK}/{sr.FAN_CLEAR}, '
        f'via {te.VIA_SIZE}/{te.VIA_DRILL}  [{_r.source}]')
    fanned = os.path.join(work, 'fanned.kicad_pcb')
    with contextlib.redirect_stdout(sys.stderr):
        n_t, n_v, failed = mb.fanout_source(base, fanned, src, names)
        fix_project_for_output(fanned, clearance=te.SPEC_CLEARANCE, track_width=sr.FAN_TRACK,
                               via_diameter=te.VIA_SIZE, via_drill=te.VIA_DRILL, verbose=False)
    log(f'  {src} fanned out: {n_t} tracks, {n_v} vias' + (f', refused {failed}' if failed else ''))
    with contextlib.redirect_stdout(sys.stderr):
        mb.write_ladder(fanned, names, log=log)
        ladder = coherent_nets(10 ** 6, fanned)
    K = min(int(k), len(ladder)) if k else len(ladder)
    nets = ladder[:K]
    log(f'  the run: K={K} of the ladder\'s {len(ladder)} nets')

    # 3. the flow frame
    with contextlib.redirect_stdout(sys.stderr):
        q, cx, cy = ff.quarter_of(parse_kicad_pcb(fanned), dest, set(nets))
    frame = os.path.join(work, 'frame.kicad_pcb')
    bad = ff.turn_file(fanned, frame, q, cx, cy)
    if bad:
        log('route_bus: the turn into the flow frame failed: ' + '; '.join(bad[:6]))
        return 2, None
    log(f'  turned into the flow frame: {q} quarter turn(s) about ({ff._fmt(cx)}, {ff._fmt(cy)})')

    # 4. the whole route
    wr.INPROC = inproc
    rc, grade = wr.chain(K, os.path.join(work, 'run'), rounds, base=frame, dest=dest, settings=STEP_SETTINGS)
    seq = _routed(os.path.join(work, 'run'))
    if rc != 0 or seq is None:
        log(f'route_bus: the whole route did not route the bus (exit {rc}): {grade}')
        return 1, grade

    # 5. back into the board's own frame, and graded there
    bad = ff.turn_file(seq, out, -q, cx, cy)
    if bad:
        log('route_bus: the turn back failed: ' + '; '.join(bad[:6]))
        return 2, grade
    for ext in ('.ladder.txt',):
        side = out[:-len('.kicad_pcb')] + ext
        if os.path.exists(side):
            os.remove(side)
    # the grade: every bus net connected, no violation on a bus net, and the whole board no worse than it came (a
    # board the chain hands on carries its earlier steps' violations; each is graded at its own project's floor)
    pats = [f'*{n}' for n in nets]
    checker = lambda name: os.path.join(HERE, '..', 'py_router', name)
    cc = wr.run([checker('check_connected.py'), out, '--nets'] + pats, dict(os.environ),
                log_path=os.path.join(work, 'conn.log'), own_process=True)[0]

    def drc(path, tag, *more):
        lp = os.path.join(work, f'drc_{tag}.log')
        wr.run([checker('check_drc.py'), path, '--clearance-margin', '0.1', '--max-print', '0', *more],
               dict(os.environ), log_path=lp, own_process=True)
        txt = open(lp, encoding='utf-8', errors='replace').read()
        m = re.search(r'FOUND (\d+) DRC VIOLATIONS', txt)
        return 0 if 'NO DRC VIOLATIONS' in txt else (int(m.group(1)) if m else None)
    d_bus, d_out, d_in = drc(out, 'bus', '--nets', *pats), drc(out, 'board'), drc(board, 'input')
    ok_drc = d_bus == 0 and None not in (d_out, d_in) and d_out <= d_in
    v, c = wr.grade_counts(out, set(nets))
    g = (f'BUS {src}->{dest} K={K} {grade.split(" ", 2)[2] if grade else ""} | on the board: vias={v} copper={c}mm '
         f'connected={int(cc == 0)} drc={int(ok_drc)} (bus {d_bus}, board {d_out} vs {d_in} in) '
         f'secs={int(time.time() - t0)}')
    log(g)
    return int(cc != 0 or not ok_drc), g


def waypoint_pairs(pcb, names, src, dest):
    """{leg: part} for the pairs among `names` that pass through a termination part between the arrays
    (pairs.pair_waypoints: a two-pad part with one pad on each leg, neither array, not under a ball)"""
    import pairs as _pairs
    by = {n.name.split('/')[-1]: i for i, n in pcb.nets.items()}
    short = [n.split('/')[-1] for n in names]
    out = {}
    for _b, (pn, nn) in _pairs.pair_names(short, admit_all=True).items():
        if pn in by and nn in by:
            for pp, _qn in _pairs.pair_waypoints(pcb, by[pn], by[nn], src, dest):
                out[pn] = out[nn] = pp.component_ref
    return out


def _routed(run_dir):
    """the last round's routed board, if the chain wrote one"""
    rs = sorted((d for d in os.listdir(run_dir) if d.startswith('r') and d[1:].isdigit()), key=lambda d: int(d[1:]))
    for d in reversed(rs):
        p = os.path.join(run_dir, d, 'seq.kicad_pcb')
        if os.path.isfile(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('board', metavar='BOARD.kicad_pcb')
    ap.add_argument('out', metavar='OUT.kicad_pcb')
    ap.add_argument('--src', required=True, help='the source array (fanned out by the step)')
    ap.add_argument('--dest', required=True, help='the destination array')
    ap.add_argument('--k', type=int, help="the ladder's first K nets (default: the whole ladder)")
    ap.add_argument('--rounds', type=int, default=3, help='fanout rounds (default 3)')
    ap.add_argument('--inproc', action='store_true', help='every stage in this process rather than each in its own')
    a = ap.parse_args()
    if not os.path.isfile(a.board):
        print(f'route_bus: no board {a.board}', file=sys.stderr)
        sys.exit(2)
    sys.exit(route_bus(a.board, a.out, a.src, a.dest, a.k, a.rounds, a.inproc)[0])


if __name__ == '__main__':
    main()
