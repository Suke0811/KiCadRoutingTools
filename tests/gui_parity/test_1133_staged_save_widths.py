#!/usr/bin/env python3
"""#1133: the GUI oracle leg on a real pcbnew save -- the width a run gives
one named net reaches THAT net on the staged board, and the copper the oracle
lays comes back onto the right live net.

`gui_utils.run_kicad_oracle_on_live_board` temp-saves the live board with
`pcbnew.SaveBoard` and the oracle re-parses that save. KiCad 10 writes the
nets by NAME and the parser numbers them by first appearance, so on a board
that carried a numbered net table the ids move: flat_hierarchy's
`/pic_programmer/PC-CLOCK-OUT` is netcode 8 in pcbnew and 81 in the save.
The engine run's payload used to be keyed by pcbnew netcodes, and the GUI
applied the oracle's copper with `SetNetCode(<the save's id>)`.

The recipe the issue gives, through the REAL consumer:

  1. load a temp copy of flat_hierarchy with pcbnew and pick a net whose
     netcode means ANOTHER net in the staged save (the negative control: an
     id-keyed payload would land on that other net -- asserted, so the
     fixture cannot go vacuous);
  2. give that net a distinctive power width in the by-name payload
     (`kicad_oracle.oracle_net_widths_by_name` of a config keyed by the
     live netcodes, i.e. what route.py posts);
  3. run `run_kicad_oracle_on_live_board`, with KiCad's link source stubbed
     to one link on that net, the routers stubbed to fail and the sliver weld
     stubbed to lay a track (the copper is not what is graded here);
  4. assert the oracle's width lookup on the staged board returns the width
     for that net and for no other, and that the track it laid is on that
     net on the LIVE board.

Needs pcbnew; re-execs into KiCad's python automatically. Does not
self-skip: a gate that exits 0 without running reports what it guards as
checked.

    python3 tests/gui_parity/test_1133_staged_save_widths.py
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'py_router'))
sys.path.insert(0, os.path.join(REPO, 'py_tools'))

from kicad_locate import path_version_key  # noqa: E402
KICAD_PYTHONS = [
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/"
    "Versions/Current/bin/python3",
    "/usr/bin/python3",
    os.path.expandvars(r"C:\Program Files\KiCad\bin\python.exe"),
    *sorted(glob.glob(r"C:\Program Files\KiCad\*\bin\python.exe"),
            key=path_version_key, reverse=True),
]

BOARD = os.path.join(REPO, 'kicad_files', 'flat_hierarchy.kicad_pcb')
PREFERRED = '/pic_programmer/PC-CLOCK-OUT'
WIDTH = 0.77          # distinctive: no class or default width is this
TRACK = 0.2


def _reexec_into_kicad():
    for cand in KICAD_PYTHONS:
        if cand == sys.executable or not os.path.exists(cand):
            continue
        r = subprocess.run([cand, '-c', 'import pcbnew'], capture_output=True)
        if r.returncode == 0:
            # os.execv re-splits argv on spaces on Windows ("Program Files").
            sys.exit(subprocess.run([cand, os.path.abspath(__file__)]
                                    + sys.argv[1:]).returncode)
    print("ERROR: no python with pcbnew found; this gate does not self-skip")
    sys.exit(2)


def run():
    import pcbnew
    from copy_board import copy_board
    from kicad_parser import parse_kicad_pcb, build_pcb_data_from_board
    from routing_config import GridRouteConfig
    import kicad_oracle
    import kicad_exact_fill
    import plane_region_connector
    import net_rescue
    from kicad_parser import Segment
    from kicad_routing_plugin.gui_utils import run_kicad_oracle_on_live_board

    fails = []

    def check(cond, msg):
        print(f"  {'PASS' if cond else 'FAIL'}: {msg}")
        if not cond:
            fails.append(msg)

    if kicad_oracle.find_kicad_cli(warn=False) is None:
        print("ERROR: kicad-cli not found; run_kicad_oracle_on_live_board "
              "skips without it, so this gate cannot run")
        return False

    work = tempfile.mkdtemp(prefix='t1133_')
    try:
        src = os.path.join(work, 'flat_hierarchy.kicad_pcb')
        copy_board(BOARD, src)
        board = pcbnew.LoadBoard(src)
        live = {str(nm): ni.GetNetCode()
                for nm, ni in board.GetNetInfo().NetsByName().items()
                if str(nm)}

        # The staged save's numbering, the way the consumer will see it.
        probe = os.path.join(work, 'probe.kicad_pcb')
        pcbnew.SaveBoard(probe, board, aSkipSettings=True)
        staged = {n.name: nid for nid, n in parse_kicad_pcb(probe).nets.items()
                  if n.name}
        staged_by_id = {v: k for k, v in staged.items()}
        moved = sorted(n for n in live if n in staged and live[n] != staged[n]
                       and live[n] in staged_by_id)
        check(len(moved) > 10,
              f"fixture: {len(moved)} of {len(live)} nets get an id in the "
              f"staged save that names ANOTHER net")
        if not moved:
            return False
        name = PREFERRED if PREFERRED in moved else moved[0]
        other = staged_by_id[live[name]]
        print(f"  net {name}: pcbnew {live[name]} -> staged {staged[name]}; "
              f"an id-keyed map would land on {other!r}")
        check(other != name, "negative control: the live netcode names "
                             "another net in the staged save")

        # What route.py posts: the run's config is keyed by the LIVE ids
        # (build_pcb_data_from_board), the payload is by name.
        run_pcb = build_pcb_data_from_board(board)
        run_cfg = GridRouteConfig(clearance=0.2, track_width=TRACK)
        run_cfg.power_net_widths = {live[name]: WIDTH}
        payload = kicad_oracle.oracle_net_widths_by_name(run_cfg,
                                                         run_pcb.nets)
        check(payload == {'power_net_widths': {name: WIDTH}},
              f"payload by name: {payload}")

        bb = run_pcb.board_info.board_bounds
        x0 = (bb[0] + bb[2]) / 2.0
        y0 = (bb[1] + bb[3]) / 2.0
        seen, welds = [], []
        calls = {'n': 0}

        def fake_exact(board_file, net_names=None, pcb_data=None,
                       verbose=False, project_from=None):
            calls['n'] += 1
            if calls['n'] > 1:
                return []
            return [(name, (x0, y0, 'F.Cu', 'track'),
                     (x0 + 0.5, y0, 'F.Cu', 'track'))]

        def fake_bbo(*a, **k):
            seen.append(k.get('config'))
            return object(), None

        def fake_weld(pcb_data, net_id, ax, ay, bx, by, layer, config,
                      islands_map=None, net_name=None):
            welds.append((net_id, net_name))
            return Segment(start_x=ax, start_y=ay, end_x=bx, end_y=by,
                           width=config.track_width, layer=layer,
                           net_id=net_id)

        saved = (kicad_exact_fill.exact_unconnected,
                 kicad_oracle.kicad_unconnected,
                 kicad_exact_fill.refill_islands,
                 plane_region_connector.build_base_obstacles,
                 plane_region_connector.route_plane_connection_wide,
                 net_rescue._attempt_edge, kicad_oracle._direct_sliver_weld)
        kicad_exact_fill.exact_unconnected = fake_exact
        kicad_oracle.kicad_unconnected = lambda *a, **k: None
        kicad_exact_fill.refill_islands = lambda *a, **k: None
        plane_region_connector.build_base_obstacles = fake_bbo
        plane_region_connector.route_plane_connection_wide = \
            lambda *a, **k: (None, 0)
        net_rescue._attempt_edge = lambda *a, **k: (None, None)
        kicad_oracle._direct_sliver_weld = fake_weld
        def _at_link(t):
            return (t.GetClass() == 'PCB_TRACK'
                    and abs(pcbnew.ToMM(t.GetStart().x) - x0) < 1e-3
                    and abs(pcbnew.ToMM(t.GetStart().y) - y0) < 1e-3)
        check(not [t for t in board.GetTracks() if _at_link(t)],
              "fixture: no track starts at the stubbed link before the run")
        try:
            orc = run_kicad_oracle_on_live_board(
                board, [name], clearance=0.2, track_width=TRACK,
                via_size=0.6, via_drill=0.3, grid_step=0.1,
                layers=['F.Cu', 'B.Cu'], net_widths_by_name=payload)
        finally:
            (kicad_exact_fill.exact_unconnected,
             kicad_oracle.kicad_unconnected, kicad_exact_fill.refill_islands,
             plane_region_connector.build_base_obstacles,
             plane_region_connector.route_plane_connection_wide,
             net_rescue._attempt_edge,
             kicad_oracle._direct_sliver_weld) = saved

        check(orc is not None and orc.get('available'),
              f"the GUI oracle ran ({None if orc is None else orc.get('why')})")
        check(bool(seen), "the oracle built its link's obstacle map")
        if seen:
            cfg = seen[0]
            hits = sorted(n for n, sid in staged.items()
                          if abs(cfg.get_net_track_width(sid, 'F.Cu')
                                 - WIDTH) < 1e-9)
            check(hits == [name],
                  f"the width lookup on the staged board returns {WIDTH} "
                  f"for {name} and no other net (got {hits})")
            check(abs(cfg.get_net_track_width(staged[other], 'F.Cu')
                      - TRACK) < 1e-9,
                  f"{other!r} (staged id {staged[other]}, the old channel's "
                  f"landing site) keeps the default width")
        check(welds and welds[0][1] == name,
              f"the weld was laid for {name}: {welds}")
        new = [t for t in board.GetTracks() if _at_link(t)]
        nets = [t.GetNetname() for t in new]
        check(nets == [name],
              f"the oracle's track landed on the live board's {name} "
              f"(got {nets})")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if fails:
        print(f"\n{len(fails)} check(s) FAILED")
        return False
    print("PASS  #1133 staged-save widths and the oracle's copper follow "
          "the net NAME")
    return True


if __name__ == '__main__':
    try:
        import pcbnew  # noqa: F401
    except ImportError:
        _reexec_into_kicad()
    sys.exit(0 if run() else 1)
