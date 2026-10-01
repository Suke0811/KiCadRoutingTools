#!/usr/bin/env python3
"""#1105: `--decap-owners-first` seats the decap owner ICs before stage 2.5.

Stage 2.5 seats one cap per supply PIN of a PLACED IC. With no lock, zone or
declared row, nothing seats an IC before it, so on a flat board or a pile it
claimed nothing: run 38's StickHub pile, 0 of 38 caps ("no PLACED IC carries
a scoped cap's rail"). The opt-in stage 2.5a seats the ICs carrying a scoped
cap's rail first, with stage 3's own seat. It is NOT the default:
tests/test_placement_ab.py's `decap-owners-*` rows regressed a guard on all
four flat boards, so the default must stay off and say why when it claims 0.
"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_placer'))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

BOARD = os.path.join(ROOT, 'kicad_files', 'watchy.kicad_pcb')


def seed(**kw):
    from kicad_parser import parse_kicad_pcb
    from placement import seeder
    from placement.floorplan import emit_intent, intent_from_dict
    pcb = parse_kicad_pcb(BOARD)
    intent = emit_intent(pcb, BOARD, derive_decaps='auto')
    if not (intent.get('decaps') or {}).get('max_distance_mm'):
        raise unittest.SkipTest('the auto intent armed no decap limit')
    return seeder.seed_from_intent(
        parse_kicad_pcb(BOARD), BOARD, intent_from_dict(intent, BOARD), random.Random('1'),
        clearance=0.2, board_edge_clearance=0.3, grid_step=0.1, **kw)


class TestDecapOwnersFirst(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BOARD):
            raise unittest.SkipTest('watchy not present')
        cls.off = seed()
        cls.on = seed(decap_owners_first=True)

    def test_the_default_claims_nothing_and_says_why(self):
        st = self.off['decap_stage']
        self.assertTrue(st['armed'])
        self.assertEqual(st['claimed'], 0)
        self.assertEqual(st['owners_first'], [])
        self.assertIn('--decap-owners-first', st['reason'])

    def test_the_flag_seats_owners_and_claims_caps(self):
        st = self.on['decap_stage']
        self.assertTrue(st['owners_first'])
        self.assertTrue(all(r.startswith('U') for r in st['owners_first']))
        self.assertGreater(st['claimed'], 0)
        self.assertIsNone(st['reason'])

    def test_the_default_is_off(self):
        from placement import seeder
        self.assertFalse(seeder.DECAP_OWNERS_FIRST_DEFAULT)


if __name__ == '__main__':
    unittest.main()
