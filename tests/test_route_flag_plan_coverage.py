#!/usr/bin/env python3
"""Every route.py flag must replay through a GUI plan, or say why it does not.

`route.py --bus` has a GUI home -- the Advanced-options checkbox `bus_enabled`
-- and a recorded manifest replayed through a GUI plan still routed with bus
mode OFF: the converter's unknown-flag fallthrough spelled the param `bus`,
which matches no control and no alias, so the plan executor logged "no control
for bus, ignored". The converter-parity gate never saw it, because it checks
only the flags a recorded manifest uses AND a hand-kept table names, and
`--bus` was on no table.

`tests/gui_parity/test_manifest_plan_parity.py` now carries
`check_route_flag_coverage`, which enumerates EVERY flag route.py's argparse
accepts and requires each to be reached, listed CLI-only with a reason, or
listed as a known gap. THIS IS ITS WX-FREE, RUN_ALL HALF: `run_all.py`'s flat
glob never collects `tests/gui_parity/`, so a gate living only there is one
this suite cannot fail on. It runs the gate (in-process and on the fixture),
pins the `--bus` fix itself, and proves by NEGATIVE CONTROL that the gate
fails for the right reason -- on a temp copy of the tree, never the repo:

  * the --bus converter row AND legacy alias removed -> --bus NOT REACHED;
  * only the alias removed -> the legacy `bus` name resolves nowhere;
  * only the row removed -> the fixture's --bus expectation fails;
  * a made-up flag added to route.py's parser and to nothing else;
  * a --no-X flag "fixed" with a plain alias onto its POSITIVE checkbox;
  * a stale CLI-only entry for a flag that reaches the GUI;
  * the bus_enabled line dropped from reset_params_to_defaults, and each of
    the five keepout / guide-corridor reset lines, one at a time.
"""
from __future__ import annotations

RUN_ALL_FAST_OK = True

import io
import os
import shutil
import sys
import tempfile
import unittest

_TESTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS)
for _p in (_TESTS, os.path.join(_TESTS, 'stress'),
           os.path.join(_TESTS, 'gui_parity')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_utils                                              # noqa: E402

GATE = os.path.join(_TESTS, 'gui_parity', 'test_manifest_plan_parity.py')
FIXTURE = os.path.join(_TESTS, 'gui_parity', 'fixtures',
                       'sample_redo_commands.sh')


def _src(path):
    with io.open(path, encoding='utf-8', newline='') as f:
        return f.read()


class TheEnumeration(unittest.TestCase):
    """In-process: every flag is accounted for, and exactly once."""

    @classmethod
    def setUpClass(cls):
        import test_manifest_plan_parity as gate
        cls.gate = gate
        cls.bad, cls.rows = gate.check_route_flag_coverage()

    def test_every_route_flag_is_accounted_for(self):
        self.assertEqual(self.bad, [], '\n'.join(
            '%s: %s' % b for b in self.bad))

    def test_it_enumerates_the_parser_not_a_list(self):
        """The universe is krt_capabilities.script_flags, which
        tests/test_798_registrar_flags.py holds EXACT against argparse. A
        hand list only covers the flags someone thought of."""
        import krt_capabilities as caps
        real = set(caps.script_flags(caps._tool_path(caps.ROOT, 'route.py')))
        self.assertEqual(set(self.rows), real)
        self.assertIn('--bus', self.rows)

    def test_each_flag_has_one_disposition(self):
        both = set(self.gate.ROUTE_CLI_ONLY) & set(self.gate.ROUTE_KNOWN_GAPS)
        self.assertEqual(both, set())
        for flag, (disp, detail) in self.rows.items():
            self.assertIn(disp, ('reached', 'cli-only', 'known-gap'),
                          '%s: %s' % (flag, detail))

    def test_the_known_gaps_are_still_gaps(self):
        """A known-gap entry is a promise that the flag does NOT reach the
        GUI yet; the gate fails the day it does, so the list cannot rot."""
        for flag in self.gate.ROUTE_KNOWN_GAPS:
            self.assertEqual(self.rows[flag][0], 'known-gap', flag)

    def test_no_reached_control_is_parked_as_a_leak(self):
        """keepout_check and guide_corridor_check leaked between plan steps
        until their reset lines landed; the list that held them is empty,
        and a new leak must be fixed in the reset, not parked there."""
        self.assertEqual(self.gate.ROUTE_RESET_KNOWN_GAPS, {})


class TheBusFix(unittest.TestCase):
    """The defect itself, pinned on both halves of the path."""

    def test_the_converter_emits_the_control_name(self):
        import manifest_to_plan as m2p
        step = m2p.parse_command(
            ['python3', 'py_router/route.py', 'in.kicad_pcb', 'out.kicad_pcb',
             '--nets', '*', '--bus', '--bus-detection-radius', '4'])
        self.assertIs(step['params'].get('bus_enabled'), True)
        self.assertNotIn('bus', step['params'])
        self.assertEqual(step['params'].get('bus_detection_radius'), 4)

    def test_a_plan_converted_before_the_row_still_reaches_it(self):
        import test_manifest_plan_parity as gate
        aliases, _special = gate._ai_plan_tables()
        self.assertEqual(aliases.get('bus'), 'bus_enabled')
        self.assertEqual(gate._class_widgets()['RoutingDialog'].get(
            'bus_enabled'), 'CheckBox')

    def test_the_control_is_reset_and_persisted(self):
        """CLAUDE.md: a plan-settable control must be in
        reset_params_to_defaults or it leaks between steps -- and a
        persisted one must be saved AND restored."""
        import test_manifest_plan_parity as gate
        self.assertIn('bus_enabled', gate._reset_touched())
        persist = _src(os.path.join(_ROOT, 'kicad_routing_plugin',
                                    'settings_persistence.py'))
        self.assertIn("'bus_enabled': dialog.bus_enabled.GetValue()", persist)
        self.assertIn("if 'bus_enabled' in settings:", persist)


class TheGuiParityGate(unittest.TestCase):
    """The counterpart this file is the run_all half of."""

    def test_the_gate_exists_and_its_main_runs_the_enumeration(self):
        self.assertTrue(os.path.isfile(GATE))
        main = _src(GATE).split('\ndef main(', 1)[1]
        self.assertIn('check_route_flag_coverage()', main)

    def test_the_whole_converter_gate_passes_on_the_fixture(self):
        r = run_utils.check([sys.executable, '-X', 'utf8', GATE, FIXTURE],
                            accept=True, timeout=300)
        self.assertIn('Route flag coverage: OK', r.stdout)
        self.assertIn('0 mismatch(es)', r.stdout)


# --- negative controls ---------------------------------------------------------
# The gate is run as a subprocess on a TEMP COPY of what it reads: the
# plugin's four GUI files and ai_plan.py, the converter, the gate itself and
# its fixture, and py_router / py_tools / py_placer + krt_capabilities.py for
# the flag scan. Each control mutates one or two files in the copy, asserts
# the gate refuses for the STATED reason (run_utils.check reports a traceback
# or an import failure as a broken test, not a held guard), and restores the
# copy. The repository is never written.

_COPY_DIRS = ('py_router', 'py_tools', 'py_placer', 'tests/stress')
_COPY_FILES = ('krt_capabilities.py',
               'kicad_routing_plugin/ai_plan.py',
               'kicad_routing_plugin/swig_gui.py',
               'kicad_routing_plugin/differential_gui.py',
               'kicad_routing_plugin/fanout_gui.py',
               'kicad_routing_plugin/planes_gui.py',
               'tests/gui_parity/test_manifest_plan_parity.py',
               'tests/gui_parity/fixtures/sample_redo_commands.sh')

M2P = 'tests/stress/manifest_to_plan.py'
AI_PLAN = 'kicad_routing_plugin/ai_plan.py'
SWIG = 'kicad_routing_plugin/swig_gui.py'
ROUTE = 'py_router/route.py'
GATE_REL = 'tests/gui_parity/test_manifest_plan_parity.py'


class NegativeControls(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='route_flag_cov_')
        ign = shutil.ignore_patterns('__pycache__', '*.so', '*.pyd',
                                     '*.kicad_pcb', '*.kicad_pro', '*.png')
        for d in _COPY_DIRS:
            shutil.copytree(os.path.join(_ROOT, d), os.path.join(cls.tmp, d),
                            ignore=ign)
        for f in _COPY_FILES:
            dst = os.path.join(cls.tmp, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(os.path.join(_ROOT, f), dst)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _path(self, rel):
        return os.path.join(self.tmp, rel)

    def _mutate(self, rel, old, new, within=None):
        """Replace ONE exact occurrence in the copy; restored on cleanup.

        Anchors are SINGLE-LINE and carry no newline, so they match an LF and
        a CRLF checkout alike (read and written with newline=''); a removed
        statement becomes `pass`, so the file stays valid Python. `within`
        names a `def` whose body the anchor must be unique in -- the reset
        lines repeat the constructor's own lines byte for byte."""
        path = self._path(rel)
        before = _src(path)
        start, end = 0, len(before)
        if within is not None:
            start = before.index('def %s(' % within)
            nxt = before.find('\n    def ', start + 1)
            end = nxt if nxt != -1 else end
        region = before[start:end]
        self.assertNotIn('\n', old)
        self.assertEqual(region.count(old), 1,
                         'mutation anchor %r is not unique in %s%s -- the '
                         'control would test nothing'
                         % (old, rel, ' ' + within if within else ''))
        with io.open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(before[:start] + region.replace(old, new) + before[end:])

        def restore():
            with io.open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(before)
        self.addCleanup(restore)
        return restore

    def _run(self, **kw):
        gate = self._path(GATE_REL)
        fixture = self._path('tests/gui_parity/fixtures/'
                             'sample_redo_commands.sh')
        return run_utils.check([sys.executable, '-X', 'utf8', gate, fixture],
                               cwd=self.tmp, timeout=300, **kw)

    def test_0_the_unmutated_copy_passes(self):
        """The precondition: without it, a refusal below could be the COPY's
        fault rather than the mutation's."""
        r = self._run(accept=True)
        self.assertIn('Route flag coverage: OK', r.stdout)

    def test_bus_row_and_alias_removed(self):
        self._mutate(M2P, "'--bus': 'bus_enabled',", '')
        self._mutate(AI_PLAN, "'bus': 'bus_enabled',", '')
        self._run(refuse="--bus: NOT REACHED -- param 'bus' -> 'bus', which "
                         "is no settable control")

    def test_bus_alias_removed_only(self):
        """The converter still emits bus_enabled, so the ENUMERATION holds;
        a plan converted before the row carries `bus`, and that name must
        still resolve."""
        self._mutate(AI_PLAN, "'bus': 'bus_enabled',", '')
        self._run(refuse='bus: no control, no alias')

    def test_bus_row_removed_only(self):
        """The legacy alias still reaches the control, so the ENUMERATION
        holds; the fixture's independent expectation is what catches a
        converter that stopped emitting the control's own name."""
        self._mutate(M2P, "'--bus': 'bus_enabled',", '')
        self._run(refuse='--bus: bool flag not set (bus_enabled)')

    def test_a_made_up_route_flag_added_to_nothing(self):
        anchor = 'parser.add_argument("--bus", action="store_true",'
        self._mutate(ROUTE, anchor,
                     'parser.add_argument("--zz-probe-knob", type=float, '
                     'default=1.0, help="negative control"); ' + anchor)
        self._run(refuse="--zz-probe-knob: NOT REACHED -- param "
                         "'zz_probe_knob'")

    def test_a_no_flag_aliased_onto_its_positive_checkbox(self):
        """A plain alias renames; it cannot invert. `no_smoothing -> smoothing`
        would TICK the box the flag exists to untick."""
        self._mutate(M2P, "'--no-smoothing': 'smoothing',", '')
        self._mutate(AI_PLAN, "'bus': 'bus_enabled',",
                     "'bus': 'bus_enabled', 'no_smoothing': 'smoothing',")
        self._run(refuse="a --no-X switch landing on the POSITIVE checkbox "
                         "'smoothing' must untick it")

    def test_a_stale_cli_only_entry(self):
        self._mutate(GATE_REL, "ROUTE_CLI_ONLY = {",
                     "ROUTE_CLI_ONLY = {'--bus': 'negative control',")
        self._run(refuse='--bus: STALE list entry: it now reaches the GUI')

    def test_a_control_missing_from_the_reset(self):
        self._mutate(SWIG, 'self.bus_enabled.SetValue(False)', 'pass',
                     within='reset_params_to_defaults')
        self._run(refuse='--bus: LEAKS between plan steps: bus_enabled is '
                         'not restored by reset_params_to_defaults')

    def test_each_keepout_and_corridor_reset_line_is_load_bearing(self):
        """The five reset lines that ended the keepout / guide-corridor leak.
        keepout_check and guide_corridor_check had leaked since they were
        aliased; each line is removed alone and must be named."""
        for line, flag, ctrl in (
                ('self.keepout_check.SetValue(defaults.KEEPOUT_ENABLED)',
                 '--keepout', 'keepout_check'),
                ('self.keepout_layer_ctrl.SetValue(defaults.KEEPOUT_LAYER)',
                 '--keepout-layer', 'keepout_layer_ctrl'),
                ('self.guide_corridor_check.SetValue('
                 'defaults.GUIDE_CORRIDOR_ENABLED)',
                 '--guide-corridor', 'guide_corridor_check'),
                ('self.guide_corridor_layer_ctrl.SetValue('
                 'defaults.GUIDE_CORRIDOR_LAYER)',
                 '--guide-corridor-layer', 'guide_corridor_layer_ctrl'),
                ('self.guide_corridor_spacing_ctrl.SetValue('
                 'str(defaults.GUIDE_CORRIDOR_SPACING))',
                 '--guide-corridor-spacing', 'guide_corridor_spacing_ctrl')):
            with self.subTest(flag=flag):
                restore = self._mutate(SWIG, line, 'pass',
                                       within='reset_params_to_defaults')
                try:
                    self._run(refuse='%s: LEAKS between plan steps: %s is not '
                                     'restored' % (flag, ctrl))
                finally:
                    restore()


if __name__ == '__main__':
    unittest.main(verbosity=2)
