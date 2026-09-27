#!/usr/bin/env python3
"""#1043's reproduction: `place_portfolio` on run 32's `placed_v3` under its
own intent, before and after the quench holds decap tethers.

The fixture is NOT in this repo (run 32's `wk/run32/placed_v3.kicad_pcb` and
`glasgow.intent.json`; the intent is also committed here as
`glasgow_run32.intent.json`). Stage the board with
`py_router/copy_board.py`, never a bare cp.

    # one run, from the root of the tree under test:
    python3 tests/fixtures/1051/repro_1043.py run BOARD INTENT OUT_DIR
    # compare two runs' slates (the pre-#1043 tree's and this one's):
    python3 tests/fixtures/1051/repro_1043.py compare BOARD INTENT BEFORE AFTER

`compare` reads each slate's `portfolio.json` and prints, per candidate, the
NEW intent errors the exit gate counted (by rule) and how many ICs moved
>= 0.5 mm, plus the viable count and the exit code `run` recorded. The
recorded comparison is `repro_1043_result.json` beside this file.
"""
import json
import math
import os
import subprocess
import sys

ROOT = os.getcwd()
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, ROOT)

#: The #1037 / #1043 command's arguments, verbatim.
LOCK = ('C1 C15 C17 C18 C25 C78 C80 C87 C89 D11 D12 D4 D6 FID1 FID2 FID3 FID4 '
        'FID5 FID6 FID8 J1 J10 J2 J3 J4 J5 MK1 MK2 MK3 MK4 R11 R12 R31 R32 SW1 '
        'TP1 U14 U2 U3 U9').split()
IGNORE = ['GND', '+3V3', '+5V', '+1V2', '/IO_Banks/VIOA', '/IO_Banks/VIOB']
MOVED_MM = 0.5


def run(board, intent, out_dir):
    argv = [sys.executable, '-X', 'utf8',
            os.path.join(ROOT, 'py_placer', 'place_portfolio.py'), board,
            '--out-dir', out_dir, '--candidates', '10', '--keep', '5',
            '--intent', intent, '--lock', *LOCK, '--ignore-nets', *IGNORE,
            '--max-displacement', '5', '--clearance', '0.2',
            '--board-edge-clearance', '0.5', '--route-top', '0']
    r = subprocess.run(argv, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'run.log'), 'w', encoding='utf-8') as fh:
        fh.write(r.stdout + r.stderr)
    with open(os.path.join(out_dir, 'exit_code'), 'w') as fh:
        fh.write(str(r.returncode))
    return r.returncode


def _grade(intent, path):
    from kicad_parser import parse_kicad_pcb
    from placement import floorplan
    # place_portfolio's own arguments (score_candidate): --group-by auto,
    # the command's clearance and edge clearance.
    return floorplan.grade(intent, parse_kicad_pcb(path), path,
                           group_sources=('kicad', 'sheet'), clearance=0.2,
                           board_edge_clearance=0.5).violations


def summarize(board, slate, intent_path):
    import io
    from contextlib import redirect_stdout
    from kicad_parser import parse_kicad_pcb
    from placement import floorplan
    from placement.groups import chip_refs
    pcb = parse_kicad_pcb(board)
    ics = chip_refs(pcb)
    intent = floorplan.load_intent(intent_path)
    with redirect_stdout(io.StringIO()):
        base = _grade(intent, board)
    with open(os.path.join(slate, 'portfolio.json'), encoding='utf-8') as fh:
        doc = json.load(fh)
    code = None
    try:
        with open(os.path.join(slate, 'exit_code')) as fh:
            code = int(fh.read().strip())
    except OSError:
        pass
    rows = []
    for c in doc['candidates']:
        rec = c.get('intent') or {}
        final = c.get('final_poses') or {}
        by_rule = {}
        if final:
            # The FULL delta, re-derived: portfolio.json keeps only the first
            # ten `new` entries. Its own total must agree with this one.
            with redirect_stdout(io.StringIO()):
                delta = floorplan.grade_delta(base, _grade(intent, c['board']))
            for n in delta:
                key = n.get('rule') or n.get('budget')
                by_rule[key] = by_rule.get(key, 0) + int(n.get('added', 1))
            assert sum(by_rule.values()) == rec.get('new_errors'), (
                c['index'], by_rule, rec.get('new_errors'))
        moved = sorted(
            r for r in ics if r in final and math.hypot(
                final[r][0] - pcb.footprints[r].x,
                final[r][1] - pcb.footprints[r].y) >= MOVED_MM)
        rows.append({'index': c['index'], 'strategy': c['strategy'],
                     'passed': bool((c.get('gates') or {}).get('passed')),
                     'barren': not final,
                     'new_errors': sum(by_rule.values()),
                     'new_by_rule': dict(sorted(by_rule.items())),
                     'ics_moved_ge_0_5mm': len(moved)})
    return {'exit_code': code, 'viable': sum(r['passed'] for r in rows),
            'kept': len(doc.get('kept') or ()),
            'input_intent_errors': doc.get('input_intent_errors'),
            'candidates': rows}


def main(argv):
    if argv[:1] == ['run'] and len(argv) == 4:
        return run(*argv[1:])
    if argv[:1] == ['compare'] and len(argv) == 5:
        board, intent, before, after = argv[1:]
        out = {'before': summarize(board, before, intent),
               'after': summarize(board, after, intent)}
        json.dump(out, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write('\n')
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
