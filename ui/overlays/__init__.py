"""
Pacote de Overlays e Janelas Flutuantes do Willy (UI).
Contém widgets flutuantes Always-on-Top, pílula, spotlight, teleprompter e ícone de bandeja.
"""

from .pill import FloatingPill
from .spotlight import HistorySpotlight
from .teleprompter import LiveTeleprompter
from .tray import TrayManager

__all__ = [
    "FloatingPill",
    "HistorySpotlight",
    "LiveTeleprompter",
    "TrayManager",
]
