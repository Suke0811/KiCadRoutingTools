"""whole_solve.py OUT.json -- the WHOLE-ROUTE crossing and layer solve (CP-SAT), one permutation: the launch order
-> the berths' order round the destination's pad box (unrolled from a cut on its far face between the branches).
Each lane's route is ONE
coordinate u: trunk s from its entry (its tooth's projection) to the handoff, then its ring (u = handoff + s_b -
ring start) to its berth; a head lane's trunk s to its berth. Every inverted pair crosses once, at a u both share
(a pair in one branch may cross on the ring, up to the earlier leg); the braid triple rule over ALL triples;
each lane's crossings a pitch apart along its track (a stayer), or less for a sweep (a mover), and a pair's two
crossings of opposite ways its turning run and a pitch apart (no zigzag it cannot turn); up to KMAX changes per lane,
each a via's half-room from its own crossings and a via's room apart, a single's a change's room from both its ends
(END_ROOM) and a pair's its dive room; no crossing and no change in the band along the source's near face
(FACE_ROOM), where the teeth stand; neighbouring lanes' changes -- neighbours at either end, or two that cross --
staggered along the route so their vias clear; tooth layer at the start, berth layer at the end. Objective: the nets
over two vias first, then the vias, then HISTORY congestion (the crossings and changes in the places earlier rounds'
audits found the plan short, HIST).

The bench from BENCH / NETS / DEST (whole_ctx). HINT=SOLVE.json warm-starts from an earlier solve; CUTS=GEO.json,..
adds the geometry's cuts (whole_geo: the islands a lane could not be kept off, the changes it could not give their
room). HIST=HOT.json,.. prices the places earlier audits found short (whole_gate --hot). The solve is bounded in WORK,
not time: a count of CP-SAT's interleaved batches, its workers pinned and sharing no clauses, so the same model gives
the same answer on every run, later on a slower machine (WHOLE_SOLVE_BATCHES sets the budget). It stops sooner when
the vias are proved (the plan's vias no more than the bound's whole vias) or, once it has a plan, when it STALLS
(SOLVE_STALL of its own model reductions in a row with no better plan or bound: events of the search, never a clock). Only a plan PROVED optimal in its vias is written;
one the search could not prove is no plan."""
import sys, os, re, itertools, collections, json, math, hashlib
import detmath
if __name__ == '__main__':
    detmath.install()          # a chain stage: detmath's functions for the platform's, before the chain loads
import whole_ctx
import whole_frame
from ortools.sat.python import cp_model
import braid as bd
import pairs as _pairs
# every length below is in the design rules' own units: track, clearance, via size, a via's room, the lane pitch
TRK, CLR, VIA, VNEED, PITCH = bd.TRACK, bd.CLEAR, bd.VIA_SIZE, bd.VIA_NEED, bd.LANE_MIN
LEGROOM = PITCH                        # a peeling leg crosses, then still runs a pitch to its berth
VR_STAY = 1.1                          # a change's room from a stayer's crossing: its via is passed at an angle
KMAX = 3                               # layer changes per lane at most (every proved plan K15-K51 has 2 at most: a
                                       # fourth only widened the model -- K51 proved in 37 s at 3 with SUBSOLVERS)
G = PITCH / 5                          # the solve's time grid: a fifth of the lane pitch
MARG = CLR                             # a crossing starts a clearance past both lanes' terminals (a lane leaving its tooth may cross at once)
# a crossing's room along each lane: a STAYER's crossings a pitch apart, a MOVER's (a sweep crossing a bundle nearly
# across the spine, its slope up to K_SWEEP) PITCH / sqrt(1 + K^2) apart along s; the geometry keeps the real pitch
K_SWEEP = 4.0
W_V = 10 ** 6                          # per via: vias first (an integer: the objective stays CP-SAT's exact one)
SOLVE_BATCHES = int(os.environ.get('WHOLE_SOLVE_BATCHES', '100'))  # CP-SAT interleaved batches: the work budget
SOLVE_WORKERS = 4
# ...running these: two LP workers (the default and the strongest relaxation), core-based search and the objective's
# lower-bound search. The default four ran nothing that raises the bound, and a plan's vias are proved from below: K51's
# first solve stopped unproved at 421 s (best 56 vias, bound 40), with these it proves 42 in 141 s, K41 in 17 s (38)
SUBSOLVERS = ['default_lp', 'max_lp', 'core', 'objective_lb_search']
# ...and when they cannot prove it, the PLAN-FINDING workers the first four leave out, with core-based search to close
# the proof from their plan (the finders alone found K51-on-the-human's-fanout's plan and left its bound where it was)
FALLBACK = ['quick_restart', 'no_lp', 'core']
FACE_ROOM = 2 * VNEED                  # the band along the source's near face: a change's room along its lane
SOLVE_STALL = 3                        # the search's model reductions in a row with no progress: stalled


def solve(ctx, dest, cuts=(), hist=(), hint=None):
    """the solve of the bench ctx (whole_ctx.plan()) round the destination part `dest`: the JSON
    whole_geo reads (crossings, changes, each lane's route coordinate), or None when CP-SAT finds no plan or none it
    proves optimal in its vias. `cuts`
    names the geometry's cut files (whole_geo), `hist` the audits' hot files (whole_gate --hot), `hint` an earlier
    solve to warm-start from"""
    Fr = whole_frame.build(ctx, dest)          # the whole route's own frame (whole_frame.py)
    prs = getattr(ctx, 'pairs', {}) or {}
    M = list(Fr.M)
    F = lambda x: 1 if x == 'B.Cu' else 0
    tl = {n: F(ctx.tooth_layer[n]) for n in M}
    dl = {n: F(ctx.dest_layer[n]) for n in M}
    Dv = {n: 2 * VNEED + (_pairs.pitch(TRK) if n in prs else 0.0) for n in M}     # a change's room along its lane
    Q = lambda s: int(round(s / G))
    QU = lambda s: int(math.ceil(s / G - 1e-9))
    # ---- the whole route of each lane in u: its trunk s from its entry, and for a ring lane (bname: its class, the
    # face of the destination it berths on) past the arrival line H0 its ring's
    spine, bname, H0, ring_of, Hk = Fr.spine, Fr.cls, Fr.H0, Fr.rings, Fr.Hk
    Hn = {n: Hk[bname[n]] for n in bname}         # where each ring lane leaves the trunk: its ring's start
    # a ring's route coordinate starts where the geometry starts it: ahead of every class lane's handoff point, on a
    # geometry column (two solve steps) -- ONE origin for the solve and the layout
    GG = 2 * G
    rs = {}
    for k_, b_ in ring_of.items():
        sbs = [b_.project_pt(spine.xy(Hk[k_], Fr.o_h[n]))[0] for n in M if bname.get(n) == k_]
        rs[k_] = math.ceil(max(sbs) / GG - 1e-9) * GG
    entry = {n: Fr.st[n][0] for n in M}
    def u_ring(n, s_b):
        return Hn[n] + (s_b - rs[bname[n]])
    end = {}
    for n in M:
        if n in bname:
            end[n] = u_ring(n, ring_of[bname[n]].project_pt(Fr.land[n])[0])     # where it lands (whole_frame)
        else:
            end[n] = spine.project_pt(Fr.land[n])[0]     # its landing: its berth, or a trunk pair's across its face
    tend = {n: (Hn[n] if n in bname else end[n]) for n in M}      # where the lane leaves the TRUNK frame
    # a PAIR's end: no CROSSING inside its END CONNECTOR (pairs.end_connector: the legs from its tips to the pose where the
    # pair router takes over; SDQS1 once crossed SDQ15 and SDQ13 in the last 0.3 mm before their berths), and no CHANGE of
    # its own nearer than its DIVE ROOM (pairs.dive_room: that connector, then the router's straight from the pose into the
    # via). A crossing lane is on the other layer there; only the pair's own dive has to stand beyond its pose
    RIN0 = {n: (_pairs.end_connector(ctx.cfg, ctx.pair_ends[n][0]) if n in prs else 0.0) for n in M}   # at the tooth end
    RIN1 = {n: (_pairs.end_connector(ctx.cfg, ctx.pair_ends[n][1]) if n in prs else 0.0) for n in M}   # ... the berth end
    _axis = lambda u: u if u is not None else (1.0, 0.0)
    # ...and a SINGLE's change stands a change's room from its own tooth and berth (as two of its changes stand apart):
    # there its neighbours have not spread from the array's edge yet, on either layer, and a via planned 0.2 past a
    # tooth had no room beside it (K28: SDQ11 0.47 and SCKE1 0.59 past theirs, each moved by a via cut a round later).
    # Its crossings keep their own windows
    END_ROOM = 2 * VNEED
    VIN0 = {n: (_pairs.dive_room(ctx.cfg, ctx.pair_ends[n][0], _axis(ctx.tooth_dir.get(n))) if n in prs else END_ROOM)
            for n in M}
    VIN1 = {n: (_pairs.dive_room(ctx.cfg, ctx.pair_ends[n][1], _axis(ctx.stub_dir.get(n))) if n in prs else END_ROOM)
            for n in M}
    # ...a CROSSED pair's (pairs.opposite_hands: its legs swap once, at its first dive, a crossover) by the crossover's
    # own runs (pairs.crossover_room) -- its first change from its tooth, and at its berth where that change is its only
    # one; its other changes are plain dives, and its changes' cuts are the crossover's, the longer
    XO = {n for n in prs if n in M and _pairs.opposite_hands(ctx, n)}
    for n in XO:
        VIN0[n] = _pairs.crossover_room(ctx.cfg, ctx.pair_ends[n][0], _axis(ctx.tooth_dir.get(n)), 0)
        VIN1[n] = max(VIN1[n], _pairs.crossover_room(ctx.cfg, ctx.pair_ends[n][1], _axis(ctx.stub_dir.get(n)), 1))
    # a PAIR's KNOWN TURNS: the pair router neither turns at its via nor within its straight run of one, so its changes
    # stay out of every stretch of its route where the frames already turn (below, as built-in via cuts) -- and, where an
    # end's stub stands more than its connector's 45 degrees off the route's own way there, beyond the turn onto that way
    # as well. A turn is one the router must make: half a router step or more. The rest -- a lane's own sweep onto its
    # berth -- only the geometry knows, and it and the polish send those (whole_geo / whole_polish vcuts)
    TURN_DEG = 22.5
    L_DIVE = _pairs.via_straight(ctx.cfg, (math.sqrt(0.5), math.sqrt(0.5))) + ctx.cfg.grid_step   # the longer (diagonal) run
    _xs = _pairs.crossover_shape(ctx.cfg, (math.sqrt(0.5), math.sqrt(0.5)))
    L_XO = (max(_xs[1], _xs[2]) + ctx.cfg.grid_step) if _xs else L_DIVE                        # ... a crossover's
    LD = lambda n: L_XO if n in XO else L_DIVE


    def turn_room(deg):
        """half the stretch a pair's turn of `deg` takes: its 45-degree turns, a turning radius's straight run apart"""
        return _pairs.turn_straight_steps(ctx.cfg) * ctx.cfg.grid_step * max(0, math.ceil(abs(deg) / 45.0 - 1e-9) - 1) / 2


    def _deg(a, b):
        return math.degrees(math.acos(max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b))))))


    def route_dir(n, u):
        """the unit way lane n's route runs at u: its trunk's spine, or past the handoff its ring's"""
        if n in bname and u > Hn[n]:
            sp_ = ring_of[bname[n]]
            return tuple(sp_.d[sp_.seg_of(u - Hn[n] + rs[bname[n]])])
        return tuple(spine.d[spine.seg_of(u)])


    for n in prs:
        if n not in M:
            continue
        for k_, (u_e, esc, sg) in enumerate(((entry[n], ctx.tooth_dir.get(n), 1.0), (end[n], ctx.stub_dir.get(n), -1.0))):
            if esc is None:
                continue
            rd = route_dir(n, u_e)
            th = _deg((esc[0] * sg, esc[1] * sg), rd) - 45.0         # what the connector's 45 degrees leave to turn
            if th >= TURN_DEG:
                if k_ == 0:
                    VIN0[n] += 2 * turn_room(th) + LD(n)
                else:
                    VIN1[n] += 2 * turn_room(th) + LD(n)
    print('classes:', dict(collections.Counter(bname.get(n, 'W') for n in M)), 'W ends', sorted(round(end[n], 2) for n in M if n not in bname))
    Ln, Fn = list(Fr.launch), list(Fr.final)                  # both north to south (whole_frame)
    li = {n: i for i, n in enumerate(Ln)}; fi = {n: i for i, n in enumerate(Fn)}
    inv = lambda a, b: (li[a] < li[b]) == (fi[a] > fi[b])
    pairs = [(a, b) for a, b in itertools.combinations(Ln, 2) if inv(a, b)]
    same = lambda a, b: a in bname and b in bname and bname[a] == bname[b]
    # the FACE BAND: no crossing and no change within a change's room (FACE_ROOM) of the source's near face line --
    # lanes leaving its corner and its side faces (still running along them, beside its pad box) have not spread
    # there, and the geometry folded or squeezed what the solve put in it (K28: SCKE1's via beside the SCK pair at the
    # south-east corner; K35: SA9 and SCK short of their pitch along the south face). A side face's lanes run in the
    # band and cross beyond it
    S_FACE = float(spine.project_pt((Fr.SB[2], (Fr.SB[1] + Fr.SB[3]) / 2))[0])
    BAND = S_FACE + FACE_ROOM
    win = {}
    for a, b in pairs:
        lo = max(entry[a] + max(MARG, RIN0[a]), entry[b] + max(MARG, RIN0[b]), BAND)
        # a crossing on the ring leaves the earlier lane's leg LEGROOM to reach its berth after it
        hi = min(end[a] - max(LEGROOM, RIN1[a]), end[b] - max(LEGROOM, RIN1[b])) if same(a, b) else \
            min(tend[a] - (max(MARG, RIN1[a]) if a not in bname else MARG), tend[b] - (max(MARG, RIN1[b]) if b not in bname else MARG))
        win[(a, b)] = (lo, max(hi, lo + G))
    m = cp_model.CpModel()
    t = {k: m.NewIntVar(Q(lo), Q(hi), f't_{k[0]}_{k[1]}') for k, (lo, hi) in win.items()}
    # ---- geometry cuts (whole_geo.py's islands a lane could not be kept off): none of that lane's crossings in the span
    CUTS = []
    for fn_ in cuts:
        CUTS += json.load(open(fn_)).get('cuts', [])
    ncut = 0
    for cu_ in sorted({(c_['lane'], round(c_['u_lo'], 3), round(c_['u_hi'], 3)) for c_ in CUTS}):
        n_, lo_, hi_ = cu_
        for key in t:
            if n_ not in key:
                continue
            a_ = m.NewBoolVar('')
            m.Add(t[key] <= Q(lo_)).OnlyEnforceIf(a_); m.Add(t[key] >= Q(hi_) + 1).OnlyEnforceIf(a_.Not())
            ncut += 1
    if CUTS:
        print(f'   geometry cuts: {len(CUTS)} island spans, {ncut} crossing constraints')
    VCUTS = []
    for fn_ in cuts:
        VCUTS += json.load(open(fn_)).get('vcuts', [])
    # ...and a pair's built-in via cuts, at its route's known turns: its trunk's spine corners, its ring's (the pad box's
    # corners) and the handoff from the one onto the other
    NVC0 = len(VCUTS)
    for n in prs:
        if n not in M:
            continue
        turns = [(s_, d_) for _i, s_, d_ in spine.corners(TURN_DEG) if entry[n] < s_ < tend[n]]
        if n in bname:
            sp_ = ring_of[bname[n]]
            turns += [(u_, d_) for _i, sb_, d_ in sp_.corners(TURN_DEG) for u_ in [u_ring(n, sb_)] if Hn[n] < u_ < end[n]]
            dh = _deg(route_dir(n, Hn[n] - G), route_dir(n, Hn[n] + G))
            if dh >= TURN_DEG and entry[n] < Hn[n] < end[n]:
                turns.append((Hn[n], dh))
        VCUTS += [{'lane': n, 'u': u_, 'w': LD(n) + turn_room(d_)} for u_, d_ in turns]
    if len(VCUTS) > NVC0:
        print(f'   built-in via cuts at the pairs\' known turns: {len(VCUTS) - NVC0}')
    # ...and at the OTHER PARTS' PADS on the trunk and the TEETH of the nets outside the bus (whole_ctx.foreign_teeth:
    # their stubs' ends on the arrays' box lines): a lane whose reference (its taut path, whole_frame.ref) passes within
    # a via's reach of one -- its half size, a via's copper and clearance, a pair's barrel offset, and a lane pitch the
    # geometry may move it -- keeps its changes off that stretch (K35: SDQS0's dive planned beside C5's pad, 0.127 from
    # it where 0.242 was asked, and the geometry folded the pair round it). A PAIR's stretch is longer by its dive's
    # straight run (L_DIVE) either side: its lane bends round the item, and the pair router neither turns at its via
    # nor within that run of one (K41: SDQS0's dive planned 0.6 past its tooth, where its lane bent round SDQ4's tooth
    # beside it, turned 75 degrees at the via)
    NVC1 = len(VCUTS)
    off_ = {n: (_pairs.dive_offset(ctx.cfg, _pairs.pitch(TRK) / 2) if n in prs else 0.0) for n in M}
    items = [((pd_.global_x, pd_.global_y), max(pd_.size_x, pd_.size_y) / 2)
             for ref_, fp_ in ctx.pcb.footprints.items() if ref_ not in (Fr.src, Fr.dst) for pd_ in fp_.pads
             if pd_.pad_type != 'np_thru_hole' and any(L.endswith('.Cu') for L in pd_.layers)]
    items += [((x_, y_), r_) for (x_, y_, r_, _L, _nm) in whole_ctx.foreign_teeth(ctx, M, (Fr.SB, Fr.DB))]
    for (px_, py_), rp_ in items:
        sp_, op_ = (float(v_) for v_ in spine.project_pt((px_, py_)))
        for n in M:
            w_ = rp_ + VIA / 2 + CLR + (LD(n) if n in prs else 0.0)
            if not (entry[n] < sp_ + w_ and sp_ - w_ < tend[n]):       # the stretch reaches into the trunk's route
                continue
            if abs(whole_frame.ref(Fr, n, sp_) - op_) < rp_ + VIA / 2 + CLR + off_[n] + PITCH:
                VCUTS.append({'lane': n, 'u': sp_, 'w': w_})
    if len(VCUTS) > NVC1:
        print(f'   built-in via cuts at other parts\' pads and the teeth outside the bus: {len(VCUTS) - NVC1}')
    # ---- the braid rule over every triple
    nt = 0
    for i, j, k in itertools.combinations(Ln, 3):
        ij, ik, jk = (i, j) in t, (i, k) in t, (j, k) in t
        if ij and ik and jk:
            b1 = m.NewBoolVar('')
            m.Add(t[(i, j)] < t[(i, k)]).OnlyEnforceIf(b1); m.Add(t[(i, k)] < t[(j, k)]).OnlyEnforceIf(b1)
            m.Add(t[(j, k)] < t[(i, k)]).OnlyEnforceIf(b1.Not()); m.Add(t[(i, k)] < t[(i, j)]).OnlyEnforceIf(b1.Not())
            nt += 1
        elif ij and ik:
            m.Add(t[(i, j)] < t[(i, k)]); nt += 1
        elif ik and jk:
            m.Add(t[(j, k)] < t[(i, k)]); nt += 1
        elif ij and jk:
            raise SystemExit(f'inconsistent triple {i} {j} {k}')
    ev = collections.defaultdict(list)
    for key in t:
        for n in key: ev[n].append(key)
    P_STAY = PITCH                        # along a STAYER two crossings sit a pitch apart (its crossers are parallel there)
    MV = {}
    # (the mover / stayer model) every crossing has a MOVER (the steep lane, crossing over) and a STAYER; along a stayer
    # its crossings are P_STAY apart in s, along a mover PITCH / sqrt(1 + K_SWEEP^2) (a sweep): the mover chosen by the solve
    ivs_of = collections.defaultdict(list)
    w_move, w_stay = max(1, QU(PITCH / math.sqrt(1 + K_SWEEP * K_SWEEP))), max(1, QU(P_STAY))
    for key in t:
        a, b = key
        mv = m.NewBoolVar('')                           # True: a moves, b stays
        MV[key] = mv
        ivs_of[a].append(m.NewOptionalFixedSizeIntervalVar(t[key], w_move, mv, ''))
        ivs_of[a].append(m.NewOptionalFixedSizeIntervalVar(t[key], w_stay, mv.Not(), ''))
        ivs_of[b].append(m.NewOptionalFixedSizeIntervalVar(t[key], w_move, mv.Not(), ''))
        ivs_of[b].append(m.NewOptionalFixedSizeIntervalVar(t[key], w_stay, mv, ''))
    for n, ivs in ivs_of.items():
        m.AddNoOverlap(ivs)
    # a PAIR does not ZIGZAG: two of its crossings that pass lanes in OPPOSITE directions (one taking it north of a lane,
    # the other south of one) stand a pair's turn apart -- two 45-degree bends, each with its straight run, and its own
    # width -- or the geometry folds it between them (K35: SDQS0 run north on B to cross some lanes and back south to
    # cross others, a V in half a millimetre)
    zq = QU(2 * _pairs.turn_straight_steps(ctx.cfg) * ctx.cfg.grid_step + _pairs.pitch(TRK))
    for n in M:
        if n not in prs:
            continue
        ks = [k for k in t if n in k]
        way = {k: (1 if li[n] > li[k[1] if k[0] == n else k[0]] else -1) for k in ks}
        for k1, k2 in itertools.combinations(ks, 2):
            if way[k1] != way[k2]:
                zb = m.NewBoolVar('')
                m.Add(t[k1] + zq <= t[k2]).OnlyEnforceIf(zb); m.Add(t[k2] + zq <= t[k1]).OnlyEnforceIf(zb.Not())
    # ---- layer changes
    cost = []
    chg, tot = {}, {}
    for n in M:
        lo_n, hi_n = Q(max(entry[n] + VIN0[n], BAND)), Q(end[n] - VIN1[n])
        cs_ = [m.NewIntVar(lo_n, hi_n + 1, f'c_{n}_{k}') for k in range(KMAX)]
        act = [m.NewBoolVar('') for _ in range(KMAX)]
        for k in range(KMAX):
            m.Add(cs_[k] <= hi_n).OnlyEnforceIf(act[k]); m.Add(cs_[k] == hi_n + 1).OnlyEnforceIf(act[k].Not())
            if k:
                m.Add(cs_[k] >= cs_[k - 1] + Q(Dv[n])).OnlyEnforceIf(act[k]); m.AddImplication(act[k], act[k - 1])
        # a change's room from each of its lane's crossings, along s: a STAYER's via is passed by a steep mover at an
        # angle (VR_STAY x the room), a MOVER's via sits on its own steep track (the room itself) -- the room of both
        # lanes there, a PAIR crossing the via's lane the wider by its second leg: sized by the via's lane alone, SDQ13's
        # via stood 0.40 before SDQS1 swept across it, and the pair folded round it twice (K41)
        before = {}
        for key in ev[n]:
            wide = Dv[n] + (_pairs.pitch(TRK) if (key[1] if key[0] == n else key[0]) in prs else 0.0)
            h_st, h_mv = QU(VR_STAY * wide / 2), QU(wide / 2)               # a room rounds UP to the grid
            stay = MV[key].Not() if key[0] == n else MV[key]
            bits = []
            for k in range(KMAX):
                bb = m.NewBoolVar('')
                for h_, lit in ((h_st, stay), (h_mv, stay.Not())):
                    m.Add(cs_[k] + h_ <= t[key]).OnlyEnforceIf([bb, lit])
                    m.Add(cs_[k] - h_ >= t[key]).OnlyEnforceIf([bb.Not(), act[k], lit])
                m.AddImplication(bb, act[k]); bits.append(bb)
            before[key] = bits
        m.AddBoolXOr(act + ([m.NewConstant(1)] if tl[n] == dl[n] else []))
        tot[n] = sum(act); chg[n] = (cs_, act)
        ev[n] = before
    # an OPPOSITE-HANDS pair (pairs.opposite_hands) swaps its legs at a dive, a crossover: it changes layer at least once.
    # Where its tooth and berth are on different layers the berth rule's parity already asks an odd number; only where they
    # share one could it plan none (and be laid uncrossed) -- the rule is added there alone, since an added constraint that
    # binds nothing still moves the solver to another of its equal optima
    for n in M:
        if n in prs and tl[n] == dl[n] and _pairs.opposite_hands(ctx, n):
            m.Add(chg[n][1][0] == 1)
    # two lanes' changes apart along one frame far enough that two on NEIGHBOURING lanes -- a lane pitch across -- clear
    # the via-to-via rule as the geometry plans it (a grid step over it): a via apart along left them 0.36 where the rule
    # is 0.38, for the geometry to spread. Only lanes that can BE neighbours: adjacent at the launch or at the berths,
    # or crossing each other (adjacent where they cross). Vias on lanes far apart across a frame stand side by side,
    # as the human's do; held single file along the whole frame, K35's trunk (6.5 mm between the arrays, a change
    # every 0.28) could not hold its changes. The geometry keeps the real via-to-via rule between every two vias, and
    # sends back a via cut where it cannot
    from fab_tiers import min_via_center_distance
    _VV = min_via_center_distance(VIA, CLR, ctx.cfg.via_drill, getattr(ctx.cfg, 'hole_to_hole_clearance', 0.0) or 0.0) \
        + ctx.cfg.grid_step
    STAGGER = max(VIA, math.sqrt(max(_VV * _VV - PITCH * PITCH, 0.0)))
    fr_ivs = collections.defaultdict(lambda: collections.defaultdict(list))      # frame -> lane -> its changes there
    w_s = max(1, Q(STAGGER))
    for n in M:
        cs_, act = chg[n]
        for x, a_ in zip(cs_, act):
            if n in bname:
                # its frame is the trunk before the handoff, its ring after
                inT, inR = m.NewBoolVar(''), m.NewBoolVar('')
                m.Add(x <= Q(Hn[n])).OnlyEnforceIf(inT); m.Add(x > Q(Hn[n])).OnlyEnforceIf(inR)
                m.AddBoolOr([inT.Not(), a_]); m.AddBoolOr([inR.Not(), a_])
                m.Add(inT + inR == 1).OnlyEnforceIf(a_); m.Add(inT + inR == 0).OnlyEnforceIf(a_.Not())
                fr_ivs['T'][n].append(m.NewOptionalFixedSizeIntervalVar(x, w_s, inT, ''))
                fr_ivs[bname[n]][n].append(m.NewOptionalFixedSizeIntervalVar(x, w_s, inR, ''))
            else:
                fr_ivs['T'][n].append(m.NewOptionalFixedSizeIntervalVar(x, w_s, a_, ''))
    nbr = {frozenset(p_) for p_ in zip(Ln, Ln[1:])} | {frozenset(p_) for p_ in zip(Fn, Fn[1:])} | \
        {frozenset(k) for k in t}
    for f_, by_lane in fr_ivs.items():
        for p_ in sorted(nbr, key=lambda p_: sorted(p_)):
            a_, b_ = sorted(p_)
            if by_lane.get(a_) and by_lane.get(b_):
                m.AddNoOverlap(by_lane[a_] + by_lane[b_])
    for key in t:
        a, b = key
        # crossing lanes DIFFER: tl_a ^ tl_b ^ Ca ^ Cb == 1, i.e. XOR(parity bits [+ 1 when the teeth differ]) == 1
        lits = ev[a][key] + ev[b][key]
        if tl[a] ^ tl[b] == 1: lits = lits + [m.NewConstant(1)]
        m.AddBoolXOr(lits)
    # ---- via cuts (whole_geo.py: a change the geometry could not give its room): that lane's changes stay out of the window
    for vc_ in sorted({(c_['lane'], round(c_['u'], 3), round(c_['w'], 3)) for c_ in VCUTS}):
        n_, u_, w_ = vc_
        if n_ not in chg:
            continue
        cs_v, act_v = chg[n_]
        for x_, a_ in zip(cs_v, act_v):
            lo_b, hi_b = m.NewBoolVar(''), m.NewBoolVar('')
            m.Add(x_ <= Q(u_ - w_)).OnlyEnforceIf(lo_b); m.Add(x_ >= Q(u_ + w_)).OnlyEnforceIf(hi_b)
            m.AddBoolOr([lo_b, hi_b, a_.Not()])
    if VCUTS:
        print(f'   via cuts: {len(VCUTS)}')
    # ---- HISTORY congestion (negotiated, as PathFinder prices a resource that was overused before): HIST=HOT.json,.. are
    # the audits' findings of earlier rounds (whole_gate --hot: where a plan was short -- a dive, a pitch, a static, a
    # shape), one file per audit. A finding marks the bins of route within a via's room of it, on the frame whose spine is
    # nearest; a bin's price is the number of audits it was hot in. Only those bins carry terms: a crossing in one pays a
    # crossing's copper area (a pitch across, a pitch along), a change a via's patch (a pair's two) -- after the vias and
    # the nets over two, so it moves crossings and changes out of the places the plan could not fit, never adds a via
    LB = 2 * PITCH                         # a history bin: two lane pitches of route
    R_HOT = 2 * VNEED                      # a finding marks the bins within a via's room of it
    SC = 1000.0                            # objective units per mm^2 of copper area
    A_V, A_X = 2 * (2 * VNEED) * (2 * VNEED), PITCH * PITCH
    # a frame's bins from its own origin: the trunk's from H0, a ring's from where it leaves the trunk (Hk)
    origin = lambda fr: H0 if fr == 'T' else Hk[fr]
    kof = lambda fr, u: int(math.floor((u - origin(fr)) / LB + 1e-9))
    HOT = collections.Counter()
    HFILES = list(hist)
    for fn_ in HFILES:
        marked = set()
        for x_, y_, *_k in json.load(open(fn_)).get('hot', []):
            # the frame whose spine the finding stands nearest -- a ring's only past where its lanes leave the trunk (a
            # ring's spine runs back along the trunk before that, and a finding at the source's face, nearer it than the
            # trunk's, was priced on the ring before any of its lanes is on it: nothing, K41's SDQS0 dive)
            fr_u = [('T',) + tuple(spine.project_pt((x_, y_)))]
            fr_u += [e_ for k_ in ring_of for e_ in [(lambda so: (k_, Hk[k_] + so[0] - rs[k_], so[1]))(
                ring_of[k_].project_pt((x_, y_)))] if e_[1] >= Hk[k_]]
            fr, u, _o = min(fr_u, key=lambda e_: abs(e_[2]))
            marked |= {(fr, k) for k in range(kof(fr, u - R_HOT), kof(fr, u + R_HOT) + 1)}
        HOT.update(marked)


    def in_bin(v_, u0, u1, lit=None):
        """a bool that is 1 whenever v_ lies in [u0, u1) (and lit holds): it carries a positive price, so it is 1 only then"""
        x_, lo_b, hi_b = m.NewBoolVar(''), m.NewBoolVar(''), m.NewBoolVar('')
        m.Add(v_ >= Q(u0)).OnlyEnforceIf(lo_b); m.Add(v_ < Q(u0)).OnlyEnforceIf(lo_b.Not())
        m.Add(v_ < Q(u1)).OnlyEnforceIf(hi_b); m.Add(v_ >= Q(u1)).OnlyEnforceIf(hi_b.Not())
        m.AddBoolOr([lo_b.Not(), hi_b.Not(), x_] + ([lit.Not()] if lit is not None else []))
        return x_


    def in_frame(fr, n, u0, u1):
        """the part of frame fr's bin [u0, u1) where lane n's route is in that frame -- a ring lane's is its ring's past
        where it leaves the trunk (Hn), the trunk's before it -- or None"""
        if fr == 'T':
            lo_, hi_ = u0, (min(u1, Hn[n]) if n in bname else u1)
        elif bname.get(n) == fr:
            lo_, hi_ = max(u0, Hn[n]), u1
        else:
            return None
        return (lo_, hi_) if lo_ < hi_ else None

    nh_x = nh_v = 0
    for (fr, k), h_ in sorted(HOT.items(), key=lambda e_: (str(e_[0][0]), e_[0][1])):
        u0, u1 = origin(fr) + k * LB, origin(fr) + (k + 1) * LB
        for key, (lo, hi) in win.items():
            a, b = key
            # (a crossing is on a ring only between two lanes of that ring)
            sp_ = in_frame(fr, a, u0, u1) if same(a, b) else ((u0, u1) if fr == 'T' else None)
            if sp_ is None or hi < sp_[0] or lo >= sp_[1]:
                continue
            cost.append(int(round(SC * A_X * h_)) * in_bin(t[key], *sp_)); nh_x += 1
        for n in M:
            sp_ = in_frame(fr, n, u0, u1)
            if sp_ is None or end[n] < sp_[0] or entry[n] >= sp_[1]:
                continue
            cs_, act = chg[n]
            for cv_, a_ in zip(cs_, act):
                cost.append(int(round(SC * A_V * (2 if n in prs else 1) * h_)) * in_bin(cv_, *sp_, a_)); nh_v += 1
    if HFILES:
        print(f'   history: {len(HFILES)} audit(s), {len(HOT)} hot bin(s) (hottest {max(HOT.values(), default=0)}), '
              f'{nh_x} crossing and {nh_v} change terms')
    if hint:
        Hj = json.load(open(hint))
        nh = 0
        for k_, v_ in Hj['cross'].items():
            a_, b_ = k_.split('|')
            key_ = (a_, b_) if (a_, b_) in t else (b_, a_)
            if key_ in t:
                m.AddHint(t[key_], int(round(v_['u'] / G))); nh += 1
        for n_, chs_ in Hj['changes'].items():
            cs_h, act_h = chg[n_]
            for i_ in range(KMAX):
                if i_ < len(chs_):
                    m.AddHint(cs_h[i_], int(round(chs_[i_] / G))); m.AddHint(act_h[i_], 1)
                else:
                    m.AddHint(act_h[i_], 0)
        print(f'   warm start from {os.path.basename(hint)}: {nh} crossing hints')
    # ---- no more than TWO VIAS on a net where that can be had (Andy, 2026-09-25): a net's vias on the board are its stubs'
    # own (the bench's copper) and its lane's changes -- a pair's leg a barrel at each dive. The objective is
    # lexicographic: first how far the nets go over two, then the vias, then congestion -- a preference, never a cap, so a
    # board that cannot keep it still plans
    VIA_PREF = 2
    SV = {n: max(sum(1 for v in ctx.base_vias if v.net_id == ctx.byname[leg][0]) for leg in (prs[n] if n in prs else (n,)))
          for n in M}
    over = {n: m.NewIntVar(0, KMAX + SV[n], f'over_{n}') for n in M}
    for n in M:
        m.Add(over[n] >= SV[n] + tot[n] - VIA_PREF)
    W_OVER = W_V * (KMAX * len(M) + 1)        # one via over two outweighs every via the plan could save
    # ---- the ROOT's proof, a floor for every re-solve of the bench: the first solve (no geometry cuts) proved the least
    # nets over two and vias there are; a re-solve only adds cuts to it (a flip drops only an island cut a re-solve
    # added) and history below a via, so it can do no better -- and a plan it finds AT the root's is proved at once. A
    # re-solve left short of that proof ran out its budget on the proof alone (K51: best 1 over two and 42 vias, the
    # root's own, bound 36, 193 s unproved, and the loop stopped). The root is carried in each solve's JSON and read from
    # the warm start's, and taken only for the same model: its lanes, their orders, end layers, stub vias, KMAX and the
    # built-in cuts (the bench's own), by a signature
    sig = hashlib.sha1(json.dumps([sorted(M), list(Ln), list(Fn), [(n, tl[n], dl[n], SV[n]) for n in sorted(M)], KMAX,
                                   VIA_PREF, [(c_['lane'], round(c_['u'], 4), round(c_['w'], 4)) for c_ in VCUTS[NVC0:]]],
                                  sort_keys=True).encode()).hexdigest()
    root = None
    if hint:
        r_ = json.load(open(hint)).get('root')
        if r_ and r_.get('sig') == sig:
            root = r_
            m.Add(W_OVER * sum(over.values()) + W_V * sum(tot.values()) >= W_OVER * r_['over'] + W_V * r_['vias'])
            print(f"   the root's proof as a floor: {r_['over']} via(s) over two, {r_['vias']} vias")
    OBJ = W_OVER * sum(over.values()) + W_V * sum(tot.values()) + sum(cost)
    m.Minimize(OBJ)
    # ...and STOPPED when it STALLS: once it has a plan, SOLVE_STALL of the search's own model reductions in a row with
    # no better plan and no better bound (its log's '#Model' against '#n' and '#Bound' lines, events of the
    # deterministic search, never a clock). K35: its one plan at 46 s, then 145 s with neither -- the budget spent on
    # nothing. Before its first plan the budget decides: K41's re-solve, stopped at 31 s with none, proved a plan of
    # 33 vias by 255 s. And DONE once the vias
    # are PROVED, read off the same lines (best, and the bound below it): the plan's vias no more than the bound's
    # whole vias -- the nets over two and the vias settled, only the history's tie-break open (K35's re-solve: 167 s,
    # most of it on the tie-break). (A gap limit of a via would stop short of that proof: a plan of 24 vias against a
    # bound of 23 and half a via's history is within one via, and a 23-via plan may still exist.)
    def run(subs):
        s_ = cp_model.CpSolver()
        s_.parameters.num_workers = SOLVE_WORKERS
        s_.parameters.subsolvers.extend(subs)
        # REPRODUCIBLE: stopped by a count of interleaved batches, the workers sharing no clauses. Measured on this
        # model (OR-tools 9.15): bounded by deterministic time, four solves of one model gave four answers (36051281 ..
        # 36051642); by batches with clause sharing on, two gave two; by batches with sharing off, two concurrent
        # solves agree exactly
        s_.parameters.interleave_search = True
        s_.parameters.max_num_deterministic_batches = SOLVE_BATCHES
        s_.parameters.share_glue_clauses = False
        s_.parameters.share_binary_clauses = False
        stall = {'n': 0, 'plan': False}

        def _progress(line):
            if line.startswith('#Bound') or re.match(r'#\d+\s', line):
                stall['n'] = 0
                stall['plan'] = stall['plan'] or not line.startswith('#Bound')
                m_ = re.search(r'best:(\S+)\s+next:\[([^,\]]+)', line)
                if m_ and float(m_.group(1)) < math.inf and \
                        math.floor(float(m_.group(1)) / W_V) <= math.floor(float(m_.group(2)) / W_V):
                    s_.StopSearch()
            elif line.startswith('#Model') and stall['plan']:
                stall['n'] += 1
                if stall['n'] >= SOLVE_STALL:
                    s_.StopSearch()
        s_.parameters.log_search_progress = True
        s_.parameters.log_to_stdout = False
        s_.log_callback = _progress
        st_ = s_.Solve(m)
        pr_ = st_ in (cp_model.OPTIMAL, cp_model.FEASIBLE) and \
            math.floor(s_.ObjectiveValue() / W_V) <= math.floor(s_.BestObjectiveBound() / W_V)
        return s_, st_, pr_
    sv, st, proved = run(SUBSOLVERS)
    if not proved:
        # the FALLBACK: the bound-raising workers could not prove it (the plan they found was not good enough to meet
        # their bound: K51 on the human's fanout, best 2 over two + 38 vias against 0 + 32, 124 s). The PLAN-FINDING
        # workers run on from there -- its best plan as their start, and its bound, proved on this very model, a
        # constraint (no worker proves it again)
        print(f'   bound-raising workers: [{sv.StatusName(st)}] {sv.WallTime():.0f}s' +
              (f', best {sv.ObjectiveValue():.0f}' if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else ', no plan') +
              f', bound {sv.BestObjectiveBound():.0f} -- the plan-finding workers on from there')
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            m.ClearHints()
            for i_ in range(len(m.Proto().variables)):
                v_ = m.GetIntVarFromProtoIndex(i_)
                m.AddHint(v_, sv.Value(v_))
        m.Add(OBJ >= int(math.ceil(sv.BestObjectiveBound() - 1e-6)))
        t_first = sv.WallTime()
        sv, st, proved = run(FALLBACK)
        print(f'   plan-finding workers: [{sv.StatusName(st)}] {sv.WallTime():.0f}s (after {t_first:.0f}s)')
    print(f'whole_solve: {len(t)} crossings ({sum(1 for k in t if same(*k))} same-branch), {nt} triples, K<={KMAX}, '
          f'mover/stayer (stay {P_STAY}), stagger {STAGGER:.3f}, MARG {MARG}: [{sv.StatusName(st)}] {sv.WallTime():.0f}s', end=' ')
    # only a plan PROVED optimal in its vias -- the nets over two and the vias, whole multiples of W_V; the history
    # terms below one are congestion's tie-break -- goes on to the geometry: one the search could not prove is a plan
    # whose ends it found hard, and the geometry would be laid on a guess (K35's round 2: best and bound a thousandth
    # of a via apart, refused for the tie-break alone)
    if not proved:
        print(('(not proved optimal: best ' + f'{sv.ObjectiveValue():.0f}, bound {sv.BestObjectiveBound():.0f} -- no plan)')
              if st == cp_model.FEASIBLE else '')
        return None
    per = {n: int(sv.Value(tot[n])) for n in M}
    ov = [n for n in M if SV[n] + per[n] > VIA_PREF]
    print(f'vias {sum(per.values())}, nets over {VIA_PREF} vias on the board: {len(ov)} {ov}, changes per lane {dict(sorted(collections.Counter(per.values()).items()))}, obj {sv.ObjectiveValue():.0f} bound {sv.BestObjectiveBound():.0f}')
    # verify: every crossing on two layers, every lane on its berth layer
    lay = lambda n, u: tl[n] ^ (sum(1 for x, a_ in zip(*chg[n]) if sv.Value(a_) and sv.Value(x) * G < u) & 1)
    bad = [(a, b) for (a, b), v in t.items() if lay(a, sv.Value(v) * G) == lay(b, sv.Value(v) * G)]
    badb = [n for n in M if lay(n, 1e9) != dl[n]]
    print(f'   check: crossings on one layer {len(bad)}, lanes off their berth layer {len(badb)}')
    J = {'H0': H0, 'Hk': Hk, 'rs': rs, 'cross': {}, 'changes': {}, 'entry': entry, 'end': end, 'tend': tend, 'branch': bname,
         'final': Fn, 'launch': Ln}
    for (a, b), v in t.items():
        J['cross'][f'{a}|{b}'] = {'u': sv.Value(v) * G, 'ring': same(a, b) and sv.Value(v) * G > Hn[a] + 1e-9}
    for n in M:
        cs_, act = chg[n]
        J['changes'][n] = [sv.Value(x) * G for x, a_ in zip(cs_, act) if sv.Value(a_)]
    # (the root: this solve's own proof when it has no geometry cuts, else the one it was floored by)
    J['root'] = root if root is not None else \
        ({'over': int(sum(sv.Value(over[n]) for n in M)), 'vias': int(sum(per.values())), 'sig': sig}
         if not CUTS and NVC0 == 0 else None)
    return J


def main():
    files = lambda var: [x for x in os.environ.get(var, '').split(',') if x]
    out = sys.argv[1] if len(sys.argv) > 1 else '/dev/null'
    ctx, _cs = whole_ctx.plan()
    J = solve(ctx, os.environ['DEST'], files('CUTS'), files('HIST'), os.environ.get('HINT') or None)
    if J is None:
        sys.exit(1)
    json.dump(J, open(out, 'w'), indent=0)


if __name__ == '__main__':
    main()
