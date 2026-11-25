"""
Willy 🎙️ - Copiloto de Voz Ultraleve com Whisper Large v3 e IA da Groq.
Ponto de entrada principal da aplicação.
"""

import os
import sys
import threading
import time

import keyboard
import numpy as np


# Garante compatibilidade total quando executado via pythonw
class SafeStream:
    def write(self, text):
        pass
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = SafeStream()
elif sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de inicialização/desligamento
        pass

if sys.stderr is None:
    sys.stderr = SafeStream()
elif sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de inicialização/desligamento
        pass

import ctypes
from ctypes import wintypes

from core import (
    BASE_DIR,
    FLAG_SHOW_DASHBOARD,
    USER_DATA_DIR,
    VOCAB_FILE,
    ActionManager,
    AudioManager,
    AutoStartManager,
    ConfigManager,
    ContextCategory,
    ContextManager,
    GroqService,
    SingleInstanceManager,
    SnippetManager,
    SoundManager,
    TTSManager,
    Win32HotKeyManager,
)
from core.audio import negociar_stream
from core.audio_processing.dsp import (
    TAXA_WHISPER,
    condicionar_para_whisper,
    para_taxa_whisper,
)
from core.audio_processing.vad import PisoDeEscuta, compute_rms
from core.config import cofre_do_sistema, credenciais_do_willy, criar_env_do_template
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.system.injector import default_injector
from ui.dashboard import WillyDashboard
from ui.overlays import FloatingPill, HistorySpotlight, LiveTeleprompter, TrayManager
from ui.theme import (
    FLUTUANTE_AMARELO,
    FLUTUANTE_CIANO,
    FLUTUANTE_LARANJA,
    FLUTUANTE_LILAS,
    FLUTUANTE_ROXO,
    FLUTUANTE_TEXTO,
    FLUTUANTE_VERDE,
)


def _redirecionar_log_debug() -> None:
    """Em modo windowed (sem console), redireciona saídas para arquivo de log em AppData."""
    if isinstance(sys.stdout, SafeStream) or sys.stdout is None:
        try:
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            debug_log = os.path.join(USER_DATA_DIR, "willy_debug.log")
            log_f = open(debug_log, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — stream global de stdout/stderr do processo
            sys.stdout = log_f
            sys.stderr = log_f
            print(f"\n--- [Willy Iniciado: {time.strftime('%Y-%m-%d %H:%M:%S')}] ---")
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de inicialização/worker
            err = getattr(sys, "__stderr__", None)
            if err is not None:
                try:
                    err.write(f"[Willy] Falha ao abrir willy_debug.log: {e!r}\n")
                except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de fallback/winsound
                    pass


# Instâncias dos Gerenciadores (sem tocar disco ou cofre no import: ver inicializar_ambiente_partida)
single_instance = SingleInstanceManager()
config_mgr = ConfigManager(cofre=None)
sound_mgr = SoundManager(is_silent_func=lambda: config_mgr.silent_mode)
groq_service = GroqService(
    api_key=config_mgr.groq_api_key,
    model=config_mgr.model,
    translate_model=config_mgr.translate_model,
    llm_model=config_mgr.llm_model
)
audio_mgr = AudioManager(
    device_index=config_mgr.audio_device,
    system_device_index=config_mgr.system_audio_device,
    gain_boost=config_mgr.mic_gain,
    whisper_mode=config_mgr.whisper_mode,
)
hotkey_mgr = Win32HotKeyManager()
snippet_mgr = SnippetManager()
tts_mgr = TTSManager()


def inicializar_ambiente_partida() -> None:
    """Inicializa arquivos de dados, log e cofre do sistema na partida (após a trava de instância única)."""
    global config_mgr
    _redirecionar_log_debug()
    criar_env_do_template()
    config_mgr = ConfigManager(cofre=cofre_do_sistema())
    transcription_pipeline.config_mgr = config_mgr
    groq_service.set_api_key(config_mgr.groq_api_key)
    groq_service.model = config_mgr.model
    groq_service.translate_model = config_mgr.translate_model
    groq_service.set_llm_model(config_mgr.llm_model)
    audio_mgr.set_device(config_mgr.audio_device)
    audio_mgr.set_system_device(config_mgr.system_audio_device)
    audio_mgr.set_gain_boost(config_mgr.mic_gain)
    audio_mgr.set_whisper_mode(config_mgr.whisper_mode, config_mgr.mic_gain)
    audio_mgr.carregar_silero_em_background()
spotlight: HistorySpotlight | None = None
teleprompter: LiveTeleprompter | None = None
hotkey_orchestrator = None

current_app_context = ("unknown.exe", "", ContextCategory.GENERAL)
# (janela, controle com o foco do teclado) para onde vai o texto do ditado em curso (ver
# ContextManager.resolver_janela_alvo); (0, 0) sem nenhuma.
_alvo_da_gravacao: tuple[int, int] = (0, 0)

root = None
pill = None
dashboard = None
tray_mgr = None

# Controle de Wake Word "Ei Willy"
_wake_word_lock = threading.RLock()
_wake_word_buffer = []
_wake_word_processing = False
_piso_de_escuta = PisoDeEscuta()

# Fôlego extra do corte por silêncio num ditado longo: a pausa de quem pensa entre parágrafos.
_DITADO_LONGO_S = 10.0
_FOLEGO_EXTRA_S = 0.6

# O atalho temporário do Esc, ligado só durante a gravação (Win32HotKeyManager.registrar_temporario).
_ATALHO_DO_CANCELAR = "cancelar_gravacao"
# O Esc com os modificadores do atalho que começou a gravação: segurando Ctrl+Alt+P, o Esc chega
# ao Windows como Ctrl+Alt+Esc, e o Esc puro não o pega (Bloco 10).
_ATALHO_DO_CANCELAR_SEGURANDO = "cancelar_gravacao_segurando"
_VK_ESCAPE = 0x1B


def _carregar_win32_willy():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    s = ctypes.WinDLL("shell32", use_last_error=True)
    s.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    s.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
    return u, s


_user32, _shell32 = _carregar_win32_willy()

# Cópia avulsa do áudio que a Groq recusou (413, chave, bug). O que dá para reenviar fica
# na fila do pipeline (USER_DATA_DIR/failed/).
FAILED_AUDIO_PATH = os.path.join(USER_DATA_DIR, "last_failed_audio.wav")
last_injected_text = None
selected_text_for_transform = ""



import queue

_ui_queue = queue.SimpleQueue()

def iniciar_dreno_ui(root):
    def _drenar():
        while not _ui_queue.empty():
            func, args, kwargs = _ui_queue.get_nowait()
            try:
                func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de UI/flag
                import sys
                print(f"[UI Dispatch] Falha: {e}", file=sys.stderr)
        if root and getattr(root, "winfo_exists", lambda: False)():
            root.after(16, _drenar)
    if root and getattr(root, "winfo_exists", lambda: False)():
        root.after(16, _drenar)

def safe_dispatch_ui(func, *args, delay_ms: int = 0):
    """Despacha chamada para a thread do Tkinter de forma estritamente segura usando fila FIFO."""
    if delay_ms > 0:
        _ui_queue.put((lambda f=func, a=args, d=delay_ms: root.after(d, f, *a) if root and getattr(root, "winfo_exists", lambda: False)() else None, (), {}))
    else:
        _ui_queue.put((func, args, {}))


def atualizar_ui(estado: str, msg: str = "", por_cima: bool = False):
    """Despacha atualizações visuais de forma segura para a thread da interface.

    `por_cima=True` para erro ou sucesso que não encerra a gravação em curso: a pílula volta
    ao "ouvindo" em vez de sumir (ver FloatingPill.show_state).
    """
    if pill:
        safe_dispatch_ui(
            pill.show_state,
            estado,
            msg,
            audio_mgr.recording_mode,
            config_mgr.refine_prompt,
            por_cima,
        )


def _pipeline_on_caption(texto: str):
    if teleprompter and getattr(teleprompter, "is_visible", False):
        safe_dispatch_ui(teleprompter.adicionar_legenda, texto)


def _pipeline_on_pill_text(texto: str, colado: bool):
    global last_injected_text
    if colado:
        last_injected_text = texto
    if pill:
        safe_dispatch_ui(pill.set_last_text, texto)


def _pipeline_on_sync():
    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_dados)


transcription_pipeline = TranscriptionPipeline(
    groq_service=groq_service,
    config_mgr=config_mgr,
    audio_mgr=audio_mgr,
    injector=default_injector,
    sound_mgr=sound_mgr,
    snippet_mgr=snippet_mgr,
    tts_mgr=tts_mgr,
    ui_notifier=atualizar_ui,
    ui_dispatcher=safe_dispatch_ui,
    on_caption=_pipeline_on_caption,
    on_pill_text=_pipeline_on_pill_text,
    on_success_sync=_pipeline_on_sync,
    failed_audio_path=FAILED_AUDIO_PATH,
    user_data_dir=USER_DATA_DIR,
)


def _trigger_wake_word_check():
    """Aciona verificação assíncrona da palavra de ativação 'Ei Willy' em background."""
    global _wake_word_processing
    ww_lock = globals().get("_wake_word_lock")
    if ww_lock is not None:
        with ww_lock:
            if _wake_word_processing or not _wake_word_buffer:
                return
            _wake_word_processing = True
            chunks = list(_wake_word_buffer)
            _wake_word_buffer.clear()
    else:
        if _wake_word_processing or not _wake_word_buffer:
            return
        _wake_word_processing = True
        chunks = list(_wake_word_buffer)
        _wake_word_buffer.clear()
    # A taxa destes blocos é a do microfone agora, não a de quando o worker rodar.
    taxa = getattr(audio_mgr, "actual_sample_rate", audio_mgr.sample_rate)

    def _worker():
        global _wake_word_processing
        try:
            import numpy as np
            # A 16 kHz, como o ditado: a 48 kHz o trecho ia três vezes maior para a Groq.
            audio_data = para_taxa_whisper(np.concatenate(chunks, axis=0), taxa)
            wav_bytes = audio_mgr.convert_to_wav(audio_data, sample_rate=TAXA_WHISPER)
            texto = groq_service.transcribe(wav_bytes, prompt="Ei Willy, Willy, opa Willy", temperature=0.0)
            # A transcrição leva um tempo: se nele a pessoa começou um ditado pelo atalho, pôs o
            # Willy em repouso ou desligou a palavra, o "detectado" com som tocava por cima.
            livre = (config_mgr.wake_word_enabled and audio_mgr.is_awake
                     and not audio_mgr.is_recording and not audio_mgr.is_processing)
            if livre and texto and any(kw in texto.lower() for kw in ("willy", "uili", "wili", "oili", "ei willy")):
                sound_mgr.sound_start()
                atualizar_ui("listening", "Ei Willy detectado! 🗣️")
                safe_dispatch_ui(lambda: iniciar_gravacao(modo="transcribe"), delay_ms=100)
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de inicialização/worker
            import sys as _sys
            err_stream = getattr(globals().get("sys", _sys), "stderr", _sys.stderr)
            print(f"[WakeWord] Falha na checagem de palavra de ativação: {e!r}", file=err_stream)
        finally:
            if ww_lock is not None:
                with ww_lock:
                    _wake_word_processing = False
            else:
                _wake_word_processing = False

    threading.Thread(target=_worker, daemon=True).start()


def callback_audio(indata, frames, time_info, status):
    """Callback de tempo real executado pela thread do sounddevice."""
    class _SemTrava:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    trava = getattr(audio_mgr, "lock", None) or _SemTrava()
    ww_lock = globals().get("_wake_word_lock") or _SemTrava()

    if not audio_mgr.is_recording:
        with ww_lock:
            processando_ww = _wake_word_processing
        if config_mgr.wake_word_enabled and audio_mgr.is_awake and not audio_mgr.is_processing and not processando_ww:
            volume = audio_mgr.compute_rms(indata)
            # Os dois ramos abaixo leem cur_sr: atribuir dentro do `if` deixava o `elif`
            # com a variavel nao ligada e derrubava a stream do sounddevice.
            cur_sr = getattr(audio_mgr, "actual_sample_rate", audio_mgr.sample_rate)
            # Acima do ruído medido na escuta, e não só do limiar fixo x 1,3 (0,0117): na C920
            # (ruído 0,032) todo bloco passava, e 1,8 s de ruído iam à Groq ~33 vezes por minuto.
            # Cada abertura do microfone (o app subindo, outro microfone nos Ajustes) recomeça a medida.
            aberturas = getattr(audio_mgr, "aberturas_do_microfone", 0)
            with ww_lock:
                if aberturas != _piso_de_escuta.abertura:
                    _piso_de_escuta.reset(aberturas)
                _piso_de_escuta.update(volume, len(indata) / cur_sr if cur_sr else None)
                if _piso_de_escuta.calibrando:
                    return
                speech_th = _piso_de_escuta.limiar_de_fala(config_mgr.speech_threshold)
                acionar_ww = False
                if volume > speech_th:
                    _wake_word_buffer.append(indata.copy())
                    if len(_wake_word_buffer) >= int(cur_sr / len(indata) * 1.8):
                        acionar_ww = True
                elif len(_wake_word_buffer) >= int(cur_sr / len(indata) * 0.5):
                    acionar_ww = True
                elif len(_wake_word_buffer) > 0:
                    _wake_word_buffer.clear()
            if acionar_ww:
                _trigger_wake_word_check()
        return

    if not audio_mgr.is_awake:
        return

    audio_mgr.append_audio(indata)
    volume = audio_mgr.compute_rms(indata)
    taxa = getattr(audio_mgr, "actual_sample_rate", audio_mgr.sample_rate)
    audio_mgr.update_noise_floor(volume, len(indata) / taxa if taxa else None)

    agora_wf = time.time()
    atualizar_wf = False
    if pill:
        with trava:
            if agora_wf - getattr(audio_mgr, "_last_wf_time", 0.0) >= 0.033:
                audio_mgr._last_wf_time = agora_wf
                atualizar_wf = True
    if atualizar_wf:
        # Com o piso de ruído: na C920, as barras ficavam altas e vermelhas em silêncio.
        safe_dispatch_ui(
            pill.update_waveform,
            volume,
            audio_mgr.is_recording,
            audio_mgr.recording_mode,
            audio_mgr.ambient_noise_floor,
        )

    if config_mgr.auto_silence and audio_mgr.recording_mode != "meeting":
        agora = time.time()
        speech_th, silence_th = audio_mgr.get_adaptive_thresholds(
            config_mgr.speech_threshold, config_mgr.silence_threshold
        )
        # Fala e silêncio pelo nível suavizado (~200 ms), não pelo quadro: um quadro solto do
        # ruído zerava a contagem do silêncio. Na calibração (o começo, ~0,65 s), o ruído sozinho
        # não vira fala: na C920 do dono, o 1º quadro já passava do limiar fixo e travava
        # has_spoken, e o ditado nunca terminava sozinho. Nela só vale o cancelamento por 7 s sem
        # fala: num microfone mudo a calibração não acabava, e a gravação ficava aberta. E a fala
        # que veio antes de o piso ser conhecido (logo no 1º quadro) conta quando ele é, senão os
        # 7 s sem fala cancelavam o ditado.
        nivel = audio_mgr.nivel_de_voz
        decide = not audio_mgr.calibrando_ruido
        usar_silero = bool(getattr(config_mgr, "silero_vad", True))
        if usar_silero and hasattr(audio_mgr, "observar_silero"):
            voz_confirmada = audio_mgr.observar_silero(indata, len(indata) / taxa if taxa else None)
            acima_confirmada = audio_mgr.houve_fala_confirmada_acima(speech_th)
        else:
            voz_confirmada = True
            acima_confirmada = True
        fala_acima = bool(
            decide
            and nivel <= speech_th
            and not audio_mgr.has_spoken
            and audio_mgr.houve_fala_acima(speech_th)
            and acima_confirmada
        )
        disparar_parar = False
        disparar_cancelar = False
        despacho_status = None
        with trava:
            if (
                decide
                and (
                    nivel > speech_th
                    or (nivel > silence_th and audio_mgr.has_spoken)
                    or (not audio_mgr.has_spoken and fala_acima)
                )
                and (voz_confirmada or (not audio_mgr.has_spoken and fala_acima))
            ):
                audio_mgr.has_spoken = True
                audio_mgr.silence_start_time = None
                if audio_mgr.recording_mode == "translate":
                    msg_ouvindo = "Willy ouvindo (PT-BR ➔ Inglês)..."
                elif audio_mgr.recording_mode == "translate_es":
                    msg_ouvindo = "Willy ouvindo (PT-BR ➔ Espanhol)..."
                elif audio_mgr.recording_mode == "prompt":
                    msg_ouvindo = "🎯 Arquiteto de Prompts... (fale a tarefa do agente)"
                elif audio_mgr.recording_mode == "send":
                    msg_ouvindo = "🚀 Ditar e Enviar... (fale sua mensagem)"
                elif audio_mgr.recording_mode == "transform":
                    msg_ouvindo = "🪄 Willy: Fale o que fazer com a seleção..."
                else:
                    msg_ouvindo = "Willy ouvindo... (fale seu prompt)"
                if audio_mgr.last_status_msg != msg_ouvindo:
                    audio_mgr.last_status_msg = msg_ouvindo
                    if pill:
                        despacho_status = (msg_ouvindo, FLUTUANTE_TEXTO)

            elif decide and audio_mgr.has_spoken:
                # Num ditado longo, fôlego extra: quem pensa entre um parágrafo e outro pausa mais que
                # os 2,2 s, e o ditado era enviado no meio do raciocínio. A contagem da pílula usa o
                # mesmo tempo.
                silencio_efetivo = config_mgr.silence_seconds
                if agora - getattr(audio_mgr, "recording_start_time", agora) > _DITADO_LONGO_S:
                    silencio_efetivo += _FOLEGO_EXTRA_S
                if audio_mgr.silence_start_time is None:
                    audio_mgr.silence_start_time = agora
                else:
                    elapsed = agora - audio_mgr.silence_start_time
                    if elapsed >= silencio_efetivo:
                        if not getattr(audio_mgr, "is_stopping", False):
                            audio_mgr.is_stopping = True
                            disparar_parar = True
                    elif elapsed > 1.2 and pill:
                        restante = max(0.0, silencio_efetivo - elapsed)
                        msg_countdown = f"Pausa... Willy enviando em {restante:.1f}s"
                        if audio_mgr.last_status_msg != msg_countdown:
                            audio_mgr.last_status_msg = msg_countdown
                            despacho_status = (msg_countdown, FLUTUANTE_AMARELO)

            elif (not audio_mgr.has_spoken
                  and audio_mgr.no_speech_start_time
                  and (agora - audio_mgr.no_speech_start_time >= 7.0)
                  and not getattr(audio_mgr, "is_stopping", False)):
                audio_mgr.is_stopping = True
                disparar_cancelar = True

        if despacho_status is not None:
            safe_dispatch_ui(pill.update_status_text, despacho_status[0], despacho_status[1])
        if disparar_parar:
            threading.Thread(target=parar_gravacao, daemon=True).start()
        if disparar_cancelar:
            threading.Thread(target=cancelar_gravacao, daemon=True).start()
    elif not config_mgr.auto_silence and audio_mgr.recording_mode != "meeting":
        # Modo Manual (Pressione para Parar / Toggle):
        # Permite pausas longas e reflexivas sem qualquer corte por silêncio
        despacho_manual = None
        with trava:
            dur = int(time.time() - getattr(audio_mgr, "recording_start_time", time.time()))
            mins = dur // 60
            secs = dur % 60
            if audio_mgr.recording_mode == "translate":
                msg_manual = f"🌐 Tradução Manual... {mins:02d}:{secs:02d} (Pressione atalho p/ enviar)"
                cor_manual = FLUTUANTE_LILAS
            elif audio_mgr.recording_mode == "translate_es":
                msg_manual = f"🌐 Tradução ES Manual... {mins:02d}:{secs:02d} (Pressione atalho p/ enviar)"
                cor_manual = FLUTUANTE_LILAS
            elif audio_mgr.recording_mode == "prompt":
                msg_manual = f"🎯 Prompt Manual... {mins:02d}:{secs:02d} (Pressione atalho p/ enviar)"
                cor_manual = FLUTUANTE_ROXO
            elif audio_mgr.recording_mode == "send":
                msg_manual = f"🚀 Ditar e Enviar Manual... {mins:02d}:{secs:02d} (Pressione atalho p/ enviar)"
                cor_manual = FLUTUANTE_VERDE
            elif audio_mgr.recording_mode == "transform":
                msg_manual = f"🪄 Transformar Manual... {mins:02d}:{secs:02d} (Pressione atalho p/ enviar)"
                cor_manual = FLUTUANTE_LILAS
            else:
                msg_manual = f"🎙️ Ditado Manual... {mins:02d}:{secs:02d} (Pressione atalho p/ enviar)"
                cor_manual = FLUTUANTE_CIANO

            if audio_mgr.last_status_msg != msg_manual:
                audio_mgr.last_status_msg = msg_manual
                if pill:
                    despacho_manual = (msg_manual, cor_manual)
        if despacho_manual is not None:
            safe_dispatch_ui(pill.update_status_text, despacho_manual[0], despacho_manual[1])
    elif audio_mgr.recording_mode == "meeting":
        # No modo reunião, atualiza o status com a duração da gravação
        despacho_meet = None
        with trava:
            start_t = getattr(audio_mgr, "recording_start_time", 0) or getattr(audio_mgr, "speech_start_time", 0) or time.time()
            dur = int(time.time() - start_t)
            mins = dur // 60
            secs = dur % 60
            msg_meet = f"🎙️ Gravando Reunião... {mins:02d}:{secs:02d} (Pressione atalho para finalizar)"
            if audio_mgr.last_status_msg != msg_meet:
                audio_mgr.last_status_msg = msg_meet
                if pill:
                    despacho_meet = msg_meet
        if despacho_meet is not None:
            safe_dispatch_ui(pill.update_status_text, despacho_meet, FLUTUANTE_LARANJA)


def reenviar_ultimo_audio():
    """Reenvia o áudio mais recente da fila; o pipeline o apaga só se o texto for entregue."""
    item = transcription_pipeline.fila.mais_recente()
    audio_bytes = None
    if item:
        try:
            with open(item[0], "rb") as f:
                audio_bytes = f.read()
        except OSError:
            pass

    if not audio_bytes:
        atualizar_ui("error", "Nenhum áudio salvo para reenviar", por_cima=True)
        return

    caminho, modo = item
    # O alvo de agora, não o do ditado que falhou: a pessoa reenvia de onde está. Do menu da
    # bandeja (o Willy na frente), o app sob o cursor ou o último em que ela estava. A reunião,
    # como na gravação, não tem: a ata de 1 h leva minutos para sair, e a pessoa já está noutro lugar.
    if modo == "meeting":
        alvo = (0, 0)
    else:
        alvo = ContextManager.resolver_janela_alvo((_janela_antes_do_willy, _foco_antes_do_willy))
    threading.Thread(
        target=_executar_pipeline_transcricao,
        args=(audio_bytes, modo, True, caminho, alvo),
        daemon=True
    ).start()


def aba_inicial(cfg_mgr=None) -> str | None:
    """Escolhe a aba inicial da partida e a abre no painel, se houver painel."""
    cfg = config_mgr if cfg_mgr is None else cfg_mgr
    if cfg.precisa_onboarding():
        aba = "onboarding"
    elif not cfg.groq_api_key or cfg.groq_api_key == "sua_chave_aqui":
        aba = "settings"
    else:
        return None
    if dashboard:
        dashboard.mudar_aba(aba)
    return aba


def _abrir_painel_sem_chave() -> None:
    if not dashboard:
        return
    aba = "onboarding" if config_mgr.precisa_onboarding() else "settings"
    safe_dispatch_ui(lambda: (dashboard.mostrar(), dashboard.mudar_aba(aba)))


def _executar_pipeline_transcricao(wav_bytes: bytes, modo: str, is_retry: bool = False,
                                   retry_path: str | None = None,
                                   alvo: tuple[int, int] | None = None):
    """Executa o pipeline completo de transcrição, IA e digitação sobre o buffer WAV.

    `alvo`: para onde vai o texto (ver ContextManager.resolver_janela_alvo); sem ele, o da
    gravação mais recente."""
    # Sem chave, abre o guia ou os Ajustes e segue para o pipeline, que guarda o áudio na fila e avisa.
    # O return que havia aqui jogava o ditado fora.
    if (not config_mgr.groq_api_key or config_mgr.groq_api_key in ("", "sua_chave_aqui")) and dashboard:
        abrir = globals().get("_abrir_painel_sem_chave")
        if abrir:
            abrir()
        else:
            aba = "onboarding" if getattr(config_mgr, "precisa_onboarding", lambda: False)() else "settings"
            safe_dispatch_ui(lambda: (dashboard.mostrar(), dashboard.mudar_aba(aba)))

    ctx = PipelineContext(
        wav_bytes=wav_bytes,
        modo=modo,
        app_context=current_app_context,
        # O reenvio lê a seleção de agora: a guardada é a do último Ctrl+Alt+T, talvez de outro
        # pedido, e a instrução de um áudio seria aplicada ao texto de outro.
        selected_text=None if is_retry else selected_text_for_transform,
        is_retry=is_retry,
        retry_path=retry_path,
        janela_alvo=(alvo or _alvo_da_gravacao)[0],
        foco_alvo=(alvo or _alvo_da_gravacao)[1],
    )
    transcription_pipeline.process(ctx)
    # A fila pode ter ganhado ou perdido um item: o contador da bandeja acompanha.
    sincronizar_bandeja()


def processar_transcricao(audio_data, modo: str, taxa: int, piso_ruido: float = 0.0,
                          alvo: tuple[int, int] | None = None):
    """Processa o áudio capturado, converte para WAV e aciona o pipeline de transcrição.

    `taxa` é a taxa em que estas amostras foram gravadas (de stop_recording_com_taxa), e
    `piso_ruido` o piso que o corte por silêncio mediu nelas.
    """
    cur_sr = taxa
    duracao = len(audio_data) / cur_sr
    if duracao < 0.3:
        atualizar_ui("cancelled")
        return

    # O dispositivo pode ter negociado 44,1/48 kHz. Nessa taxa, um ditado de 4,6 min ou um
    # bloco de reunião de 10 min já passa dos 25 MB da Groq; a 16 kHz, não.
    audio_data = para_taxa_whisper(audio_data, cur_sr)
    # Sem o ronco grave, sem o silêncio das bordas e com a voz no nível certo: na cauda de ruído
    # da C920, o Whisper alucinava finais de vídeo em inglês e restos do prompt ("K", "Kennis, P").
    # Só silêncio sobrou: cancela sem gastar a chamada à Groq. Na reunião, só o passa-alta (ver
    # condicionar_para_whisper).
    audio_data = condicionar_para_whisper(audio_data, TAXA_WHISPER, piso_ruido, aparar=modo != "meeting")
    if len(audio_data) < 0.3 * TAXA_WHISPER:
        atualizar_ui("cancelled")
        return
    wav_bytes = audio_mgr.convert_to_wav(audio_data, sample_rate=TAXA_WHISPER)
    _executar_pipeline_transcricao(wav_bytes, modo, alvo=alvo)


def iniciar_gravacao(modo: str = "transcribe", atalho: str | None = None):
    """Inicia a gravação de áudio em modo normal ou tradução capturando o contexto da janela ativa.
    `atalho` é a combinação que começou a gravação (nenhuma no "Ei Willy")."""
    global current_app_context, _alvo_da_gravacao
    # Já gravando: sair ANTES do ensure_stream e do contexto. Com uma troca de microfone
    # pendente, ensure_stream reabriria o device novo no meio da gravação (duas taxas no
    # mesmo buffer), e o contexto do ditado em andamento seria trocado pelo da janela atual.
    if audio_mgr.is_recording or audio_mgr.is_processing or not audio_mgr.is_awake:
        return

    # Captura o aplicativo e janela em foco antes de iniciar o ditado
    current_app_context = ContextManager.get_foreground_app()
    # E para onde o texto vai: a janela e o controle em que a pessoa digitava. A pílula aparece
    # no monitor dela quando o painel do Willy ou a barra de tarefas estão na frente. A reunião não
    # tem: dura meia hora, uma hora, e a janela do começo trazida de volta no fim receberia a ata
    # no campo que tivesse o foco nela (o chat da própria reunião). A ata vai para onde o foco
    # estiver quando ela sai, como antes do Bloco 11 (a janela fixada continua valendo).
    if modo == "meeting":
        _alvo_da_gravacao = (0, 0)
    else:
        _alvo_da_gravacao = ContextManager.resolver_janela_alvo((_janela_antes_do_willy, _foco_antes_do_willy))
    if pill:
        pill.janela_alvo = _alvo_da_gravacao[0]

    # A pílula só diz "ouvindo" com o microfone aberto: antes disso, o que a pessoa fala se
    # perde. Sem microfone, o erro aparece no lugar do "ouvindo" mudo de antes. A reunião
    # com áudio do sistema é a exceção: grava o lado de lá da chamada mesmo sem microfone.
    microfone = audio_mgr.ensure_stream(callback_audio)
    reuniao_com_sistema = modo == "meeting" and audio_mgr.system_device_index is not None
    if not microfone and not reuniao_com_sistema:
        sound_mgr.sound_error()
        atualizar_ui("error", "Microfone indisponível: confira em Ajustes")
        return
    # O Esc cancela o ditado em curso. Fora da reunião: 30 min perdidos por um Esc acidental
    # custam mais que um atalho a menos. Ligado antes do start_recording: um parar que chegue
    # logo depois dele (o atalho apertado duas vezes, em outra thread) já o encontra e solta;
    # ligado depois, o pedido podia chegar depois do parar, e o Esc ficava preso sem gravação.
    cancela_com_esc = modo != "meeting"
    if cancela_com_esc:
        hotkey_mgr.registrar_temporario(_ATALHO_DO_CANCELAR, "esc", cancelar_por_esc)
        # Ctrl+Esc e Ctrl+Shift+Esc (Ctrl+Espaço e Ctrl+Shift+Enter segurados) o Windows não dá a
        # ninguém: esses o monitorar_hold pega pelo teclado.
        esc_segurando = Win32HotKeyManager.com_os_modificadores_de(atalho, "esc") if atalho else None
        if esc_segurando:
            hotkey_mgr.registrar_temporario(_ATALHO_DO_CANCELAR_SEGURANDO, esc_segurando, cancelar_por_esc)
    comecou = False
    try:
        comecou = audio_mgr.start_recording(modo)
    finally:
        # A gravação que não começou (ou cujo start levantou) não deixa o Esc preso. Uma outra que
        # começou ao mesmo tempo (o "Ei Willy" e o atalho) fica com ele.
        if cancela_com_esc and not comecou:
            _soltar_esc_sem_gravacao()
    if comecou:
        if not microfone:
            atualizar_ui("listening", "Sem microfone: só o áudio do sistema")
        elif modo == "transform":
            atualizar_ui("listening", "🪄 Willy: Fale o que fazer com o texto...")
        elif not config_mgr.auto_silence and modo != "meeting":
            atualizar_ui("listening", "🎙️ Modo Manual (Pressione atalho p/ enviar)")
        else:
            atualizar_ui("listening")
        sound_mgr.sound_start()
        return
    if not microfone:
        sound_mgr.sound_error()
        atualizar_ui("error", "Sem microfone e sem áudio do sistema")


def _soltar_esc():
    """O Esc volta para o app em foco: o Willy só o pega enquanto grava."""
    hotkey_mgr.soltar_temporario(_ATALHO_DO_CANCELAR)
    hotkey_mgr.soltar_temporario(_ATALHO_DO_CANCELAR_SEGURANDO)


def _soltar_esc_sem_gravacao():
    """Solta o Esc se nada está gravando. Depois de parar ou cancelar: um parar em outra thread
    pode encerrar a gravação que começou depois do _soltar_esc do início, e ninguém soltava o
    Esc dela (achado do juiz do Bloco 9)."""
    if not audio_mgr.is_recording:
        _soltar_esc()


def cancelar_por_esc():
    """Esc durante o ditado: descarta o áudio na hora, sem ir à Groq. Nunca a reunião, nem o
    ditado que já está sendo enviado."""
    _soltar_esc()
    trava = getattr(audio_mgr, "lock", None)
    if trava is not None:
        with trava:
            ignorar = getattr(audio_mgr, "is_stopping", False) or audio_mgr.recording_mode == "meeting"
    else:
        ignorar = getattr(audio_mgr, "is_stopping", False) or audio_mgr.recording_mode == "meeting"
    if ignorar:
        return
    cancelou = audio_mgr.cancel_recording()
    # Como no parar: a gravação seguinte, que registrou o Esc depois do _soltar_esc daqui, pode
    # ter sido a cancelada (juiz do Bloco 9, 2ª rodada).
    _soltar_esc_sem_gravacao()
    if not cancelou:
        return
    if not config_mgr.wake_word_enabled:
        audio_mgr.pause_stream()
    sound_mgr.sound_stop()
    atualizar_ui("cancelled", "Ditado cancelado (Esc)")


def parar_gravacao():
    """Finaliza a gravação e despacha para processamento assíncrono."""
    # O alvo DESTA gravação, antes de ela parar: lido depois, na thread, podia ser já o de um
    # ditado novo, começado noutro app no meio tempo (de 16 a 257 ms, conforme o tamanho).
    alvo = _alvo_da_gravacao
    _soltar_esc()
    # A taxa vem junto do áudio: se o microfone foi trocado durante a gravação, o stop
    # reabre o device novo e actual_sample_rate já não descreve estas amostras.
    resultado = audio_mgr.stop_recording_com_taxa()
    _soltar_esc_sem_gravacao()
    # Aqui, e não na thread: uma gravação nova, começada antes de ela rodar, zera o piso. Ele é
    # medido no sinal cru, e o buffer leva o ganho (o do slider, ou o 3x do sussurro): sem a
    # mesma escala, com ganho 0,5 a fala no buffer ficava abaixo dos limiares e era aparada.
    piso_ruido = audio_mgr.ambient_noise_floor * audio_mgr.gain_boost
    if not config_mgr.wake_word_enabled:
        audio_mgr.pause_stream()

    if resultado:
        audio_data, modo, taxa = resultado
        threading.Thread(target=processar_transcricao, args=(audio_data, modo, taxa, piso_ruido, alvo),
                         daemon=True).start()


def cancelar_gravacao() -> bool:
    """Cancela a gravação descartando o áudio. Devolve se havia o que cancelar.

    Roda numa thread disparada pelos 7 s sem fala. Se a pessoa parou pelo atalho antes, o som
    de erro e o "cancelado" saíam por cima do ditado sendo processado, e o microfone era
    pausado embaixo da gravação seguinte.
    """
    _soltar_esc()
    cancelou = audio_mgr.cancel_recording()
    _soltar_esc_sem_gravacao()
    if not cancelou:
        return False
    if not config_mgr.wake_word_enabled:
        audio_mgr.pause_stream()
    sound_mgr.sound_error()
    atualizar_ui("cancelled")
    return True


def monitorar_hold(combo: str):
    """Detecta se o usuário está segurando o atalho `combo` (Push-to-Talk), sem falso corte
    em toques rápidos.

    Olhava sempre a barra de espaço: com Ctrl+Alt+P ou Ctrl+Shift+Enter, segurar o P ou o
    Enter não era percebido, e o atalho funcionava só como liga e desliga.

    Segurar é o atalho inteiro: só a tecla principal aos 650 ms podia ser um espaço digitado
    depois de um toque rápido em Ctrl+Espaço, e soltá-lo cortava o ditado. E o monitor só
    encerra a gravação que ele viu começar: com toque, toque e toque, a primeira thread
    encerrava a gravação seguinte.

    O Esc apertado enquanto o atalho está seguro cancela, e soltar o atalho depois não envia
    (Bloco 10). Ele chega ao Windows com os modificadores do atalho (Ctrl+Esc com Ctrl+Espaço), que
    o Esc temporário não pega, e o Ctrl+Esc ninguém registra: o monitor lê a tecla Esc.
    """
    try:
        mods, vk = Win32HotKeyManager.parse_hotkey(combo)
    except ValueError:
        return
    modificadores = Win32HotKeyManager.teclas_dos_modificadores(mods)
    trava = getattr(audio_mgr, "lock", None)
    if trava is not None:
        with trava:
            sessao = audio_mgr.recording_start_time
    else:
        sessao = audio_mgr.recording_start_time
    passo_s = 0.025
    passos_da_espera = 26  # 650 ms

    def _apertada(tecla):
        return bool(_user32.GetAsyncKeyState(tecla) & 0x8000)

    def _mesma_gravacao():
        if trava is not None:
            with trava:
                return audio_mgr.is_recording and audio_mgr.recording_start_time == sessao
        return audio_mgr.is_recording and audio_mgr.recording_start_time == sessao

    def _cancelou_com_esc():
        """Esc apertado: cancela, e o monitor sai sem enviar. A reunião não se cancela com Esc."""
        if trava is not None:
            with trava:
                eh_reuniao = audio_mgr.recording_mode == "meeting"
        else:
            eh_reuniao = audio_mgr.recording_mode == "meeting"
        if eh_reuniao or not _apertada(_VK_ESCAPE):
            return False
        cancelar_por_esc()
        return True

    # Espera 650ms para diferenciar toque rápido (hands-free) de segurar (push-to-talk)
    for _ in range(passos_da_espera):
        time.sleep(passo_s)
        if not _mesma_gravacao() or not audio_mgr.is_awake or _cancelou_com_esc():
            return

    segurando = _apertada(vk) and all(any(_apertada(t) for t in lados) for lados in modificadores)
    if not segurando:
        return
    # Usuário está no modo Push-to-Talk: espera soltar a tecla. O Esc é lido antes da tecla: com o
    # Esc apertado e o atalho solto no mesmo passo de 25 ms, vale o cancelar.
    while _mesma_gravacao():
        if _cancelou_com_esc():
            return
        if not _apertada(vk):
            parar_gravacao()
            return
        time.sleep(passo_s)


def _pronto_para_gravar() -> bool:
    """Guarda unificada de prontidão dos atalhos de gravação (is_processing, is_awake, groq_api_key)."""
    if getattr(audio_mgr, "is_processing", False):
        atualizar_ui("error", "Aguarde o processo atual...", por_cima=True)
        return False

    if not audio_mgr.is_awake:
        sound_mgr.sound_error()
        atualizar_ui("sleeping_hint")
        return False

    chave_groq = getattr(config_mgr, "groq_api_key", "gsk_ok")
    if not chave_groq or chave_groq in ("", "sua_chave_aqui"):
        sound_mgr.sound_error()
        atualizar_ui("error", "Configure sua chave Groq")
        abrir = globals().get("_abrir_painel_sem_chave")
        if abrir:
            abrir()
        else:
            dash = globals().get("dashboard")
            despachar = globals().get("safe_dispatch_ui")
            if dash and despachar:
                aba = "onboarding" if getattr(config_mgr, "precisa_onboarding", lambda: False)() else "settings"
                despachar(lambda: (dash.mostrar(), dash.mudar_aba(aba)))
        return False

    return True


def on_voice_hotkey():
    """Acionado pelo atalho principal Ctrl + Espaço."""
    if not _pronto_para_gravar():
        return

    if not audio_mgr.is_recording:
        iniciar_gravacao("transcribe", config_mgr.hotkey)
        threading.Thread(target=monitorar_hold, args=(config_mgr.hotkey,), daemon=True).start()
    else:
        parar_gravacao()


def on_translate_hotkey():
    """Acionado pelo atalho de tradução Ctrl + Alt + Espaço."""
    if not _pronto_para_gravar():
        return

    if not audio_mgr.is_recording:
        iniciar_gravacao("translate", config_mgr.translate_hotkey)
        threading.Thread(target=monitorar_hold, args=(config_mgr.translate_hotkey,), daemon=True).start()
    else:
        parar_gravacao()


def on_translate_es_hotkey():
    """Acionado pelo atalho da tradução para o espanhol, Ctrl + Alt + N: o ditado em português,
    transcrito pelo Whisper e traduzido pelo LLM (o Whisper só traduz para o inglês)."""
    if not _pronto_para_gravar():
        return

    if not audio_mgr.is_recording:
        iniciar_gravacao("translate_es", config_mgr.translate_es_hotkey)
        threading.Thread(target=monitorar_hold, args=(config_mgr.translate_es_hotkey,), daemon=True).start()
    else:
        parar_gravacao()


def on_meeting_hotkey():
    """Acionado pelo atalho do Modo Reunião (Ctrl + Alt + R). Gravação contínua sem auto-silêncio."""
    if not _pronto_para_gravar():
        return

    if not audio_mgr.is_recording:
        iniciar_gravacao("meeting")
    else:
        parar_gravacao()


def on_prompt_hotkey():
    """Acionado pelo atalho do Modo Arquiteto de Prompts (Ctrl + Alt + P). Gera missões de agentes (/goal, loop, maestro)."""
    if not _pronto_para_gravar():
        return

    if not audio_mgr.is_recording:
        iniciar_gravacao("prompt", config_mgr.prompt_hotkey)
        threading.Thread(target=monitorar_hold, args=(config_mgr.prompt_hotkey,), daemon=True).start()
    else:
        parar_gravacao()


def on_history_hotkey():
    """Acionado pelo atalho do Mini-Spotlight de Histórico (Ctrl + Alt + H)."""
    if not audio_mgr.is_awake:
        return

    def _colar_texto_spotlight(texto: str):
        global last_injected_text
        if default_injector.paste_text(texto, auto_send=False):
            last_injected_text = texto
            sound_mgr.sound_success()
        else:
            # Clipboard ocupado por outro programa: nada foi colado.
            sound_mgr.sound_error()
            atualizar_ui("error", "Não consegui colar. Tente de novo", por_cima=True)

    if spotlight:
        safe_dispatch_ui(lambda: spotlight.mostrar(config_mgr.load_history(), on_paste_callback=_colar_texto_spotlight))


def on_send_hotkey():
    """Acionado pelo atalho 'Ditar e Enviar' (Ctrl + Shift + Enter). Dita e pressiona Enter automaticamente."""
    if not _pronto_para_gravar():
        return

    if not audio_mgr.is_recording:
        iniciar_gravacao("send", config_mgr.send_hotkey)
        threading.Thread(target=monitorar_hold, args=(config_mgr.send_hotkey,), daemon=True).start()
    else:
        parar_gravacao()


def desfazer_ultimo_ditado():
    """Desfaz o último ditado inserido pelo Willy enviando Ctrl+Z ao aplicativo ativo.

    Nada aqui encerra uma gravação em curso: os avisos passam por cima do "ouvindo".
    """
    global last_injected_text
    if not last_injected_text:
        atualizar_ui("error", "Nenhum ditado para desfazer", por_cima=True)
        return

    # O Ctrl+Alt+Z chega com o Alt ainda apertado: o Ctrl+Z saía como Ctrl+Alt+Z, o próprio
    # atalho do Willy, e não chegava ao app. Esta é a thread do atalho, só dele: dá para esperar.
    # Sem soltar, o ditado continua guardado, e a pessoa tenta de novo.
    if not ActionManager.esperar_modificadores_soltos(2.0):
        sound_mgr.sound_error()
        atualizar_ui("error", "Solte o atalho para desfazer", por_cima=True)
        return

    try:
        keyboard.send("ctrl+z")
        sound_mgr.sound_success()
        atualizar_ui("success", "Ditado desfeito! ↩️", por_cima=True)
        last_injected_text = None
    except Exception as e:  # noqa: BLE001 — Fronteira defensiva de atalho/sistema
        import sys
        print(f"[Willy] Erro ao desfazer último ditado: {e}", file=sys.stderr)
        sound_mgr.sound_error()
        atualizar_ui("error", "Falha ao desfazer", por_cima=True)


def on_undo_hotkey():
    """Acionado pelo atalho de desfazer (Ctrl + Alt + Z)."""
    desfazer_ultimo_ditado()


def on_speak_hotkey():
    """Acionado pelo atalho de leitura em voz alta (Ctrl + Alt + S). Lê seleção com voz neural SAPI Maria/Zira."""
    if tts_mgr.is_speaking:
        tts_mgr.stop()
        sound_mgr.sound_stop()
        atualizar_ui("idle", "Leitura pausada ⏹️")
        return

    sel_text = ActionManager.get_selected_text()
    if not sel_text or not sel_text.strip():
        sound_mgr.sound_error()
        atualizar_ui("warning", "Selecione um texto para ler")
        return

    sound_mgr.sound_action()
    atualizar_ui("speaking", "Lendo texto em voz alta... 🔊")
    tts_mgr.speak_async(
        sel_text,
        on_done=lambda: (sound_mgr.sound_success(), atualizar_ui("idle", "Leitura concluída ✅"))
    )


def on_sticky_hotkey():
    """Acionado pelo atalho de janela fixada (Ctrl + Alt + F). Fixa/desfixa destino para ditado invisível."""
    current_sticky = ContextManager.get_sticky_window()
    if current_sticky:
        ContextManager.clear_sticky_window()
        sound_mgr.sound_action()
        atualizar_ui("sticky_unpinned", "Janela desfixada! Ditado livre 🎯")
    else:
        hwnd = ContextManager.get_foreground_hwnd()
        # O painel do Willy ou a barra de tarefas na frente não são destino: fixados, o ditado era
        # colado dentro do Willy, ou em lugar nenhum. Vale a última janela de fora em que a pessoa
        # estava (juiz do Bloco 11, 3ª rodada; já era assim antes do bloco).
        if not ContextManager.janela_externa(hwnd):
            hwnd = _janela_antes_do_willy if ContextManager.janela_externa(_janela_antes_do_willy) else 0
        if hwnd:
            app_exe, app_title, _ = ContextManager.get_foreground_app(hwnd)
            target_name = app_exe.replace(".exe", "").capitalize() or app_title[:20] or "Janela"
            ContextManager.set_sticky_window(hwnd, target_name)
            sound_mgr.sound_success()
            atualizar_ui("sticky_pinned", f"Destino fixado: {target_name} 🎯")
        else:
            sound_mgr.sound_error()
            atualizar_ui("warning", "Nenhuma janela detectada para fixar")


def on_captions_hotkey():
    """Acionado pelo atalho de legendas (Ctrl + Alt + L). Alterna teleprompter flutuante translúcido."""
    if teleprompter:
        def _do_toggle():
            teleprompter.toggle()
            if teleprompter.is_visible:
                sound_mgr.sound_start()
                atualizar_ui("idle", "Teleprompter ativo 🪟")
            else:
                sound_mgr.sound_stop()
                atualizar_ui("idle", "Teleprompter oculto 🪟")
        safe_dispatch_ui(_do_toggle)


def on_transform_hotkey():
    """Acionado pelo atalho de transformar seleção por voz (Ctrl + Alt + T)."""
    global selected_text_for_transform
    if not _pronto_para_gravar():
        return

    if audio_mgr.is_recording:
        if audio_mgr.recording_mode == "transform":
            parar_gravacao()
        return

    if ActionManager.esperar_modificadores_soltos():
        sel_text = ActionManager.get_selected_text()
        if not sel_text or not sel_text.strip():
            sound_mgr.sound_error()
            atualizar_ui("warning", "Selecione um texto antes de transformar")
            return
    else:
        # Segurando o atalho para falar: com o Alt preso, o Ctrl+C não copiaria. A seleção é
        # lida pelo pipeline quando a gravação termina, com as teclas já soltas.
        sel_text = None

    selected_text_for_transform = sel_text
    iniciar_gravacao(modo="transform", atalho=config_mgr.transform_hotkey)
    # Só se este atalho começou a gravação: no meio de uma reunião o iniciar_gravacao não faz
    # nada, e o monitor seguiria a reunião (segurar e soltar o T a encerrava).
    if audio_mgr.is_recording and audio_mgr.recording_mode == "transform":
        threading.Thread(target=monitorar_hold, args=(config_mgr.transform_hotkey,), daemon=True).start()


def on_profile_toggle_hotkey():
    """Acionado pelo atalho de alternar perfil de IA (Ctrl + Alt + E). Cicla dev -> executivo -> puro."""
    perfis = ["dev", "executivo", "puro"]
    cur = getattr(config_mgr, "processing_profile", "dev")
    idx = (perfis.index(cur) + 1) % len(perfis) if cur in perfis else 0
    novo_perfil = perfis[idx]
    config_mgr.processing_profile = novo_perfil
    config_mgr.save_settings({"PROCESSING_PROFILE": novo_perfil})
    sound_mgr.sound_action()

    labels = {
        "dev": "💻 Dev & Código",
        "executivo": "👔 Executivo & Prosa",
        "puro": "⚡ Puro (Zero-Latency)"
    }
    label = labels.get(novo_perfil, novo_perfil)
    atualizar_ui("profile_changed", f"Perfil: {label}")
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_ajustes)


# Avisos para a bandeja que chegam antes de o ícone aparecer. Na partida, os atalhos são
# registrados logo depois de a thread da bandeja começar, e um notify sem ícone some calado.
_bandeja_lock = threading.Lock()
_bandeja_pronta = False
_avisos_pendentes_bandeja: list[tuple[str, str]] = []


def notificar_bandeja(titulo: str, texto: str) -> None:
    """Notificação da bandeja que não se perde se o ícone ainda não subiu."""
    with _bandeja_lock:
        if not _bandeja_pronta:
            _avisos_pendentes_bandeja.append((titulo, texto))
            return
    if tray_mgr:
        tray_mgr.notify(titulo, texto)


def bandeja_pronta() -> None:
    """O ícone da bandeja apareceu: entrega os avisos que esperavam por ele."""
    global _bandeja_pronta
    with _bandeja_lock:
        _bandeja_pronta = True
        pendentes = list(_avisos_pendentes_bandeja)
        _avisos_pendentes_bandeja.clear()
    for titulo, texto in pendentes:
        if tray_mgr:
            tray_mgr.notify(titulo, texto)


def avisar_atalhos_em_uso(falhas: list[str], mantidos: dict[str, str]) -> None:
    """Atalho que o Windows não registrou fica mudo: avisa na pílula e na bandeja.

    Antes o aviso ia só para o stderr, que no .exe ninguém vê, e a pessoa apertava o
    atalho sem nada acontecer. `mantidos` diz, para cada combinação recusada numa troca,
    qual anterior continua valendo. O texto não diz "outro programa": a mesma recusa vem
    de dois atalhos do próprio Willy com a mesma combinação.
    """
    lista = ", ".join(falhas)
    aviso = f"Atalho não registrado: {lista}" if len(falhas) == 1 else f"Atalhos não registrados: {lista}"
    continua = ", ".join(mantidos.values())
    if continua:
        aviso += f" (vale {continua})"
    atualizar_ui("warning", aviso)
    notificar_bandeja(
        "Willy: atalho não registrado",
        f"O Windows não aceitou {lista}: outro programa, ou outro atalho do Willy, já usa a "
        "combinação. " + (f"Continua valendo {continua}. " if continua else "")
        + "Troque na aba Atalhos do Willy.",
    )


def toggle_willy_awake():
    """Acorda ou coloca o Willy em repouso (Ctrl + Shift + Espaço)."""
    audio_mgr.is_awake = not audio_mgr.is_awake

    if audio_mgr.is_awake:
        if config_mgr.wake_word_enabled:
            audio_mgr.ensure_stream(callback_audio)
        sound_mgr.sound_wake()
        atualizar_ui("app_enabled")
    else:
        ww_lock = globals().get("_wake_word_lock")
        if ww_lock is not None:
            with ww_lock:
                _wake_word_buffer.clear()
        elif "_wake_word_buffer" in globals():
            _wake_word_buffer.clear()
        if audio_mgr.is_recording:
            _soltar_esc()
            audio_mgr.cancel_recording()
        audio_mgr.pause_stream()
        sound_mgr.sound_sleep()
        atualizar_ui("app_disabled")

    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(lambda: dashboard.atualizar_status_willy(audio_mgr.is_awake))
    return audio_mgr.is_awake


def sincronizar_bandeja():
    """Atualiza o menu e o ícone da bandeja."""
    if tray_mgr:
        tray_mgr.update(
            is_awake=audio_mgr.is_awake,
            refine_enabled=config_mgr.refine_prompt,
            silent_mode=config_mgr.silent_mode,
            pill_pos=config_mgr.pill_position,
            hotkey=config_mgr.hotkey,
            trans_hotkey=config_mgr.translate_hotkey,
            trans_es_hotkey=config_mgr.translate_es_hotkey,
            master_hotkey=config_mgr.master_hotkey,
            meeting_hotkey=config_mgr.meeting_hotkey,
            llm_model=config_mgr.llm_model,
            history_items=config_mgr.load_history(),
            prompt_hotkey=config_mgr.prompt_hotkey,
            auto_silence=config_mgr.auto_silence,
            pendentes=len(transcription_pipeline.fila),
        )


def toggle_modo_envio():
    config_mgr.toggle_auto_silence()
    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_ajustes)


def toggle_polimento_ia():
    config_mgr.save_settings({"REFINE_PROMPT": not config_mgr.refine_prompt})
    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_ajustes)


def toggle_modo_silencioso():
    config_mgr.save_settings({"SILENT_MODE": not config_mgr.silent_mode})
    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_ajustes)


def definir_posicao_pilula(pos: str):
    config_mgr.save_settings({"PILL_POSITION": pos})
    if pill:
        safe_dispatch_ui(pill.reposicionar)
    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_ajustes)


def abrir_vocabulario():
    try:
        if hasattr(os, "path") and not os.path.exists(VOCAB_FILE):
            raise FileNotFoundError(f"Arquivo de vocabulário não encontrado: {VOCAB_FILE}")
        os.startfile(VOCAB_FILE)
    except Exception as e:  # noqa: BLE001 — Fronteira defensiva de atalho/sistema
        import sys
        print(f"[Willy] Erro ao abrir vocabulário: {e}", file=sys.stderr)
        if "atualizar_ui" in globals() and callable(atualizar_ui):
            atualizar_ui("error", "Não foi possível abrir o vocabulário", por_cima=True)


def abrir_pasta_config():
    """Abre a pasta dos dados do Willy (.env, histórico, vocabulário), a do AppData no
    instalado. O item da bandeja promete "pasta de configuração (AppData)" e abria a pasta
    do programa."""
    try:
        os.startfile(USER_DATA_DIR)
    except Exception as e:  # noqa: BLE001 — Fronteira defensiva de atalho/sistema
        import sys
        print(f"[Willy] Erro ao abrir pasta de configuração: {e}", file=sys.stderr)
        if "atualizar_ui" in globals() and callable(atualizar_ui):
            atualizar_ui("error", "Não foi possível abrir a pasta de configuração", por_cima=True)


def dashboard_save_settings(dados):
    chave_antes = config_mgr.groq_api_key
    config_mgr.save_settings(dados)
    groq_service.set_api_key(config_mgr.groq_api_key)
    if "GROQ_LLM_MODEL" in dados:
        groq_service.set_llm_model(config_mgr.llm_model)
    if "AUDIO_DEVICE" in dados:
        audio_mgr.set_device(config_mgr.audio_device)
    if "SYSTEM_AUDIO_DEVICE" in dados:
        audio_mgr.set_system_device(config_mgr.system_audio_device)
    if "MIC_GAIN" in dados:
        audio_mgr.set_gain_boost(config_mgr.mic_gain)
    if "WHISPER_MODE" in dados:
        audio_mgr.set_whisper_mode(config_mgr.whisper_mode, config_mgr.mic_gain)
    if "WAKE_WORD_ENABLED" in dados:
        # O "Ei Willy" precisa do microfone aberto fora da gravação. Ligado nos Ajustes, só
        # passava a ouvir depois de reiniciar o Willy; desligado, o microfone seguia aberto.
        # Em repouso, ensure_stream não abre: o toggle_willy_awake abre ao acordar.
        if config_mgr.wake_word_enabled:
            audio_mgr.ensure_stream(callback_audio)
        else:
            ww_lock = globals().get("_wake_word_lock")
            if ww_lock is not None:
                with ww_lock:
                    _wake_word_buffer.clear()
            elif "_wake_word_buffer" in globals():
                _wake_word_buffer.clear()
            if not audio_mgr.is_recording:
                # Gravando, quem fecha é o parar_gravacao, que já vê a palavra desligada.
                audio_mgr.pause_stream()

    # Recusada pelo Windows, a troca volta à combinação anterior, e a config com ela: as abas
    # Atalhos e Ajustes releem o que ficou valendo.
    if hotkey_orchestrator and hotkey_orchestrator.recarregar_se_necessario(dados) and dashboard:
        safe_dispatch_ui(dashboard.sincronizar_atalhos)

    sincronizar_bandeja()
    if pill:
        safe_dispatch_ui(pill.reposicionar)

    # O áudio guardado por falta de chave (ou chave inválida) passa com a chave nova.
    chave = config_mgr.groq_api_key
    pendentes = len(transcription_pipeline.fila)
    if chave and chave != chave_antes and chave != "sua_chave_aqui" and pendentes:
        atualizar_ui("offline_retry", f"Chave salva. Áudios salvos: {pendentes}. Clique p/ reenviar")
    dash = globals().get("dashboard")
    if dash:
        safe_dispatch_ui(dash._atualizar_banner_onboarding)


def validar_e_aplicar_chave_groq(chave: str, salvar: bool = False) -> tuple[bool, str, float, dict]:
    """Valida uma chave na API da Groq e opcionalmente salva no cofre aplicando em memória."""
    ok, msg, lat, info = groq_service.validar_chave(chave)
    if ok and salvar:
        limpa = (chave or "").strip()
        dashboard_save_settings({"GROQ_API_KEY": limpa})
        if dashboard:
            safe_dispatch_ui(dashboard.recarregar_ajustes)
    return ok, msg, lat, info


def recarregar_chave_do_cofre_vivo() -> bool:
    """Relê o cofre e o .env em busca de chave nova e atualiza o serviço Groq em memória."""
    encontrou = config_mgr.recarregar_chave_do_cofre()
    groq_service.set_api_key(config_mgr.groq_api_key)
    sincronizar_bandeja()
    dash = globals().get("dashboard")
    if dash:
        safe_dispatch_ui(dash._atualizar_banner_onboarding)
    return encontrou


def concluir_onboarding_willy(abrir_aba: str = "history") -> None:
    """Marca o guia inicial como concluído e abre a aba de destino no painel."""
    config_mgr.save_settings({"ONBOARDING_COMPLETED": True})
    if dashboard:
        safe_dispatch_ui(lambda: (dashboard.recarregar_ajustes(), dashboard.mudar_aba(abrir_aba)))


def capturar_e_testar_ditado(stop_event=None, on_level=None) -> tuple[bool, str, str, str]:
    """Captura áudio curto no painel de onboarding, transcreve e refina sem colar em outra janela."""
    chave = (getattr(config_mgr, "groq_api_key", "") or "").strip()
    if not chave or chave == "sua_chave_aqui":
        return False, "", "", "Configure e valide uma chave Groq antes de testar o ditado."
    if audio_mgr.is_recording or audio_mgr.is_processing:
        return False, "", "", "Aguarde o ditado atual terminar antes de rodar o teste."

    taxa_base = getattr(audio_mgr, "sample_rate", 16000) or 16000
    try:
        stream, chosen_sr = negociar_stream(config_mgr.audio_device, None, 1, taxa_base)
    except Exception:  # noqa: BLE001 — fronteira defensiva: abertura de stream PortAudio para teste
        stream, chosen_sr = None, taxa_base
    if stream is None:
        return False, "", "", "Não foi possível abrir o microfone selecionado. Confira o passo anterior."

    pedacos: list[np.ndarray] = []
    inicio = time.monotonic()
    falou = False
    inicio_silencio: float | None = None
    chunk_size = max(160, int(chosen_sr * 0.05))
    try:
        while time.monotonic() - inicio < 8.0:
            if stop_event is not None and stop_event.is_set():
                break
            data, _ = stream.read(chunk_size)
            pedacos.append(data[:, 0].copy() if getattr(data, "ndim", 1) > 1 else data.copy())
            rms = compute_rms(data)
            if on_level is not None:
                on_level(min(1.0, rms / 0.06))
            if rms >= config_mgr.speech_threshold:
                falou = True
                inicio_silencio = None
            elif falou and rms <= config_mgr.silence_threshold:
                if inicio_silencio is None:
                    inicio_silencio = time.monotonic()
                elif time.monotonic() - inicio_silencio >= 1.6 and time.monotonic() - inicio >= 1.2:
                    break
            time.sleep(0.01)
    except Exception as e:  # noqa: BLE001 — fronteira defensiva: captura de áudio do teste guiado
        return False, "", "", f"Erro ao gravar áudio do microfone ({type(e).__name__})."
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001, S110 — fronteira defensiva: encerramento de stream PortAudio
            pass

    if not pedacos:
        return False, "", "", "Nenhum áudio capturado do microfone."

    audio_np = np.concatenate(pedacos).astype(np.float32)
    ganho = getattr(config_mgr, "mic_gain", 1.0) or 1.0
    if ganho > 1.0:
        audio_np = np.clip(audio_np * ganho, -1.0, 1.0)
    audio_np = para_taxa_whisper(audio_np, chosen_sr)
    audio_np = condicionar_para_whisper(audio_np, TAXA_WHISPER, 0.0, aparar=True)
    if len(audio_np) < int(0.3 * TAXA_WHISPER):
        return False, "", "", "Áudio curto demais ou muito silencioso. Fale mais perto do microfone."

    wav_bytes = audio_mgr.convert_to_wav(audio_np, sample_rate=TAXA_WHISPER)
    try:
        bruto = groq_service.transcribe(
            wav_bytes,
            prompt_context=config_mgr.get_prompt_context(),
            language=config_mgr.input_language,
        )
    except Exception as e:  # noqa: BLE001 — fronteira defensiva: chamada Whisper no teste guiado
        return False, "", "", f"Falha ao transcrever na Groq ({type(e).__name__}). Confira internet e chave."

    if not bruto or not bruto.strip():
        return False, "", "", "Não reconheci fala clara no áudio. Tente falar novamente."

    try:
        refinado = groq_service.refine_text(
            bruto,
            enabled=config_mgr.refine_prompt,
            tone=config_mgr.output_tone,
            smart_paragraphing=config_mgr.smart_paragraphing,
            profile=config_mgr.processing_profile,
        )
    except Exception:  # noqa: BLE001 — fronteira defensiva: fallback seguro para o texto bruto no teste guiado
        refinado = bruto
    return True, bruto.strip(), (refinado or bruto).strip(), ""


def _aviso_pilula_modelo_desconhecido(valor: str) -> str:
    nome = valor.strip()
    curto = nome if len(nome) <= 11 else nome[:10] + "…"
    return f"Modelo {curto} desconhecido: usando Smart"


def importar_perfil(caminho: str) -> bool:
    """Restaura um perfil e o aplica no processo em execução. Devolve se deu certo.

    Era uma lambda que devolvia a tupla (ok, None), sempre verdadeira: a aba mostrava
    "Perfil Restaurado ✓" com o import falho. E o {"RELOAD": True} que ela passava não casa
    com nenhum campo de atalho, então os atalhos restaurados só valiam depois de reiniciar.
    """
    if not config_mgr.import_profile(caminho, snippet_mgr=snippet_mgr):
        return False
    modelo_substituido = getattr(config_mgr, "modelo_llm_substituido", None)
    # Os campos que dashboard_save_settings aplica no processo vivo (a chave da Groq ele
    # aplica sempre).
    dashboard_save_settings({
        "GROQ_LLM_MODEL": config_mgr.llm_model,
        "AUDIO_DEVICE": config_mgr.audio_device,
        "SYSTEM_AUDIO_DEVICE": config_mgr.system_audio_device,
        "MIC_GAIN": config_mgr.mic_gain,
        "WHISPER_MODE": config_mgr.whisper_mode,
        # Abre ou fecha o microfone do "Ei Willy" na hora (sem ele, o perfil só valia depois
        # de reiniciar o Willy).
        "WAKE_WORD_ENABLED": config_mgr.wake_word_enabled,
    })
    if isinstance(modelo_substituido, str) and modelo_substituido.strip():
        # dashboard_save_settings gravou o modelo normalizado e limparia o aviso antes da UI lê-lo.
        config_mgr.modelo_llm_substituido = modelo_substituido
    if hotkey_orchestrator:
        hotkey_orchestrator.registrar_todos()
    if dashboard:
        # Todas as abas: o perfil trouxe vocabulário, templates e atalhos novos, e a aba
        # Atalhos e o mapa de conflitos do Keycap ficavam com as combinações de antes.
        safe_dispatch_ui(lambda: dashboard.recarregar_dados(completo=True))
    if isinstance(modelo_substituido, str) and modelo_substituido.strip():
        aviso_ui = globals().get("atualizar_ui")
        if callable(aviso_ui):
            nome = modelo_substituido.strip()
            curto = nome if len(nome) <= 11 else nome[:10] + "…"
            aviso_ui("warning", f"Modelo {curto} desconhecido: usando Smart")
    if config_mgr.chave_do_perfil_ignorada and tray_mgr:
        # Notificação do Windows, e não a pílula: o estado "success" some em 900 ms e corta o texto.
        tray_mgr.notify("Perfil restaurado", "A chave da Groq do perfil foi ignorada: a sua continua.")
    return True


def definir_modelo_ia(modelo: str):
    config_mgr.save_settings({"GROQ_LLM_MODEL": modelo})
    groq_service.set_llm_model(modelo)
    sincronizar_bandeja()
    if dashboard:
        safe_dispatch_ui(dashboard.recarregar_ajustes)


# A última janela em primeiro plano que não era do Willy nem do Windows (barra de tarefas), e o
# controle com o foco do teclado nela: é nela que o "Reusar" do Histórico cola, e é o alvo do
# ditado que começa com o painel do Willy na frente. Atualizada pelo laço de 400 ms do main().
_janela_antes_do_willy = 0
_foco_antes_do_willy = 0


def lembrar_janela_fora_do_willy() -> None:
    global _janela_antes_do_willy, _foco_antes_do_willy
    hwnd = ContextManager.get_foreground_hwnd()
    if hwnd and not ContextManager.eh_janela_do_willy(hwnd) and not ContextManager.eh_janela_do_shell(hwnd):
        _janela_antes_do_willy = hwnd
        _foco_antes_do_willy = ContextManager.foco_do_teclado(hwnd)


def reusar_no_app_anterior(texto: str) -> bool:
    """O "Reusar" do Histórico: devolve o foco ao app em que a pessoa estava, esconde o painel
    e cola o texto lá. Devolve False sem esse app (fechado, ou nenhum desde que o Willy abriu),
    e a aba então só copia e diz isso.

    O botão prometia "copiar e colar no app anterior" e só copiava, igual ao "Copiar" ao lado.
    """
    hwnd = _janela_antes_do_willy
    # O foco antes de esconder o painel: só o processo em primeiro plano pode passá-lo, e o
    # Willy deixa de sê-lo assim que o painel some.
    if not hwnd or not ContextManager.focus_window(hwnd, _foco_antes_do_willy or None):
        return False
    if dashboard:
        dashboard.esconder()

    def _colar():
        global last_injected_text
        fim = time.monotonic() + 0.6
        while ContextManager.get_foreground_hwnd() != hwnd:
            if time.monotonic() >= fim:
                # O foco não chegou: colar agora cairia em outra janela.
                sound_mgr.sound_error()
                if ActionManager.secure_copy(texto):
                    atualizar_ui("error", "Não voltei ao app: texto copiado")
                else:
                    atualizar_ui("error", "Não colei nem copiei. Tente de novo")
                return
            time.sleep(0.02)
        if default_injector.paste_text(texto, auto_send=False):
            sound_mgr.sound_success()
            atualizar_ui("success", "Colado no app anterior")
            last_injected_text = texto  # Ctrl+Alt+Z desfaz, como num ditado
        else:
            sound_mgr.sound_error()
            atualizar_ui("error", "Não consegui colar. Tente de novo")

    threading.Thread(target=_colar, daemon=True).start()
    return True


def ultimo_app_externo() -> tuple[str, str] | None:
    """(executável, título) do último app em que a pessoa estava fora do Willy: o "Capturar
    último app" das regras por aplicativo, nos Ajustes. None sem ele (fechado, ou nenhum desde
    que o Willy abriu)."""
    hwnd = _janela_antes_do_willy
    if not hwnd or not ContextManager.janela_existe(hwnd):
        return None
    app_exe, titulo, _categoria = ContextManager.get_foreground_app(hwnd)
    return app_exe, titulo


# Os tons do "Reformatar" do Histórico (os do refino; ver GroqService._get_tone_instructions).
TONS_DO_REFORMATAR = ("natural", "formal", "concise", "bullet_points", "technical")


def reformatar_texto(texto: str, acao: str) -> str:
    """O "Reformatar / Traduzir" de um item do Histórico, pela Groq: um tom de TONS_DO_REFORMATAR,
    "translate" (inglês) ou "translate_es" (espanhol).

    Chamada pela aba numa thread dela, nunca na da interface. Falha da IA ou da rede sobe
    (FalhaDoLLM, erro do cliente): a aba avisa, e o item fica como estava.
    """
    from core.text_processing import TextProcessor

    termos = config_mgr.get_vocab_terms()
    termos_fixos = f"Termos da pessoa, que ficam como estão: {', '.join(termos)}" if termos else ""
    if acao == "translate":
        resultado = groq_service.translate_to_english(texto, extra_context=termos_fixos, estrito=True)
    elif acao == "translate_es":
        resultado = groq_service.translate_to_spanish(texto, extra_context=termos_fixos, estrito=True)
    elif acao in TONS_DO_REFORMATAR:
        # O perfil Puro tira o LLM do ditado, pela latência; aqui a pessoa pediu a IA num clique.
        perfil = "dev" if config_mgr.processing_profile == "puro" else config_mgr.processing_profile
        resultado = groq_service.refine_text(texto, enabled=True, tone=acao,
                                             smart_paragraphing=config_mgr.smart_paragraphing,
                                             profile=perfil, estrito=True)
        resultado = TextProcessor.pontuar_perguntas(resultado)
    else:
        raise ValueError(f"ação de reformatação desconhecida: {acao!r}")

    reps = config_mgr.load_replacements()
    if isinstance(reps, dict) and reps:
        resultado = TextProcessor.apply_replacements(resultado, reps)
    return resultado


def transcrever_arquivo_em_segundo_plano(caminho_arquivo: str) -> None:
    """O "Transcrever arquivo" da aba Histórico, fora da thread da interface.

    O botão chamava transcrever_arquivo_externo direto: o envio à Groq (minutos, num arquivo
    longo) congelava a janela, e nem o "processando" da pílula aparecia, porque as
    atualizações dela esperam a mesma thread.
    """
    threading.Thread(target=transcrever_arquivo_externo, args=(caminho_arquivo,), daemon=True).start()


def transcrever_arquivo_externo(caminho_arquivo: str, gerar_ata: bool = False) -> str | None:
    """
    Transcreve um arquivo de áudio local (.mp3, .wav, .m4a, .ogg, .flac).
    Se gerar_ata=True, resume estruturadamente em formato de Ata Executiva.
    Salva no histórico, copia para o clipboard e notifica a UI.
    """
    pipeline = globals().get("transcription_pipeline")
    if pipeline is None:
        from core.pipeline import TranscriptionPipeline

        def _sync():
            sync_fn = globals().get("sincronizar_bandeja")
            if sync_fn:
                sync_fn()
            dash = globals().get("dashboard")
            dispatch = globals().get("safe_dispatch_ui")
            if dash and dispatch:
                dispatch(dash.recarregar_dados)

        pipeline = TranscriptionPipeline(
            groq_service=groq_service,
            config_mgr=config_mgr,
            audio_mgr=audio_mgr,
            injector=None,
            sound_mgr=sound_mgr,
            ui_notifier=atualizar_ui,
            ui_dispatcher=globals().get("safe_dispatch_ui"),
            on_success_sync=_sync,
        )
    return pipeline.transcrever_arquivo_externo(caminho_arquivo, gerar_ata=gerar_ata)


def fechar_aplicacao():
    """Encerra a aplicação por completo liberando todos os recursos."""
    try:
        sound_mgr.sound_sleep()
    except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de inicialização/desligamento
        pass

    if tts_mgr:
        tts_mgr.stop()

    if hotkey_mgr:
        try:
            hotkey_mgr.stop()
        except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de desligamento
            pass

    audio_mgr.close()

    if tray_mgr:
        tray_mgr.stop()

    def _fechar_ui_e_sair():
        if teleprompter:
            try:
                teleprompter.destroy()
            except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de desligamento UI
                pass
        if pill:
            try:
                pill.destroy()
            except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de desligamento UI
                pass
        if root:
            try:
                root.quit()
            except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de desligamento UI
                pass
            try:
                root.destroy()
            except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de desligamento UI
                pass
        single_instance.release()
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream is not None and hasattr(stream, "flush"):
                    stream.flush()
            except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de desligamento UI
                pass

    safe_dispatch_ui(_fechar_ui_e_sair)


def main():
    global root, pill, dashboard, tray_mgr, spotlight, teleprompter

    # 1. Controle de Instância Única
    if not single_instance.acquire():
        single_instance.signal_and_restore(USER_DATA_DIR)
        sys.exit(0)

    inicializar_ambiente_partida()

    # O last_failed_audio.wav à espera de reenvio, de antes da fila, entra nela (uma vez só).
    # Depois da trava de instância: uma segunda cópia do app não pode mexer na fila.
    transcription_pipeline.importar_audio_legado()

    # 2. Identificador de Aplicativo Nativo do Windows (para ícone na barra de tarefas)
    try:
        _shell32.SetCurrentProcessExplicitAppUserModelID("jottaprado.willy.app.1.0")
    except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de inicialização/desligamento
        pass

    callbacks_dash = {
        "get_history": config_mgr.load_history,
        "get_analytics": config_mgr.get_analytics_metrics,
        "get_audio_devices": AudioManager.get_input_devices,
        # As abas despacham atualizacoes de UI por aqui. Sem o registro elas caem
        # num fallback com `self.after`, que agenda no widget da aba em vez da
        # raiz: o despacho centralizado que esta funcao existe para dar nunca
        # acontecia, e nada avisava porque o fallback nao falha.
        "safe_dispatch_ui": safe_dispatch_ui,
        # A aba de diagnóstico testa o microfone na taxa REAL da gravação. Sem
        # este callback ela caía na nominal e podia medir 16000 enquanto o Willy
        # gravava a 48000 — a divergência que o teste deveria detectar.
        "get_actual_sample_rate": lambda: getattr(
            audio_mgr, "actual_sample_rate", audio_mgr.sample_rate
        ),
        # A aba Atalhos marca a linha do atalho que o Windows recusou (outro programa o tem).
        "get_hotkey_failures": lambda: hotkey_orchestrator.atalhos_com_falha() if hotkey_orchestrator else {},
        "get_credential_catalog": lambda: credenciais_do_willy(config_mgr),
        "get_snippets": snippet_mgr.get_snippets,
        "on_save_snippet": snippet_mgr.save_snippet,
        "on_delete_snippet": snippet_mgr.delete_snippet,
        "on_transcribe_file": transcrever_arquivo_em_segundo_plano,
        "on_reuse_text": reusar_no_app_anterior,
        "on_reformat_text": reformatar_texto,
        "on_learn_correction": config_mgr.learn_correction,
        "get_app_rules": config_mgr.get_app_context_rules,
        "on_save_app_rules": config_mgr.save_app_context_rules,
        "get_last_external_app": ultimo_app_externo,
        "on_export_profile": lambda path, incluir_historico=False: config_mgr.export_profile(
            path, snippet_mgr=snippet_mgr, include_history=incluir_historico
        ),
        "on_summarize_profile": config_mgr.resumir_perfil,
        "on_import_profile": importar_perfil,
        "get_replacements": config_mgr.load_replacements,
        "on_save_replacement": config_mgr.add_replacement,
        "on_delete_replacement": config_mgr.delete_replacement,
        "on_open_outputs": config_mgr.open_outputs_folder,
        "on_open_file": ConfigManager.open_file,
        "get_outputs_dir": lambda: config_mgr.outputs_dir,
        "get_settings": lambda: {
            "auto_silence": config_mgr.auto_silence,
            "clean_fillers": config_mgr.clean_fillers,
            "clipboard_only": config_mgr.clipboard_only,
            "smart_paragraphing": config_mgr.smart_paragraphing,
            "output_tone": config_mgr.output_tone,
            "input_language": config_mgr.input_language,
            "silence_seconds": config_mgr.silence_seconds,
            "refine_prompt": config_mgr.refine_prompt,
            "silent_mode": config_mgr.silent_mode,
            "private_mode": config_mgr.private_mode,
            "outputs_dir": config_mgr.outputs_dir,
            "pill_position": config_mgr.pill_position,
            "llm_model": config_mgr.llm_model,
            "audio_device": config_mgr.audio_device,
            "system_audio_device": config_mgr.system_audio_device,
            "mic_gain": config_mgr.mic_gain,
            "prompt_hotkey": config_mgr.prompt_hotkey,
            "transform_hotkey": config_mgr.transform_hotkey,
            "profile_hotkey": config_mgr.profile_hotkey,
            "processing_profile": getattr(config_mgr, "processing_profile", "dev"),
            "whisper_mode": getattr(config_mgr, "whisper_mode", False),
            "voice_hotkey": config_mgr.hotkey,
            "translate_hotkey": config_mgr.translate_hotkey,
            "translate_es_hotkey": config_mgr.translate_es_hotkey,
            "master_hotkey": config_mgr.master_hotkey,
            "meeting_hotkey": config_mgr.meeting_hotkey,
            "history_hotkey": config_mgr.history_hotkey,
            "undo_hotkey": config_mgr.undo_hotkey,
            "send_hotkey": config_mgr.send_hotkey,
            "speak_hotkey": config_mgr.speak_hotkey,
            "sticky_hotkey": config_mgr.sticky_hotkey,
            "captions_hotkey": config_mgr.captions_hotkey,
            "save_audio_files": config_mgr.save_audio_files,
            "silero_vad": config_mgr.silero_vad,
            "wake_word_enabled": config_mgr.wake_word_enabled,
            "onboarding_completed": getattr(config_mgr, "onboarding_completed", True),
            "api_key": config_mgr.groq_api_key,
            "cofre_ilegivel": config_mgr.cofre_ilegivel,
            "modelo_llm_substituido": config_mgr.modelo_llm_substituido,
            "autostart": AutoStartManager.is_enabled()
        },
        "on_undo_dictation": desfazer_ultimo_ditado,
        "on_toggle_autostart": AutoStartManager.set_enabled,
        "on_toggle_auto_silence": toggle_modo_envio,
        "get_vocab": config_mgr.load_vocab_text,
        "get_awake_status": lambda: audio_mgr.is_awake,
        "on_toggle_sleep": toggle_willy_awake,
        "on_save_settings": dashboard_save_settings,
        "on_validate_groq_key": validar_e_aplicar_chave_groq,
        "on_reload_api_key": recarregar_chave_do_cofre_vivo,
        "on_test_dictation": capturar_e_testar_ditado,
        "on_complete_onboarding": concluir_onboarding_willy,
        "on_save_vocab": config_mgr.save_vocab_text,
        "on_clear_history": lambda: (config_mgr.clear_history(), sincronizar_bandeja()),
        # A bandeja relê do disco; a lista vem para manter a assinatura da aba de Histórico.
        "on_history_changed": lambda _itens: sincronizar_bandeja(),
        "on_ping_groq": groq_service.ping,
        "on_close_app": fechar_aplicacao,
        "on_play_audio": sound_mgr.play_wav_file,
        "on_speak_text": lambda text: tts_mgr.speak_async(text, on_done=lambda: atualizar_ui("idle")),
        "on_stop_speaking": lambda: (tts_mgr.stop(), atualizar_ui("idle")),
        "on_toggle_teleprompter": lambda: teleprompter.toggle() if teleprompter else None,
        "on_toggle_sticky": on_sticky_hotkey,
        "get_sticky_status": ContextManager.get_sticky_window,
        "notify_tray": lambda title, msg: tray_mgr.notify(title, msg) if tray_mgr else None,
        "on_copied": sound_mgr.sound_success,
    }


    dashboard = WillyDashboard(callbacks=callbacks_dash)
    root = dashboard
    pill = FloatingPill(root, position_getter=lambda: config_mgr.pill_position,
                        modo_privado_getter=lambda: config_mgr.private_mode,
                        atalho_getter=lambda atributo: getattr(config_mgr, atributo, ""),
                        eh_do_willy_ou_do_shell=lambda hwnd: (ContextManager.eh_janela_do_willy(hwnd)
                                                              or ContextManager.eh_janela_do_shell(hwnd)))
    pill.set_retry_callback(reenviar_ultimo_audio)
    spotlight = HistorySpotlight(root)
    teleprompter = LiveTeleprompter(root)

    dashboard.mostrar()

    aba_inicial(config_mgr)

    # Monitoramento de requisição externa para exibir o dashboard
    def verificar_solicitacao():
        lembrar_janela_fora_do_willy()
        if os.path.exists(FLAG_SHOW_DASHBOARD):
            try:
                os.remove(FLAG_SHOW_DASHBOARD)
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de UI/flag
                import sys

                print(f"[Willy] Falha ao remover {FLAG_SHOW_DASHBOARD}: {e!r}", file=sys.stderr)
            if dashboard:
                try:
                    dashboard.mostrar()
                except Exception as e:  # noqa: BLE001 — Fronteira defensiva de restauração UI
                    import sys

                    print(f"[Willy] Falha ao restaurar dashboard: {e!r}", file=sys.stderr)
        if root:
            root.after(400, verificar_solicitacao)

    verificar_solicitacao()

    # Inicialização da Bandeja do Sistema
    tray_callbacks = {
        "on_open_dashboard": lambda: safe_dispatch_ui(dashboard.mostrar),
        "on_toggle_sleep": toggle_willy_awake,
        "on_toggle_refine": toggle_polimento_ia,
        "on_toggle_auto_silence": toggle_modo_envio,
        "on_toggle_meeting": on_meeting_hotkey,
        "on_toggle_prompt": on_prompt_hotkey,
        "on_set_model": definir_modelo_ia,
        "on_toggle_silent": toggle_modo_silencioso,
        "on_set_position": definir_posicao_pilula,
        "on_open_vocab": abrir_vocabulario,
        "on_open_outputs": config_mgr.open_outputs_folder,
        "on_open_folder": abrir_pasta_config,
        "on_exit": fechar_aplicacao,
        "on_copied": sound_mgr.sound_success,
        "on_retry_audio": reenviar_ultimo_audio,
    }
    tray_mgr = TrayManager(callbacks=tray_callbacks, base_dir=BASE_DIR,
                           modo_privado_getter=lambda: config_mgr.private_mode)

    def _tray_thread():
        def _on_ready(icon):
            sincronizar_bandeja()
            bandeja_pronta()
            if not config_mgr.silent_mode:
                try:
                    import winsound
                    winsound.Beep(1000, 50)
                    winsound.Beep(1500, 70)
                except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de fallback/winsound
                    pass
        tray_mgr.start(on_ready=_on_ready)

    threading.Thread(target=_tray_thread, daemon=True).start()

    # Atalhos Globais Nativos via HotkeyOrchestrator (Win32 RegisterHotKey com MOD_NOREPEAT)
    global hotkey_orchestrator
    from core.system.hotkey_orchestrator import HotkeyOrchestrator
    handlers = {
        "master": toggle_willy_awake,
        "translate": on_translate_hotkey,
        "translate_es": on_translate_es_hotkey,
        "meeting": on_meeting_hotkey,
        "prompt": on_prompt_hotkey,
        "transform": on_transform_hotkey,
        "profile": on_profile_toggle_hotkey,
        "history": on_history_hotkey,
        "undo": on_undo_hotkey,
        "send": on_send_hotkey,
        "speak": on_speak_hotkey,
        "sticky": on_sticky_hotkey,
        "captions": on_captions_hotkey,
        "voice": on_voice_hotkey,
    }
    hotkey_orchestrator = HotkeyOrchestrator(hotkey_mgr, config_mgr, handlers,
                                             on_falha=avisar_atalhos_em_uso)
    hotkey_orchestrator.registrar_todos()
    # A aba Atalhos foi montada antes do registro: passa a mostrar a alternativa que entrou no lugar
    # de um padrão ocupado e o aviso nos atalhos que o Windows recusou.
    if dashboard:
        safe_dispatch_ui(dashboard.sincronizar_atalhos)

    # Inicia captura de áudio preventivamente apenas se wake word estiver ativo
    if config_mgr.wake_word_enabled:
        audio_mgr.ensure_stream(callback_audio)
    
    iniciar_dreno_ui(root)

    if isinstance(config_mgr.modelo_llm_substituido, str) and config_mgr.modelo_llm_substituido.strip():
        atualizar_ui("warning", _aviso_pilula_modelo_desconhecido(config_mgr.modelo_llm_substituido))

    try:
        root.mainloop()
    except KeyboardInterrupt:
        fechar_aplicacao()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — Fronteira defensiva de inicialização/desligamento
        import traceback
        with open(os.path.join(USER_DATA_DIR, "crash.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
