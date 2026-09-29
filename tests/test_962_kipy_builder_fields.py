#!/usr/bin/env python3
"""#962 and #1063 on the IPC read path: the fields the kipy builder must fill.

main's two parse paths -- the text scan and the SWIG pcbnew walk -- fill the
paste stencil (#962: pad and footprint paste overrides, a custom pad's anchor
size, the board's paste margin and via-protection policy, `paste_apertures`)
and each pad's unconnected-layer mode (#1063). This branch's
`build_pcb_data_from_board` is neither path, and until it read them the IPC
model carried none of it: every pad flashed on every layer, no paste opening
existed, and a via-in-paste could be neither kept out nor declared.

WHY THE HELPERS AND NOT THE BUILDER. The builder needs a RUNNING KiCad, and
`fake_ipc_board` serves reads by re-parsing the file, so driving the builder
through it would grade the text parser twice. The kipy reads therefore live in
functions this test reaches with REAL kipy objects (`kipy.board_types.Pad`,
`FootprintInstance`), edited through the same proto fields KiCad fills:

  A. `kipy_unconnected_layer_mode`  -- the #1063 enum, all values
  B. `kipy_pad_paste_overrides`     -- set vs unset, where 0 is a real value
  C. `kipy_footprint_paste_overrides`
  D. `kipy_paste_graphics`          -- file geometry at the LIVE pose; the
     oracle is `extract_paste_graphics`, the text path's own reader
  E. the assembled stencil equals `parse_kicad_pcb(...).paste_apertures`
  F. the via protection spec, READ off a live via and WRITTEN onto a new one
     (`kipy_via_protection_live`, `kipy_set_via_protection`), pinned to the
     blocks KiCad 10.0.0 itself saved for those padstack enums -- without the
     write, the IPC front shipped #962's Type VII stamp as an inheriting via

    python3 -X utf8 tests/test_962_kipy_builder_fields.py
"""
import copy
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

try:
    from kipy.board_types import FootprintInstance, Pad
    from kipy.proto.board import board_types_pb2 as bt
except Exception as _e:                                          # noqa: BLE001
    print(f"SKIP: kipy is not importable ({type(_e).__name__}: {_e}); install "
          f"kicad-python, which requirements.txt lists on this branch")
    sys.exit(77)

from kicad_parser import (extract_paste_graphics,                # noqa: E402
                          kipy_footprint_paste_overrides,
                          kipy_pad_paste_overrides, kipy_paste_graphics,
                          kipy_unconnected_layer_mode, parse_kicad_pcb)
from paste_apertures import build_paste_apertures               # noqa: E402

BOARD = os.path.join(ROOT, 'kicad_files', 'esp_prog.kicad_pcb')
#: esp_prog's U2 carries a footprint-owned F.Paste graphic (its thermal tab),
#: the case #962 was filed about.
OWNER = 'U2'

FAILS = []


def check(cond, msg):
    print(f"  {'ok  ' if cond else 'FAIL'}  {msg}")
    if not cond:
        FAILS.append(msg)
    return cond


# ---------------------------------------------------------------------------
# A. unconnected-layer mode (#1063)
# ---------------------------------------------------------------------------
def test_unconnected_layer_mode():
    want = {'ULR_UNKNOWN': 'keep_all',
            'ULR_KEEP': 'keep_all',
            'ULR_REMOVE': 'remove_all',
            'ULR_REMOVE_EXCEPT_START_AND_END': 'remove_except_start_end',
            # kipy 0.7+ only; KiCad saves it as remove_all.
            'ULR_START_END_ONLY': 'remove_all'}
    seen = 0
    for name, mode in want.items():
        val = getattr(bt, name, None)
        if val is None:
            continue
        pad = Pad()
        pad.padstack.proto.unconnected_layer_removal = val
        check(kipy_unconnected_layer_mode(pad.padstack) == mode,
              f"{name} reads as {mode!r}")
        seen += 1
    check(seen >= 4, f"the enum was exercised ({seen} values)")
    check(kipy_unconnected_layer_mode(object()) == 'keep_all',
          "an unreadable padstack reads keep_all, the no-token reading")


# ---------------------------------------------------------------------------
# B. a pad's own paste overrides
# ---------------------------------------------------------------------------
def test_pad_paste_overrides():
    pad = Pad()
    check(kipy_pad_paste_overrides(pad.padstack) == (None, None),
          "a pad with no override reads (None, None) -- it inherits")

    pad = Pad()
    pad.padstack.proto.front_outer_layers.solder_paste_settings \
        .solder_paste_margin.value_nm = -50000
    check(kipy_pad_paste_overrides(pad.padstack) == (-0.05, None),
          "a front margin override reads in mm, the ratio still unset")

    pad = Pad()
    pad.padstack.proto.front_outer_layers.solder_paste_settings \
        .solder_paste_margin.value_nm = 0
    check(kipy_pad_paste_overrides(pad.padstack) == (0.0, None),
          "a margin SET to 0 reads 0.0, not None: 0 is an override, and "
          "reading the wire value instead of HasField would lose it")

    pad = Pad()
    pad.padstack.proto.back_outer_layers.solder_paste_settings \
        .solder_paste_margin_ratio.value = -0.25
    check(kipy_pad_paste_overrides(pad.padstack) == (None, -0.25),
          "a back-only override is read when the front sets none")


# ---------------------------------------------------------------------------
# C. a footprint's paste overrides
# ---------------------------------------------------------------------------
def test_footprint_paste_overrides():
    fp = FootprintInstance()
    check(kipy_footprint_paste_overrides(fp) == (None, None),
          "a footprint with no override reads (None, None)")
    fp = FootprintInstance()
    fp.proto.overrides.solder_paste.solder_paste_margin_ratio.value = -0.1
    fp.proto.overrides.solder_paste.solder_paste_margin.value_nm = 25000
    check(kipy_footprint_paste_overrides(fp) == (0.025, -0.1),
          "footprint-level margin and ratio both read")


# ---------------------------------------------------------------------------
# D. paste graphics at the live pose
# ---------------------------------------------------------------------------
def _shift(g, dx, dy):
    g = dict(g)
    if 'points' in g:
        g['points'] = [(x + dx, y + dy) for x, y in g['points']]
    if 'center' in g:
        g['center'] = (g['center'][0] + dx, g['center'][1] + dy)
    return g


def _close(a, b, tol=1e-9):
    if a.keys() != b.keys():
        return False
    for k in a:
        va, vb = a[k], b[k]
        if k in ('points',):
            if len(va) != len(vb) or any(
                    abs(p[0] - q[0]) > tol or abs(p[1] - q[1]) > tol
                    for p, q in zip(va, vb)):
                return False
        elif k == 'center':
            if abs(va[0] - vb[0]) > tol or abs(va[1] - vb[1]) > tol:
                return False
        elif isinstance(va, float):
            if abs(va - vb) > tol:
                return False
        elif va != vb:
            return False
    return True


def test_paste_graphics_live_pose(content, pcb):
    oracle = extract_paste_graphics(content)
    owned = [g for g in oracle if g.get('owner_ref') == OWNER]
    if not check(owned, f"the fixture still carries a {OWNER} paste graphic "
                        f"(a board that stops being a witness must fail)"):
        return

    got, skipped = kipy_paste_graphics(content, pcb.footprints)
    check(not skipped and len(got) == len(oracle)
          and all(_close(a, b) for a, b in zip(got, oracle)),
          "unmoved parts: the live-posed read equals extract_paste_graphics")

    moved = dict(pcb.footprints)
    fp = copy.copy(moved[OWNER])
    fp.x, fp.y = fp.x + 3.0, fp.y - 2.0
    moved[OWNER] = fp
    got, skipped = kipy_paste_graphics(content, moved)
    mine = [g for g in got if g.get('owner_ref') == OWNER]
    check(not skipped and len(mine) == len(owned)
          and all(_close(a, _shift(b, 3.0, -2.0)) for a, b in zip(mine, owned)),
          f"{OWNER} moved (+3, -2) since the save: its paste tab moves with it "
          f"-- posing at the FILE's (at ...) would strand it")
    # Negative control: the file pose is what a naive read would give.
    check(not all(_close(a, b) for a, b in zip(mine, owned)),
          "negative control: the moved read differs from the file-pose read")

    for label, mutate in (
            ('flipped since the save', lambda f: setattr(
                f, 'layer', 'B.Cu' if f.layer == 'F.Cu' else 'F.Cu')),
            ('a different part under the same key', lambda f: setattr(
                f, 'uuid', '00000000-0000-0000-0000-000000000000'))):
        alt = dict(pcb.footprints)
        f2 = copy.copy(alt[OWNER])
        mutate(f2)
        alt[OWNER] = f2
        got, skipped = kipy_paste_graphics(content, alt)
        check(skipped == [OWNER]
              and not [g for g in got if g.get('owner_ref') == OWNER],
              f"{OWNER} {label}: SKIPPED and named, not posed on a guess")

    alt = {k: v for k, v in pcb.footprints.items() if k != OWNER}
    got, skipped = kipy_paste_graphics(content, alt)
    check(skipped == [OWNER], f"{OWNER} gone from the live board: skipped")


# ---------------------------------------------------------------------------
# E. the assembled stencil
# ---------------------------------------------------------------------------
def test_assembled_apertures(content, pcb):
    graphics, _ = kipy_paste_graphics(content, pcb.footprints)
    ours = build_paste_apertures(pcb.footprints, pcb.board_info, graphics)
    theirs = pcb.paste_apertures
    check(len(theirs) > 0 and [a.label() for a in ours]
          == [a.label() for a in theirs],
          f"the IPC assembly reproduces parse_kicad_pcb's {len(theirs)} "
          f"paste openings on an unmoved board")


# ---------------------------------------------------------------------------
# F. via protection, both ways, pinned to what KiCad 10.0.0 WROTE
# ---------------------------------------------------------------------------
#: Probed 2026-09-29: vias created over IPC with these padstack enums, saved by
#: KiCad 10.0.0 (SaveCopyOfDocument), and the via block it wrote. The oracle
#: for each spec is the TEXT PARSER reading KiCad's own block, so neither the
#: reader nor the writer can be graded against its own guess.
PROBED = (
    ('Type VII',
     {'drill.capped': 'VDCM_CAPPED', 'drill.filled': 'VDFM_FILLED'},
     '(via (at 2 2) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") '
     '(capping yes) (filling yes) (net ""))'),
    ('tenting F yes, B no',
     {'front_outer_layers.solder_mask_mode': 'SMM_MASKED',
      'back_outer_layers.solder_mask_mode': 'SMM_UNMASKED'},
     '(via (at 4 2) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") '
     '(tenting (front yes) (back no) ) (net ""))'),
    ('nothing set',
     {},
     '(via (at 6 2) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net ""))'),
    ('one side each, capping no',
     {'front_outer_layers.plugging_mode': 'VPM_PLUGGED',
      'back_outer_layers.covering_mode': 'VCM_COVERED',
      'drill.capped': 'VDCM_UNCAPPED'},
     '(via (at 8 2) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") '
     '(capping no) (covering (front none) (back yes) ) '
     '(plugging (front yes) (back none) ) (net ""))'),
)


def _set(ps, path, enum_name):
    obj = ps
    *parents, leaf = path.split('.')
    for p in parents:
        obj = getattr(obj, p)
    setattr(obj, leaf, getattr(bt, enum_name))


def _get(ps, path):
    obj = ps
    for p in path.split('.'):
        obj = getattr(obj, p)
    return obj


def test_via_protection_round_trip():
    from kipy.board_types import Via
    from kicad_parser import (_kipy_protection_enums, _via_spec_from_block,
                              kipy_set_via_protection, kipy_via_protection_live)

    if _kipy_protection_enums() is None:
        # kicad-python < 0.7 exposes the solder mask only. The contract there
        # is no PARTIAL spec: nothing read, every token reported unwritable.
        v = Via()
        check(kipy_via_protection_live(v) is None,
              "old kipy: the live reader answers None, never a partial spec")
        check(kipy_set_via_protection(v, {'capping': 'yes', 'filling': 'yes'})
              == ['capping', 'filling'],
              "old kipy: every token is reported unwritten")
        print("  (kicad-python < 0.7 here: the KiCad-probed mapping is graded "
              "where 0.7+ is installed, e.g. the Modal suite image)")
        return

    for label, enums, block in PROBED:
        want = _via_spec_from_block(block)
        v = Via()
        for path, name in enums.items():
            _set(v.padstack.proto, path, name)
        check(kipy_via_protection_live(v) == want,
              f"{label}: the live read is what KiCad wrote -- {want}")

        fresh = Via()
        unwritten = kipy_set_via_protection(fresh, want)
        check(not unwritten and all(
            _get(fresh.padstack.proto, p) == getattr(bt, n)
            for p, n in enums.items()),
              f"{label}: writing that spec sets the enums KiCad was given")
        check(kipy_via_protection_live(fresh) == want,
              f"{label}: and reads back identically")

    check(kipy_set_via_protection(Via(), {}) == [],
          "an empty spec writes nothing (the via inherits the board setup)")
    check(kipy_set_via_protection(Via(), {'capping': 'maybe',
                                          'bogus': 'yes'})
          == ['bogus', 'capping'],
          "an unknown token or value is reported unwritten, not guessed")


def test_disclosure_names_only_unwritable():
    """make_via writes every KiCad 10 token, so a Type VII stamp is NOT
    reported; a token it cannot write is. Negative control included."""
    import kicad_ipc_adapter as A
    from types import SimpleNamespace as NS
    from kicad_parser import _kipy_protection_enums
    pcb = NS(board_info=NS(via_protection_setup={}))
    vii = [{'x': 1.0, 'y': 2.0, 'net_id': 1,
            'tenting_attrs': {'capping': 'yes', 'filling': 'yes'}}]
    n = A.disclose_unwritten_via_protection(vii, lambda _n: '/N', pcb, 'test')
    if _kipy_protection_enums() is None:
        check(n == 1, "old kipy: a Type VII stamp is reported unwritten")
        return
    check(n == 0, "a Type VII stamp is written, so nothing is disclosed")
    bad = [{'x': 1.0, 'y': 2.0, 'net_id': 1,
            'tenting_attrs': {'capping': 'maybe'}}]
    check(A.disclose_unwritten_via_protection(bad, lambda _n: '/N', pcb, 'test')
          == 1, "negative control: an unwritable token IS disclosed")


def run():
    print("A. unconnected-layer mode")
    test_unconnected_layer_mode()
    print("B. pad paste overrides")
    test_pad_paste_overrides()
    print("C. footprint paste overrides")
    test_footprint_paste_overrides()
    content = open(BOARD, encoding='utf-8').read()
    pcb = parse_kicad_pcb(BOARD)
    print("D. paste graphics at the live pose")
    test_paste_graphics_live_pose(content, pcb)
    print("E. assembled stencil")
    test_assembled_apertures(content, pcb)
    print("F. via protection, read and written, as KiCad 10.0.0 saves it")
    test_via_protection_round_trip()
    test_disclosure_names_only_unwritable()
    if FAILS:
        print(f"\n{len(FAILS)} check(s) FAILED")
        return False
    print("\nPASS  #962/#1063 kipy builder fields")
    return True


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
