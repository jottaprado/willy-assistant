"""
Módulo de Processamento Digital de Sinal (DSP) e Dispositivos de Áudio do Willy.
Contém utilitários para amostragem, conversão de WAV, chunking, VAD e listagem de hardware.
"""

from .devices import get_input_devices
from .dsp import (
    convert_to_wav,
    preencher,
    reamostrar,
    split_audio_into_chunks,
)
from .vad import NoiseFloorTracker, compute_rms

__all__ = [
    "NoiseFloorTracker",
    "compute_rms",
    "convert_to_wav",
    "get_input_devices",
    "preencher",
    "reamostrar",
    "split_audio_into_chunks",
]
