"""
Módulo de Abas da Interface Gráfica (Dashboard) do Willy.
"""

from .tab_diagnostics import DiagnosticsTab, build_tab_diagnostics
from .tab_history import HistoryTab, build_tab_history
from .tab_onboarding import OnboardingTab, build_tab_onboarding
from .tab_settings import SettingsTab, build_tab_settings
from .tab_shortcuts import build_tab_shortcuts, render_keycaps_row
from .tab_templates import TemplatesTab, build_tab_templates
from .tab_vocabulary import VocabularyTab, build_tab_vocabulary

__all__ = [
    "DiagnosticsTab",
    "HistoryTab",
    "OnboardingTab",
    "SettingsTab",
    "TemplatesTab",
    "VocabularyTab",
    "build_tab_diagnostics",
    "build_tab_history",
    "build_tab_onboarding",
    "build_tab_settings",
    "build_tab_shortcuts",
    "build_tab_templates",
    "build_tab_vocabulary",
    "render_keycaps_row",
]
