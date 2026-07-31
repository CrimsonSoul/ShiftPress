"""
ShiftPrint - Batch print shift schedules via Word COM automation.

This package provides modules for:
- Configuration management (config)
- UI components (ui)
- Word document processing (word_processor)
- Date and scheduling logic (scheduler)
- Path validation (path_validation)
- Constants and styling (constants)
- Logging setup (logger)
- Per-user data paths (app_paths)
"""

__version__ = "3.0.0"
__author__ = "ShiftPrint"

__all__ = ["ShiftPrintApp", "main"]


def __getattr__(name: str) -> object:
    """Lazy-import heavy symbols to avoid eagerly loading the entire app stack.

    Args:
        name: The attribute name being looked up.

    Returns:
        The requested module-level symbol (``ShiftPrintApp`` or ``main``).

    Raises:
        AttributeError: If *name* is not a public symbol of this package.
    """

    if name in ("ShiftPrintApp", "main"):
        from .main import ShiftPrintApp, main  # noqa: F811

        globals()["ShiftPrintApp"] = ShiftPrintApp
        globals()["main"] = main
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
