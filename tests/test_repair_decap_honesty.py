#!/usr/bin/env python3
"""#1066: `place_seed --repair` reports a violator repaired only when the grade
error it was CHARGED for is gone.

The repair charges every intent grade error that names a ref (decap_distance,
decap_pin_distance, zones, ...), but `_try_place` searches for the nearest
LEGAL pose and has no intent target, so it accepts the part where it stands.
The run-7 honesty re-grade re-checked pads, holes and containment only, so
each intent-only violator was reported repaired with nothing moved -- glasgow
run 34: "33 violator(s), 33 repaired (0 moved)", floorplan errors 43 -> 43.

What each case pins (esp_prog, `decaps.max_distance_mm = 2.0`, which charges
C3 alone at the human pose: 2.125mm from U1):

* ZERO MOVE: C3 at its human pose is not moved and is UNRESOLVED, naming
  decap_distance.
* MOVED, STILL FAILING: C3 dropped onto Y1's pads is charged for the pad
  conflict AND the decap distance. The repair moves it off R1 -- and it is
  still too far from U1, so it is UNRESOLVED too ("it moved"). Re-grading
  only the zero-move refs (the obvious half-fix) passes the first case and
  fails this one.
* A REAL FIX is still repaired: R2 dropped onto R1 charges one pad conflict,
  the repair moves one of them off it, and that part is reported repaired.
* A charged claim the POSE grader cannot reproduce (it comes from `grade`
  outside the rules loop, so no move can clear it) stays UNRESOLVED.
* A re-grade that RAISES is not a pass: the ref is unresolved and says why.
* CLI: `place_seed --repair` writes `violators`, `repaired_refs`,
  `unresolved_refs`, `unresolved_by_rule` (its exit 4 is the final grade's,
  as before), and -- the issue's own regression property -- the refs it
  reports repaired share no member with the refs a FRESH `floorplan.grade` of
  the written board still charges a decap error to.

    python3 tests/test_repair_decap_honesty.py
"""
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS_DIR)

from kicad_parser import parse_kicad_pcb           # noqa: E402
from placement import floorplan as fp              # noqa: E402
from placement import seeder                       # noqa: E402
from placement.writer import write_placed_output   # noqa: E402
from run_utils import check, evidence              # noqa: E402

RUN_ALL_TIMEOUT = 600

ESP = os.path.join(ROOT, 'kicad_files', 'esp_prog.kicad_pcb')
PLACE_SEED = os.path.join(ROOT, 'py_placer', 'place_seed.py')
SOURCES = ('kicad', 'sheet')
CLEARANCE = 0.2
DECAP_RULES = ('decap_distance', 'decap_pin_distance')


def _intent(td):
    doc = {'schema': 1, 'kind': fp.KIND, 'units': 'mm',
           'decaps': {'max_distance_mm': 2.0}}
    path = os.path.join(td, 'intent.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)
    return fp.load_intent(path), path


def _board(td, name, moves=()):
    """esp_prog, with `moves` [(ref, x, y)] applied through the shipped
    writer, and its project siblings -- or the tracked board itself."""
    if not moves:
        return ESP
    pcb = parse_kicad_pcb(ESP)
    out = os.path.join(td, name)
    write_placed_output(ESP, out, [
        {'reference': r, 'new_x': x, 'new_y': y,
         'new_rotation': pcb.footprints[r].rotation or 0.0}
        for r, x, y in moves])
    return evidence(out, 'the perturbed board')


def _repair(board, intent):
    return seeder.repair_placement(
        parse_kicad_pcb(board), board, intent, group_sources=SOURCES,
        clearance=CLEARANCE)


def _decap_refs_after(board, res, intent, td, name):
    """Refs a FRESH grade of the repaired, written board charges a decap
    error to -- the issue's own instrument, not the repair's."""
    out = os.path.join(td, name)
    write_placed_output(board, out, res['moves'])
    g = fp.grade(intent, parse_kicad_pcb(out), out, group_sources=SOURCES,
                 clearance=CLEARANCE)
    return {v.ref for v in g.errors if v.rule in DECAP_RULES}


def test_a_zero_move_decap_violator_is_unresolved():
    with tempfile.TemporaryDirectory() as td:
        intent, _p = _intent(td)
        res = _repair(ESP, intent)
        assert 'C3' in res['violators'], res['violators']
        assert not res['moves'], res['moves']
        assert 'C3' not in res['repaired'], res['repaired']
        assert 'C3' in res['unresolved'], res['unresolved']
        assert res['unresolved_claims']['C3'] == ['decap_distance'], \
            res['unresolved_claims']
        note = [n for n in res['notes'] if n.startswith('C3: UNRESOLVED')]
        assert note and 'decap_distance' in note[0] \
            and 'did not move' in note[0], res['notes']
        still = _decap_refs_after(ESP, res, intent, td, 'z.kicad_pcb')
        assert not set(res['repaired']) & still, (res['repaired'], still)
    print(f"  PASS: C3 not moved and unresolved -- {note[0]}")


def test_a_moved_violator_still_failing_is_unresolved_and_a_real_fix_is_not():
    pcb = parse_kicad_pcb(ESP)
    r1, y1 = pcb.footprints['R1'], pcb.footprints['Y1']
    with tempfile.TemporaryDirectory() as td:
        intent, _p = _intent(td)
        # C3 onto the crystal Y1: 3.555mm from U1, inside the decap radius
        # (so graded, not `decap_ungraded`), and no move off Y1 that a pad
        # conflict licenses brings it within 2mm. R2 onto R1.
        board = _board(td, 'stacked.kicad_pcb',
                       [('C3', y1.x, y1.y), ('R2', r1.x, r1.y + 0.3)])
        res = _repair(board, intent)
        moved = {m['reference'] for m in res['moves']}
        # The pad conflict moved C3 -- the arm is about a MOVED violator.
        assert 'C3' in moved, (moved, res['notes'])
        assert 'C3' in res['unresolved'], (res['unresolved'], res['notes'])
        assert 'C3' not in res['repaired'], res['repaired']
        note = [n for n in res['notes'] if n.startswith('C3: UNRESOLVED')]
        assert note and 'it moved' in note[0], res['notes']
        # R1/R2 is a pad conflict and nothing else: one of the pair moved
        # off the other and that part IS repaired. (Its partner is repaired
        # too without moving -- the pair is clear -- which is run-7 A2's
        # legitimate zero-move case, not this issue's.)
        fixed = {'R1', 'R2'} & set(res['repaired'])
        assert fixed & moved, (res['repaired'], moved)
        still = _decap_refs_after(board, res, intent, td, 'm.kicad_pcb')
        assert 'C3' in still, still
        assert not set(res['repaired']) & still, (res['repaired'], still)
    print(f"  PASS: C3 moved {sorted(moved)} and is unresolved; "
          f"{sorted(fixed)} repaired")


def test_a_claim_the_pose_grader_cannot_reproduce_stays_unresolved():
    """A charged error from `grade` outside its rules loop (intent
    validation, block resolution, `exclusive_unsatisfiable`) is invariant
    under every move. Injected here as one extra error on U2, which carries
    no other claim and does not move."""
    real = fp.grade

    def grade_plus(*a, **kw):
        g = real(*a, **kw)
        g.violations.append(fp.Violation(
            'synthetic_invariant', fp.ERROR, 'a claim no pose can change',
            ref='U2', expected={'k': 1}))
        return g
    with tempfile.TemporaryDirectory() as td:
        intent, _p = _intent(td)
        fp.grade = grade_plus
        try:
            res = _repair(ESP, intent)
        finally:
            fp.grade = real
        assert 'U2' in res['violators'], res['violators']
        assert 'U2' not in {m['reference'] for m in res['moves']}
        assert 'U2' in res['unresolved'], (res['unresolved'], res['notes'])
        assert res['unresolved_claims']['U2'] == ['synthetic_invariant']
    print("  PASS: a pose-invariant charged claim is never read as cleared")


def test_a_regrade_that_raises_is_not_a_pass():
    real = fp.PoseGrader.violations
    calls = {'n': 0}

    def flaky(self, *a, **kw):
        calls['n'] += 1
        if calls['n'] > 1:
            raise fp.UntrustworthyOutline(['injected after the census'])
        return real(self, *a, **kw)
    with tempfile.TemporaryDirectory() as td:
        intent, _p = _intent(td)
        fp.PoseGrader.violations = flaky
        try:
            res = _repair(ESP, intent)
        finally:
            fp.PoseGrader.violations = real
        assert calls['n'] >= 2, calls
        assert 'C3' in res['unresolved'], (res['unresolved'], res['notes'])
        note = [n for n in res['notes'] if n.startswith('C3: UNRESOLVED')]
        assert note and 'could not be re-run' in note[0], res['notes']
    print(f"  PASS: {note[0]}")


def _summary(r):
    m = re.search(r'^JSON_SUMMARY: (.*)$', r.stdout, re.M)
    assert m, r.stdout[-1500:]
    return json.loads(m.group(1))


def test_cli_writes_the_refs_and_the_repaired_set_is_honest():
    from placement.portfolio import copy_siblings
    with tempfile.TemporaryDirectory() as td:
        intent, ipath = _intent(td)
        src = os.path.join(td, 'in.kicad_pcb')
        write_placed_output(ESP, src, [])
        copy_siblings(ESP, src)
        out = os.path.join(td, 'out.kicad_pcb')
        # Exit 4 here is the FINAL GRADE's (the board still carries C3's
        # error, which place_seed has always refused on), asserted by its
        # reason -- not `unresolved`, which sets no exit code of its own.
        r = check([sys.executable, '-X', 'utf8', PLACE_SEED, src, out,
                   '--intent', ipath, '--repair', '--clearance',
                   str(CLEARANCE)], refuse='GRADE ERROR [decap_distance] C3',
                  code=4, timeout=RUN_ALL_TIMEOUT)
        s = _summary(r)
        for k in ('violators', 'repaired_refs', 'unresolved',
                  'unresolved_refs', 'unresolved_by_rule'):
            assert k in s, (k, sorted(s))
        assert 'C3' in s['unresolved_refs'], s
        assert s['unresolved_by_rule'].get('decap_distance') == 1, s
        assert s['repaired'] == len(s['repaired_refs']), s
        assert s['unresolved'] == len(s['unresolved_refs']), s
        g = fp.grade(intent, parse_kicad_pcb(evidence(out, 'the output')),
                     out, group_sources=SOURCES, clearance=CLEARANCE)
        still = {v.ref for v in g.errors if v.rule in DECAP_RULES}
        assert 'C3' in still, still
        assert not set(s['repaired_refs']) & still, (s['repaired_refs'],
                                                      still)
        line = [ln for ln in r.stdout.splitlines()
                if ln.startswith('Repair:')]
        assert line and '1 unresolved' in line[0], line
    print(f"  PASS: {line[0]}")


TESTS = [
    test_a_zero_move_decap_violator_is_unresolved,
    test_a_moved_violator_still_failing_is_unresolved_and_a_real_fix_is_not,
    test_a_claim_the_pose_grader_cannot_reproduce_stays_unresolved,
    test_a_regrade_that_raises_is_not_a_pass,
    test_cli_writes_the_refs_and_the_repaired_set_is_honest,
]


if __name__ == '__main__':
    only = sys.argv[1:]
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        print(f"--- {t.__name__}")
        t()
    print('ALL PASS')
