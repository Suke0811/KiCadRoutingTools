#!/usr/bin/env python3
"""#1136: copper admit/refuse checks against another net's copper.

`stub_clear_of_foreign_pads` sized every stub at `config.track_width`, not
at the stub segment's own width (its sibling `stub_clear_of_foreign_tracks`
reads `seg.width`). A stub narrower than the default track was refused
where it fits, and a wider one admitted where it grazes.

Each case states the verdict the fixed code must give; every one of them
fails on the unfixed code.

    python3 tests/test_1136_admission_pairwise.py [test-substring ...]
"""
import os
import sys
import traceback

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, TESTS_DIR)

from kicad_parser import BoardInfo, Net                   # noqa: E402
from routing_config import GridRouteConfig                # noqa: E402
from synth import make_pad, make_seg, make_pcb            # noqa: E402

OWN, FOREIGN = 1, 99
BI = BoardInfo(layers={}, board_bounds=None, copper_layers=['F.Cu', 'B.Cu'])

#: (test, case label, passed)
RESULTS = []


def check(label, got, want):
    RESULTS.append((_CURRENT[0], label, got == want))
    mark = 'PASS' if got == want else 'FAIL'
    print(f"  {mark}: {label}: got {got!r}, want {want!r}")


_CURRENT = ['']


def cfg(**kw):
    c = GridRouteConfig(clearance=0.2, track_width=0.2, via_size=0.6,
                        via_drill=0.3, layers=['F.Cu', 'B.Cu'], grid_step=0.05)
    c.hole_to_hole_clearance = 0.2
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def pcb(segs=(), pads=()):
    by_net = {}
    for p in pads:
        by_net.setdefault(p.net_id, []).append(p)
    return make_pcb(segments=list(segs), pads_by_net=by_net, board_info=BI,
                    nets={OWN: Net(OWN, '/OWN'), FOREIGN: Net(FOREIGN, '/F')})


# ---- the stub's own width (not the pairwise class) ---------------------------

def test_stub_pad_check_reads_the_stub_width():
    """A 0.5 mm pad whose edge is `gap` from the stub centreline, flat 0.2
    clearance: the requirement is the stub's half width + 0.2."""
    import stub_layer_switching as sls

    def admitted(width, gap):
        board = pcb(pads=[make_pad(FOREIGN, 0.0, gap + 0.25)])
        stub = [make_seg(-1, 0, 1, 0, net_id=OWN, width=width)]
        return sls.stub_clear_of_foreign_pads(stub, 'F.Cu', OWN, board,
                                              cfg(), set())[0]
    check('0.1 mm stub, pad edge 0.27 (needs 0.25): admitted',
          admitted(0.1, 0.27), True)
    check('0.3 mm stub, pad edge 0.32 (needs 0.35): refused',
          admitted(0.3, 0.32), False)


TESTS = [test_stub_pad_check_reads_the_stub_width]


def main(argv):
    only = argv[1:]
    ran = 0
    for t in TESTS:
        if only and not any(o in t.__name__ for o in only):
            continue
        _CURRENT[0] = t.__name__
        print(f"--- {t.__name__}")
        ran += 1
        try:
            t()
        except Exception:                                  # noqa: BLE001
            traceback.print_exc()
            RESULTS.append((t.__name__, 'raised', False))
    if only and not ran:
        print(f"NO TEST matches {only}")
        return 2
    failed = [r for r in RESULTS if not r[2]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} cases pass")
    for t, label, _ in failed:
        print(f"  FAILED {t}: {label}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
