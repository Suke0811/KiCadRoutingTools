#!/usr/bin/env python3
"""Independent grade of a pcb-free-agent board -- never the agent's own claim.

    python3 -X utf8 .claude/skills/pcb-free-agent/scripts/grade.py BOARD \
        --baseline INPUT.kicad_pcb [--intent INTENT.json] [--mode full|place|route] \
        [--label NAME] [--out-dir DIR]

Runs the graders the skill's verifier runs, at the board's own .kicad_pro
floor, and writes `<out-dir>/grade_<label>.json` with the headline numbers
and each tool's exit code. Grade every arm of a comparison with this same
script at the same commit, or the numbers do not compare.

`--mode route` also checks that no footprint moved against --baseline.
Exit 0 when the mode's DONE conditions all hold, 4 when they do not, 2 on
usage.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

KRT_TOOL = {'scope': ['placement', 'routing', 'combined'], 'kind': 'instrument'}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))


def _run(argv):
    p = subprocess.run([sys.executable, '-X', 'utf8'] + [str(a) for a in argv],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _poses(board):
    sys.path.insert(0, os.path.join(ROOT, 'py_router'))
    from kicad_parser import parse_kicad_pcb
    pcb = parse_kicad_pcb(board)
    return {k: (round(f.x, 4), round(f.y, 4), round((f.rotation or 0) % 360, 3),
                f.layer)
            for k, f in pcb.footprints.items() if f.pads}


def grade(board, baseline, intent=None, mode='full', label=None, out_dir=None):
    # Absolute BEFORE anything runs: every checker runs with cwd=ROOT, so a
    # path relative to the caller's directory would name a missing file.
    board, baseline = os.path.abspath(board), os.path.abspath(baseline)
    intent = os.path.abspath(intent) if intent else None
    if intent and not os.path.isfile(intent):
        raise SystemExit(f'refuse: intent {intent} does not exist')
    for p, what in ((board, 'board'), (baseline, 'baseline')):
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            raise SystemExit(f'refuse: {what} {p} is not a real non-empty file')
    label = label or os.path.splitext(os.path.basename(board))[0]
    out_dir = os.path.abspath(out_dir or os.path.dirname(board))
    tmp = os.path.join(out_dir, f'_grade_{label}')
    os.makedirs(tmp, exist_ok=True)
    with open(board, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    out = {'board': board, 'sha256': sha, 'mode': mode, 'baseline': baseline,
           'intent': intent,
           'has_kicad_pro': os.path.isfile(os.path.splitext(board)[0] + '.kicad_pro')}
    iflag = ['--intent', intent] if intent else []

    aj = os.path.join(tmp, 'assembly.json')
    out['check_assembly_rc'], _ = _run(['py_tools/check_assembly.py', board,
                                        *iflag, '--json', aj])
    out['assembly_verdict'] = (_load(aj) or {}).get('verdict')
    out['buildable'] = bool((_load(aj) or {}).get('buildable'))

    if intent:
        fj = os.path.join(tmp, 'floorplan.json')
        out['check_floorplan_rc'], _ = _run(['py_tools/check_floorplan.py', board,
                                             '--intent', intent, '--allow-routed',
                                             '--json', fj])
        f = _load(fj)
        if isinstance(f, dict) and isinstance(f.get('violations'), list):
            v = f['violations']
            out['floorplan_errors'] = sum(1 for x in v
                                          if x.get('severity') == 'error')
            out['floorplan_warnings'] = sum(1 for x in v
                                            if x.get('severity') == 'warn')
            out['floorplan_pass'] = f.get('pass')
        else:
            out['floorplan_errors'] = None      # unreadable -> not DONE

    rj = os.path.join(tmp, 'render.json')
    out['render_rc'], _ = _run(['py_tools/render_placement.py', board,
                                '--json-out', rj, '-o',
                                os.path.join(tmp, 'render.png'), '--quiet'])
    off = ((_load(rj) or {}).get('checklist') or {}).get('a_off_outline') or {}
    out['off_outline_pad_copper'] = off.get('pad_copper')
    out['off_outline_graphic_copper'] = off.get('graphic_copper')
    metrics = (_load(rj) or {}).get('metrics') or {}
    for k in ('hpwl', 'crossings'):          # render_placement's own keys
        if k in metrics:
            out[k] = metrics[k]

    done = out['buildable'] and not out['off_outline_pad_copper'] \
        and not out['off_outline_graphic_copper'] \
        and (not intent or out.get('floorplan_errors') == 0)

    if mode in ('full', 'route'):
        sj = os.path.join(tmp, 'score.json')
        out['board_score_rc'], _ = _run(['py_tools/board_score.py', board,
                                         *iflag, '--baseline', baseline,
                                         '--json', sj, '--quiet'])
        s = _load(sj) or {}
        c = s.get('components') or {}
        out.update(blocking=s.get('blocking'),
                   unrouted=(c.get('unrouted') or {}).get('count'),
                   broken=(c.get('broken') or {}).get('count'),
                   drc=(c.get('drc') or {}).get('count'),
                   **(s.get('quality') or {}))
        for key, extra in (('check_complete', []),
                           ('check_complete_authored', ['--authored-from', baseline])):
            cj = os.path.join(tmp, f'{key}.json')
            out[key + '_rc'], _ = _run(['check_complete.py', board, *iflag,
                                        *extra, '--json', cj])
            out[key] = (_load(cj) or {}).get('verdict')
        rc, log = _run(['py_router/check_connected.py', board])
        out['check_connected_rc'] = rc
        rc, log = _run(['py_router/check_drc.py', board, '--baseline', baseline,
                        '--clearance-margin', '0.1'])
        out['check_drc_rc'] = rc
        done = done and out['blocking'] == 0 and out['check_complete'] == 'DONE'

    if mode == 'route':
        before, after = _poses(baseline), _poses(board)
        moved = sorted(k for k in before if after.get(k) != before[k])
        out['moved_parts'] = moved
        done = done and not moved

    out['done'] = bool(done)
    dst = os.path.join(out_dir, f'grade_{label}.json')
    with open(dst, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    return out, dst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('board')
    ap.add_argument('--baseline', required=True,
                    help='the input board the run started from')
    ap.add_argument('--intent', default=None)
    ap.add_argument('--mode', choices=('full', 'place', 'route'), default='full')
    ap.add_argument('--label', default=None)
    ap.add_argument('--out-dir', default=None,
                    help="default: the board's own directory")
    a = ap.parse_args(argv)
    out, dst = grade(a.board, a.baseline, a.intent, a.mode, a.label, a.out_dir)
    keys = ('done', 'blocking', 'unrouted', 'broken', 'drc', 'vias',
            'copper_mm', 'segments', 'check_complete', 'check_complete_authored',
            'assembly_verdict', 'floorplan_errors', 'moved_parts')
    print(json.dumps({k: out.get(k) for k in keys if k in out}))
    print('wrote', dst)
    return 0 if out['done'] else 4


if __name__ == '__main__':
    sys.exit(main())
