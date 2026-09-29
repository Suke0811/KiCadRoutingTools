#!/usr/bin/env python3
"""What a converge ledger row SAYS about its board, for the film (#1081).

The stage3d benchmark band draws one curve with two regimes: above a DONE
line, `blocking` falling toward it; below it, the board getting BETTER. This
module answers the three questions that needs, per row, without importing
`py_placer` (`_placer_path`'s one-way rule -- the router side does not import
placement engines):

  * `row_done(row)` -- is this row's board a fully working PCB? The DONE line
    is drawn at the first row that is.
  * `quality_key(score)` -- the ranking below the line: `(vias, copper_mm,
    segments)`, LEXICOGRAPHIC, the tie-break of `converge._score_key` read
    the same way, so a record the film draws is a record the run counts. It is
    never a weighted sum: a weighted sum lets a router buy off a disconnected
    net with a lower via count, and below the line it lets a board "improve"
    by trading one term for another the run's own ranking does not accept.
  * `deciding_term(prev, new)` -- WHICH term made a record a record, for its
    label (`copper -3.2 mm`): a lap that ties on vias and wins on copper is
    still progress, and a curve plotted on vias alone would draw it flat.

`tests/test_1081_benchmark_band.py` holds `quality_key` to
`converge._score_key`'s quality half on a shuffled ledger, so the two cannot
drift apart.
"""
from __future__ import annotations

import math
import re
import sys
from typing import Optional, Tuple

#: The quality tuple, in `converge._score_key`'s order.
TERMS = ('vias', 'copper_mm', 'segments')
#: How a deciding term reads on a record label.
TERM_LABEL = {'vias': 'vias', 'copper_mm': 'copper', 'segments': 'segments'}
TERM_UNIT = {'vias': '', 'copper_mm': ' mm', 'segments': ''}

#: A verifier's verdict line, `converge._LENS_RE`'s grammar.
_LENS_RE = re.compile(r'^VERDICT=(PASS|FAIL):lens=([A-Za-z0-9_-]+)')

#: Kinds whose row grades a ROUTED board. A placement lap's `blocking` counts
#: what a routed result would still block on, but it is not a routed board:
#: the film never calls a placement lap a working PCB.
DONE_KINDS = ('completion', 'routing')


def _term(v):
    """One quality term EXACTLY as `_score_key` reads it: an int as it is
    (however large -- `float()` would overflow it), a finite float, else
    +inf (unmeasured ranks last, never first). A bool is not a count."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return math.inf
    if isinstance(v, int) or math.isfinite(v):
        return v
    return math.inf


def quality_key(score) -> Tuple[float, float, float]:
    """`(vias, copper_mm, segments)` of a score document; +inf per missing
    or non-numeric term. A non-dict score or quality is all +inf."""
    q = score.get('quality') if isinstance(score, dict) else None
    if not isinstance(q, dict):
        q = {}
    return tuple(_term(q.get(k)) for k in TERMS)


def is_inf(v) -> bool:
    """True for +/-inf. Safe on an int of any size (`math.isinf(10**400)`
    raises OverflowError)."""
    return isinstance(v, float) and math.isinf(v)


def plottable(v) -> bool:
    """True when `v` can be drawn: a number whose float is finite."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(float(v))
    except OverflowError:
        return False


def deciding_term(prev, new) -> Optional[Tuple[str, float]]:
    """`(term, new - prev)` for the FIRST term the two keys differ on --
    the one the lexicographic ranking decided on -- or None when equal."""
    if prev is None or new is None:
        return None
    for name, a, b in zip(TERMS, prev, new):
        if a != b:
            if not (plottable(a) and plottable(b)):
                # one side unmeasured (or too large to subtract): the term
                # decided it, but there is no honest difference to print
                return (name, math.inf if is_inf(a) else -math.inf)
            return (name, float(b) - float(a))
    return None


def term_label(term) -> str:
    """`('copper_mm', -3.2)` -> `'copper -3.2 mm'`."""
    if not term:
        return ''
    name, d = term
    if is_inf(d):
        return '%s %s' % (TERM_LABEL.get(name, name),
                          'measured' if d < 0 else 'unmeasured')
    num = ('%d' % d) if float(d).is_integer() else ('%.1f' % d)
    if d > 0:
        num = '+' + num
    return '%s %s%s' % (TERM_LABEL.get(name, name), num,
                        TERM_UNIT.get(name, ''))


def lens_verdicts(row):
    """`{lens: 'PASS'|'FAIL'}` from a row's `lenses` (case-folded); a line
    that is not a verdict is ignored. FAIL wins over PASS for one lens."""
    out = {}
    lenses = row.get('lenses') if isinstance(row, dict) else None
    if not isinstance(lenses, (list, tuple)):
        return out
    for raw in lenses:
        m = _LENS_RE.match(str(raw or '').strip())
        if not m:
            continue
        name = m.group(2).lower()
        if out.get(name) != 'FAIL':
            out[name] = m.group(1)
    return out


def _blocking(score):
    """`score.blocking` as a count, or None (the film's own rule)."""
    try:
        from movie_attempts import _blocking_value
    except Exception:                                          # noqa: BLE001
        return None
    return _blocking_value(score.get('blocking')
                           if isinstance(score, dict) else None)


def row_done(row) -> Optional[bool]:
    """True when this row's board is a FULLY WORKING PCB, False when the
    row says it is not, None when the row cannot say (not a routed kind,
    or no countable `blocking`).

    Working means: `blocking == 0`, nothing `unknown`, no lens FAILed, and a
    score that is about THIS board (`score_stale` names a score that is not:
    #963). An ABSENT lens is not a failure -- ordinary laps carry none; only
    a `--final` row is guaranteed to, which `done_evidence` reports apart.
    """
    if not isinstance(row, dict):
        return None
    if str(row.get('kind') or '').lower() not in DONE_KINDS:
        return None
    score = row.get('score')
    b = _blocking(score)
    if b is None:
        return None
    if b != 0:
        return False
    unknown = score.get('unknown')
    if isinstance(unknown, (list, tuple)) and len(unknown):
        return False
    stale = row.get('score_stale')
    if isinstance(stale, dict) and stale.get('binding') in ('other',
                                                            'unbound'):
        return False
    if 'FAIL' in lens_verdicts(row).values():
        return False
    return True


def done_evidence(row) -> str:
    """`'verified'` when a DONE row is a `--final` row whose every lens PASSed
    (connectivity, drc and spec at least -- `record --final`'s own set), else
    `'measured'`: the numbers say done, no verifier has said so."""
    v = lens_verdicts(row)
    need = ('connectivity', 'drc', 'spec')
    if (isinstance(row, dict) and row.get('final')
            and all(v.get(k) == 'PASS' for k in need)
            and 'FAIL' not in v.values()):
        return 'verified'
    return 'measured'


if __name__ == '__main__':                                     # pragma: no cover
    import json
    for line in open(sys.argv[1], encoding='utf-8'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            print(r.get('iteration'), r.get('kind'), row_done(r),
                  quality_key(r.get('score')))
