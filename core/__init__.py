"""
Pacote Central do Willy (Core).
Reúne os módulos de configuração, áudio, inteligência artificial, processamento de texto,
atalhos e controle de processo. A interface mora em ui/: core não importa ui.
"""

from .actions import ActionManager
from .audio import AudioManager, negociar_stream
from .autostart import AutoStartManager
from .config import (
    BASE_DIR,
    CHANNELS,
    DEV_PROMPT_CONTEXT,
    ENV_FILE,
    FLAG_SHOW_DASHBOARD,
    HISTORY_FILE,
    SAMPLE_RATE,
    USER_DATA_DIR,
    VOCAB_FILE,
    ConfigManager,
)
from .context import ContextCategory, ContextManager
from .groq_service import GroqService
from .hotkey import Win32HotKeyManager
from .pipeline.transcription_pipeline import (
    PipelineContext,
    PipelineResult,
    TranscriptionPipeline,
)
from .single_instance import SingleInstanceManager
from .snippets import SnippetManager
from .sound import SoundManager
from .system.injector import TextInjector, default_injector
from .text_processing import TextProcessor
from .tts import TTSManager

__all__ = [
    "BASE_DIR",
    "CHANNELS",
    "DEV_PROMPT_CONTEXT",
    "ENV_FILE",
    "FLAG_SHOW_DASHBOARD",
    "HISTORY_FILE",
    "SAMPLE_RATE",
    "USER_DATA_DIR",
    "VOCAB_FILE",
    "ActionManager",
    "AudioManager",
    "AutoStartManager",
    "ConfigManager",
    "ContextCategory",
    "ContextManager",
    "GroqService",
    "PipelineContext",
    "PipelineResult",
    "SingleInstanceManager",
    "SnippetManager",
    "SoundManager",
    "TTSManager",
    "TextInjector",
    "TextProcessor",
    "TranscriptionPipeline",
    "Win32HotKeyManager",
    "default_injector",
    "negociar_stream",
]
