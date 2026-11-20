"""
Módulo de Efeitos Sonoros do Willy.
Executa bipes assíncronos via winsound sem bloquear as threads de hooks do Windows.
"""

import sys
import threading

try:
    import winsound
except ImportError:
    winsound = None


class SoundManager:
    """Gerencia bipes de feedback auditivo do Willy."""

    def __init__(self, is_silent_func=None):
        self._is_silent = is_silent_func or (lambda: False)

    def set_silent_checker(self, func):
        self._is_silent = func

    def play(self, beeps: list[tuple[int, int]]) -> None:
        """Executa sequência de bipes (frequência, duração_ms) em thread de background."""
        if not winsound or self._is_silent():
            return

        def _worker():
            try:
                for freq, dur in beeps:
                    winsound.Beep(freq, dur)
            except Exception as e:  # noqa: BLE001 — fronteira de hardware de áudio Win32 (winsound)
                print(f"[SoundManager] Aviso ao emitir bipe sonoro: {e!r}", file=sys.stderr)

        threading.Thread(target=_worker, daemon=True).start()

    def sound_start(self):
        """Som suave ao iniciar gravação (tom ascendente ultracurto)."""
        self.play([(1320, 45)])

    def sound_stop(self):
        """Som discreto ao encerrar gravação e começar processamento."""
        self.play([(880, 45)])

    def sound_success(self):
        """Acorde maior brilhante de confirmação ao colar com sucesso."""
        self.play([(1175, 40), (1568, 55)])

    def sound_action(self):
        """Acorde tríade futurista de ação do Copiloto de IA."""
        self.play([(988, 35), (1318, 45), (1760, 55)])

    def sound_error(self):
        """Tom grave sutil para erro ou cancelamento."""
        self.play([(440, 60), (330, 80)])

    def sound_sleep(self):
        """Melodia suave descendente de repouso."""
        self.play([(659, 50), (440, 70)])

    def sound_wake(self):
        """Melodia suave ascendente de despertar."""
        self.play([(659, 45), (988, 50), (1318, 60)])

    def play_wav_file(self, wav_path: str) -> bool:
        """Toca um arquivo .wav assincronamente usando winsound."""
        if not winsound or not wav_path or self._is_silent():
            return False
        import os
        if not os.path.exists(wav_path):
            return False
        try:
            winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de hardware de áudio Win32 (winsound)
            print(
                f"[SoundManager] Erro ao reproduzir arquivo WAV ({wav_path}): {e!r}",
                file=sys.stderr,
            )
            return False
