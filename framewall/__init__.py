"""framewall - detect visually-embedded prompt injection in screenshots."""

__version__ = "0.2.0"
__all__ = ["__version__", "scan_bytes", "scan_image"]


def __getattr__(name):
    # Lazy, so the guard hook's `import framewall` check can't mistake a broken Pillow for no framewall.
    if name in ("scan_bytes", "scan_image"):
        from . import scanner

        return getattr(scanner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
