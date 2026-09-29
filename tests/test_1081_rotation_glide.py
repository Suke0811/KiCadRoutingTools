#!/usr/bin/env python3
"""A part that turns while it glides turns DURING the glide (#1086).

`Stage._tween` glides a part by offsetting the DESTINATION parse backwards.
That offset was a pure translation, so a rotated part was drawn at its source
position with its destination orientation from the first glide frame on, and
the `tween=0` "before" frame -- whose whole job is to show the source --
showed the destination orientation too.

Pinned here, on the real `build_boards` + `Stage` path, with U1 moving 10 mm
AND turning 90 degrees (`film_chain_1081`, `rot_u1=90`):

  * **frame 0 is the SOURCE orientation.** The pad offsets from the part's
    origin on the first glide frame are compared against the SOURCE board's
    own parse (an independent reading: the parser, not the tween, says where
    those pads sit at the source rotation);
  * **mid-glide is mid-turn**, by the rotation the stage record carries;
  * **the landing frame is the parsed board BIT FOR BIT** (positions,
    `rect_rotation`, `rotation`), so the hand-off to the copper reveal cannot
    jump;
  * **`tween=0`'s "before" frame is the source orientation too**;
  * **the turn takes the SHORT way round** (`turn_deg`).
"""
import math
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import importlib.util                                           # noqa: E402
if importlib.util.find_spec('PIL') is None:
    print('SKIP: needs Pillow')
    sys.exit(77)

import film_chain_1081 as FC                                    # noqa: E402
import movie_camera as MC                                       # noqa: E402
from kicad_parser import parse_kicad_pcb                        # noqa: E402

_FAIL = []
REF = 'U1'


def _check(ok, msg):
    print('  %s %s' % ('ok  ' if ok else 'FAIL', msg))
    if not ok:
        _FAIL.append(msg)


def _offsets(fp):
    return [(p.global_x - fp.x, p.global_y - fp.y) for p in fp.pads]


def _record_snaps(boards, tween):
    """Film, capturing U1's pose and pad offsets on every Stage snap."""
    seen = []
    orig = MC.Stage._snap

    def _snap(self, label):
        fp = self.r.pcb.footprints.get(REF) if self.r.pcb else None
        if fp is not None and REF in (self.movie.moving or ()):
            seen.append((label, fp.x, fp.y, fp.rotation, _offsets(fp),
                         [p.rect_rotation for p in fp.pads]))
        return orig(self, label)
    MC.Stage._snap = _snap
    try:
        frames, m, st, g = FC.film(boards, tween=tween)
    finally:
        MC.Stage._snap = orig
    return seen, st


def _max_dev(a, b):
    return max(math.hypot(x0 - x1, y0 - y1) for (x0, y0), (x1, y1)
               in zip(a, b))


def test_the_glide_starts_at_the_source_orientation_and_lands_exactly():
    with FC.Chain(rot_u1=90.0) as c:
        src = parse_kicad_pcb(c.boards[1]).footprints[REF]    # before the move
        dst = parse_kicad_pcb(c.boards[2]).footprints[REF]    # after it
        _check(abs(((dst.rotation - src.rotation) % 360.0) - 90.0) < 1e-6,
               'fixture: U1 turns 90 degrees (%s -> %s)'
               % (src.rotation, dst.rotation))
        seen, _st = _record_snaps(c.boards, tween=10)
        _check(len(seen) == 10, 'U1 glides over 10 frames (%d)' % len(seen))
        if len(seen) != 10:
            return
        radius = max(math.hypot(x, y) for x, y in _offsets(src))
        first = seen[0]
        dev_src = _max_dev(first[4], _offsets(src))
        dev_dst = _max_dev(first[4], _offsets(dst))
        # t = smoothstep(1/10) ~ 0.028, so ~2.5 degrees of the turn is done
        _check(dev_src < 0.1 * radius < dev_dst,
               'frame 0: pads sit in the SOURCE orientation (%.3f mm off the '
               'source parse, %.3f mm off the destination; radius %.2f)'
               % (dev_src, dev_dst, radius))
        mid = seen[4]
        t = MC.smoothstep(5 / 10.0)
        want = dst.rotation - 90.0 * (1 - t)
        _check(abs(((mid[3] - want + 180.0) % 360.0) - 180.0) < 1e-6,
               'mid-glide rotation %.2f is %.0f%% of the turn (want %.2f)'
               % (mid[3], 100 * t, want))
        last = seen[-1]
        _check(last[4] == _offsets(dst),
               'the landing frame\'s pads equal the parsed board bit for bit')
        _check(last[5] == [p.rect_rotation for p in dst.pads]
               and last[3] == dst.rotation,
               'the landing frame\'s rotation and rect_rotation are the '
               'parsed ones (%s vs %s)' % (last[3], dst.rotation))


def test_the_before_frame_of_a_cut_shows_the_source():
    with FC.Chain(rot_u1=90.0) as c:
        src = parse_kicad_pcb(c.boards[1]).footprints[REF]
        dst = parse_kicad_pcb(c.boards[2]).footprints[REF]
        seen, _st = _record_snaps(c.boards, tween=0)
        before = [s for s in seen if 'before' in s[0]]
        _check(len(before) == 1, 'one "before" frame (%d)' % len(before))
        if not before:
            return
        _check(_max_dev(before[0][4], _offsets(src)) < 1e-6,
               'the "before" frame\'s pads are the source parse\'s (%.6f mm)'
               % _max_dev(before[0][4], _offsets(src)))
        _check(_max_dev(before[0][4], _offsets(dst)) > 0.1,
               'and not the destination\'s')


def test_the_turn_takes_the_short_way_round():
    # `source - destination`, folded: 0 -> 270 is the 90-degree turn BACK
    # from 270 to 0, never the 270-degree one.
    rows = [((0, 270), 90.0), ((270, 0), -90.0), ((350, 10), -20.0),
            ((10, 350), 20.0), ((0, 180), 180.0), ((45, 45), 0.0)]
    for (a, b), want in rows:
        got = MC.turn_deg({'from': [0, 0, a], 'to': [0, 0, b]})
        _check(abs(got - want) < 1e-9, 'turn %s -> %s is %s (want %s)'
               % (a, b, got, want))
    _check(MC.turn_deg({'from': [0, 0], 'to': [0, 0]}) == 0.0,
           'a pose without a rotation does not turn')


TESTS = (
    test_the_glide_starts_at_the_source_orientation_and_lands_exactly,
    test_the_before_frame_of_a_cut_shows_the_source,
    test_the_turn_takes_the_short_way_round,
)


def main():
    for fn in TESTS:
        print('%s:' % fn.__name__)
        fn()
    if _FAIL:
        print('')
        print('%d FAILURE(S)' % len(_FAIL))
        for msg in _FAIL:
            print('  - %s' % msg)
        return 1
    print('')
    print('all %d checks passed' % len(TESTS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
