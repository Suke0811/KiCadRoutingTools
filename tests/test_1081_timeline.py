#!/usr/bin/env python3
"""The 3D board replays the X-ray's frames, event for event (#1081).

`stage3d.timeline` rebuilds each frame's copper from the stage record alone
(a log position, the keys a growth stage hides, the highlight rows). The
claim that the 3D board shows "exactly the events the 2D X-ray shows" is only
as good as that rebuild, so this file checks it against the X-ray's OWN draw
calls: `BoardRenderer.frame` is wrapped, every argument it receives on a
Movie frame is recorded, and for every frame of a real film the timeline must
rebuild the same segments, the same vias, the same highlights -- on a film
with a flip, a glide, a rip-and-retract and a growth stage.

It also pins the side rules: with a Stage, the 3D board turns on the Stage's
own flip frames and nowhere else; without one, `activity_sides` turns only after
the back-side work has held for the dwell, never for a stray event.
"""
import json
import math
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TESTS)
for _p in (ROOT, _TESTS, os.path.join(ROOT, 'py_router')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import importlib.util                                           # noqa: E402
if importlib.util.find_spec('PIL') is None:
    print('SKIP: needs Pillow')
    sys.exit(77)

import film_chain_1081 as FC                                    # noqa: E402
import animate_route as A                                       # noqa: E402
import route_render as RR                                       # noqa: E402
from stage3d import timeline as TL                              # noqa: E402

_FAIL = []


def _check(ok, msg):
    print('  %s %s' % ('ok  ' if ok else 'FAIL', msg))
    if not ok:
        _FAIL.append(msg)


def _r(x):
    return round(float(x), 4)


def _seg_row(s):
    return (_r(s.start_x), _r(s.start_y), _r(s.end_x), _r(s.end_y),
            _r(s.width), s.layer)


def _via_row(v):
    ls = getattr(v, 'layers', None) or ['F.Cu', 'B.Cu']
    return (_r(v.x), _r(v.y), _r(v.size), _r(v.drill), ls[0], ls[-1])


def _film_with_calls(boards, **kw):
    """Film, capturing what `BoardRenderer.frame` drew for each Movie frame."""
    calls = []
    last = {}
    orig_frame = RR.BoardRenderer.frame
    orig_push = A.Movie._push_frame

    def _frame(self, segments=None, vias=None, highlight_segments=None,
               highlight_vias=None, **k):
        last['c'] = (sorted(_seg_row(s) for s in (segments or ())),
                     sorted(_via_row(v) for v in (vias or ())),
                     sorted(_seg_row(s) for s in (highlight_segments or ())),
                     sorted(_via_row(v) for v in (highlight_vias or ())))
        return orig_frame(self, segments=segments, vias=vias,
                          highlight_segments=highlight_segments,
                          highlight_vias=highlight_vias, **k)

    def _push(self, img, label, kind, **k):
        calls.append((kind, last.get('c')))
        return orig_push(self, img, label, kind, **k)
    RR.BoardRenderer.frame, A.Movie._push_frame = _frame, _push
    try:
        out = {}
        frames, _m, st, _g = FC.film(boards, stage_out=out, **kw)
    finally:
        RR.BoardRenderer.frame, A.Movie._push_frame = orig_frame, orig_push
    return frames, st, out, calls


def _rebuilt(tl, st):
    names = tl['layers']
    segs = sorted((_r(s[0]), _r(s[1]), _r(s[2]), _r(s[3]), _r(s[4]),
                   names[s[5]])
                  for i, s in enumerate(tl['segs'])
                  if i in set(TL.visible(tl['segs'], st['ns'], st['hide'])))
    vias = sorted((_r(v[0]), _r(v[1]), _r(v[2]), _r(v[3]), names[v[4]],
                   names[v[5]])
                  for v in (tl['vias'][i]
                            for i in TL.visible(tl['vias'], st['nv'])))
    hl_s = sorted((_r(h[0]), _r(h[1]), _r(h[2]), _r(h[3]), _r(h[4]),
                   names[int(h[5])]) for h in st['hl_s'])
    hl_v = sorted((_r(h[0]), _r(h[1]), _r(h[2]), _r(h[3]), names[int(h[4])],
                   names[int(h[5])]) for h in st['hl_v'])
    return segs, vias, hl_s, hl_v


def test_every_frame_is_rebuilt_from_the_record_alone():
    with FC.Chain() as c:
        # a rip-and-retract and a regrowth, after the flip: re-reveal the
        # copper board through a board with a chunk of it removed
        tr = FC.rip_trace(c.boards[-1], os.path.join(c.dir, 'trace.json'))
        frames, st, out, calls = _film_with_calls(c.boards, traces={3: tr})
        tl = TL.build(out)
        # the record must survive JSON: the page receives it that way
        tl = json.loads(json.dumps(tl))
        _check(len(tl['frames']) == len(frames) == len(calls),
               'one timeline frame per film frame (%d / %d / %d)'
               % (len(tl['frames']), len(frames), len(calls)))
        bad = []
        checked = 0
        for i, (kind, call) in enumerate(calls):
            if kind == 'flip' or call is None:
                continue          # a flip frame is the Stage's own picture
            checked += 1
            got = _rebuilt(tl, TL.state_for(tl, i))
            for what, a, b in zip(('segments', 'vias', 'highlights',
                                   'via highlights'), got, call):
                if a != b:
                    bad.append((i, what, len(a), len(b)))
        _check(checked > 40, 'checked %d Movie frames' % checked)
        _check(not bad, 'every frame\'s copper rebuilt from the record '
               'alone equals what the X-ray drew (first mismatches: %s)'
               % bad[:4])
        grown = [i for i, s in enumerate(tl['frames'])
                 if tl['states'][s]['hide']]
        _check(grown, '%d frames hide a growth stage\'s finished copper '
               '(the fixture must exercise it)' % len(grown))
        died = sum(1 for s in tl['segs'] if s[-1] >= 0)
        _check(died >= 24, '%d copper items die (the rip)' % died)


def test_the_board_faces_the_work_and_turns_back():
    """#1081: the board flips for bottom-side work and flips BACK for top
    work. The Stage alone never flips back -- a film whose last copper
    landed on F.Cu ended face-down (the phase-7 verification) -- so the 3D
    board follows the activity: U1's back-side glide is seen from the back,
    the F.Cu copper that follows from the front, the B.Cu after it from the
    back, and each turn completes BEFORE its work starts."""
    with FC.Chain() as c:
        out = {}
        tr = FC.rip_trace(c.boards[-1], os.path.join(c.dir, 'tr.json'))
        _f, _m, st, _g = FC.film(c.boards, stage_out=out, traces={3: tr})
        tl = TL.build(out)
        ang = [tl['states'][s]['angle'] for s in tl['frames']]
        log = out['log']
        glide_b = [i for i in range(len(log))
                   if 'U1' in (log[i].get('moving') or {})]
        f_cu = [i for i in range(len(log)) if log[i].get('kind') == 'frame'
                and log[i].get('active') == 'F.Cu']
        b_cu = [i for i in range(len(log)) if log[i].get('kind') == 'frame'
                and log[i].get('active') == 'B.Cu']
        _check(glide_b and all(abs(ang[i] - math.pi) < 1e-5
                               for i in glide_b),
               'U1\'s back-side glide is seen from the back, every frame '
               '(%s)' % [round(ang[i], 2) for i in glide_b])
        first_f = f_cu[:6]
        _check(first_f and all(abs(ang[i]) < 1e-5 for i in first_f),
               'the F.Cu copper that follows lands face-on, the board turned '
               'back (%s)' % [round(ang[i], 2) for i in first_f])
        _check(b_cu and abs(ang[b_cu[0]] - math.pi) < 1e-5,
               'and the B.Cu work after it faces the back again')
        _check(tl['side_rule'].startswith('activity:'),
               'the rule is named (%r)' % tl['side_rule'])


def _rec(active=None, moving=None, epoch=0):
    return {'active': active, 'moving': moving or {}, 'epoch': epoch}


def test_the_side_rule_waits_out_a_stray_event():
    fps = 6.0
    ep = [{'U1': [0, 0, 0, 'B.Cu'], 'C1': [0, 0, 0, 'F.Cu']}]
    rec = ([_rec('F.Cu')] * 20 + [_rec('B.Cu')] * 2
           + [_rec('F.Cu')] * 20 + [_rec('B.Cu')] * 30
           + [_rec('In1.Cu')] * 10)
    ang, turns = TL.activity_sides(rec, ep, fps)
    _check(len(ang) == len(rec), 'one angle per frame')
    turn = int(TL.AUTO_FLIP_S * fps)
    _check(all(v == 0.0 for v in ang[:42 - turn]),
           'a 2-frame stray back-side event does not flip the board')
    _check(turns == 1, 'one turn for the sustained back-side work (%d)'
           % turns)
    _check(all(abs(v - math.pi) < 1e-9 for v in ang[42:]),
           'the board already faces the back when the work starts, and an '
           'inner-layer event keeps it there')
    _check(0 < ang[42 - turn] < math.pi, 'the turn happens BEFORE the work')
    # a glide faces its parts' side, whatever the copper last touched
    rec = [_rec('F.Cu')] * 12 + [_rec(moving={'U1': [1, 1, 0]})] * 10
    ang, _t = TL.activity_sides(rec, ep, fps)
    _check(all(abs(v - math.pi) < 1e-9 for v in ang[12:]),
           'a back-side glide is watched from the back')


TESTS = (
    test_every_frame_is_rebuilt_from_the_record_alone,
    test_the_board_faces_the_work_and_turns_back,
    test_the_side_rule_waits_out_a_stray_event,
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
