#!/usr/bin/env python3
"""A copper layer renamed in Board Setup keeps its copper on the live board (#1056).

KiCad lets a layer carry a display name (Board Setup > Board Editor Layers:
In1.Cu shown as "GND"). board.GetLayerName() returns that name, while the
engine speaks only the canonical one ("In1.Cu"), so every live-board site that
mapped a layer through GetLayerName missed on a renamed layer:

  pour     the Planes tab's apply keyed its name -> id table by display name,
           so a pour for In1.Cu fell back to F.Cu, where the board's GND/+5V
           through-hole pads connect to nothing.
  rerun    its duplicate-zone guard compared the canonical layer with the
           display name, so a second Create poured every zone again.
  rip      the Route tab's ripped-copper strip keyed live tracks by display
           name, so a ripped track on a renamed layer stayed on the board.
  fill     live_fill_islands keyed its islands ('GND', 'GND'), a key no
           engine lookup of ('GND', 'In1.Cu') finds.
  builder  build_pcb_data_from_board fell back to the display name for a
           non-copper layer, so a User.1 renamed "In1.Cu" (the reporter's
           workaround) read as copper on In1.Cu, which the text parse never
           does.

Every arm drives the real code on a real headless RoutingDialog (nothing
mocked) and has a negative control: the pre-fix display-name mapping patched
back in must reproduce the bug, so a pass means the fix did the work.

Needs KiCad python (wx + pcbnew); re-execs into it like its siblings.

    python3 tests/gui_parity/test_1056_renamed_layers_gui.py
"""

# ---------------------------------------------------------------------------
# NOT RUNNABLE ON ipc-migration, and the reason is that the defect has no
# front here -- not that the gate is inconvenient.
#
# #1056 was the SWIG front naming a live layer with `board.GetLayerName()`,
# which returns the user's DISPLAY name once a layer is renamed in Board Setup.
# Every arm above patches or drives `swig_gui._build_layer_mappings` and the
# pcbnew `build_pcb_data_from_board`; neither exists on this branch.
#
# The IPC front never asks KiCad for a layer's name. kipy hands layers over as
# the `BoardLayer` enum, and `kicad_ipc_adapter.layer_maps` translates it
# through a FIXED table (BL_In1_Cu -> 'In1.Cu', ...) -- the file tokens, which
# is what #1056's `pcbnew_copper_layer_names` restores on main. The builder
# (`get_layer_name`), every apply path (`layer_id_for`) and the duplicate-zone
# check (`existing_zone_keys` via `layer_name_for`) all go through it.
#
# WHAT IS NOT COVERED: nothing on this branch drives a live KiCad with a
# renamed layer. Restore this file against the IPC front if a display-name
# read ever appears there.
import sys

if __name__ == '__main__':
    print("SKIP: #1056 is a SWIG display-name bug (swig_gui._build_layer_mappings, "
          "pcbnew GetLayerName); the IPC front maps kipy's BoardLayer enum through "
          "kicad_ipc_adapter.layer_maps' fixed canonical table and reads no "
          "display name.")
    sys.exit(77)
