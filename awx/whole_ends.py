"""whole_ends.py -- the whole route's own choice of ENDS: each net's tooth at the source and its berth at the
destination, chosen together from the fanout's escape menus (fanout_from_plan.plan_state: the destination menu, the
source menu, the teeth as laid), so the braid they make is cheap. fanout_from_plan's PLAN_JUDGE=ends chooses and
judges with it.

The ends decide the braid: the order of the teeth round the source and of the berths round the destination (read as
the whole frame reads them: whole_frame's boxes, cut and unrolled perimeters) fix every crossing, and the layers at
the two ends fix what a crossing costs. Two lanes cross only on different layers, so a crossing between two lanes on
ONE layer end to end sends one of them off its layer and back -- two changes; a lane whose end layers differ changes
once and can take its crossings on either side of that change; an OPPOSITE-HANDS pair on one layer end to end crosses
over at a dive (two changes) and takes its crossings there. A pair's change is two vias.

The route's changes are ESTIMATED from the ends alone, for the search: the end-layer changes and crossovers; two per
lane of a least-weight cover of the crossings between lanes on one layer end to end (exact: a permutation graph); then
the SETTLING of each lane whose end layers differ -- its one change serves its crossings with lanes on one layer end
to end only if none it must meet on its end layer is met, in a forced order, before one it must meet on its start
layer; broken, it takes an excursion or the fewest of those partners dive (an exact cut) -- and the COUPLING of two
such lanes that do not cross each other, when a pair of partners crossing each other must be met by them in orders no
single place of the partners' own crossing gives. Two lanes whose ends stand at one place round a box (an F end
stacked over a B one) have no order there. The best few states the searches reach are then ranked on the route EXACT
on their orders (exact_route: the whole solve's order model without its lengths, CP-SAT on one worker to a
deterministic work limit), and a state's judged objective is that one.

The objective is the whole solve's, in its order: first how far the nets go over two vias on the board (a net's stubs'
own vias, a tie via at a ball with a pad of its own under it, and its lane's changes), then the vias -- the ends' own
and the route's -- with each lane's ride (round the two arrays, and each leg's straight stubs from its balls to its
exits) at select_moves.VIA_MM per via, then CONGESTION on the trunk (each lane's load there past what the solve takes
freely, and each crossing there) and the whole route's FEEDBACK (ends its audits found crowded, whole_feedback), and
the crossings' count as the tie-break.

Searched locally -- one lane's tooth or berth at a time, one other lane
ejected where it is in the way, each improving change taken as it is found, sweep after sweep until none is left,
then iterated from random kicks until ILS_PATIENCE kicks
in a row find nothing -- first with the teeth as laid, then with the teeth free from the berths just chosen; tooth
moves are asked only when they save more than TOOTH_GAIN. Never taken: two moves the fanout cannot lay together
(select_moves._conflict, an F exit stacked over a B one allowed; a tooth move through another run net's LAID tooth;
two berths a destination pass laid in violation of each other); a pair's legs on different faces or layers, or exits
not neighbours; copper of a net outside the run between a pair's tips; a tooth on the source's far face (the whole
frame has no way round the source); a pair with another lane's end on its layer between its tips; a pair's joint move
the fanout refused.

usage: whole_ends.py BOARD NETS|@FILE  -- the ends on the teeth as laid, and with the teeth free, the objective's parts
for each (the fanout's menus as PLAN_JUDGE=ends builds them)
"""
import collections
import itertools
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'py_router'))

import pairs as _pairs  # noqa: E402
import braid as _bd  # noqa: E402
import select_moves as _sm  # noqa: E402
_LANE_PITCH = _bd.LANE_MIN                   # a crossing's length along a lane holding its line
_CHG_ROOM = 2 * 1.1 * _bd.VIA_NEED           # a layer change's room along its lane (whole_solve: VR_STAY x a via's room)

EPS_X = 0.01              # a crossing: the tie-break between ends of one via count
TOOTH_GAIN = 0.5          # tooth moves are asked only for at least half a via (a realize costs a fanout run)
DUP_TOL = _sm._STACK_PITCH / 2   # two exits this close are one (two distinct ones on a layer stand a pitch apart)
ILS_ROUNDS = 12           # iterated local search: kicks from the best state (a count, never a clock)
ILS_KICK = 3              # ... each moving this many lanes' ends to random options
ILS_PATIENCE = 4          # ... stopping after this many kicks in a row that find nothing (K15: none of 12 did)
ILS_SEED = 622
VIA_PREF = 2              # no more than two vias on a net where that can be had (whole_solve's first objective)
W_OVER = 100.0            # a via over two on a net: outweighs every via the ends could save
VIA_MM = _sm.VIA_MM       # a via is worth this much ride (the one exchange rate)
EXACT_TOP = 6             # the search's best distinct ends re-ranked on the exact route (best_exact) ...
EXACT_MARGIN = 4.0        # ... those within this much of the best by the estimate
EXACT_KMAX = 3            # a lane's changes at most in the exact route (the whole solve's KMAX)
EXACT_WORK = 20.0         # CP-SAT's deterministic work limit for one exact route
LOAD_OK = 0.5             # a lane's congestion on the trunk (score) the solve takes freely ...
W_CONG = 20.0             # ... past it, vias per the square of the overload
X_TRUNK = 0.2             # a crossing on the trunk, in vias
FB_AVOID = 5.0            # an end the whole route's audits found crowded (whole_feedback), in vias ...
FB_PAIR = 10.0            # ... two ends found crowded together
BIG = 100000.0            # a conflict, a split pair or a refused end: never taken
FAR = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}


def _seg_d(a, b, p, q):
    """the least distance between segments ab and pq"""
    def pt(u, v, w):
        dx, dy = w[0] - v[0], w[1] - v[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((u[0] - v[0]) * dx + (u[1] - v[1]) * dy) / L))
        return math.hypot(v[0] + t * dx - u[0], v[1] + t * dy - u[1])

    def cross(a, b, p, q):
        o = lambda u, v, w: (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
        return o(a, b, p) * o(a, b, q) < 0 and o(p, q, a) * o(p, q, b) < 0
    if cross(a, b, p, q):
        return 0.0
    return min(pt(a, p, q), pt(b, p, q), pt(p, a, b), pt(q, a, b))


def min_cut_cover(edges, wt):
    """the least-weight vertex cover of bipartite `edges` [(left, right)] (weights `wt`): a minimum s-t cut"""
    cap = collections.defaultdict(float)
    adj = collections.defaultdict(set)
    left, right = sorted({a for a, _b in edges}), sorted({b for _a, b in edges})

    def add(u, v, c):
        cap[(u, v)] += c; adj[u].add(v); adj[v].add(u)
    for a in left:
        add('s', ('L', a), wt[a])
    for b in right:
        add(('R', b), 't', wt[b])
    for a, b in edges:
        add(('L', a), ('R', b), math.inf)
    while True:
        prev = {'s': None}
        q = collections.deque(['s'])
        while q and 't' not in prev:
            u = q.popleft()
            for v in sorted(adj[u], key=repr):
                if v not in prev and cap[(u, v)] > 1e-12:
                    prev[v] = u; q.append(v)
        if 't' not in prev:
            break
        f, v = math.inf, 't'
        while prev[v] is not None:
            f = min(f, cap[(prev[v], v)]); v = prev[v]
        v = 't'
        while prev[v] is not None:
            cap[(prev[v], v)] -= f; cap[(v, prev[v])] += f; v = prev[v]
    return [a for a in left if ('L', a) not in prev] + [b for b in right if ('R', b) in prev]


class Ends:
    """the lanes of one plan state (a pair one lane) with their tooth and berth options, and the objective"""

    def __init__(self, st, src_free=True, fixed=None, learned=None, free_teeth=None):
        import pages_first as pf
        import source_realize as sr
        self.st = st
        names = [n for n in st['launch'] if st['dmenu'].get(n)]
        prs = {}
        if int(os.environ.get('PLAN_PAIRS', os.environ.get('BRAID_PAIRS', '0')) or 0):
            prs = {b: pr for b, pr in _pairs.pair_names(names).items() if pr[0] in names and pr[1] in names}
        legs = {l_ for pr in prs.values() for l_ in pr}
        self.lanes = [(n, (n,)) for n in names if n not in legs] + [(b, pr) for b, pr in prs.items()]
        self.legs_of = dict(self.lanes)
        sb, db = st['sgrid'].bbox, st['dgrid'].bbox
        cs = ((sb[0] + sb[2]) / 2, (sb[1] + sb[3]) / 2)
        cd = ((db[0] + db[2]) / 2, (db[1] + db[3]) / 2)
        if cd[0] <= cs[0] or abs(cd[1] - cs[1]) > cd[0] - cs[0]:
            raise SystemExit('whole_ends: the bench is not in the canonical frame (source to destination along +x)')
        far_dir = min(FAR, key=lambda d_: FAR[d_][0] * (cd[0] - cs[0]) + FAR[d_][1] * (cd[1] - cs[1]))
        cur = {n: pf.current_tooth(st, n) for n in names}
        # ---- each lane's options at each end: (moves per leg, point, layer, vias)
        rt = 1.3 * max(st['sgrid'].pitch_x, st['sgrid'].pitch_y)
        rb = 1.3 * max(st['dgrid'].pitch_x, st['dgrid'].pitch_y)

        def combos(menus, reach, forced=False):
            # (moves per leg, point, layer, vias, refused); `forced`: the ends as they stand, one option, REFUSED
            # when the whole route cannot take it (a pair's legs on different faces or layers, or not neighbours)
            if len(menus) == 1:
                return [((m,), m.exit_pt, m.layer, m.vias, False) for m in menus[0]]
            out = []
            for a in menus[0]:
                for b in menus[1]:
                    d = math.hypot(a.exit_pt[0] - b.exit_pt[0], a.exit_pt[1] - b.exit_pt[1])
                    ok = (a.direction, a.layer) == (b.direction, b.layer) and DUP_TOL < d <= reach
                    if ok or forced:
                        out.append(((a, b), ((a.exit_pt[0] + b.exit_pt[0]) / 2, (a.exit_pt[1] + b.exit_pt[1]) / 2),
                                    a.layer, a.vias + b.vias, not ok))
            return out
        fixed = fixed or {}
        banned = st.get('banned') or set()

        def unbanned(lg, opts):
            # a pair's options without the joint moves the fanout would not lay (fanout_from_plan.ban_moves)
            if len(lg) < 2:
                return opts
            return [o for o in opts if ('pair', lg[0], lg[1], sr.move_sig(o[0][0]), sr.move_sig(o[0][1])) not in banned]

        def same_as_laid(m, c):
            # a menu move that IS the laid tooth: its kind, face and layer, its exit within DUP_TOL (the menu's exit
            # stands on the array's edge line, the laid stub's end a hair off it) -- asked, it was realized as it
            # stood, three rounds running at K15 ('= original')
            return (c is not None and m.kind == c.kind and m.direction == c.direction and m.layer == c.layer
                    and math.hypot(m.exit_pt[0] - c.exit_pt[0], m.exit_pt[1] - c.exit_pt[1]) <= DUP_TOL)
        self.T, self.B = {}, {}
        for lane, lg in self.lanes:
            # (`free_teeth`: an incremental fanout frees only the teeth its feedback names; the rest stand as laid)
            held = not src_free or (free_teeth is not None and lane not in free_teeth)
            if held and all(cur[l_] is not None for l_ in lg):
                # the teeth as laid: the one option, refused on the source's far face
                self.T[lane] = [o[:4] + (o[4] or o[0][0].direction == far_dir,)
                                for o in combos([[cur[l_]] for l_ in lg], rt, forced=True)]
            else:
                tm = [[m for m in ([cur[l_]] if cur[l_] is not None else [])
                       + [m for m in st['smenu'].get(l_, []) if not same_as_laid(m, cur[l_])]
                       if m.direction != far_dir] for l_ in lg]
                self.T[lane] = unbanned(lg, combos(tm, rt))
                if not self.T[lane]:
                    # nothing clean to offer (a pair's legs with no clean combination, every joint move banned, the laid
                    # tooth on the far face): the options as they stand, REFUSED -- a lane with none stops the search
                    self.T[lane] = (combos(tm, rt, forced=True) if all(tm) else []) or \
                        ([o[:4] + (True,) for o in combos([[cur[l_]] for l_ in lg], rt, forced=True)]
                         if all(cur[l_] is not None for l_ in lg) else [])
            dm = [[m for m in st['dmenu'][l_] if l_ not in fixed or sr.move_sig(m) == fixed[l_]] or list(st['dmenu'][l_])
                  for l_ in lg]
            forced = all(l_ in fixed for l_ in lg)
            self.B[lane] = (combos(dm, rb, forced=forced) if forced else
                            unbanned(lg, combos(dm, rb)) or combos(dm, rb, forced=True))     # (nothing clean: refused)
        # a PAIR's end is refused where copper of a net OUTSIDE the run stands between its two tips on its layer: the
        # pair cannot be coupled there. A run net's stub there is no refusal: it moves with the search, and the score's
        # split count sees whichever of its options stands between the tips (the bench's SA6 stub between SCK's teeth
        # refused the teeth the human laid, and SA6's own menu has the move that clears them)
        run_ids = {st['byname'][l_][0] for _lane, lg in self.lanes for l_ in lg}
        fx = [(sg.layer, (sg.start_x, sg.start_y), (sg.end_x, sg.end_y), sg.width / 2, sg.net_id)
              for sg in st['pcb'].segments if sg.net_id not in run_ids]
        fx += [(L, (v.x, v.y), (v.x, v.y), v.size / 2, v.net_id) for v in st['pcb'].vias if v.net_id not in run_ids
               for L in ('F.Cu', 'B.Cu')]

        def between_tips(o, lg):
            (a, b), L = [m.exit_pt for m in o[0]], o[2]
            own = {st['byname'][l_][0] for l_ in lg}
            for L_, p, q, r, nid in fx:
                if L_ != L or nid in own:
                    continue
                if _seg_d(a, b, p, q) < _bd.TRACK / 2 + _bd.SPEC_CLEARANCE + r:
                    return True
            return False
        for lane, lg in self.lanes:
            if len(lg) == 2:
                self.T[lane] = [o[:4] + (o[4] or between_tips(o, lg),) for o in self.T[lane]]
                self.B[lane] = [o[:4] + (o[4] or between_tips(o, lg),) for o in self.B[lane]]
        self.cur = cur
        # a TIE VIA at the ball where a pad of the net's own lies under it on the other layer (fanout_from_plan.
        # tie_vias_under): one more via on that leg whatever its escapes
        self.tie = {l_: int(any(_pairs.under_pad(st['dst_pad'][l_], q, _bd.VIA_SIZE) for q in st['byname'][l_][1].pads))
                    for _l, lg in self.lanes for l_ in lg}
        # ---- the pad boxes the orders run round (grown, per state, by where its ends stand -- whole_frame's own)
        import whole_frame
        self.sbox, self.dbox = whole_frame.box_of(st['pcb'], st['sref']), whole_frame.box_of(st['pcb'], st['dref'])
        # ---- the moves the fanout cannot lay together
        kept = {0: collections.defaultdict(dict), 1: collections.defaultdict(dict)}
        for lane, lg in self.lanes:
            for end, opts in ((0, self.T[lane]), (1, self.B[lane])):
                for o in opts:
                    for leg, m in zip(lg, o[0]):
                        kept[end][leg][id(m)] = m
        conf = collections.defaultdict(set)
        for cands, strict in (({n: list(kept[0][n].values()) for n in names}, True),
                              ({n: list(kept[1][n].values()) for n in names}, bool(pf.PAGES_STRICT))):
            # stacked: the whole route orders each layer's lanes on their own, so an F exit over a B one is
            # no conflict
            for (a, i, b, j) in pf._conflicts(cands, strict, stack=True):
                conf[(a, id(cands[a][i]))].add((b, id(cands[b][j])))
                conf[(b, id(cands[b][j]))].add((a, id(cands[a][i])))
        # ...and a tooth move through another run net's LAID tooth (fanout_from_plan: sblock): a conflict with that
        # laid tooth alone -- the net's other options are free of it
        for (a, ida), bs in st.get('sblock', {}).items():
            for b in bs:
                if b != a and cur.get(b) is not None:
                    conf[(a, ida)].add((b, id(cur[b])))
                    conf[(b, id(cur[b]))].add((a, ida))
        # ...and the berth pairs a destination pass laid exactly but in violation of each other (`learned`: frozensets
        # of two move signatures, fanout_from_plan.fanout_destination): those two moves together, not either alone
        if learned:
            by_sig = collections.defaultdict(list)
            for n in names:
                for m in st['dmenu'][n]:
                    by_sig[sr.move_sig(m)].append((n, id(m)))
            for pr in learned:
                if len(pr) != 2:
                    continue
                sa, sb = tuple(pr)
                for (a, ia) in by_sig.get(sa, ()):
                    for (b, ib) in by_sig.get(sb, ()):
                        if a != b:
                            conf[(a, ia)].add((b, ib))
                            conf[(b, ib)].add((a, ia))
        self.conf = conf
        # ...and per OPTION: the other lanes' options (same end) it cannot be laid with -- a hit test is then a lookup
        where = collections.defaultdict(list)
        for lane, lg in self.lanes:
            for end, opts in ((0, self.T[lane]), (1, self.B[lane])):
                for i, o in enumerate(opts):
                    for leg, m in zip(lg, o[0]):
                        where[(leg, id(m), end)].append((lane, i))
        self.oconf = {}
        for lane, lg in self.lanes:
            for end, opts in ((0, self.T[lane]), (1, self.B[lane])):
                for i, o in enumerate(opts):
                    hit = set()
                    for leg, m in zip(lg, o[0]):
                        for (ol, oid) in conf.get((leg, id(m)), ()):
                            hit.update((ln, j) for ln, j in where.get((ol, oid, end), ()) if ln != lane)
                    self.oconf[(lane, end, i)] = hit
        self._ride = {}
        # ---- the whole route's FEEDBACK (whole_feedback: ends its audits found crowded, FEEDBACK= to the fanout): an
        # end to avoid costs FB_AVOID vias when chosen, a pair of ends FB_PAIR when both are -- the options matched
        # by their lane, their layer and each leg's exit at the end's points as laid
        self.fb_avoid, self.fb_pairs = collections.defaultdict(set), []

        def matches(it):
            lane, k = it['lane'], it['end']
            if lane not in self.legs_of:
                return set()
            opts = self.T[lane] if k == 0 else self.B[lane]
            return {i for i, o in enumerate(opts)
                    if o[2] == it['layer'] and len(o[0]) == len(it['points'])
                    and all(math.hypot(m.exit_pt[0] - p_[0], m.exit_pt[1] - p_[1]) <= DUP_TOL
                            for m, p_ in zip(o[0], it['points']))}
        fb = st.get('feedback') or {}
        for it in fb.get('avoid', ()):
            ix = matches(it)
            if ix:
                self.fb_avoid[(it['lane'], it['end'])] |= ix
        for a_, b_ in fb.get('pairs', ()):
            ma, mb = matches(a_), matches(b_)
            if ma and mb and a_['end'] == b_['end']:
                self.fb_pairs.append((a_['lane'], b_['lane'], a_['end'], ma, mb))
        self._xroute = {}          # the exact route per state (exact_route)
        self.pool = {}             # every search's result: its state -> its objective by the estimate
        self._memo = {}            # every state scored: its (objective, parts) -- the search asks a third of them again
        self._perim = {}           # a point's place round a grown box: one lane's move rarely moves the box

    def ride(self, lane, npair, ti, bi):
        """a lane's ride in mm, each leg's: round the destination and the source from its tooth to its berth
        (select_moves.ride_mm's own measure), and its STUBS -- each leg's straight run from its ball to its tooth's
        and its berth's exit (a laid tooth has no legs of its own to measure; the straight run measures every option
        alike). Without them a tooth that ran 5 mm inside the source's balls to leave by another face cost nothing
        (K15 SDQS1, via-in-pad on B from the east rows out through the north face)"""
        k = (lane, ti, bi)
        if k not in self._ride:
            import plan_ends as pe
            a, b = self.T[lane][ti][1], self.B[lane][bi][1]
            d = pe.sm.around_box(a, b, self.st['dboxes'])
            d += pe.sm.around_box(a, b, self.st['sgrid'].bbox) - math.hypot(b[0] - a[0], b[1] - a[1])
            lg = dict(self.lanes)[lane]
            stubs = 0.0
            for leg, tm, bm in zip(lg, self.T[lane][ti][0], self.B[lane][bi][0]):
                sp_, dp_ = self.st['src_pad'][leg], self.st['dst_pad'][leg]
                stubs += math.hypot(tm.exit_pt[0] - sp_.global_x, tm.exit_pt[1] - sp_.global_y)
                stubs += math.hypot(bm.exit_pt[0] - dp_.global_x, bm.exit_pt[1] - dp_.global_y)
            self._ride[k] = npair * d + stubs
        return self._ride[k]

    # ---- the objective
    def score(self, state, exact=False):
        """(objective, parts) of a state {lane: (tooth option index, berth option index)}: each state scored once
        (the local search asks a third of its states again -- an ejection's winner is scored in the min and then again,
        a sweep revisits the kicks' states)"""
        key = (tuple(state[l_] for l_, _lg in self.lanes), exact)
        got = self._memo.get(key)
        if got is None:
            got = self._memo[key] = self._score(state, exact)
        return got

    def _score(self, state, exact=False):
        import whole_frame
        T, B = self.T, self.B
        lanes = [l_ for l_, _lg in self.lanes]
        npair = {l_: len(lg) for l_, lg in self.lanes}
        to = {l_: T[l_][state[l_][0]] for l_ in lanes}
        bo = {l_: B[l_][state[l_][1]] for l_ in lanes}
        fan = sum(to[l_][3] + bo[l_][3] + sum(self.tie[g] for g in lg) for l_, lg in self.lanes)
        # the moves chosen, for the conflicts
        chosen = set()
        for l_, lg in self.lanes:
            for leg, m in zip(lg, to[l_][0]):
                chosen.add((leg, id(m)))
            for leg, m in zip(lg, bo[l_][0]):
                chosen.add((leg, id(m)))
        nconf = sum(1 for c in chosen for o in self.conf.get(c, ()) if o in chosen) // 2
        nref = sum(1 for l_ in lanes if to[l_][4] or bo[l_][4])
        # the orders, as the whole frame reads them (whole_frame.build)
        SB = whole_frame.grown(self.sbox, [to[l_][1] for l_ in lanes])
        DB = whole_frame.grown(self.dbox, [bo[l_][1] for l_ in lanes])
        pc = self._perim

        def dface(p):
            k = ('face', p, DB)
            if k not in pc:
                pc[k] = whole_frame.face(p, DB)
            return pc[k]
        cut = whole_frame.cut([bo[l_][1][1] for l_ in lanes if dface(bo[l_][1]) == 'E'], DB[1], DB[3])

        def psrc(p):
            k = (p, SB)
            if k not in pc:
                pc[k] = whole_frame.perim_s(p, SB)
            return pc[k]

        def pdst(p):
            k = (p, DB, cut)
            if k not in pc:
                pc[k] = whole_frame.perim_d(p, DB, cut)
            return pc[k]
        ps = {l_: psrc(to[l_][1]) for l_ in lanes}
        pd = {l_: pdst(bo[l_][1]) for l_ in lanes}
        tl = {l_: to[l_][2] for l_ in lanes}
        dl = {l_: bo[l_][2] for l_ in lanes}
        # strict orders: a tie broken by the lane's place in the run, the same way in both
        idx = {l_: i for i, l_ in enumerate(lanes)}
        kp = {l_: (ps[l_], idx[l_]) for l_ in lanes}
        kd = {l_: (pd[l_], idx[l_]) for l_ in lanes}
        inv = [(a, b) for a, b in itertools.combinations(lanes, 2) if (kp[a] < kp[b]) != (kd[a] < kd[b])]
        flat = {l_: tl[l_] == dl[l_] for l_ in lanes}
        same = [(a, b) for a, b in inv if flat[a] and flat[b] and tl[a] == tl[b]]
        # split pairs: another lane's end on the pair's layer between its two tips, at either end
        nsplit = 0
        if any(len(lg) > 1 for _l, lg in self.lanes):
            # every leg's place round each box, once
            legs_at = [(to, {l_: [psrc(m.exit_pt) for m in to[l_][0]] for l_ in lanes}, SB),
                       (bo, {l_: [pdst(m.exit_pt) for m in bo[l_][0]] for l_ in lanes}, DB)]
            for l_, lg in self.lanes:
                if len(lg) < 2:
                    continue
                for opt, pv, B_ in legs_at:
                    whole = 2 * (B_[2] - B_[0] + B_[3] - B_[1])
                    a_, b_ = sorted(pv[l_])
                    L = opt[l_][2]
                    for o in lanes:
                        if o == l_ or opt[o][2] != L:
                            continue
                        if any(whole_frame.between(a_, b_, v, whole) for v in pv[o]):
                            nsplit += 1
        parity = sum(npair[l_] for l_ in lanes if not flat[l_])
        # an OPPOSITE-HANDS pair (pairs.opposite_hands: P on one side of its travel at its tooth, on the other arriving
        # at its berth) crosses over at a dive: on one layer end to end, that is two changes -- and a lane already off
        # its layer and back takes its crossings there at no more
        xo = {}
        for l_, lg in self.lanes:
            xo[l_] = 0
            if len(lg) == 2 and flat[l_]:
                (tp, tn), (bp, bn) = to[l_][0], bo[l_][0]
                a_ = _pairs.hand(tp.direction, tp.exit_pt, tn.exit_pt)
                b_ = _pairs.hand(bp.direction, bp.exit_pt, bn.exit_pt, arriving=True)
                xo[l_] = 2 if a_ and b_ and a_ != b_ else 0
        same = [(a, b) for a, b in same if not xo[a] and not xo[b]]
        # a net's vias on the board: its stubs' own (a pair's leg the more) and its lane's changes -- one for ends on
        # two layers, two more for a lane leaving its layer to cross; how far that goes over two is priced first,
        # as the whole solve does
        sv = {l_: max(t_.vias + b_.vias + self.tie[g] for g, t_, b_ in zip(lg, to[l_][0], bo[l_][0]))
              for l_, lg in self.lanes}
        base = {l_: sv[l_] + (0 if flat[l_] else 1) + xo[l_] for l_ in lanes}
        ov = lambda l_, k_: max(0, base[l_] + k_ - VIA_PREF)
        w = {l_: 2 * npair[l_] + W_OVER * (ov(l_, 2) - ov(l_, 0)) for l_ in lanes}
        cov = self._cover([l_ for l_ in lanes if flat[l_] and not xo[l_]], tl, kp, kd, w)
        cover = sum(npair[l_] for l_ in cov)
        cross = sum(npair[l_] * xo[l_] for l_ in lanes)
        # each lane's changes so far: one for ends on two layers, two for a crossover pair, two for a lane of the cover
        chg = {l_: (0 if flat[l_] else 1) + xo[l_] + (2 if l_ in cov else 0) for l_ in lanes}
        # ...then each lane whose ends differ SETTLES the crossings its one change cannot serve. It crosses the lanes on
        # one layer end to end on the other layer: before its change those on its end layer, after it those on its
        # start layer. Two of them met in the wrong order break that -- when the order is forced: two lanes that do
        # not cross each other are met in the order the straight lines from launch rank to final rank meet them (two
        # that do, the solve orders). Broken, either the lane takes one excursion more (two changes) or the fewest of
        # those partners dive (an exact cut: the broken pairs are bipartite) -- fewer nets over two vias first, then
        # fewer vias, as the whole solve decides (K15: SDQ15 met four lanes on its end layer, then SDQS1 on its start
        # layer; the bound said 4 route vias, the solve paid 12)
        rl = {l_: i for i, l_ in enumerate(sorted(lanes, key=lambda l_: kp[l_]))}
        rf = {l_: i for i, l_ in enumerate(sorted(lanes, key=lambda l_: kd[l_]))}
        xs = collections.defaultdict(list)
        for a, b in inv:
            xs[a].append(b); xs[b].append(a)
        cset = {frozenset(e) for e in inv}
        tcr = lambda n, m: (rl[m] - rl[n]) / ((rl[m] - rl[n]) - (rf[m] - rf[n]))
        ovk = lambda l_, k_: max(0, sv[l_] + k_ - VIA_PREF)
        settle = 0
        for n in sorted((l_ for l_ in lanes if not flat[l_]), key=lambda l_: rl[l_]):
            ps = [(m, 'B.Cu' if tl[m] == 'F.Cu' else 'F.Cu') for m in sorted(xs[n], key=lambda m: tcr(n, m))
                  if flat[m] and chg[m] == 0]
            bad = [(a, b) for (a, na), (b, nb) in itertools.combinations(ps, 2)
                   if na == dl[n] and nb == tl[n] and frozenset((a, b)) not in cset]
            if not bad:
                continue
            wt = {m: W_OVER * (ovk(m, 2) - ovk(m, 0)) + 2 * npair[m] for e in bad for m in e}
            div = min_cut_cover(bad, wt)
            if W_OVER * (ovk(n, chg[n] + 2) - ovk(n, chg[n])) + 2 * npair[n] <= sum(wt[m] for m in div):
                chg[n] += 2
                settle += 2 * npair[n]
            else:
                for m in div:
                    chg[m] = 2
                    settle += 2 * npair[m]
        # ...then the lanes whose settling SHARES a choice. Two partners on one layer end to end that cross each other
        # (a, b; on different layers, neither diving) are met by a lane crossing both in the order the partners'
        # own crossing P decides: a lane that a meets before P meets first the partner it would meet with a and b
        # still uncrossed -- the nearer at launch, or a when they start either side of it -- and one met after P the
        # other. Two lanes that do not cross each other are met by a in a forced order, so the first cannot need P
        # after it while the second needs P before it (K15: SDQ11 needed SDQ15 first, SDQ9 met after it needed
        # SDQS1 first; each alone settled, together one of the four took an excursion). Each such conflict is
        # resolved by one of its four lanes -- an excursion (two changes) or a partner's dive -- the cheapest first,
        # fewer nets over two vias before fewer vias
        couple = 0
        conflicts = []
        # two lanes whose ends stand at one place round a box (an F tooth stacked over a B one) have no order
        # there: whether they cross is the route's to choose, so no order through them is forced
        tie = lambda x, y: abs(kp[x][0] - kp[y][0]) < 1e-3 or abs(kd[x][0] - kd[y][0]) < 1e-3
        for a, b in inv:
            if not (flat[a] and flat[b] and chg[a] == 0 and chg[b] == 0 and tl[a] != tl[b]) or tie(a, b):
                continue
            ns = [n for n in set(xs[a]) & set(xs[b]) if not flat[n] and chg[n] == 1
                  and not tie(n, a) and not tie(n, b)]
            if len(ns) < 2:
                continue
            want = {}
            for n in ns:
                first = a if tl[n] != tl[a] else b             # the partner asking n's start layer
                if (rl[a] - rl[n]) * (rl[b] - rl[n]) > 0:
                    pre = a if abs(rl[a] - rl[n]) < abs(rl[b] - rl[n]) else b
                else:
                    pre = a
                want[n] = first == pre                           # True: n needs P after it along a
            ns.sort(key=lambda n: tcr(a, n))
            for i, n1 in enumerate(ns):
                for n2 in ns[i + 1:]:
                    if frozenset((n1, n2)) not in cset and not tie(n1, n2) and not want[n1] and want[n2]:
                        conflicts.append((a, b, n1, n2))
        while conflicts:
            def fix_cost(x):
                return (W_OVER * (ovk(x, chg[x] + 2) - ovk(x, chg[x])) + 2 * npair[x]) if not flat[x] else \
                    (W_OVER * (ovk(x, 2) - ovk(x, 0)) + 2 * npair[x])
            cand = sorted({x for c in conflicts for x in c}, key=lambda x: idx[x])
            x = min(cand, key=lambda x: (fix_cost(x) / sum(1 for c in conflicts if x in c), idx[x]))
            chg[x] = chg[x] + 2 if not flat[x] else 2
            couple += 2 * npair[x]
            conflicts = [c for c in conflicts if x not in c]
        over = sum(ovk(l_, chg[l_]) for l_ in lanes)
        route = sum(npair[l_] * chg[l_] for l_ in lanes)
        route_est = route
        # ---- CONGESTION on the trunk (the whole frame's straight run between the two arrays, whole_frame): a crossing
        # with a lane off the lane's own ring happens there and takes a lane pitch along it, and a lane that berths on
        # the destination's near face changes layer there, a change taking its room; a lane's LOAD is what it needs
        # over the trunk's length. The solve can take a load to LOAD_OK freely (K28's ends: 0.5 at most, solved in 6
        # s); past it each lane pays W_CONG vias per the square of its overload (K35's: 0.8, 173 crossings on a 6.5
        # mm trunk, the solve found no plan)
        dcls = {}
        for l_ in lanes:
            f_ = dface(bo[l_][1])
            dcls[l_] = ('N' if bo[l_][1][1] < cut else 'S') if f_ == 'E' else f_
        gT = max(DB[0] - SB[2], _LANE_PITCH)
        xT = collections.Counter()
        for a, b in inv:
            if not (dcls[a] == dcls[b] and dcls[a] != 'W'):
                xT[a] += 1; xT[b] += 1
        # ...and each crossing on the trunk its price, X_TRUNK vias, whatever the load: the solve's work grows with the
        # crossings it must place there, and ends with fewer of them are the easy ones (the human's K35 ends: 48 on
        # the trunk against our 94-173, for two vias more, by berths on the destination's far face)
        cong = X_TRUNK * sum(xT.values()) / 2
        for l_ in lanes:
            load = (xT[l_] * _LANE_PITCH + (chg[l_] if dcls[l_] == 'W' else 0) * _CHG_ROOM) / gT
            over_ = max(0.0, load - LOAD_OK)
            cong += npair[l_] * W_CONG * over_ * over_
        if exact:
            # the route EXACT on the orders (Ends.exact_route): what the estimate above approximates
            xr = self.exact_route(state, lanes, kp, kd, tl, dl, sv, xo, npair)
            if xr is not None:
                route, over, chg = xr
        ride = sum(self.ride(l_, npair[l_], state[l_][0], state[l_][1]) for l_ in lanes)
        fbk = (FB_AVOID * sum(1 for (l_, k_), ix in self.fb_avoid.items() if state[l_][k_] in ix)
               + FB_PAIR * sum(1 for a_, b_, k_, ia, ib in self.fb_pairs if state[a_][k_] in ia and state[b_][k_] in ib))
        obj = W_OVER * over + fan + route + ride / VIA_MM + cong + fbk + EPS_X * len(inv) + BIG * (nconf + nsplit + nref)
        return obj, dict(fan=fan, parity=parity, crossover=cross, cover=cover, settle=settle, couple=couple,
                         route=route, route_est=route_est, over=over, cong=round(cong, 2), feedback=fbk,
                         ride=round(ride, 1), chg=chg,
                         crossings=len(inv), same=len(same), conflicts=nconf, splits=nsplit, refused=nref)

    def exact_route(self, state, lanes, kp, kd, tl, dl, sv, xo, npair):
        """(route vias, nets over two, changes per lane) of a state EXACT on its orders: the whole solve's order model
        without its lengths -- every inverted pair crossing once at a position, the braid triple rule, each lane's
        changes between its crossings, two crossing lanes on different layers there, an opposite-hands pair crossed
        over at a dive -- CP-SAT on the solve's own objective (nets over two vias first, then vias, a pair's change two):
        its optimum, or the best plan it finds within its work limit. Two lanes at one place round a box (an F end stacked over a B one) are taken in the order
        that does not cross them there. One worker and a deterministic work limit: the same answer on every machine;
        None when it finds no plan in that work (the estimate stands)"""
        key = tuple(sorted(state.items()))
        if key in self._xroute:
            return self._xroute[key]
        from ortools.sat.python import cp_model
        idx = {l_: i for i, l_ in enumerate(lanes)}
        rkd = {l_: i for i, l_ in enumerate(sorted(lanes, key=lambda l_: kd[l_]))}
        rkp = {l_: i for i, l_ in enumerate(sorted(lanes, key=lambda l_: kp[l_]))}
        Ln = sorted(lanes, key=lambda l_: (round(kp[l_][0], 3), rkd[l_], idx[l_]))
        Fn = sorted(lanes, key=lambda l_: (round(kd[l_][0], 3), rkp[l_], idx[l_]))
        li = {l_: i for i, l_ in enumerate(Ln)}
        fi = {l_: i for i, l_ in enumerate(Fn)}
        X = [(a, b) for a, b in itertools.combinations(Ln, 2) if (li[a] < li[b]) == (fi[a] > fi[b])]
        m = cp_model.CpModel()
        H = 2 * len(X) + 2
        t = {k: m.NewIntVar(1, H, '') for k in X}
        for i, j, k in itertools.combinations(Ln, 3):
            ij, ik, jk = (i, j) in t, (i, k) in t, (j, k) in t
            if ij and ik and jk:
                b_ = m.NewBoolVar('')
                m.Add(t[(i, j)] < t[(i, k)]).OnlyEnforceIf(b_); m.Add(t[(i, k)] < t[(j, k)]).OnlyEnforceIf(b_)
                m.Add(t[(j, k)] < t[(i, k)]).OnlyEnforceIf(b_.Not()); m.Add(t[(i, k)] < t[(i, j)]).OnlyEnforceIf(b_.Not())
            elif ij and ik:
                m.Add(t[(i, j)] < t[(i, k)])
            elif ik and jk:
                m.Add(t[(j, k)] < t[(i, k)])
        ev = {l_: [k for k in X if l_ in k] for l_ in lanes}
        for l_ in lanes:
            if len(ev[l_]) > 1:
                m.AddAllDifferent([t[k] for k in ev[l_]])
        F_ = lambda L: int(L == 'B.Cu')
        before, act_of, cost = {}, {}, []
        for l_ in lanes:
            cs = [m.NewIntVar(0, H + 1, '') for _ in range(EXACT_KMAX)]
            act = [m.NewBoolVar('') for _ in range(EXACT_KMAX)]
            for k in range(EXACT_KMAX):
                m.Add(cs[k] <= H).OnlyEnforceIf(act[k]); m.Add(cs[k] == H + 1).OnlyEnforceIf(act[k].Not())
                if k:
                    m.Add(cs[k] > cs[k - 1]).OnlyEnforceIf(act[k]); m.AddImplication(act[k], act[k - 1])
            for key_ in ev[l_]:
                bits = []
                for k in range(EXACT_KMAX):
                    bb = m.NewBoolVar('')
                    m.Add(cs[k] < t[key_]).OnlyEnforceIf(bb); m.Add(cs[k] > t[key_]).OnlyEnforceIf([bb.Not(), act[k]])
                    m.AddImplication(bb, act[k]); bits.append(bb)
                before[(l_, key_)] = bits
            m.AddBoolXOr(act + ([m.NewConstant(1)] if tl[l_] == dl[l_] else []))
            if xo.get(l_):
                m.Add(act[0] == 1)              # an opposite-hands pair crosses over at a dive
            n_ = sum(act)
            ov = m.NewIntVar(0, EXACT_KMAX + 8, '')
            m.Add(ov >= sv[l_] + n_ - VIA_PREF)
            act_of[l_] = act
            cost.append(int(W_OVER) * ov + npair[l_] * n_)
        for key_ in X:
            a, b = key_
            lits = before[(a, key_)] + before[(b, key_)]
            if F_(tl[a]) ^ F_(tl[b]):
                lits = lits + [m.NewConstant(1)]
            m.AddBoolXOr(lits)
        m.Minimize(sum(cost))
        sol = cp_model.CpSolver()
        sol.parameters.num_workers = 1
        sol.parameters.max_deterministic_time = EXACT_WORK
        r = sol.Solve(m)
        out = None
        if r in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            chg = {l_: sum(sol.Value(a) for a in act_of[l_]) for l_ in lanes}
            out = (sum(npair[l_] * chg[l_] for l_ in lanes),
                   sum(max(0, sv[l_] + chg[l_] - VIA_PREF) for l_ in lanes), chg)
        self._xroute[key] = out
        return out

    def best_exact(self, state, log=print):
        """(state, (objective, parts)): of `state` and the searches' best distinct ends so far (the pool, within
        EXACT_MARGIN of the best by the estimate, EXACT_TOP of them), the best by the EXACT route. The estimate steers
        the search; the orders it cannot see (a crossing pair met by two lanes in the orders each needs, a cover's
        excursion that cannot hold every crossing it must) decide among its best"""
        ranked = sorted(self.pool.items(), key=lambda kv: (kv[1], kv[0]))
        v0 = ranked[0][1] if ranked else None
        cands = [dict(k) for k, v in ranked[:EXACT_TOP] if v <= v0 + EXACT_MARGIN]
        if dict(state) not in cands:
            cands.append(dict(state))
        best = None
        for s_ in cands:
            v_, p_ = self.score(s_, exact=True)
            if best is None or v_ < best[1][0] - 1e-9:
                best = (s_, (v_, p_))
        if best[0] != dict(state):
            log(f'  whole ends: by the exact route, another of the search\'s best: {_fmt(best[1][1])}')
        return best

    @staticmethod
    def _cover(flat_lanes, layer, kp, kd, w):
        """the lanes of least weight `w` covering every crossing between two of `flat_lanes` on one layer: EXACT. On a
        layer those crossings are the inversions between the two orders -- a permutation graph -- so what needs no
        cover is the heaviest chain rising in both, and the cover is the rest (an O(n^2) chain, per layer)"""
        out = set()
        for L in sorted({layer[l_] for l_ in flat_lanes}):
            ls = sorted((l_ for l_ in flat_lanes if layer[l_] == L), key=lambda l_: kp[l_])
            best, prev = {}, {}
            for i, a in enumerate(ls):
                best[a], prev[a] = w[a], None
                for b in ls[:i]:
                    if kd[b] < kd[a] and best[b] + w[a] > best[a]:
                        best[a], prev[a] = best[b] + w[a], b
            if not ls:
                continue
            chain, x = set(), max(ls, key=lambda l_: (best[l_], -kp[l_][1]))
            while x is not None:
                chain.add(x); x = prev[x]
            out |= set(ls) - chain
        return out

    # ---- the search
    def start(self, seed=None):
        """the teeth as laid (their own option, else the cheapest clear one), the berths at `seed` {net: Move}
        (default: the fanout's greedy selection, plan_ends.sm.select -- every berth clear of the others), a pair at
        the combination nearest its legs' there; a lane the seed leaves out at its cheapest berth clear of those
        taken"""
        import plan_ends as pe
        import source_realize as sr
        st = self.st
        if seed is None:
            pads = {nm: (st['dst_pad'][nm].global_x, st['dst_pad'][nm].global_y) for nm in st['dst_pad']}
            seed, _un = pe.sm.select(st['dmenu'], st['launch'], keep_out=st['dboxes'], buses=st['buses'],
                                     tooth_layer=st['tooth0'], log=None, pads=pads, chi=st['chi'])
        greedy = seed
        state = {l_: (None, None) for l_, _lg in self.lanes}
        for lane, lg in self.lanes:
            ti = next((i for i, o in enumerate(self.T[lane]) if all(m is self.cur.get(l_) for l_, m in zip(lg, o[0]))),
                      None)
            want = [greedy.get(l_) for l_ in lg]
            if all(w is not None for w in want):
                bi = min(range(len(self.B[lane])), default=None,
                         key=lambda i: sum(math.hypot(m.exit_pt[0] - w.exit_pt[0], m.exit_pt[1] - w.exit_pt[1])
                                           + (0 if sr.move_sig(m) == sr.move_sig(w) else 1e-3)
                                           for m, w in zip(self.B[lane][i][0], want)))
            else:
                bi = None
            state[lane] = (ti, bi)
        for lane, lg in self.lanes:
            for end in (0, 1):
                if state[lane][end] is None:
                    opts = self.T[lane] if end == 0 else self.B[lane]
                    free = [i for i in range(len(opts)) if self._clear(state, lane, end, i)] or list(range(len(opts)))
                    i = min(free, key=lambda i: opts[i][3]) if free else None
                    state[lane] = (i, state[lane][1]) if end == 0 else (state[lane][0], i)
        return state

    def _hits(self, state, lane, end, i):
        """the other lanes whose chosen moves (at the same end) a lane's option i conflicts with"""
        return {o for o, j in self.oconf[(lane, end, i)] if state[o][end] == j}

    def _clear(self, state, lane, end, i):
        return not self._hits(state, lane, end, i)

    def search(self, state=None, sweeps=20, log=print):
        """each improving change of one lane's tooth or berth (one other lane ejected where it is in the way), taken as
        it is found, sweep after sweep until a sweep finds none"""
        state = dict(state or self.start())
        missing = [l_ for l_ in state if state[l_][0] is None or state[l_][1] is None]
        if missing:
            raise SystemExit(f'whole_ends: no tooth or berth option for {missing}')
        best, parts = self.score(state)
        set_ = lambda s_, l_, e_, i_: {**s_, l_: ((s_[l_][0], i_) if e_ else (i_, s_[l_][1]))}
        for sw in range(sweeps):
            improved = False
            for lane, _lg in self.lanes:
                for end in (1, 0):
                    opts = self.B[lane] if end else self.T[lane]
                    for i in range(len(opts)):
                        if i == state[lane][end]:
                            continue
                        hits = self._hits(state, lane, end, i)
                        if len(hits) > 1:
                            continue
                        trial = set_(state, lane, end, i)
                        if hits:
                            # an EJECTION: the one lane in the way moves to its best option clear of the others
                            (o,) = hits
                            oo = self.B[o] if end else self.T[o]
                            cands = [j for j in range(len(oo)) if self._clear(trial, o, end, j)]
                            if not cands:
                                continue
                            trial = min((set_(trial, o, end, j) for j in cands), key=lambda s_: self.score(s_)[0])
                        v, p_ = self.score(trial)
                        if v < best - 1e-9:
                            best, parts, state, improved = v, p_, trial, True
            log(f'  whole ends: sweep {sw}: objective {best:.2f} {parts}')
            if not improved:
                break
        self.pool[tuple(sorted(state.items()))] = best
        return state

    def iterate(self, state, rounds=None, log=print):
        """ITERATED local search from `state` (already a local optimum): `rounds` times, the best state with KICK lanes'
        ends moved to random options (a fixed seed: the same answer on every machine), searched again, kept when
        better. A one-lane search stops in the first basin it reaches: at K41 it found 74 vias from the greedy's berths
        and 66 from the human's"""
        import random
        rounds = ILS_ROUNDS if rounds is None else rounds
        rng = random.Random(ILS_SEED)
        best, (bv, bp) = dict(state), self.score(state)
        lanes = [l_ for l_, _lg in self.lanes]
        idle = 0
        for r in range(rounds):
            if idle >= ILS_PATIENCE:
                break                   # that many kicks in a row found nothing: the basin is the best one near
            s_ = dict(best)
            for l_ in rng.sample(lanes, min(ILS_KICK, len(lanes))):
                e_ = rng.randrange(2) if len(self.T[l_]) > 1 else 1
                opts = self.T[l_] if e_ == 0 else self.B[l_]
                i_ = rng.randrange(len(opts))
                s_[l_] = (i_, s_[l_][1]) if e_ == 0 else (s_[l_][0], i_)
            s_ = self.search(s_, log=lambda *a: None)
            v_, p_ = self.score(s_)
            if v_ < bv - 1e-9:
                best, bv, bp = s_, v_, p_
                idle = 0
                log(f'  whole ends: kick {r}: objective {bv:.2f} {bp}')
            else:
                idle += 1
        return best

    def choice(self, state):
        """(the berths {net: Move}, the teeth to MOVE {net: Move}) of a state"""
        dst, src = {}, {}
        for lane, lg in self.lanes:
            for leg, m in zip(lg, self.B[lane][state[lane][1]][0]):
                dst[leg] = m
            for leg, m in zip(lg, self.T[lane][state[lane][0]][0]):
                if m is not self.cur.get(leg):
                    src[leg] = m
        return dst, src


def choose(st, log=print, src_free=True, fixed=None, seed=None, learned=None, free_teeth=None):
    """the whole route's ends on a plan state: (berths {net: Move}, teeth to move {net: Move}). The berths are first
    searched against the teeth AS LAID (the laid objective, `choose.last['laid']`: what a realized board is judged
    on); with `src_free` the teeth are searched too, from there, and their moves asked only when that is better.
    `fixed` {net: move signature}: berths held; `seed` {net: Move}: the berths to start from; `learned`: berth pairs
    not to be laid together (Ends); `free_teeth` {lane}: with `src_free`, only these lanes' teeth move"""
    quiet = lambda *a: None
    E = Ends(st, src_free=False, fixed=fixed, learned=learned)
    sL = E.iterate(E.search(E.start(seed), log=quiet), log=quiet)
    sL, (vL, pL) = E.best_exact(sL, log=log)
    out, vF, pF = E.choice(sL), None, None
    log(f'  whole ends: on the teeth as laid: {_fmt(pL)}')
    if src_free:
        E2 = Ends(st, src_free=True, fixed=fixed, learned=learned, free_teeth=free_teeth)
        # a local search from the berths just chosen on the teeth as laid, iterated
        sF = E2.iterate(E2.search(E2.start(out[0]), log=quiet), log=quiet)
        sF, (vF, pF) = E2.best_exact(sF, log=log)
        if vF < vL - TOOTH_GAIN:
            out = E2.choice(sF)
            log(f'  whole ends: teeth moved ({len(out[1])}): {_fmt(pF)}')
        else:
            log('  whole ends: no tooth move is better')
    # (`st`: the plan state it chose on, and whether it asked tooth moves -- asked none, its berths ARE the choice on
    # that board's teeth as laid, and fanout_from_plan need not ask again)
    choose.last = dict(laid=vL, laid_parts=pL, free=vF, free_parts=pF, moved=bool(out[1]))
    return out


def judge(st, choice):
    """(objective, parts) of berths `choice` {net: Move} against the teeth as laid -- a net `choice` leaves out at
    its greedy berth"""
    import source_realize as sr
    E = Ends(st, src_free=False, fixed={nm: sr.move_sig(m) for nm, m in choice.items()})
    return E.score(E.start(), exact=True)


def _fmt(p):
    return (f'{p["fan"] + p["route"]} vias predicted (fanout {p["fan"]}, route >= {p["route"]}: {p["parity"]} end-layer '
            f'changes + {p["crossover"]} crossover + 2 x {p["cover"]} + {p["settle"]} settling + {p["couple"]} coupled), '
            f'{p["over"]} over two on a net, '
            f'ride {p["ride"]} mm, congestion {p.get("cong", 0)}, ' + (f'feedback {p["feedback"]}, ' if p.get('feedback') else '') +
            f'{p["crossings"]} crossings ({p["same"]} on one layer)' + ''.join(f', {p[k]} {k}' for k in ('conflicts', 'splits', 'refused') if p[k])
            + (f' [the route exact on the orders: {p["route"]}, estimated {p["route_est"]}]'
               if p.get('route_est') is not None and p['route_est'] != p['route'] else ''))


if __name__ == '__main__':
    os.environ.setdefault('PLAN_JUDGE', 'ends')      # (read by fanout_from_plan at import: the menus the ends model takes)
    from kicad_parser import parse_kicad_pcb
    import fanout_from_plan as F
    board, nets = sys.argv[1], sys.argv[2]
    names = [x for x in (open(nets[1:]).read().split() if nets.startswith('@') else nets.split(',')) if x]
    st = F.plan_state(parse_kicad_pcb(board), names)
    dst, src = choose(st)
    print(f'  {len(src)} tooth move(s): {sorted(src)}')
