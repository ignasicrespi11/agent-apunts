"""Loader registry: file extension -> loader.

Registration is explicit (the list at the bottom), not automatic discovery: reading this file
tells you exactly which formats are supported.
"""

from pathlib import Path

from agent_apunts.ingestion.loaders.base import Loader, RawPage
from agent_apunts.ingestion.loaders.pdf import PdfLoader

__all__ = ["Loader", "RawPage", "loader_for", "register", "supported_extensions"]

_REGISTRY: dict[str, Loader] = {}


def register(loader: Loader) -> None:
    for ext in loader.extensions:
        if ext in _REGISTRY:
            raise ValueError(f"{ext} already handled by {_REGISTRY[ext].name}")
        _REGISTRY[ext] = loader


def loader_for(path: Path) -> Loader | None:
    return _REGISTRY.get(path.suffix.lower())


def supported_extensions() -> set[str]:
    return set(_REGISTRY)


# --- Supported formats. A new format = a new module in this folder + one line here. ---
register(PdfLoader())
