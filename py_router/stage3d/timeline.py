#!/usr/bin/env python3
"""The film's per-frame stage record -> a timeline a 3D page can draw (#1081).

`animate_route.build_boards(stage_out=)` records, for EVERY frame, where the
film is in the copper edit logs, what is highlighted, what a growth stage
hides under itself, which parts are mid-glide and where, whether the board is
seen from the back, and whether it is mid-flip. This module turns that record
into data a renderer can replay with no knowledge of how the film was made:

  * **copper as lifetimes.** Each edit-log entry becomes one item with the op
    index it was born at and the op index it died at. A frame at log position
    `n` shows exactly the items with `born < n <= died` -- the same set
    `_OpLog.state_at(n)` returns, which `test_1081_timeline` checks frame by
    frame against the X-ray's own draw calls;
  * **frames as small states**: that position, the items a growth stage hides,
    the highlight rows, the moving parts' poses, the board side and flip.
    Frames with identical states are coalesced (`unique`), because a rip hold
    or a caption-only change repeats a picture the renderer need not redraw.

**The flip is the Stage's.** When the film had a Stage, its recorded flip
frames and mirror flag are the only source of the board's side, so the 3D
board turns on exactly the frames the X-ray does. A film with no Stage has no
flip in 2D at all; there `auto_sides` applies a documented 3D-only rule --
B-side activity faces the camera to the back, with a minimum dwell and no
flip for a stray event -- and says so in the timeline's `side_rule`.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import List, Optional

#: A 3D-only flip (films without a Stage) needs the new side to hold this long
#: before the board turns, and the board holds a side at least this long.
AUTO_DWELL_S = 1.0
#: ...and turns over this long.
AUTO_FLIP_S = 1.0


def _is_gone(val) -> bool:
    try:
        from animate_route import _GONE
    except Exception:                                          # noqa: BLE001
        return False
    return val is _GONE


def _row(val, width):
    """A `_Seg`/`_Via` adapter back to its numeric row."""
    if width == 'seg':
        return (float(val.start_x), float(val.start_y), float(val.end_x),
                float(val.end_y), float(val.width), val.layer)
    ls = getattr(val, 'layers', None) or ['F.Cu', 'B.Cu']
    return (float(val.x), float(val.y), float(val.size), float(val.drill),
            ls[0], ls[-1])


def _ops_items(ops, kind):
    items = []
    live = {}
    for i, (key, val) in enumerate(ops):
        j = live.pop(key, None)
        if j is not None:
            items[j][-1] = i          # replaced or removed at op i
        if _is_gone(val):
            continue
        items.append(list(_row(val, kind)) + [i, -1])
        live[key] = len(items) - 1
    return items


def _key_to_item(ops, n):
    """`{key: item index}` for the items alive after `n` ops."""
    live = {}
    count = 0
    for i, (key, val) in enumerate(ops):
        if i >= n:
            break
        live.pop(key, None)
        if not _is_gone(val):
            live[key] = count
        if not _is_gone(val):
            count += 1
    return live


def side_of(rec) -> str:
    return 'B' if rec.get('mirror') else 'F'


def flip_angle(rec) -> float:
    """The board's turn about its long axis, radians: 0 = the front faces
    the camera, pi = the back. A Stage flip frame carries `(t, to_side)`."""
    fl = rec.get('flip')
    if fl:
        t, to = float(fl[0]), fl[1]
        return math.pi * t if to == 'B' else math.pi * (1.0 - t)
    return math.pi if rec.get('mirror') else 0.0


def auto_sides(log, fps, dwell_s=AUTO_DWELL_S, flip_s=AUTO_FLIP_S):
    """Per-frame flip angle for a film with NO Stage: face the back while the
    work is on the back. `active` names the layer each frame's event touched;
    `B.Cu` wants the back, `F.Cu` the front, an inner layer keeps whatever is
    showing. A switch happens only when the wanted side has held for
    `dwell_s` AND the current side has been shown that long; it then turns
    over `flip_s`. Returns (angles, flips) where flips counts the turns."""
    dwell = max(1, int(round(dwell_s * fps)))
    turn = max(1, int(round(flip_s * fps)))
    want = []
    cur = 'F'
    for r in log:
        a = r.get('active') or ''
        if a == 'B.Cu':
            cur = 'B'
        elif a == 'F.Cu':
            cur = 'F'
        want.append(cur)
    side, held, pend, since = 'F', dwell, None, 0
    angles = []
    flips = 0
    turning = None                  # (start frame, to side)
    for i, w in enumerate(want):
        if turning is not None:
            k = (i - turning[0] + 1) / float(turn)
            if k >= 1.0:
                side, held, turning = turning[1], 0, None
            else:
                a = math.pi * k if turning[1] == 'B' else math.pi * (1 - k)
                angles.append(a)
                continue
        held += 1
        if w != side:
            if pend != w:
                pend, since = w, 0
            since += 1
            if since >= dwell and held >= dwell:
                turning = (i, w)
                flips += 1
                pend = None
        else:
            pend = None
        angles.append(math.pi if side == 'B' else 0.0)
    return angles, flips


def build(stage_out, *, fps=6.0, stage_present=True) -> dict:
    """The JSON timeline for one film.

    `stage_out` is what `build_boards(stage_out=)` filled. The result:
    `layers`, `segs` / `vias` (rows with `born`, `died` op indices),
    `epochs` (part poses per board), `frames` (one per film frame, each an
    index into `states`), `states` (the distinct per-frame states) and
    `side_rule` ('stage' or 'auto: ...')."""
    log = stage_out['log']
    segs = _ops_items(stage_out['ops_s'], 'seg')
    vias = _ops_items(stage_out['ops_v'], 'via')
    layers = list(stage_out['layers'])
    li = {n: i for i, n in enumerate(layers)}
    for s in segs:
        s[5] = li.get(s[5], 0)
    for v in vias:
        v[4], v[5] = li.get(v[4], 0), li.get(v[5], len(layers) - 1)
    if stage_present:
        angles = [flip_angle(r) for r in log]
        rule = 'stage'
    else:
        angles, nf = auto_sides(log, fps)
        rule = ('auto: B.Cu work faces the back after %.1f s, %d turn(s); '
                'the 2D film has no flip' % (AUTO_DWELL_S, nf))
    ops_s = stage_out['ops_s']
    states = []
    index = {}
    frames = []
    for i, r in enumerate(log):
        hide = []
        if r.get('hide'):
            k2i = _key_to_item(ops_s, r['ns'])
            hide = sorted(k2i[k] for k in r['hide'] if k in k2i)
        st = {'ns': r['ns'], 'nv': r['nv'], 'hide': hide,
              'hl_s': [list(x) for x in r.get('hl_s') or ()],
              'hl_v': [list(x) for x in r.get('hl_v') or ()],
              'color': list(r['color']) if r.get('color') else None,
              'epoch': r['epoch'],
              'moving': {k: list(v) for k, v in
                         sorted((r.get('moving') or {}).items())},
              'angle': round(angles[i], 6),
              'active': r.get('active')}
        h = hashlib.sha1(json.dumps(st, sort_keys=True).encode()).hexdigest()
        if h not in index:
            index[h] = len(states)
            states.append(st)
        frames.append(index[h])
    return {'layers': layers, 'segs': segs, 'vias': vias,
            'epochs': [{k: list(v) for k, v in e.items()}
                       for e in stage_out['epochs']],
            'frames': frames, 'states': states, 'side_rule': rule}


def visible(items, n, hide=()) -> List[int]:
    """Indices of the copper items shown at log position `n`: born before
    it, not dead by it, and not hidden by a growth stage."""
    h = set(hide)
    return [i for i, it in enumerate(items)
            if it[-2] < n and (it[-1] < 0 or it[-1] >= n) and i not in h]


def state_for(timeline, frame) -> Optional[dict]:
    fr = timeline['frames']
    if not 0 <= frame < len(fr):
        return None
    return timeline['states'][fr[frame]]
