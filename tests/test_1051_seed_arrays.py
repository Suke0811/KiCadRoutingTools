#!/usr/bin/env python3
"""#1051 / #1053 / #1054 phase 3: the SEEDER seats declared rows, seats the
served ICs first, and seats fixed poses exactly.

What each case pins, and why:

* splitflap U4:47k (the detector's row, `emit_intent(derive_arrays='auto')`):
  seated as ONE row -- one axis, U4's pin order (either direction), one
  rotation, a pitch that clears the board clearance -- and the GRADER, on a
  written copy of the seeded poses, calls it formed too (`array_formation`,
  the rule's own measurement, not the seeder's self-check). Every member
  passes `pose_ok` against its siblings at the written poses.
* glasgow: a resistor-array pair (U30:33R~2, RN7+RN8) and a buffer bank
  (U30:SN74LVC1T45DCKR~2, eight SOT-363) form, graded the same way.
* an UNSEATABLE row (esp_prog R3+R4 at a declared pitch below the courtyard)
  is disclosed in `array_unseated` with its reason, and its members are still
  seated one by one -- not unseated.
* the POSE CAP trips and says so (`array_pose_cap=1`), against a control at
  the default cap in which the same row forms -- so "capped" is not how that
  row always ends.
* `decaps.max_distance_mm = 3`: splitflap and watchy claim > 0 caps at a
  supply pin (#1053; both claimed 0 before stage 2.4), and the forced 0-claim
  case (the only cap's owner is not U-prefixed) returns the reason and prints
  the note.
* fixed poses (#1054): seated EXACTLY, stamped `(locked yes)`, and unmoved by
  `place_seed --repair` and `--force` (CLI). The repair arm is not vacuous: a
  control intent WITHOUT the fixed pose moves the same part on the same board.
* an illegal fixed pose is REFUSED, never nudged: off the board (pad copper
  past the outline), colliding with an earlier fixed pose (named), and on a
  side the part is not on (no flip move). Refused refs are unseated, unwritten
  and unlocked.
* stage 1 treats a stage-0 part as an obstacle: run 27's fixture, where a
  declared south-edge header's band midpoint lands on FIX1 -- with FIX1 a
  fixed pose, the header slides clear of it (control: without the fixed pose
  the header takes the midpoint).
* an intent declaring none of `decaps.max_distance_mm`, `arrays`,
  `fixed_poses` seeds IDENTICALLY to the pre-phase-3 seeder
  (tests/fixtures/1051/seed_unarmed_baseline.json, recorded at 754e7f419).

    python3 tests/test_1051_seed_arrays.py
"""
import json
import os
import random
import re
import subprocess
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
from placement.legality import grade_pad_legality  # noqa: E402
from placement.writer import write_placed_output   # noqa: E402

RUN_ALL_TIMEOUT = 600

BOARDS = os.path.join(ROOT, 'kicad_files')
SPLITFLAP = os.path.join(BOARDS, 'splitflap_driver.kicad_pcb')
GLASGOW = os.path.join(BOARDS, 'glasgow_revC.kicad_pcb')
WATCHY = os.path.join(BOARDS, 'watchy.kicad_pcb')
ESP = os.path.join(BOARDS, 'esp_prog.kicad_pcb')
PLACE_SEED = os.path.join(ROOT, 'py_placer', 'place_seed.py')
BASELINE = os.path.join(TESTS_DIR, 'fixtures', '1051',
                        'seed_unarmed_baseline.json')
SOURCES = ('kicad', 'sheet')
CLEARANCE = 0.2

#: esp_prog's R3 and R4 are the series resistors on U1 pins 3 and 4 (U0RXD /
#: U0TXD), one 0402 footprint -- a two-member row with a served IC.
ESP_ROW = {'name': 'u1_uart', 'members': ['R4', 'R3'], 'serves': 'U1',
           'order': 'pin', 'rotation': 'shared', 'pitch_mm': 'auto',
           'axis': 'auto', 'why': 'test row'}


def _intent(doc, td, name='intent.json'):
    path = os.path.join(td, name)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    return fp.load_intent(path), path


def _seed(board, intent, seed='0', **kw):
    pcb = parse_kicad_pcb(board)
    res = seeder.seed_from_intent(pcb, board, intent, random.Random(seed),
                                  group_sources=SOURCES, clearance=CLEARANCE,
                                  **kw)
    return pcb, res


def _write(board, res, td, name):
    out = os.path.join(td, name)
    write_placed_output(board, out, res['placements'])
    return out


def _graded_rows(intent, out):
    """{name: array_measured row} from the GRADER on the written board."""
    g = fp.grade(intent, parse_kicad_pcb(out), out, group_sources=SOURCES,
                 clearance=CLEARANCE)
    return {str(a['name']): a for a in g.array_measured}


def _check_row(pcb, res, name, out, graded):
    """The row `name` is formed by the seeder AND the grader, lies in its pin
    order, at one rotation, and every member is legal against its siblings
    at the WRITTEN poses."""
    rec = res['arrays_formed'].get(name)
    assert rec is not None, (name, res['array_unseated'].get(name))
    assert rec['verdict'] == 'formed', rec
    assert graded[name]['formed'] is True, graded[name]
    members = rec['members']
    exp = graded[name].get('order_expected')
    if exp:
        seen = [m for m in members if m in exp]
        assert seen in (exp, list(reversed(exp))), (members, exp)
    written = parse_kicad_pcb(out)
    rots = {round((written.footprints[m].rotation or 0.0) % 360.0, 6)
            for m in members}
    assert len(rots) == 1 and next(iter(rots)) == rec['rot'] % 360.0, rots
    import pose_score
    st = pose_score.make_state(written, out, clearance=CLEARANCE)
    others = set(st.parts) - set(members)
    for m in members:
        p = st.parts[m]
        assert seeder.pose_ok(st, m, p.x, p.y, p.rot, others), (
            f"{m} is not legal against its siblings at its written pose")
    # The pitch clears the board clearance between neighbours.
    b = st.parts[members[0]].rect(0.0, 0.0, rec['rot'])
    ext = (b[2] - b[0]) if rec['axis'] == 'x' else (b[3] - b[1])
    assert rec['pitch_mm'] >= ext + CLEARANCE, (rec['pitch_mm'], ext)
    return rec


def test_splitflap_u4_row_is_formed():
    with tempfile.TemporaryDirectory() as td:
        pcb = parse_kicad_pcb(SPLITFLAP)
        doc = fp.emit_intent(pcb, SPLITFLAP, derive_arrays='auto')
        names = [a['name'] for a in doc['arrays']]
        assert 'U4:47k' in names, names
        intent, _p = _intent(doc, td)
        pcb, res = _seed(SPLITFLAP, intent)
        out = _write(SPLITFLAP, res, td, 'sf.kicad_pcb')
        graded = _graded_rows(intent, out)
        rec = _check_row(pcb, res, 'U4:47k', out, graded)
        assert sorted(rec['members']) == sorted(
            next(a['members'] for a in doc['arrays']
                 if a['name'] == 'U4:47k'))
        assert not res['unseated'], res['unseated']
        # The seeder's self-check and the grader agree on every row.
        for n, r in res['arrays_formed'].items():
            assert (r['verdict'] == 'formed') == bool(graded[n]['formed']), n
    print(f"  PASS: splitflap U4:47k is one row along {rec['axis']} at "
          f"{rec['rot']:g}deg, pitch {rec['pitch_mm']}mm, in U4's pin order, "
          f"after {rec['poses_tried']} pose(s); the grader agrees on all "
          f"{len(res['arrays_formed'])} seated rows")


def test_glasgow_resistor_pair_and_buffer_bank_are_formed():
    with tempfile.TemporaryDirectory() as td:
        pcb = parse_kicad_pcb(GLASGOW)
        doc = fp.emit_intent(pcb, GLASGOW, derive_arrays='auto')
        intent, _p = _intent(doc, td)
        pcb, res = _seed(GLASGOW, intent)
        out = _write(GLASGOW, res, td, 'gl.kicad_pcb')
        graded = _graded_rows(intent, out)
        pair = _check_row(pcb, res, 'U30:33R~2', out, graded)
        assert sorted(pair['members']) == ['RN7', 'RN8'], pair['members']
        bank = _check_row(pcb, res, 'U30:SN74LVC1T45DCKR~2', out, graded)
        assert len(bank['members']) == 8, bank['members']
        n_formed = sum(1 for r in res['arrays_formed'].values()
                       if r['verdict'] == 'formed')
    print(f"  PASS: glasgow RN7+RN8 and the 8-buffer bank are formed rows "
          f"(grader agrees); {n_formed} of {len(doc['arrays'])} detected "
          f"rows formed, {len(res['array_unseated'])} not seated as rows")


def test_unseatable_row_is_disclosed_and_falls_through():
    with tempfile.TemporaryDirectory() as td:
        doc = fp.emit_intent(parse_kicad_pcb(ESP), ESP)
        doc['arrays'] = [dict(ESP_ROW, pitch_mm=0.3)]
        intent, _p = _intent(doc, td)
        pcb, res = _seed(ESP, intent)
        un = res['array_unseated'].get('u1_uart')
        assert un is not None and not res['arrays_formed'], res
        assert 'pitch 0.3mm is below the courtyard extent' in un['reason'], un
        assert un['capped'] is False and un['poses_tried'] == 0, un
        written = {p['reference'] for p in res['placements']}
        assert {'R3', 'R4'} <= written, written
        assert not {'R3', 'R4'} & set(res['unseated']), res['unseated']
        assert any('array u1_uart: NOT seated as a row' in n
                   for n in res['notes']), res['notes']
    print(f"  PASS: a row at a pitch below its courtyard is disclosed "
          f"({un['reason'][:60]}...) and R3/R4 are seated one by one")


def test_pose_cap_trips_and_says_so():
    with tempfile.TemporaryDirectory() as td:
        doc = fp.emit_intent(parse_kicad_pcb(ESP), ESP)
        doc['arrays'] = [dict(ESP_ROW)]
        intent, _p = _intent(doc, td)
        # CONTROL first: at the default cap the same row forms, so "capped"
        # below is the cap's doing and not the row's fate.
        _pcb, ok = _seed(ESP, intent)
        rec = ok['arrays_formed'].get('u1_uart')
        assert rec is not None and rec['verdict'] == 'formed', ok
        assert rec['poses_tried'] > 1, rec
        _pcb, res = _seed(ESP, intent, array_pose_cap=1)
        un = res['array_unseated'].get('u1_uart')
        assert un is not None, res['arrays_formed']
        assert un['capped'] is True and un['poses_tried'] == 1, un
        assert 'the pose cap (1) was reached' in un['reason'], un
        assert any('pose cap (1)' in n for n in res['notes'])
        assert not {'R3', 'R4'} & set(res['unseated'])
    print(f"  PASS: cap 1 trips after 1 pose and says so; the default cap "
          f"forms the same row after {rec['poses_tried']} pose(s)")


def test_decaps_armed_claims_caps_on_splitflap_and_watchy():
    got = {}
    with tempfile.TemporaryDirectory() as td:
        for board in (SPLITFLAP, WATCHY):
            doc = fp.emit_intent(parse_kicad_pcb(board), board)
            doc['decaps'] = dict(doc.get('decaps') or {}, max_distance_mm=3.0)
            intent, _p = _intent(doc, td, os.path.basename(board) + '.json')
            _pcb, res = _seed(board, intent)
            ds = res['decap_stage']
            assert ds['armed'] and ds['scope'] > 0, ds
            assert ds['claimed'] > 0, ds
            assert ds['served_first'], ds
            got[os.path.basename(board)] = (ds['claimed'], ds['scope'])
    print(f"  PASS: with max_distance_mm 3 the pin stage claims caps "
          f"(claimed, scope): {got}")


def test_zero_claim_reports_why():
    import test_792_decap_seeding as t792
    with tempfile.TemporaryDirectory() as wd:
        # Only C3 in scope; its owner IC1 is not U-prefixed, so neither 2.4
        # nor 2.5 treats it as an owner (decap_owner_chips is off).
        res, _poses, _pcb = t792._seed(
            wd, {'max_distance_mm': 3.0, 'exempt': ['C1', 'C2', 'C5']})
        ds = res['decap_stage']
        assert ds['armed'] and ds['scope'] == 1 and ds['claimed'] == 0, ds
        assert 'pins 0' in (ds['reason'] or ''), ds
        note = [n for n in res['notes'] if n.startswith('decap stage 2.5:')]
        assert note and '1 cap(s) in scope, 0 claimed' in note[0], res['notes']
    print(f"  PASS: a non-empty scope claiming 0 says why: {ds['reason']}")


def _summary(r):
    m = re.search(r'^JSON_SUMMARY: (.*)$', r.stdout, re.M)
    assert m, r.stdout[-1500:]
    return json.loads(m.group(1))


def _run_seed(args):
    r = subprocess.run([sys.executable, '-X', 'utf8', PLACE_SEED] + args,
                       capture_output=True, text=True, encoding='utf-8',
                       errors='replace', cwd=ROOT, timeout=600)
    out = r.stdout + r.stderr
    assert 'Traceback' not in out, out[-2000:]
    # 0, or 4 for a grade finding on this board -- never an argparse or
    # load failure. The fixed-pose contract is read off the summary and the
    # written file, not off the exit code.
    assert r.returncode in (0, 4), (r.returncode, out[-2000:])
    return r


def _fp_pose(path, ref):
    f = parse_kicad_pcb(path).footprints[ref]
    return (round(f.x, 3), round(f.y, 3), round((f.rotation or 0.0) % 360, 3),
            bool(f.locked))


def test_fixed_pose_exact_locked_and_survives_repair_and_force():
    from placement.portfolio import copy_siblings
    with tempfile.TemporaryDirectory() as td:
        doc = fp.emit_intent(parse_kicad_pcb(ESP), ESP)
        # R1 at its own (human) pose: small, so the repair control below has
        # room to move it -- a large part on this dense board has none.
        fixed = {'ref': 'R1', 'x': 136.4, 'y': 98.8, 'rot': 270, 'side': 'F',
                 'basis': 'declared', 'why': 'test datum'}
        doc_fixed = dict(doc, fixed_poses=[fixed])
        _i, ip = _intent(doc_fixed, td, 'fixed.json')
        _i, ip_ctl = _intent(doc, td, 'control.json')
        seeded = os.path.join(td, 'seeded.kicad_pcb')
        s = _summary(_run_seed([ESP, seeded, '--intent', ip, '--force',
                                '--clearance', str(CLEARANCE)]))
        assert s['fixed_seated']['R1']['how'] == 'contained', s['fixed_seated']
        assert s['fixed_seated']['R1']['at_written_pose'] is True
        assert _fp_pose(seeded, 'R1') == (136.4, 98.8, 270.0, True), \
            _fp_pose(seeded, 'R1')

        # --force on the seeded board: R1 is file-locked AT its pose.
        forced = os.path.join(td, 'forced.kicad_pcb')
        s = _summary(_run_seed([seeded, forced, '--intent', ip, '--force',
                                '--clearance', str(CLEARANCE)]))
        assert s['fixed_seated']['R1']['how'] == 'already_there', s
        assert _fp_pose(forced, 'R1') == (136.4, 98.8, 270.0, True)

        # --repair, with a real violation ON R1: C3 dropped onto it, the
        # stamp on R1 REMOVED (so the file lock is not what protects it) and
        # C3 locked (so the pair's only mover is R1). The control intent,
        # without the fixed pose, must move R1 -- or this arm is vacuous.
        bad = os.path.join(td, 'bad.kicad_pcb')
        write_placed_output(seeded, bad, [{'reference': 'C3', 'new_x': 136.4,
                                           'new_y': 98.8,
                                           'new_rotation': 270.0}])
        copy_siblings(seeded, bad)
        assert seeder.stamp_unlocked(bad, ['R1']) == 1
        seeder.stamp_locked(bad, ['C3'])
        assert _fp_pose(bad, 'R1')[3] is False
        ctl = os.path.join(td, 'repair_ctl.kicad_pcb')
        _run_seed([bad, ctl, '--intent', ip_ctl, '--repair',
                   '--clearance', str(CLEARANCE)])
        assert _fp_pose(ctl, 'R1')[:3] != (136.4, 98.8, 270.0), (
            "control: the repair did not move R1 without the fixed pose, so "
            "the fixed-pose arm below would prove nothing")
        rep = os.path.join(td, 'repair.kicad_pcb')
        _run_seed([bad, rep, '--intent', ip, '--repair',
                   '--clearance', str(CLEARANCE)])
        assert _fp_pose(rep, 'R1')[:3] == (136.4, 98.8, 270.0), \
            _fp_pose(rep, 'R1')
        # And the stamped board is untouched by --repair too.
        rep2 = os.path.join(td, 'repair2.kicad_pcb')
        _run_seed([seeded, rep2, '--intent', ip, '--repair',
                   '--clearance', str(CLEARANCE)])
        assert _fp_pose(rep2, 'R1') == (136.4, 98.8, 270.0, True)
    print("  PASS: R1 seated exactly and stamped; --force keeps it "
          "(already_there); --repair leaves it, stamped or not, where the "
          "control intent moves it")


def test_illegal_fixed_pose_is_refused_not_nudged():
    with tempfile.TemporaryDirectory() as td:
        doc = fp.emit_intent(parse_kicad_pcb(ESP), ESP)
        doc['fixed_poses'] = [
            {'ref': 'R1', 'x': 100.0, 'y': 100.0, 'rot': 0,
             'basis': 'declared', 'why': 'off the board'},
            {'ref': 'C1', 'x': 138.46, 'y': 96.23, 'rot': 90,
             'basis': 'declared', 'why': 'legal'},
            {'ref': 'C3', 'x': 138.46, 'y': 96.23, 'rot': 90,
             'basis': 'declared', 'why': 'on top of C1'},
            {'ref': 'R2', 'x': 136.4, 'y': 101.6, 'rot': 90, 'side': 'B',
             'basis': 'declared', 'why': 'wrong side'},
        ]
        intent, _p = _intent(doc, td)
        pcb, res = _seed(ESP, intent)
        ref_ = res['fixed_refused']
        assert set(ref_) == {'R1', 'C3', 'R2'}, ref_
        assert 'past the outline' in ref_['R1']['reason'], ref_['R1']
        assert 'C1' in ref_['C3']['reason'], ref_['C3']
        assert 'no flip move' in ref_['R2']['reason'], ref_['R2']
        assert res['fixed_seated']['C1']['how'] == 'contained'
        written = {p['reference']: p for p in res['placements']}
        assert (written['C1']['new_x'], written['C1']['new_y'],
                written['C1']['new_rotation']) == (138.46, 96.23, 90.0)
        for r in ('R1', 'C3', 'R2'):
            assert r in res['unseated'], (r, res['unseated'])
            assert r not in written, r
            assert r not in res['lock_refs'], r
        assert 'C1' in res['lock_refs']
        assert sum('REFUSED' in n for n in res['notes']) == 3, res['notes']
    print("  PASS: off-board, colliding (names C1) and wrong-side fixed poses "
          "are refused, unseated, unwritten and unlocked; C1 is exact and "
          "locked")


def test_stage1_treats_a_stage0_part_as_an_obstacle():
    import test_run27_edge_seat_clears_placed as t27
    with tempfile.TemporaryDirectory() as td:
        path = t27._board(td, 'b.kicad_pcb', locked=False)
        base = dict(t27.INTENT)

        def seed(doc):
            pcb = parse_kicad_pcb(path)
            res = seeder.seed_from_intent(
                pcb, path, fp.intent_from_dict(doc, path),
                random.Random('27'), group_sources=(), clearance=0.2,
                board_edge_clearance=0.3, grid_step=0.1)
            out = os.path.join(td, 'o.kicad_pcb')
            write_placed_output(path, out, res['placements'])
            pose = {p['reference']: (round(p['new_x'], 3),
                                     round(p['new_y'], 3))
                    for p in res['placements']}
            return res, pose, grade_pad_legality(parse_kicad_pcb(out), 0.2,
                                                 pcb_file=out)

        # CONTROL: FIX1 in the pile, so the header takes the band midpoint --
        # exactly where FIX1's fixed pose will be.
        _r, ctl, _g = seed(base)
        assert abs(ctl['J1'][0] - 15.0) < 0.5, ctl['J1']
        doc = dict(base, fixed_poses=[{'ref': 'FIX1', 'x': 15.0, 'y': 18.4,
                                       'rot': 0, 'basis': 'declared',
                                       'why': 'datum'}])
        res, pose, g = seed(doc)
        assert pose['FIX1'] == (15.0, 18.4), pose['FIX1']
        assert 'FIX1' in res['fixed_seated'], res['fixed_refused']
        assert g['pad_conflicts'] == 0, g
        assert abs(pose['J1'][0] - 15.0) > 1.0, pose['J1']
    print(f"  PASS: with FIX1 seated at stage 0 the header slides to "
          f"x={pose['J1'][0]} (control: {ctl['J1'][0]}), no pad conflict")


def test_unarmed_seeds_are_identical_to_the_pre_phase3_seeder():
    with open(BASELINE, encoding='utf-8') as fh:
        base = json.load(fh)['runs']
    boards = {'watchy': WATCHY, 'esp_prog': ESP}
    n = 0
    with tempfile.TemporaryDirectory() as td:
        for key, want in sorted(base.items()):
            board, s = key.split(':')
            path = boards[board]
            doc = fp.emit_intent(parse_kicad_pcb(path), path)
            assert not doc.get('arrays') and not doc.get('fixed_poses')
            assert (doc.get('decaps') or {}).get('max_distance_mm') is None
            intent, _p = _intent(doc, td, f'{board}.json')
            _pcb, res = _seed(path, intent, seed=s)
            got = {p['reference']: [p['new_x'], p['new_y'],
                                    p['new_rotation'], p.get('new_side')]
                   for p in res['placements']}
            assert got == want['placements'], (
                key, sorted(r for r in set(got) | set(want['placements'])
                            if got.get(r) != want['placements'].get(r)))
            assert res['unseated'] == want['unseated'], key
            assert res['lock_refs'] == want['lock_refs'], key
            assert res['decap_stage']['armed'] is False
            assert not res['arrays_formed'] and not res['fixed_seated']
            n += len(got)
    print(f"  PASS: {len(base)} unarmed seeds ({n} placements) are identical "
          f"to the pre-phase-3 seeder's")


TESTS = [
    test_splitflap_u4_row_is_formed,
    test_glasgow_resistor_pair_and_buffer_bank_are_formed,
    test_unseatable_row_is_disclosed_and_falls_through,
    test_pose_cap_trips_and_says_so,
    test_decaps_armed_claims_caps_on_splitflap_and_watchy,
    test_zero_claim_reports_why,
    test_fixed_pose_exact_locked_and_survives_repair_and_force,
    test_illegal_fixed_pose_is_refused_not_nudged,
    test_stage1_treats_a_stage0_part_as_an_obstacle,
    test_unarmed_seeds_are_identical_to_the_pre_phase3_seeder,
]


if __name__ == '__main__':
    only = sys.argv[1:]
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        print(f"--- {t.__name__}")
        t()
    print('ALL PASS')
