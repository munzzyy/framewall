"""framewall - detect visually-embedded prompt injection in screenshots."""

from .scanner import scan_bytes, scan_image

__version__ = "0.2.0"
__all__ = ["__version__", "scan_bytes", "scan_image"]
