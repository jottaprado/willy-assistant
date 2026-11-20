"""
Utilitários para descoberta e enumeração de hardware de áudio (sounddevice).
"""

import sys
from collections.abc import Callable

import sounddevice as sd


def get_input_devices(query_fn: Callable | None = None) -> list[tuple[int, str]]:
    """Lista todos os dispositivos de entrada de áudio (microfones) válidos."""
    devices = []
    try:
        fn = query_fn or sd.query_devices
        raw_devices = fn()
        for idx, d in enumerate(raw_devices):
            if d.get("max_input_channels", 0) > 0:
                nome = d.get("name", f"Dispositivo {idx}")
                devices.append((idx, nome))
    except Exception as e:  # noqa: BLE001 — fronteira PortAudio/callback de enumeração
        print(f"[AudioDevices] Erro ao listar dispositivos de entrada: {e!r}", file=sys.stderr)
    return devices
