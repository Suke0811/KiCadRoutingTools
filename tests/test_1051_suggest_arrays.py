#!/usr/bin/env python3
"""#1051 phase 2: the array DETECTOR -- it suggests, it is pose-blind, and
what it suggests on the real boards is pinned against their real nets.

What each case pins, and why:

* glasgow_revC: the 33R resistor arrays split into PAIRS by channel -- RN7+
  RN8 (IO_Buffer_A) and RN1+RN2 (IO_Buffer_B) each on four balls of U30,
  RN9+RN10 / RN3+RN4 on connectors J2 / J3. The issue's "RN1-4 & RN7-10
  serving U30" is NOT what the nets say: RN3/4/9/10 reach U30 only through
  the SN74LVC1T45 buffers. The 17 buffers meet `pin_run` on U30 (pin 5, the
  DAx/DBx bus) as 8 + 8 by sheet; U32 is the 17th, alone on the top sheet
  on a different net, and is suggested nowhere.
* splitflap: the seven 47k resistors, each on its own pin of U4, in U4's
  pin order (pads 3, 4, 10, 11, 12, 13, 14).
* ulx3s: the 549R resistors on U1 split by sheet into the eight LED
  resistors (blinkey), three analog and two GPDI -- 13 on U1, not the 17 a
  count of "shares any net with U1" gives (that count includes +3V3/GND).
* a negative control that cannot pass vacuously: the same synthetic parts
  give no suggestion without a common part, and one WITH it.
* pose-blindness: identical output after every footprint pose and pad
  position is randomised in memory -- and `groups.chip_refs`, which DOES read
  poses, changes on the same randomised board, so the shuffle was strong
  enough to move a pose-reading predicate.
* `array_formation` on the HUMAN glasgow for the detected rows (count
  reported), every resistor-array row formed, and one shuffled member fails.
* `emit_intent`: the default writes no `arrays`; `'auto'` writes them with a
  `why` naming the criterion and no evidence bulk, and round-trips through
  `load_intent` and `grade` with no array_unresolved / array_conflict.
* the CLI: `--suggest-arrays` stdout is bare JSON equal to the in-process
  answer, and it refuses to run with `--intent`, for its stated reason.

    python3 tests/test_1051_suggest_arrays.py
"""
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kicad_parser import parse_kicad_pcb           # noqa: E402
from placement import arrays as arr                # noqa: E402
from placement import floorplan as fp              # noqa: E402
from placement import groups as groups_mod         # noqa: E402
from run_utils import check                        # noqa: E402

RUN_ALL_TIMEOUT = 900

GLASGOW = os.path.join(ROOT, 'kicad_files', 'glasgow_revC.kicad_pcb')
SPLITFLAP = os.path.join(ROOT, 'kicad_files', 'splitflap_driver.kicad_pcb')
ULX3S = os.path.join(ROOT, 'kicad_files', 'ulx3s.kicad_pcb')
CHECK_FLOORPLAN = os.path.join(ROOT, 'py_tools', 'check_floorplan.py')

BUFFERS_A = ['U4', 'U6', 'U9', 'U10', 'U11', 'U16', 'U17', 'U18']
BUFFERS_B = ['U22', 'U23', 'U24', 'U25', 'U26', 'U27', 'U28', 'U29']

_PCB = {}
_SUG = {}


def _pcb(path):
    if path not in _PCB:
        _PCB[path] = parse_kicad_pcb(path)
    return _PCB[path]


def _sug(path):
    if path not in _SUG:
        _SUG[path] = arr.suggest_arrays(_pcb(path))
    return _SUG[path]


def _by_members(cands, members):
    want = set(members)
    hit = [c for c in cands if set(c['members']) == want]
    assert len(hit) == 1, (f"expected one candidate with members "
                           f"{sorted(want)}, got {len(hit)}: "
                           f"{[c['members'] for c in cands]}")
    return hit[0]


def _no_part_twice(cands):
    seen = {}
    for c in cands:
        for m in c['members']:
            assert m not in seen, (f"{m} is in {seen[m]!r} AND "
                                   f"{c['name']!r}: a part is in at most "
                                   f"one candidate")
            seen[m] = c['name']
    names = [c['name'] for c in cands]
    assert len(names) == len(set(names)), f"duplicate names: {names}"


def _shape_ok(c):
    for k in ('name', 'members', 'serves', 'order', 'rotation', 'pitch_mm',
              'axis', 'criterion', 'evidence'):
        assert k in c, f"{c.get('name')}: missing key {k!r}"
    assert c['criterion'] in arr.CRITERIA
    assert c['order'] in arr.ORDERS
    assert (c['rotation'], c['pitch_mm'], c['axis']) == ('shared', 'auto',
                                                         'auto')
    assert len(c['members']) >= arr.MIN_MEMBERS


def test_glasgow_resistor_arrays_and_buffers():
    cands = _sug(GLASGOW)
    for c in cands:
        _shape_ok(c)
    _no_part_twice(cands)

    # The two resistor arrays per channel that reach U30 directly.
    b = _by_members(cands, ['RN1', 'RN2'])
    a = _by_members(cands, ['RN7', 'RN8'])
    for c, sheet_nets in ((b, ('/IO_Banks/QB0', '/IO_Banks/QB7')),
                          (a, ('/IO_Banks/QA0', '/IO_Banks/QA7'))):
        assert c['criterion'] == 'pin_run' and c['serves'] == 'U30', c
        # U30 is a BGA: its ball names do not order a row (GRID_ORDER_NOTE).
        assert c['order'] == 'unknown', c['order']
        assert c['evidence']['host_pads'] == 'grid'
        nets = {ln['net'] for m in c['members']
                for ln in c['evidence']['links'][m]}
        assert set(sheet_nets) <= nets and len(nets) == 8, sorted(nets)
    assert b['evidence']['links']['RN1'] == [
        {'net': '/IO_Banks/QB0', 'pad': 'B11', 'member_pad': '1'},
        {'net': '/IO_Banks/QB1', 'pad': 'C11', 'member_pad': '2'},
        {'net': '/IO_Banks/QB2', 'pad': 'D10', 'member_pad': '3'},
        {'net': '/IO_Banks/QB3', 'pad': 'D11', 'member_pad': '4'}], \
        b['evidence']['links']['RN1']

    # The other two 33R arrays per channel reach U30 only THROUGH the
    # buffers; the part they each land on directly is a connector.
    for members, host in ((['RN3', 'RN4'], 'J3'), (['RN9', 'RN10'], 'J2')):
        c = _by_members(cands, members)
        assert c['criterion'] == 'pin_run' and c['serves'] == host, c
        assert c['order'] == 'pin' and c['evidence']['host_pads'] == \
            'numbered'

    # The 17 SN74LVC1T45: 8 + 8 on U30 by channel; U32 nowhere.
    for bank in (BUFFERS_A, BUFFERS_B):
        c = _by_members(cands, bank)
        assert c['criterion'] == 'pin_run' and c['serves'] == 'U30', c
        pads = {ln['member_pad'] for m in c['members']
                for ln in c['evidence']['links'][m]}
        assert pads == {'5'}, f"each buffer reaches U30 by pin 5: {pads}"
    assert not any('U32' in c['members'] for c in cands), \
        "U32 is the lone buffer on the top sheet and is no row's member"
    # Nothing without a net (fiducials) nor on shared nets only (mounting
    # holes: GND) is ever a member.
    fps = _pcb(GLASGOW).footprints
    for c in cands:
        for m in c['members']:
            assert 'Fiducial' not in fps[m].footprint_name
            assert 'MountingHole' not in fps[m].footprint_name
    print(f"  PASS: glasgow {len(cands)} suggestions; RN1+RN2 and RN7+RN8 "
          f"on U30, RN3+RN4 on J3, RN9+RN10 on J2, buffers 8+8 on U30, U32 "
          f"none")


def test_splitflap_pullups_in_u4_pin_order():
    c = _by_members(_sug(SPLITFLAP), ['R6', 'R7', 'R8', 'R9', 'R11', 'R12',
                                      'R14'])
    assert c['criterion'] == 'pin_run' and c['serves'] == 'U4', c
    assert c['order'] == 'pin'
    assert c['members'] == ['R11', 'R12', 'R14', 'R6', 'R7', 'R8', 'R9'], \
        c['members']
    pads = [c['evidence']['links'][m][0]['pad'] for m in c['members']]
    assert pads == ['3', '4', '10', '11', '12', '13', '14'], pads
    # R14 is a pull-DOWN: its GND is excluded as a rail, its signal decides.
    assert c['evidence']['links']['R14'] == [
        {'net': '/SENSOR_IN', 'pad': '10', 'member_pad': '1'}]
    # The members ARE the grader's pin order, so a suggestion and its grade
    # cannot disagree about it.
    assert arr.pin_order(_pcb(SPLITFLAP), 'U4', c['members'])[0] == \
        c['members']
    _no_part_twice(_sug(SPLITFLAP))
    print("  PASS: splitflap 47k x7 -> U4 pads 3,4,10..14 in pin order")


def test_ulx3s_549r_on_u1():
    cands = _sug(ULX3S)
    _no_part_twice(cands)
    led = _by_members(cands, ['R41', 'R42', 'R43', 'R44', 'R45', 'R46',
                              'R47', 'R48'])
    analog = _by_members(cands, ['R15', 'R19', 'R58'])
    gpdi = _by_members(cands, ['R61', 'R67'])
    on_u1 = []
    for c in (led, analog, gpdi):
        assert c['criterion'] == 'pin_run' and c['serves'] == 'U1', c
        assert c['evidence']['value'] == '549'
        on_u1 += c['members']
    assert len(on_u1) == 13
    all549 = {m for c in cands if c['evidence']['value'] == '549'
              for m in c['members']}
    assert all549 == set(on_u1), sorted(all549 - set(on_u1))
    # R36's only net no other 549R has is GND: excluded as a rail, so it is
    # not a "member" of U1's LED bank.
    assert 'R36' not in all549
    print(f"  PASS: ulx3s 549R -> U1 as 8 (blinkey) + 3 (analog) + 2 (gpdi) "
          f"= 13; {len(cands)} suggestions in all")


def _synthetic(with_host: bool):
    """Three identical 10k resistors, each between two private nets. The
    far ends reach three DIFFERENT two-pad parts, so there is no shared
    part and no repeated shape; `with_host` lands each one's first pad on
    its own pin of one 8-pin IC instead."""
    nets, fps = {}, {}

    def pad(ref, num, net_id, x=0.0):
        p = SimpleNamespace(pad_number=str(num), net_id=net_id,
                            component_ref=ref, layers=['F.Cu'],
                            local_x=x, local_y=float(num), global_x=x,
                            global_y=float(num), pintype='', pinfunction='')
        if net_id:
            nets.setdefault(net_id, SimpleNamespace(
                name=f'/N{net_id}', pads=[])).pads.append(p)
        return p

    def part(ref, fpname, value, pads):
        fps[ref] = SimpleNamespace(reference=ref, footprint_name=fpname,
                                   value=value, sheet_path='/root/' + ref,
                                   pads=pads, locked=False, x=0.0, y=0.0,
                                   rotation=0.0)

    others = [('C9', 'C_0402', '1u'), ('D9', 'D_SOD323', 'BAT'),
              ('L9', 'L_0603', '1uH')]
    for i, (oref, ofp, oval) in enumerate(others):
        a, b = 10 + 2 * i, 11 + 2 * i
        part(f'R{i + 1}', 'R_0402', '10k', [pad(f'R{i + 1}', 1, a),
                                            pad(f'R{i + 1}', 2, b)])
        # Each R's far end on a different kind of part: no repeated shape.
        part(oref, ofp, oval, [pad(oref, 1, b), pad(oref, 2, 0)])
        if not with_host:
            part(f'X{i}', f'SOT23_{i}', f'Q{i}',
                 [pad(f'X{i}', 1, a), pad(f'X{i}', 2, 0)])
    if with_host:
        part('U1', 'SOIC-8', 'MCU',
             [pad('U1', n, 10 + 2 * (n - 1) if n <= 3 else 0,
                  x=(0.0 if n <= 4 else 5.0)) for n in range(1, 9)])
    return SimpleNamespace(footprints=fps, nets=nets)


def test_negative_control_no_common_part_no_suggestion():
    neg = arr.suggest_arrays(_synthetic(False))
    assert neg == [], f"no common part, no repeated shape -> none: {neg}"
    pos = arr.suggest_arrays(_synthetic(True))
    assert len(pos) == 1 and pos[0]['serves'] == 'U1' and \
        pos[0]['members'] == ['R1', 'R2', 'R3'], pos
    print("  PASS: the same three 10k give nothing without U1, one "
          "pin_run with it (the control is not vacuous)")


def _randomise(pcb, seed):
    rng = random.Random(seed)
    for f in pcb.footprints.values():
        f.x = rng.uniform(-500, 500)
        f.y = rng.uniform(-500, 500)
        f.rotation = rng.uniform(0, 360)
        for p in f.pads:
            p.global_x = rng.uniform(-500, 500)
            p.global_y = rng.uniform(-500, 500)
            if hasattr(p, 'rect_rotation'):
                p.rect_rotation = rng.uniform(-89, 89)
    return pcb


def test_pose_blind():
    for path in (GLASGOW, SPLITFLAP, ULX3S):
        base = _sug(path)
        shuffled = _randomise(copy.deepcopy(_pcb(path)), 1051)
        # The shuffle is strong enough to move a predicate that DOES read
        # poses: `chip_refs`' row test reads global pad coordinates.
        assert groups_mod.chip_refs(shuffled) != groups_mod.chip_refs(
            _pcb(path)), f"{path}: the shuffle moved nothing pose-read"
        assert arr.pose_free_chip_refs(shuffled) == \
            arr.pose_free_chip_refs(_pcb(path))
        got = arr.suggest_arrays(shuffled)
        assert json.dumps(got, sort_keys=True) == json.dumps(
            base, sort_keys=True), f"{os.path.basename(path)}: suggestions " \
            f"moved with the poses"
    print("  PASS: identical suggestions on 3 boards with every pose "
          "randomised (and chip_refs, which reads poses, did change)")


def _grade_auto(pcb, path):
    doc = fp.emit_intent(pcb, path, derive_arrays='auto')
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'intent.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh)
        intent = fp.load_intent(p)
    return doc, intent, fp.grade(intent, pcb, path)


def test_formation_on_the_human_glasgow():
    """The human rows, graded by the ONE predicate at DEFAULT_TOLERANCES.

    Measured here (and why no tolerance moved): of the 27 rows the auto
    intent declares, 15 are formed. Every failure is a real non-row: the
    smallest failing axis offset is 0.65mm (J1:5k1, R52/R53), the rest
    fail on 90-degree rotation splits or multi-mm pitch gaps, and the
    buffer banks are 2x4 GRIDS (two columns 4.0mm apart) that a row
    schema cannot express. No failure is within a tolerance of passing.
    """
    pcb = _pcb(GLASGOW)
    doc, intent, res = _grade_auto(pcb, GLASGOW)
    meas = {m['name']: m for m in res.array_measured}
    assert len(meas) == len(doc['arrays']) == 27, len(meas)
    formed = sorted(n for n, m in meas.items() if m.get('formed'))
    print(f"  human glasgow: {len(formed)} of {len(meas)} detected rows "
          f"formed")
    assert len(formed) >= 15, formed
    by = {tuple(sorted(a['members'])): a['name'] for a in doc['arrays']}
    for pair in (('RN1', 'RN2'), ('RN3', 'RN4'), ('RN5', 'RN6'),
                 ('RN7', 'RN8'), ('RN10', 'RN9'), ('RN11', 'RN12')):
        assert meas[by[pair]]['formed'] is True, (pair, meas[by[pair]])
    for bank in (BUFFERS_A, BUFFERS_B):
        m = meas[by[tuple(sorted(bank))]]
        assert m['formed'] is False and 'axis' in m['failed'], m

    # One member shuffled: the row it belonged to fails, on the axis.
    moved = copy.deepcopy(pcb)
    f = moved.footprints['RN2']
    f.x += 1.5
    for p in f.pads:
        p.global_x += 1.5
    res2 = fp.grade(intent, moved, GLASGOW)
    m2 = {m['name']: m for m in res2.array_measured}[by[('RN1', 'RN2')]]
    assert m2['formed'] is False and 'axis' in m2['failed'], m2
    assert any(v.rule == 'array_formation' and v.block == by[('RN1', 'RN2')]
               for v in res2.violations)
    print(f"  PASS: every R-array row formed on the human board; RN2 moved "
          f"1.5mm -> {by[('RN1', 'RN2')]!r} fails {m2['failed']}")


def test_emit_intent_default_unchanged_and_auto_round_trips():
    pcb = _pcb(SPLITFLAP)
    d0 = fp.emit_intent(pcb, SPLITFLAP)
    d1 = fp.emit_intent(pcb, SPLITFLAP, derive_arrays='off')
    assert json.dumps(d0, sort_keys=True) == json.dumps(d1, sort_keys=True)
    assert 'arrays' not in d0 and 'arrays_note' not in d0['context']
    try:
        fp.emit_intent(pcb, SPLITFLAP, derive_arrays='on')
    except ValueError as exc:
        assert "expected 'off' or 'auto'" in str(exc), exc
    else:
        raise AssertionError("derive_arrays='on' must refuse")

    doc, intent, res = _grade_auto(pcb, SPLITFLAP)
    assert doc['min_reader'] >= 7
    assert doc['arrays'], 'auto emitted no arrays on splitflap'
    for a in doc['arrays']:
        assert 'evidence' not in a and 'criterion' not in a, a
        assert a['why'].startswith('detector ') and any(
            k in a['why'] for k in arr.CRITERIA), a['why']
    # Edge connectors are dropped BY NAME, never silently.
    dropped = {d['name']: d for d in doc['context'].get('arrays_dropped')
               or ()}
    assert dropped and all(
        set(d['members'].values()) <= {'an edge_connectors entry'}
        for d in dropped.values()), dropped
    edge = {c['ref'] for c in doc['edge_connectors']}
    assert not any(m in edge for a in doc['arrays'] for m in a['members'])
    assert len(intent.arrays) == len(doc['arrays'])
    bad = [(v.rule, v.ref, v.message) for v in res.violations
           if v.rule in ('array_unresolved', 'array_conflict')]
    assert not bad, bad
    assert {m['name'] for m in res.array_measured} == \
        {a['name'] for a in doc['arrays']}
    print(f"  PASS: default emits no arrays; auto emits "
          f"{len(doc['arrays'])}, drops {len(dropped)} edge-connector rows by "
          f"name, loads and grades with no array_unresolved/conflict")


def test_cli_bare_json_and_refusal():
    r = subprocess.run([sys.executable, '-X', 'utf8', CHECK_FLOORPLAN,
                        SPLITFLAP, '--suggest-arrays'],
                       capture_output=True, text=True, encoding='utf-8',
                       cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    doc = json.loads(r.stdout)          # bare JSON: no CMD: banner line
    assert doc['pose_blind'] is True and doc['count'] == len(
        doc['suggestions'])
    assert json.dumps(doc['suggestions'], sort_keys=True) == json.dumps(
        _sug(SPLITFLAP), sort_keys=True)
    check([sys.executable, '-X', 'utf8', CHECK_FLOORPLAN, SPLITFLAP,
           '--suggest-arrays', '--intent', 'x.json'],
          refuse='--suggest-arrays runs alone', code=2, allow=('usage:',))
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 's.json')
        r = check([sys.executable, '-X', 'utf8', CHECK_FLOORPLAN, SPLITFLAP,
                   '--suggest-arrays', '--json', out], accept=True)
        assert 'array suggestion(s)' in r.stdout
        with open(out, encoding='utf-8') as fh:
            assert json.load(fh)['count'] == doc['count']
    print("  PASS: --suggest-arrays stdout is bare JSON equal to the "
          "in-process answer; --json gets the file and a summary; with "
          "--intent it refuses by reason")


TESTS = [
    test_glasgow_resistor_arrays_and_buffers,
    test_splitflap_pullups_in_u4_pin_order,
    test_ulx3s_549r_on_u1,
    test_negative_control_no_common_part_no_suggestion,
    test_pose_blind,
    test_formation_on_the_human_glasgow,
    test_emit_intent_default_unchanged_and_auto_round_trips,
    test_cli_bare_json_and_refusal,
]


if __name__ == '__main__':
    for t in TESTS:
        print(f"--- {t.__name__}")
        t()
    print('ALL PASS')
