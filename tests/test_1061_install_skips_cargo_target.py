#!/usr/bin/env python3
"""#1061: install_plugin.py must not copy the cargo build dir into KiCad.

`build_router.py --from-source` leaves rust_router/target/ behind (~118 MB of
intermediates on Windows), and copy_plugin() copied it into every KiCad
version's plugins directory -- a 177 MB install where ~30 MB is the plugin.
package_pcm.py already strips `target`; the local installer did not.

  A. copy_plugin() leaves rust_router/target/ behind.
  B. Everything the plugin loads from rust_router/ is still copied: the
     grid_router binary next to Cargo.toml, and the crate sources.
  C. Only the cargo build dir is skipped: a `target` directory elsewhere in
     the tree is copied as before.

Run with:  python3 tests/test_1061_install_skips_cargo_target.py
"""
import os
import sys
import tempfile
from pathlib import Path

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, ROOT_DIR)

import install_plugin  # noqa: E402

RUN_ALL_FAST_OK = True

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


def _touch(path: Path, data: bytes = b'x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _install_fake_tree():
    """Copy a minimal source tree the way install_plugin does; return the
    installed root (the TemporaryDirectory is kept alive by the caller)."""
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / 'src' / 'KiCadRoutingTools'
    _touch(src / '__init__.py')
    _touch(src / 'rust_router' / 'Cargo.toml')
    _touch(src / 'rust_router' / 'src' / 'lib.rs')
    _touch(src / 'rust_router' / 'grid_router.pyd')
    _touch(src / 'rust_router' / 'target' / 'release' / 'grid_router.dll')
    _touch(src / 'rust_router' / 'target' / 'release' / 'deps' / 'numpy.rlib')
    _touch(src / 'py_router' / 'target' / 'keep.py')
    dest = Path(tmp.name) / 'plugins' / 'KiCadRoutingTools'
    install_plugin.copy_plugin(src, dest)
    return tmp, dest


def test_cargo_target_not_copied():
    tmp, dest = _install_fake_tree()
    with tmp:
        check(not (dest / 'rust_router' / 'target').exists(),
              "rust_router/target/ (the cargo build dir) was copied into the "
              "installed plugin")


def test_router_binary_and_sources_copied():
    tmp, dest = _install_fake_tree()
    with tmp:
        for rel in ('rust_router/grid_router.pyd', 'rust_router/Cargo.toml',
                    'rust_router/src/lib.rs', '__init__.py'):
            check((dest / rel).is_file(), f"{rel} is missing from the install")


def test_other_target_dirs_copied():
    tmp, dest = _install_fake_tree()
    with tmp:
        check((dest / 'py_router' / 'target' / 'keep.py').is_file(),
              "a `target` directory outside rust_router/ was skipped too")


def run():
    test_cargo_target_not_copied()
    test_router_binary_and_sources_copied()
    test_other_target_dirs_copied()

    if FAILS:
        for f in FAILS:
            print(f"  FAIL  {f}")
        print(f"\n{len(FAILS)} check(s) FAILED")
        return False
    print("PASS  #1061 install_plugin skips rust_router/target, keeps the "
          "router binary and sources")
    return True


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
