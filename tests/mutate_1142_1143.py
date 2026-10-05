"""The #1142 / #1143 mutation battery: per-cap decap_ungraded, and
aperture-only pads that are not pads.

One row per load-bearing line, each reverting it; every row names the test
case that must fail. **THE ROWS TO LOOK AT FIRST if this file ever goes red**
restore a defect somebody measured:

  * `aperture-predicate-drops-npth` -- treating an NPTH hole as an aperture
    moves splitflap H6/H7 and test_837's census (the reason the predicate is
    not `_pad_carries_copper`);
  * `chip-list-reads-paste` -- tigard C25 measured 2.43 mm to J1's paste
    windows, not 2.93 mm to its copper (#1143);
  * `per-cap-severity-ignored` -- a decoupler the reference keeps within the
    radius and a seed strands beyond it reads as a WARN (#1142: splitflap 7,
    tigard 7, watchy 4 on the issue's piles).

NOT named `test_*.py`, so `tests/run_all.py` does not collect it: it REWRITES
the sources in place. One writer per tree. It refuses to start on a dirty
target, and it runs every witness UNMUTATED first -- a witness that already
fails would score every row as killed.

    python3 tests/mutate_1142_1143.py
    python3 tests/mutate_1142_1143.py --row per-cap-severity-ignored

A row is KILLED by a failure or an error. An anchor that does not match
EXACTLY ONCE is BROKEN, never skipped; `preflight()` runs right after `ROWS`.
Edits are `str.replace(old, new, 1)`; anchors are LF and translated to the
target's own ending. A witness is `(test file, case-name substring...)`.

Not covered by a row, and why:
  * the "has pads" gates of portfolio, reconcile, recovery, lock_advisor,
    placement_state, grow_board, plan_check and the board tools: no corpus
    board carries an aperture-only part (measure_1143), and each gate is the
    same one-line `non_aperture_pads(fp)` the rows below already pin through
    the predicate itself;
  * the escape face assignment and `_part_rect`: `pitch-reads-paste-lattice`
    and the empty-part case in test_1143's pitch witness cover the module.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS)
_PL = os.path.join(_ROOT, 'py_placer', 'placement')

TARGETS = {
    'kp': os.path.join(_ROOT, 'py_router', 'kicad_parser.py'),
    'util': os.path.join(_PL, 'utility.py'),
    'body': os.path.join(_PL, 'body.py'),
    'escape': os.path.join(_PL, 'escape.py'),
    'legality': os.path.join(_PL, 'legality.py'),
    'groups': os.path.join(_PL, 'groups.py'),
    'part_class': os.path.join(_PL, 'part_class.py'),
    'quench': os.path.join(_PL, 'quench.py'),
    'pose_ops': os.path.join(_PL, 'pose_ops.py'),
    'pscore': os.path.join(_ROOT, 'py_placer', 'placement_score.py'),
    'floorplan': os.path.join(_PL, 'floorplan.py'),
}


def _t(name, *cases):
    return (os.path.join(_TESTS, name),) + cases


T1143 = 'test_1143_paste_only_siblings.py'
PRED = _t(T1143, 'predicate_keeps')
BBOX = _t(T1143, 'bbox_local')
RUNG = _t(T1143, 'occupancy_rect')
CENSUS = _t(T1143, 'assembly_census')
BAL = _t(T1143, 'pad_area_balance')
BASIS = _t(T1143, 'balance_refuses')
PITCH = _t(T1143, 'pad_pitch')
GEO = _t(T1143, 'copper_geometry')
CLASS = _t(T1143, 'part_class')
CHIP = _t(T1143, 'chip_bounds')
QUENCH = _t(T1143, 'quench_takes')
TIGARD = _t(T1143, 'tigard_c25')
T1142 = 'test_1142_ungraded_per_cap.py'
EMIT = _t(T1142, 'emits_the_held_list')
STRAND = _t(T1142, 'held_cap_stranded')
EXPL = _t(T1142, 'explicit_severity')
GATING = _t(T1142, 'gating_follows')
LOADER = _t(T1142, 'loader_refuses')
FPMATCH = _t(T1142, 'footprint_mismatch')
CLI = _t(T1142, 'cli_fixed_point')

# (name, target, old, new, tests, expect)
ROWS = [
    # ----------------------------------------------------------- #1143
    ('aperture-predicate-drops-npth', 'kp',
     "    if getattr(pad, 'pad_type', '') == 'np_thru_hole':\n"
     "        return False\n"
     "    if (getattr(pad, 'drill', 0.0) or 0.0) > 0:\n",
     "    if getattr(pad, 'pad_type', '') == 'np_thru_hole':\n"
     "        return True\n"
     "    if (getattr(pad, 'drill', 0.0) or 0.0) > 0:\n",
     (PRED, BBOX, CENSUS), 'KILLED'),
    ('aperture-predicate-drops-drilled', 'kp',
     "    if (getattr(pad, 'drill', 0.0) or 0.0) > 0:\n"
     "        return False\n"
     "    return not pad_has_copper(pad)\n",
     "    return not pad_has_copper(pad)\n",
     (PRED,), 'KILLED'),
    ('bbox-reads-paste', 'util',
     "    pads = non_aperture_pads(footprint)\n",
     "    pads = list(footprint.pads or ())\n",
     (BBOX,), 'KILLED'),
    ('aperture-only-part-gets-pad-rung', 'body',
     "    if non_aperture_pads(fp):\n",
     "    if getattr(fp, 'pads', None):\n",
     (RUNG,), 'KILLED'),
    ('census-counts-paste-only-parts', 'legality',
     "        pads = non_aperture_pads(fp)\n        if not pads:\n"
     "            zero_pad[side].append(ref)\n",
     "        pads = list(fp.pads or ())\n        if not pads:\n"
     "            zero_pad[side].append(ref)\n",
     (CENSUS,), 'KILLED'),
    ('balance-weighs-paste', 'pscore',
     "            if pad_is_aperture_only(pad):\n"
     "                aperture += 1\n                continue\n",
     "",
     (BAL,), 'KILLED'),
    ('balance-basis-dropped', 'pscore',
     "                 basis=[BALANCE_BASIS],\n",
     "",
     (BASIS, BAL), 'KILLED'),
    ('pitch-reads-paste-lattice', 'escape',
     "    pads = _pads(fp)\n    if len(pads) < 2:\n",
     "    pads = list(fp.pads or ())\n    if len(pads) < 2:\n",
     (PITCH,), 'KILLED'),
    ('copper-geometry-fallback-reads-paste', 'legality',
     "        _pads = non_aperture_pads(fp)\n",
     "        _pads = list(fp.pads or ())\n",
     (GEO,), 'KILLED'),
    ('class-counts-paste-as-plated', 'part_class',
     "    from kicad_parser import non_aperture_pads\n"
     "    pads = non_aperture_pads(fp)\n\n    # Structural",
     "    pads = getattr(fp, 'pads', None) or []\n\n    # Structural",
     (CLASS,), 'KILLED'),
    ('chip-bounds-read-paste', 'groups',
     "        '_': SimpleNamespace(pads=_pads(fp))}), min_pads=1)",
     "        '_': fp}), min_pads=1)",
     (CHIP,), 'KILLED'),
    ('centroid-reads-paste', 'groups',
     "    pts = [(p.global_x, p.global_y) for p in _pads(fp)]",
     "    pts = [(p.global_x, p.global_y) for p in fp.pads]",
     (CHIP,), 'KILLED'),
    ('chip-list-reads-paste', 'groups',
     "    return [c for c in build_chip_list(_pads_view(pcb_data),\n",
     "    return [c for c in build_chip_list(pcb_data,\n",
     (TIGARD,), 'KILLED'),
    ('quench-aperture-part-movable', 'quench',
     "            if not non_aperture_pads(fp):\n"
     "                # Zero-pad footprints",
     "            if not fp.pads:\n"
     "                # Zero-pad footprints",
     (QUENCH,), 'KILLED'),
    ('part-centre-reads-paste', 'pose_ops',
     "    pads = non_aperture_pads(fp)        # apertures are not copper",
     "    pads = list(fp.pads or ())        # apertures are not copper",
     (GEO,), 'KILLED'),

    # ----------------------------------------------------------- #1142
    ('per-cap-severity-ignored', 'floorplan',
     "        cap_sev = ERROR if (is_held and not explicit) else sev\n",
     "        cap_sev = sev\n",
     (STRAND,), 'KILLED'),
    ('held-includes-reference-beyond', 'floorplan',
     "            _near_ref = groups_mod.decap_populations(_ref_pcb, "
     "radius=_r)[0]\n",
     "            _pp = groups_mod.decap_populations(_ref_pcb, radius=_r)\n"
     "            _near_ref = dict(_pp[0], _beyond=[(c, d) for c, _i, d "
     "in _pp[1]])\n",
     (EMIT,), 'KILLED'),
    ('held-ignores-footprint-match', 'floorplan',
     "                if c in _ours_fp\n"
     "                and _ours_fp[c] == _ref_pcb.footprints[c]"
     ".footprint_name)\n",
     "                if c in _ours_fp)\n",
     (FPMATCH,), 'KILLED'),
    ('held-list-not-emitted', 'floorplan',
     "            if _held:\n"
     "                _decaps['within_radius_refs'] = _held\n",
     "            if False:\n"
     "                _decaps['within_radius_refs'] = _held\n",
     (EMIT, CLI), 'KILLED'),
    ('explicit-severity-loses-to-list', 'floorplan',
     "    explicit = 'decap_ungraded' in (ctx.intent.severity or {})\n",
     "    explicit = False\n",
     (EXPL,), 'KILLED'),
    ('list-without-limit-loads', 'floorplan',
     "        if 'max_distance_mm' not in decaps:\n"
     "            raise IntentError(\n"
     "                \"decaps.within_radius_refs without",
     "        if False:\n"
     "            raise IntentError(\n"
     "                \"decaps.within_radius_refs without",
     (LOADER,), 'KILLED'),
    ('radius-mismatch-loads', 'floorplan',
     "        if abs(float(search) - float(r)) > 1e-9:\n",
     "        if False:\n",
     (LOADER,), 'KILLED'),
    ('min-reader-not-stamped', 'floorplan',
     "        doc['min_reader'] = max(int(doc.get('min_reader') or 0), 8)\n",
     "        pass\n",
     (EMIT, LOADER), 'KILLED'),
    ('gating-ignores-the-list', 'floorplan',
     "    if (rule == 'decap_ungraded' and rule not in intent.severity\n"
     "            and (intent.decaps or {}).get('within_radius_refs')):\n",
     "    if False:\n",
     (GATING,), 'KILLED'),
    ('gating-ignores-explicit-warn', 'floorplan',
     "    if (rule == 'decap_ungraded' and rule not in intent.severity\n",
     "    if (rule == 'decap_ungraded'\n",
     (EXPL,), 'KILLED'),
]

sys.path.insert(0, _TESTS)
from mutation_anchors import preflight   # noqa: E402
preflight(__file__)


def _dirty(path):
    p = subprocess.run(['git', 'status', '--porcelain', '--', path],
                       capture_output=True, text=True, cwd=_ROOT)
    return bool(p.stdout.strip())


def _purge_pycache():
    """Drop every compiled module under the engine trees before a row is
    applied: two same-size edits within one second leave (mtime, size)
    unchanged and a witness would import the previous row's bytecode."""
    import shutil
    for base in ('py_placer', 'py_router', 'py_tools'):
        for dirpath, dirnames, _files in os.walk(os.path.join(_ROOT, base)):
            if os.path.basename(dirpath) == '__pycache__':
                shutil.rmtree(dirpath, ignore_errors=True)
                dirnames[:] = []


def _run_tests(tests):
    failed = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    for t in tests:
        p = subprocess.run([sys.executable, '-B', '-X', 'utf8', t[0]]
                           + list(t[1:]),
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=2400, cwd=_ROOT, env=env)
        if p.returncode != 0:
            failed.append((os.path.basename(t[0]) + ':' + ','.join(t[1:]),
                           p.returncode,
                           [ln.strip()[:90] for ln in
                            ((p.stdout or '') + (p.stderr or '')).splitlines()
                            if 'FAIL' in ln or 'Error' in ln][:2]))
    return failed


def run(only=None):
    rows = [r for r in ROWS if only is None or r[0] == only]
    if not rows:
        print('no row named %r' % only)
        return 1
    for path in TARGETS.values():
        if _dirty(path):
            print('REFUSING: %s has uncommitted changes. Commit or stash '
                  'first -- this battery restores by overwriting.'
                  % os.path.basename(path))
            return 2
    witnesses = sorted({t for r in rows for t in r[4]})
    base_fail = _run_tests(witnesses)
    if base_fail:
        print('REFUSING: witnesses fail UNMUTATED -- %s' % base_fail)
        return 2
    print('baseline: %d witnesses pass unmutated' % len(witnesses))
    orig = {k: io.open(v, encoding='utf-8', newline='').read()
            for k, v in TARGETS.items()}
    results = []
    try:
        for name, tgt, old, new, tests, expect in rows:
            path = TARGETS[tgt]
            base = orig[tgt]
            o, n = old, new
            if '\r\n' in base:
                o, n = o.replace('\n', '\r\n'), n.replace('\n', '\r\n')
            if base.count(o) != 1 or o == n:
                results.append((name, 'BROKEN', expect,
                                ['anchor matched %d times' % base.count(o)]))
                continue
            _purge_pycache()
            io.open(path, 'w', encoding='utf-8', newline='').write(
                base.replace(o, n, 1))
            try:
                failed = _run_tests(tests)
            finally:
                io.open(path, 'w', encoding='utf-8', newline='').write(base)
            results.append((name, 'KILLED' if failed else 'SURVIVED',
                            expect, [str(f)[:150] for f in failed[:2]]))
            print('%-40s %s' % (name, results[-1][1]), flush=True)
    finally:
        for k, v in TARGETS.items():
            io.open(v, 'w', encoding='utf-8', newline='').write(orig[k])
        _purge_pycache()
    wrong = [r for r in results if r[1] != r[2]]
    print('')
    for name, verdict, expect, why in results:
        print('%-40s %-9s%s' % (name, verdict, '' if verdict == expect else
                                '   <-- WRONG, expected %s' % expect))
        for w in why:
            print('      %s' % w)
    print('\n%d rows: %d killed, %d survived, %d broken'
          % (len(results), sum(r[1] == 'KILLED' for r in results),
             sum(r[1] == 'SURVIVED' for r in results),
             sum(r[1] == 'BROKEN' for r in results)))
    return 1 if wrong else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--row', default=None, help='run only this row')
    a = ap.parse_args()
    return run(a.row)


if __name__ == '__main__':
    sys.exit(main())
