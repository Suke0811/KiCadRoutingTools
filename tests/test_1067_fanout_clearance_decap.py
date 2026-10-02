#!/usr/bin/env python3
"""#1067: `place_fanout_clearance --intent` holds the declared decap limits.

Run 34 (glasgow, after bga_fanout U30) moved C63 from 2.00 to 2.96 mm from
its +3V3 ball U30.C10 while the tool logged "0 unresolved": the cap pass had
no intent input and no decap term. The fixture is that board cropped around
U30 (tests/fixtures/1067/make_fixture.py says how). What each case pins:

A. OFF (no intent) still breaks it -- the damaged control: the summary says
   0 unresolved while the decap grade gains U30's decap_pin_distance claim.
B. ON (`--intent`): the decap grade gains NO claim, `check_floorplan`
   agrees, JSON_SUMMARY says so, and the byte-pinned `Moved ...` line keeps
   its format. The cap the gate holds is named and stays unresolved.
C. ON with `--no-rotate`: the same holds without rotation.
D. The gate IS the quench's: `TetherGateView` binds QuenchState's methods
   (identity), and on a lattice of C63 poses its verdict equals a QuenchState
   built with the same tethers.
E. A move invalidates the gate's caches (`note_move`): a pin served by two
   caps refuses the second cap's walk-off once the first has walked off.
F. An unreadable intent exits 2 for that reason, writes no board and
   records nothing.
G. Without an intent nothing changes: no `Decap` line, no JSON_SUMMARY, and
   an early return grows no `decap` key.

    python3 tests/test_1067_fanout_clearance_decap.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, TESTS_DIR)

from kicad_parser import parse_kicad_pcb            # noqa: E402
from placement import floorplan as fp               # noqa: E402
from placement import quench as q                   # noqa: E402
import run_utils                                    # noqa: E402

RUN_ALL_TIMEOUT = 1800

FIX = os.path.join(TESTS_DIR, 'fixtures', '1067', 'u30_crop.kicad_pcb')
TOOL = run_utils.tool('place_fanout_clearance.py')
LIMIT = 2.5
MOVED = re.compile(r'^Moved \d+ cap\(s\); resolved \d+/\d+ initial '
                   r'violations(?: \(\d+ freed by via-nudge\))?; \d+ '
                   r'unresolved\.$', re.M)


def _intent_file(td):
    doc = fp.emit_intent(parse_kicad_pcb(FIX), FIX)
    doc['blocks'] = []
    doc['decaps'] = {'max_distance_mm': LIMIT, 'max_pin_distance_mm': LIMIT}
    path = os.path.join(td, 'crop.intent.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    return path


def _run(td, name, extra=()):
    out = os.path.join(td, name + '.kicad_pcb')
    r = subprocess.run([sys.executable, '-X', 'utf8', TOOL, FIX, out,
                        '--clearance', '0.1'] + list(extra),
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=ROOT)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    return out, r.stdout


def _decap_errors(board, intent):
    g = fp.grade(intent, parse_kicad_pcb(board), board)
    return [v for v in g.violations
            if v.rule.startswith('decap_') and v.severity == fp.ERROR]


def _summary(stdout):
    m = re.search(r'^JSON_SUMMARY: (.*)$', stdout, re.M)
    return json.loads(m.group(1)) if m else None


_CACHE = {}


def _arms():
    """The OFF and ON runs, once for the whole file."""
    if not _CACHE:
        td = tempfile.mkdtemp(prefix='t1067_')
        ip = _intent_file(td)
        _CACHE.update(td=td, ip=ip, intent=fp.load_intent(ip),
                      off=_run(td, 'off'),
                      on=_run(td, 'on', ['--intent', ip]))
    return _CACHE


def test_off_still_breaks_the_decap_limit():
    run_utils.evidence(FIX, 'the U30 crop')
    a = _arms()
    out, stdout = a['off']
    assert '0 unresolved.' in stdout, stdout[-800:]
    before = _decap_errors(FIX, a['intent'])
    after = _decap_errors(out, a['intent'])
    added = fp.grade_delta(before, after)
    assert {(d['rule'], d['ref']) for d in added} >= {
        ('decap_pin_distance', 'U30')}, added
    msg = [v.message for v in after if v.ref == 'U30']
    assert any('pin C10' in m and 'C63' in m for m in msg), msg
    assert 'Decap' not in stdout and _summary(stdout) is None, stdout[-600:]
    print(f"  PASS: without an intent the pass says 0 unresolved and adds "
          f"{added}")


def test_on_adds_no_decap_claim_and_names_the_held_cap():
    a = _arms()
    out, stdout = a['on']
    before = _decap_errors(FIX, a['intent'])
    after = _decap_errors(out, a['intent'])
    assert fp.grade_delta(before, after) == [], fp.grade_delta(before, after)
    assert not any(v.ref == 'U30' for v in after), [v.message for v in after]
    s = _summary(stdout)
    assert s and s['decap']['grade']['added'] == [], s
    assert s['decap']['grade']['errors_before'] == len(before), s
    assert MOVED.search(stdout), stdout[-1500:]
    assert 'Decap grade (intent): errors' in stdout, stdout[-800:]
    held = s['decap']['held']
    # the fixture exercises the gate: C63's only clear poses break a limit
    assert 'C63' in held, held
    assert set(held) <= set(s['unresolved']), (held, s['unresolved'])
    for ref in held:
        assert f"{ref} (decap_" in stdout, stdout[-800:]
    # check_floorplan, the grader a user runs, agrees
    r = subprocess.run([sys.executable, '-X', 'utf8',
                        run_utils.tool('check_floorplan.py'), out, '--intent',
                        a['ip'], '--allow-routed'],
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=ROOT)
    assert not re.search(r'ERROR\] decap_pin_distance: U30 ', r.stdout), \
        r.stdout[-1500:]
    print(f"  PASS: --intent adds no decap claim ({len(before)} -> "
          f"{len(after)} errors); held: {sorted(held)}")


def test_on_without_rotation_holds_too():
    a = _arms()
    out, stdout = _run(a['td'], 'on_nr', ['--intent', a['ip'], '--no-rotate'])
    before = _decap_errors(FIX, a['intent'])
    assert fp.grade_delta(before, _decap_errors(out, a['intent'])) == []
    s = _summary(stdout)
    assert s['decap']['refused'], s
    print(f"  PASS: --no-rotate: no decap claim added; held "
          f"{sorted(s['decap']['held'])}")


def _spec(intent):
    return {k: v for k, v in fp.tether_gate_spec(intent).items()
            if k in ('decap_distance', 'decap_pin_distance')}


def test_the_gate_is_the_quench_gate():
    from placement import fanout_clearance as fc
    for name in ('_tether_measure', 'tether_failures', 'tether_ok',
                 'tether_terms_for', '_iter_tether_failures',
                 '_incumbent_tether', '_posed_fp', '_pose_of'):
        assert getattr(q.TetherGateView, name) is getattr(q.QuenchState,
                                                         name), name
    a = _arms()
    pcb = parse_kicad_pcb(FIX)
    spec = _spec(a['intent'])
    st = fc._Repair(pcb, FIX, 0.1, 0.1, 0.55, 1.0, 2.0, 0.3, 'C,R,FB',
                    set())
    view = q.TetherGateView(pcb, FIX, st.caps, spec)
    assert view._tether_active and 'C63' in view._tethers_of, \
        sorted(view._tethers_of)
    qs = q.QuenchState(pcb, FIX, 0.1, 0.55, 30.0, 0.5, 0.15, 2.0, 2.0, 2.0,
                       0.1, 0.3, tethers=spec)
    c = st.caps['C63']
    n = refused = 0
    for dx in (-1.5, -0.75, 0.0, 0.75, 1.5):
        for dy in (-1.5, -0.75, 0.0, 0.75, 1.5):
            for rot in (0.0, 90.0, 180.0, 270.0):
                pose = {'C63': (c.x + dx, c.y + dy, rot)}
                v, w = view.tether_ok(pose), qs.tether_ok(pose)
                assert v == w, (pose, v, w)
                n += 1
                refused += not v
    assert 0 < refused < n, (refused, n)
    print(f"  PASS: bound methods are QuenchState's; {n} C63 poses agree "
          f"with the quench ({refused} refused)")


def test_a_move_invalidates_the_gate_caches():
    """Find a supply pin two movable caps both serve within the limit. With
    A in place, B may walk off (A still serves the pin). Once A has walked
    off and the gate is told, B's walk-off is refused."""
    from placement import fanout_clearance as fc
    a = _arms()
    pcb = parse_kicad_pcb(FIX)
    st = fc._Repair(pcb, FIX, 0.1, 0.1, 0.55, 1.0, 2.0, 0.3, 'C,R,FB',
                    set())
    view = q.TetherGateView(pcb, FIX, st.caps, _spec(a['intent']))
    st._tethers = view
    found = None
    for i, t in enumerate(view._tether_terms):
        if t.kind != 'pin':
            continue
        movable = [r for r in t.data['caps'] if r in st.caps]
        if len(movable) < 2 or view._tether_value(i) > t.threshold:
            continue
        for ca in movable:
            for cb in movable:
                if ca == cb:
                    continue
                far_a = (st.caps[ca].x + 6.0, st.caps[ca].y, st.caps[ca].rot)
                far_b = (st.caps[cb].x - 6.0, st.caps[cb].y, st.caps[cb].rot)
                if (view.tether_ok({cb: far_b})
                        and not view.tether_ok({ca: far_a, cb: far_b})):
                    found = (ca, cb, far_a, far_b)
                    break
            if found:
                break
        if found:
            break
    assert found, 'the fixture has no pin two movable caps both serve'
    ca, cb, far_a, far_b = found
    assert view.tether_ok({cb: far_b})          # A still serves the pin
    st.apply_pose(ca, *far_a)                   # A walks off; the gate is told
    assert not view.tether_ok({cb: far_b}), (ca, cb)
    print(f"  PASS: {cb} may leave while {ca} serves the pin, and is refused "
          f"once {ca} has left")


def test_an_unreadable_intent_is_refused():
    with tempfile.TemporaryDirectory() as td:
        bad = os.path.join(td, 'bad.json')
        with open(bad, 'w', encoding='utf-8') as fh:
            fh.write('{ not json')
        out = os.path.join(td, 'out.kicad_pcb')
        manifest = os.path.join(td, 'redo_commands.sh')
        env = dict(os.environ, REDO_MANIFEST=manifest)
        r = subprocess.run([sys.executable, '-X', 'utf8', TOOL, FIX, out,
                            '--intent', bad], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', cwd=ROOT,
                           env=env)
        assert r.returncode == 2, (r.returncode, r.stdout[-500:],
                                   r.stderr[-500:])
        assert 'cannot load intent' in r.stderr, r.stderr[-500:]
        assert not os.path.exists(out), 'a refused run wrote a board'
        assert not os.path.exists(manifest) or \
            os.path.getsize(manifest) == 0, open(manifest).read()
    print("  PASS: an unreadable intent exits 2, writes nothing, records "
          "nothing")


def test_no_intent_changes_nothing():
    from placement import fanout_clearance as fc
    board = os.path.join(ROOT, 'kicad_files', 'flat_hierarchy.kicad_pcb')
    pcb = parse_kicad_pcb(board)
    # an early return (no vias): no `decap` key, with or without an intent
    with tempfile.TemporaryDirectory() as td:
        doc = fp.emit_intent(pcb, board)
        doc['decaps'] = {'max_distance_mm': LIMIT}
        ip = os.path.join(td, 'i.json')
        with open(ip, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh)
        for intent in (None, fp.load_intent(ip)):
            res = fc.repair_fanout_clearance(parse_kicad_pcb(board), board,
                                             intent=intent)
            assert 'decap' not in res, sorted(res)
    a = _arms()
    out, stdout = a['off']
    assert 'Decap' not in stdout and 'JSON_SUMMARY' not in stdout
    print("  PASS: no intent prints no Decap line and no JSON_SUMMARY; an "
          "early return grows no key")


TESTS = [
    test_off_still_breaks_the_decap_limit,
    test_on_adds_no_decap_claim_and_names_the_held_cap,
    test_on_without_rotation_holds_too,
    test_the_gate_is_the_quench_gate,
    test_a_move_invalidates_the_gate_caches,
    test_an_unreadable_intent_is_refused,
    test_no_intent_changes_nothing,
]


if __name__ == '__main__':
    only = sys.argv[1:]
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        print(f"--- {t.__name__}")
        t()
    print('ALL PASS')
