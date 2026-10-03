"""The #1064 mutation battery: place_pose grades a pad stack, any net.

One row per load-bearing line, each reverting it; every row names the test
case that must fail. **THE ROWS TO LOOK AT FIRST if this file ever goes red**
restore the defect #1064 measured, or the reason it went unseen:

  * `pose-grade-skips-stacks` -- place_pose graded with `grade_pad_legality`
    alone, whose pair loop skips a same-net pad pair before measuring, so
    esp_prog's C4 on Y1 (one net, 0.0412 mm2) exited 0 `legal: true` while
    check_assembly graded the board NOT BUILDABLE;
  * `pair-arm-off` -- #1100's lesson for stacks: C15 leaving one stack for
    an identical one ties the count AND the area, and only the pair set
    sees the new stack (run 38 put C15 on C19 after #1100 had landed);
  * `same-net-blind-again` -- the measurement is check_assembly's own
    channel, which measures any net; skipping same-net pads there is the
    original bug moved into the shared function.

NOT named `test_*.py`, so `tests/run_all.py` does not collect it: it REWRITES
the sources in place. One writer per tree. It refuses to start on a dirty
target, and it runs every witness UNMUTATED first -- a witness that already
fails would score every row as killed.

    python3 tests/mutate_1064.py
    python3 tests/mutate_1064.py --row pair-arm-off

A row is KILLED by a failure or an error. An anchor that does not match
EXACTLY ONCE is BROKEN, never skipped; `preflight()` runs right after `ROWS`.
Edits are `str.replace(old, new, 1)`; anchors are LF and translated to the
target's own ending. A witness is `(test file, case-name substring...)`: the
test files run only the cases whose names contain one of the substrings.

Not covered by a row, and why:
  * `place_pose._report`'s `pad stacks:` line -- cosmetic, and every arm that
    could see it also reads the refusal text, which names the pair;
  * the eps of the exact confirmation -- `over >= eps` reads "edge distance
    <= 0" whatever eps is, and the bounding-box prefilter already requires
    the pad rectangles to overlap, so a changed eps changes no verdict;
  * `to_json`'s `pad_stacks` block -- asserted by `floorplan_prints`, whose
    other assertions die first under every mutant that reaches it.
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
    'leg': os.path.join(_PL, 'legality.py'),
    'pose': os.path.join(_PL, 'pose_ops.py'),
    'fp': os.path.join(_PL, 'floorplan.py'),
    'cfp': os.path.join(_ROOT, 'py_tools', 'check_floorplan.py'),
}


def _t(name, *cases):
    return (os.path.join(_TESTS, name),) + cases


T = 'test_1064_place_pose_same_net_stack.py'
REPRO = _t(T, 'issue_repro')
FORCE = _t(T, 'force_writes')
RUN38 = _t(T, 'run38_shape')
NEAR_TOUCH = _t(T, 'near_touch_is_not')
DEEPEN = _t(T, 'deepening_stack')
SUMMED = _t(T, 'summed_not_maxed')
NEW_PAIR = _t(T, 'totals_tie')
ARMS = _t(T, 'three_arms')
CENSUS = _t(T, 'census_is_check')
SCOPE = _t(T, 'scope_names_it')
FLOORPLAN = _t(T, 'floorplan_prints')
FLOORPLAN_EXACT = _t(T, 'floorplan_is_exact')
LOCKED = _t('test_run8_locked_contact.py')

# (name, target, old, new, tests, expect)
ROWS = [
    # -- legality: the lifted channel and its census -------------------------
    ('same-net-blind-again', 'leg',
     "                    ov = rect_overlap_area((a0, a1, a2, a3),",
     "                    if na == nb and na > 0:\n"
     "                        continue\n"
     "                    ov = rect_overlap_area((a0, a1, a2, a3),",
     (REPRO, RUN38), 'KILLED'),
    ('exact-confirm-dropped', 'leg',
     "                            if not (hit and over >= eps - 1e-9):",
     "                            if False:",
     (NEAR_TOUCH, FLOORPLAN_EXACT), 'KILLED'),
    ('body-overlap-drops-a-stack', 'leg',
     "    pairs.extend(pad_intersection_pairs(pcb_data, clearance, locked_refs))",
     "    pairs.extend(pad_intersection_pairs(pcb_data, clearance, locked_refs)[1:])",
     (CENSUS,), 'KILLED'),
    ('body-overlap-loses-locks', 'leg',
     "    pairs.extend(pad_intersection_pairs(pcb_data, clearance, locked_refs))",
     "    pairs.extend(pad_intersection_pairs(pcb_data, clearance, ()))",
     (CENSUS, LOCKED), 'KILLED'),
    ('census-area-is-max', 'leg',
     "            'pad_stack_area': round(sum(r[2] for r in rows), 4),",
     "            'pad_stack_area': round(max([r[2] for r in rows] or [0.0]), 4),",
     (SUMMED,), 'KILLED'),
    # -- pose_ops: the three arms and the grade that feeds them --------------
    ('pose-grade-skips-stacks', 'pose',
     "    g.update(pad_stack_census(pcb_data, clearance))",
     "    pass",
     (REPRO, RUN38), 'KILLED'),
    ('count-arm-off', 'pose',
     "                 'pad_stack_count')",
     "                 )",
     (ARMS,), 'KILLED'),
    ('area-arm-off', 'pose',
     "                  'pad_stack_area')",
     "                  )",
     (DEEPEN, ARMS), 'KILLED'),
    ('pair-arm-off', 'pose',
     "             'pad_stack_pairs')",
     "             )",
     (NEW_PAIR,), 'KILLED'),
    ('legality-row-drops-the-pairs', 'pose',
     "    row['pad_stack_pairs_after'] = after.get('pad_stack_pairs')",
     "    row['pad_stack_pairs_after'] = None",
     (REPRO, FORCE), 'KILLED'),
    ('refusal-does-not-say-why', 'pose',
     "        if any(k.startswith('pad_stack_') for k in bad):",
     "        if False:",
     (REPRO,), 'KILLED'),
    ('legal-scope-silent', 'pose',
     "               \"-- a pad stack, check_assembly's pad_intersection (#1064)\")",
     "               \"-- check_assembly's pad_intersection (#1064)\")",
     (SCOPE,), 'KILLED'),
    # -- check_floorplan: printed, exact --------------------------------------
    ('floorplan-not-measured', 'cfp',
     "                       with_pad_stacks=True)",
     "                       with_pad_stacks=False)",
     (FLOORPLAN,), 'KILLED'),
    ('floorplan-prints-the-box-census', 'fp',
     "            f\"  pad stacks: {_ps1064['pad_stack_count']} (two parts' pad \"",
     "            f\"  pad stacks: {r.legality.get('pad_intersection_pairs')} (two parts' pad \"",
     (FLOORPLAN_EXACT,), 'KILLED'),
    ('summary-key-is-the-box-census', 'fp',
     "        out['pad_stack_count'] = r.pad_stacks['pad_stack_count']",
     "        out['pad_stack_count'] = r.legality.get('pad_intersection_pairs')",
     (FLOORPLAN_EXACT,), 'KILLED'),
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
