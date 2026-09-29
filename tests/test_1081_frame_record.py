#!/usr/bin/env python3
"""Every frame of a film goes through ONE path, flipped or not (#1082-#1085).

A Stage flip to the back side used to hand its frames to a second render path
(`Stage._snap`'s mirrored branch, `_emit_flip`) that appended straight to
`movie.frames`. Four defects came out of that one bypass, all measured on the
chain in `film_chain_1081.py` (a flip at frames 35..41 of 73):

  * **#1082** -- no chrome record for those frames: 73 frames, 42 records, so
    the rail and the layer strip of 38 frames were drawn from ANOTHER frame's
    record (the flip read the copper of a step that had not happened yet);
  * **#1083** -- the caption stamped over the board on a layout whose rail
    already carries it (31 stamps);
  * **#1084** -- no `overlays=`, so a back-side glide drew no ghost or arrow;
  * **#1085** -- the copper a routing step reveals after the flip went
    through Movie's own path, which never mirrored: the hook meant to
    (`Stage.exit_step`) had no caller, so the film read B, F, B.

The fix mirrors inside `Movie._push_frame`, the one place a frame joins the
film. This file pins each symptom on the REAL `build_boards` + `Stage` path,
plus the stage-state record #1081's 3D board is rebuilt from, which must be
exactly as long as the film.
"""
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

try:
    from PIL import ImageChops, ImageOps
except ImportError as exc:
    print('SKIP: needs Pillow (%s)' % exc)
    sys.exit(77)

import film_chain_1081 as FC                                    # noqa: E402
import animate_route as A                                       # noqa: E402
import route_render as RR                                       # noqa: E402

_FAIL = []


def _check(ok, msg):
    print('  %s %s' % ('ok  ' if ok else 'FAIL', msg))
    if not ok:
        _FAIL.append(msg)


def _shots(st, kind):
    return [(a, b) for k, a, b in st.frame_log() if k == kind]


def test_one_chrome_record_and_one_stage_record_per_frame():
    """#1082: the rail and the strip of frame i are frame i's."""
    with FC.Chain() as c:
        out = {}
        frames, m, st, _g = FC.film(c.boards, stage_out=out)
        n = len(frames)
        _check(bool(_shots(st, 'flip')), 'the fixture flips (%s)'
               % [k for k, _a, _b in st.frame_log()])
        _check(len(m.chrome) == n,
               'one chrome record per frame: %d records, %d frames'
               % (len(m.chrome), n))
        _check(len(out.get('log') or ()) == n,
               'one stage record per frame: %d records, %d frames'
               % (len(out.get('log') or ()), n))
        # The flip happens on a copper-free board (S1 -> S2 are stripped), so
        # a flip frame's layer strip must show NO copper. Before the fix it
        # read the records the later copper reveal wrote: 151, then 604.
        a, b = _shots(st, 'flip')[0]
        live = [len(A._live(m.chrome[i]['live'])) for i in range(a, b)]
        _check(live and not any(live),
               'the flip frames\' strip copper is the board\'s (0): %s' % live)
        kinds = [r['kind'] for r in out['log'][a:b]]
        _check(kinds == ['flip'] * (b - a),
               'the stage record calls the flip frames flips: %s' % kinds)


def test_no_caption_over_the_board_when_a_rail_carries_it():
    """#1083: 0 over-board stamps on a rail layout -- and the legacy frame,
    which has no rail, still gets its caption (the stamp was not just
    deleted)."""
    calls = []
    orig = RR.BoardRenderer._label

    def _spy(self, img, text, *a, **k):
        calls.append(text)
        return orig(self, img, text, *a, **k)
    RR.BoardRenderer._label = _spy
    try:
        with FC.Chain() as c:
            FC.film(c.boards, layout='sidebar')
            rail = list(calls)
            del calls[:]
            FC.film(c.boards, layout='legacy')
            legacy = list(calls)
    finally:
        RR.BoardRenderer._label = orig
    _check(rail == [], 'sidebar (rail): no over-board caption (%d stamps: %s)'
           % (len(rail), rail[:3]))
    _check(any('B side' in t for t in legacy),
           'legacy (no rail): the flip is still captioned (%d stamps)'
           % len(legacy))


def test_a_back_side_glide_draws_its_ghost():
    """#1084: the ghost/arrow reaches the renderer on the back as on the
    front, and it changes pixels there (a control with the ghost disabled)."""
    import movie_camera as MC
    import place_motion as PM
    seen = []
    orig_frame = RR.BoardRenderer.frame
    orig_snap = MC.Stage._snap
    last = {}

    def _frame(self, *a, **k):
        last['ov'] = k.get('overlays')
        return orig_frame(self, *a, **k)

    def _snap(self, label):
        last.clear()
        ov = self.movie.overlay is not None
        mirrored = self._mirror
        out = orig_snap(self, label)
        if ov:
            seen.append((mirrored, last.get('ov') is not None))
        return out
    with FC.Chain() as c:
        RR.BoardRenderer.frame, MC.Stage._snap = _frame, _snap
        try:
            frames, _m, st, _g = FC.film(c.boards)
        finally:
            RR.BoardRenderer.frame, MC.Stage._snap = orig_frame, orig_snap
        back = [got for mir, got in seen if mir]
        front = [got for mir, got in seen if not mir]
        _check(front and all(front), 'front glide: ghost passed %d/%d'
               % (sum(front), len(front)))
        _check(back and all(back), 'back glide: ghost passed %d/%d'
               % (sum(back), len(back)))
        og = PM.ghost_overlay
        PM.ghost_overlay = lambda *a, **k: None
        try:
            plain, _m2, _st2, _g2 = FC.film(c.boards)
        finally:
            PM.ghost_overlay = og
        flip_at = _shots(st, 'flip')[0][0]
        a, b = [s for s in _shots(st, 'action') if s[0] >= flip_at][0]
        changed = sum(1 for i in range(a, b)
                      if ImageChops.difference(frames[i].convert('RGB'),
                                               plain[i].convert('RGB'))
                      .getbbox())
        _check(changed > 0, 'the back glide\'s ghost changes %d of %d frames'
               % (changed, b - a))


def test_copper_revealed_after_the_flip_is_mirrored():
    """#1085: the copper reveal after a flip to B is seen from the back. The
    last reveal frame and the first outro frame show one state at one view
    (the settle already brought the camera home), so their board boxes are
    EQUAL -- before the fix the outro frame equalled the reveal's MIRROR."""
    with FC.Chain() as c:
        out = {}
        frames, _m, st, g = FC.film(c.boards, stage_out=out)
        outro = _shots(st, 'outro')[0][0]
        flip_end = _shots(st, 'flip')[0][1]
        bx = g.board
        box = (bx.x, bx.y + bx.h // 3, bx.x + bx.w, bx.y + bx.h)
        rev = frames[outro - 1].convert('RGB').crop(box)
        first = frames[outro].convert('RGB').crop(box)
        same = ImageChops.difference(rev, first).getbbox()
        mirr = ImageChops.difference(ImageOps.mirror(rev), first).getbbox()
        _check(same is None and mirr is not None,
               'reveal frame %d and outro frame %d agree (diff %s; vs the '
               'mirror %s)' % (outro - 1, outro, same, mirr))
        flags = [r['mirror'] for r in out['log'][flip_end:]]
        _check(flags and all(flags),
               'every frame after the flip is recorded mirrored (%d of %d)'
               % (sum(flags), len(flags)))


TESTS = (
    test_one_chrome_record_and_one_stage_record_per_frame,
    test_no_caption_over_the_board_when_a_rail_carries_it,
    test_a_back_side_glide_draws_its_ghost,
    test_copper_revealed_after_the_flip_is_mirrored,
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
