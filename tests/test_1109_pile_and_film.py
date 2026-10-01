#!/usr/bin/env python3
"""#1109: one pile predicate, and a 2D film fallback that is said out loud.

(a) board_brief's `unplaced` read false on run 38's StickHub pile (a staging
    RING, 93% of parts off the outline) while check_floorplan's emitter
    called it a pile; the free-agent skill chose its mode from `unplaced`.
    `PlacementState.pile` is now the one test; board_brief publishes it.
(b) make_film fell back to the 2D X-ray with only a stderr line mid-log.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in ('py_placer', 'py_router', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _p))

from placement.placement_state import PlacementState  # noqa: E402

# A 40x40 board with 20 small parts on a ring OUTSIDE it: spread, not
# stacked, so `unplaced` (S1, or S2+S3) does not fire; S3 does.
RING = ['(kicad_pcb (version 20240108) (generator pcbnew)',
        '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))',
        '  (net 0 "") (net 1 "A")',
        '  (gr_rect (start 0 0) (end 40 40) (stroke (width 0.1) (type default))'
        ' (layer "Edge.Cuts"))']
for i in range(20):
    x, y = (-30 + 6 * i, -20) if i < 10 else (-30 + 6 * (i - 10), 70)
    RING.append(
        f'  (footprint "t:R" (layer "F.Cu") (at {x} {y})\n'
        f'    (property "Reference" "R{i + 1}" (at 0 0) (layer "F.SilkS"))\n'
        '    (fp_rect (start -1 -0.6) (end 1 0.6) (stroke (width 0.05)'
        ' (type default)) (layer "F.CrtYd"))\n'
        '    (pad "1" smd rect (at -0.5 0) (size 0.6 0.8) (layers "F.Cu")'
        ' (net 1 "A"))\n'
        '    (pad "2" smd rect (at 0.5 0) (size 0.6 0.8) (layers "F.Cu")'
        ' (net 1 "A")))')
RING.append(')')


class TestPilePredicate(unittest.TestCase):
    def test_each_arm(self):
        self.assertTrue(PlacementState(unplaced=True).pile)
        self.assertTrue(PlacementState(signals={'s3_outside': True}).pile)
        heap = PlacementState(partially_unplaced=True, n_footprints=10,
                              stacked_suspect_refs=[f'R{i}' for i in range(5)])
        self.assertTrue(heap.pile)
        few = PlacementState(partially_unplaced=True, n_footprints=10,
                             stacked_suspect_refs=['R1', 'R2'])
        self.assertFalse(few.pile)
        self.assertFalse(PlacementState().pile)

    def test_board_brief_publishes_pile_on_a_staging_ring(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'ring.kicad_pcb')
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(RING))
            r = subprocess.run(
                [sys.executable, '-X', 'utf8',
                 os.path.join(ROOT, 'py_tools', 'board_brief.py'), p],
                capture_output=True, text=True, cwd=ROOT, timeout=600)
        line = [ln for ln in r.stdout.splitlines()
                if ln.startswith('JSON_SUMMARY: ')]
        self.assertTrue(line, r.stdout[-2000:] + r.stderr[-2000:])
        summary = json.loads(line[-1][len('JSON_SUMMARY: '):])
        self.assertIs(summary['unplaced'], False)   # the gap #1109 is about
        self.assertIs(summary['pile'], True)

    def test_a_placed_board_is_not_a_pile(self):
        r = subprocess.run(
            [sys.executable, '-X', 'utf8',
             os.path.join(ROOT, 'py_tools', 'board_brief.py'),
             os.path.join(ROOT, 'kicad_files', 'splitflap_driver.kicad_pcb')],
            capture_output=True, text=True, cwd=ROOT, timeout=600)
        line = [ln for ln in r.stdout.splitlines()
                if ln.startswith('JSON_SUMMARY: ')]
        self.assertTrue(line, r.stderr[-2000:])
        self.assertIs(json.loads(line[-1][len('JSON_SUMMARY: '):])['pile'],
                      False)


class TestFilmBoardBoxLine(unittest.TestCase):
    def _line(self, report):
        import make_film
        from stage3d import film
        film.LAST_REPORT.clear()
        film.LAST_REPORT.update(report)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            make_film._board_box_line()
        film.LAST_REPORT.clear()
        return buf.getvalue()

    def test_fallback_is_a_warning_on_stdout(self):
        out = self._line({'mode': '2d', 'asked': 'auto',
                          'why': 'playwright-core is not installed'})
        self.assertIn('WARNING board box: 2D X-ray', out)
        self.assertIn('playwright-core is not installed', out)

    def test_asked_2d_and_3d_are_not_warnings(self):
        self.assertNotIn('WARNING', self._line({'mode': '2d', 'asked': '2d'}))
        out = self._line({'mode': '3d', 'asked': 'auto', 'renderer': 'x'})
        self.assertIn('board box: 3D', out)
        self.assertNotIn('WARNING', out)

    def test_apply_records_its_report(self):
        from stage3d import film
        film.LAST_REPORT.clear()
        frames, rep = film.apply([], None, None, None, None,
                                 stage_present=False, mode='2d')
        self.assertEqual(film.LAST_REPORT.get('mode'), '2d')
        self.assertEqual(film.LAST_REPORT.get('asked'), '2d')


if __name__ == '__main__':
    unittest.main()
