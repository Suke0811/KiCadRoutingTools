#!/usr/bin/env python3
"""#1111: check_pads measures a CUSTOM pad on its real copper, not its box.

`check_pads` outlined every pad from `size_x/size_y`, which for a custom pad
is a box symmetric about the anchor. StickHub's solder jumper JP1 -- two
interleaved toothed pads whose real copper is 0.150 mm apart -- read as a
0.150 mm overlap, and through check_complete's `pad_overlaps` step no StickHub
board could reach DONE (run 39 was blocked on exactly that). The tracked
corpus has a second victim: rp2350_fpga_eensy_prePlane's U5, 4 false pairs.

The fix keeps today's outline test FIRST and confirms a pair that involves a
custom pad with check_drc's own exact pad-pad check, then measures the depth
on the shared copper with the placement graders' `overlap_thickness`. So the
exact measurement can only remove a hit. Every discriminating arm here fails
on the box model and passes on the copper, and the fixture is ASYMMETRIC (an
L-shaped pad off its anchor) because a centred shape makes the box and the
copper agree.

The L pad: anchor 0.4 x 0.4 (rect) at the footprint origin, plus a gr_poly
bar x[0, 1] y[-0.2, 0.2] and an arm x[0.8, 1] y[0.2, 1]. Its copper is the
union of those; its box is +-1.0 about the anchor.

Run: python3 -X utf8 tests/test_1111_custom_pad_exact.py [case ...]
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_utils  # noqa: E402

ROOT = run_utils.ROOT_DIR
for _sub in ('py_router', 'py_tools', 'py_placer'):
    _p = os.path.join(ROOT, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kicad_parser import parse_kicad_pcb  # noqa: E402
import check_pads  # noqa: E402

RUN_ALL_TIMEOUT = 900

_L_POLY = ('(gr_poly (pts (xy 0 -0.2) (xy 1 -0.2) (xy 1 1) (xy 0.8 1) '
           '(xy 0.8 0.2) (xy 0 0.2)) (width 0) (fill yes))')

#: StickHub JP1, `footprints:JP-2_1.5x1.5`, copied from KiCad 10's demo
#: (share/kicad/demos/stickhub/StickHub.kicad_pcb; CC BY-NC-SA, so the board
#: itself is not tracked) -- the two pads as the file spells them.
_JP1_PADS = '''    (pad "1" connect custom (at -0.975 0.05) (size 1.5 1.5)
      (layers "B.Cu" "B.Mask") (net 1 "N1")
      (options (clearance outline) (anchor rect))
      (primitives
        (gr_poly (pts (xy -0.000001 -1.05) (xy -0.249999 -0.55) (xy 0.25 -0.55)) (width 0) (fill yes))
        (gr_poly (pts (xy -0.5 -1.049999) (xy -0.75 -0.55) (xy -0.249999 -0.55)) (width 0) (fill yes))
        (gr_poly (pts (xy 0.5 -1.05) (xy 0.25 -0.55) (xy 0.75 -0.550001)) (width 0) (fill yes))))
    (pad "2" connect custom (at {x2} 0.05) (size 1.5 1.5)
      (layers "B.Cu" "B.Mask") (net 2 "N2")
      (options (clearance outline) (anchor rect))
      (primitives
        (gr_poly (pts (xy -0.249994 1.05) (xy -0.000007 0.55) (xy -0.5 0.55)) (width 0) (fill yes))
        (gr_poly (pts (xy 0.250006 1.049999) (xy 0.499994 0.55) (xy -0.000001 0.55)) (width 0) (fill yes))))
'''


def _l_pad(num, net, lx=0.0, ly=0.0, rot=0.0):
    return (f'    (pad "{num}" smd custom (at {lx} {ly} {rot:g}) (size 0.4 0.4)'
            f' (layers "F.Cu") (net {net} "N{net}")\n'
            f'      (options (clearance outline) (anchor rect))\n'
            f'      (primitives {_L_POLY}))\n')


def _rect_pad(num, net, lx, ly, w=0.4, h=0.4, rot=0.0, thru=False):
    if thru:
        return (f'    (pad "{num}" thru_hole rect (at {lx} {ly} {rot:g}) '
                f'(size {w} {h}) (drill 0.2) (layers "*.Cu") '
                f'(net {net} "N{net}"))\n')
    return (f'    (pad "{num}" smd rect (at {lx} {ly} {rot:g}) (size {w} {h})'
            f' (layers "F.Cu") (net {net} "N{net}"))\n')


def _fp(ref, x, y, pads, rot=0.0, layer='F.Cu'):
    return (f'  (footprint "t:{ref}" (layer "{layer}") (at {x} {y} {rot:g})\n'
            f'    (property "Reference" "{ref}" (at 0 0) (layer "F.SilkS"))\n'
            + pads + '  )\n')


def _board(path, *footprints):
    text = ('(kicad_pcb (version 20240108) (generator pcbnew)\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) '
            '(44 "Edge.Cuts" user))\n'
            '  (net 0 "") (net 1 "N1") (net 2 "N2")\n'
            '  (gr_rect (start 0 0) (end 30 30) (stroke (width 0.1) '
            '(type default)) (layer "Edge.Cuts"))\n'
            + ''.join(footprints) + ')\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def _pcb(*footprints):
    wd = tempfile.mkdtemp(prefix='t1111_')
    return parse_kicad_pcb(_board(os.path.join(wd, 'b.kicad_pcb'),
                                  *footprints))


def _l_with(rect_x, rect_y, w=0.4, h=0.4, rot=0.0):
    """The L pad at (10, 10) and a rect neighbour at (rect_x, rect_y), both
    in ONE footprint (check_pads' default per-footprint mode), turned
    rigidly by `rot` about the L's anchor: the rect's offset is LOCAL, so the
    parser turns both pads with the footprint."""
    return _pcb(_fp('U1', 10, 10, _l_pad('1', 1, rot=rot)
                    + _rect_pad('2', 2, round(rect_x - 10.0, 6),
                                round(rect_y - 10.0, 6), w, h, rot=rot),
                    rot=rot))


def _depths(pcb, **kw):
    return sorted(round(d, 3) for _a, _b, d in
                  check_pads.find_pad_overlaps(pcb, **kw))


def _exact_gap(a, b, layers):
    """check_drc's own answer: the edge gap between two pads (mm), probed at
    a 0.5 mm clearance."""
    from check_drc import check_pad_pad_overlap
    hit, over, _pt = check_pad_pad_overlap(a, b, 0.5, layers,
                                           clearance_margin=0.0)
    return 0.5 - over if hit else None


def _box_depth(pcb):
    """What the pre-#1111 model reads: the outline test alone."""
    out = []
    for fp in pcb.footprints.values():
        out.extend(round(d, 3) for _a, _b, d in
                   check_pads._overlaps_in(fp.pads, 0.05))
    return sorted(out)


def test_the_interleaved_jumper_is_clean():
    """StickHub JP1 as drawn: the box reads 0.150 mm overlap; the copper is
    0.150 mm APART, which check_drc confirms on the same pads."""
    pcb = _pcb(_fp('JP1', 15, 15, _JP1_PADS.format(x2=0.975), rot=90,
                   layer='B.Cu'))
    assert _box_depth(pcb) == [0.15], f"fixture box depth {_box_depth(pcb)}"
    assert _depths(pcb) == [] and _depths(pcb, cross_footprint=True) == [], (
        _depths(pcb))
    a, b = pcb.footprints['JP1'].pads
    gap = _exact_gap(a, b, pcb.board_info.copper_layers)
    assert gap is not None and abs(gap - 0.150) < 0.005, f"exact gap {gap}"
    print(f"  JP1: box 0.150 overlap, copper gap {gap:.3f}, check_pads clean")


def test_a_genuine_jumper_overlap_is_still_found():
    """The same pads pushed 0.25 mm together, so the teeth really overlap:
    still reported, at the copper's depth rather than the box's."""
    pcb = _pcb(_fp('JP1', 15, 15, _JP1_PADS.format(x2=0.725), rot=90,
                   layer='B.Cu'))
    box, got = _box_depth(pcb), _depths(pcb)
    assert len(got) == 1 and 0.0 < got[0] < box[0], (box, got)
    print(f"  JP1 pushed together: box {box[0]:.3f}, copper {got[0]:.3f}")


def test_the_box_empty_side_is_not_copper():
    """A rect on the L's EMPTY side (west of the anchor), 0.1 mm from its
    copper and deep inside its box: the box reads 0.700."""
    pcb = _l_with(9.5, 10.0)
    assert _box_depth(pcb) == [0.7], _box_depth(pcb)
    assert _depths(pcb) == [], _depths(pcb)
    print("  empty side: box 0.700, copper clean")


def test_a_concave_notch_is_not_copper():
    """A rect in the L's inner corner, 0.1 mm from both arms: clean. A convex
    hull of the L would contain it."""
    pcb = _l_with(10.5, 10.5)
    assert _box_depth(pcb) == [0.7], _box_depth(pcb)
    assert _depths(pcb) == [], _depths(pcb)
    print("  inner corner: box 0.700, copper clean")


def test_a_sliver_overlap_is_measured_on_the_copper():
    """A rect overlapping the L's arm by 0.08 mm: reported, at 0.080 -- the
    thickness of the shared copper, not the box's 0.700 nor a hull's."""
    pcb = _l_with(10.59, 10.5, w=0.58)
    assert _box_depth(pcb) == [0.7], _box_depth(pcb)
    got = _depths(pcb)
    assert len(got) == 1 and abs(got[0] - 0.080) < 0.002, got
    print(f"  sliver: box 0.700, copper {got[0]:.3f}")


def test_the_tolerance_applies_to_the_copper_depth():
    pcb = _l_with(10.59, 10.5, w=0.58)
    assert check_pads.find_pad_overlaps(pcb, tolerance=0.1) == []
    assert len(check_pads._overlaps_in(
        pcb.footprints['U1'].pads, 0.1)) == 1     # the box still trips
    print("  tolerance 0.1: the 0.080 sliver is under it; the box was not")


def test_a_turned_footprint_reads_the_same():
    """The empty-side and sliver fixtures turned rigidly by 30 degrees: the
    same verdicts, so the copper is read in the board frame."""
    assert _depths(_l_with(9.5, 10.0, rot=30)) == []
    got = _depths(_l_with(10.59, 10.5, w=0.58, rot=30))
    assert len(got) == 1 and abs(got[0] - 0.080) < 0.005, got
    print(f"  turned 30: empty side clean, sliver {got[0]:.3f}")


def test_a_deep_contact_reads_the_same_either_way():
    """CONTROL: a rect overlapping the L's bar 0.1 mm deep. Box and copper
    agree, so this passes on both models -- it shows the exact path does not
    drop a real short."""
    pcb = _l_with(11.1, 10.0)
    assert _box_depth(pcb) == [0.1], _box_depth(pcb)
    assert _depths(pcb) == [0.1], _depths(pcb)
    print("  deep contact: 0.100 on both")


def test_cross_footprint_mode_measures_the_copper_too():
    pcb = _pcb(_fp('U1', 10, 10, _l_pad('1', 1)),
               _fp('R1', 9.5, 10, _rect_pad('1', 2, 0, 0)))
    assert _depths(pcb) == []                       # different footprints
    pads = [p for fp in pcb.footprints.values() for p in fp.pads]
    assert len(check_pads._overlaps_in(pads, 0.05)) == 1
    assert _depths(pcb, cross_footprint=True) == [], _depths(
        pcb, cross_footprint=True)
    print("  cross-footprint: box 1 hit, copper clean")


def test_no_copper_layers_keeps_the_box_verdict():
    """check_drc reads a `*.Cu` pad as on NO layer when it is given none, so
    a through-hole pair would silently read clear. Without the board's
    copper layers the box verdict stands."""
    pcb = _l_with(9.5, 10.0)
    pads = pcb.footprints['U1'].pads
    assert len(check_pads._overlaps_in(pads, 0.05, [])) == 1
    th = _pcb(_fp('U1', 10, 10, _l_pad('1', 1)
                  + _rect_pad('2', 2, -0.5, 0, thru=True)))
    assert len(check_pads._overlaps_in(th.footprints['U1'].pads, 0.05,
                                       [])) == 1
    assert check_pads._overlaps_in(th.footprints['U1'].pads, 0.05,
                                   th.board_info.copper_layers) == []
    print("  no copper layers: box verdict kept; with them, clean")


def test_rp2350_u5_has_no_false_pairs():
    """The tracked corpus victim: U5 (VQFN-HR), 4 pairs on the box, real gap
    0.2 mm each."""
    pcb = parse_kicad_pcb(run_utils.evidence(os.path.join(
        ROOT, 'kicad_files', 'rp2350_fpga_eensy_prePlane.kicad_pcb')))
    u5 = pcb.footprints['U5']
    assert len(check_pads._overlaps_in(u5.pads, 0.05)) == 4
    assert check_pads.find_pad_overlaps(pcb, component='U5') == []
    cross = [h for h in check_pads.find_pad_overlaps(pcb, cross_footprint=True)
             if 'U5' in (h[0].component_ref, h[1].component_ref)]
    assert cross == [], cross
    print("  rp2350 U5: 4 box pairs -> 0")


def test_a_pair_with_no_custom_pad_is_untouched():
    """Every pair with no custom pad keeps today's outline depth, unchanged,
    on three corpus boards -- read at tolerance -0.3 so near misses (the
    negative depths) are compared too, not only hits."""
    for name, want in (('rp2350_fpga_eensy_prePlane', 74),
                       ('glasgow_revC', 129), ('orangecrab_ext_pll', 16)):
        pcb = parse_kicad_pcb(run_utils.evidence(os.path.join(
            ROOT, 'kicad_files', name + '.kicad_pcb')))
        layers = pcb.board_info.copper_layers
        old, new = [], []
        for fp in pcb.footprints.values():
            for out, rl in ((old, ()), (new, layers)):
                out.extend((a.component_ref, a.pad_number, b.pad_number,
                            round(d, 9))
                           for a, b, d in check_pads._overlaps_in(
                               fp.pads, -0.3, rl)
                           if not (a.polygons or b.polygons))
        assert old == new, f"{name}: a non-custom pair changed"
        assert len(old) == want, f"{name}: {len(old)} non-custom pairs, {want}"
        print(f"  {name}: {len(old)} non-custom pairs identical")


def test_the_cli_says_so():
    wd = tempfile.mkdtemp(prefix='t1111_cli_')
    jp = _board(os.path.join(wd, 'jp.kicad_pcb'),
                _fp('JP1', 15, 15, _JP1_PADS.format(x2=0.975), rot=90,
                    layer='B.Cu'))
    tool = os.path.join(ROOT, 'py_router', 'check_pads.py')
    r = run_utils.check([sys.executable, '-X', 'utf8', tool, jp,
                         '--cross-footprint'], accept=True)
    assert 'OK: no overlapping' in r.stdout, r.stdout
    sl = _board(os.path.join(wd, 'sliver.kicad_pcb'),
                _fp('U1', 10, 10, _l_pad('1', 1)
                    + _rect_pad('2', 2, 0.59, 0.5, 0.58, 0.4)))
    r = run_utils.check([sys.executable, '-X', 'utf8', tool, sl],
                        refuse='FAILED: 1 overlapping different-net pad pair',
                        code=1)
    assert 'overlap 0.080 mm' in r.stdout, r.stdout
    print("  CLI: jumper OK (exit 0); sliver FAILED 0.080 (exit 1)")


TESTS = [
    test_the_interleaved_jumper_is_clean,
    test_a_genuine_jumper_overlap_is_still_found,
    test_the_box_empty_side_is_not_copper,
    test_a_concave_notch_is_not_copper,
    test_a_sliver_overlap_is_measured_on_the_copper,
    test_the_tolerance_applies_to_the_copper_depth,
    test_a_turned_footprint_reads_the_same,
    test_a_deep_contact_reads_the_same_either_way,
    test_cross_footprint_mode_measures_the_copper_too,
    test_no_copper_layers_keeps_the_box_verdict,
    test_rp2350_u5_has_no_false_pairs,
    test_a_pair_with_no_custom_pad_is_untouched,
    test_the_cli_says_so,
]


if __name__ == '__main__':
    only = sys.argv[1:]
    ran = 0
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        print(f"--- {t.__name__}")
        t()
        ran += 1
    if only and not ran:
        # A filter that names no case passes nothing: a mutation battery
        # witness spelled wrong would otherwise read every row as SURVIVED.
        print(f"NO TEST matches {only}")
        sys.exit(2)
    print('ALL PASS')
