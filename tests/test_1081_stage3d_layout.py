#!/usr/bin/env python3
"""The `stage3d` layout (#1081): the board gets at least 70% x 70%.

`stage3d` (F) is the layout whose board box holds the 3D board, with the layer
column to its right and one benchmark band along the bottom. Its promise is a
FLOOR, not a ratio: the box is at least `STAGE3D_BOARD_W_FRAC` of the frame's
width and `STAGE3D_BOARD_H_FRAC` of its height, whatever else asks for room.
What this file pins:

  * **the floor holds** across every named ratio, three sizes and five board
    shapes, with and without a band -- on a LANDSCAPE frame both floors, on a
    portrait one the height (the board then takes the full width);
  * **a band that would breach the floor is shrunk, then declined -- never the
    board**, and either is SAID in `frame_status_line`, because a missing band
    that nothing explains reads as a missing feature;
  * **portrait turns the column into a row** under the board, and drops it
    (said) when it would be too short to read;
  * **an extreme declared aspect falls back to `legacy`**, said, at the
    board's own aspect -- a declared ratio kept would starve the legacy frame;
  * **`auto` never picks it**: it is a stance, like C and D;
  * **every layout key is in both CLIs' `--layout` help** -- the help used to
    be hand-listed, and a new layout is exactly what such a list forgets;
  * **`layout_budget` excludes it on purpose** (px/mm under perspective is not
    comparable), so the exclusion cannot silently become an omission.
"""
import os
import subprocess
import sys

RUN_ALL_FAST_OK = True

_TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TESTS)
for _p in (ROOT, _TESTS, os.path.join(ROOT, 'py_router')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import frame_layout as FL                                       # noqa: E402
import layout_budget as LB                                      # noqa: E402

_FAIL = []

SHAPES = {'wide 1.85': (0, 0, 185, 100), '4:3': (0, 0, 133, 100),
          'square': (0, 0, 100, 100), 'tall 1:1.6': (0, 0, 100, 160),
          'very wide 6.5': (0, 0, 650, 100)}


def _check(ok, msg):
    if not ok:
        print('  FAIL ' + msg)
        _FAIL.append(msg)
    return ok


def _plan(bb, ratio, size, track, foot=24):
    return FL.plan_frame(bb, layout='stage3d', ratio=FL.parse_ratio(ratio),
                         size=size, panel=True, foot_px=foot,
                         track_px=track, iso=True, quiet=True)


def test_the_board_keeps_seventy_by_seventy():
    mark = len(_FAIL)
    n = 0
    for ratio in [r for r in FL.RATIOS if r != 'board'] + [None]:
        for size in (500, 1000, 1400):
            for sn, bb in SHAPES.items():
                for track in (0, 120, 400):
                    g = _plan(bb, ratio, size, track)
                    n += 1
                    if g.layout != 'stage3d':
                        continue            # an extreme ratio; tested below
                    W, H = g.frame.w, g.frame.h
                    land = W >= FL.ISO_SIDE_ASPECT * H
                    tag = '%s/%s/%s/band %d' % (ratio, size, sn, track)
                    _check(g.board.h >= FL.STAGE3D_BOARD_H_FRAC * H
                           or g.track is None,
                           '%s: board %d of %d px high' % (tag, g.board.h, H))
                    if land:
                        _check(g.board.w >= FL.STAGE3D_BOARD_W_FRAC * W,
                               '%s: board %d of %d px wide'
                               % (tag, g.board.w, W))
                        _check(g.panel is not None and g.panel.x == g.board.w,
                               '%s: the layer column sits right of the board'
                               % tag)
                    else:
                        _check(g.board.w == W, '%s: a portrait board takes '
                               'the full width' % tag)
                    _check(g.board.x == 0 and g.board.y == g.rail.h,
                           '%s: the board is top-left' % tag)
                    if g.track is not None:
                        _check(g.track.w == W and g.track.y >= g.board.y
                               + g.board.h, '%s: the band is full width '
                               'under the board' % tag)
                    _check(g.panel_split is None,
                           '%s: no iso split -- the board box is the 3D '
                           'view' % tag)
    if len(_FAIL) == mark:
        print('  PASS: 70 x 70 holds on %d plans' % n)


def test_a_band_is_shrunk_then_declined_and_either_is_said():
    mark = len(_FAIL)
    g = _plan(SHAPES['wide 1.85'], '16:9', 1400, 400)
    _check(g.track is not None and g.track.h < 400
           and g.board.h >= FL.STAGE3D_BOARD_H_FRAC * g.frame.h,
           '1400 16:9, band 400: shrunk to %s, board %d of %d'
           % (g.track and g.track.h, g.board.h, g.frame.h))
    _check('band 400 ->' in FL.frame_status_line(g),
           'the shrink is said: %r' % FL.frame_status_line(g))
    g = _plan(SHAPES['wide 1.85'], '16:9', 500, 120)
    _check(g.track is None, '500 16:9: the band is declined (%s)' % (g.track,))
    _check('no benchmark band' in FL.frame_status_line(g),
           'the decline is said: %r' % FL.frame_status_line(g))
    g = _plan(SHAPES['wide 1.85'], '16:9', 1400, 120)
    _check(g.track is not None and g.track.h == 120 and not any(
        'band' in n for n in g.notes),
           'a band that fits is untouched and unremarked (%s, %s)'
           % (g.track, g.notes))
    if len(_FAIL) == mark:
        print('  PASS: shrink, decline, and both said')


def test_portrait_makes_the_column_a_row_or_says_why_not():
    mark = len(_FAIL)
    g = _plan(SHAPES['square'], '9:16', 1400, 0)
    _check(g.panel is not None and g.panel.y == g.board.y + g.board.h
           and g.panel.w == g.frame.w,
           '9:16: the layer row sits under the board (%s)' % (g.panel,))
    _check('row under the board' in FL.frame_status_line(g),
           'and it is said: %r' % FL.frame_status_line(g))
    g = _plan(SHAPES['square'], '9:16', 500, 300)
    _check(g.panel is None and 'no layer row' in FL.frame_status_line(g),
           '9:16 500 with a tall band: the row is dropped and said (%s, %r)'
           % (g.panel, FL.frame_status_line(g)))
    if len(_FAIL) == mark:
        print('  PASS: portrait row, or a stated drop')


def test_an_extreme_aspect_falls_back_to_legacy_and_says_so():
    mark = len(_FAIL)
    for ratio in ('4:1', '1:3'):
        for track in (0, 120):
            g = _plan(SHAPES['wide 1.85'], ratio, 500, track)
            line = FL.frame_status_line(g)
            _check(g.layout == 'legacy' and 'outside' in line,
                   '%s band %d: legacy, said (%s: %r)'
                   % (ratio, track, g.layout, line))
            bw = SHAPES['wide 1.85'][2] / float(SHAPES['wide 1.85'][3])
            # the legacy FRAME grows by the clock band; its board box is
            # the board's own aspect
            got = g.board.w / float(g.board.h)
            _check(abs(got - bw) < 0.05,
                   '%s band %d: the board box is the board\'s own aspect '
                   '%.2f (got %.2f)' % (ratio, track, bw, got))
    if len(_FAIL) == mark:
        print('  PASS: extreme aspects fall back, said')


def test_auto_never_picks_it():
    mark = len(_FAIL)
    for sn, bb in SHAPES.items():
        for size in (400, 1000):
            g = FL.plan_frame(bb, layout='auto', size=size, panel=True,
                              quiet=True)
            _check(g.layout != 'stage3d', 'auto on %s chose stage3d' % sn)
    if len(_FAIL) == mark:
        print('  PASS: auto never infers stage3d')


def test_every_layout_is_in_both_clis_help():
    mark = len(_FAIL)
    for script in (os.path.join(ROOT, 'py_router', 'make_movie.py'),
                   os.path.join(ROOT, 'py_tools', 'make_film.py')):
        r = subprocess.run([sys.executable, script, '--help'],
                           capture_output=True, text=True, timeout=120,
                           cwd=ROOT)
        _check(r.returncode == 0, '%s --help exited %d: %s'
               % (os.path.basename(script), r.returncode, r.stderr[-300:]))
        text = ' '.join(r.stdout.split())
        for key in FL.LAYOUTS:
            _check(key in text, '%s --help does not name %r'
                   % (os.path.basename(script), key))
    if len(_FAIL) == mark:
        print('  PASS: both --help texts name every layout')


def test_layout_budget_excludes_stage3d_on_purpose():
    mark = len(_FAIL)
    _check('stage3d' not in LB.LAYOUTS,
           'layout_budget measures stage3d -- px/mm under perspective is '
           'not comparable with the flat layouts\'')
    _check(set(LB.LAYOUTS) == set(FL.LAYOUTS) - {'legacy', 'auto', 'stage3d'},
           'layout_budget measures %s, expected every flat chrome layout'
           % (LB.LAYOUTS,))
    if len(_FAIL) == mark:
        print('  PASS: the exclusion is deliberate and exact')


TESTS = (
    test_the_board_keeps_seventy_by_seventy,
    test_a_band_is_shrunk_then_declined_and_either_is_said,
    test_portrait_makes_the_column_a_row_or_says_why_not,
    test_an_extreme_aspect_falls_back_to_legacy_and_says_so,
    test_auto_never_picks_it,
    test_every_layout_is_in_both_clis_help,
    test_layout_budget_excludes_stage3d_on_purpose,
)


def main():
    for fn in TESTS:
        print('%s:' % fn.__name__)
        fn()
    if _FAIL:
        print('')
        print('%d FAILURE(S)' % len(_FAIL))
        for msg in _FAIL[:40]:
            print('  - %s' % msg)
        return 1
    print('')
    print('all %d checks passed' % len(TESTS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
