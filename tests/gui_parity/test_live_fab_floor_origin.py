#!/usr/bin/env python3
"""A GUI run that relaxes a fab floor says so, and records what it relaxed.

The file writers (fix_project_for_output, apply_routed_floors) record the
board's ORIGINAL fab floors in `kicad_routing_tools.fab_floor_origin` before
lowering anything, and print FAB FLOOR RELAXED against that origin (ad7f24de,
run 14). The GUI lowers the same floors on the LIVE board -- each step runs
fix_kicad_drc_settings.apply_targets_to_board and then
gui_utils.update_live_drc_floors -- and did neither. A manual GUI run that took
min_via_diameter 0.8 -> 0.4 printed nothing, and a later CLI step baselined on
0.4.

Real pcbnew, a real routed board (lvds_converter_dualclk_gnd: 97 tracks, 9
vias) with a .kicad_pro declaring floors ABOVE what the step routes at, the
two live writers called as a routing tab calls them, stdout captured (every
tab's apply phase routes print() into its log):

  * the origin lands in the project at the DECLARED value, not the lowered one;
  * FAB FLOOR RELAXED names ORIGINAL -> now and counts real copper under it;
  * a second step, which lowers nothing more, still says the board is under
    its original (the run-14 rule);
  * a board whose floors the step does not lower gets no banner.

Needs KiCad python (pcbnew); re-execs into it like its siblings.

    python3 tests/gui_parity/test_live_fab_floor_origin.py
"""

# ---------------------------------------------------------------------------
# NOT RUNNABLE ON ipc-migration, and the reason is that the defect has no
# front here.
#
# This gate grades the SWIG front's LIVE writers -- `apply_targets_to_board`
# and `gui_utils.update_live_drc_floors`, lowering floors on a pcbnew BOARD.
# Neither runs on this branch: kipy cannot write live design settings, so
# every tab records its floors through
# `kicad_ipc_adapter.write_drc_settings_to_project`, which delegates to
# `fix_kicad_drc_settings.fix_project_for_output` -- the CLI's own file
# writer. That writer seeds `fab_floor_origin` and prints FAB FLOOR RELAXED
# itself, so the IPC front has the behaviour without a mirror.
#
# WHERE THE COVERAGE WENT: tests/test_run14_fab_floor_origin.py and
# tests/test_run8_fab_floor_disclosure.py grade that file writer.
import sys

if __name__ == '__main__':
    print("SKIP: gui_utils.update_live_drc_floors does not exist on "
          "ipc-migration; the IPC front writes floors through "
          "fix_project_for_output, whose fab_floor_origin / FAB FLOOR RELAXED "
          "is graded by tests/test_run14_fab_floor_origin.py and "
          "tests/test_run8_fab_floor_disclosure.py.")
    sys.exit(77)
