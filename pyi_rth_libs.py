"""PyInstaller runtime hook — register .libs sibling directories on Windows.

numpy 2.x (and several other wheels built with delvewheel) ship their native
DLL dependencies in a sibling directory like `numpy.libs/`. The wheel's
`_distributor_init.py` is responsible for calling `os.add_dll_directory()`
on this sibling at import time, but PyInstaller's frozen-import machinery
loads the package via its own importer and the side-effect doesn't always
fire — symptom is `ImportError: DLL load failed` when the .pyd tries to
resolve its native dependency.

Workaround: at bundle bootstrap, before any third-party code runs, scan the
bundle root for `*.libs` directories and add them to the DLL search path
explicitly. This is idempotent and harmless on platforms that don't have
the issue.
"""
import os
import sys


def _register_libs_dirs() -> None:
    if os.name != 'nt':
        return
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir is None:
        # Not running under PyInstaller — nothing to do.
        return
    try:
        for entry in os.listdir(bundle_dir):
            full = os.path.join(bundle_dir, entry)
            if entry.endswith('.libs') and os.path.isdir(full):
                try:
                    os.add_dll_directory(full)
                except (OSError, ValueError):
                    # add_dll_directory raises if the path doesn't exist or
                    # AddDllDirectory fails. Either way, silent fallback is
                    # correct — the next import will surface a clearer
                    # message than we could.
                    pass
    except OSError:
        pass


_register_libs_dirs()
