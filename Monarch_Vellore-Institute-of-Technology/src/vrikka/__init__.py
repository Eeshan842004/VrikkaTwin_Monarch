"""VrikkaTwin: a kidney digital twin for Indian heatwaves."""
import os

__version__ = "0.1.0"


def _preload_msvc_runtime() -> None:
    """Windows only: load a current MSVC C++ runtime before LightGBM is imported.

    LightGBM 4.7 wheels are built with Visual Studio 2022 17.10+, whose std::mutex needs msvcp140.dll >= 14.40. With an
    older system runtime (seen on a build machine with 14.13) every LightGBM call fails with "access violation reading
    0x0000000000000000". scikit-learn's wheel bundles a current msvcp140.dll / vcomp140.dll; loading them first makes
    Windows reuse them for lib_lightgbm.dll. Harmless when the system runtime is already current; a no-op elsewhere.
    The proper fix on such a machine is the latest Microsoft Visual C++ Redistributable (x64).
    """
    if os.name != "nt":
        return
    import ctypes
    import importlib.util

    spec = importlib.util.find_spec("sklearn")
    if spec is None or not spec.submodule_search_locations:
        return
    libs = os.path.join(next(iter(spec.submodule_search_locations)), ".libs")
    for name in ("msvcp140.dll", "vcomp140.dll"):
        path = os.path.join(libs, name)
        if os.path.exists(path):
            try:
                ctypes.WinDLL(path)
            except OSError:
                pass


_preload_msvc_runtime()
