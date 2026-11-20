"""
Módulo de Captura e Processamento de Áudio do Willy.
Gerencia InputStream do sounddevice, bufferização thread-safe, RMS e detecção de silêncio.
"""

import io
import sys
import threading
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from .audio_processing.devices import get_input_devices
from .audio_processing.dsp import (
    convert_to_wav,
    preencher,
    reamostrar,
    split_audio_into_chunks,
)
from .audio_processing.vad import NoiseFloorTracker, PorteiroSilero, compute_rms
from .config import CHANNELS, SAMPLE_RATE

# Quadros de 20 ms no callback: o corte por silêncio foi medido e testado assim. Sem o blocksize,
# o quadro era o que o driver escolhesse; com 64 ms ou mais, a calibração passava de 1,3 s e a
# fala logo no começo podia ser cancelada ou cortada.
_QUADRO_DO_STREAM_S = 0.02


def negociar_stream(device_index: int | None, callback: Callable | None,
                    channels: int, taxa_preferida: int,
                    on_before_start: Callable[[int], None] | None = None) -> tuple[sd.InputStream, int]:
    """Abre um InputStream negociando a taxa, devolvendo (stream, taxa_real).

    Mora no nivel do modulo, e nao dentro do AudioManager, porque quem precisa dela nao
    e so o gravador: a aba de diagnostico abre o proprio stream para medir o microfone.
    Enquanto cada um mantinha a sua copia, o VU meter podia medir numa taxa enquanto a
    gravacao rodava em outra, e ninguem tinha como perceber.

    A taxa sai junto com o stream em vez de ir para um campo: cada device negocia a sua.
    `callback` pode ser None, que e o modo de leitura bloqueante do sounddevice.
    O stream volta JA INICIADO: abrir e iniciar sao falhas distintas no PortAudio, e um
    device que aceita a taxa na abertura pode recusa-la no start. Com o start fora da
    escada, esse caso nao caia para a taxa seguinte e ainda vazava o handle do device.
    """
    rates_to_try = [taxa_preferida]
    if device_index is not None:
        try:
            dev_info = sd.query_devices(device_index)
            native_sr = int(dev_info.get("default_samplerate", 0))
            if native_sr and native_sr not in rates_to_try:
                rates_to_try.append(native_sr)
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: sondagem e abertura PortAudio/sounddevice
            pass
    for fallback_sr in (48000, 44100):
        if fallback_sr not in rates_to_try:
            rates_to_try.append(fallback_sr)

    last_err = None
    for sr in rates_to_try:
        stream = None
        try:
            stream = sd.InputStream(
                samplerate=sr,
                channels=channels,
                device=device_index,
                callback=callback,
                blocksize=max(1, round(sr * _QUADRO_DO_STREAM_S)),
            )
            if on_before_start is not None:
                on_before_start(sr)
            stream.start()
            return stream, sr
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: PortAudio/sounddevice e montagem de buffer
            last_err = e
            if stream is not None:
                try:
                    stream.close()
                except Exception:  # noqa: BLE001, S110 — fronteira defensiva: close de stream falho PortAudio
                    pass

    raise last_err or RuntimeError("Falha ao inicializar stream de áudio com as taxas disponíveis.")


class AudioManager:
    """Controlador de captura e buffer de áudio do microfone."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS,
                 device_index: int | None = None,
                 system_device_index: int | None = None, gain_boost: float = 1.0,
                 whisper_mode: bool = False):
        self.sample_rate = sample_rate
        self.actual_sample_rate = sample_rate
        # Taxa real negociada pela captura de audio do sistema (modo reuniao). E um
        # device diferente do microfone, entao negocia a propria taxa.
        self.system_actual_sample_rate: int | None = None
        self.channels = channels
        self.device_index = device_index
        self.system_device_index = system_device_index
        self.gain_boost = gain_boost
        self.whisper_mode = False
        self.lock = threading.Lock()
        if whisper_mode:
            # O Modo Sussurro salvo nos Ajustes vale desde a partida. Antes só a tela de Ajustes
            # o aplicava: até alguém salvar de novo, o ditado gravava com o ganho normal.
            self.set_whisper_mode(True, gain_boost)

        self.stream: sd.InputStream | None = None
        # Quantas vezes o microfone abriu (criado ou religado): a escuta do "Ei Willy" recomeça a
        # medir o ruído a cada uma (outro microfone, ou o fade-in de quando ele acorda).
        self.aberturas_do_microfone = 0
        self.system_stream: sd.InputStream | None = None
        self.system_buffer: list[np.ndarray] = []
        self.is_awake = True
        self.is_recording = False
        self.is_stopping = False
        self.is_processing = False
        self.recording_mode = "transcribe"  # 'transcribe', 'translate', 'translate_es', 'meeting', 'prompt'

        self.buffer: list[np.ndarray] = []
        self.has_spoken = False
        self.silence_start_time: float | None = None
        self.no_speech_start_time: float | None = None
        self.recording_start_time: float = 0.0
        self._last_wf_time: float = 0.0

        self._noise_tracker = NoiseFloorTracker()
        self.porteiro_silero = PorteiroSilero(sample_rate=self.actual_sample_rate)
        self.last_status_msg = ""
        self._current_callback: Callable | None = None
        # Troca de microfone pedida durante uma gravação: aplicada quando ela termina, para
        # não misturar duas taxas de amostragem no mesmo self.buffer.
        self._troca_pendente = False


    @staticmethod
    def _fechar_stream(stream) -> None:
        """Para e fecha um stream. SEMPRE fora de self.lock.

        Pa_StopStream espera o callback em andamento terminar, e o callback precisa de
        self.lock para gravar o bloco: parar segurando o lock trava os dois para sempre
        (reproduzido com microfone WASAPI; no MME, 2 s de congelamento).
        """
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: PortAudio/sounddevice e montagem de buffer
            print(f"[AudioManager] erro ao fechar stream: {e!r}", file=sys.stderr)

    @property
    def noise_samples(self) -> list[float]:
        return self._noise_tracker.noise_samples

    @property
    def ambient_noise_floor(self) -> float:
        return self._noise_tracker.ambient_noise_floor

    @ambient_noise_floor.setter
    def ambient_noise_floor(self, val: float) -> None:
        self._noise_tracker.ambient_noise_floor = val

    def set_system_device(self, device_index: int | None) -> None:
        """Define o dispositivo de captura de áudio do sistema para chamadas/reuniões."""
        with self.lock:
            self.system_device_index = device_index

    def set_gain_boost(self, gain: float) -> None:
        """Ajusta o ganho de software do microfone (Modo Sussurro)."""
        with self.lock:
            self.gain_boost = max(0.5, min(gain, 4.0))

    def set_whisper_mode(self, enabled: bool, base_gain: float = 1.0) -> None:
        """Ativa ou desativa o Modo Sussurro (ganho digital de 3.0x e sensibilidade apurada).

        `base_gain` é o ganho do slider, que volta a valer ao desligar o modo. Sem ele, todo
        "Salvar" dos Ajustes (que envia MIC_GAIN e depois WHISPER_MODE) zerava o ganho em 1.0.
        """
        with self.lock:
            self.whisper_mode = enabled
            self.gain_boost = 3.0 if enabled else max(0.5, min(base_gain, 4.0))


    @staticmethod
    def get_input_devices() -> list[tuple[int, str]]:
        """Lista todos os dispositivos de entrada de áudio (microfones) válidos."""
        return get_input_devices(query_fn=sd.query_devices)

    def set_device(self, device_index: int | None) -> None:
        """Altera o microfone ativo e reinicia o stream de áudio se estiver ativo."""
        with self.lock:
            if device_index == self.device_index:
                # O "Salvar" dos Ajustes sempre reenvia AUDIO_DEVICE: não reiniciar à toa.
                return
            self.device_index = device_index
            self.porteiro_silero.reset(self.actual_sample_rate)
            if self.is_recording:
                self._troca_pendente = True
                return
            antigo, self.stream = self.stream, None
        self._fechar_stream(antigo)

        if self._current_callback and self.is_awake:
            self.ensure_stream(self._current_callback)

    def _aplicar_troca_pendente(self) -> None:
        """Reabre o microfone no device escolhido durante a gravação que acabou de terminar."""
        with self.lock:
            if not self._troca_pendente:
                return
            self._troca_pendente = False
            antigo, self.stream = self.stream, None
        self._fechar_stream(antigo)
        if self._current_callback and self.is_awake:
            self.ensure_stream(self._current_callback)


    compute_rms = staticmethod(compute_rms)



    def _create_input_stream(self, callback: Callable) -> sd.InputStream:
        """Cria o InputStream do microfone, começando por sample_rate e caindo para a taxa nativa do dispositivo."""
        taxa_anterior = self.actual_sample_rate
        aberturas_anterior = self.aberturas_do_microfone

        def _preparar_antes_do_start(sr_tentada: int) -> None:
            self.actual_sample_rate = sr_tentada
            self.aberturas_do_microfone = aberturas_anterior + 1
            self.porteiro_silero.reset(sr_tentada)

        try:
            stream, sr = negociar_stream(
                self.device_index, callback, self.channels, self.sample_rate, _preparar_antes_do_start
            )
        except Exception:
            self.actual_sample_rate = taxa_anterior
            self.aberturas_do_microfone = aberturas_anterior
            raise
        self.actual_sample_rate = sr
        self.aberturas_do_microfone = aberturas_anterior + 1
        return stream











    def ensure_stream(self, callback: Callable) -> bool:
        """Garante que o InputStream do microfone esteja ativo. Devolve se ficou ativo.

        Antes não devolvia nada e a falha só ia para o stderr: quem iniciava a gravação
        seguia sem microfone, com a pílula dizendo "ouvindo" e nada sendo gravado.
        """
        if not self.is_awake:
            return False

        self._current_callback = callback
        with self.lock:
            try:
                if self.stream is None:
                    self.stream = self._create_input_stream(callback)
                elif not self.stream.active:
                    aberturas_anterior = self.aberturas_do_microfone
                    try:
                        self.aberturas_do_microfone = aberturas_anterior + 1
                        self.stream.start()
                        self.aberturas_do_microfone = aberturas_anterior + 1
                    except Exception:  # noqa: BLE001 — fronteira defensiva: reabertura de stream PortAudio
                        try:
                            self.aberturas_do_microfone = aberturas_anterior
                            self.stream.close()
                        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: close de stream inativo PortAudio
                            pass
                        # Se a reabertura abaixo falhar, self.stream não pode continuar
                        # apontando para o stream fechado como se houvesse microfone.
                        self.stream = None
                        self.stream = self._create_input_stream(callback)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: ensure_stream PortAudio/sounddevice
                print(f"Aviso ao inicializar microfone: {e}", file=sys.stderr)
            return self.stream is not None and bool(self.stream.active)

    def pause_stream(self) -> None:
        """Pausa o stream de áudio durante o repouso para economizar CPU e energia."""
        with self.lock:
            stream = self.stream
        # stop() fora do lock: ele espera o callback, que precisa do lock (ver _fechar_stream).
        try:
            if stream and stream.active:
                stream.stop()
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: PortAudio/sounddevice e montagem de buffer
            print(f"[AudioManager] erro ao pausar stream: {e!r}", file=sys.stderr)

    def start_recording(self, mode: str = "transcribe") -> bool:
        """Inicia uma sessão de gravação. Devolve False se já há gravação ou processamento,
        ou se não há de onde gravar: sem microfone aberto, só a reunião com áudio do sistema
        segue, e só se o áudio do sistema abrir.

        A checagem e a reserva (`is_recording = True`) acontecem no MESMO trecho sob o lock,
        antes de qualquer I/O. Antes, um segundo início (atalho de transformar no meio de uma
        reunião, wake word em cima de gravação por atalho) zerava o buffer em andamento.
        """
        with self.lock:
            if self.is_recording or self.is_processing or not self.is_awake:
                return False
            # Sem stream ativo nenhum bloco chega: gravar assim era a gravação fantasma, com
            # a pílula em "ouvindo" e o buffer vazio até a pessoa desistir. A exceção é a
            # reunião com áudio do sistema, que grava o lado de lá da chamada sozinha (o ramo
            # "só o áudio do sistema" do stop_recording existe para isso).
            sem_microfone = self.stream is None or not self.stream.active
            if sem_microfone and not (mode == "meeting" and self.system_device_index is not None):
                return False
            self.recording_mode = mode
            self.buffer = []
            self.system_buffer = []
            
            self.has_spoken = False
            self.silence_start_time = None
            self.no_speech_start_time = time.time()
            self.recording_start_time = time.time()
            self._last_wf_time = 0.0
            self._noise_tracker.reset()
            self.porteiro_silero.reset(self.actual_sample_rate)
            self.last_status_msg = ""
            self.is_recording = True
            self.is_stopping = False

        if mode == "meeting" and self.system_device_index is not None:
            def _sys_cb(in_data, frames, time_info, status):
                mono = np.mean(in_data, axis=1, keepdims=True) if in_data.shape[1] > 1 else in_data
                with self.lock:
                    if self.is_recording:
                        self.system_buffer.append(mono.copy())

            # Negociação fora do lock: abrir um device WASAPI leva tempo e o callback do
            # microfone precisa do lock nesse meio-tempo. Mono primeiro; o loopback (Mixagem
            # estéreo, o alto-falante via WASAPI) costuma só abrir com os dois canais dele, e
            # recusado em mono a reunião saía sem o lado de lá. O _sys_cb mistura para mono.
            stream, taxa, erro = None, None, None
            for canais in (1, 2):
                try:
                    stream, taxa = negociar_stream(
                        self.system_device_index, _sys_cb, canais, self.actual_sample_rate
                    )
                    break
                except Exception as e:  # noqa: BLE001 — fronteira defensiva: negociação de canais WASAPI loopback
                    erro = e
            if stream is None:
                print(f"[AudioManager] áudio do sistema indisponível, gravando só o microfone: {erro!r}",
                      file=sys.stderr)

            with self.lock:
                # O "parar" pode ter chegado durante a negociação: o stream não tem mais dono.
                valido = self.is_recording and self.recording_mode == "meeting"
                if valido:
                    self.system_stream, self.system_actual_sample_rate = stream, taxa
                    if sem_microfone and stream is None:
                        # Nem microfone nem áudio do sistema: não há o que gravar.
                        self.is_recording = False
                        return False
            if not valido:
                self._fechar_stream(stream)

        return True

    def update_noise_floor(self, volume: float, duracao_s: float | None = None) -> None:
        """Soma um quadro de `duracao_s` segundos à estimativa do piso de ruído e ao nível de voz
        suavizado (ver NoiseFloorTracker). O piso segue a gravação inteira, não só o começo."""
        with self.lock:
            self._noise_tracker.update(volume, duracao_s)

    @property
    def nivel_de_voz(self) -> float:
        """O nível de voz suavizado (mediana dos últimos ~200 ms), que decide fala e silêncio."""
        with self.lock:
            return self._noise_tracker.nivel

    @property
    def calibrando_ruido(self) -> bool:
        """O começo da gravação (~0,65 s) só mede o ambiente: nada vira fala nem silêncio."""
        with self.lock:
            return self._noise_tracker.calibrando

    def houve_fala_acima(self, limiar: float) -> bool:
        """O nível desta gravação já passou de `limiar` (a fala que veio antes do piso conhecido)."""
        with self.lock:
            return self._noise_tracker.houve_fala_acima(limiar)

    def carregar_silero_em_background(self) -> threading.Thread:
        """Carrega o modelo Silero VAD em thread de fundo na partida."""
        return self.porteiro_silero.carregar_em_background()

    def observar_silero(self, indata: np.ndarray, duracao_s: float | None = None) -> bool:
        """Alimenta o porteiro Silero com `indata` cru (antes do ganho) e devolve se há fala confirmada."""
        with self.lock:
            sr = getattr(self, "actual_sample_rate", self.sample_rate) or self.sample_rate
            nivel = self._noise_tracker.nivel
            inicio_ignorado = self._noise_tracker.inicio_ignorado_s
        if self.porteiro_silero.sample_rate != sr:
            self.porteiro_silero.reset(sr)
        return self.porteiro_silero.observar_bloco(
            indata,
            duracao_s=duracao_s,
            nivel_suave=nivel,
            inicio_ignorado_s=inicio_ignorado,
        )

    def houve_fala_confirmada_acima(self, limiar: float) -> bool:
        """Indica se houve fala confirmada pelo Silero acima de `limiar` durante a calibração."""
        return self.porteiro_silero.houve_fala_confirmada_acima(limiar)

    def get_adaptive_thresholds(self, base_speech_th: float, base_silence_th: float) -> tuple[float, float]:
        """
        Calcula os limiares dinâmicos adaptados ao nível real de ruído de fundo do ambiente.
        Evita cortes falsos ou travamento do silêncio em locais com ar-condicionado ou teclados.
        """
        with self.lock:
            is_whisper = self.whisper_mode
            return self._noise_tracker.get_adaptive_thresholds(
                base_speech_th, base_silence_th, is_whisper=is_whisper
            )

    def append_audio(self, indata: np.ndarray) -> None:
        """Acrescenta um bloco de áudio ao buffer protegido por lock com ganho digital (Modo Sussurro)."""
        with self.lock:
            if self.is_recording:
                if self.gain_boost != 1.0:
                    boosted = indata * self.gain_boost
                    np.clip(boosted, -1.0, 1.0, out=boosted)
                    self.buffer.append(boosted)
                else:
                    self.buffer.append(indata.copy())

    def stop_recording(self) -> tuple[np.ndarray, str] | None:
        """Finaliza a gravação e retorna os dados brutos concatenados e o modo.

        O áudio sai na taxa em que foi GRAVADO. Quem precisa dela (para gerar o WAV) usa
        stop_recording_com_taxa: uma troca de microfone adiada é aplicada aqui dentro e muda
        self.actual_sample_rate antes de o chamador conseguir lê-la.
        """
        resultado = self.stop_recording_com_taxa()
        if resultado is None:
            return None
        audio, modo, _taxa = resultado
        return audio, modo

    def stop_recording_com_taxa(self) -> tuple[np.ndarray, str, int] | None:
        """Como stop_recording, devolvendo também a taxa das amostras: (áudio, modo, taxa)."""
        with self.lock:
            if not self.is_recording:
                self.is_stopping = False
                return None
            self.is_recording = False
            self.is_stopping = False
            raw_buffer = list(self.buffer)
            raw_sys_buffer = list(self.system_buffer)
            current_mode = self.recording_mode
            self.buffer = []
            self.system_buffer = []
            sys_stream, self.system_stream = self.system_stream, None
            # Capturadas AGORA: _aplicar_troca_pendente abaixo reabre o microfone e
            # _create_input_stream reescreve actual_sample_rate com a taxa do device novo.
            taxa_mic = self.actual_sample_rate
            taxa_sistema = self.system_actual_sample_rate or taxa_mic

        self._fechar_stream(sys_stream)
        self._aplicar_troca_pendente()

        tem_sistema = current_mode == "meeting" and bool(raw_sys_buffer)
        if not raw_buffer and not tem_sistema:
            return None

        try:
            # Invariante desta função: o que ela devolve está SEMPRE em taxa_mic, a taxa
            # em que o microfone gravou esta sessão.
            if not raw_buffer:
                # Só o áudio do sistema tem conteúdo. Antes a gravação inteira era
                # descartada aqui, perdendo a reunião de quem ficou no mudo o tempo todo.
                sys_completo = np.concatenate(raw_sys_buffer, axis=0)
                return reamostrar(sys_completo, taxa_sistema, taxa_mic), current_mode, taxa_mic

            audio_completo = np.concatenate(raw_buffer, axis=0)

            # Mixagem opcional do microfone com áudio do sistema (outros participantes do Meet/Teams)
            if tem_sistema:
                try:
                    sys_completo = np.concatenate(raw_sys_buffer, axis=0)
                    # Igualar as taxas antes de somar. Somar amostra a amostra com taxas
                    # diferentes juntava duas linhas do tempo em escalas distintas sem
                    # levantar exceção: a trilha do sistema saía acelerada e cortada.
                    sys_completo = reamostrar(sys_completo, taxa_sistema, taxa_mic)
                    # Preenche com silêncio até a trilha mais longa, em vez de cortar na
                    # mais curta. As duas streams não abrem nem fecham no mesmo instante,
                    # então truncar pelo menor descartava a cauda da outra: quem falasse
                    # depois que a captura do sistema parasse sumia da ata.
                    n_amostras = max(len(audio_completo), len(sys_completo))
                    if n_amostras > 0:
                        m_mic = audio_completo
                        m_sys = sys_completo
                        if m_mic.ndim == 2 and m_sys.ndim == 1:
                            m_sys = np.expand_dims(m_sys, axis=1)
                        elif m_mic.ndim == 1 and m_sys.ndim == 2:
                            m_mic = np.expand_dims(m_mic, axis=1)
                        m_mic = preencher(m_mic, n_amostras)
                        m_sys = preencher(m_sys, n_amostras)
                        mix = m_mic + m_sys
                        max_abs = np.max(np.abs(mix))
                        if max_abs > 1.0:
                            mix = mix / max_abs
                        audio_completo = mix
                except Exception as mix_err:  # noqa: BLE001 — fronteira defensiva: mixagem de faixas de reunião
                    print(f"[AudioManager] Aviso ao mixar faixas de reunião: {mix_err}", file=sys.stderr)

            return audio_completo, current_mode, taxa_mic
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: PortAudio/sounddevice e montagem de buffer
            print(f"[AudioManager] falha ao montar a gravação: {e!r}", file=sys.stderr)
            return None

    def cancel_recording(self) -> bool:
        """Cancela a gravação descartando qualquer áudio capturado. Devolve se havia gravação.

        Sem gravação não mexe em nada: o corte por 7 s sem fala chega numa thread, e a pessoa
        pode ter parado pelo atalho antes dela.
        """
        with self.lock:
            if not self.is_recording:
                return False
            self.is_recording = False
            self.is_stopping = False
            self.buffer = []
            self.system_buffer = []
            sys_stream, self.system_stream = self.system_stream, None

        self._fechar_stream(sys_stream)
        self._aplicar_troca_pendente()
        return True

    def convert_to_wav(self, audio_data: np.ndarray, sample_rate: int | None = None) -> io.BytesIO:
        """Converte a matriz numpy de PCM para um buffer WAV em memória.

        `sample_rate` serve ao áudio que não veio deste gravador — arquivo importado,
        WAV relido do disco. Sem ele o header herdava a taxa do microfone e passava a
        mentir sobre as amostras que acompanha.
        """
        sr = sample_rate or getattr(self, "actual_sample_rate", self.sample_rate)
        return convert_to_wav(audio_data, sample_rate=sr)

    def split_audio_into_chunks(self, audio_data: np.ndarray, chunk_seconds: int = 600,
                                sample_rate: int | None = None) -> list[io.BytesIO]:
        """
        Divide uma gravação de áudio em múltiplos buffers WAV caso exceda chunk_seconds (padrão: 10 minutos).
        Garante que reuniões de 1h+ sejam enviadas à Groq sem estourar o limite de 25MB da API.
        """
        sr = sample_rate or getattr(self, "actual_sample_rate", self.sample_rate)
        return split_audio_into_chunks(audio_data, chunk_seconds=chunk_seconds, sample_rate=sr)

    def close(self) -> None:
        """Encerra e libera os recursos do microfone."""
        with self.lock:
            sys_stream, self.system_stream = self.system_stream, None
            mic_stream, self.stream = self.stream, None
        # Fora do lock: fechar durante uma reunião travava o shutdown antes do os._exit.
        self._fechar_stream(sys_stream)
        self._fechar_stream(mic_stream)
