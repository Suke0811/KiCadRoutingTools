#!/usr/bin/env python3
"""The film's bands and panels, ONE implementation for both front ends (#1087).

`make_movie` and `make_film.build_film` each re-implemented the same
post-pass pipeline -- discover the search behind the film, measure the
placement panels, reserve the band, ask whether the iso panel can run, then
compose the placement panels, the attempts band (or, on stage3d, the
benchmark band) and the iso panel -- so every film-level feature had to be
threaded twice, and #1081's stage3d band was the latest to pay that. This
module is that pipeline, in two halves around `animate_route.build_boards`:

  * `plan(...)` runs BEFORE the frame is planned and answers what
    `build_boards` must reserve (`attempts_band`, `iso_panel`);
  * `compose(...)` and `compose_iso(...)` run AFTER, on the frames.

What stays in each front end is what is genuinely its own: make_movie's run
clock, make_film's badges and cards. Every status line prints with the
caller's `who` prefix, and -- as before -- even when quiet, because a band
with no dialog control has no other way to say whether it ran.
"""
from __future__ import annotations

import os
import sys
from typing import Any, NamedTuple, Optional


class Bands(NamedTuple):
    stage3d: bool
    btrack: Any                 # movie_benchmark.BenchTrack, stage3d only
    track: Any                  # movie_attempts.Track (verdict band)
    verdict: bool
    ptrack: Any                 # movie_placement track, or None
    pwhy: str
    pfn: Any                    # movie_placement.band_px(...)
    band: Any                   # what build_boards reserves (attempts_band)
    iso_box: bool               # what build_boards reserves (iso_panel)
    placement_asked: Any


def _say(who, msg):
    print(('%s: %s' % (who, msg)) if who else msg, file=sys.stderr)


def plan(steps, final, layout, *, attempts=None, attempts_ledger=None,
         attempts_from=None, placement=None, want_iso=False, iso_opts=None,
         quiet=False, who='make_movie') -> Bands:
    """Everything the frame must reserve, decided before it is planned.

    `attempts`: a Track (use it), False (the OFF arm) or None (discover:
    `attempts_ledger` if named, else beside `attempts_from` or the final
    board; `attempts_from=''` means do not look). `placement`: `{'off',
    'ledger', 'benchmark', 'benchmark_score', 'intent'}`."""
    placement = dict(placement or {})
    stage3d = str(layout or '').strip().lower() == 'stage3d'
    here = os.path.dirname(os.path.abspath(final)) if final else ''
    btrack = None
    if stage3d:
        # #1081. ONE band, the benchmark band, which folds the verdict band
        # and the placement panels into one curve -- neither is measured
        # or reserved, and there is no iso panel: the board box IS the 3D
        # view.
        try:
            import movie_benchmark
            if attempts is not False and attempts_from != '':
                led = attempts_ledger or placement.get('ledger')
                btrack = (movie_benchmark.from_converge_ledger(led) if led
                          else movie_benchmark.discover(
                              attempts_from or here))
            if btrack is not None and placement.get('benchmark'):
                btrack = movie_benchmark.with_benchmark(
                    btrack, movie_benchmark.grade_benchmark(
                        placement['benchmark'],
                        placement.get('benchmark_score')))
        except Exception as exc:                               # noqa: BLE001
            _say(who or 'make_movie', 'no benchmark band (%s)' % exc)
            btrack = None
        return Bands(True, btrack, None, False, None, 'folded into the '
                     'benchmark band (stage3d)', None,
                     bool(btrack is not None and len(btrack.points) >= 2),
                     False, False)
    # #946/C4: the attempts are found BEFORE the frame is planned, so the
    # band is RESERVED in the layout (`plan_frame(track_px=)`) rather than
    # grown under every frame afterwards.
    track = None
    try:
        import movie_attempts
        if attempts is False or attempts_from == '':
            track = None
        elif attempts is not None:
            track = attempts
        elif attempts_ledger:
            track = movie_attempts.attempts_from_converge_ledger(
                attempts_ledger)
        else:
            track = movie_attempts.discover(attempts_from or here)
    except Exception as exc:                                   # noqa: BLE001
        if not quiet:
            _say(who or 'make_movie', 'no attempts band (%s)' % exc)
        track = None
    # one attempt is a single point under a flat staircase: no band for it
    verdict = bool(track is not None and len(track.attempts) >= 2)
    # #1042: the placement panels, measured on the film's own placement
    # boards before the frame is planned so their region is reserved too
    ptrack, pwhy, pfn = None, 'off (--no-placement-panel)', None
    if not placement.get('off'):
        try:
            import movie_placement
            led = placement.get('ledger') or attempts_ledger
            if not led and here:
                cand = os.path.join(here, 'ledger.jsonl')
                led = cand if os.path.isfile(cand) else None
            ptrack, pwhy = movie_placement.build_track(
                steps, [], ledger=led, benchmark=placement.get('benchmark'),
                intent=placement.get('intent'), quiet=quiet)
        except Exception as exc:                               # noqa: BLE001
            ptrack, pwhy = None, 'could not measure (%s)' % exc
    band = bool(verdict)
    if ptrack is not None:
        import movie_placement
        # the band is SIZED for readable panels (`plan_band`), not scaled
        pfn = movie_placement.band_px(ptrack, verdict)
        band = pfn
    # the iso view gets a region of the layout's own panel when the layout
    # has one to split and the panel WOULD run -- asked before the frame is
    # planned, because a region reserved for a gated-off panel is a blank box
    iso_box = False
    if want_iso and str(layout or 'legacy').lower() not in (
            'legacy', 'inset', 'stage3d'):
        try:
            import movie_panels
            if iso_opts is None:
                iso_opts = movie_panels.IsoOpts()
            iso_box = movie_panels.preflight(
                steps[0][1] if steps else final, iso_opts) is None
        except Exception:                                      # noqa: BLE001
            iso_box = False
    return Bands(False, None, track, verdict, ptrack, pwhy, pfn, band,
                 iso_box, placement.get('asked'))


def compose(frames, bands, geom, marks, lands, theme, *, quiet=False,
            who='make_movie'):
    """The bands, onto frames `build_boards` planned with `bands`. Order:
    placement panels, then the verdict band (or the benchmark band) -- all
    before the run clock and the iso panel, so a band sits next to the board
    it annotates."""
    box = geom.track if geom is not None else None
    if bands.stage3d:
        try:
            import movie_benchmark
            frames, rep = movie_benchmark.attach(frames, bands.btrack,
                                                 box=box, theme=theme,
                                                 marks=marks)
            _say(who, movie_benchmark.status_line(rep))
        except Exception as exc:                               # noqa: BLE001
            _say(who or 'make_movie', 'no benchmark band (%s)' % exc)
        return frames
    ptrack, pwhy, plan_ = bands.ptrack, bands.pwhy, None
    vbox = box
    if ptrack is not None:
        import movie_placement
        pfn = bands.pfn
        plan_ = pfn.plans[-1] if pfn is not None and pfn.plans else None
        if plan_ is not None and plan_.mode == 'declined':
            ptrack, pwhy = None, 'declined: %s' % plan_.why
        elif geom is not None and geom.track is not None:
            pbox, vbox = movie_placement.split_band(
                geom.track, both=bands.verdict, track=ptrack,
                frame_h=geom.frame.h)
            ptrack = movie_placement.with_firsts(ptrack, marks, lands)
            frames = movie_placement.compose(frames, pbox, ptrack, marks,
                                             theme, geom.frame.h)
        else:
            ptrack, pwhy = None, 'no band could be reserved in this frame'
    # SAID whenever a placement was found, drawn or declined
    if bands.ptrack is not None or bands.placement_asked or plan_ is not None:
        import movie_placement
        _say(who, movie_placement.status_line(ptrack, pwhy, plan_))
    try:
        import movie_attempts
        # the band is all placement when the panels took the whole box
        track = bands.track if (vbox is not None or ptrack is None) else None
        frames, rep = movie_attempts.attach(frames, track, theme=theme,
                                            marks=marks, box=vbox)
        # SILENT on a chain with no search behind it (most chains); it
        # speaks whenever there IS one -- drawn or declined, with why
        if rep.get('drawn') or rep.get('attempts'):
            _say(who, movie_attempts.status_line(rep))
    except Exception as exc:                                   # noqa: BLE001
        if not quiet:
            _say(who or 'make_movie', 'no attempts band (%s)' % exc)
    return frames


def compose_iso(frames, bands, geom, marks, final, iso_opts, theme, *,
                who='make_movie'):
    """The iso panel, last of the post-passes (or the stage3d line saying
    why there is none)."""
    if bands.stage3d:
        _say(who, 'iso panel: not drawn -- the stage3d board box IS the 3D '
                  'view')
        return frames
    # bound through the module so a test that monkeypatches
    # movie_panels.compose_two_panel still bites
    import movie_panels
    if iso_opts is None:
        iso_opts = movie_panels.IsoOpts()
    if iso_opts.theme is None:
        iso_opts.theme = theme
    box: Optional[Any] = None
    if bands.iso_box and geom is not None and geom.panel_split:
        box = geom.panel_split[0]
    # `box=` only when there IS one: an in-process caller (and the tests)
    # may stand in for compose_two_panel with the four-argument shape
    frames, report = movie_panels.compose_two_panel(
        frames, marks, final, iso_opts,
        **({'box': box} if box is not None else {}))
    _say(who, movie_panels.iso_status_line(report))
    return frames
