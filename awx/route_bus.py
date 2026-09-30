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


# the sizes route_bus takes, as the routing CLIs spell them (route.py's, and the escapes' own track)
SIZE_ARGS = ('clearance', 'clearance_ceiling', 'track_width', 'fanout_track_width', 'via_size', 'via_drill',
             'hole_to_hole_clearance', 'board_edge_clearance')


def resolve_rules(board, clearance=None, clearance_ceiling=None, track_width=None, fanout_track_width=None,
                  via_size=None, via_drill=None, hole_to_hole_clearance=None, board_edge_clearance=None, log=print):
    """The run's rules: the chain's sizes, resolved as route.py resolves its own, through Rules.from_router_config
    (rules.py's one seam; rules.py itself never reads a board).

    A size given is taken. One omitted is the board's Default net class's, else routing_defaults'. The clearance is
    capped at `clearance_ceiling` (min of the two, route.py's reading). The hole-to-hole and edge floors are the
    board's own when not given (list_nets.resolve_cli_floor). Every size is pinned up to the fab floor for the
    board's copper layer count (fab_tiers.enforce_fab_floors). The escapes' track is `fanout_track_width`, else the
    lanes' -- the chain lays its fanout narrower than its routes, and a router config has one track."""
    import dataclasses
    import types
    import routing_defaults as defaults
    import rules as _rules
    from list_nets import board_default_netclass_param, resolve_cli_floor
    from fab_tiers import enforce_fab_floors, count_copper_layers_in_file
    got = {}
    for name, key, given, fallback in (('track_width', 'track_width', track_width, defaults.TRACK_WIDTH),
                                       ('via_size', 'via_diameter', via_size, defaults.VIA_SIZE),
                                       ('via_drill', 'via_drill', via_drill, defaults.VIA_DRILL),
                                       ('clearance', 'clearance', clearance, defaults.CLEARANCE)):
        if given is None:
            v = board_default_netclass_param(board, key)
            given = v if v is not None else fallback
            log(f'  --{name.replace("_", "-")} not given: {given} mm, '
                f'{"the board Default net class" if v is not None else "the fallback"}')
        got[name] = float(given)
    if clearance_ceiling is not None and clearance_ceiling < got['clearance']:
        log(f'  --clearance-ceiling {clearance_ceiling}: the clearance {got["clearance"]} capped at it')
        got['clearance'] = float(clearance_ceiling)
    got['hole_to_hole_clearance'] = resolve_cli_floor(board, 'hole_to_hole', hole_to_hole_clearance,
                                                      defaults.HOLE_TO_HOLE_CLEARANCE, '--hole-to-hole-clearance')
    got['board_edge_clearance'] = resolve_cli_floor(board, 'board_edge_clearance', board_edge_clearance,
                                                    defaults.BOARD_EDGE_CLEARANCE, '--board-edge-clearance')
    n_cu = count_copper_layers_in_file(board)
    got.update(enforce_fab_floors(n_cu, **got))
    fan = float(fanout_track_width) if fanout_track_width is not None else got['track_width']
    fan = enforce_fab_floors(n_cu, track_width=fan).get('track_width', fan)
    r = _rules.Rules.from_router_config(types.SimpleNamespace(**got), fan_track=fan)
    return dataclasses.replace(r, source='the chain\'s sizes, resolved as route.py resolves its own')


def route_bus(board, out, src, dest, k=None, rounds=3, inproc=False, log=print, **sizes):
    """Route the bus between `src` and `dest` on `board`, writing `out`, at the chain's sizes (`sizes`: SIZE_ARGS,
    resolve_rules). Returns (exit code, grade line). The run's rules are installed for the step and supplied to
    every stage (rules.SETTING); the process's own are put back after."""
    import rules as _rules
    bad = sorted(set(sizes) - set(SIZE_ARGS))
    if bad:
        raise TypeError(f'route_bus: no size {bad}')
    run_rules = resolve_rules(board, log=log, **sizes)
    prev = _rules.active()
    _rules.install(run_rules)
    try:
        return _route(board, out, src, dest, k, rounds, inproc, log, run_rules)
    finally:
        _rules.install(prev)


def _route(board, out, src, dest, k, rounds, inproc, log, run_rules):
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
    log(f'  rules: clearance {te.SPEC_CLEARANCE}, track {te.TRACK}, fanout {sr.FAN_TRACK}/{sr.FAN_CLEAR}, '
        f'via {te.VIA_SIZE}/{te.VIA_DRILL}  [{run_rules.source}]')
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
    rc, grade = wr.chain(K, os.path.join(work, 'run'), rounds, base=frame, dest=dest,
                         settings={**STEP_SETTINGS, _rules.SETTING: _rules.as_setting(run_rules)})
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
    g = ap.add_argument_group('sizes', 'the chain\'s sizes, as the routing CLIs take them; one omitted is resolved as '
                                       'route.py resolves it (the board\'s Default net class, else the fallback)')
    g.add_argument('--clearance', type=float, help='the run\'s clearance (mm)')
    g.add_argument('--clearance-ceiling', type=float, help='cap the clearance at this (mm), as route.py does')
    g.add_argument('--track-width', type=float, help='the lanes\' track (mm)')
    g.add_argument('--fanout-track-width', type=float, help='the escapes\' track (mm; default: --track-width)')
    g.add_argument('--via-size', type=float, help='via diameter (mm)')
    g.add_argument('--via-drill', type=float, help='via drill (mm)')
    g.add_argument('--hole-to-hole-clearance', type=float, help='drill to drill (mm; default: the board\'s own)')
    g.add_argument('--board-edge-clearance', type=float, help='copper to edge (mm; default: the board\'s own)')
    a = ap.parse_args()
    if not os.path.isfile(a.board):
        print(f'route_bus: no board {a.board}', file=sys.stderr)
        sys.exit(2)
    sizes = {n: getattr(a, n) for n in SIZE_ARGS if getattr(a, n) is not None}
    sys.exit(route_bus(a.board, a.out, a.src, a.dest, a.k, a.rounds, a.inproc, **sizes)[0])


if __name__ == '__main__':
    main()
