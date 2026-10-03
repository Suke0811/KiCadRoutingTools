"""The #1120 / #1121 / #1122 mutation battery: a placement path turns a part
only into the rotation its intent declares.

One row per load-bearing line, each reverting it; every row names the test
case that must fail. **THE ROWS TO LOOK AT FIRST if this file ever goes red**
restore the defect each issue measured, or the reason it went unseen:

  * `poses-ignores-the-declaration` / `generator-reads-no-intent` (#1121) --
    the portfolio's `poses` strategy turned splitflap's U1 270 -> 90 with U1
    declared 270, because nothing handed it the claims the quench is gated
    with;
  * `gate-blind-to-other-callees` -- test_893's standing gate read only
    `_try_place` calls, which is why `perturb_poses` was never asked for its
    declaration.

NOT named `test_*.py`, so `tests/run_all.py` does not collect it: it REWRITES
the sources in place. One writer per tree. It refuses to start on a dirty
target, and it runs every witness UNMUTATED first -- a witness that already
fails would score every row as killed.

    python3 tests/mutate_1120_1121_1122.py
    python3 tests/mutate_1120_1121_1122.py --row poses-sorts-a-set

A row is KILLED by a failure or an error. An anchor that does not match
EXACTLY ONCE is BROKEN, never skipped; `preflight()` runs right after `ROWS`.
Edits are `str.replace(old, new, 1)`; anchors are LF and translated to the
target's own ending. A witness is `(test file, case-name substring...)`: the
test files run only the cases whose names contain one of the substrings.

Not covered by a row, and why:
  * `generate()`'s `poses: N free part(s) declare a rotation` line -- a
    disclosure; `place_portfolio_does_not_turn` asserts it, and its mutant
    is that assertion failing;
  * dropping a row from test_893's `_DECLARATION_CALLS` -- that deletes the
    guard rather than weakening it, and no assertion can see its own table
    shrink without restating the table.
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
    'pf': os.path.join(_PL, 'portfolio.py'),
    't893': os.path.join(_TESTS, 'test_893_declared_rotation.py'),
}


def _t(name, *cases):
    return (os.path.join(_TESTS, name),) + cases


T1121 = 'test_1121_portfolio_declared_rotation.py'
DECLARED = _t(T1121, 'declared_angle_is_not')
SLOT = _t(T1121, 'declared_slot_goes')
OFF_ANGLE = _t(T1121, 'off_its_declared_angle')
CAND_SET = _t(T1121, 'candidate_set_bounds')
AUTHOR = _t(T1121, 'author_order')
OFF_LATTICE = _t(T1121, 'off_lattice_member')
E2E = _t(T1121, 'place_portfolio_does_not')
GATE = _t('test_893_declared_rotation.py', 'declaration_taking_call')
GATE_CTL = _t('test_893_declared_rotation.py', 'ladder_gate')

# (name, target, old, new, tests, expect)
ROWS = [
    # -- #1121: the portfolio's poses strategy -------------------------------
    ('poses-ignores-the-declaration', 'pf',
     "    if claim is None:",
     "    if True:",
     (DECLARED, CAND_SET), 'KILLED'),
    ('poses-offers-the-current-angle', 'pf',
     "            if not _same_angle(a, part.rot)]",
     "            ]",
     (DECLARED, AUTHOR), 'KILLED'),
    ('poses-ranks-before-it-filters', 'pf',
     "                   and _pose_variants(state.parts[r], declared.get(r))),",
     "                   ),",
     (SLOT,), 'KILLED'),
    ('poses-sorts-a-set', 'pf',
     "    return [a % 360 for a in declared_ladder(claim)",
     "    return [a % 360 for a in sorted(declared_ladder(claim))",
     (AUTHOR,), 'KILLED'),
    ('poses-judges-an-unmaterialised-box', 'pf',
     "                rot = _materialise_rotation(part, rot)",
     "                rot = rot % 360",
     (OFF_LATTICE,), 'KILLED'),
    ('generator-drops-the-declaration', 'pf',
     "                                  declared=_declared)",
     "                                  declared=None)",
     (E2E, GATE), 'KILLED'),
    ('generator-kwarg-dropped-gate-sees-it', 'pf',
     "                                  declared=_declared)",
     "                                  )",
     (GATE,), 'KILLED'),
    ('generator-reads-no-intent', 'pf',
     "    _declared = dict((qkw.get('intent_gate') or {}).get('rotations') or {})",
     "    _declared = {}",
     (E2E,), 'KILLED'),
    ('gate-blind-to-other-callees', 't893',
     "        if name == callee:",
     "        if name == '_try_place':",
     (GATE,), 'KILLED'),
    ('gate-accepts-a-literal-None', 't893',
     "        return '%s=None' % kw",
     "        return None",
     (GATE_CTL,), 'KILLED'),
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
