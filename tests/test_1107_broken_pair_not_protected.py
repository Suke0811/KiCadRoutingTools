#!/usr/bin/env python3
"""#1107: a diff-pair member with disconnected pads is not protected.

route_diff records a pair's members as 'diff-pair' protected (#521) when both
laid coupled copper, deliberately without asking whether they end terminal to
terminal (cparti's multi-point pair defers a leg BY DESIGN). Run 38's /U1D
was such a partial pair, its /U1D- was never finished, and the protection
then froze it broken: no later step could rip it, and route.py's hints named
it as a blocker in every failing box until the final board.

`protection_map` now lifts 'diff-pair' protection from a member whose pads
are disconnected on the board being routed; once connected it is protected
again. 'length-matched' and KiCad-locked protection are untouched.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

BOARD = (
    '(kicad_pcb (version 20240108) (generator pcbnew)\n'
    '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n'
    '  (net 0 "") (net 1 "/D+") (net 2 "/D-") (net 3 "/LM")\n'
    '  (gr_rect (start 0 0) (end 30 10) (stroke (width 0.1) (type default))'
    ' (layer "Edge.Cuts"))\n'
    '  (footprint "t:U" (layer "F.Cu") (at 5 5)\n'
    '    (property "Reference" "U1" (at 0 0) (layer "F.SilkS"))\n'
    '    (pad "1" smd rect (at 0 -1) (size 0.6 0.6) (layers "F.Cu") (net 1 "/D+"))\n'
    '    (pad "2" smd rect (at 0 1) (size 0.6 0.6) (layers "F.Cu") (net 2 "/D-"))\n'
    '    (pad "3" smd rect (at 0 3) (size 0.6 0.6) (layers "F.Cu") (net 3 "/LM")))\n'
    '  (footprint "t:J" (layer "F.Cu") (at 25 5)\n'
    '    (property "Reference" "J1" (at 0 0) (layer "F.SilkS"))\n'
    '    (pad "1" smd rect (at 0 -1) (size 0.6 0.6) (layers "F.Cu") (net 1 "/D+"))\n'
    '    (pad "2" smd rect (at 0 1) (size 0.6 0.6) (layers "F.Cu") (net 2 "/D-"))\n'
    '    (pad "3" smd rect (at 0 3) (size 0.6 0.6) (layers "F.Cu") (net 3 "/LM")))\n'
    # /D+ is finished; /D- stops half way; /LM is open but length-matched.
    '  (segment (start 5 4) (end 25 4) (width 0.2) (layer "F.Cu") (net 1))\n'
    '  (segment (start 5 6) (end 15 6) (width 0.2) (layer "F.Cu") (net 2))\n'
    ')\n')


def protection(board_text, mapping):
    import importlib
    import protected_nets
    importlib.reload(protected_nets)
    from kicad_parser import parse_kicad_pcb
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'b.kicad_pcb')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(board_text)
        with open(protected_nets.pro_path_for_board(p), 'w',
                  encoding='utf-8') as fh:
            json.dump({protected_nets.PRO_NAMESPACE:
                       {protected_nets.PRO_KEY: mapping}}, fh)
        return protected_nets.protection_map(parse_kicad_pcb(p), p)


class TestBrokenPairMember(unittest.TestCase):
    MAP = {'/D+': 'diff-pair', '/D-': 'diff-pair', '/LM': 'length-matched'}

    def test_the_open_member_is_lifted_the_finished_one_kept(self):
        m = protection(BOARD, self.MAP)
        self.assertEqual(m.get('/D+'), 'diff-pair')
        self.assertNotIn('/D-', m)
        # Only diff-pair protection is lifted.
        self.assertEqual(m.get('/LM'), 'length-matched')

    def test_finishing_the_member_restores_its_protection(self):
        done = BOARD.replace(
            '(end 15 6) (width 0.2) (layer "F.Cu") (net 2))',
            '(end 25 6) (width 0.2) (layer "F.Cu") (net 2))')
        m = protection(done, self.MAP)
        self.assertEqual(m.get('/D-'), 'diff-pair')
        self.assertEqual(m.get('/D+'), 'diff-pair')

    def test_the_lift_is_said(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            protection(BOARD, self.MAP)
        self.assertIn('Protection lifted: /D- (diff-pair)', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
