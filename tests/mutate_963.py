#!/usr/bin/env python3
"""#963 mutation battery: is each gate ARMED, or does its test merely run?

    python3 tests/mutate_963.py                 # every battery
    python3 tests/mutate_963.py converge        # one
    python3 tests/mutate_963.py --row <name>
    python3 tests/mutate_963.py --list

NOT named `test_*`, so `run_all.py` never collects it: it REWRITES engine and
skill files in place and restores them, and a suite running beside it would
grade a mutated tree. One writer per tree.

WHY THIS ISSUE NEEDS ONE PARTICULARLY. Six fresh verifiers read these six
commits, and between them they found FIVE guards that could not fail:

  * the L5 terminal ship refusal -- deleting the whole 50-line block passed
    --self-test, both dumps, and every 963/904/431/923 test, because
    `_refusal_sites` builds its obligation by AST-walking the same file it
    checks;
  * the bare-`--quiet` clause in test_431, sitting behind a `continue` on its
    own condition;
  * four discovery rows, because every test drove `_cross_check` with a
    hand-built namespace and nothing asserted that l5 CALLS discovery;
  * `_await_report` never re-running the board audits when DONE changed -- the
    branch its own commit called load-bearing;
  * and `arm_report` writing no marker, which is the whole production-caller
    claim.

Every one of those was green. So a row here is not a formality: it is the only
instrument that distinguishes "the test passes" from "the test would notice".

A row is KILLED when any named test exits non-zero -- a failed assertion and an
ERROR count the same, because a mutation that makes the graders crash is still
one the graders noticed. A row whose anchor does not match EXACTLY ONCE is
BROKEN, not skipped: an anchor that silently matches nothing reports every
mutation as killed and is the most flattering possible bug.

PER-ROW TEST LISTS. A row may name its own killers instead of its battery's
(`None` means the battery's list). The three rows that named
`test_431_skill_commands.py` for a driver-emitted `--quiet` left with the
loop driver when the staged skills were retired for pcb-free-agent.

BYTECODE. Each row rewrites a file and restores it within the same second, so
the runner drops `__pycache__` and runs every test with `-B`; without that a
later row imports an earlier row's mutant and the results are fiction.
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS)
sys.path.insert(0, _TESTS)

CONVERGE = os.path.join(_ROOT, 'py_placer', 'converge.py')
RENDER = os.path.join(_ROOT, 'py_tools', 'render_placement.py')
WATCHER = os.path.join(_ROOT, 'tests', 'stress', 'run_watch.py')

T_CLASS = os.path.join(_TESTS, 'test_963_classification_evidence.py')
T_EXH = os.path.join(_TESTS, 'test_963_exhaustion_binding.py')
T_BIND = os.path.join(_TESTS, 'test_963_one_binding_predicate.py')
T_TEMPL = os.path.join(_TESTS, 'test_963_render_templates.py')
T_MARK = os.path.join(_TESTS, 'test_963_report_marker.py')
T_LAP = os.path.join(_TESTS, 'test_904_not_a_lap.py')
T_898 = os.path.join(_TESTS, 'test_898_review_sheet_without_json.py')

# --- converge: the record's own gates -------------------------------------
CONVERGE_ROWS = [
    # The predicate #963 exists to make singular. Collapsing it to a bool
    # deletes cmd_record's "payload carries no board_sha" disclosure, which is
    # a different operator action from "grades a different board".
    ('binding-collapsed-to-a-bool',
     "        return ('this' if board_sha == psha else 'other', psha)",
     "        return ('this' if board_sha == psha else 'other', psha)\n"
     "    # mutant: unbound reads as other\n"
     "    if True:\n"
     "        return ('other', psha)",
     None),
    # "I could not tell" must never read as a mismatch.
    ('unknown-reads-as-other',
     "    if not board or not os.path.isfile(board):\n"
     "        return ('unknown', psha)",
     "    if not board or not os.path.isfile(board):\n"
     "        return ('other', psha)",
     None),
    # The row's own board, which is what binds a declaration to a board.
    ('declaration-drops-the-board',
     "            sha = r.get('result_sha')",
     "            sha = None",
     None),
    # The contributor's own "safe initial implementation", as a mutation. A
    # test must kill it, or the argument for reporting rather than gating is
    # unproven.
    ('any-digest-change-invalidates',
     "            if board_sha and board_sha != dec[2]:\n"
     "                out['declared_stale_board'] = dec[2]",
     "            if board_sha and board_sha != dec[2]:\n"
     "                out['declared_stale_board'] = dec[2]\n"
     "                out.update(flat=False, why='too-few-laps')",
     None),
    # A declaration is a claim about --board; an ordinary row is not.
    ('exhausted-score-mismatch-back-to-a-warning',
     "    if a.exhausted and isinstance(_score_doc, dict):",
     "    if False and isinstance(_score_doc, dict):",
     None),
    # The shape IS the decision.
    ('classification-shape-not-required',
     "    if a.kind == 'classification' and not a.shape:",
     "    if False and not a.shape:",
     None),
    # ...and the measurement that named it. Without this the gate is cleared
    # by one command that records nothing, which is how run 29's exact false
    # close-out was accepted in a verifier's reconstruction.
    ('classification-lever-not-required',
     "    if a.kind == 'classification' and not (a.lever or '').strip():",
     "    if False and not (a.lever or '').strip():",
     None),
    # A decision that was thrown away is not one the next lap can act on.
    ('a-rejected-classification-counts',
     "        if (r.get('kind') or '') == 'classification' and r.get('accepted'):",
     "        if (r.get('kind') or '') == 'classification':",
     None),
    # The LAST decision, not the first.
    ('classification-picks-the-first-not-the-last',
     "            found, idx = r, i\n    if found is None:",
     "            found, idx = found or r, idx if idx >= 0 else i\n"
     "    if found is None:",
     None),
    # convergence.md's strongest claim, on a ledger that measured nothing.
    ('final-stop-4-gate-deleted',
     "    if a.final and _stop_token in UNFIXABLE_STOPS:",
     "    if False and _stop_token in UNFIXABLE_STOPS:",
     None),
    # "This board cannot be fixed" is a claim about the whole board, so a
    # placement lap makes it as stale as a routing lap does.
    ('stop-4-counts-routing-only',
     "        _since = None if _cls is None else sum(_cls['laps_since'].values())",
     "        _since = None if _cls is None else _cls['laps_since']['routing']",
     None),
    # A reader crashing on a bad row rather than reading it as "not this half".
    ('is_lap-unhashable-kind-crashes',
     "    if _HALF.get(str(row.get('kind') or '')) != half:",
     "    if _HALF.get(row.get('kind')) != half:",
     None),
    # ROUND 2. The hardened `_is_lap` is UNREACHABLE from the stop-4 gate --
    # this walk runs first, so a bare string on any ledger line tracebacked
    # out before a lap was counted. A traceback is not a refusal.
    ('is_lap-assumes-objects',
     "    if not isinstance(row, dict):\n        return False\n"
     "    if _HALF.get(str(row.get('kind') or '')) != half:",
     "    if _HALF.get(str(row.get('kind') or '')) != half:",
     None),
    ('classification-walk-assumes-objects',
     "        if not isinstance(r, dict):\n            continue\n"
     "        # ACCEPTED ONLY.",
     "        # ACCEPTED ONLY.",
     None),
    # "Nobody classified" and "every classification was thrown away" are
    # different sentences about the reader's own file, and only one of them
    # was ever printed.
    ('rejected-only-reads-as-never-written',
     "        _rej = _classification_rejected(_prior)",
     "        _rej = 0",
     None),
    # The null lever with a word typed in it.
    ('lever-may-name-the-shape-again',
     "    if (a.kind == 'classification'\n"
     "            and (a.lever or '').strip().strip('.:;,-').lower() in SHAPES):",
     "    if False and (a.lever or '').strip().lower() in SHAPES:",
     None),
    # A write site with no read site: "nobody could look" then reads to the
    # operator exactly like "it was checked and it matched".
    ('unbindable-declaration-goes-silent',
     "        if st[h].get('declared_board_unknown'):",
     "        if False and st[h].get('declared_board_unknown'):",
     [T_EXH]),
]

# --- the loop driver: RETIRED ---------------------------------------------
# Its 21 rows (the L5 continue gate, verdict discovery, the hand-off renders'
# --quiet/-o, the close-out DONE marker) mutated loop_driver.py, which was
# retired with the combined skill for pcb-free-agent, as were its killers
# test_904_closeout_order and test_431's driver-render arm.

# --- render_placement: the document must survive a sheet failure ----------
RENDER_ROWS = [
    ('sheet-failure-eats-the-document',
     "    _sheet_exit = 2 if _sheet_failed else 0\n"
     "    if _sheet_failed:",
     "    _sheet_exit = 0\n"
     "    if _sheet_failed:\n"
     "        return 2\n"
     "    if _sheet_failed:",
     None),
    ('gate-4-hides-the-sheet-refusal',
     "            return _sheet_exit or 4",
     "            return 4",
     None),
]

# --- run_watch: the second marker -----------------------------------------
WATCHER_ROWS = [
    # `return 0 or _await_report(...)` was a BAD MUTATION, not a missing test:
    # `0 or X` evaluates X, so the mutant behaved identically and reported
    # SURVIVED about a row that had changed nothing. This one restores the
    # pre-#963 contract -- exit at DONE, and never audit the report.
    ('report-marker-never-waited',
     "            return _await_report(workdir, done_path, _done_sha, truthdir,",
     "            return 0\n"
     "            return _await_report(workdir, done_path, _done_sha, truthdir,",
     None),
    ('report-audit-is-a-noop',
     "    out = []\n    if not os.path.isfile(report_path):",
     "    return []\n    out = []\n    if not os.path.isfile(report_path):",
     None),
    ('bounded-wait-removed',
     "    _deadline = time.monotonic() + report_wait if report_wait else None",
     "    _deadline = None",
     None),
    ('done-rewrite-not-detected',
     "            if now and done_sha and now != done_sha:",
     "            if False:",
     None),
    ('shipped-sha-back-to-every-hex-token',
     "    shipped = set(_DONE_SHIPPED_RE.findall(done_raw))",
     "    shipped = set(_SHA_RE.findall(done_raw))",
     None),
]

ARM_ROWS = [
    # The production caller, without which the guard never arms: the watcher
    # then waits for a file only an agent would ever write. Its own list,
    # because a battery's rows are resolved against that battery's FILE and a
    # row living in the wrong list reports STALE.
    ('report-marker-has-no-producer',
     "        with open(_marker, 'w', encoding='utf-8') as fh:",
     "        with open(_marker + '.disabled', 'w', encoding='utf-8') as fh:",
     None),
]

ARM_REPORT = os.path.join(_ROOT, 'tests', 'stress', 'arm_report.py')

BATTERIES = {
    'converge': (CONVERGE, [T_CLASS, T_EXH, T_LAP, T_BIND], CONVERGE_ROWS),
    'render': (RENDER, [T_TEMPL, T_898], RENDER_ROWS),
    'watcher': (WATCHER, [T_MARK], WATCHER_ROWS),
    'armreport': (ARM_REPORT, [T_MARK], ARM_ROWS),
}

from mutation_anchors import preflight                        # noqa: E402
preflight(__file__)


def _dirty(path):
    p = subprocess.run(['git', 'status', '--porcelain', '--', path],
                       capture_output=True, text=True, cwd=_ROOT)
    return bool(p.stdout.strip())


def _drop_pyc(path):
    cache = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(cache):
        shutil.rmtree(cache, ignore_errors=True)


def run(which, only=None):
    src_path, tests, rows = BATTERIES[which]
    rows = [r for r in rows if only is None or r[0] == only]
    if not rows:
        return None
    if _dirty(src_path):
        print('REFUSING: %s has uncommitted changes. Commit first -- this '
              'battery restores by overwriting.' % os.path.basename(src_path))
        return 2

    orig = io.open(src_path, encoding='utf-8', newline='').read()
    results = []
    try:
        for row in rows:
            name, old, new = row[0], row[1], row[2]
            extra = row[3] if len(row) > 3 else None
            n = orig.count(old)
            if n != 1:
                results.append((name, 'BROKEN', 'anchor matched %d times' % n,
                                []))
                continue
            io.open(src_path, 'w', encoding='utf-8', newline='').write(
                orig.replace(old, new, 1))
            _drop_pyc(src_path)
            killers = []
            for t in list(tests) + list(extra or []):
                p = subprocess.run(
                    [sys.executable, '-X', 'utf8', '-B', t],
                    capture_output=True, text=True, timeout=2400, cwd=_ROOT)
                if p.returncode:
                    killers.append(os.path.basename(t))
                    break          # one killer is enough; the rest cost time
            io.open(src_path, 'w', encoding='utf-8', newline='').write(orig)
            _drop_pyc(src_path)
            results.append((name, 'KILLED' if killers else 'SURVIVED',
                            '%d' % len(killers), killers))
    finally:
        io.open(src_path, 'w', encoding='utf-8', newline='').write(orig)
        _drop_pyc(src_path)

    w = max(len(r[0]) for r in results)
    for name, verdict, cnt, killers in results:
        print('%-*s  %-9s  %s' % (w, name, verdict, cnt))
        for f in killers:
            print('%s      %s' % (' ' * w, f))
    killed = sum(1 for r in results if r[1] == 'KILLED')
    broken = sum(1 for r in results if r[1] == 'BROKEN')
    print('\n%s: killed %d / %d%s'
          % (which, killed, len(results),
             ', %d BROKEN ANCHOR(S)' % broken if broken else ''))
    return 0 if killed == len(results) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('battery', nargs='?', choices=sorted(BATTERIES),
                    help='default: every battery')
    ap.add_argument('--row', help='run a single row by name')
    ap.add_argument('--list', action='store_true',
                    help='row names and their battery, run nothing')
    a = ap.parse_args()
    if a.list:
        for which in sorted(BATTERIES):
            for row in BATTERIES[which][2]:
                print('%-10s %s' % (which, row[0]))
        return 0
    worst = 0
    for which in ([a.battery] if a.battery else sorted(BATTERIES)):
        rc = run(which, a.row)
        if rc is None:
            continue
        worst = max(worst, rc)
    if a.row and worst == 0 and not any(
            r[0] == a.row for w in BATTERIES for r in BATTERIES[w][2]):
        print('no row named %r' % a.row)
        return 1
    return worst


if __name__ == '__main__':
    sys.exit(main())
