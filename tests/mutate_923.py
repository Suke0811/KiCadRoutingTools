#!/usr/bin/env python3
"""Mutation battery for #923 -- the three blind spots, and their controls.

Green tests are not evidence of coverage, and a gate ADDED to close a blind
spot is exactly the kind of code that can assert nothing while printing PASS.
Every row below breaks one thing the new gates claim to hold down; a row that
survives is a hole, and a row recorded as an expected survivor is a finding
rather than a convenience.

    python3 tests/mutate_923.py            # every row
    python3 tests/mutate_923.py --list
    python3 tests/mutate_923.py --row skill-key-misspelt

A row is KILLED by a FAILURE or an ERROR. An anchor that does not match EXACTLY
ONCE is reported BROKEN, never skipped: a mutation that silently edited nothing
would otherwise be recorded as a surviving row, which is the opposite of what
it means.

Refuses to start on a dirty target tree, because it restores the ORIGINAL text
from disk and would write committed text over uncommitted work.

Three of the seven rows mutate the GATES rather than the things they guard.
That is deliberate: the controls inside `test_923_output_key_claims` and the
exit-code analyser in `test_431_skill_commands` are the only reason those
gates cannot pass on an empty scan, so a battery that never breaks them would
be reporting on a claim nobody tested. (The staged drivers' site-enumeration
rows left with the drivers when their skills were retired for pcb-free-agent.)

Four rows SURVIVED on the run that mattered, and every one was a real finding
rather than a rejected row: two showed the flag scan could not see a command
that spells its tool by bare basename (which the drivers do, four times), one
showed a scenario deletion only bites when that scenario is the sole renderer
of a checkable text, and one was a mutation that renamed a label and changed
nothing. The gates were fixed; the rows now kill.
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KILLED, SURVIVED, BROKEN = 'KILLED', 'SURVIVED', 'BROKEN'

TARGETS = {
    'rs': os.path.join(REPO, '.claude', 'skills', 'plan-pcb-routing',
                       'SKILL.md'),
    'rd': os.path.join(REPO, 'py_router', 'routing_defaults.py'),
    'ru': os.path.join(REPO, 'tests', 'run_utils.py'),
    't431': os.path.join(REPO, 'tests', 'test_431_skill_commands.py'),
}

T431 = 'tests/test_431_skill_commands.py'
T923 = 'tests/test_923_output_key_claims.py'

#: (name, target, old, new, tests that must notice, expectation)
ROWS = [
    # ---- blind spot 2: the refusal branches --------------------------------
    # RETIRED. Its eight rows mutated the two staged drivers (and test_431's
    # dump reader) and were killed by the `--dump-refusals` scan; the drivers,
    # the dumps and that scan left the tree when the staged skills were
    # retired for pcb-free-agent, which emits no commands from code.

    # ---- blind spot 1: what a flag MEANS ------------------------------------
    # #923's acceptance criterion, exactly: move the constant and the skills
    # that quote it must fail.
    ('heuristic-weight-moves', 'rd',
     "HEURISTIC_WEIGHT = 2.3",
     "HEURISTIC_WEIGHT = 2.4",
     (T431,), KILLED),
    # ...and the other direction: the doc quoting the value it used to have.
    ('skill-quotes-the-old-default', 'rs',
     "| `--heuristic-weight 2.3` | 2.3 |",
     "| `--heuristic-weight 1.9` | 1.9 |",
     (T431,), KILLED),
    # The exit-code claim that was true only as a string. The placement
    # skill that carried it was retired, so the claim is INJECTED -- the exact
    # shape it had (a `#` annotation over a place_optimize --suggest-locks
    # command, which returns 0 above the board-state gate) -- into the routing
    # skill. SINGLE-LINE anchor on purpose: the target is CRLF, and a
    # multi-line anchor resolves differently depending on how the file is
    # read (`mutation_anchors.py` reports that as NEWLINE_SENSITIVE).
    ('exit-3-claim-returns', 'rs',
     "## Step 1: Load and Analyze PCB Structure",
     "# --suggest-locks exits 3 if the board is not placed\n"
     "python3 -X utf8 py_placer/place_optimize.py b.kicad_pcb --suggest-locks\n"
     "## Step 1: Load and Analyze PCB Structure",
     (T431,), KILLED),
    # The analyser behind it: if it stops seeing the early return, every
    # exit-code claim reads as fine.
    ('exit-analyser-blinded', 't431',
     "            if any(isinstance(x, ast.Return) for x in ast.walk(node)):\n"
     "                return True",
     "            if any(isinstance(x, ast.Return) for x in ast.walk(node)):\n"
     "                return False",
     (T431,), KILLED),

    # ---- blind spot 3: a claim about a tool's OUTPUT ------------------------
    # A key renamed in the doc rather than in the code. (`hot[].ratio`, the
    # key that started this, sat beside check_pockets in a skill page since
    # retired; test_923's own positive control still pins that exact claim.)
    ('skill-key-misspelt', 'rs',
     "  `components.unrouted.placement_blocked` and prints it",
     "  `components.unrouted.placement_blockd` and prints it",
     (T923,), KILLED),
    # The resolver, which is the only reason an unresolvable key is a failure.
    ('resolver-accepts-anything', 'ru',
     "        if not nxt:\n            return False",
     "        if not nxt:\n            return True",
     (T923,), KILLED),
    # The filter that keeps file names out of the key scan. Without it
    # `route.py` reads as a key claim and the control says so.
    ('path-filter-dropped', 'ru',
     "    if not text or text.lower().endswith(_PATH_NOT_A_KEY):\n"
     "        return None",
     "    if not text:\n        return None",
     (T923,), KILLED),
]


# The shared pre-flight (#877): refuses in ONE SECOND on an anchor that matches
# anything other than exactly once, instead of reporting BROKEN forty minutes
# later. Two of this battery's anchors went stale against edits in the same
# branch and only the standing gate noticed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mutation_anchors import preflight                       # noqa: E402
preflight(__file__)


def _dirty():
    r = subprocess.run(['git', 'status', '--porcelain'] +
                       sorted(set(TARGETS.values())),
                       cwd=REPO, capture_output=True, text=True)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def run_row(row, keep=False):
    name, target, old, new, tests, _expect = row
    path = TARGETS[target]
    # newline='' on BOTH sides: read with universal newlines and write with
    # none and every CRLF file comes back LF, so a row that RESTORED its target
    # still left the tree dirty. Measured on three .md targets.
    with open(path, encoding='utf-8', newline='') as fh:
        original = fh.read()
    if '\r\n' in original:
        # ...and the anchors are written with '\n', so they are translated to
        # the file's own ending rather than the file being normalised to
        # theirs. A multi-line anchor otherwise matches nothing in a CRLF file
        # and the row is reported BROKEN, which is the right answer to the
        # wrong question.
        old = old.replace('\n', '\r\n')
        new = new.replace('\n', '\r\n')
    if original.count(old) != 1:
        return BROKEN, f'anchor matched {original.count(old)} time(s)'
    try:
        with open(path, 'w', encoding='utf-8', newline='') as fh:
            fh.write(original.replace(old, new, 1))
        for t in tests:
            r = subprocess.run([sys.executable, '-X', 'utf8',
                                os.path.join(REPO, t)],
                               cwd=REPO, capture_output=True, text=True,
                               encoding='utf-8', errors='replace')
            if r.returncode != 0:
                return KILLED, f'{t} exit {r.returncode}'
        return SURVIVED, ''
    finally:
        if not keep:
            with open(path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(original)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--row', action='append', default=[])
    a = ap.parse_args()

    if a.list:
        for name, target, _o, _n, tests, expect in ROWS:
            print(f"  {name:32} {target:5} {expect:8} {' '.join(tests)}")
        return 0

    dirty = _dirty()
    if dirty:
        print('REFUSING: the target tree is dirty. This restores the ORIGINAL '
              'text from disk and would write committed text over uncommitted '
              'work.')
        for ln in dirty:
            print(f'  {ln}')
        return 2

    rows = [r for r in ROWS if not a.row or r[0] in a.row]
    if a.row and not rows:
        print(f'no row matches {a.row}')
        return 2
    counts = {KILLED: 0, SURVIVED: 0, BROKEN: 0}
    disagreed = 0
    for row in rows:
        got, detail = run_row(row)
        counts[got] += 1
        flag = 'ok  ' if got == row[5] else 'DISAGREES'
        if got != row[5]:
            disagreed += 1
        print(f'  {row[0]:32} {got:9} {flag} {detail}')
    print(f"\n{len(rows)} rows: {counts[KILLED]} killed, "
          f"{counts[SURVIVED]} survived, {counts[BROKEN]} broken, "
          f"{disagreed} disagreeing with expectation")
    return 1 if (counts[BROKEN] or disagreed) else 0


if __name__ == '__main__':
    sys.exit(main())
