#!/usr/bin/env python3
"""joint_escape.py -- one escape planned for every signal ball of an array, the bus's and the other nets' together.

    python3 joint_escape.py BOARD REF --bus N1,N2,.. [--others N,..] [--prefer PREFER_BOARD] [--out OUT.kicad_pcb]

A ball-by-ball fanout lays each escape the cheapest way for that ball and cannot know which other balls still need a
way out: a bus escape run across three rows to a side face fences in every ball behind it (zynq U1, 2026-09-30: a
block of ~20 other balls left bare, boxed by the bus's runs, with no face and no layer left). So the escapes are
CHOSEN together, then laid together:

1. Every signal ball of the array gets its menu of escapes (escape_moves.enumerate_moves: surface along an adjacent
   gap, dog-bone, via-in-pad; face, exit gap, layer, kind), priced against the board's static copper the way the
   whole route prices its own (braid.build_obstacles). A bus ball's layers are F.Cu and B.Cu and it never leaves by
   the array's far face (the one facing away from the other array); another net's layers are the board's signal
   layers -- never an inner plane layer.
2. The moves that cannot both be laid are found as the whole route finds them (pages_first._conflicts, strict: a
   shared gap stretch on a layer, a shared site, a via in the other's lane) -- two balls of one net's too, since the
   engine lays every escape on its own. A net's balls share copper through STRAPS instead: a ball of a net with more
   than one ball may join an adjacent ball of its net by a straight track rather than escape, and every chain of
   straps ends at a ball that escapes.
3. ONE CP-SAT solve picks at most one move per ball, no two in conflict: as many bus balls escaped as possible, then
   as many other balls, then the cheapest -- vias and length, and for a bus ball its distance from the tooth it is
   preferred to have (`prefer`: a board whose bus teeth the whole route has planned on).
4. The choice is handed to the production engine as a planned move for EVERY ball it covers
   (source_realize.full_move, strict), so no generic phase takes a planned ball's gap first.

plan_array() returns the hints and a report; lay() runs the one engine call (the under-pad engine's joint escape,
py_router/bga_fanout/underpad.py with joint=True: the plan first, the plane balls dropped, each net held to its
layers)."""

KRT_TOOL = {'scope': [], 'kind': 'actor'}   # #937: a research tool (awx), catalogued, shown at no door
import argparse
import collections
import contextlib
import io
import math
import os
import sys
import time
import types

import awx_settings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'py_router'))

OUTER = ('F.Cu', 'B.Cu')
W_BUS = 1_000_000          # a bus ball escaped
W_OTHER = 10_000           # another ball escaped
C_VIA = 300                # a via
C_MM = 20                  # a millimetre of escape
C_DEV_MM = 60              # a millimetre between a bus ball's exit and its preferred tooth's
C_DEV_KIND = 400           # ...another face, layer or kind than its preferred tooth's
W_DROP = 10_000            # a plane ball dropped to its plane
C_VIP = 300                # a drop's via in the pad rather than a gap (filled and capped at the fab)
SOLVE_BATCHES = int(awx_settings.get('JOINT_SOLVE_BATCHES', '20'))    # CP-SAT interleaved batches: phase 2's budget
P1_DET = float(awx_settings.get('JOINT_P1_DET', '120'))   # phase 1's deterministic time, per question asked
# A climb's reach, in pitches. zynq U1's whole array (100 batches): uncapped (to 19) 21172 moves, objective 48280503;
# capped at 8, 17356 and 48261318; at 4, 12582 and 48309493 -- the proved bound 48.44M in all three, and every climb
# any of the solves chose 1 to 4 deep but one
CLIMB = int(awx_settings.get('JOINT_CLIMB', '4'))


def short_name(n):
    return n.split('/')[-1]


def signal_layers(pcb):
    """every copper layer but an INNER one carrying a pour (a plane layer); an outer layer always"""
    planes = {z.layer for z in (pcb.zones or []) if z.net_id and z.layer not in OUTER}
    return [L for L in pcb.board_info.copper_layers if L not in planes]


def far_face(pcb, ref, other_ref):
    """the face of `ref`'s array facing away from `other_ref`'s"""
    import escape_moves as em
    a, b = pcb.footprints[ref], pcb.footprints[other_ref]
    ax = sum(p.global_x for p in a.pads) / len(a.pads)
    ay = sum(p.global_y for p in a.pads) / len(a.pads)
    bx = sum(p.global_x for p in b.pads) / len(b.pads)
    by = sum(p.global_y for p in b.pads) / len(b.pads)
    return min(em.DIRS, key=lambda d: em.DIRS[d][0] * (bx - ax) + em.DIRS[d][1] * (by - ay))


def preferred_teeth(board, ref, bus):
    """{net short name: the tooth `board` has for it at `ref`} (source_realize.measure_tooth), for the bus's nets"""
    from kicad_parser import parse_kicad_pcb
    import source_realize as sr
    with contextlib.redirect_stdout(io.StringIO()):
        pcb = parse_kicad_pcb(board)
    byname = {short_name(n.name): (i, n) for i, n in pcb.nets.items()}
    out = {}
    for n in bus:
        nm = short_name(n)
        if nm not in byname:
            continue
        pad = next((q for q in byname[nm][1].pads if q.component_ref == ref), None)
        g = sr.measure_tooth(pcb, nm, pad, byname) if pad is not None else None
        if g and g.get('tooth'):
            out[nm] = g
    return out


Strap = collections.namedtuple('Strap', 'to a b layer length')     # a join to the neighbouring ball `to`
Drop = collections.namedtuple('Drop', 'site stub layer inpad r dr')  # a plane ball's via: in a diagonal gap behind a
#                                                                     stub (a, b) on `layer`, or in its pad; its
#                                                                     radius and its drill's, as the engine lays it
Piece = collections.namedtuple('Piece', 'net legs vias balls')      # an option's copper: legs [(a, b, layer)], vias
#                                                                     [(pt, radius, drill radius)] (every layer), its
#                                                                     own balls [pt]


def _pt_seg(c, u, v):
    ux, uy = v[0] - u[0], v[1] - u[1]
    L2 = ux * ux + uy * uy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((c[0] - u[0]) * ux + (c[1] - u[1]) * uy) / L2))
    return math.hypot(c[0] - (u[0] + t * ux), c[1] - (u[1] + t * uy))


def _seg_seg(p, q, a, b):
    def cross(o, a_, b_):
        return (a_[0] - o[0]) * (b_[1] - o[1]) - (a_[1] - o[1]) * (b_[0] - o[0])
    d1, d2, d3, d4 = cross(a, b, p), cross(a, b, q), cross(p, q, a), cross(p, q, b)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0
    return min(_pt_seg(p, a, b), _pt_seg(q, a, b), _pt_seg(a, p, q), _pt_seg(b, p, q))


def _sizes(pcb, foot):
    """The REAL sizes the engine lays the plan at, each item at its own: the fan track and clearance (the rung's),
    hole to hole, a gap site's via (the rung's), a ball's via-in-pad as the engine sizes it for THAT pad
    (clamp_via_to_pad on the fab ladder: zynq U1's 0.35 mm balls take no 0.45 mm via), the stacking pitch of two lanes
    at that track, and the engine's own-ball disk (underpad home_r)."""
    import braid as te
    import rules as _rules
    import source_realize as sr
    from list_nets import board_constraint, escalation_rungs
    from routing_defaults import HOLE_TO_HOLE_CLEARANCE
    from bga_fanout.geometry import clamp_via_to_pad
    tw, cl = sr.FAN_TRACK, sr.FAN_CLEAR
    h2h = _rules.active().hole_to_hole
    if h2h is None and getattr(pcb, 'source_path', ''):
        h2h = board_constraint(pcb.source_path, 'min_hole_to_hole')
    h2h = max(h2h or 0.0, HOLE_TO_HOLE_CLEARANCE)
    floors = escalation_rungs(len(pcb.board_info.copper_layers or ()) or 4)
    memo = {}

    def inpad(p):
        """(radius, drill radius) of the via the engine lays in pad p"""
        if id(p) not in memo:
            cs, cd = clamp_via_to_pad(te.VIA_SIZE, te.VIA_DRILL, p, floors)[:2]
            memo[id(p)] = (cs / 2.0, (cd or 0.0) / 2.0)
        return memo[id(p)]
    pad_r = max((max(q.size_x, q.size_y) for q in foot.pads), default=0.4) / 2
    return dict(tw=tw, cl=cl, h2h=h2h, d_seg=tw + cl, vr=te.VIA_SIZE / 2.0, vdr=te.VIA_DRILL / 2.0, inpad=inpad,
                grow=te.VIA_SIZE + cl, stack=tw + cl + _rules.HUG_OVER,
                r_home=max(pad_r + tw / 2 + cl, te.VIA_SIZE / 2 + tw / 2 + cl))


def _hit(P, Q, same, sz):
    """can two options' copper not both be laid, each item at its own size? Two nets': any two legs on one layer
    closer than track + clearance, a via that close to a leg of the other's plus its radius (every layer), two vias
    closer than their radii + clearance or their drills than their radii + hole-to-hole. One net's, as the engine's
    raster sees it (it carries no nets): a leg's centreline OUTSIDE its own balls' disks that close to the other's
    copper, and drills at hole-to-hole."""
    tw2, cl = sz['tw'] / 2, sz['cl']
    for (c, r, dr) in P.vias:
        for (c2, r2, dr2) in Q.vias:
            dd = math.hypot(c[0] - c2[0], c[1] - c2[1])
            if dd < dr + dr2 + sz['h2h'] - 1e-6 or (not same and dd < r + r2 + cl - 1e-6):
                return True
    if not same:
        for (a, b, L) in P.legs:
            for (u, v, L2) in Q.legs:
                if L == L2 and _seg_seg(a, b, u, v) < sz['d_seg'] - 1e-6:
                    return True
        return any(_pt_seg(c, u, v) < r + tw2 + cl - 1e-6 for (c, r, _d) in P.vias for (u, v, _L) in Q.legs) or \
            any(_pt_seg(c, a, b) < r + tw2 + cl - 1e-6 for (c, r, _d) in Q.vias for (a, b, _L) in P.legs)
    rh = sz['r_home']
    for X, Y in ((P, Q), (Q, P)):
        for (a, b, L) in X.legs:
            n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02))
            for i in range(n + 1):
                t = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                if any(math.hypot(t[0] - o[0], t[1] - o[1]) < rh for o in X.balls):
                    continue
                if any(L == L2 and _pt_seg(t, u, v) < sz['d_seg'] - 1e-6 for (u, v, L2) in Y.legs) or \
                        any(math.hypot(t[0] - c[0], t[1] - c[1]) < r + tw2 + cl - 1e-6 for (c, r, _d) in Y.vias):
                    return True
    return False


def _box(pc, grow):
    pts = [q for (a, b, _L) in pc.legs for q in (a, b)] + [c for (c, _r, _d) in pc.vias] + list(pc.balls)
    return (min(q[0] for q in pts) - grow, min(q[1] for q in pts) - grow,
            max(q[0] for q in pts) + grow, max(q[1] for q in pts) + grow)


def _straps(pcb, grid, items, obs):
    """{ball: [Strap]}: a ball of a net with more than one ball here may, instead of escaping, join an adjacent ball
    of its net (one of its eight neighbours) by a straight track on its own layer -- the net's balls sharing an
    escape. The engine lays a strap after the planned escapes, exactly against the other nets' copper and on its
    raster with the two balls' own disks exempted."""
    by_net = collections.defaultdict(list)
    for key, (nm, _p) in items.items():
        by_net[nm].append(key)

    def near(d, pitch):
        return d < 0.01 or abs(d - pitch) < 0.01
    straps = collections.defaultdict(list)
    for nm, keys in by_net.items():
        if len(keys) < 2:
            continue
        for k1 in keys:
            p = items[k1][1]
            home = next((L for L in pcb.board_info.copper_layers if L in p.layers), 'F.Cu')
            for k2 in keys:
                q = items[k2][1]
                dx, dy = abs(q.global_x - p.global_x), abs(q.global_y - p.global_y)
                if k2 == k1 or home not in q.layers or not (near(dx, grid.pitch_x) and near(dy, grid.pitch_y)):
                    continue
                a, b = (p.global_x, p.global_y), (q.global_x, q.global_y)
                if obs(p.net_id, home).seg_clear(a, b):
                    straps[k1].append(Strap(k2, a, b, home, math.hypot(b[0] - a[0], b[1] - a[1])))
    return straps


def _via_clear(pcb, obs, nid, q, r, sz):
    """a via of radius `r` at q clear of the board's static copper on every layer (the model is inflated by the
    clearance and half the fan track)"""
    return all(not (obs(nid, L).point_violation(q, pad=r - sz['tw'] / 2) or [0])[0]
               for L in pcb.board_info.copper_layers)


def _drops(pcb, grid, p, obs, sz):
    """[Drop]: a plane ball's ways down to its plane -- a stub to one of its four diagonal inter-ball gaps and a via
    there (the engine's dog-bone drop, at the rung's via), or a via in its pad (at the size the engine gives that
    pad) -- each clear of the board's static copper"""
    home = next((L for L in pcb.board_info.copper_layers if L in p.layers), 'F.Cu')
    hx, hy = grid.pitch_x / 2.0, grid.pitch_y / 2.0
    x0, y0, x1, y1 = grid.bbox
    pad = (p.global_x, p.global_y)
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            site = (pad[0] + sx * hx, pad[1] + sy * hy)
            if x0 < site[0] < x1 and y0 < site[1] < y1 and obs(p.net_id, home).seg_clear(pad, site) \
                    and _via_clear(pcb, obs, p.net_id, site, sz['vr'], sz):
                out.append(Drop(site, (pad, site), home, False, sz['vr'], sz['vdr']))
    r, dr = sz['inpad'](p)
    if _via_clear(pcb, obs, p.net_id, pad, r, sz):
        out.append(Drop(pad, None, home, True, r, dr))
    return out


def reserve_ball_vias(pcb, spec=None):
    """The joint fanout's promise to the arrays' OTHER nets and plane balls, kept by the bus's own fanout: each such
    ball keeps the via in its own pad. `spec` the joint spec ({"arrays": [{"ref", "others", "drops"}]}), else the
    file FANOUT_JOINT names; neither -- no joint fanout -- does nothing. A stand-in via, of the size the engine lays
    in that pad and locked, is added to `pcb.vias` for each ball, so the bus's menus and the fanout engine leave the
    site as they leave any via; nothing writes it (a fanout writes the board it read plus its own copper). Without it
    the bus's comb may run a track on B under a ball of another net and wall it in (zynq U1: DDR3_A4 under
    DDR3_CK_N's M2, the A0/A2/A3 teeth round it on F -- no escape at any rung). Returns the number added."""
    if spec is None:
        path = awx_settings.get('FANOUT_JOINT')
        if not path:
            return 0
        import json
        with open(path, encoding='utf-8') as f:
            spec = json.load(f)
    if getattr(pcb, '_joint_reserved', False):
        return 0
    import braid as te
    from kicad_parser import Via
    from list_nets import escalation_rungs
    from bga_fanout.geometry import clamp_via_to_pad
    floors = escalation_rungs(len(pcb.board_info.copper_layers or ()) or 4)
    n = 0
    for a in spec.get('arrays', ()):
        foot = pcb.footprints.get(a['ref'])
        if foot is None:
            continue
        want = {short_name(x) for x in list(a.get('others', ())) + list(a.get('drops', ()))}
        for p in foot.pads:
            if not p.net_id or short_name(p.net_name or '') not in want:
                continue
            size, drill = clamp_via_to_pad(te.VIA_SIZE, te.VIA_DRILL, p, floors)[:2]
            pcb.vias.append(Via(x=p.global_x, y=p.global_y, size=size, drill=drill or te.VIA_DRILL,
                                layers=['F.Cu', 'B.Cu'], net_id=p.net_id, locked=True))
            n += 1
    pcb._joint_reserved = True
    return n


def movable_refs(pcb, ref):
    """the movable passives (unlocked two-pad C/R/FB, bga_fanout.geometry): the cap step that follows moves them off
    the fanout, so the joint escape plans and lays as if they were not there"""
    from bga_fanout.geometry import MOVABLE_PASSIVE_PREFIXES
    return frozenset(r for r, f in pcb.footprints.items()
                     if r != ref and not getattr(f, 'locked', False) and r.startswith(MOVABLE_PASSIVE_PREFIXES)
                     and len([q for q in f.pads if any(str(L).endswith('.Cu') for L in q.layers)]) <= 2)


def build_menus(pcb, ref, bus, others, other_layers, far=None, drops=(), climb=CLIMB, street=2, only=None):
    """Every ball's OPTIONS for plan_array (its escapes, its straps, its drops, each with its copper as a Piece at its
    real size), and what they were built from: a namespace of foot, grid, bus_s, oth_s, drop_s, sz, items, menu (the
    escapes alone, per ball), balls, opts, via_r (a move's via radius), t_menu. `only` (a set of ball keys, NET#PAD):
    those balls alone -- a round that plans again only the balls whose copper did not stand (carry)."""
    import braid as te
    import escape_moves as em
    import fanout_from_plan as fp
    t0 = time.time()
    foot = pcb.footprints[ref]
    grid = em.grid_of(foot)
    if climb is None:
        climb = max(len(grid.xs), len(grid.ys))
    bus_s = {short_name(n) for n in bus}
    oth_s = {short_name(n) for n in others}
    drop_s = {short_name(n) for n in drops} - bus_s - oth_s
    sz = _sizes(pcb, foot)
    skip = movable_refs(pcb, ref)
    cache = {}

    def obs(nid, layer):
        key = (nid, layer)
        if key not in cache:
            cache[key] = te.build_obstacles(pcb, nid, {nid}, layer, margin=sz['cl'] + sz['tw'] / 2, skip_refs=skip)
        return cache[key]
    items, menu, balls, dmenu = {}, {}, {}, {}
    for p in foot.pads:
        nm = short_name(p.net_name or '')
        if not p.net_id or (nm not in bus_s and nm not in oth_s and nm not in drop_s):
            continue
        key = f'{nm}#{p.pad_number}'
        if only is not None and key not in only:
            continue
        items[key] = (nm, p)
        balls[key] = (p.global_x, p.global_y)
        if nm in drop_s:
            menu[key] = []
            dmenu[key] = _drops(pcb, grid, p, obs, sz)
            continue
        home = next((L for L in pcb.board_info.copper_layers if L in p.layers), 'F.Cu')
        lays = [home] + [L for L in (OUTER if nm in bus_s else other_layers) if L != home]
        centre = (p.global_x, p.global_y)
        with contextlib.redirect_stdout(io.StringIO()):
            moves = em.enumerate_moves(
                p, grid, lays,
                lambda a, b, L, _n=p.net_id: obs(_n, L).seg_clear(a, b),
                lambda q, L, _n=p.net_id, _p=p, _c=centre: not (obs(_n, L).point_violation(
                    q, pad=(sz['inpad'](_p)[0] if q == _c else sz['vr']) - sz['tw'] / 2) or [0])[0],
                climb=climb, own_line=True, straight=True,
                street=street, street_pitch=sz['stack'] + 1e-4)
        moves = fp.dedupe_climbs(moves)
        if nm in bus_s and far:
            moves = [m for m in moves if m.direction != far]
        menu[key] = moves
        dmenu[key] = []
    t_menu = time.time() - t0
    straps = _straps(pcb, grid, {k: v for k, v in items.items() if v[0] not in drop_s}, obs)
    # every ball's options, escapes first (their conflicts are the whole route's own, by index); each with its copper
    # at its real size: a via in the ball's own pad the engine's clamped one, any other the rung's
    opts, via_r = {}, {}
    for key, (nm, p) in items.items():
        own = [(p.global_x, p.global_y)]
        o = []
        for m in menu[key]:
            vias = []
            if m.site is not None:
                r, dr = sz['inpad'](p) if tuple(m.site) == own[0] else (sz['vr'], sz['vdr'])
                vias = [(tuple(m.site), r, dr)]
                via_r[id(m)] = r
            o.append(('escape', m, Piece(nm, list(m.legs), vias, own)))
        o += [('strap', s, Piece(nm, [(s.a, s.b, s.layer)], [], [s.a, s.b])) for s in straps.get(key, ())]
        o += [('drop', d, Piece(nm, [d.stub + (d.layer,)] if d.stub else [], [(d.site, d.r, d.dr)], own))
              for d in dmenu[key]]
        opts[key] = o
    return types.SimpleNamespace(foot=foot, grid=grid, bus_s=bus_s, oth_s=oth_s, drop_s=drop_s, sz=sz, items=items,
                                 menu=menu, balls=balls, opts=opts, straps=straps, dmenu=dmenu, t_menu=t_menu,
                                 via_r=via_r)


def plan_array(pcb, ref, bus, others, other_layers, far=None, prefer=None, drops=(), climb=CLIMB, street=2,
               batches=None, workers=4, time_limit=None, log=print, debug=False, only=None):
    """(hints, report): one planned move for every signal ball of `ref` on `pcb` -- the bus's nets (`bus`, full or
    short names) escaping on F.Cu/B.Cu, never by the `far` face; `others` escaping on `other_layers`, or a multi-ball
    net's ball strapped to a neighbour of its net; and every ball of the plane nets `drops` dropped to its plane --
    chosen together. `prefer` {bus net: measured tooth}: the teeth the bus is preferred to keep. hints: {ball
    position: strict planned move} for the joint escape engine.

    The menus are EVERY move escape_moves has: the surface escapes (along an adjacent gap, and straight out along
    the ball's own line), dog-bones and vias-in-pad, the CLIMBS -- a dog-bone or via-in-pad whose run first travels
    along a gap or the ball's own line, up to `climb` pitches (None: the whole array), before it leaves -- and the
    STREET dog-bones (a via in an empty band of the array, `street` sites along a lane; the whole route's 2). The
    escapes' conflicts are the whole route's own (pages_first._conflicts as its ends take them: strict, an F exit
    stacked over a B one allowed)."""
    import conflict_groups as cg
    import source_realize as sr
    from ortools.sat.python import cp_model
    t0 = time.time()
    bm = build_menus(pcb, ref, bus, others, other_layers, far=far, drops=drops, climb=climb, street=street,
                     only=only)
    bus_s, oth_s, drop_s, sz = bm.bus_s, bm.oth_s, bm.drop_s, bm.sz
    items, menu, balls, opts, straps, dmenu, t_menu = (bm.items, bm.menu, bm.balls, bm.opts, bm.straps, bm.dmenu,
                                                       bm.t_menu)
    via_r = bm.via_r
    n_moves = sum(len(v) for v in menu.values())
    # the escapes' conflicts, the whole route's own relation as groups that all conflict pairwise (conflict_groups:
    # pages_first._conflicts pair by pair was 129 s and 3.1 million pairs for the bus alone with every move kind).
    # Every crossing counts (xing 2, asked for here, not left to the process: select_moves' default counts one only
    # where a move climbs, and only importing pages_first raises it) -- a plan of every ball has plain escapes out of
    # the interior, and two of those cross (zynq U1, the plan at the default rule: 85 of 86 clashing pairs in the laid
    # geometry were two plain surface escapes crossing on F.Cu).
    # One net's two ESCAPES conflict as two nets' do: the engine lays each ball's escape on its own, on a raster
    # that carries no nets (zynq U1: five VCC_1V0 balls planned out through one gap, four laid nowhere)
    t1 = time.time()
    groups, bigroups, gpairs = cg.conflict_groups(menu, stack=True, stack_pitch=sz['stack'],
                                                  via_r=lambda m: via_r.get(id(m), sz['vr']),
                                                  reach_extra=sz['cl'] + sz['tw'] / 2, xing=2)
    pairs = [(a[0], a[1], b[0], b[1]) for a, b in sorted(gpairs)]
    # built in a canonical order (pages_first's note: the order constraints reach the CP-SAT picks its answer)
    # (a group of one ball's moves alone says nothing its own AtMostOne does not)
    groups = sorted((sorted(g) for g in groups if len({m_[0] for m_ in g}) > 1), key=repr)
    bigroups = sorted(((sorted(a), sorted(b)) for a, b in bigroups if len({m_[0] for m_ in a | b}) > 1), key=repr)
    t_lane = time.time() - t1
    t1 = time.time()
    # a strap or a drop against every other ball's option: geometry at the laid sizes, the candidates found through a
    # 1 mm cell index of the options' boxes (a climb's box spans the array; the all-pairs loop was 10^7 box tests)
    index = collections.defaultdict(list)
    boxes = {}
    for k in sorted(opts):
        for i, (_kind, _o, pc) in enumerate(opts[k]):
            bx = boxes[(k, i)] = _box(pc, sz['grow'])
            for cx in range(int(math.floor(bx[0])), int(math.floor(bx[2])) + 1):
                for cy in range(int(math.floor(bx[1])), int(math.floor(bx[3])) + 1):
                    index[(cx, cy)].append((k, i))
    for k in sorted(opts):
        for i, (kind, _o, pc) in enumerate(opts[k]):
            if kind == 'escape':
                continue
            bx = boxes[(k, i)]
            seen = set()
            for cx in range(int(math.floor(bx[0])), int(math.floor(bx[2])) + 1):
                for cy in range(int(math.floor(bx[1])), int(math.floor(bx[3])) + 1):
                    for (k2, j) in index[(cx, cy)]:
                        if k2 == k or (k2, j) in seen or (opts[k2][j][0] != 'escape' and (k2, j) <= (k, i)):
                            continue
                        seen.add((k2, j))
                        bx2 = boxes[(k2, j)]
                        if bx[0] > bx2[2] or bx2[0] > bx[2] or bx[1] > bx2[3] or bx2[1] > bx[3]:
                            continue
                        if _hit(pc, opts[k2][j][2], items[k][0] == items[k2][0], sz):
                            pairs.append((k, i, k2, j))
    t_geo = time.time() - t1
    log(f'  joint escape of {ref}: {len(items)} balls ({sum(1 for k in items if items[k][0] in bus_s)} bus, '
        f'{sum(1 for k in items if items[k][0] in drop_s)} plane), {n_moves} moves, '
        f'{sum(len(v) for v in straps.values())} straps, {sum(len(v) for v in dmenu.values())} drops, '
        f'{len(groups)} conflict cliques + {len(bigroups)} bicliques + {len(pairs)} pairs, {time.time() - t0:.0f} s '
        f'(menus {t_menu:.0f}, '
        f'conflicts {t_lane:.0f}, geometry {t_geo:.0f})')

    def cost(key, kind, o):
        nm, p = items[key]
        if kind == 'strap':
            return int(round(C_MM * o.length))
        if kind == 'drop':
            return int(round(C_VIA + (C_VIP if o.inpad else C_MM * math.hypot(o.site[0] - p.global_x,
                                                                               o.site[1] - p.global_y))))
        ln = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b, _L in (o.legs or [])) or \
            math.hypot(o.exit_pt[0] - p.global_x, o.exit_pt[1] - p.global_y)
        c = C_VIA * o.vias + C_MM * ln
        g = (prefer or {}).get(nm) if nm in bus_s else None
        if g:
            t = g['tooth']
            c += C_DEV_MM * math.hypot(o.exit_pt[0] - t[0], o.exit_pt[1] - t[1])
            c += C_DEV_KIND * ((o.direction != g.get('direction')) + (o.layer != g.get('layer'))
                               + (o.kind != g.get('kind')))
        return int(round(c))
    mdl = cp_model.CpModel()
    keys = sorted(opts)
    v = {key: [mdl.NewBoolVar(f'v{k}_{i}') for i in range(len(opts[key]))] for k, key in enumerate(keys)}
    served = {}                      # the ball takes one of its options (an escape, a strap or a drop)
    for k, key in enumerate(keys):
        if v[key]:
            served[key] = mdl.NewBoolVar(f's{k}')
            mdl.Add(sum(v[key]) == served[key])
    for g in groups:
        mdl.AddAtMostOne([v[k][i] for k, i in g])
    # every move of A against every move of B: y_A covers A's moves, y_B B's, and a move on both sides stands with
    # them -- at most one of y_A, y_B and those
    for n_, (a, b) in enumerate(bigroups):
        both = set(a) & set(b)
        lits = [v[k][i] for k, i in sorted(both)]
        for side, tag in ((a, 'a'), (b, 'b')):
            only = [m_ for m_ in side if m_ not in both]
            if only:
                y = mdl.NewBoolVar(f'bi{n_}{tag}')
                for k, i in only:
                    mdl.AddImplication(v[k][i], y)
                lits.append(y)
        if len(lits) > 1:
            mdl.AddAtMostOne(lits)
    for a, i, b, j in pairs:
        mdl.AddBoolOr([v[a][i].Not(), v[b][j].Not()])
    # a strap joins a ball that is itself served -- escaped, or strapped on -- and a chain of straps is a path, not a
    # loop, so every chain ends at a ball that escapes: a strap climbs one level toward it
    lvl = {key: mdl.NewIntVar(0, len(items), f'l{k}') for k, key in enumerate(keys) if straps.get(key)}
    for key in keys:
        for i, (kind, o, _pc) in enumerate(opts[key]):
            if kind != 'strap':
                continue
            c = o.to
            if not v[c]:
                mdl.Add(v[key][i] == 0)          # a neighbour with no move of its own cannot carry anyone
                continue
            mdl.Add(sum(v[c]) >= 1).OnlyEnforceIf(v[key][i])
            if c in lvl:
                mdl.Add(lvl[key] >= lvl[c] + 1).OnlyEnforceIf(v[key][i])
    wt = {key: W_BUS if items[key][0] in bus_s else (W_DROP if items[key][0] in drop_s else W_OTHER) for key in keys}
    rank = {key: 2 if items[key][0] in bus_s else (0 if items[key][0] in drop_s else 1) for key in keys}
    # PHASE 1, the balls served: EVERY ball is asked to be (an assumption each), with no cost in the question -- one
    # objective of count and cost together left balls unserved that a plan could serve (zynq U1, the bus fixed: 249 of
    # 251 in 200 s at 100 batches, where every ball the board allows, 250, is found in 6 s this way). A proved conflict
    # names the balls it holds (CP-SAT's core); the least of them is let go -- a plane ball before another net's, an
    # other net's before the bus's: a plane net keeps its other balls, a signal has no other way out -- and the rest
    # asked again. One worker, stopped by deterministic time: the same model gives the same answer.
    t_p1 = time.time()
    let_go = []
    idx = {served[k].Index(): k for k in served}
    s1 = cp_model.CpSolver()
    s1.parameters.num_workers = 1
    s1.parameters.max_deterministic_time = P1_DET
    if time_limit:
        s1.parameters.max_time_in_seconds = time_limit
    while True:
        mdl.ClearAssumptions()
        mdl.AddAssumptions([served[k] for k in keys if k in served and k not in let_go])
        st1 = s1.Solve(mdl)
        if st1 != cp_model.INFEASIBLE:
            break
        core = sorted(idx[c] for c in s1.SufficientAssumptionsForInfeasibility() if c in idx)
        if not core:
            break
        let_go.append(min(core, key=lambda k_: (rank[k_], k_)))
    mdl.ClearAssumptions()
    held = st1 in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    if held:
        for key in keys:
            for i, var in enumerate(v[key]):
                mdl.AddHint(var, s1.Value(var))
            if key in served and key not in let_go:
                mdl.Add(served[key] == 1)
    t_p1 = time.time() - t_p1
    # PHASE 2, the cost, every ball phase 1 served held served (a ball let go still earns its weight if it can be
    # served after all). Phase 1 out of time (no answer to hold): today's one objective, count and cost together.
    obj = []
    for key in keys:
        w = wt[key] if (not held or key in let_go) else 0
        for i, (kind, o, _pc) in enumerate(opts[key]):
            obj.append((w - cost(key, kind, o)) * v[key][i])
    mdl.Maximize(sum(obj))
    s_ = cp_model.CpSolver()
    # REPRODUCIBLE, as the whole solve is (whole_solve): stopped by a count of interleaved batches, the workers
    # sharing no clauses -- the same model gives the same answer (a wall-clock limit on eight workers gave two answers
    # in two runs of zynq U1's array). `time_limit` caps the wall clock on top, and an answer it stops is not
    # reproducible.
    s_.parameters.num_workers = workers
    s_.parameters.interleave_search = True
    s_.parameters.max_num_deterministic_batches = batches or SOLVE_BATCHES
    s_.parameters.share_glue_clauses = False
    s_.parameters.share_binary_clauses = False
    if time_limit:
        s_.parameters.max_time_in_seconds = time_limit
    st = s_.Solve(mdl)
    chosen, ci = {}, {}              # ball -> (kind, option); ball -> its index
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for key in keys:
            for i, var in enumerate(v[key]):
                if s_.Value(var):
                    chosen[key] = opts[key][i][:2]
                    ci[key] = i
    # the choice against the laid geometry, apart from the lane model the pairs came from: two chosen options of two
    # balls whose copper the engine could not both lay (the lane model does not see, e.g., two plain moves crossing)
    clashes = []
    ck = sorted(chosen)
    for x_, a in enumerate(ck):
        ba = boxes[(a, ci[a])]
        for b in ck[x_ + 1:]:
            bb = boxes[(b, ci[b])]
            if ba[0] > bb[2] or bb[0] > ba[2] or ba[1] > bb[3] or bb[1] > ba[3]:
                continue
            if _hit(opts[a][ci[a]][2], opts[b][ci[b]][2], items[a][0] == items[b][0], sz):
                clashes.append((a, b))
    obj_orig = sum((W_BUS if items[k][0] in bus_s else (W_DROP if items[k][0] in drop_s else W_OTHER))
                   - cost(k, kind, o) for k, (kind, o) in chosen.items())
    hints = {}
    for key, (kind, o) in chosen.items():
        at = (round(balls[key][0], 3), round(balls[key][1], 3))
        if kind == 'escape':
            h = sr.full_move(o)
            # the move's own legs, always: the plan proved ITS legs clear of each other, and an exit alone is laid by
            # a search that reaches it by any cells (full_move carries them only under PLAN_PAGES)
            h['legs'] = [(tuple(a), tuple(b), L) for (a, b, L) in o.legs]
        elif kind == 'strap':
            h = {'kind': 'strap', 'to': tuple(o.b), 'layer': o.layer}
        else:
            h = {'kind': 'drop', 'site': tuple(o.site), 'layer': o.layer, 'inpad': bool(o.inpad)}
        h['strict'] = True
        hints[at] = h
    kinds = collections.Counter((('bus' if items[k][0] in bus_s else 'plane' if items[k][0] in drop_s
                                  else 'other'), kind) for k, (kind, _o) in chosen.items())
    rep = dict(status=s_.StatusName(st), balls=len(items), moves=n_moves, conflicts=len(pairs), conflict_groups=len(groups), conflict_bicliques=len(bigroups),
               bus_escaped=kinds[('bus', 'escape')],
               bus_balls=sum(1 for k in items if items[k][0] in bus_s),
               others_escaped=kinds[('other', 'escape')], others_strapped=kinds[('other', 'strap')],
               others_balls=sum(1 for k in items if items[k][0] in oth_s),
               dropped=kinds[('plane', 'drop')],
               dropped_in_pad=sum(1 for k, (kind, o) in chosen.items() if kind == 'drop' and o.inpad),
               plane_balls=sum(1 for k in items if items[k][0] in drop_s),
               no_move=sorted(k for k in items if not opts[k]),
               unplanned=sorted(k for k in items if k not in chosen), clashes=clashes,
               climbed=sum(1 for k, (kind, o) in chosen.items() if kind == 'escape' and getattr(o, 'climb', 0)),
               streets=sum(1 for k, (kind, o) in chosen.items() if kind == 'escape' and getattr(o, 'street', 0)),
               faces=dict(collections.Counter(f'{"bus" if items[k][0] in bus_s else "other"} {o.direction} '
                                              f'{o.layer} {o.kind}' for k, (kind, o) in chosen.items()
                                              if kind == 'escape')),
               let_go=list(let_go), phase1=s1.StatusName(st1), phase1_secs=round(t_p1, 1),
               secs=round(time.time() - t0, 1))
    if debug:
        # the model's pieces, for checking the answer against them (the conflict pairs, the options) and the solve's
        # own account of itself (objective, proved bound, wall time, branches)
        rep['debug'] = dict(items=items, opts=opts, pairs=pairs, groups=groups, bigroups=bigroups, chosen=chosen, cost=cost, sizes=sz,
                            objective=obj_orig if chosen else None, bound=s_.BestObjectiveBound(),
                            wall=s_.WallTime(), branches=s_.NumBranches(), conflicts_cp=s_.NumConflicts())
    log(f'  joint escape of {ref}: {rep["status"]} -- bus {rep["bus_escaped"]}/{rep["bus_balls"]}, others '
        f'{rep["others_escaped"]} escaped + {rep["others_strapped"]} strapped of {rep["others_balls"]}, plane '
        f'{rep["dropped"]} dropped ({rep["dropped_in_pad"]} in pad) of {rep["plane_balls"]}; '
        f'{rep["climbed"]} climbs, {rep["streets"]} street vias chosen; {len(rep["no_move"])} balls with no option; '
        f'{len(clashes)} chosen pairs clash in the laid geometry; served first {rep["phase1"]} in '
        f'{rep["phase1_secs"]} s' + (f', let go (a proved conflict) {rep["let_go"]}' if rep['let_go'] else '')
        + f'; {rep["secs"]} s')
    return hints, rep


def lay(board, out, ref, bus, others, other_layers, hints, other_pairs=()):
    """The plan laid in ONE call of the under-pad engine's joint escape (py_router/bga_fanout/underpad.py,
    joint=True): the planned moves on their own legs and the straps first, each net held to its layers (the bus to
    F/B, the others to `other_layers`) and the bus first; then the balls the plan could not place, by the under-pad
    grid's generic phases; the plane balls dropped (plane_drop auto: every net the call leaves out that owns a zone
    or six balls). Returns (tracks, vias, failed nets)."""
    import shutil
    from kicad_parser import parse_kicad_pcb
    from kicad_writer import add_tracks_and_vias_to_pcb
    from bga_fanout import generate_bga_fanout
    import braid as te
    import fanout_from_plan as fp
    import pairs as _pairs
    import ship_vias
    import source_realize as sr
    extra = dict(diff_pair_patterns=[f'{b}*' for b in other_pairs], diff_pair_gap=_pairs.GAP) if other_pairs else {}
    spec = {'net_layers': {**{n: list(OUTER) for n in bus}, **{n: list(other_layers) for n in others}},
            'priority': list(bus)}
    # the movable passives (the decoupling caps under the array) are not obstacles: the cap placement step follows
    # the bus step in the chain and moves them off this copper (geometry.immovable_foreign_pads)
    pcb = parse_kicad_pcb(board)
    tracks, vias_add, vias_rm, failed = generate_bga_fanout(
        pcb.footprints[ref], pcb, net_filter=list(bus) + list(others),
        layers=list(pcb.board_info.copper_layers), track_width=sr.FAN_TRACK, clearance=sr.FAN_CLEAR,
        via_size=te.VIA_SIZE, via_drill=te.VIA_DRILL, exit_margin=0.5, escape_method='jointescape',
        plane_drop='auto', escape_dir_hints=hints, bus=spec, **extra)
    if tracks or vias_add:
        add_tracks_and_vias_to_pcb(board, out, tracks, vias_add, vias_rm,
                                   net_id_to_name={i: n.name for i, n in pcb.nets.items()})
        ship_vias.stamp(out, 'joint escape', print)
    else:
        shutil.copy(board, out)
    fp.copy_pro(board, out)
    return len(tracks), len(vias_add), sorted(set(failed))


def bare_balls(board, ref, nets, track_width):
    """`ref`'s balls of `nets` with no copper of their net on them (bga_fanout.ball_has_copper, the board's copper)"""
    from kicad_parser import parse_kicad_pcb
    from bga_fanout import ball_has_copper
    with contextlib.redirect_stdout(io.StringIO()):
        pcb = parse_kicad_pcb(board)
    want = {short_name(n) for n in nets}
    vias = [{'x': v.x, 'y': v.y, 'size': v.size, 'net_id': v.net_id} for v in pcb.vias]
    tracks = [{'start': (s.start_x, s.start_y), 'end': (s.end_x, s.end_y), 'layer': s.layer, 'net_id': s.net_id}
              for s in pcb.segments]
    return [f'{short_name(p.net_name)}#{p.pad_number}' for p in pcb.footprints[ref].pads
            if p.net_id and short_name(p.net_name or '') in want and not ball_has_copper(p, vias, tracks, track_width)]


def carry(prev, cur, out, ref, others, drops, grow=1.5, release_near=()):
    """A later round of the whole route keeps the array's other nets and plane balls as the previous round laid them,
    as it keeps its own held teeth: each ball's PIECE on PREV -- its net's tracks and vias joined to it through their
    ends, inside the array's box grown by `grow` (an escape ends past the boundary line; a strap's piece reaches both
    its balls) -- is put on CUR, the round's board, if it still stands there: every track clear on its layer and every
    via on every layer, checked as plan_array checks an option (braid obstacles at the round's sizes, the movable
    passives skipped). OUT is CUR with the standing pieces. Returns (the ball keys NET#PAD to plan again -- a piece
    the round's bus copper now meets, or a ball that had none -- , pieces kept, pieces moved). `release_near` (ball
    keys): a piece whose balls stand within a pitch and a half of one of these is released too, so a ball left with
    no way down or out is planned again with its neighbours rather than round their held copper."""
    import braid as te
    import fanout_from_plan as fp
    import ship_vias
    from kicad_parser import parse_kicad_pcb
    from kicad_writer import add_tracks_and_vias_to_pcb
    with contextlib.redirect_stdout(io.StringIO()):
        old, now = parse_kicad_pcb(prev), parse_kicad_pcb(cur)
    want = {short_name(n) for n in list(others) + list(drops)}
    name_of = {i: short_name(n.name) for i, n in old.nets.items()}
    id_now = {short_name(n.name): i for i, n in now.nets.items()}
    foot = old.footprints[ref]
    xs, ys = [p.global_x for p in foot.pads], [p.global_y for p in foot.pads]
    box = (min(xs) - grow, min(ys) - grow, max(xs) + grow, max(ys) + grow)
    inside = lambda x, y: box[0] <= x <= box[2] and box[1] <= y <= box[3]     # noqa: E731
    segs, vias = collections.defaultdict(list), collections.defaultdict(list)
    for s in old.segments:
        if name_of.get(s.net_id) in want and inside(s.start_x, s.start_y) and inside(s.end_x, s.end_y):
            segs[s.net_id].append(s)
    for v in old.vias:
        if name_of.get(v.net_id) in want and inside(v.x, v.y):
            vias[v.net_id].append(v)
    near = lambda a, b: abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) < 1e-3    # noqa: E731
    balls = [p for p in foot.pads if p.net_id and name_of.get(p.net_id) in want]
    key_of = lambda p: f'{name_of[p.net_id]}#{p.pad_number}'                  # noqa: E731
    pieces, claimed = [], set()
    for p in balls:
        if key_of(p) in claimed:
            continue
        nid, got_s, got_v = p.net_id, [], []
        frontier = [(p.global_x, p.global_y)]
        while frontier:
            q = frontier.pop()
            for s in segs[nid]:
                if any(s is t for t in got_s):
                    continue
                a, b = (s.start_x, s.start_y), (s.end_x, s.end_y)
                if near(a, q) or near(b, q):
                    got_s.append(s)
                    frontier += [a, b]
            for v in vias[nid]:
                if not any(v is w for w in got_v) and near((v.x, v.y), q):
                    got_v.append(v)
        pts = [(s.start_x, s.start_y) for s in got_s] + [(s.end_x, s.end_y) for s in got_s] + [(v.x, v.y) for v in got_v]
        keys = sorted({key_of(b) for b in balls if b.net_id == nid
                       and any(near((b.global_x, b.global_y), q) for q in pts)} | {key_of(p)})
        claimed.update(keys)
        if got_s or got_v:
            pieces.append((keys, got_s, got_v))
    sz = _sizes(now, now.footprints[ref])
    skip = movable_refs(now, ref)
    cache = {}
    pos = {key_of(b): (b.global_x, b.global_y) for b in balls}
    stuck = [pos[k] for k in release_near if k in pos]
    if stuck:
        import escape_moves as em
        _g = em.grid_of(foot)
        reach = 1.5 * min(_g.pitch_x, _g.pitch_y)
    near_stuck = lambda keys: any(math.hypot(pos[k][0] - c[0], pos[k][1] - c[1]) < reach   # noqa: E731
                                  for k in keys if k in pos for c in stuck) if stuck else False

    def obs(nid, layer):
        if (nid, layer) not in cache:
            cache[(nid, layer)] = te.build_obstacles(now, nid, {nid}, layer, margin=sz['cl'] + sz['tw'] / 2,
                                                     skip_refs=skip)
        return cache[(nid, layer)]
    stand, moved = [], []
    for keys, ss, vv in pieces:
        nid = id_now.get(name_of[(ss or vv)[0].net_id])
        ok = nid is not None and not near_stuck(keys) \
            and all(obs(nid, s.layer).seg_clear((s.start_x, s.start_y), (s.end_x, s.end_y)) for s in ss) \
            and all(not (obs(nid, L).point_violation((v.x, v.y), pad=v.size / 2 - sz['tw'] / 2) or [0])[0]
                    for v in vv for L in now.board_info.copper_layers)
        (stand if ok else moved).append((keys, ss, vv))
    tracks = [{'start': (s.start_x, s.start_y), 'end': (s.end_x, s.end_y), 'width': s.width, 'layer': s.layer,
               'net_id': id_now[name_of[s.net_id]]} for _k, ss, _v in stand for s in ss]
    new_vias = [{'x': v.x, 'y': v.y, 'size': v.size, 'drill': v.drill, 'layers': list(v.layers),
                 'net_id': id_now[name_of[v.net_id]]} for _k, _s, vv in stand for v in vv]
    with contextlib.redirect_stdout(sys.stderr):
        add_tracks_and_vias_to_pcb(cur, out, tracks, new_vias, [],
                                   net_id_to_name={i: n.name for i, n in now.nets.items()})
        ship_vias.stamp(out, 'joint escape (carried)', print)
    fp.copy_pro(cur, out)
    kept = {k for keys, _s, _v in stand for k in keys}
    return sorted(key_of(p) for p in balls if key_of(p) not in kept), len(stand), len(moved)


def undropped_balls(board, ref, drops, track_width):
    """`ref`'s balls of the plane nets `drops` with no copper of their net on them (bare_balls) and no pour of their net
    on their own layer -- measured on the board, not taken from the engine's report, which a call that lays no drop
    pass leaves as an earlier call wrote it"""
    from kicad_parser import parse_kicad_pcb
    with contextlib.redirect_stdout(io.StringIO()):
        pcb = parse_kicad_pcb(board)
    poured = {(short_name(z.net_name or ''), z.layer) for z in (pcb.zones or []) if z.net_id}
    layers_of = {f'{short_name(p.net_name or "")}#{p.pad_number}': set(p.layers) for p in pcb.footprints[ref].pads}
    return [k for k in bare_balls(board, ref, drops, track_width)
            if not any((k.split('#')[0], L) in poured for L in layers_of.get(k, ()))]


def fan_array(board, out, ref, bus, others, other_layers, far=None, prefer=None, drops=(), log=print, only=None,
              rungs=None, filter_nets=(), **solve):
    """The array's joint escape at ONE size for the whole fanout: planned and laid at the chain's fan track and via,
    and -- only when a ball is left bare or a plane ball undropped -- the whole of it again at the next rung of the
    fab ladder, the via and the track stepped down TOGETHER (list_nets.escalation_rungs, as the under-pad shrink
    rescue steps them; never one via or one track on its own), until a rung serves every ball; else the rung that
    left the fewest bare, then the fewest undropped. OUT is that rung's board. Returns (its sizes, as rules.Rules,
    and a report per rung tried). The chain's own rules are back in place on return. `rungs` (rules.Rules): these
    sizes instead of the ladder -- a later round keeps the first round's; `only`: those balls alone (plan_array);
    `filter_nets`: more other nets for the engine's net filter, already laid (a later round's carried nets) -- the
    engine leaves a ball that carries its net's copper, and never meets an empty filter, which it reads as EVERY net
    (a round that planned plane drops alone fanned a refused bus net that way)."""
    import dataclasses
    import shutil
    import rules as _rules
    import fanout_from_plan as fp
    from kicad_parser import parse_kicad_pcb
    from list_nets import escalation_rungs
    base = _rules.active()
    with contextlib.redirect_stdout(io.StringIO()):
        ncu = len(parse_kicad_pcb(board).board_info.copper_layers or ()) or 4
    ladder = [base]
    for f in (escalation_rungs(ncu) if not rungs else ()):
        r = dataclasses.replace(base, fan_track=min(ladder[-1].fan_track, f['track_width']),
                                via_size=min(ladder[-1].via_size, f['via_diameter']),
                                via_drill=min(ladder[-1].via_drill, f['via_drill']))
        if (r.fan_track, r.via_size, r.via_drill) != (ladder[-1].fan_track, ladder[-1].via_size, ladder[-1].via_drill):
            ladder.append(r)
    if rungs:
        ladder = list(rungs)
    stem = out[:-len('.kicad_pcb')] if out.endswith('.kicad_pcb') else out
    reports, best = [], None
    try:
        for n, r in enumerate(ladder):
            _rules.install(r)
            with contextlib.redirect_stdout(io.StringIO()):
                pcb = parse_kicad_pcb(board)
            hints, rep = plan_array(pcb, ref, bus, others, other_layers, far=far, prefer=prefer, drops=drops, log=log,
                                    only=only, **solve)
            laid = f'{stem}.rung{n}.kicad_pcb'
            lay_others = list(others) + [n for n in filter_nets if n not in others]
            with contextlib.redirect_stdout(sys.stderr):
                lay(board, laid, ref, bus, lay_others, other_layers, hints)
            und = undropped_balls(laid, ref, drops, r.fan_track) if drops else []
            undropped = len(und)
            bare = bare_balls(laid, ref, list(bus) + list(others), r.fan_track)
            reports.append(dict(track=r.fan_track, via=r.via_size, drill=r.via_drill, bare=bare, undropped=undropped,
                                undropped_balls=und, status=rep['status'], planned_bus=rep['bus_escaped'],
                                planned_others=rep['others_escaped'] + rep['others_strapped'],
                                planned_drops=rep['dropped']))
            log(f'  joint escape of {ref} at track {r.fan_track} / via {r.via_size}/{r.via_drill}: {len(bare)} bare '
                f'ball(s){" " + str(bare) if bare else ""}, {undropped} plane ball(s) undropped'
                + (f' {und}' if und else ''))
            if best is None or (len(bare), undropped) < best[0]:
                best = ((len(bare), undropped), laid, r)
            if not bare and not undropped:
                break
    finally:
        _rules.install(base)
    shutil.copy(best[1], out)
    fp.copy_pro(best[1], out)
    return best[2], reports


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('board')
    ap.add_argument('ref')
    ap.add_argument('--bus', required=True, help='the bus nets, comma separated')
    ap.add_argument('--others', default='', help='the other nets fanned with it, comma separated')
    ap.add_argument('--dest', help='the other array: the bus never leaves by the face facing away from it')
    ap.add_argument('--prefer', help='a board whose bus teeth at REF the plan prefers to keep')
    ap.add_argument('--out', help='lay the plan: the fanned board')
    ap.add_argument('--batches', type=int, default=SOLVE_BATCHES, help='the solve\'s work budget (CP-SAT batches)')
    a = ap.parse_args()
    from kicad_parser import parse_kicad_pcb
    with contextlib.redirect_stdout(io.StringIO()):
        pcb = parse_kicad_pcb(a.board)
    bus = [n for n in a.bus.split(',') if n]
    others = [n for n in a.others.split(',') if n]
    prefer = preferred_teeth(a.prefer, a.ref, bus) if a.prefer else None
    far = far_face(pcb, a.ref, a.dest) if a.dest else None
    hints, rep = plan_array(pcb, a.ref, bus, others, signal_layers(pcb), far=far, prefer=prefer,
                            batches=a.batches)
    print({k: v for k, v in rep.items() if k not in ('unplanned', 'no_move')})
    if a.out:
        with contextlib.redirect_stdout(sys.stderr):
            n_t, n_v, failed = lay(a.board, a.out, a.ref, bus, others, signal_layers(pcb), hints)
        print(f'laid: {n_t} tracks, {n_v} vias, failed {failed}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
