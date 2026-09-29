#!/usr/bin/env python3
"""ONE benchmark band for the stage3d film (#1081): is it working yet, and is
it still getting better?

The verdict band plots `blocking`, and placement is three more panels. A viewer
asking "is this board working yet, and is it still improving?" had to read
four graphs and still found no finish line. This band is one curve on one
x axis, in two regimes split by ONE horizontal line:

  * **above the line: not working yet.** `blocking` (log scale) falling toward
    the line -- placement laps and routing laps alike, one curve, because a
    placement lap's `board_score` already reports the `blocking` a routed
    result would still carry. Placement detail rides on the point labels.
  * **the line is DONE**, `ledger_score.row_done`: blocking 0, nothing
    unknown, no lens FAILed, a score about THIS board. The first row across it
    gets a `WORKING @ t` chip, and from there the band's ground and the curve
    turn green -- `status_kept`, a role the theme already measures, so no new
    colour escapes the contrast gate.
  * **below the line: better.** Records are ranked on the FULL
    `(vias, copper_mm, segments)` key, lexicographic like the run's own
    ranking, never a weighted sum. y is the via count as a percentage of a
    reference; a lap that ties on vias but wins on copper is still a record
    step, labelled with the term that decided it (`copper -3.2 mm`), so the
    curve never reads "no progress" where the run counted progress.

**The human benchmark is OPTIONAL** (`--benchmark-board`). With one, y is a
percentage of ITS via count, a dashed line marks 100 %, and the first record
strictly better than it -- on the full key, and only when the benchmark is
itself a working board -- earns a GOLD marker (`status_best`). Without one,
100 % is the first working board, there is no line and no gold, and the band's
own label says "no benchmark board" so the absence reads as a fact rather than
a missing feature.

Degradation is never silent: `attach` returns the frames untouched and says
why, like `movie_attempts.attach`, whose frame plumbing this reuses.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys
from typing import NamedTuple, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import ledger_score as LS                                       # noqa: E402

#: The share of the plot height above the DONE line (the blocking regime).
ABOVE_FRAC = 0.52
#: Row kinds that are laps on this band's axis.
LAP_KINDS = ('placement', 'completion', 'routing')


class Point(NamedTuple):
    index: int
    t: Optional[float]
    kind: str
    accepted: bool
    blocking: Optional[float]       # None = ungraded (drawn as a tick)
    done: Optional[bool]
    key: Tuple[float, float, float]
    evidence: str                   # 'verified' | 'measured' | ''
    detail: str                     # placement detail for the point label


class Benchmark(NamedTuple):
    name: str
    key: Tuple[float, float, float]
    blocking: Optional[float]       # None = not graded
    why: str                        # how it was graded, or why not


class BenchTrack(NamedTuple):
    points: Tuple[Point, ...]
    source: str
    domain: Optional[Tuple[float, float]]
    benchmark: Optional[Benchmark]
    note: str


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------
def _placement_detail(score) -> str:
    """The placement terms a placement lap's label carries (`blocking_by`)."""
    by = score.get('blocking_by') if isinstance(score, dict) else None
    if not isinstance(by, dict):
        return ''
    parts = []
    for k in ('floorplan', 'assembly', 'unrouted', 'broken', 'drc'):
        v = by.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            parts.append('%s %g' % (k, v))
    return ', '.join(parts[:3])


def from_converge_ledger(path) -> Optional[BenchTrack]:
    """A converge ledger (JSONL) -> a BenchTrack; placement AND routing laps,
    on one curve. Non-object lines and non-lap kinds are skipped; a row with
    no countable `blocking` is kept, ungraded."""
    rows = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        return None
    pts = []
    ts = []
    for i, r in enumerate(rows):
        kind = str(r.get('kind') or '').lower()
        if kind not in LAP_KINDS:
            continue
        sc = r.get('score') if isinstance(r.get('score'), dict) else {}
        from movie_attempts import _blocking_value, _row_t
        b = _blocking_value(sc.get('blocking')) if sc else None
        t = _row_t(r)
        if t is not None:
            ts.append(t)
        it = r.get('iteration')
        idx = it if isinstance(it, int) and not isinstance(it, bool) else i
        done = LS.row_done(r)
        pts.append(Point(index=int(idx), t=t, kind=kind,
                         accepted=bool(r.get('accepted')),
                         blocking=None if b is None else float(b),
                         done=done, key=LS.quality_key(sc),
                         evidence=LS.done_evidence(r) if done else '',
                         detail=(_placement_detail(sc)
                                 if kind == 'placement' else '')))
    if not pts:
        return None
    dom = None
    if len(ts) >= 2 and max(ts) > min(ts) and all(p.t is not None
                                                  for p in pts):
        dom = (min(ts), max(ts))
    ung = sum(1 for p in pts if p.blocking is None)
    note = '%d laps' % len(pts)
    if ung:
        note += ', %d ungraded' % ung
    return BenchTrack(tuple(pts), 'converge', dom, None, note)


def from_loop_dir(work_dir) -> Optional[BenchTrack]:
    """`loop_round*.json` sidecars -> a BenchTrack: the loop's `failures` is
    its blocking term, and `metrics.vias` its only quality term (copper and
    segments are not recorded, so they rank as unmeasured, +inf)."""
    docs = []
    for p in sorted(glob.glob(os.path.join(work_dir, 'loop_round*.json'))):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get('schema') == 1 and 'round' in d:
            docs.append(d)
    if not docs:
        return None
    docs.sort(key=lambda d: d['round'])
    from movie_attempts import _blocking_value
    pts = []
    for d in docs:
        met = d.get('metrics') or {}
        b = _blocking_value(met.get('failures'))
        done = None if b is None else (b == 0)
        pts.append(Point(index=int(d['round']), t=None, kind='completion',
                         accepted=bool(d.get('accepted')),
                         blocking=None if b is None else float(b), done=done,
                         key=LS.quality_key({'quality': {
                             'vias': met.get('vias')}}),
                         evidence='measured' if done else '', detail=''))
    return BenchTrack(tuple(pts), 'loop', None, None,
                      '%d rounds' % len(pts))


def discover(hint) -> Optional[BenchTrack]:
    """The converge ledger beside `hint` if there is one, else its loop
    sidecars, else None."""
    if not hint:
        return None
    d = hint if os.path.isdir(hint) else os.path.dirname(os.path.abspath(hint))
    for name in ('ledger.jsonl', 'converge.jsonl'):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            tr = from_converge_ledger(p)
            if tr:
                return tr
    return from_loop_dir(d)


def grade_benchmark(board, score_json=None, timeout=900) -> Benchmark:
    """The human board's key and blocking. Its quality is read in process
    (`board_score.quality`); its blocking from `score_json` when given (a
    `board_score --json` document), else by running `board_score` once --
    never guessed. A benchmark that cannot be graded still gets its line; it
    cannot earn gold, and `why` says so."""
    name = os.path.splitext(os.path.basename(board))[0]
    root = os.path.dirname(_HERE)
    tools = os.path.join(root, 'py_tools')
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import board_score
        q = board_score.quality(board)
    except Exception as exc:                                   # noqa: BLE001
        q = {'error': str(exc)}
    key = LS.quality_key({'quality': q})
    doc = None
    why = ''
    if score_json:
        try:
            with open(score_json, encoding='utf-8') as f:
                doc = json.load(f)
            why = 'graded by %s' % os.path.basename(score_json)
        except (OSError, ValueError) as exc:
            why = 'could not read %s (%s)' % (score_json, exc)
    else:
        import subprocess
        import tempfile
        out = os.path.join(tempfile.mkdtemp(prefix='bench_'), 'score.json')
        try:
            subprocess.run([sys.executable, os.path.join(tools,
                                                         'board_score.py'),
                            board, '--json', out, '-q'],
                           capture_output=True, timeout=timeout, cwd=root)
            with open(out, encoding='utf-8') as f:
                doc = json.load(f)
            why = 'graded by board_score'
        except Exception as exc:                               # noqa: BLE001
            why = 'board_score could not grade it (%s)' % (
                str(exc).splitlines()[0][:80] if str(exc) else
                type(exc).__name__)
    b = None
    if isinstance(doc, dict):
        from movie_attempts import _blocking_value
        b = _blocking_value(doc.get('blocking'))
        if b is None:
            why += '; its blocking is not a count'
    return Benchmark(name, key, None if b is None else float(b), why)


def with_benchmark(track, bench) -> BenchTrack:
    return track._replace(benchmark=bench) if track is not None else None


# ---------------------------------------------------------------------------
# the record, decided once
# ---------------------------------------------------------------------------
class Plan(NamedTuple):
    order: Tuple[Point, ...]            # by x
    done_at: Optional[int]              # position in `order` of the crossing
    records: Tuple[Tuple[int, str], ...]   # (position, deciding-term label)
    ref_vias: Optional[float]           # 100 %
    gold_at: Optional[int]              # position of the first strict beat
    ties_at: Optional[int]              # ...or of a match, when none beat
    bmax: float                         # the blocking axis' top


def plan(track) -> Plan:
    """Where the line is crossed, which laps are records, and against what.

    Records above the line are the running minimum of `blocking` over
    ACCEPTED laps; below it, the running minimum of the lexicographic key over
    accepted DONE laps. Gold needs a benchmark that is itself working
    (`blocking == 0`) and a record whose key is STRICTLY lower than its key.
    """
    order = tuple(sorted(track.points,
                         key=lambda p: ((p.t if track.domain else 0.0),
                                        p.index)))
    done_at = next((i for i, p in enumerate(order) if p.done), None)
    records = []
    best_b = None
    best_k = None
    for i, p in enumerate(order):
        if not p.accepted or p.blocking is None:
            continue
        if p.done:
            if best_k is None or p.key < best_k:
                lab = (LS.term_label(LS.deciding_term(best_k, p.key))
                       if best_k is not None else '')
                records.append((i, lab))
                best_k = p.key
        elif done_at is None or i < done_at:
            if best_b is None or p.blocking < best_b:
                records.append((i, ''))
                best_b = p.blocking
    bench = track.benchmark
    ref = None
    if bench is not None and LS.plottable(bench.key[0]) and bench.key[0] > 0:
        ref = float(bench.key[0])
    elif done_at is not None and LS.plottable(order[done_at].key[0]):
        ref = max(float(order[done_at].key[0]), 1.0)
    gold = ties = None
    if (bench is not None and bench.blocking == 0
            and all(LS.plottable(v) for v in bench.key)):
        for i, _lab in records:
            p = order[i]
            if not p.done:
                continue
            if p.key < bench.key and gold is None:
                gold = i
            elif p.key == bench.key and ties is None:
                ties = i
    bs = [p.blocking for p in order if p.blocking is not None]
    return Plan(order, done_at, tuple(records), ref, gold,
                None if gold is not None else ties,
                max([1.0] + bs))


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------
def _fmt_t(sec) -> str:
    sec = int(max(0, sec))
    return '%d:%02d:%02d' % (sec // 3600, (sec // 60) % 60, sec % 60)


def _blend(a, b, k):
    return tuple(int(round(x * (1 - k) + y * k)) for x, y in zip(a, b))


def draw_band(d, box, track, *, upto=None, theme=None, debug=None) -> bool:
    """Draw the band into `box` on draw `d`, showing laps up to `upto` (an
    index horizon, like the verdict band). Returns whether it drew."""
    try:
        import render_theme
        th = render_theme.theme(theme, strict=False)
    except Exception:                                          # noqa: BLE001
        th = None

    def rgb(role, fallback):
        try:
            return th.rgb(role) if th is not None else fallback
        except Exception:                                      # noqa: BLE001
            return fallback
    ground = rgb('ground', (14, 16, 18))
    ink = rgb('chrome_text', (200, 204, 196))
    dim = rgb('chrome_text_dim', (120, 126, 118))
    ok = rgb('status_kept', (86, 206, 130))
    gold = rgb('status_best', (255, 214, 88))
    tried = rgb('status_tried', (200, 130, 60))
    dropped = rgb('status_dropped', (110, 110, 110))
    from route_render import load_font
    cap_h = max(12, min(16, box.h // 9))
    font = load_font(cap_h - 2)
    small = load_font(max(9, cap_h - 4))
    x0, y0 = box.x + 44, box.y + cap_h + 6
    x1, y1 = box.x + box.w - 12, box.y + box.h - 14
    if x1 - x0 < 60 or y1 - y0 < 40:
        return False
    pl = plan(track)
    order = pl.order
    if not order:
        return False
    line_y = int(y0 + (y1 - y0) * ABOVE_FRAC)
    # x: run time when every lap has one, else the lap order
    if track.domain:
        t0, t1 = track.domain
        xs = [x0 + (x1 - x0) * (p.t - t0) / (t1 - t0) for p in order]
    else:
        n = max(1, len(order) - 1)
        xs = [x0 + (x1 - x0) * i / n for i in range(len(order))]
    horizon = upto if upto is not None else max(p.index for p in order)
    shown = [i for i, p in enumerate(order) if p.index <= horizon]
    lb = math.log1p(pl.bmax)

    def y_above(b):
        return line_y - 3 - (line_y - 3 - y0) * (math.log1p(b) / lb
                                                 if lb else 0)
    # below: vias % of the reference; lower = better = further down
    pcts = []
    if pl.ref_vias:
        for p in order:
            if p.done and LS.plottable(p.key[0]):
                pcts.append(100.0 * p.key[0] / pl.ref_vias)
        if track.benchmark is not None:
            pcts.append(100.0)
    lo_p = min(pcts + [100.0]) if pcts else 90.0
    hi_p = max(pcts + [100.0]) if pcts else 100.0
    if hi_p - lo_p < 10:
        lo_p = hi_p - 10

    def y_below(pct):
        return line_y + 4 + (y1 - line_y - 4) * (hi_p - pct) / (hi_p - lo_p)

    def ypos(p):
        if p.blocking is None:
            return None
        if p.done and pl.ref_vias and LS.plottable(p.key[0]):
            return y_below(100.0 * p.key[0] / pl.ref_vias)
        if p.done:
            return line_y + 4
        return y_above(max(p.blocking, 0.5))
    crossed = pl.done_at is not None and pl.done_at in shown
    xc = xs[pl.done_at] if crossed else None
    # ground: the working regime is tinted from the crossing on
    d.rectangle([box.x, box.y, box.x + box.w - 1, box.y + box.h - 1],
                fill=ground)
    if crossed:
        d.rectangle([int(xc), y0, x1, y1], fill=_blend(ground, ok, 0.12))
    # the DONE line
    d.line([(x0, line_y), (x1, line_y)], fill=ok, width=2)
    d.text((x0 + 4, line_y - small.size - 3 if hasattr(small, 'size')
            else line_y - 12),
           'FULLY WORKING PCB (blocking 0, no lens FAIL)', fill=ok, font=small)
    # the benchmark line
    bench = track.benchmark
    if bench is not None and pl.ref_vias:
        yb = int(y_below(100.0))
        for xx in range(int(x0), int(x1), 10):
            d.line([(xx, yb), (min(xx + 5, x1), yb)], fill=gold, width=1)
        d.text((x1 - 4, yb + 2), 'benchmark %s = 100 %%' % bench.name,
               fill=gold, font=small, anchor='ra')
    # the curve: accepted laps in order, orange above, green below
    prev = None
    for i in shown:
        p = order[i]
        y = ypos(p)
        if y is None or not p.accepted:
            continue
        if prev is not None:
            col = ok if (p.done and order[prev[0]].done) else tried
            d.line([(prev[1], prev[2]), (xs[i], y)], fill=col, width=3)
        prev = (i, xs[i], y)
    # the record staircase
    rec = [(i, lab) for i, lab in pl.records if i in shown]
    for (a, _la), (b, _lb) in zip(rec, rec[1:]):
        ya, yb2 = ypos(order[a]), ypos(order[b])
        if ya is None or yb2 is None:
            continue
        d.line([(xs[a], ya), (xs[b], ya), (xs[b], yb2)], fill=gold, width=2)
    # nodes
    r = 4
    for i in shown:
        p = order[i]
        y = ypos(p)
        if y is None:
            d.line([(xs[i], y1), (xs[i], y1 - 7)], fill=dropped, width=2)
            continue
        col = ok if p.done else tried
        if p.accepted:
            d.ellipse([xs[i] - r, y - r, xs[i] + r, y + r], fill=col)
        else:
            d.ellipse([xs[i] - r, y - r, xs[i] + r, y + r], outline=col,
                      width=2)
    # record labels below the line: the term that decided each record
    labels = []
    for i, lab in rec:
        p = order[i]
        if lab and p.done:
            y = ypos(p)
            ty = y + 3 if y + 3 + cap_h <= box.y + box.h else y - cap_h - 2
            d.text((xs[i] + 6, ty), lab, fill=ok, font=small)
            labels.append((i, lab))
    # the crossing chip
    chip = None
    if crossed:
        p = order[pl.done_at]
        d.ellipse([xc - 7, line_y - 7, xc + 7, line_y + 7], fill=ok)
        when = (_fmt_t(p.t - track.domain[0]) if track.domain
                else 'lap %d' % p.index)
        chip = 'WORKING @ %s' % when
        if p.evidence == 'measured':
            chip += ' (measured)'
        tw = int(d.textlength(chip, font=font)) + 12
        cx = min(int(xc) + 10, x1 - tw)
        cy = y0
        d.rectangle([cx, cy, cx + tw, cy + cap_h + 4], fill=ok)
        d.text((cx + 6, cy + 2), chip, fill=ground, font=font)
    # gold: the first record that beats the (working) benchmark
    marker = None
    for pos, word in ((pl.gold_at, 'beats'), (pl.ties_at, 'matches')):
        if pos is None or pos not in shown:
            continue
        p = order[pos]
        y = ypos(p)
        s = 7
        d.polygon([(xs[pos], y - s), (xs[pos] + s, y), (xs[pos], y + s),
                   (xs[pos] - s, y)], fill=gold)
        when = (_fmt_t(p.t - track.domain[0]) if track.domain
                else 'lap %d' % p.index)
        marker = '%s benchmark @ %s' % (word, when)
        d.text((xs[pos] + 10, y - 16), marker, fill=gold, font=small)
        break
    # caption
    if bench is None:
        tail = 'no benchmark board (100 % = the first working board)'
    elif bench.blocking == 0:
        tail = 'benchmark %s' % bench.name
    else:
        tail = 'benchmark %s -- not a working board, so no gold (%s)' % (
            bench.name, bench.why)
    cap = ('records ranked on (vias, copper, segments)  |  %s  |  %s'
           % (tail, track.note))
    d.text((box.x + 6, box.y + 2), cap, fill=dim, font=small)
    d.text((box.x + 6, y0), 'blocking', fill=ink, font=small)
    d.text((box.x + 6, line_y + 6), 'vias %', fill=ink, font=small)
    if debug is not None:
        debug.update(line_y=line_y, xs=xs, shown=shown, crossed=crossed,
                     chip=chip, marker=marker, labels=labels,
                     records=[i for i, _l in rec], caption=cap,
                     plot=(x0, y0, x1, y1), done_at=pl.done_at,
                     ypos={i: ypos(order[i]) for i in shown})
    return True


def attach(frames, track, *, box, theme=None, marks=None):
    """Draw the band into `box` (the layout's reserved band) on every frame,
    revealing laps as the film's steps pass -- `movie_attempts.attach`'s
    horizon rule. Returns `(frames, report)`; with nothing to draw the frames
    come back untouched and the report says why."""
    report = {'drawn': False, 'why': '', 'laps': 0}
    if not frames:
        report['why'] = 'no frames'
        return frames, report
    if box is None or box.w <= 0 or box.h <= 0:
        report['why'] = 'the layout reserved no band'
        return frames, report
    if track is None or len(track.points) < 2:
        report['why'] = ('no converge ledger or loop rounds with two laps: '
                         'nothing to rank')
        return frames, report
    from PIL import Image, ImageDraw
    import frame_spool
    import frame_layout
    idx = [p.index for p in track.points]
    lo, hi = min(idx), max(idx)
    n = max(1, len(frames) - 1)
    horizons = None
    if marks:
        ends = sorted({int(m[3]) for m in marks if len(m) >= 4})
        if ends:
            horizons = [lo + (hi - lo) * (sum(1 for e in ends if e < i)
                                          / float(len(ends)))
                        for i in range(len(frames))]
    probe = Image.new('RGB', (box.w, box.h))
    if not draw_band(ImageDraw.Draw(probe), frame_layout.Box(0, 0, box.w,
                                                             box.h),
                     track, theme=theme):
        report['why'] = 'the band is %dx%d, too small for its plot' % (
            box.w, box.h)
        return frames, report
    W, H = frames[0].size

    def _into(i, f):
        up = horizons[i] if horizons else lo + (hi - lo) * (i / float(n))
        draw_band(ImageDraw.Draw(f), box, track, upto=up, theme=theme)
        return f
    frames = frame_spool.transform(frames, _into, out_size=(W, H),
                                   optional='benchmark band')
    pl = plan(track)
    report.update(drawn=True, laps=len(track.points),
                  why='%s (%s); %s; %s'
                      % (track.source, track.note,
                         'working at lap %d' % pl.order[pl.done_at].index
                         if pl.done_at is not None else 'never working',
                         ('benchmark %s' % track.benchmark.name)
                         if track.benchmark else 'no benchmark board'))
    return frames, report


def status_line(report) -> str:
    if not report:
        return 'benchmark band: not asked for'
    if report.get('drawn'):
        return 'benchmark band: %s' % report.get('why', '')
    return 'benchmark band: not drawn -- %s' % (report.get('why') or 'unknown')
