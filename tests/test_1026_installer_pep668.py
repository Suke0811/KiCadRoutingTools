#!/usr/bin/env python3
"""#1026: install_plugin.py on a PEP 668 interpreter.

KiCad's Linux packages run the system python, which Arch, Debian 12+, Ubuntu
23.04+ and Fedora 38+ mark EXTERNALLY-MANAGED. pip refuses there before it
resolves anything, so the installer printed pip's refusal and "run as
Administrator" on a machine whose packages were all installed already. The GUI
had been fixed for the same interpreter in #944; the installer had not.

  A. The out-of-process dependency probe (contributed in PR #1026) answers
     what the runtime gate answers -- including for a requirement with no
     floor, which that probe's first version dropped and so reported as
     satisfied whether it was installed or not.
  B. The marker probe asks the TARGET interpreter, not this one: a marker
     planted in the target (a sitecustomize on PYTHONPATH) is found, and this
     process's own answer is untouched.
  C. install_dependencies end to end, with the real probes and only pip
     intercepted:
       satisfied           -> True, pip never runs
       missing + PEP 668   -> False, pip never runs -- the distro commands and
                              a QUOTED override are printed, and nothing says
                              "Administrator"
       missing, no marker  -> pip runs once, its output NOT captured (the user
                              watches the download) and never with
                              --break-system-packages
       probe failed + PEP 668 -> every requirement named, none claimed absent

Run with:  python3 tests/test_1026_installer_pep668.py
"""

# ---------------------------------------------------------------------------
# NOT RUNNABLE ON ipc-migration, and it says so rather than dying mid-run.
#
# Every arm above grades install_plugin.py's PIP path: `install_dependencies`,
# `_target_dependency_problems` and `_target_externally_managed`. The IPC
# installer has none of them -- KiCad 10 provisions the plugin's venv from
# requirements.txt on the first action invocation, so the installer copies
# files and pip-installs nothing. Left as it arrived, arm A reached
# `startup_checks.dependency_problems` over EVERY requirement in this branch's
# requirements.txt, which also lists `kicad-python` and `wxPython`, and died
# on `import kicad-python` -- a SyntaxError that exits like a failed guard.
#
# WHERE THE COVERAGE WENT. The half of #1026 that is shared code --
# `startup_checks.externally_managed_marker` and the distro package tables --
# is graded by tests/test_943_optional_render_dependency.py (D'). Nothing on
# this branch installs dependencies, so arms B and C have no counterpart.
#
# Restore this file WITH the functions if the IPC installer ever installs
# packages itself.
import sys

if __name__ == '__main__':
    print("SKIP: install_plugin.py pip-installs nothing on ipc-migration (KiCad "
          "10 provisions the plugin venv from requirements.txt), so #1026's "
          "install_dependencies / _target_* probes do not exist. The shared "
          "PEP 668 probe is graded by tests/test_943_optional_render_dependency.py.")
    sys.exit(77)
