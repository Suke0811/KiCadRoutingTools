#!/usr/bin/env python3
"""The stage3d 3D board renders, deterministically, on SwiftShader (#1081).

Self-skips (exit 77) when this machine cannot render it at all -- no Node, no
`npm ci` in `py_router/stage3d`, no Chromium -- and SAYS which, because a skip
that does not name its cause reads like a pass.

What it pins, on the film_chain fixture (a flip, a glide, copper):

  * **the renderer is SwiftShader**, named in the result, so a GPU render --
    whose pixels depend on the machine -- is refused rather than trusted;
  * **two renders of the same timeline are the same bytes**, state for
    state: the page reads no clock, and the renderer is a CPU rasteriser;
  * **the pictures carry the story**: a state with copper differs from one
    without, the mid-flip state differs from both faces, and the back-side
    state is not the front;
  * **one frame per distinct state**, and the time per state is printed so a
    regression in cost is visible.
"""
import hashlib
import os
import shutil
import sys
import tempfile

_TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TESTS)
for _p in (ROOT, _TESTS, os.path.join(ROOT, 'py_router')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import importlib.util                                           # noqa: E402
if importlib.util.find_spec('PIL') is None:
    print('SKIP: needs Pillow')
    sys.exit(77)

from stage3d import render3d as R3                              # noqa: E402

OK, WHY = R3.available()
if not OK:
    print('SKIP: the 3D board cannot render on this machine: %s' % WHY)
    sys.exit(77)

from PIL import Image, ImageChops                               # noqa: E402
import film_chain_1081 as FC                                    # noqa: E402
from kicad_parser import parse_kicad_pcb                        # noqa: E402
from stage3d import scene as SC                                 # noqa: E402
from stage3d import timeline as TL                              # noqa: E402

_FAIL = []


def _check(ok, msg):
    print('  %s %s' % ('ok  ' if ok else 'FAIL', msg))
    if not ok:
        _FAIL.append(msg)


def _sha(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _diff(a, b):
    with Image.open(a) as x, Image.open(b) as y:
        d = ImageChops.difference(x.convert('RGB'), y.convert('RGB'))
        return d.convert('L').point(
            lambda q: 255 if q > 8 else 0).histogram()[255]


def test_the_board_renders_deterministically():
    tmp = tempfile.mkdtemp(prefix='t1081r_')
    try:
        with FC.Chain() as c:
            out = {}
            tr = FC.rip_trace(c.boards[-1], os.path.join(c.dir, 'tr.json'))
            _f, _m, st, _g = FC.film(c.boards, layout='stage3d', size=480,
                                     stage_out=out, traces={3: tr})
            tl = TL.build(out)
            sc = SC.build_scene(parse_kicad_pcb(c.boards[-1]))
            W, H = 320, 240
            a, ia, wa = R3.render(sc, tl, width=W, height=H,
                                  out_dir=os.path.join(tmp, 'a'))
            b, ib, wb = R3.render(sc, tl, width=W, height=H,
                                  out_dir=os.path.join(tmp, 'b'))
            print('    %s' % wa)
            print('    %s' % ia.get('tools'))
            _check(a is not None and b is not None,
                   'both renders produced frames (%s / %s)' % (wa, wb))
            if a is None or b is None:
                return
            _check('swiftshader' in str(ia.get('renderer')).lower(),
                   'the renderer is SwiftShader (%r)' % ia.get('renderer'))
            _check(len(a) == len(tl['states']),
                   'one frame per distinct state (%d)' % len(a))
            same = sum(1 for x, y in zip(a, b) if _sha(x) == _sha(y))
            _check(same == len(a), 'two renders are byte-identical, state '
                   'for state (%d of %d)' % (same, len(a)))
            with Image.open(a[0]) as im:
                _check(im.size == (W, H), 'frames are the board box size '
                       '(%s)' % (im.size,))
            flip_a, flip_b = [(x, y) for k, x, y in st.frame_log()
                              if k == 'flip'][0]
            fr = tl['frames']
            front = fr[flip_a - 1]
            mid = fr[(flip_a + flip_b) // 2]
            back = fr[flip_b + 1]
            last = fr[-1]
            _check(_diff(a[front], a[mid]) > 500 and
                   _diff(a[mid], a[back]) > 500,
                   'the mid-flip frame differs from both faces')
            _check(_diff(a[front], a[back]) > 500,
                   'the back is not the front')
            _check(_diff(a[back], a[last]) > 50,
                   'the copper the film reveals changes the picture')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


TESTS = (test_the_board_renders_deterministically,)


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
