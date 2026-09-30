"""#1096: pad copper off the outline makes check_assembly NOT BUILDABLE.

Run 36 (KiCad's StickHub demo, placed from a pile) left C20 at its staging
pose, 7.24 mm below the board's south edge. check_assembly printed
"pad copper genuinely off the outline (per-pad, margin 0): C20 (36.8mm)" and
then `VERDICT: buildable (blocking 0)`; the run routed the board and the
router took GND off the board to reach C20.

Two things are pinned here:
- the per-pad, margin-0 channel is a verdict conjunct (and board_score's);
- the printed number is a DISTANCE (`oob_pad_copper_overrun_mm`). The old
  "36.8mm" was rect_outside_amount's ranking sum -- one overshoot term per
  off-board corner plus the bbox term -- for copper that reaches 7.84 mm out.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_placer'))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, os.path.join(ROOT, 'py_tools'))

BOARD = (
    '(kicad_pcb (version 20240108) (generator pcbnew)\n'
    '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n'
    '  (net 0 "") (net 1 "N1") (net 2 "N2")\n'
    '  (gr_rect (start 0 0) (end 20 20) (stroke (width 0.1) (type default))'
    ' (layer "Edge.Cuts"))\n'
    '  (footprint "t:R" (layer "F.Cu") (at 10 {y})\n'
    '    (property "Reference" "R1" (at 0 0) (layer "F.SilkS"))\n'
    '    (fp_rect (start -1 -0.5) (end 1 0.5) (stroke (width 0.05)'
    ' (type default)) (layer "F.CrtYd"))\n'
    '    (pad "1" smd rect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu")'
    ' (net 1 "N1"))\n'
    '    (pad "2" smd rect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu")'
    ' (net 2 "N2"))))\n')


def run(y):
    """check_assembly on a 20x20 board with R1 at (10, y)."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'b.kicad_pcb')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(BOARD.format(y=y))
        js = os.path.join(td, 'a.json')
        r = subprocess.run([sys.executable, '-X', 'utf8',
                            os.path.join(ROOT, 'py_tools',
                                         'check_assembly.py'),
                            path, '--json', js],
                           capture_output=True, text=True, cwd=ROOT)
        assert os.path.isfile(js), r.stderr[-2000:]
        with open(js, encoding='utf-8') as fh:
            return r, json.load(fh)


class TestOffOutline(unittest.TestCase):
    def test_a_part_off_the_board_is_not_buildable(self):
        """R1 at y=27: its pads span y 26.7-27.3, 6.7-7.3 mm below y=20."""
        r, d = run(27)
        self.assertEqual(r.returncode, 4, r.stdout[-1500:])
        self.assertFalse(d['buildable'])
        self.assertEqual([x[0] for x in d['oob_pad_copper_refs']], ['R1'])
        self.assertAlmostEqual(d['oob_pad_copper_overrun_mm']['R1'],
                               27.3 - 20, places=3)
        self.assertIn('R1 (7.3mm past the outline)', r.stdout)
        self.assertIn('NOT BUILDABLE', r.stdout)

    def test_a_part_half_off_names_its_overhang(self):
        """R1 at y=20: half of each pad is past the edge by 0.3 mm."""
        _r, d = run(20)
        self.assertFalse(d['buildable'])
        self.assertAlmostEqual(d['oob_pad_copper_overrun_mm']['R1'], 0.3,
                               places=3)

    def test_the_control_on_the_board_is_buildable(self):
        r, d = run(10)
        self.assertEqual(r.returncode, 0, r.stdout[-1500:])
        self.assertTrue(d['buildable'])
        self.assertEqual(d['oob_pad_copper_refs'], [])

    def test_board_score_counts_it(self):
        """board_score reads the verdict: NOT BUILDABLE at blocking 0 is 1,
        and the conjunct is named among the live ones."""
        import board_score
        _r, d = run(27)
        comp = board_score.assembly_component(d, 4)
        self.assertEqual(comp['count'], 1)
        self.assertIn('oob_pad_copper_count', comp['live_conjuncts_fired'])


if __name__ == '__main__':
    unittest.main()
