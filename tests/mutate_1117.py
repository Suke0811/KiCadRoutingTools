"""The #1117 mutation battery: the post-polish re-seat holds a declared ladder.

One row per load-bearing line, each reverting it; every row names the test
case that must fail. **THE ROWS TO LOOK AT FIRST if this file ever goes red**
restore the defect #1117 measured, or the reason it went unseen:

  * `reseat-passes-no-ladder` -- `place_seed`'s re-seat searched the fallback
    lattice and wrote a part declared `rotation: 0` at 90, exit 0;
  * `gate-blind-to-attribute-calls` / `gate-reads-seeder-only` -- test_893's
    standing gate read only seeder.py and only bare-name calls, which is why
    the one site that omitted the ladder (`seeder._try_place` in place_seed)
    was never reported.

NOT named `test_*.py`, so `tests/run_all.py` does not collect it: it REWRITES
the sources in place. One writer per tree. It refuses to start on a dirty
target, and it runs every witness UNMUTATED first -- a witness that already
fails would score every row as killed.

    python3 tests/mutate_1117.py
    python3 tests/mutate_1117.py --row reseat-passes-no-ladder

A row is KILLED by a failure or an error. An anchor that does not match
EXACTLY ONCE is BROKEN, never skipped; `preflight()` runs right after `ROWS`.
Edits are `str.replace(old, new, 1)`; anchors are LF and translated to the
target's own ending. A witness is `(test file, case-name substring...)`: the
test files run only the cases whose names contain one of the substrings.

Not covered by a row, and why:
  * `declared_ladder`'s `if claim is None: return None` -- a two-line anchor,
    and its mutant (an IndexError on unpacking None) dies in every witness
    that seeds anything, so a row would add cost and no information;
  * the `zone` / `rules` fields of a `reseat_declined` record: asserted by
    `not_traded`, but each is one dict entry whose mutant is the same
    assertion failing, already exercised by `declined-reseat-unrecorded`.
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
    'ps': os.path.join(_ROOT, 'py_placer', 'place_seed.py'),
    'fp': os.path.join(_PL, 'floorplan.py'),
    'sd': os.path.join(_PL, 'seeder.py'),
    't893': os.path.join(_TESTS, 'test_893_declared_rotation.py'),
}


def _t(name, *cases):
    return (os.path.join(_TESTS, name),) + cases


T = 'test_1117_reseat_declared_rotation.py'
NOT_TRADED = _t(T, 'not_traded')
CANDIDATES = _t(T, 'candidate_set')
TURNED_BACK = _t(T, 'turned_back')
UNDECLARED = _t(T, 'undeclared_decline')
REPAIR = _t(T, 'repair_placement')
LADDER = _t(T, 'one_ladder')
GATE = _t('test_893_declared_rotation.py', 'try_place_site')
GATE_CTL = _t('test_893_declared_rotation.py', 'ladder_gate')
SEEDED = _t('test_893_declared_rotation.py', 'is_the_angle_that_is_placed',
            'candidates_restrict')

# (name, target, old, new, tests, expect)
ROWS = [
    # -- place_seed: the re-seat itself --------------------------------------
    ('reseat-passes-no-ladder', 'ps',
     "                        rotations=_ladder)",
     "                        )",
     (NOT_TRADED,), 'KILLED'),
    ('reseat-ladder-dropped-gate-sees-it', 'ps',
     "                        rotations=_ladder)",
     "                        )",
     (GATE,), 'KILLED'),
    ('reseat-passes-literal-None', 'ps',
     "                        rotations=_ladder)",
     "                        rotations=None)",
     (GATE,), 'KILLED'),
    ('reseat-ladder-ignores-the-declaration', 'ps',
     "                    _ladder = floorplan.declared_ladder(_claim)",
     "                    _ladder = None",
     (NOT_TRADED, TURNED_BACK), 'KILLED'),
    ('reseat-reads-no-declarations', 'ps',
     "                _declared = floorplan.rotations_for_ref(intent, blocks2)",
     "                _declared = {}",
     (NOT_TRADED,), 'KILLED'),
    ('declined-reseat-unrecorded', 'ps',
     "                        reseat_declined[ref] = {",
     "                        _dropped = {",
     (NOT_TRADED, UNDECLARED), 'KILLED'),
    ('decline-line-drops-the-claim', 'ps',
     '        how = (f"at its declared rotation {rot:g} -- the angle is the claim, "',
     '        how = (f"at any rotation -- the angle is the claim, "',
     (LADDER,), 'KILLED'),
    ('undeclared-decline-silent', 'ps',
     "                for ref in sorted(reseat_declined):",
     "                for ref in sorted(r for r in reseat_declined"
     " if reseat_declined[r]['rotation'] is not None"
     " or reseat_declined[r]['rotation_candidates']):",
     (UNDECLARED,), 'KILLED'),
    ('json-key-dropped', 'ps',
     "               'reseat_declined': reseat_declined,",
     "               'reseat_declined': {},",
     (NOT_TRADED,), 'KILLED'),
    # -- floorplan: the one ladder ------------------------------------------
    ('helper-drops-candidates', 'fp',
     "    return [rot] if rot is not None else list(cands)",
     "    return [rot] if rot is not None else list(cands)[:1]",
     (CANDIDATES,), 'KILLED'),
    ('helper-sorts-candidates', 'fp',
     "    return [rot] if rot is not None else list(cands)",
     "    return [rot] if rot is not None else sorted(cands)",
     (CANDIDATES,), 'KILLED'),
    # -- seeder: both closures delegate --------------------------------------
    ('seed-closure-disconnected', 'sd',
     "        return floorplan.declared_ladder(declared_rot.get(ref))",
     "        return None",
     (SEEDED,), 'KILLED'),
    ('repair-closure-disconnected', 'sd',
     "        return floorplan.declared_ladder(_declared_rot.get(ref))",
     "        return None",
     (REPAIR,), 'KILLED'),
    # -- test_893: the standing gate that missed it --------------------------
    ('gate-blind-to-attribute-calls', 't893',
     "                else fn.attr if isinstance(fn, ast.Attribute) else None)",
     "                else None)",
     (GATE, GATE_CTL), 'KILLED'),
    ('gate-accepts-rotations-None', 't893',
     "    if isinstance(v, ast.Constant) and v.value is None:",
     "    if False:",
     (GATE_CTL,), 'KILLED'),
    ('gate-reads-seeder-only', 't893',
     "_LADDER_TREES = ('py_placer', 'py_router', 'py_tools', 'kicad_routing_plugin')",
     "_LADDER_TREES = ('py_placer/placement',)",
     (GATE,), 'KILLED'),
]

sys.path.insert(0, _TESTS)
from mutation_anchors import preflight   # noqa: E402
preflight(__file__)


def _dirty(path):
    p = subprocess.run(['git', 'status', '--porcelain', '--', path],
                       capture_output=True, text=True, cwd=_ROOT)
    return bool(p.stdout.strip())


def _run_tests(tests):
    failed = []
    for t in tests:
        p = subprocess.run([sys.executable, '-X', 'utf8', t[0]] + list(t[1:]),
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=2400, cwd=_ROOT)
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
    # THE UNMUTATED BASELINE: every witness must pass as the code stands,
    # or a row it "kills" proves nothing.
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
