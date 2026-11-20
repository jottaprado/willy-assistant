"""
Módulo do Pipeline de Transcrição e Processamento de IA do Willy.
Desacopla a orquestração de áudio, Whisper, Refino LLM, Injeção e Persistência.
"""

from .transcription_pipeline import (
    PipelineContext,
    PipelineResult,
    TranscriptionPipeline,
)

__all__ = [
    "PipelineContext",
    "PipelineResult",
    "TranscriptionPipeline",
]
