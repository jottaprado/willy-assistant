"""
Módulo de Armazenamento e Persistência do Willy.
"""

from core.storage.history_store import HistoryEntry, HistoryStore
from core.storage.profile_manager import ProfileManager
from core.storage.settings_store import AppRulesStore, SettingsStore
from core.storage.vocabulary_store import VocabularyStore

__all__ = [
    "AppRulesStore",
    "HistoryEntry",
    "HistoryStore",
    "ProfileManager",
    "SettingsStore",
    "VocabularyStore",
]
