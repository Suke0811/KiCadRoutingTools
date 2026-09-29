#!/usr/bin/env python3
"""The defaults #1081's requester asked for: stage3d and light (#1081).

  * **the film's layout is `stage3d`** when nothing names one -- no flag, no
    `$KICAD_MOVIE_LAYOUT` -- through the ONE resolver both front ends use
    (`frame_layout.resolve_layout_aspect`), so make_movie, make_film, the GUI
    recorder and place_route_loop's film all get it; the variable still
    overrides;
  * **every render is `light`** when nothing names a theme: the resolver
    (`render_theme.default_theme`), a `BoardRenderer` built with no theme,
    `layer_palette` with no theme, and the fallback for a bad name;
    `$KICAD_RENDER_THEME=dark` still overrides, per process.

Each check runs in a child process, because `env_knobs` reads the
environment once at import.
"""
import os
import subprocess
import sys

RUN_ALL_FAST_OK = True

_TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TESTS)
_FAIL = []


def _check(ok, msg):
    print('  %s %s' % ('ok  ' if ok else 'FAIL', msg))
    if not ok:
        _FAIL.append(msg)


_PROBE = r'''
import sys
sys.path[:0] = [%r, %r]
import frame_layout, render_theme, route_render
from kicad_parser import parse_kicad_pcb
layout, aspect = frame_layout.resolve_layout_aspect(None, None)
r = route_render.BoardRenderer(parse_kicad_pcb(%r), size=64)
print('LAYOUT', layout)
print('THEME', render_theme.default_theme().name)
print('RENDERER', r.theme.name)
print('PALETTE', render_theme.layer_palette(['F.Cu', 'B.Cu'])['F.Cu']
      == render_theme.default_theme().layers[0])
print('FALLBACK', render_theme.theme('chartreuse', strict=False).name)
import env_knobs
print('BOARD3D', env_knobs.MOVIE_BOARD3D)
'''


def _probe(env_extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ('KICAD_MOVIE_LAYOUT', 'KICAD_RENDER_THEME',
                        'KICAD_MOVIE_BOARD3D')}
    env.update(env_extra)
    code = _PROBE % (ROOT, os.path.join(ROOT, 'py_router'),
                     os.path.join(ROOT, 'kicad_files',
                                  'splitflap_driver.kicad_pcb'))
    r = subprocess.run([sys.executable, '-X', 'utf8', '-c', code],
                       capture_output=True, text=True, env=env, timeout=300,
                       cwd=ROOT)
    out = {}
    for line in r.stdout.splitlines():
        k, _s, v = line.partition(' ')
        out[k] = v
    if r.returncode:
        out['_err'] = r.stderr[-400:]
    return out


def test_the_defaults_are_stage3d_and_light():
    got = _probe({})
    _check(not got.get('_err'), 'the probe ran (%s)' % got.get('_err'))
    _check(got.get('LAYOUT') == 'stage3d',
           'no flag, no variable: the film is stage3d (%r)' % got.get('LAYOUT'))
    _check(got.get('THEME') == 'light', 'the default theme is light (%r)'
           % got.get('THEME'))
    _check(got.get('RENDERER') == 'light',
           'a BoardRenderer built with no theme draws light (%r)'
           % got.get('RENDERER'))
    _check(got.get('PALETTE') == 'True',
           'layer_palette with no theme follows the default')
    _check(got.get('BOARD3D') == 'auto',
           'the board is auto (3D when it can) unless told (%r)'
           % got.get('BOARD3D'))
    _check(got.get('FALLBACK') == 'light',
           'a bad theme name falls back to the default (%r)'
           % got.get('FALLBACK'))


def test_the_variables_still_override():
    got = _probe({'KICAD_MOVIE_LAYOUT': 'legacy', 'KICAD_RENDER_THEME': 'dark',
                  'KICAD_MOVIE_BOARD3D': '2d'})
    _check(got.get('LAYOUT') == 'legacy' and got.get('THEME') == 'dark'
           and got.get('RENDERER') == 'dark' and got.get('BOARD3D') == '2d',
           '$KICAD_MOVIE_LAYOUT=legacy and $KICAD_RENDER_THEME=dark win (%s)'
           % got)


TESTS = (test_the_defaults_are_stage3d_and_light,
         test_the_variables_still_override)


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
