"""Arrays of identical parts: the formation predicate and the pin order (#1051).

A declared `arrays[]` entry says "these parts are one row": resistor banks along
a bus in the served IC's pin order, a decap row under a chip, one rotation for
the lot. The seeder has no term that builds such a row and the quench pulls
each member toward its own nets, so identical parts scatter (run 32:
3750 crossings against the human layout's 1352).

This module holds the two PURE pieces every consumer shares:

* `formation` -- ONE predicate for "is this set of poses a formed row": a
  common axis, the expected order along it, one shared rotation, an even
  pitch. The grade rule `array_formation` calls it, and the seeder's row seat
  and the quench's block move are to call it too (#1051 phases 3-4) rather
  than each carrying a copy, which is how a grader and an engine come to
  disagree about what "formed" means.
* `pin_order` -- the order a row must follow for `order: "pin"`: the served
  IC's pad numbering, read off pads and nets only. POSE-BLIND on purpose: an
  order read off where the parts sit would bless whatever arrangement the
  board already has, the emit-then-grade round trip this toolchain refuses
  everywhere else.

The detector that SUGGESTS arrays (#1051 phase 2) lands in this module too; it
suggests only, and reaches an intent through `emit_intent(derive_arrays=...)`.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

#: The row's tolerances. Constants rather than intent keys: the schema
#: declares WHAT a row is (axis, order, rotation, pitch) and these say how
#: close to exact the measurement must be, which is a property of the
#: measurement (grid and float noise), not of the design.
#:
#: `axis_mm`: how far a member's centre may sit off the row's line.
#: `rotation_deg`: how far a member may be turned from the row's rotation.
#: `pitch_spread_mm`: max minus min of the consecutive gaps, `pitch_mm: auto`.
#: `pitch_mm`: how far one gap may be from a DECLARED pitch.
DEFAULT_TOLERANCES = {'axis_mm': 0.25, 'rotation_deg': 0.5,
                      'pitch_spread_mm': 0.25, 'pitch_mm': 0.25}

#: The enums, shared with `floorplan`'s loader so the schema and the
#: predicate cannot disagree about a spelling.
ORDERS = ('pin', 'declared', 'unknown')
ROTATION_WORDS = ('shared', 'unknown')
AXES = ('auto', 'x', 'y')
PITCH_WORDS = ('auto',)


def natural_key(pad_number) -> Tuple:
    """Sort key for pad numbers: '2' < '10', 'A2' < 'A10' < 'B1'.

    Digit runs compare as integers and letter runs as text, each tagged with
    its kind so a digit run never compares against a letter run.
    """
    out = []
    for i, chunk in enumerate(re.split(r'(\d+)', str(pad_number))):
        if not chunk:
            continue
        out.append((0, int(chunk), '') if i % 2 else (1, 0, chunk))
    return tuple(out)


def pin_order(pcb, serves: str, members: Sequence[str]
              ) -> Tuple[List[str], Dict[str, str]]:
    """`(ordered_refs, unresolved)`: members in the served part's PIN order.

    Pose-blind: reads pad numbering and nets, never a footprint position.

    A member's key is the lowest (natural-sorted) pad of `serves` on a net
    that member reaches and no OTHER member reaches. A net several members
    share is a rail (+3V3 on every pull-up of a bank) and says nothing about
    order. Among a member's own nets, one landing on exactly ONE pad of the
    served part is preferred to one landing on several: a GND pull-down's
    ground lands on every ground pin, while its signal lands on one.

    `unresolved` is `{ref: why}` for a member with no such net, or one the
    board does not have; it is ordered by nothing, and a caller must say so
    rather than drop it.
    """
    fps = pcb.footprints or {}
    unresolved: Dict[str, str] = {}
    host = fps.get(serves)
    if host is None:
        return [], {m: f"{serves} is not on this board" for m in members}
    host_pads: Dict[int, List[str]] = {}
    for pd in host.pads:
        if pd.net_id:
            host_pads.setdefault(pd.net_id, []).append(str(pd.pad_number))
    nets_of: Dict[str, set] = {}
    for m in members:
        fp = fps.get(m)
        if fp is None:
            unresolved[m] = 'not on this board'
            continue
        nets_of[m] = {pd.net_id for pd in fp.pads if pd.net_id}
    reach: Dict[int, int] = {}
    for nets in nets_of.values():
        for n in nets:
            reach[n] = reach.get(n, 0) + 1
    keyed = []
    for m, nets in nets_of.items():
        own = [n for n in nets if reach.get(n) == 1 and n in host_pads]
        single = [n for n in own if len(host_pads[n]) == 1]
        use = single or own
        if not use:
            unresolved[m] = (f"no net of its own lands on a pad of {serves}"
                             if any(n in host_pads for n in nets)
                             else f"shares no net with {serves}")
            continue
        pad = min((p for n in use for p in host_pads[n]), key=natural_key)
        keyed.append((natural_key(pad), m))
    keyed.sort()
    return [m for _k, m in keyed], unresolved


def _ang_diff(a: float, b: float) -> float:
    d = abs(float(a) - float(b)) % 360.0
    return min(d, 360.0 - d)


def formation(members_poses: Sequence[Dict[str, object]], *,
              order_key: Optional[Sequence[str]] = None,
              rotation_spec=None, pitch_spec='auto', axis_spec='auto',
              tolerances: Optional[Dict[str, float]] = None
              ) -> Dict[str, object]:
    """Is this set of member poses ONE formed row? The shared predicate.

    `members_poses`: `[{'ref', 'x', 'y', 'rot'}]`, `x`/`y` the member's
    centre in whatever frame the caller measures (the grade uses the
    courtyard centre, so identical parts compare like for like).

    `order_key`: the expected order of refs along the row, or None when the
    order is not declared (`order: "unknown"`). A row may run either way, so
    the reversed order is formed too. Members absent from `order_key` are
    ordered by nothing and do not count against it.

    `rotation_spec`: a number (every member at that angle), `'shared'` (every
    member at ONE angle, whichever), or `'unknown'`/None (not checked).
    `pitch_spec`: `'auto'` (even gaps) or a number (every gap at it).
    `axis_spec`: `'x'` (a row running along x, so the centres share a y),
    `'y'`, or `'auto'` (the longer extent of the centres).

    Returns `{'formed', 'failed': [check names], 'unchecked': [...],
    'axis', 'order': [refs as they lie], 'checks': {name: detail}}`. A
    check that is not declared is `unchecked`, never passed silently -- the
    difference between "held" and "nobody asked" is the one this toolchain
    keeps everywhere.
    """
    tol = dict(DEFAULT_TOLERANCES)
    tol.update(tolerances or {})
    poses = [dict(p) for p in members_poses]
    checks: Dict[str, Dict[str, object]] = {}
    failed: List[str] = []
    unchecked: List[str] = []
    if len(poses) < 2:
        return {'formed': False, 'failed': ['members'], 'unchecked': [],
                'axis': None, 'order': [p.get('ref') for p in poses],
                'checks': {'members': {'ok': False, 'count': len(poses),
                                       'why': 'a row needs two members'}}}

    xs = [float(p['x']) for p in poses]
    ys = [float(p['y']) for p in poses]
    if axis_spec in ('x', 'y'):
        axis = axis_spec
    else:
        axis = 'x' if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 'y'
    along = xs if axis == 'x' else ys
    across = ys if axis == 'x' else xs
    mid = sorted(across)[len(across) // 2]
    dev = max(abs(a - mid) for a in across)
    ok = dev <= tol['axis_mm'] + 1e-9
    checks['axis'] = {'ok': ok, 'axis': axis, 'declared': axis_spec,
                      'max_offset_mm': round(dev, 4),
                      'tolerance_mm': tol['axis_mm']}
    if not ok:
        failed.append('axis')

    lie = sorted(range(len(poses)), key=lambda i: (along[i], poses[i]['ref']))
    observed = [poses[i]['ref'] for i in lie]
    want = ([] if order_key is None
            else [r for r in order_key if r in set(observed)])
    if order_key is None:
        unchecked.append('order')
    elif len(want) < 2:
        # Fewer than two members HAVE an expected position: an order over
        # one ref (or none) is satisfied by every arrangement, so it is
        # UNCHECKED, never a pass (Phase-1 verifier: `serves: J3` on
        # splitflap resolved nobody and graded clean).
        unchecked.append('order')
        checks['order'] = {'ok': None, 'expected': want,
                           'why': (f"only {len(want)} member(s) have an "
                                   f"expected position")}
    else:
        seen = [r for r in observed if r in set(want)]
        ok = seen == want or seen == list(reversed(want))
        checks['order'] = {'ok': ok, 'expected': want, 'observed': seen}
        if not ok:
            failed.append('order')

    rots = [float(p.get('rot') or 0.0) % 360.0 for p in poses]
    if isinstance(rotation_spec, (int, float)) and not isinstance(
            rotation_spec, bool):
        want_rot = float(rotation_spec) % 360.0
        off = sorted(p['ref'] for p, r in zip(poses, rots)
                     if _ang_diff(r, want_rot) > tol['rotation_deg'])
        checks['rotation'] = {'ok': not off, 'declared': want_rot,
                              'off': off,
                              'rotations': sorted({round(r, 3)
                                                   for r in rots})}
        if off:
            failed.append('rotation')
    elif rotation_spec == 'shared':
        base = rots[0]
        spread = max(_ang_diff(r, base) for r in rots)
        ok = spread <= tol['rotation_deg']
        checks['rotation'] = {'ok': ok, 'declared': 'shared',
                              'rotations': sorted({round(r, 3)
                                                   for r in rots})}
        if not ok:
            failed.append('rotation')
    else:
        unchecked.append('rotation')

    pos = sorted(along)
    gaps = [b - a for a, b in zip(pos, pos[1:])]
    if isinstance(pitch_spec, (int, float)) and not isinstance(
            pitch_spec, bool):
        bad = [round(g, 4) for g in gaps
               if abs(g - float(pitch_spec)) > tol['pitch_mm'] + 1e-9]
        ok = not bad
        checks['pitch'] = {'ok': ok, 'declared': float(pitch_spec),
                           'gaps_mm': [round(g, 4) for g in gaps],
                           'off_mm': bad, 'tolerance_mm': tol['pitch_mm']}
    else:
        spread = (max(gaps) - min(gaps)) if gaps else 0.0
        # A zero gap is two members on one spot: even, and not a row.
        ok = (spread <= tol['pitch_spread_mm'] + 1e-9
              and min(gaps) > tol['pitch_spread_mm'])
        checks['pitch'] = {'ok': ok, 'declared': 'auto',
                           'gaps_mm': [round(g, 4) for g in gaps],
                           'spread_mm': round(spread, 4),
                           'tolerance_mm': tol['pitch_spread_mm']}
    # Members closer along the axis than the tolerance share one spot.
    stacked = set()
    for i in range(len(lie) - 1):
        a, b = lie[i], lie[i + 1]
        if along[b] - along[a] <= tol['pitch_spread_mm']:
            stacked.update((poses[a]['ref'], poses[b]['ref']))
    checks['pitch']['stacked'] = sorted(stacked)
    if not ok:
        failed.append('pitch')

    return {'formed': not failed, 'failed': failed, 'unchecked': unchecked,
            'axis': axis, 'order': observed, 'checks': checks}


def spec_of(entry: Dict[str, object]) -> Dict[str, object]:
    """One intent `arrays[]` entry with its absent keys RESOLVED.

    Absent is not "unknown": an absent `order` is reported as absent by the
    brief and never checked; `"unknown"` is the author saying so. Both leave
    the order unchecked, so this collapses them for the PREDICATE only --
    the raw entry keeps the difference for every report.
    """
    rot = entry.get('rotation')
    return {
        'name': str(entry.get('name')),
        'members': [str(m) for m in (entry.get('members') or ())],
        'serves': entry.get('serves'),
        'order': entry.get('order') or 'unknown',
        'rotation': (float(rot) % 360.0
                     if isinstance(rot, (int, float))
                     and not isinstance(rot, bool) else (rot or 'unknown')),
        'pitch_mm': entry.get('pitch_mm', 'auto'),
        'axis': entry.get('axis', 'auto'),
        'allow_mixed': bool(entry.get('allow_mixed', False)),
    }


def expected_order(pcb, spec: Dict[str, object]
                   ) -> Tuple[Optional[List[str]], Dict[str, str]]:
    """`(order_key, unresolved)` for a resolved spec: the pin order for
    `order: "pin"`, the declared list for `"declared"`, None otherwise."""
    if spec['order'] == 'pin':
        return pin_order(pcb, str(spec['serves']), spec['members'])
    if spec['order'] == 'declared':
        return list(spec['members']), {}
    return None, {}


def is_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(float(v)))
