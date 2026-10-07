#!/usr/bin/env python3
"""What stands between a bus pair's two teeth (awx/pair_teeth.py).

  python3 tests/test_622_pair_teeth.py

A pair's two legs leaving an array by one face on one layer close to their gap just past their teeth; another net's
copper between the teeth splits the pair there. On hand-made copper (a ball box to x = 9.6, a pair's legs P and N on
B.Cu ending at x = 10.0, 0.8 mm apart, as the zynq U1's DDR3_DQS1 teeth stood):

1. LIVENESS: teeth() finds each leg's tooth -- its end furthest past the box -- on its layer and face; else the checks
   below test nothing (BROKEN TEST);
2. another net's B.Cu track along the gap between the two legs, ending between the teeth (the zynq's NetR3_2), splits
   the pair; the same track on F.Cu does not, nor one a row outside the legs;
3. another net's via just past the teeth, between them, splits it on any layer;
4. legs leaving by two layers are reported apart.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'awx'))
import pair_teeth as pt  # noqa: E402

BAD = []


def check(ok, what):
    print(('ok    ' if ok else 'FAIL  ') + what)
    if not ok:
        BAD.append(what)


BOX = (0.0, -1.0, 9.6, 2.0)
NAMES = {1: 'DQS_P', 2: 'DQS_N', 3: 'OTHER'}
PAIRS = {'DQS': ('DQS_P', 'DQS_N')}
LEGS = [((8.0, 0.0), (10.0, 0.0), 'B.Cu', 1), ((8.0, 0.8), (10.0, 0.8), 'B.Cu', 2)]


def run(extra_segs=(), vias=(), legs=LEGS):
    segs = list(legs) + list(extra_segs)
    t = pt.teeth(segs, NAMES, {'DQS_P', 'DQS_N'}, BOX)
    return t, pt.between(PAIRS, t, segs, list(vias), NAMES, 0.4)


# 1. liveness
t0, r0 = run()
if t0.get('DQS_P') != ((10.0, 0.0), (1, 0), 'B.Cu') or t0.get('DQS_N') != ((10.0, 0.8), (1, 0), 'B.Cu'):
    print(f'BROKEN TEST: teeth() found {t0}, not the two B.Cu ends at x = 10.0 facing +x')
    sys.exit(2)
check(r0 == {'DQS': ('B.Cu', (1, 0), [])}, f'liveness: the bare pair has nothing between its teeth ({r0})')

# 2. a track along the gap between the legs
gap = ((5.0, 0.4), (10.05, 0.4))
_t, r = run([gap + ('B.Cu', 3)])
check(r['DQS'][2] == ['OTHER'], f'another net\'s B.Cu escape ending between the teeth splits the pair ({r})')
_t, r = run([gap + ('F.Cu', 3)])
check(r['DQS'][2] == [], f'the same escape on F.Cu does not ({r})')
_t, r = run([((5.0, 1.6), (10.05, 1.6), 'B.Cu', 3)])
check(r['DQS'][2] == [], f'one a row outside the legs does not ({r})')

# 3. a via between the teeth
_t, r = run(vias=[((10.6, 0.4), 3)])
check(r['DQS'][2] == ['OTHER'], f'another net\'s via just past the teeth, between them, splits the pair ({r})')
_t, r = run(vias=[((10.6, 0.4), 1)])
check(r['DQS'][2] == [], f'a via of the pair\'s own leg does not ({r})')

# 4. apart
_t, r = run(legs=[LEGS[0], ((8.0, 0.8), (10.0, 0.8), 'F.Cu', 2)])
check(r == {'DQS': 'apart'}, f'legs on two layers are reported apart ({r})')

print(f'\n{"PASS" if not BAD else "FAIL"}: {len(BAD)} failure(s)' + (': ' + '; '.join(BAD) if BAD else ''))
sys.exit(1 if BAD else 0)
