#!/usr/bin/env python3
"""#1105: test_placement_ab's pile input mode measures a PILE, not a board.

The pile rows (and the pilot, tests/measure_1105_pile_variants.py) run on the
basis `tests/1105_pile_ab_prereg.json` fixed: the corpus board staged as an
unaided pile, one intent the CLI emits with `--decaps-from` the board itself,
and place_seed's own seed scope. Each case pins one way that could silently
become the corpus basis again:

* the staged board reads as unplaced, the CLI intent carries the decap limit
  and withholds the pile's pose claims, and the mechanical refs reach the
  intent as fixed poses (only the CLI compiles mechanical.json);
* `stage()` arms the unaided provenance regime over pile/ ONLY: the arms,
  written beside it, are outside every regime;
* the seed scope is place_seed's without --force: the stacked suspects;
* a board that is NOT a pile is refused with an AssertionError that is not
  `PileIneligible` -- a placed board measured under a pile's name is a broken
  measurement, not an ineligible board;
* a pile row that also states seed_intents is refused before anything is
  seated.

    python3 tests/test_1105_pile_input.py [name-substring ...]
"""
import os
import shutil
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
for _d in ('py_router', 'py_placer', 'py_tools'):
    sys.path.insert(0, os.path.join(ROOT, _d))
sys.path.insert(0, TESTS_DIR)

import test_placement_ab as AB                       # noqa: E402

RUN_ALL_TIMEOUT = 600
ESP = os.path.join(AB.BOARDS, 'esp_prog.kicad_pcb')


def test_the_pile_basis_is_a_pile():
    from kicad_parser import parse_kicad_pcb
    from placement import provenance
    from placement.placement_state import assess_placement
    with tempfile.TemporaryDirectory() as td:
        pile, intent, doc, refs = AB._pile_inputs(ESP, td)
        assert os.path.dirname(pile) == os.path.join(td, 'pile'), pile
        st = assess_placement(parse_kicad_pcb(pile), pile)
        assert st.partially_unplaced or st.unplaced, st.reasons
        assert doc['context']['pose_claims_withheld'], doc['context']
        assert doc['decaps']['max_distance_mm'] is not None, doc['decaps']
        assert doc['context']['decap_census']['reference_board'] == ESP
        # mechanical.json (USB1 and the two Ref* markers on esp_prog) reached
        # the intent as fixed poses -- the CLI's job, not emit_intent's
        fixed = {str(f['ref']) for f in intent.fixed_poses}
        assert 'USB1' in fixed, fixed
        # place_seed's scope without --force: the pile, not the mechanical
        assert refs is not None and 'USB1' not in refs and 'U1' in refs, refs
        assert refs == set(st.stacked_suspect_refs), (refs, st)
        # the regime covers pile/ and nothing the arms write
        assert provenance.regime_for(pile) == os.path.join(td, 'pile')
        for arm in ('off', 'on'):
            assert provenance.regime_for(
                os.path.join(td, f'{arm}.kicad_pcb')) is None, arm
        f = AB._pile_forecast(doc)
        assert f.get('scope', 0) >= 1, f
    print(f"  PASS: esp_prog pile -- {len(refs)} seeded, fixed "
          f"{sorted(fixed)}, limit {doc['decaps']['max_distance_mm']}, "
          f"forecast scope {f['scope']}, regime on pile/ only")


def test_a_placed_board_is_refused_not_ineligible():
    """Stage a 'pile' that is the placed board itself: the helper must raise,
    and must not raise the eligibility exception, which a caller treats as a
    legitimate pinned-neutral outcome."""
    real = None
    stress = os.path.join(ROOT, 'tests', 'stress')
    if stress not in sys.path:
        sys.path.insert(0, stress)
    import stage_unaided
    real = stage_unaided.stage

    def fake(src, out_board, *a, **k):
        shutil.copy2(src, out_board)
        return {}
    stage_unaided.stage = fake
    try:
        with tempfile.TemporaryDirectory() as td:
            try:
                AB._pile_inputs(ESP, td)
            except AB.PileIneligible as exc:
                raise AssertionError(f"a placed board read as INELIGIBLE: "
                                     f"{exc}")
            except AssertionError as exc:
                assert 'does not read it as unplaced' in str(exc), exc
            else:
                raise AssertionError("a placed board was accepted as a pile")
    finally:
        stage_unaided.stage = real
    print("  PASS: a placed board is refused as a broken measurement")


def test_a_pile_row_reads_no_seed_intents():
    row = {'name': 'pile-ctl', 'board': 'esp_prog.kicad_pcb', 'corridors': [],
           'engine': 'seed', 'input': 'pile',
           'seed_intents': {'off': 'off', 'on': 'auto', 'grade': 'auto'},
           'seed_off': {'decap_claim_after_ics': False},
           'seed_on': {'decap_claim_after_ics': True},
           'signal': 'intent_errors', 'guard': ('crossings',)}
    with tempfile.TemporaryDirectory() as td:
        try:
            AB.run_row(row, td)
        except AssertionError as exc:
            assert 'seed_intents is not read' in str(exc), exc
        else:
            raise AssertionError("a pile row with seed_intents ran")
        assert not os.path.isdir(os.path.join(td, 'pile-ctl', 'pile')), (
            "the refusal came after the pile was staged")
    print("  PASS: a pile row stating seed_intents is refused before staging")


TESTS = [
    test_the_pile_basis_is_a_pile,
    test_a_placed_board_is_refused_not_ineligible,
    test_a_pile_row_reads_no_seed_intents,
]


if __name__ == '__main__':
    want = sys.argv[1:]
    for t in TESTS:
        if want and not any(w in t.__name__ for w in want):
            continue
        print(f"--- {t.__name__}")
        t()
    print("ALL PASS")
