"""
O nível de voz acima do ruído e o diagnóstico do teste de microfone (Bloco 9).

A pílula e a aba Diagnósticos mostravam o volume cru: na webcam C920 do dono (ruído em silêncio
~0,032), as barras ficavam altas e vermelhas em silêncio, e o medidor do teste, metade cheio. Os
dois descontam o piso de ruído do mesmo jeito, com o limiar de silêncio do corte por silêncio.
"""

from collections.abc import Sequence

import numpy as np

from .vad import (
    FATOR_FALA,
    FATOR_SILENCIO,
    LIMIAR_FALA_BASE,
    LIMIAR_SILENCIO_BASE,
    ZERO_DIGITAL,
)

# O zero é o limiar de silêncio do corte por silêncio (NoiseFloorTracker: 2,2x o piso, base 0,005).
_ZERO = LIMIAR_SILENCIO_BASE
_FATOR_DO_SILENCIO = FATOR_SILENCIO
_FAIXA = 0.035
# Voz perto de saturar o microfone.
VOLUME_SATURANDO = 0.35

# Diagnóstico do teste de 5 s.
_RUIDO_BAIXO, _RUIDO_MODERADO = 0.006, 0.02
_FATOR_DA_FALA = FATOR_FALA  # o limiar de fala do corte por silêncio
_VOZ_BOA_MINIMA, _VOZ_BAIXA_MINIMA = 0.02, LIMIAR_FALA_BASE
_MUDO = ZERO_DIGITAL


def nivel_acima_do_piso(volume: float, piso_ruido: float = 0.0) -> float:
    """De 0 a 1, quanto a voz passa do ruído: 0 no silêncio (abaixo do limiar de silêncio), 1 na
    voz alta. A faixa cresce com o piso, para a fala normal não encher a barra num microfone com
    ruído alto."""
    zero = max(_ZERO, piso_ruido * _FATOR_DO_SILENCIO)
    faixa = max(_FAIXA, zero * 4)
    return float(min(1.0, max(0.0, (volume - zero) / faixa)))


def medir_teste(volumes: Sequence[float]) -> tuple[float, float]:
    """(piso de ruído, pico de voz) de um teste: o p10 e o p95 dos volumes medidos. O p95, e não o
    máximo, para um clique na mesa não passar por voz."""
    if not volumes:
        return 0.0, 0.0
    v = np.asarray(volumes, dtype=np.float64)
    return float(np.percentile(v, 10)), float(np.percentile(v, 95))


def resumo_do_teste(volumes: Sequence[float]) -> tuple[str, bool]:
    """O diagnóstico legível do teste de microfone e se o microfone está pronto para ditar."""
    piso, voz = medir_teste(volumes)
    if voz < _MUDO:
        return "Microfone mudo: nenhum som chegou. Confira o microfone nos Ajustes.", False
    ruido = "baixo" if piso < _RUIDO_BAIXO else ("moderado" if piso < _RUIDO_MODERADO else "alto")
    if voz >= max(_VOZ_BOA_MINIMA, piso * _FATOR_DA_FALA):
        qualidade, status, pronto = "boa", "pronto para ditado", True
    elif voz >= max(_VOZ_BAIXA_MINIMA, piso * _FATOR_DO_SILENCIO):
        qualidade, status, pronto = "baixa", "fale mais perto do microfone", False
    else:
        qualidade, status, pronto = "não detectada", "fale durante o teste", False
    return f"Ruído ambiente: {ruido} · Voz: {qualidade} · Status: {status}", pronto


def parcial_do_teste(volumes: list[float]) -> str:
    """O que mostrar enquanto o teste corre."""
    piso, voz = medir_teste(volumes)
    return f"Medindo... ruído {piso:.3f} · voz {voz:.3f}"
