#!/usr/bin/env python3
"""#943 / #944: the raster stack is OPTIONAL -- rendering only, never routing.

Main fixed three defects in `kicad_routing_plugin/deps_check.py`, the SWIG
entry point's first-launch pip dialog. **That file does not exist on this
branch**: the IPC port deleted it along with `action_plugin.py`, because
KiCad 10 provisions a per-plugin venv from `requirements.txt` on the first
action invocation. There is no import-name probe here, no `OPTIONAL_PACKAGES`
table and no one-click pip offer, so main's A (the `import Pillow` probe that
could never pass), B (the generated blocking list) and the DIALOG half of D
(#944's PEP 668 install offer) have no counterpart to test and are
deliberately absent.

What DOES carry over, and is tested here:

  B'. The dialog's own gate. `routing_dialog.py` (this branch's
      `swig_gui.py`) calls `startup_checks.dependency_problems` over
      `ROUTING_PACKAGES`, and that table must not carry Pillow --
      the GUI's only raster consumers, the movie recorder and the placement
      preview, both disable themselves -- so a venv that resolved everything
      except Pillow still opens a routing dialog. Nothing in the plugin may
      import PIL at module scope either, or the gate is bypassed by the
      import that reaches it.

  C.  `check_render_dependencies` raised StartupCheckError, a RuntimeError, so
      every `except ImportError` consumer that MEANS to disable rendering
      walked past it. It raises RenderDependencyError now, which is both.

  B2. Placement GRADING does not need the raster stack.

  D'. The PEP 668 probe and distro tables in `startup_checks` (shared code).

Run with:  python3 tests/test_943_optional_render_dependency.py
"""
import ast
import importlib
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, 'py_router'))   # #522
sys.path.insert(0, os.path.join(ROOT_DIR, 'py_tools'))    # #522
sys.path.insert(0, os.path.join(ROOT_DIR, 'kicad_routing_plugin'))

from startup_checks import (RenderDependencyError, StartupCheckError,  # noqa: E402
                            check_render_dependencies)

PLUGIN_DIR = os.path.join(ROOT_DIR, 'kicad_routing_plugin')

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


def _module_scope_imports(path):
    """Top-level `import X` / `from X import ...` names in one file.

    AST, not a grep: an import nested inside a function or a try/except that
    the gate guards is exactly the shape this test must NOT flag, and a
    source-text scan cannot tell the two apart.
    """
    names = set()
    for node in ast.parse(open(path, encoding='utf-8').read()).body:
        if isinstance(node, ast.Import):
            names.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split('.')[0])
    return names


# ---------------------------------------------------------------------------
# B'. the dialog's hand-written gate does not carry Pillow
# ---------------------------------------------------------------------------
def test_the_dialog_gate_does_not_block_on_pillow():
    dlg = os.path.join(PLUGIN_DIR, 'routing_dialog.py')
    src = open(dlg, encoding='utf-8').read()
    # The gate CALLS the shared probe now, over ROUTING_PACKAGES, instead of
    # hand-mirroring a package list -- so "does not block on Pillow" is a
    # property of that table, and the call is what makes the table the gate.
    import startup_checks
    check('dependency_problems(ROUTING_PACKAGES)' in src,
          "routing_dialog.py's dependency gate no longer calls the shared "
          "probe over ROUTING_PACKAGES -- a hand-written list is how it "
          "drifted before")
    check('Pillow' not in startup_checks.ROUTING_PACKAGES,
          "Pillow is in ROUTING_PACKAGES, so the dialog gate blocks on it -- "
          "routing does not need it, and this would refuse a board this GUI "
          "can route (#943 B, #887)")
    check("missing.append('Pillow')" not in src
          and 'missing.append("Pillow")' not in src,
          "routing_dialog.py grew a hand-written gate that blocks on Pillow")

    # And the gate cannot be bypassed by an import that reaches it first.
    offenders = sorted(
        os.path.basename(p) for p in
        [os.path.join(PLUGIN_DIR, f) for f in sorted(os.listdir(PLUGIN_DIR))
         if f.endswith('.py')]
        if 'PIL' in _module_scope_imports(p))
    check(not offenders,
          f"these plugin modules import PIL at module scope, so a venv "
          f"without Pillow fails before the gate can decide: {offenders}")


# ---------------------------------------------------------------------------
# C. the render gate is catchable by the consumers that disable rendering
# ---------------------------------------------------------------------------
def test_render_gate_is_an_import_error():
    check(issubclass(RenderDependencyError, ImportError),
          "RenderDependencyError is not an ImportError, so the `except "
          "ImportError` consumers that disable rendering miss it (#943 C)")
    check(issubclass(RenderDependencyError, StartupCheckError),
          "RenderDependencyError is no longer a StartupCheckError, so callers "
          "that catch the startup contract miss it")

    saved = sys.modules.get('PIL', '<absent>')
    sys.modules['PIL'] = None          # makes `from PIL import ...` raise
    try:
        raised = None
        try:
            check_render_dependencies()
        except Exception as exc:                                # noqa: BLE001
            raised = exc
        check(isinstance(raised, RenderDependencyError),
              f"check_render_dependencies raised {type(raised).__name__} with "
              f"Pillow unavailable, not RenderDependencyError")
        check(raised is not None and 'Pillow' in str(raised),
              "the render gate's message does not name Pillow, so it is not "
              "the actionable message #887 asked for")
    finally:
        if saved == '<absent>':
            sys.modules.pop('PIL', None)
        else:
            sys.modules['PIL'] = saved


# ---------------------------------------------------------------------------
# B2. placement GRADING does not need the raster stack
# ---------------------------------------------------------------------------
def test_render_placement_imports_without_pillow():
    """`board_context` and the stress predictors import render_placement for
    PlacementModel / legality_findings and draw nothing. A module-scope raster
    gate made Pillow a requirement of grading a placement."""
    saved_pil = sys.modules.get('PIL', '<absent>')
    dropped = [m for m in list(sys.modules)
               if m == 'render_placement' or m.startswith('render_placement.')]
    saved_mods = {m: sys.modules.pop(m) for m in dropped}
    sys.modules['PIL'] = None
    try:
        mod = importlib.import_module('render_placement')
        for name in ('PlacementModel', 'legality_findings'):
            check(hasattr(mod, name),
                  f"render_placement imported without Pillow but has no "
                  f"{name} -- the lazy split dropped a non-raster export")
    except Exception as exc:                                    # noqa: BLE001
        check(False,
              f"render_placement cannot be imported without Pillow: "
              f"{type(exc).__name__}: {exc} (#943)")
    finally:
        sys.modules.pop('render_placement', None)
        sys.modules.update(saved_mods)
        if saved_pil == '<absent>':
            sys.modules.pop('PIL', None)
        else:
            sys.modules['PIL'] = saved_pil


# ---------------------------------------------------------------------------
# D. PEP 668 (#944)
# ---------------------------------------------------------------------------
def test_pep668_probe_and_message():
    """Both arms of the probe, against a PLANTED marker.

    Reading only the real interpreter would make this vacuous on every machine
    that is not a PEP 668 distro -- which is every machine this repo is
    developed on, and the one arm that matters would never run.

    The probe and the distro tables live in `startup_checks` since #1026,
    shared with main's install_plugin.py and deps_check.py. Neither calls them
    on this branch (the IPC installer pip-installs nothing, and deps_check is
    gone), but the module is shared, so its half of #944 is still graded here.
    main's other half -- deps_check's PEP 668 DIALOG -- has no counterpart.
    """
    import sysconfig as _sysconfig
    import tempfile
    import startup_checks

    real = startup_checks.externally_managed_marker()
    check(real is None or os.path.isfile(real),
          f"externally_managed_marker returned {real!r}, which is not a file")

    with tempfile.TemporaryDirectory() as tmp:
        planted = os.path.join(tmp, "EXTERNALLY-MANAGED")
        with open(planted, "w") as fh:
            fh.write("[externally-managed]\n")
        saved_get_path = _sysconfig.get_path
        saved_prefix, saved_base = sys.prefix, sys.base_prefix
        try:
            _sysconfig.get_path = (
                lambda key, *a, **k: tmp if key in ("stdlib", "platstdlib")
                else saved_get_path(key, *a, **k))

            sys.prefix = sys.base_prefix = "/usr"      # a system interpreter
            check(startup_checks.externally_managed_marker() == planted,
                  "externally_managed_marker did not find a planted PEP 668 "
                  "marker, so the #944 branch can never fire")

            sys.prefix = "/usr/venv-943"              # prefix != base_prefix
            check(startup_checks.externally_managed_marker() is None,
                  "externally_managed_marker claims a venv is externally "
                  "managed; PEP 668 exempts venvs and pip installs into them "
                  "fine, so this would withhold a working one-click install "
                  "(#944)")
        finally:
            _sysconfig.get_path = saved_get_path
            sys.prefix, sys.base_prefix = saved_prefix, saved_base

    names = ['scipy', 'shapely', 'Pillow']
    apt = startup_checks.distro_command(names, startup_checks.DISTRO_PACKAGES)
    dnf = startup_checks.distro_command(names, startup_checks.FEDORA_PACKAGES)
    arch = startup_checks.distro_command(names, startup_checks.ARCH_PACKAGES)
    check('python3-pil ' not in dnf + ' ' and dnf.endswith('python3-pillow'),
          f"the Fedora spelling of Pillow is python3-pillow, got: {dnf}")
    check(apt.endswith('python3-pil'),
          f"the Debian spelling of Pillow is python3-pil, got: {apt}")
    check(arch == 'python-scipy python-shapely python-pillow',
          f"the Arch spelling is python-<name>, got: {arch}")
    for n in names:
        for label, table in (('Debian', startup_checks.DISTRO_PACKAGES),
                             ('Arch', startup_checks.ARCH_PACKAGES)):
            check(n in table,
                  f"{n} has no {label} package name, so the #944 message "
                  f"would offer `{n.lower()}`")


def run():
    test_the_dialog_gate_does_not_block_on_pillow()
    test_render_gate_is_an_import_error()
    test_render_placement_imports_without_pillow()
    test_pep668_probe_and_message()

    if FAILS:
        for f in FAILS:
            print(f"  FAIL  {f}")
        print(f"\n{len(FAILS)} check(s) FAILED")
        return False
    print("PASS  #943 optional raster dependency and catchable render gate "
          "(the deps_check half has no counterpart on ipc-migration)")
    return True


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
