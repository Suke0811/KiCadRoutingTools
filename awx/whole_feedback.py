"""whole_feedback.py SIDECAR.plan.json OUT.json HOT.json [HOT.json ...] -- the ENDS the whole route's audits found
crowded, for the fanout to choose again (fanout_from_plan: FEEDBACK=OUT.json; whole_ends prices them).
whole_feedback.py --repeat SIDECAR.plan.json HOT_BEFORE.json HOT_NOW.json -- exit 0 (and name them) when a finding at
the ends -- its kind, its lanes, its end -- stands in both rounds' audits: the solve had its round and did not move it,
and only the fanout can (whole_loop stops there).
whole_feedback.py --now SIDECAR.plan.json HOT.json -- exit 0 (and name them) when a finding at the ends is one no solve
moves: a pitch or a static clearance there comes of where the ends stand (a dive there is the solve's: its via cut
moves it; a fold, the crossings the solve put round it) -- whole_loop stops at once, before paying a solve.

A finding (whole_gate --hot: its place, its kind, the lanes it names) is AT an array's ends -- the teeth or the berths --
where their own copper is: beside a side face, within the width that face's lanes stack to (its ends' count, a lane
pitch each, and two more); in front of a face, within its face band (a change's room, as whole_solve keeps clear) and a
lane pitch. One out between the arrays is the solve's, not the fanout's (K35: a fold a lane's re-solved crossings made
1.9 mm out from the source's face was read as its tooth's, and the fanout moved a tooth that was not the trouble). Two lanes it names
together are a PAIR of ends not to be chosen together again; one lane alone (a fold, a dive, a lane against static
copper) an end to AVOID. Each end is named by its lane and its legs' points and layer as laid (the sidecar's), which
whole_ends matches against its options. OUT.json is merged into when it exists: the feedback of every round stands.

The findings are in the PLAN's frame -- a board of pair chirality -1 turned over (braid.setup) -- and the sidecar's
ends in the board's: a finding is turned back before it is placed (y -> 2 CY - y about the board's mirror axis, read
from the board beside the sidecar). A lane is named as whole_ends names it: a pair by its base (pairs.pair_names),
never by a leg."""
import itertools
import json
import os
import sys

import braid as bd
import pairs as _pairs


REPEAT = sys.argv[1] == '--repeat'
NOW = sys.argv[1] == '--now'
if REPEAT or NOW:
    sys.argv.pop(1)
if NOW:
    sys.argv.insert(2, '')                            # (no earlier round)
sidecar, out, hots = sys.argv[1], sys.argv[2], sys.argv[3:]
S = json.load(open(sidecar))
ends = dict(S['ends'])
lay = {0: dict(S['tooth_layer']), 1: dict(S['dest_layer'])}
# the lanes as whole_ends makes them: a pair one lane, under the same switch
PAIRS = (_pairs.pair_names(list(ends)) if int(os.environ.get('PLAN_PAIRS', os.environ.get('BRAID_PAIRS', '0')) or 0)
         else {})
LANE = {leg: base for base, pr in PAIRS.items() for leg in pr}
CY = None
if int(S.get('chi', 1)) < 0:
    from kicad_parser import parse_kicad_pcb
    from bga_fanout.flip_frame import mirror_axis
    CY = mirror_axis(parse_kicad_pcb(sidecar[:-len('.plan.json')] + '.kicad_pcb'))


def board_xy(x, y):
    """a finding's point (the plan's frame) in the board's"""
    return (x, 2.0 * CY - y) if CY is not None else (x, y)


def legs_of(lane):
    """the sidecar's nets of a lane: itself, or a pair's two legs"""
    if lane in PAIRS:
        return [n for n in PAIRS[lane] if n in ends]
    return [lane] if lane in ends else []


def lanes_named(names):
    """the lanes a finding names (a leg read as its pair), in order, each once"""
    return list(dict.fromkeys(ln for ln in (LANE.get(n, n) for n in names) if legs_of(ln)))


def box(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


boxes = {0: box([e[0] for e in ends.values()]), 1: box([e[1] for e in ends.values()])}
FRONT = 2 * bd.VIA_NEED + bd.LANE_MIN           # in front of a face: its band (whole_solve FACE_ROOM) and a lane pitch


def side_reach(k, face):
    """beside a side face ('N' or 'S') of array k's box: the width its ends' lanes stack to, and two pitches"""
    b = boxes[k]
    y0 = b[1] if face == 'N' else b[3]
    n = sum(1 for e in ends.values() if abs(e[k][1] - y0) < 1e-3)
    return (n + 2) * bd.LANE_MIN


def near(k, x, y):
    """is (x, y) at array k's ends: beside a side face within its stack, else in front within the band"""
    b = boxes[k]
    dx = max(b[0] - x, 0.0, x - b[2])
    dy = max(b[1] - y, 0.0, y - b[3])
    if dx == 0.0 and dy > 0.0:
        return dy <= side_reach(k, 'N' if y < b[1] else 'S')
    return (dx * dx + dy * dy) ** 0.5 <= FRONT


def end_of(lane, k):
    lg = legs_of(lane)
    if not lg:
        return None
    return {'lane': lane, 'end': k, 'points': [ends[n][k] for n in lg], 'layer': lay[k].get(lg[0])}


def at_ends(fn):
    """the findings of a hot file at the ends: {(kind, lanes, end)}"""
    got = set()
    for x, y, kind, *rest in json.load(open(fn)).get('hot', []):
        x, y = board_xy(x, y)
        lanes = tuple(sorted(lanes_named(rest[0] if rest else [])))
        for k in (0, 1):
            if lanes and near(k, x, y):
                got.add((kind, lanes, k))
    return got


if NOW:
    fanouts = sorted(f for f in at_ends(hots[0]) if f[0] in ('PITCH', 'STATIC'))
    for kind, lanes, k in fanouts:
        print(f'  {kind} {"/".join(lanes)} at the {"teeth" if k == 0 else "berths"}')
    sys.exit(0 if fanouts else 1)
if REPEAT:
    both = at_ends(out) & at_ends(hots[0])            # (here `out` is the earlier round's hot file)
    for kind, lanes, k in sorted(both):
        print(f'  {kind} {"/".join(lanes)} at the {"teeth" if k == 0 else "berths"}, both rounds')
    sys.exit(0 if both else 1)

fb = json.load(open(out)) if os.path.exists(out) else {'pairs': [], 'avoid': []}
seen = {json.dumps(x, sort_keys=True) for x in fb['pairs'] + fb['avoid']}
added = 0
for fn in hots:
    for x, y, kind, *rest in json.load(open(fn)).get('hot', []):
        x, y = board_xy(x, y)
        lanes = lanes_named(rest[0] if rest else [])
        for k in (0, 1):
            if not near(k, x, y):
                continue
            es = [e for e in (end_of(ln, k) for ln in lanes) if e]
            items = ([('pairs', sorted([a, b], key=lambda e: e['lane'])) for a, b in itertools.combinations(es, 2)]
                     if len(es) >= 2 else [('avoid', es[0])] if es else [])
            for kind_, it in items:
                key = json.dumps(it, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    fb[kind_].append(it)
                    added += 1
json.dump(fb, open(out, 'w'), indent=1)
print(f'whole_feedback: {added} new, {len(fb["pairs"])} pairs and {len(fb["avoid"])} ends to avoid in {out}')
