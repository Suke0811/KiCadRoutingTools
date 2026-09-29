#!/usr/bin/env python3
"""#962 parity gate for the paste-stencil model: both parse paths, plus native pcbnew as an oracle.

`parse_kicad_pcb` (file text) and `build_pcb_data_from_board` (live pcbnew)
feed the SAME `paste_apertures.build_paste_apertures`. Parity can therefore
only break in what each path READS: the pad and footprint paste overrides, the
board `(setup ...)`, the paste graphics, and the new graphic-copper fields
(`drawn_width` / `graphic_kind` / `graphic_circle`). This gate compares every
one of those on every tracked board, and adds two checks the paths cannot give
each other.

- **A native oracle.** pcbnew's own `PAD.GetSolderPasteMargin(layer)` is
  KiCad's RESOLVED per-axis margin, and every pad opening's margin must equal
  it. Two parse paths that shared a wrong resolver would agree with each other
  and still fail here.
- **Witnesses.**
  - esp_prog U2's F.Paste graphic exists.
  - glasgow J1's pin-in-paste graphics exist.
  - ulx3s carries a pad whose ratio is -0.2.

  A parser that silently produced NO apertures would pass every parity arm.
  The witnesses make that fail instead.

A comparator self-test runs first. It removes one aperture from a copy and
requires the multiset comparison to notice, so the comparison cannot go blind
without this gate failing.

Needs pcbnew; re-execs into KiCad's python automatically. Exits 2 when no
pcbnew python is found, rather than 0, so a mutation battery using it as a
killer cannot score SURVIVED on an environment accident.

    python3 -X utf8 tests/gui_parity/test_962_paste_parity.py
"""

# ---------------------------------------------------------------------------
# NOT RUNNABLE ON ipc-migration: both of its fronts are SWIG.
#
# The read arm compares `parse_kicad_pcb` against the pcbnew
# `build_pcb_data_from_board`, which this branch replaced with the kipy
# builder; the write arm drives `gui_utils.apply_via_protection`, which the
# port removed. Left as it arrived it died with "GUI write side ran" FAILED,
# which exits like a real divergence.
#
# WHERE THE COVERAGE WENT.
#   read  -- tests/test_962_kipy_builder_fields.py grades the kipy builder's
#            #962 reads with REAL kipy objects: pad and footprint paste
#            overrides (set vs unset, where 0 is a value), the paste graphics
#            posed at the LIVE footprint pose, and the assembled stencil,
#            which must equal parse_kicad_pcb's on an unmoved board.
#   write -- this front writes no per-via protection token at all (kipy's Via
#            wrapper exposes none), so there is nothing to round-trip. What it
#            owes instead is disclosure: kicad_ipc_adapter.
#            disclose_unwritten_via_protection names every via laid without the
#            spec it carries.
#
# WHAT IS NOT COVERED: the kipy builder against a RUNNING KiCad (the builder
# needs the socket; fake_ipc_board re-parses the file, so it would grade the
# text parser twice). Measure it there before trusting it.
import sys

if __name__ == '__main__':
    print("SKIP: both arms of #962's paste parity are SWIG (the pcbnew builder, "
          "gui_utils.apply_via_protection). The kipy builder's #962 reads are "
          "graded by tests/test_962_kipy_builder_fields.py; the IPC front "
          "discloses the protection it does not write.")
    sys.exit(77)
