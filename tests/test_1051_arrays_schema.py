#!/usr/bin/env python3
"""#1051 / #1052 / #1054 phase 1: the `arrays`, `fixed_poses` and
`blocks[].rigid` schema, the brief compile, the formation predicate and the
pin order.

What this pins, and why each is a separate case rather than one round trip:

* every LOAD refusal carries its REASON and names the member -- a refusal is
  not evidence on its own (a malformed fixture once "passed" against a
  message about a different key);
* the BOARD-aware findings (`array_unresolved`, `array_conflict`) are raised
  by both `grade` and `resolve_intent_gate`, each naming its member;
* "unknown" and an absent key stay two different things in the brief report;
* a reader-6 intent still loads, and a reader-7 claim refuses on an older
  build;
* `arrays.formation` fails for each of its four reasons and passes a clean
  row -- and the as-built splitflap pull-ups R6..R8 ARE a clean pin-order row
  (pins 11-13 of U4, 19.05 mm apart), which is the positive control that the
  predicate is not failing everything;
* `arrays.pin_order` on splitflap's 47k pull-ups, read off pads and nets;
* every `fixed_poses[]` entry is GRADED (#1054 correction), whatever its
  source, and a ref the mechanical file itself anchors is graded once.

    python3 tests/test_1051_arrays_schema.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kicad_parser import parse_kicad_pcb           # noqa: E402
from placement import arrays as arr                # noqa: E402
from placement import design_brief as db           # noqa: E402
from placement import floorplan as fp              # noqa: E402
from run_utils import check                        # noqa: E402

RUN_ALL_TIMEOUT = 900

SPLITFLAP = os.path.join(ROOT, 'kicad_files', 'splitflap_driver.kicad_pcb')
ESP = os.path.join(ROOT, 'kicad_files', 'esp_prog.kicad_pcb')
GLASGOW = os.path.join(ROOT, 'kicad_files', 'glasgow_revC.kicad_pcb')
ESP_BRIEF = os.path.join(ROOT, 'tests', 'fixtures', '959', 'asbuilt',
                         'esp_prog.design-brief.json')
ESP_MECH = os.path.join(ROOT, 'tests', 'fixtures', '959',
                        'run29_mechanical.json')
CHECK_FLOORPLAN = os.path.join(ROOT, 'py_tools', 'check_floorplan.py')

#: splitflap's 47k pull-ups to U4 and the U4 pad each one's own net lands
#: on (+3V3 is shared by six of them, so it orders nothing). R14 is a
#: pull-DOWN: its GND lands on U4 pads 8 and 15, its signal on pad 10 alone,
#: so the single-pad net decides.
PULLUPS = ['R6', 'R7', 'R8', 'R9', 'R11', 'R12', 'R14']
PIN_ORDER = ['R11', 'R12', 'R14', 'R6', 'R7', 'R8', 'R9']

_PCB = {}


def _pcb(path=SPLITFLAP):
    if path not in _PCB:
        _PCB[path] = parse_kicad_pcb(path)
    return _PCB[path]


def _fresh(path=SPLITFLAP):
    return parse_kicad_pcb(path)


def _base(**over):
    d = {'schema': 1, 'kind': 'floorplan-intent', 'units': 'mm'}
    d.update(over)
    return d


def _row(**over):
    r = {'name': 'pullups', 'members': ['R6', 'R7', 'R8'], 'serves': 'U4',
         'order': 'pin', 'rotation': 'shared'}
    r.update(over)
    return r


def _rejects(raw, why):
    try:
        fp.intent_from_dict(raw)
    except fp.IntentError as exc:
        msg = str(exc)
        assert why in msg, (why, msg)
        return msg
    raise AssertionError(f"NOT REFUSED, expected {why!r}: {raw!r}")


# --------------------------------------------------------------------------
# load: the schema and its refusals
# --------------------------------------------------------------------------

def test_the_new_keys_load_and_land_on_the_intent():
    raw = _base(min_reader=7,
                blocks=[{'name': 'mcu', 'refs': ['U4'], 'rigid': True},
                        {'name': 'rest', 'refs': ['C1']}],
                arrays=[_row(pitch_mm=19.05, axis='x', allow_mixed=False,
                             why='pull-ups on U4', note='n', source='brief',
                             context={'k': 'v'})],
                fixed_poses=[{'ref': 'J1', 'x': 1.0, 'y': 2.0, 'rot': 90,
                              'side': 'F', 'basis': 'declared', 'why': 'w',
                              'context': {}}])
    it = fp.intent_from_dict(raw)
    assert it.blocks[0].rigid is True and it.blocks[1].rigid is False
    assert it.arrays[0]['members'] == ['R6', 'R7', 'R8'], it.arrays
    assert it.fixed_poses[0]['ref'] == 'J1', it.fixed_poses
    # JSON round trip: the dumped document loads to the same claims.
    again = fp.intent_from_dict(json.loads(json.dumps(raw)))
    assert again.arrays == it.arrays and again.fixed_poses == it.fixed_poses
    # An intent declaring none of it behaves as before.
    plain = fp.intent_from_dict(_base())
    assert plain.arrays == () and plain.fixed_poses == ()
    assert not fp._wants(plain, 'array_formation')
    assert fp._wants(it, 'array_formation')
    print("  PASS: arrays / fixed_poses / rigid load, round-trip, and arm "
          "array_formation only when declared")


#: (raw, the reason the refusal must carry). Each names the member.
_REFUSALS = [
    (_base(arrays=[_row(members=['R6'])]), 'at least two'),
    (_base(arrays=[_row(members=['R6', 'R6'])]), 'R6 listed twice'),
    (_base(arrays=[_row(), _row(name='b', members=['R8', 'R9'])]),
     "member R8 is also in array 'pullups'"),
    (_base(arrays=[_row()], must_lock=['R*']),
     "member R6 is named by must_lock 'R*'"),
    (_base(arrays=[_row()],
           fixed_poses=[{'ref': 'R7', 'x': 0, 'y': 0, 'basis': 'declared'}]),
     'member R7 has a `fixed_poses` entry'),
    (_base(arrays=[_row()], edge_connectors=[{'ref': 'R8', 'edge': 'west'}]),
     'member R8 is also an `edge_connectors` entry'),
    (_base(arrays=[_row(serves=None)]), '`serves` is absent'),
    (_base(arrays=[_row(serves='unknown')]), '`serves` is unknown'),
    (_base(arrays=[_row(serves='R6')]), 'is a member of the row it serves'),
    (_base(arrays=[_row(order='bus')]), "order: 'bus'"),
    (_base(arrays=[_row(rotation='any')]), 'expected a number of degrees'),
    (_base(arrays=[_row(pitch_mm=0)]), "expected 'auto' or a positive"),
    (_base(arrays=[_row(axis='z')]), "axis: 'z'"),
    (_base(arrays=[_row(allow_mixed='yes')]), 'allow_mixed: expected true'),
    (_base(arrays=[_row(membres=['R1'])]), 'unknown key(s) membres'),
    (_base(arrays=[_row(), _row(members=['R9', 'R11'])]),
     "duplicate array name 'pullups'"),
    (_base(fixed_poses=[{'ref': 'J1', 'x': 0, 'y': 0}]), 'basis'),
    (_base(fixed_poses=[{'ref': 'J1', 'y': 0, 'basis': 'declared'}]),
     'needs `x`'),
    (_base(fixed_poses=[{'ref': 'J1', 'x': 0, 'y': 0, 'basis': 'declared',
                         'side': 'top'}]), "side: 'top'"),
    (_base(fixed_poses=[{'ref': 'J1', 'x': 0, 'y': 0, 'basis': 'declared'},
                        {'ref': 'J1', 'x': 1, 'y': 1, 'basis': 'declared'}]),
     'duplicate fixed pose'),
    (_base(fixed_poses=[{'ref': 'J1', 'x': 0, 'y': 0, 'basis': 'declared'}],
           edge_connectors=[{'ref': 'J1', 'edge': 'west'}]),
     'J1 is also an `edge_connectors` entry'),
    (_base(fixed_poses=[{'ref': 'MH1', 'x': 0, 'y': 0, 'basis': 'declared'}],
           must_lock=['MH*']),
     "MH1 is also named by must_lock 'MH*'"),
    (_base(fixed_poses=[{'ref': 'J1', 'x': 0, 'y': 0, 'basis': 'guess'}]),
     "basis: 'guess'"),
    (_base(blocks=[{'name': 'b', 'refs': ['U1'], 'rigid': 'yes'}]),
     "rigid 'yes'"),
    (_base(blocks=[{'name': 'fixed:U1', 'refs': ['U1']}]), 'is reserved'),
]


def test_every_load_refusal_carries_its_reason():
    for raw, why in _REFUSALS:
        _rejects(raw, why)
    print(f"  PASS: {len(_REFUSALS)} malformed arrays / fixed_poses / rigid "
          f"refused, each for its stated reason")


def test_a_reader_6_file_still_loads_and_a_reader_7_claim_refuses_old():
    assert fp.READER_VERSION == 7, fp.READER_VERSION
    fp.intent_from_dict(_base(min_reader=6,
                              blocks=[{'name': 'b', 'refs': ['U1']}]))
    saved = fp.READER_VERSION
    try:
        # A reader-6 build handed a document that says it needs reader 7.
        fp.READER_VERSION = 6
        _rejects(_base(min_reader=7, arrays=[_row()]),
                 'this build is reader 6')
    finally:
        fp.READER_VERSION = saved
    print("  PASS: a reader-6 intent loads at 7; min_reader 7 refuses on a "
          "reader-6 build")


# --------------------------------------------------------------------------
# the predicate and the pin order
# --------------------------------------------------------------------------

def _poses(spec):
    return [{'ref': r, 'x': x, 'y': y, 'rot': rot} for r, x, y, rot in spec]


def test_the_formation_predicate():
    clean = _poses([('A', 0, 0, 90), ('B', 2, 0, 90), ('C', 4, 0, 90)])
    v = arr.formation(clean, order_key=['A', 'B', 'C'],
                      rotation_spec='shared')
    assert v['formed'] and v['axis'] == 'x', v
    # Either direction along the axis is the same row.
    v = arr.formation(clean, order_key=['C', 'B', 'A'], rotation_spec=90)
    assert v['formed'], v
    # Shuffled order.
    v = arr.formation(clean, order_key=['B', 'A', 'C'])
    assert v['failed'] == ['order'], v
    # Mixed rotation, both as `shared` and against a declared angle.
    mixed = _poses([('A', 0, 0, 90), ('B', 2, 0, 0), ('C', 4, 0, 90)])
    assert arr.formation(mixed, rotation_spec='shared')['failed'] == \
        ['rotation']
    v = arr.formation(mixed, rotation_spec=90)
    assert v['failed'] == ['rotation'] and v['checks']['rotation']['off'] \
        == ['B'], v
    # Off the axis.
    off = _poses([('A', 0, 0, 0), ('B', 2, 1.0, 0), ('C', 4, 0, 0)])
    v = arr.formation(off, axis_spec='x')
    assert 'axis' in v['failed'], v
    # Uneven pitch, and a declared pitch the row does not have.
    uneven = _poses([('A', 0, 0, 0), ('B', 2, 0, 0), ('C', 7, 0, 0)])
    assert arr.formation(uneven)['failed'] == ['pitch']
    assert arr.formation(clean, pitch_spec=3.0)['failed'] == ['pitch']
    assert arr.formation(clean, pitch_spec=2.0)['formed']
    # Two members on one spot are even, and not a row.
    stacked = _poses([('A', 0, 0, 0), ('B', 0, 0, 0)])
    assert 'pitch' in arr.formation(stacked)['failed']
    # Not declared is UNCHECKED, never passed silently.
    v = arr.formation(clean)
    assert set(v['unchecked']) == {'order', 'rotation'}, v
    print("  PASS: formation passes a clean row (either direction) and fails "
          "shuffled order, mixed rotation, off-axis and uneven pitch")


def test_pin_order_is_read_off_pads_and_nets():
    order, unresolved = arr.pin_order(_pcb(), 'U4', PULLUPS)
    assert order == PIN_ORDER and not unresolved, (order, unresolved)
    # Pose-blind: shuffling every member's pose changes nothing.
    pcb = _fresh()
    for i, r in enumerate(PULLUPS):
        f = pcb.footprints[r]
        f.x, f.y, f.rotation = 10.0 * i, 3.0 * (i % 2), 90.0 * (i % 4)
    assert arr.pin_order(pcb, 'U4', PULLUPS) == (PIN_ORDER, {})
    # A member with no net of its own on the served part is unresolved,
    # named, and never ordered; an absent served part resolves nothing.
    # R5 (an LED resistor) shares no net with U4.
    _o, un = arr.pin_order(_pcb(), 'U4', ['R6', 'R5'])
    assert un == {'R5': 'shares no net with U4'} and _o == ['R6'], (_o, un)
    _o, un = arr.pin_order(_pcb(), 'ZZ9', ['R6', 'R7'])
    assert _o == [] and set(un) == {'R6', 'R7'}, un
    assert sorted(['A10', 'B1', 'A2', '10', '2'], key=arr.natural_key) == \
        ['2', '10', 'A2', 'A10', 'B1']
    print(f"  PASS: pin order {PIN_ORDER} off U4's pad numbering, identical "
          f"with every member's pose shuffled")


# --------------------------------------------------------------------------
# grade: array_formation and the board-aware findings
# --------------------------------------------------------------------------

def _grade(raw, pcb=None, **kw):
    pcb = pcb or _pcb()
    return fp.grade(fp.intent_from_dict(raw), pcb, SPLITFLAP, **kw)


def test_array_formation_grades_the_as_built_board():
    r = _grade(_base(arrays=[_row()]))
    assert 'array_formation' in r.rules_run, r.rules_run
    assert not [v for v in r.violations if v.rule.startswith('array')], \
        [v.message for v in r.violations]
    # R9 sits 66 mm further on: the pitch breaks, and the finding names it.
    r = _grade(_base(arrays=[_row(members=['R6', 'R7', 'R8', 'R9'])]))
    found = [v for v in r.violations if v.rule == 'array_formation']
    assert len(found) == 1 and found[0].block == 'pullups', found
    assert found[0].measured['failed'] == ['pitch'], found[0].measured
    # A declared order the board does not have.
    r = _grade(_base(arrays=[_row(order='declared',
                                  members=['R7', 'R6', 'R8'])]))
    found = [v for v in r.violations if v.rule == 'array_formation']
    assert found and 'order' in found[0].measured['failed'], found
    # Dark when nothing is declared.
    r = _grade(_base())
    assert r.rules_skipped.get('array_formation') == \
        'the intent declares no arrays', r.rules_skipped
    print("  PASS: R6..R8 grade as a formed pin-order row; adding R9 fails "
          "the pitch; a wrong declared order fails; dark when undeclared")


def test_board_aware_findings_name_the_member():
    pcb = _fresh()
    pcb.footprints['R7'].locked = True
    raw = _base(
        blocks=[{'name': 'z', 'refs': ['R6'], 'zone': [150, 40, 200, 50]},
                {'name': 'rot', 'refs': ['R8'], 'rotation': 90}],
        arrays=[_row(rotation=0),
                {'name': 'mixed', 'members': ['R9', 'C1', 'ZZ9'],
                 'serves': 'ZZ8', 'order': 'declared'}])
    it = fp.intent_from_dict(raw)
    blocks, _ = fp.resolve_blocks(it, pcb)
    probs = fp.array_problems(it, pcb, blocks)
    got = {(v.rule, v.ref) for v in probs}
    # R7 is locked AND outside the zone R6's block puts the row in; R8's
    # block turns it to 90 against the row's 0 AND leaves it outside the
    # zone; C1 is a capacitor in a row of resistors.
    want = {('array_unresolved', None), ('array_unresolved', 'ZZ9'),
            ('array_conflict', 'R7'), ('array_conflict', 'C1'),
            ('array_conflict', 'R8')}
    assert want <= got, sorted(got ^ want)
    msgs = ' | '.join(v.message for v in probs)
    for frag in ('member R7 is locked', 'member C1 is', "member R8's block "
                 'declares rotation 90', 'serves ZZ8', 'member ZZ9 is not on',
                 'in zoned block'):
        assert frag in msgs, (frag, msgs)
    # BOTH reach points raise them: the gate the quenching CLIs run...
    _bundle, gate_probs = fp.resolve_intent_gate(it, pcb, ())
    assert {(v.rule, v.ref) for v in gate_probs} >= want, gate_probs
    # ...and the grade (the file lock here is the in-memory one).
    r = fp.grade(it, pcb, SPLITFLAP)
    assert {(v.rule, v.ref) for v in r.violations} >= want, r.violations
    # allow_mixed lifts only the footprint finding.
    raw2 = _base(arrays=[{'name': 'mixed', 'members': ['R9', 'C1'],
                          'order': 'declared', 'allow_mixed': True}])
    it2 = fp.intent_from_dict(raw2)
    assert not fp.array_problems(it2, _pcb(), {}), 'allow_mixed ignored'
    print(f"  PASS: {len(want)} board-aware findings, each naming its member, "
          f"from both grade and resolve_intent_gate")


def test_the_gate_bundle_carries_the_new_data():
    raw = _base(blocks=[{'name': 'mcu', 'refs': ['U4', 'C1'], 'rigid': True},
                        {'name': 'free', 'refs': ['C2']}],
                arrays=[_row()],
                fixed_poses=[{'ref': 'J3', 'x': 1, 'y': 2,
                              'basis': 'declared'}])
    it = fp.intent_from_dict(raw)
    b, _ = fp.resolve_intent_gate(it, _pcb(), ())
    assert b['rigid_blocks'] == {'array:pullups': ['R6', 'R7', 'R8'],
                                 'block:mcu': ['C1', 'U4']}, b['rigid_blocks']
    assert b['arrays'][0]['order_refs'] == ['R6', 'R7', 'R8'], b['arrays']
    assert b['fixed_poses'][0]['ref'] == 'J3'
    # The keys every existing consumer reads are unchanged.
    plain, _ = fp.resolve_intent_gate(fp.intent_from_dict(_base()), _pcb(),
                                      ())
    assert plain['arrays'] == () and plain['fixed_poses'] == () \
        and plain['rigid_blocks'] == {}
    assert set(plain) == {'rotations', 'zones', 'keepouts', 'lock_refs',
                          'arrays', 'fixed_poses', 'rigid_blocks'}
    print("  PASS: resolve_intent_gate carries arrays, fixed_poses and "
          "rigid_blocks as data")


# --------------------------------------------------------------------------
# fixed poses are graded, whatever their source (#1054 correction)
# --------------------------------------------------------------------------

def _u4_pose(dx=0.0):
    u = _pcb().footprints['U4']
    return {'ref': 'U4', 'x': u.x + dx, 'y': u.y, 'rot': u.rotation,
            'basis': 'declared', 'why': 'test'}


def test_every_fixed_pose_is_graded():
    r = _grade(_base(fixed_poses=[_u4_pose()]))
    assert not [v for v in r.violations
                if (v.block or '').startswith('fixed:')], r.violations
    r = _grade(_base(fixed_poses=[_u4_pose(5.0)]))
    hit = [v for v in r.violations if v.block == 'fixed:U4']
    assert len(hit) == 1 and hit[0].rule == 'zone_containment' \
        and hit[0].ref == 'U4' and hit[0].severity == 'error', r.violations
    # A ref the board does not have is an error, never a clean pass.
    r = _grade(_base(fixed_poses=[{'ref': 'ZZ9', 'x': 0, 'y': 0,
                                   'basis': 'declared'}]))
    assert [(v.rule, v.severity) for v in r.violations
            if v.ref == 'ZZ9'] == [('fixed_pose_unresolved', 'error')]
    # A pad-less part cannot be anchored: a WARN that says why.
    pcb = _fresh()
    pcb.footprints['H6'].pads = []
    h = pcb.footprints['H6']
    r = _grade(_base(fixed_poses=[{'ref': 'H6', 'x': h.x, 'y': h.y,
                                   'basis': 'mechanical'}]), pcb=pcb)
    w = [v for v in r.violations if v.ref == 'H6']
    assert [(v.rule, v.severity) for v in w] == [
        ('fixed_pose_unresolved', 'warn')] and 'pad-less' in w[0].message, w
    # A ref the mechanical file anchors is graded ONCE, by the file.
    mech = {'path': 'm.json', 'poses': {'U4': {
        'x': _u4_pose(5.0)['x'], 'y': _u4_pose()['y'], 'rot': 0.0,
        'reason': 'r'}}}
    r = _grade(_base(fixed_poses=[_u4_pose(5.0)]), mechanical=mech)
    blocks = sorted(v.block for v in r.violations
                    if v.rule == 'zone_containment')
    assert blocks == ['mech:U4'], blocks
    print("  PASS: a fixed pose grades clean at its pose, fails 5 mm off, "
          "refuses a missing ref, warns on a pad-less one, and is graded once "
          "when the mechanical file also anchors it")


# --------------------------------------------------------------------------
# the brief: compile, unknown vs absent, merge, drift, coverage
# --------------------------------------------------------------------------

BRIEF = {'schema': 1, 'kind': 'design-brief', 'units': 'mm'}


def _brief(**over):
    raw = dict(BRIEF)
    raw.update(over)
    return db.brief_from_dict(raw, 'b.design-brief.json')


def _brief_rejects(why, **over):
    try:
        _brief(**over)
    except db.BriefError as exc:
        assert why in str(exc), (why, str(exc))
        return
    raise AssertionError(f"NOT REFUSED, expected {why!r}: {over!r}")


def test_the_brief_compiles_arrays_and_fixed_poses():
    b = _brief(arrays=[_row(requirement='one bus, one row'),
                       {'name': 'r2', 'members': ['R9', 'R11'],
                        'order': 'unknown', 'serves': 'unknown'}],
               fixed=[{'ref': 'U4', 'why': 'datum',
                       'pose': {'x': 1.5, 'y': 2.5, 'rot': 'unknown'}},
                      {'ref': 'H1', 'why': 'boss'}])
    refs = sorted(_pcb().footprints)
    frag, rep = db.compile_brief(b, board_refs=refs)
    assert frag['min_reader'] == 7, frag
    a0 = frag['arrays'][0]
    assert a0['source'] == 'brief' and 'requirement' not in a0 \
        and a0['context']['requirement'] == 'one bus, one row', a0
    assert frag['fixed_poses'] == [{'ref': 'U4', 'x': 1.5, 'y': 2.5,
                                    'rot': 'unknown', 'basis': 'declared',
                                    'why': 'datum'}], frag['fixed_poses']
    # "unknown" is reported; an ABSENT key is neither declared nor unknown.
    assert 'arrays[r2].order' in rep['unknown'] \
        and 'arrays[r2].serves' in rep['unknown'], rep['unknown']
    assert 'fixed[U4].rot' in rep['unknown'], rep['unknown']
    assert 'arrays[pullups].order' in rep['declared'], rep['declared']
    for cid in ('arrays[r2].rotation', 'arrays[pullups].pitch_mm',
                'fixed[U4].side'):
        assert cid not in rep['declared'] and cid not in rep['unknown'], cid
    assert rep['counts']['arrays'] == 2 and rep['counts']['fixed_poses'] == 1
    assert 'H1' not in {f['ref'] for f in frag['fixed_poses']}
    # Every clause id the compiler emits parses back.
    for cid in rep['declared'] + [u for u in rep['unknown'] if '[' in u]:
        assert db.parse_clause_id(cid) is not None, cid
    # The compiled fragment loads as an intent.
    it = fp.intent_from_dict(_base(**{k: v for k, v in frag.items()}))
    assert len(it.arrays) == 2 and len(it.fixed_poses) == 1
    # A brief with neither keeps the counts it always had.
    _f, rep0 = db.compile_brief(_brief(), board_refs=refs)
    assert 'arrays' not in rep0['counts'] and 'fixed_poses' not in \
        rep0['counts'] and 'min_reader' not in _f, (rep0['counts'], _f)
    print("  PASS: arrays and fixed[].pose compile 1:1 at min_reader 7; "
          "unknown and absent reported apart")


def test_the_brief_refuses_what_the_intent_refuses():
    _brief_rejects('member R8 is also in array',
                   arrays=[_row(), _row(name='b', members=['R8', 'R9'])])
    _brief_rejects('also declared in interfaces[]',
                   interfaces=[{'ref': 'J1', 'edge': 'west'}],
                   fixed=[{'ref': 'J1', 'pose': {'x': 0, 'y': 0}}])
    _brief_rejects('member R6 has a `fixed_poses` entry',
                   arrays=[_row()],
                   fixed=[{'ref': 'R6', 'pose': {'x': 0, 'y': 0}}])
    _brief_rejects('needs `y`', fixed=[{'ref': 'J1', 'pose': {'x': 0}}])
    _brief_rejects("side: 'top'",
                   fixed=[{'ref': 'J1', 'pose': {'x': 0, 'y': 0,
                                                 'side': 'top'}}])
    _brief_rejects('unknown key(s) reqs', arrays=[_row(reqs='x')])
    _brief_rejects('member R7 is also an `edge_connectors` entry',
                   arrays=[_row()], interfaces=[{'ref': 'R7',
                                                 'edge': 'north'}])
    print("  PASS: the brief refuses a doubled member, a pose on an "
          "interface, a posed array member and malformed poses, by name")


def test_merge_drift_and_coverage():
    b = _brief(arrays=[_row()],
               fixed=[{'ref': 'U4', 'pose': {'x': 144.78, 'y': 48.26,
                                             'rot': 0}}])
    frag, rep = db.compile_brief(b, board_refs=sorted(_pcb().footprints))
    emitted = {'schema': 1, 'kind': 'floorplan-intent', 'units': 'mm',
               'must_lock': ['U4'],
               'edge_connectors': [{'ref': 'R6', 'edge': 'north',
                                    'source': 'observed'}]}
    merged = db.merge_into_intent(emitted, frag, rep)
    assert merged['arrays'] == frag['arrays']
    assert merged['fixed_poses'] == frag['fixed_poses']
    assert merged['min_reader'] == 7
    # The emitter's inferences for the same parts are DROPPED, and said so.
    assert merged['edge_connectors'] == [] and merged['must_lock'] == [], \
        merged
    joined = ' | '.join(rep['contradictions'])
    assert 'R6: the brief puts it in array' in joined \
        and "must_lock 'U4' names U4" in joined, joined
    it = fp.intent_from_dict(merged)
    assert it.arrays and it.fixed_poses
    # No drift against itself; drift when the intent lost or changed a row.
    assert db.drift_pairs(merged, frag) == []
    lost = dict(merged, arrays=[], fixed_poses=[])
    ids = db.drifted_clause_ids(lost, frag)
    assert ids == ['arrays[pullups].members', 'fixed[U4].pose'], ids
    moved = json.loads(json.dumps(merged))
    moved['arrays'][0]['order'] = 'declared'
    moved['fixed_poses'][0]['x'] = 150.0
    ids = db.drifted_clause_ids(moved, frag)
    assert ids == ['arrays[pullups].order', 'fixed[U4].pose'], ids
    # Coverage: graded when carried and graded, uncovered when dropped.
    res = fp.grade(it, _pcb(), SPLITFLAP)
    cov = db.clause_coverage(rep, merged, rules_run=res.rules_run,
                             abstained=res.budget_abstained)
    st = {c['id']: c['state'] for c in cov['clauses']}
    assert st['arrays[pullups].members'] == 'graded', st
    assert st['fixed[U4].pose'] == 'graded', st
    cov = db.clause_coverage(rep, lost, rules_run=res.rules_run)
    st = {c['id']: c['state'] for c in cov['clauses']}
    assert st['arrays[pullups].members'] == 'uncovered' \
        and st['fixed[U4].pose'] == 'uncovered', st
    # The ledger attributes a formation failure to the ARRAY clause.
    bad = json.loads(json.dumps(merged))
    bad['arrays'][0]['members'] = ['R6', 'R7', 'R8', 'R9']
    b2 = _brief(arrays=[_row(members=['R6', 'R7', 'R8', 'R9'])])
    frag2, rep2 = db.compile_brief(b2, board_refs=sorted(_pcb().footprints))
    it2 = fp.intent_from_dict(bad)
    res2 = fp.grade(it2, _pcb(), SPLITFLAP, with_roster=True,
                    brief_fragment=frag2)
    cov2 = db.clause_coverage(rep2, bad, rules_run=res2.rules_run)
    led = fp.declaration_ledger(it2, res2.roster, result=res2, coverage=cov2)
    row = [x for x in led if x['id'] == 'arrays[pullups].members']
    assert row and row[0]['status'] == 'graded_fail', row
    print("  PASS: merge appends and drops the emitter's colliding claims; "
          "drift and coverage see both keys; the ledger fails the array "
          "clause")


# --------------------------------------------------------------------------
# emit: nothing by default; the rigid path; mechanical poses compile
# --------------------------------------------------------------------------

def test_emit_intent_writes_none_of_it_by_default():
    doc = fp.emit_intent(_pcb(), SPLITFLAP)
    for key in ('arrays', 'fixed_poses', 'min_reader'):
        assert key not in doc, key
    assert not any('rigid' in b for b in doc['blocks'])
    try:
        fp.emit_intent(_pcb(), SPLITFLAP, derive_arrays='auto')
    except NotImplementedError as exc:
        assert 'phase 2' in str(exc), exc
    else:
        raise AssertionError("derive_arrays='auto' was accepted")
    # splitflap emits no blocks; glasgow emits sheet blocks.
    gl = _pcb(GLASGOW)
    base = fp.emit_intent(gl, GLASGOW)
    assert not any('rigid' in b for b in base['blocks'])
    assert 'min_reader' not in base
    name = base['blocks'][0]['name']
    ron = fp.emit_intent(gl, GLASGOW, rigid_blocks=(name,))
    assert [b['name'] for b in ron['blocks'] if b.get('rigid')] == [name]
    assert ron['min_reader'] == 7
    rigid = [z.name for z in fp.intent_from_dict(ron).blocks if z.rigid]
    assert rigid == [name], rigid
    try:
        fp.emit_intent(_pcb(), SPLITFLAP, rigid_blocks=('no-such-block',))
    except ValueError as exc:
        assert 'no-such-block' in str(exc), exc
    else:
        raise AssertionError('an unknown rigid block name was accepted')
    print(f"  PASS: emit_intent writes no arrays/fixed_poses/rigid by "
          f"default; rigid_blocks=({name!r},) marks exactly that block")


def test_mechanical_poses_compile_into_fixed_poses():
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'emitted.json')
        check([sys.executable, '-X', 'utf8', CHECK_FLOORPLAN, ESP,
               '--emit-intent', out, '--brief', ESP_BRIEF,
               '--mechanical', ESP_MECH, '-q'], accept=True)
        with open(out, encoding='utf-8') as fh:
            doc = json.load(fh)
        mech = doc['context']['mechanical']
        assert mech['fixed_poses'] == ['Ref*', 'Ref*~2'], mech
        assert set(mech['fixed_skipped']) == {'USB1'}, mech['fixed_skipped']
        rows = {f['ref']: f for f in doc['fixed_poses']}
        assert rows['Ref*']['basis'] == 'mechanical' \
            and (rows['Ref*']['x'], rows['Ref*']['y']) == (141.2, 95.9), rows
        assert doc['min_reader'] == 7
        # It loads and grades: the as-built fiducials sit at their poses.
        check([sys.executable, '-X', 'utf8', CHECK_FLOORPLAN, ESP,
               '--intent', out, '--brief', ESP_BRIEF, '--no-mechanical',
               '-q'], accept=True)
    print("  PASS: mechanical.json anchors compile to fixed_poses (USB1, an "
          "edge connector, skipped by name) and the intent grades")


TESTS = [
    test_the_new_keys_load_and_land_on_the_intent,
    test_every_load_refusal_carries_its_reason,
    test_a_reader_6_file_still_loads_and_a_reader_7_claim_refuses_old,
    test_the_formation_predicate,
    test_pin_order_is_read_off_pads_and_nets,
    test_array_formation_grades_the_as_built_board,
    test_board_aware_findings_name_the_member,
    test_the_gate_bundle_carries_the_new_data,
    test_every_fixed_pose_is_graded,
    test_the_brief_compiles_arrays_and_fixed_poses,
    test_the_brief_refuses_what_the_intent_refuses,
    test_merge_drift_and_coverage,
    test_emit_intent_writes_none_of_it_by_default,
    test_mechanical_poses_compile_into_fixed_poses,
]


if __name__ == '__main__':
    for t in TESTS:
        print(f"--- {t.__name__}")
        t()
    print('ALL PASS')
