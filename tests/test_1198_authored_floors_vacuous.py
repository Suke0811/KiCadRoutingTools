#!/usr/bin/env python3
"""#1198: check_complete --authored-from can say DONE on a board that honours
its declared floors, including vacuously.

Two inputs always landed in `unmeasured`, and any `unmeasured` entry made
the verdict INCOMPLETE:
  * `min_hole_clearance` is declaration-only (scan_board_minima measures no
    pairwise geometry), so every board whose authored project carried it --
    13 of the 14 tracked projects -- read INCOMPLETE, a declared 0.0 included,
    and a board compared with ITSELF too;
  * via floors on a board with no vias, since scan_board_minima emits via
    keys only when vias exist.

Checks (fab_floor_integrity, on staged copies of tracked boards):
  1. routed_output compared with itself: nothing unmeasured; copper-to-hole
     is `declared_kept`.
  2. A 0-via board (sonde_u) whose authored project declares via floors and
     a copper-to-hole 0.0: every one is `vacuous`, none unmeasured.
  3. A project that LOWERED copper-to-hole (0.25 authored, 0.1 now) is still
     unmeasured -- unknown, not honoured -- and names both values.
  4. A measured floor the copper breaks is still `relaxed` (UNSOUND).
  5. check_complete's verdict on (1) carries no fab-floor reason.

    python3 tests/test_1198_authored_floors_vacuous.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from check_complete import fab_floor_integrity                 # noqa: E402
from copy_board import copy_board                              # noqa: E402

ROUTED = os.path.join(ROOT, 'kicad_files', 'routed_output.kicad_pcb')
NOVIA = os.path.join(ROOT, 'kicad_files', 'sonde_u.kicad_pcb')
failures = []


def check(label, ok, detail=''):
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def stage(src, tmp, name, rules=None):
    dst = os.path.join(tmp, name)
    with contextlib.redirect_stdout(io.StringIO()):
        copy_board(src, dst)
    if rules is not None:
        pro = dst[:-len('.kicad_pcb')] + '.kicad_pro'
        doc = {}
        if os.path.isfile(pro):
            with open(pro) as f:
                doc = json.load(f)
        doc.setdefault('board', {}).setdefault('design_settings', {})['rules'] = rules
        with open(pro, 'w') as f:
            json.dump(doc, f)
    return dst


def keys(rows):
    return sorted(r['key'] for r in rows or ())


def main():
    tmp = tempfile.mkdtemp(prefix='t1198_')
    try:
        # 1. A board compared with itself.
        r = fab_floor_integrity(ROUTED, ROUTED)
        check('self-comparison: nothing unmeasured, nothing relaxed',
              r['ran'] and not r['unmeasured'] and not r['relaxed'], json.dumps(r)[:300])
        check('self-comparison: copper-to-hole is declared_kept',
              keys(r['declared_kept']) == ['min_hole_clearance'])

        # 2. A 0-via board under declared via floors and a 0.0 copper-to-hole.
        authored = {'min_via_diameter': 0.4, 'min_via_annular_width': 0.05,
                    'min_via_drill': 0.2, 'min_hole_clearance': 0.0}
        a = stage(NOVIA, tmp, 'authored.kicad_pcb', authored)
        b = stage(NOVIA, tmp, 'final.kicad_pcb', dict(authored))
        r = fab_floor_integrity(b, a)
        check('0-via board: via floors and a declared 0 are vacuous',
              keys(r['vacuous']) == sorted(authored) and not r['unmeasured']
              and not r['relaxed'], json.dumps(r)[:400])
        why = {x['key']: x['why'] for x in r['vacuous']}
        check('...each saying why',
              why.get('min_via_diameter') == 'no via on the board'
              and 'declared 0' in why.get('min_hole_clearance', ''), str(why))

        # 3. Copper-to-hole lowered in the project: unknown, and named.
        a3 = stage(NOVIA, tmp, 'a3.kicad_pcb', {'min_hole_clearance': 0.25})
        b3 = stage(NOVIA, tmp, 'b3.kicad_pcb', {'min_hole_clearance': 0.1})
        r = fab_floor_integrity(b3, a3)
        um = r['unmeasured'][0] if r['unmeasured'] else {}
        check('a lowered copper-to-hole stays unmeasured, both values named',
              um.get('key') == 'min_hole_clearance' and um.get('authored') == 0.25
              and um.get('declared') == 0.1, json.dumps(r)[:300])

        # 4. Copper below a measured floor is still relaxed.
        a4 = stage(ROUTED, tmp, 'a4.kicad_pcb', {'min_track_width': 5.0})
        r = fab_floor_integrity(ROUTED, a4)
        check('copper below an authored track floor is relaxed',
              keys(r['relaxed']) == ['min_track_width'], json.dumps(r['relaxed']))

        # 5. The verdict on the self-comparison.
        js = os.path.join(tmp, 'cc.json')
        subprocess.run([sys.executable, '-X', 'utf8', 'check_complete.py', ROUTED,
                        '--authored-from', ROUTED, '--json', js], cwd=ROOT,
                       capture_output=True, text=True)
        doc = json.load(open(js)) if os.path.isfile(js) else {}
        why = doc.get('reason') or ''
        check('check_complete names no fab-floor reason on the self-comparison',
              bool(why) and 'fab floor' not in why, why[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('FAILED: ' + ', '.join(failures) if failures else 'PASS')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
