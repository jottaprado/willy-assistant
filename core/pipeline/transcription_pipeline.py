"""
Pipeline de Transcrição, Refino com IA e Injeção do Willy.
Desacopla o fluxo monolítico de transcrição em estágios coesos e testáveis:
1. Validação de ambiente e buffers
2. Transcrição acústica (Whisper via Groq / tradução / fatiamento de reuniões)
3. Enriquecimento de texto (pontuação, tom, formatação de código, copiloto de ações, snippets e refino LLM)
4. Entrega do resultado (teleprompter, dicionário fonético, fixação de foco e injeção atômica)
5. Persistência e telemetria (registro no histórico, arquivos markdown e cache para retry offline)
"""

import calendar
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import wave
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import groq
import httpx

from core import modelos_llm
from core.actions import ActionManager
from core.audio_processing.dsp import fatiar_audio_para_whisper
from core.config import FAILED_AUDIO_PATH, USER_DATA_DIR
from core.context import ContextManager
from core.groq_service import FalhaDoLLM, RecusaDoLLM
from core.storage.history_store import _atomic_write_json
from core.text_processing import ESTILOS_EM_PROSA, TextProcessor


def _classificar_erro(exc: Exception) -> str:
    """Categoria de uma falha de transcrição, pelo TIPO da exceção.

    Antes a categoria vinha de substrings de str(exc) e tudo que não casava virava
    "offline_retry": 413, 400, 503 e até bug interno apareciam como "sem internet, clique
    p/ reenviar", num retry que nunca podia funcionar.
    """
    if isinstance(exc, groq.BadRequestError):
        texto = str(exc).lower()
        if "prompt length" in texto or "invalid_prompt" in texto:
            return "prompt_length"
        return "bad_request"
    if isinstance(exc, groq.RateLimitError):
        return "rate_limit"
    if isinstance(exc, (groq.AuthenticationError, groq.PermissionDeniedError)):
        return "invalid_key"
    # APITimeoutError herda de APIConnectionError. ConnectionError/TimeoutError nativos e
    # httpx.TransportError chegam quando a falha acontece fora do cliente da Groq.
    if isinstance(exc, (groq.APIConnectionError, groq.InternalServerError,
                        httpx.TransportError, ConnectionError, TimeoutError)):
        return "offline_retry"
    if isinstance(exc, groq.APIStatusError):
        # 408 (timeout do servidor) e 409 (conflito) são passageiros: o mesmo áudio passa.
        if exc.status_code in (408, 409):
            return "offline_retry"
        return "bad_request"
    return "internal"


# O tom dito antes de um pedido de transformação vai para a instrução ("resuma este contrato em
# tópicos"); "natural" não acrescenta nada.
_TOM_NA_INSTRUCAO = {"formal": "em tom formal", "concise": "de forma concisa",
                     "bullet_points": "em tópicos", "technical": "em tom técnico"}


def _segundos_do_wav(wav: bytes) -> float | None:
    """Duração da gravação, que vai para o histórico: é com ela que as métricas medem a
    velocidade da fala, antes uma constante de 145 palavras/min."""
    try:
        with wave.open(io.BytesIO(wav)) as w:
            taxa = w.getframerate()
            return w.getnframes() / taxa if taxa else None
    except Exception:  # noqa: BLE001 — fronteira defensiva: leitura de cabeçalho WAV para telemetria WPM
        return None


def _segundos_do_arquivo_audio(caminho: str) -> float | None:
    """Duração de um arquivo de áudio em disco (para telemetria WPM do histórico), ou None se ilegível."""
    if not caminho or not os.path.exists(caminho):
        return None
    try:
        import soundfile as sf
        info = sf.info(caminho)
        if info.duration and info.duration > 0:
            return float(info.duration)
    except Exception:  # noqa: BLE001, S110 — fronteira defensiva: fallback de soundfile para wave.open
        pass
    try:
        with open(caminho, "rb") as f:
            return _segundos_do_wav(f.read())
    except Exception:  # noqa: BLE001 — fronteira defensiva: leitura de arquivo de áudio para telemetria WPM
        return None


def _foco_no_shell() -> bool:
    """A janela em primeiro plano é do Windows (a barra de tarefas, a área de trabalho, o
    Iniciar)? Ali o Ctrl+V não chega a app nenhum."""
    frente = ContextManager.get_foreground_hwnd()
    return ContextManager.janela_existe(frente) and ContextManager.eh_janela_do_shell(frente)


def _foco_numa_janela_do_willy() -> bool:
    """A janela em primeiro plano é do próprio processo do Willy (dashboard, menu da bandeja)?"""
    try:
        return ContextManager.foco_numa_janela_do_willy()
    except Exception as e:  # noqa: BLE001 — fronteira defensiva: verificação de foco no Willy
        print(f"[Pipeline] Erro ao verificar se o foco está no Willy: {e!r}", file=sys.stderr)
        return True


# Falhas em que o MESMO áudio passa depois: só essas a pílula oferece reenviar.
_CATEGORIAS_REENVIAVEIS = ("offline_retry", "rate_limit")
# Vão para a fila. Com a chave inválida (401) o áudio também passa, mas só depois de trocada a
# chave: o reenvio é oferecido quando ela muda (willy.dashboard_save_settings), não na hora. O 403
# fica de fora (ver _tratar_erro).
_CATEGORIAS_DA_FILA = _CATEGORIAS_REENVIAVEIS + ("invalid_key",)
_MODOS = ("transcribe", "translate", "translate_es", "meeting", "prompt", "transform", "send")
# A ata falhou: entrega a transcrição, marcada, e guarda o áudio para gerar a ata depois.
_ATA_AUSENTE = "> ⚠️ Ata não gerada: a Groq não respondeu. Segue a transcrição na íntegra.\n\n"
# Mensagens curtas: no estado fixo da pílula (show_state) cabem perto de 45 caracteres, numa
# estimativa pela fonte; só o update_status_text alarga, até 65.
# (estado, mensagem, versão curta para juntar ao "Áudios salvos: N" quando há fila)
_AVISO_DA_FALHA = {
    "refino": ("error", "Sem polimento: a Groq não respondeu", "Sem polimento"),
    "prompt": ("error", "Prompt sem estrutura: Groq falhou", "Prompt sem estrutura"),
    "traducao_es": ("error", "Sem tradução: o texto ficou em português", "Sem tradução ES"),
    "ata": ("offline_retry", "Ata não gerada. Clique p/ reenviar", None),
}
# Quando a Groq respondeu, mas o modelo recusou o conteúdo (RecusaDoLLM): dizer "não respondeu"
# induz a tentar de novo sem efeito. Cada aviso cabe nos ~45 caracteres da pílula.
_AVISO_DA_RECUSA = {
    "refino": ("error", "Sem polimento: a IA recusou o texto", "Sem polimento"),
    "prompt": ("error", "Prompt sem estrutura: a IA recusou", "Prompt sem estrutura"),
    "traducao_es": ("error", "Sem tradução: a IA recusou o texto", "Sem tradução ES"),
}
# No modo privado nenhum áudio nem texto novo vai para o disco: nem o áudio na fila ou no
# last_failed_audio.wav, nem os blocos transcritos ao lado de um item. (Um item que já estava na
# fila ganha só o marcador vazio de entregue, ver _entregar_resultado.) A pílula diz isso em vez
# de "áudio salvo".
_NAO_GUARDADO_NO_PRIVADO = "privado: áudio não salvo"
# Quanto o modo transform espera o Alt e o Shift do Ctrl+Alt+T segurado subirem.
_ESPERA_DO_ATALHO_SOLTO_S = 2.0
# Acima disto o áudio vai à Groq em blocos de 10 min (a 16 kHz, 20 MB são ~10,9 min; acima de
# 25 MB ela recusa com 413), em todos os modos que transcrevem. Antes, só a reunião fatiava: o
# ditado longo no transcribe, no send, no prompt e no transformar ia inteiro e levava o 413 (o
# willy_errors.log do dono, no send).
_LIMITE_SEM_FATIAR = 20 * 1024 * 1024
# O reenvio de uma reunião cuja ata a Groq recusou (não é rede nem limite): o item sai da fila.
# Sem "de novo": a primeira passagem pode ter caído na transcrição, e esta é a primeira recusa.
_ATA_RECUSADA = "Ata recusada pela Groq: saiu da fila"
# O reenvio de um pedido sobre a seleção sem texto selecionado: o item sai da fila.
_PEDIDO_SEM_SELECAO = "Sem seleção: pedido descartado"
# Quanto a entrega espera a janela-alvo voltar à frente antes do Ctrl+V.
_ESPERA_DO_FOCO_S = 0.6
# A cópia no lugar da colagem: o foco não voltou ao app, ou não há app para onde ele volte.
_NAO_VOLTEI_AO_APP = "Não voltei ao app: copiado, cole com Ctrl+V"
_COPIADO_SEM_ALVO = "Copiado: cole onde quiser 📋"
# Etapas em que nada é colado quando a IA falha (colar seria fingir que deu certo).
_NADA_A_COLAR = {
    "transformar": "Não transformei: Groq não respondeu",
    "acao": "Não executei: Groq não respondeu",
}
_NADA_A_COLAR_RECUSA = {
    "transformar": "Não transformei: a IA recusou o pedido",
    "acao": "Não executei: a IA recusou o pedido",
}
# O modo pode ter "_" (translate_es): com [a-z]+, o item não casava e o reenvio ia como ditado.
_NOME_NA_FILA = re.compile(r"^(\d{8}T\d{6})\.(\d{9})Z_([a-z_]+)\.wav$")


class FilaDeAudioFalho:
    """Áudios à espera de reenvio, um arquivo cada: <pasta>/<timestamp>_<modo>.wav.

    Antes era um único last_failed_audio.wav: a falha seguinte sobrescrevia a anterior, e
    qualquer ditado bem-sucedido o apagava. Uma reunião que caía offline se perdia no
    primeiro ditado curto feito depois, antes do clique em reenviar.
    """

    LIMITE = 10  # os mais antigos saem; uma reunião longa passa de 100 MB
    LIMITE_GROQ = 25 * 1024 * 1024  # acima disso a Groq recusa o arquivo inteiro (ver _LIMITE_SEM_FATIAR)
    MARCADOR_LEGADO = ".legado_importado"

    def __init__(self, pasta: str):
        self.pasta = pasta

    def guardar(self, wav: bytes, modo: str) -> str:
        os.makedirs(self.pasta, exist_ok=True)
        modo = modo if modo in _MODOS else "transcribe"
        # UTC com nanossegundos: a ordem dos nomes é a ordem das falhas, sem horário de verão
        # nem stat de arquivo que outra thread pode ter acabado de apagar. E nunca antes do
        # último item: com o relógio atrasado (NTP, dual boot), o áudio novo ordenaria como o
        # mais antigo e seria podado logo depois de a pílula dizer "áudio salvo".
        agora = self._instante_seguinte()
        while True:
            caminho = os.path.join(self.pasta, self._nome(agora, modo))
            try:
                # "xb" cria só se não existir: duas threads no mesmo instante não se sobrescrevem.
                with open(caminho, "xb") as f:
                    f.write(wav)
                break
            except FileExistsError:
                agora += 1
        self._podar()
        return caminho

    def _instante_seguinte(self) -> int:
        agora = time.time_ns()
        itens = self.itens()
        ultimo = self._ns(os.path.basename(itens[-1])) if itens else None
        return ultimo + 1 if ultimo is not None and agora <= ultimo else agora

    @staticmethod
    def _nome(instante_ns: int, modo: str) -> str:
        segundos, nanos = divmod(instante_ns, 1_000_000_000)
        return time.strftime("%Y%m%dT%H%M%S", time.gmtime(segundos)) + f".{nanos:09d}Z_{modo}.wav"

    def _podar(self) -> None:
        for antigo in self.itens()[:-self.LIMITE]:
            self.remover(antigo)

    @staticmethod
    def _ns(nome: str) -> int | None:
        m = _NOME_NA_FILA.match(nome)
        if not m:
            return None
        return calendar.timegm(time.strptime(m.group(1), "%Y%m%dT%H%M%S")) * 1_000_000_000 + int(m.group(2))

    def itens(self) -> list[str]:
        """Do mais antigo ao mais novo."""
        try:
            nomes = sorted(n for n in os.listdir(self.pasta) if n.lower().endswith(".wav"))
        except FileNotFoundError:
            return []
        return [os.path.join(self.pasta, n) for n in nomes]

    def mais_recente(self) -> tuple[str, str] | None:
        """(caminho, modo) do último áudio guardado, ou None com a fila vazia."""
        itens = self.itens()
        if not itens:
            return None
        caminho = itens[-1]
        m = _NOME_NA_FILA.match(os.path.basename(caminho))
        modo = m.group(3) if m and m.group(3) in _MODOS else "transcribe"
        return caminho, modo

    def remover(self, caminho: str) -> None:
        # Só apaga dentro da própria pasta: o caminho volta de fora como parâmetro.
        if os.path.dirname(os.path.abspath(caminho)) != os.path.abspath(self.pasta):
            return
        for arquivo in (caminho, self._arquivo_de_blocos(caminho), caminho + ".entregue"):
            try:
                os.remove(arquivo)
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"[Pipeline] Não consegui tirar {arquivo} da fila: {e!r}", file=sys.stderr)

    # Reunião fatiada: os blocos já transcritos de um item ficam ao lado dele, para o reenvio
    # transcrever só os que faltam (e, se só a ata falhou, nenhum).
    @staticmethod
    def _arquivo_de_blocos(caminho: str) -> str:
        return caminho + ".blocos.json"

    def ler_blocos(self, caminho: str) -> dict[int, str]:
        try:
            with open(self._arquivo_de_blocos(caminho), "r", encoding="utf-8") as f:
                dados = json.load(f)
            return {int(k): v for k, v in dados.items() if isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            return {}

    def gravar_blocos(self, caminho: str, blocos: dict[int, str]) -> None:
        # Sem o .wav (podado pelo LIMITE no meio de um reenvio longo), o .json ficaria órfão,
        # com a transcrição em texto puro e ninguém para limpá-lo.
        if not blocos or not os.path.exists(caminho):
            return
        try:
            _atomic_write_json(self._arquivo_de_blocos(caminho), {str(k): v for k, v in sorted(blocos.items())})
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: escrita atômica de cache de blocos
            print(f"[Pipeline] Não consegui guardar os blocos já transcritos: {e!r}", file=sys.stderr)

    def marcar_entregue(self, caminho: str) -> None:
        """A transcrição deste item (reunião cuja ata falhou) já foi entregue uma vez."""
        try:
            with open(caminho + ".entregue", "w", encoding="utf-8"):
                pass
        except OSError as e:
            print(f"[Pipeline] Não consegui marcar a entrega de {caminho}: {e!r}", file=sys.stderr)

    def ja_entregue(self, caminho: str) -> bool:
        return os.path.exists(caminho + ".entregue")

    def __len__(self) -> int:
        return len(self.itens())

    def importar_legado(self, caminho_legado: str) -> str | None:
        """Traz para a fila, uma única vez, o last_failed_audio.wav de antes da fila.

        Antes da fila, esse arquivo era o áudio à espera do reenvio, e quem atualizasse com
        um pendente ficava sem oferta de reenviá-lo. Depois da fila ele virou só a cópia das
        recusas definitivas (413, bug), e por isso o marcador: o que for gravado ali depois
        não entra. Devolve o caminho do item criado, ou None.
        """
        marcador = os.path.join(self.pasta, self.MARCADOR_LEGADO)
        if os.path.exists(marcador):
            return None
        os.makedirs(self.pasta, exist_ok=True)
        importado = None
        if os.path.isfile(caminho_legado) and os.path.getsize(caminho_legado) > 0:
            # O arquivo não guardava o modo. Acima do limite da Groq, era quase sempre uma reunião (a
            # única que fatiava então): continua indo como reunião, que entrega a ata e a transcrição.
            # Desde o Bloco 10 todos os modos fatiam, e nenhum desses itens leva mais o 413.
            modo = "meeting" if os.path.getsize(caminho_legado) > self.LIMITE_GROQ else "transcribe"
            destino = os.path.join(self.pasta, self._nome(self._instante_seguinte(), modo))
            # Mover, e não ler e regravar: uma reunião legada passa de 100 MB, e isto roda na
            # abertura, antes da interface. Se a troca falhar (arquivo em uso), nada é marcado e a
            # próxima abertura tenta de novo.
            try:
                os.replace(caminho_legado, destino)
            except OSError as e:
                print(f"[Pipeline] Não consegui mover o áudio legado para a fila: {e!r}", file=sys.stderr)
                return None
            importado = destino
            self._podar()
        with open(marcador, "w", encoding="utf-8") as f:
            f.write(caminho_legado)
        return importado


@dataclass
class PipelineContext:
    """Contexto de entrada para execução de um ciclo de transcrição."""
    wav_bytes: bytes | io.BytesIO
    modo: str = "transcribe"  # 'transcribe', 'translate', 'meeting', 'prompt', 'transform', 'send'
    app_context: tuple[str, str, str] | None = None  # (app_exe, app_title, app_cat)
    selected_text: str | None = None
    is_retry: bool = False
    retry_path: str | None = None  # o item da fila que este reenvio consome
    # Para onde vai o texto (ContextManager.resolver_janela_alvo, no começo da gravação ou do
    # reenvio): a janela e o controle com o foco do teclado; 0 sem eles.
    janela_alvo: int = 0
    foco_alvo: int = 0
    enviar_com_enter: bool = False


@dataclass
class PipelineResult:
    """Resultado estruturado após processamento do pipeline."""
    success: bool
    text: str = ""
    modo: str = "transcribe"
    auto_send: bool = False
    action_type: str = "paste"  # 'paste', 'copy', 'speak', 'none'
    error_message: str | None = None
    error_category: str | None = None  # 'prompt_length', 'rate_limit', 'invalid_key', 'offline_retry', 'general'
    file_path: str | None = None


@dataclass
class _EstadoExecucao:
    """Estado transitório isolado por thread/execução do TranscriptionPipeline."""
    regra_do_app: dict[str, Any] | None = None
    texto_cru: str | None = None
    falha_llm: FalhaDoLLM | None = None
    texto_e_a_fala: bool = True
    motivo_sem_texto: str | None = None
    estado_do_motivo: str = "error"
    blocos: dict[int, str] = field(default_factory=dict)
    fallback_429: tuple[str, str] | None = None


class TranscriptionPipeline:
    """
    Orquestrador desacoplado do ciclo de vida da transcrição.
    Permite injeção de dependências para testes unitários isolados e execução resiliente em produção.
    """

    def __init__(
        self,
        groq_service: Any,
        config_mgr: Any,
        audio_mgr: Any,
        injector: Any,
        sound_mgr: Any | None = None,
        snippet_mgr: Any | None = None,
        tts_mgr: Any | None = None,
        ui_notifier: Callable[[str, str | None], None] | None = None,
        ui_dispatcher: Callable[[Callable, Any], None] | None = None,
        on_caption: Callable[[str], None] | None = None,
        on_pill_text: Callable[[str, bool], None] | None = None,
        on_success_sync: Callable[[], None] | None = None,
        failed_audio_path: str | None = None,
        user_data_dir: str | None = None,
    ):
        self.groq_service = groq_service
        self.config_mgr = config_mgr
        self.audio_mgr = audio_mgr
        self.injector = injector
        self.sound_mgr = sound_mgr
        self.snippet_mgr = snippet_mgr
        self.tts_mgr = tts_mgr
        self.ui_notifier = ui_notifier or (lambda status, msg=None, **_k: None)
        self.ui_dispatcher = ui_dispatcher or (lambda func, *args: func(*args))
        self.on_caption = on_caption
        self.on_pill_text = on_pill_text
        self.on_success_sync = on_success_sync
        self.failed_audio_path = failed_audio_path or FAILED_AUDIO_PATH
        self.user_data_dir = user_data_dir or USER_DATA_DIR
        self.fila = FilaDeAudioFalho(os.path.join(self.user_data_dir, "failed"))
        # Estado por passagem isolado em threading.local (ver _EstadoExecucao e process):
        # chamadas concorrentes ou diretas em diferentes threads não compartilham mutações.
        self._local = threading.local()

    def _estado(self) -> _EstadoExecucao:
        estado = getattr(self._local, "estado", None)
        if estado is None:
            estado = _EstadoExecucao()
            self._local.estado = estado
        return estado

    @property
    def _regra_do_app(self) -> dict[str, Any] | None:
        return self._estado().regra_do_app

    @_regra_do_app.setter
    def _regra_do_app(self, valor: dict[str, Any] | None) -> None:
        self._estado().regra_do_app = valor

    @property
    def _texto_cru(self) -> str | None:
        return self._estado().texto_cru

    @_texto_cru.setter
    def _texto_cru(self, valor: str | None) -> None:
        self._estado().texto_cru = valor

    @property
    def _falha_llm(self) -> FalhaDoLLM | None:
        return self._estado().falha_llm

    @_falha_llm.setter
    def _falha_llm(self, valor: FalhaDoLLM | None) -> None:
        self._estado().falha_llm = valor

    @property
    def _texto_e_a_fala(self) -> bool:
        return self._estado().texto_e_a_fala

    @_texto_e_a_fala.setter
    def _texto_e_a_fala(self, valor: bool) -> None:
        self._estado().texto_e_a_fala = valor

    @property
    def _motivo_sem_texto(self) -> str | None:
        return self._estado().motivo_sem_texto

    @_motivo_sem_texto.setter
    def _motivo_sem_texto(self, valor: str | None) -> None:
        self._estado().motivo_sem_texto = valor

    @property
    def _estado_do_motivo(self) -> str:
        return self._estado().estado_do_motivo

    @_estado_do_motivo.setter
    def _estado_do_motivo(self, valor: str) -> None:
        self._estado().estado_do_motivo = valor

    @property
    def _blocos(self) -> dict[int, str]:
        return self._estado().blocos

    @_blocos.setter
    def _blocos(self, valor: dict[int, str]) -> None:
        self._estado().blocos = valor

    @property
    def _fallback_429(self) -> tuple[str, str] | None:
        return self._estado().fallback_429

    @_fallback_429.setter
    def _fallback_429(self, valor: tuple[str, str] | None) -> None:
        self._estado().fallback_429 = valor

    def _registrar_fallback_429(self) -> None:
        ler = getattr(self.groq_service, "fallback_429_recente", None)
        if callable(ler):
            fb = ler()
            if isinstance(fb, tuple) and len(fb) == 2 and all(isinstance(x, str) for x in fb):
                self._fallback_429 = fb

    def importar_audio_legado(self) -> None:
        """Chamado uma vez na abertura do app (ver FilaDeAudioFalho.importar_legado)."""
        try:
            self.fila.importar_legado(self.failed_audio_path)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: migração de áudio falho legado
            # Sem o marcador, a próxima abertura tenta de novo.
            print(f"[Pipeline] Não consegui importar o áudio legado: {e!r}", file=sys.stderr)

    def _notificar_ui(self, status: str, msg: str | None = None, *, por_cima: bool = False):
        try:
            if por_cima:
                self.ui_notifier(status, msg, por_cima=True)
            else:
                self.ui_notifier(status, msg)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: callback ui_notifier externo
            print(f"[Pipeline] Erro ao notificar UI ({status}): {e!r}", file=sys.stderr)

    def _tocar_som(self, som: str):
        if not self.sound_mgr:
            return
        metodo = getattr(self.sound_mgr, f"sound_{som}", None)
        if callable(metodo):
            try:
                metodo()
            except Exception:  # noqa: BLE001, S110 — fronteira defensiva: áudio de feedback não para ditado
                pass

    def _regra_do_destino(self, context: PipelineContext) -> dict[str, Any] | None:
        """A regra por aplicativo (Contexto Automático) do app que recebe este ditado, ou None.

        Vale para o ditado comum e o que envia com Enter: os outros modos já são escolha de um
        atalho. O app é o de destino do texto, como em _ir_para_a_janela_de_entrega: a janela
        fixada (Ctrl+Alt+F), senão a janela-alvo do começo da gravação. O app_context é o da
        frente quando a gravação começou, que pode ser o próprio painel do Willy. Sem regras,
        nenhuma chamada ao Windows.
        """
        regras = getattr(self.config_mgr, "app_context_rules", None)
        if not isinstance(regras, list) or not regras or context.modo not in ("transcribe", "send"):
            return None
        fixada = ContextManager.get_sticky_window()
        janela = fixada[0] if fixada else context.janela_alvo
        if janela:
            app_exe, titulo, _categoria = ContextManager.get_foreground_app(janela)
        elif context.app_context:
            app_exe, titulo = context.app_context[0], context.app_context[1]
        else:
            app_exe, titulo, _categoria = ContextManager.get_foreground_app()
        return ContextManager.resolve_app_rule(app_exe, titulo, regras)

    @staticmethod
    def _modo_pela_regra(context: PipelineContext, regra: dict[str, Any] | None) -> PipelineContext:
        """O ditado comum e o que envia com Enter viram tradução quando a regra do app pede.
        Precedência: o atalho de tradução (ou qualquer outro modo específico) ganha da regra;
        a regra ganha da config. No ditar e enviar (send), o Enter final continua valendo."""
        modo_da_regra = (regra or {}).get("action_mode")
        if context.modo in ("transcribe", "send") and modo_da_regra in ("translate", "translate_es"):
            return replace(
                context,
                modo=modo_da_regra,
                enviar_com_enter=(context.modo == "send" or context.enviar_com_enter),
            )
        return context

    def process(self, context: PipelineContext) -> PipelineResult:
        """
        Executa os 5 estágios do pipeline de transcrição com proteção atômica e tratamento de erros.
        """
        # A regra por aplicativo antes de tudo: o ditado que vai para a fila (ocupado, sem chave,
        # sem rede) guarda o modo que ela deu, e o reenvio sai como o ditado sairia. Em variável
        # local até o pipeline ser deste ditado: outro em processamento usa a dele.
        regra = self._regra_do_destino(context)
        context = self._modo_pela_regra(context, regra)

        with self.audio_mgr.lock:
            ocupado = self.audio_mgr.is_processing
            if not ocupado:
                self.audio_mgr.is_processing = True
        if ocupado:
            return self._guardar_por_ocupado(context)

        self._local.estado = _EstadoExecucao(regra_do_app=regra)
        limpar_fb = getattr(self.groq_service, "limpar_fallback_429", None)
        if callable(limpar_fb):
            limpar_fb()
        try:
            self._tocar_som("stop")
            self._notificar_ui("processing")

            # 1. Validação de Chave da Groq. Sem ela o ditado se perdia: agora fica na fila, e o
            # reenvio é oferecido quando a chave for configurada.
            if not self.config_mgr.groq_api_key or self.config_mgr.groq_api_key in ("", "sua_chave_aqui"):
                self._tocar_som("error")
                if self._guardar_na_fila(context):
                    self._notificar_ui("error", "Configure sua chave Groq: o áudio ficou salvo")
                else:
                    self._notificar_ui("error", "Configure sua chave Groq")
                return PipelineResult(
                    success=False,
                    error_message="Chave Groq não configurada",
                    error_category="invalid_key",
                    modo=context.modo,
                )

            # Normalização de Buffer WAV
            wav_buf, tamanho_bytes, raw_wav = self._preparar_wav_buffer(context.wav_bytes)

            # 2. Transcrição Bruta (Whisper)
            texto_bruto, auto_send = self._transcrever_audio(wav_buf, tamanho_bytes, context)

            if not texto_bruto:
                self._avisar_nada_a_entregar(context)
                if self._falha_que_passa():  # IA fora: o item fica para quando ela voltar
                    self._guardar_na_fila(context)
                else:
                    self._consumir_reenvio(context)
                return PipelineResult(success=False, text="", modo=context.modo)

            if (context.retry_path and self._falha_llm is not None and self._falha_llm.etapa == "ata"
                    and self.fila.ja_entregue(context.retry_path)):
                # A transcrição já foi entregue quando a ata falhou da primeira vez. Entregar de novo
                # colaria tudo outra vez, com mais um .md, mais uma cópia do .wav e mais um item no
                # histórico, a cada clique enquanto a IA estiver fora.
                self._tocar_som("error")
                if not self._falha_que_passa():
                    # A Groq recusou de novo (não é rede nem limite): o item saía igual a cada clique,
                    # no topo da fila. A transcrição já foi entregue (e, fora do modo privado, está
                    # no histórico).
                    self.fila.remover(context.retry_path)
                    self._notificar_ui("error", _ATA_RECUSADA)
                    return PipelineResult(success=False, error_category="llm", modo=context.modo)
                if not self.config_mgr.private_mode:
                    self.fila.gravar_blocos(context.retry_path, self._blocos)
                self._notificar_ui("offline_retry", "Ata ainda não gerada. Clique p/ reenviar")
                return PipelineResult(success=False, error_category="llm", modo=context.modo)

            # 3. Enriquecimento de Texto (Comandos, Ações, Snippets e Refino)
            texto_final, action_type, auto_send_detect = self._enriquecer_texto(texto_bruto, context)
            if auto_send_detect:
                auto_send = True
            if context.retry_path:
                # O reenvio cola onde o foco está AGORA, talvez outra conversa, e o item pode ser
                # de ontem: o Enter ali não tem volta. A pessoa confere e envia.
                auto_send = False

            if action_type == "speak":
                self._consumir_reenvio(context, reoferecer=False)  # a leitura em voz alta segue
                return PipelineResult(success=True, text=texto_final, action_type="speak", modo=context.modo)

            if not texto_final:
                self._avisar_nada_a_entregar(context)
                if self._falha_que_passa():
                    self._guardar_na_fila(context)
                else:
                    self._consumir_reenvio(context)
                return PipelineResult(success=False, text="", modo=context.modo)

            # 4. Entrega do Resultado (Injeção / Clipboard)
            res = self._entregar_resultado(texto_final, auto_send, context.modo, raw_wav, context.retry_path,
                                       alvo=(context.janela_alvo, context.foco_alvo))
            return res

        except Exception as e:  # noqa: BLE001 — fronteira defensiva: roteamento de erro do pipeline para _tratar_erro
            return self._tratar_erro(e, context.wav_bytes, context.modo, context.retry_path)
        finally:
            with self.audio_mgr.lock:
                self.audio_mgr.is_processing = False

    def _falha_que_passa(self) -> bool:
        """O LLM falhou de um jeito que passa sozinho (rede, 429, 5xx): um item da fila fica para o
        próximo clique. Uma recusa, uma resposta vazia ou um 400 voltam iguais a cada reenvio, e o
        item ficava no topo da fila para sempre."""
        return self._falha_llm is not None and self._falha_llm.transitoria

    def _avisar_nada_a_entregar(self, context: PipelineContext) -> None:
        if self._motivo_sem_texto:
            self._tocar_som("error")
            if context.retry_path:
                # Um "Willy, resuma este contrato" que caiu sem rede volta sem a seleção de
                # antes, e o item sai da fila (_consumir_reenvio): guardado, ele ficaria no topo,
                # reenviado a cada clique, e a bandeja nunca tem seleção. Antes saía calado,
                # como um "cancelado"; agora a pessoa sabe que precisa repetir o pedido.
                self._notificar_ui("error", _PEDIDO_SEM_SELECAO)
            else:
                self._notificar_ui(self._estado_do_motivo, self._motivo_sem_texto)
        elif self._falha_llm is not None and self._falha_llm.etapa in _NADA_A_COLAR:
            # Colar a seleção sobre ela mesma, ou a frase do comando, parecia sucesso.
            self._tocar_som("error")
            aviso = (
                _NADA_A_COLAR_RECUSA[self._falha_llm.etapa]
                if isinstance(self._falha_llm.causa, RecusaDoLLM)
                and self._falha_llm.etapa in _NADA_A_COLAR_RECUSA
                else _NADA_A_COLAR[self._falha_llm.etapa]
            )
            self._notificar_ui("error", aviso)
        else:
            self._notificar_ui("cancelled")

    def _consumir_reenvio(self, context: PipelineContext, reoferecer: bool = True) -> None:
        """O áudio reenviado foi transcrito, mas não há texto a entregar (silêncio, só
        hesitações, o comando "leia", ou um pedido sobre a seleção sem seleção). Sem isto, o
        item ficava no topo da fila para sempre, e o clique reenviava sempre ele, nunca os
        mais antigos."""
        if not context.retry_path:
            return
        self.fila.remover(context.retry_path)
        pendentes = len(self.fila)
        if reoferecer and pendentes:
            if self._motivo_sem_texto:
                # Cabe na pílula (perto de 45 caracteres): com a contagem, o "Clique" era cortado.
                self._notificar_ui("offline_retry", "Sem seleção: descartado. Clique p/ o próximo")
            else:
                self._notificar_ui("offline_retry", f"Nada para colar nesse áudio. Áudios salvos: {pendentes}. Clique p/ reenviar")

    def _guardar_na_fila(self, context: PipelineContext) -> bool:
        """Guarda o áudio do contexto na fila; num reenvio ele já está lá. Devolve se ficou salvo."""
        if context.retry_path:
            return True
        if self.config_mgr.private_mode:
            return False
        try:
            self.fila.guardar(self._preparar_wav_buffer(context.wav_bytes)[2], context.modo)
            return True
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: gravação na fila de áudio falho
            print(f"[Pipeline] O áudio não pôde ser salvo na fila: {e!r}", file=sys.stderr)
            return False

    def _guardar_por_ocupado(self, context: PipelineContext) -> PipelineResult:
        """Um corte por silêncio com outro ditado ainda em processamento descartava o áudio."""
        ocupado = PipelineResult(success=False, error_message="Pipeline ocupado",
                                 error_category="busy", modo=context.modo)
        if not self._guardar_na_fila(context):
            if self.config_mgr.private_mode:
                self._notificar_ui("error", f"Willy ocupado ({_NAO_GUARDADO_NO_PRIVADO})")
            else:
                self._notificar_ui("error", "Willy ocupado: o áudio não pôde ser salvo")
            return ocupado
        self._notificar_ui("offline_retry", "Willy ocupado com o ditado anterior: áudio salvo. Clique p/ reenviar")
        return ocupado

    def _preparar_wav_buffer(self, wav_bytes: bytes | io.BytesIO) -> tuple[io.BytesIO, int, bytes]:
        if isinstance(wav_bytes, io.BytesIO):
            tamanho = wav_bytes.getbuffer().nbytes
            raw = wav_bytes.getvalue()
            wav_buf = wav_bytes
        elif isinstance(wav_bytes, bytes):
            tamanho = len(wav_bytes)
            raw = wav_bytes
            wav_buf = io.BytesIO(wav_bytes)
        else:
            tamanho = 0
            raw = b""
            wav_buf = io.BytesIO()
        return wav_buf, tamanho, raw

    def _transcrever_audio(self, wav_buf: io.BytesIO, tamanho_bytes: int, context: PipelineContext) -> tuple[str, bool]:
        modo = context.modo
        auto_send = (modo == "send") or bool(context.enviar_com_enter)

        if modo == "translate":
            texto = self._transcrever_whisper(wav_buf, tamanho_bytes, context, "Fatiando tradução longa...",
                                              traduzir=True)
            return TextProcessor.apply_voice_commands(texto), auto_send

        if modo == "translate_es":
            # O Whisper só traduz para o inglês: o espanhol sai da fala transcrita em português,
            # limpa e com os comandos de voz ("nova linha") já aplicados, pelo LLM.
            if tamanho_bytes > _LIMITE_SEM_FATIAR:
                texto_bruto = self._transcrever_whisper(wav_buf, tamanho_bytes, context, "Fatiando tradução longa...")
            else:
                # O áudio curto também guarda a transcrição como bloco: se a tradução cair na fila,
                # o reenvio traduz direto, sem chamar o Whisper de novo.
                ja = self.fila.ler_blocos(context.retry_path) if context.retry_path else {}
                texto_bruto = ja.get(0) or self._transcrever_whisper(
                    wav_buf, tamanho_bytes, context, "Fatiando tradução longa...")
                if texto_bruto:
                    self._blocos = {0: texto_bruto}
            if texto_bruto:
                if self.config_mgr.clean_fillers:
                    texto_bruto = self._limpar_cacoetes(texto_bruto)
                texto_bruto = TextProcessor.apply_voice_commands(texto_bruto)
                self._texto_cru = texto_bruto  # o português que a pessoa ditou
                self._notificar_ui("processing", "Willy traduzindo para Espanhol...")
                termos = self.config_mgr.get_vocab_terms()
                termos_fixos = f"Termos da pessoa, que ficam como estão: {', '.join(termos)}" if termos else ""
                try:
                    traduzido = self.groq_service.translate_to_spanish(
                        texto_bruto,
                        extra_context=termos_fixos,
                        estrito=True,
                        progress_callback=lambda msg: self._notificar_ui("processing", msg),
                    )
                    self._registrar_fallback_429()
                    return traduzido, auto_send
                except FalhaDoLLM as falha:
                    self._falha_llm = falha
                    return falha.reserva, False
            return "", auto_send

        if modo == "meeting":
            if tamanho_bytes > _LIMITE_SEM_FATIAR:
                texto_bruto = self._transcrever_whisper(wav_buf, tamanho_bytes, context,
                                                        "Fatiando áudio de reunião longa...")
            else:
                # A reunião curta também guarda a transcrição como bloco: se a ata falhar, o
                # reenvio gera só a ata, sem transcrever (e pagar) a reunião inteira de novo.
                ja = self.fila.ler_blocos(context.retry_path) if context.retry_path else {}
                texto_bruto = ja.get(0) or self.groq_service.transcribe(
                    wav_buf, self.config_mgr.get_prompt_context(), language=self.config_mgr.input_language)
                if texto_bruto:
                    self._blocos = {0: texto_bruto}

            if texto_bruto:
                self._texto_cru = texto_bruto  # a transcrição da reunião, antes da ata
                self._notificar_ui("processing", "Willy gerando Ata Executiva...")
                try:
                    ata = self.groq_service.summarize_meeting(texto_bruto, estrito=True)
                    self._registrar_fallback_429()
                    return ata, auto_send
                except FalhaDoLLM as falha:
                    self._falha_llm = falha
                    return _ATA_AUSENTE + falha.reserva, auto_send
            return "", auto_send

        if modo == "prompt":
            texto_bruto = self._transcrever_whisper(wav_buf, tamanho_bytes, context, "Fatiando pedido longo...")
            if texto_bruto:
                if self.config_mgr.clean_fillers:
                    texto_bruto = self._limpar_cacoetes(texto_bruto)
                self._texto_cru = texto_bruto  # o pedido falado, antes do /goal
                self._notificar_ui("processing", "Willy estruturando Missão de Agente (/goal)...")
                app_exe, app_title, app_cat = context.app_context or ContextManager.get_foreground_app()
                context_instr = ContextManager.get_context_prompt_instruction(app_cat, app_exe)
                git_context = ContextManager.get_git_context(app_title, app_exe)
                combined = f"{context_instr}\n\n{git_context}".strip() if git_context else context_instr
                try:
                    return self.groq_service.generate_agent_prompt(
                        texto_bruto, extra_context=combined, estrito=True), auto_send
                except FalhaDoLLM as falha:
                    self._falha_llm = falha
                    return falha.reserva, auto_send
            return "", auto_send

        if modo == "transform":
            # Sem a seleção lida no atalho (a pessoa segurou o Ctrl+Alt+T, ou é um reenvio), lê
            # agora, antes da transcrição: depois dela, a pessoa pode já estar noutra janela.
            # Sem seleção, não há o que transformar: transform_text(None) acabava num "cancelado".
            base_text = context.selected_text
            if not base_text:
                # Segurando o atalho, a gravação pode acabar com as teclas ainda apertadas (pelo
                # silêncio, ou soltando só o T). Aqui, fora da thread do atalho, dá para esperar
                # mais que os 250 ms dela; e se nem assim, o aviso é esse, e não "selecione". O
                # reenvio não vem do atalho: um Shift no clique não é o atalho preso.
                if not context.retry_path and not ActionManager.esperar_modificadores_soltos(_ESPERA_DO_ATALHO_SOLTO_S):
                    # O áudio tem a instrução falada: perdê-lo obrigava a ditar de novo. Na fila, o
                    # clique na pílula (que não tira o foco do app) o reenvia com as teclas já
                    # soltas, lendo a seleção de então. No modo privado, nada vai para o disco.
                    if self._guardar_na_fila(context):
                        self._motivo_sem_texto = "Solte o atalho. Áudio salvo: clique p/ reenviar"
                        self._estado_do_motivo = "offline_retry"
                    else:
                        self._motivo_sem_texto = "Solte o atalho para transformar"
                    return "", auto_send
                base_text = ActionManager.get_selected_text()
            if not base_text or not base_text.strip():
                self._motivo_sem_texto = "Selecione um texto antes de transformar"
                return "", auto_send
            texto_bruto = self._transcrever_whisper(wav_buf, tamanho_bytes, context, "Fatiando pedido longo...")
            if texto_bruto:
                if self.config_mgr.clean_fillers:
                    texto_bruto = self._limpar_cacoetes(texto_bruto)
                self._notificar_ui("processing", "Willy transformando seleção com IA... 🪄")
                try:
                    transformado = self.groq_service.transform_text(base_text, texto_bruto, estrito=True)
                    self._registrar_fallback_429()
                    return transformado, auto_send
                except FalhaDoLLM as falha:
                    self._falha_llm = falha
                    return "", auto_send
            return "", auto_send

        # Modo Normal / Ditado
        return self._transcrever_whisper(wav_buf, tamanho_bytes, context, "Fatiando ditado longo..."), auto_send

    def _ir_para_a_janela_de_entrega(self, alvo: tuple[int, int]) -> str | None:
        """Põe a janela que recebe o texto na frente. Devolve None para colar, ou o aviso da
        cópia quando colar cairia no lugar errado.

        A janela é a fixada (Ctrl+Alt+F) ou o `alvo` do ditado, se ainda existe. Só com o foco
        noutra janela ela é trazida de volta, com o controle em que a pessoa digitava; com ela
        já na frente, o foco fica onde a pessoa o pôs. Sem ela, com o foco no Willy ou no shell,
        copia. Antes, só a fixada era trazida, e o
        ditado que terminava com o painel do Willy na frente colava dentro dele.
        """
        fixada = ContextManager.get_sticky_window()  # já confere se ela ainda existe
        if fixada:
            janela, foco = fixada[0], 0
        elif ContextManager.janela_existe(alvo[0]):
            janela, foco = alvo
        else:
            janela = foco = 0  # nenhuma, ou fechada durante a transcrição
        if janela:
            if ContextManager.get_foreground_hwnd() == janela or ContextManager.focus_window(
                    janela, foco or None, prazo_s=_ESPERA_DO_FOCO_S):
                return None
            return _NAO_VOLTEI_AO_APP
        # Sem alvo, o Ctrl+V iria para onde o foco está: no Willy, colaria dentro dele; no shell (a
        # reunião que termina com a área de trabalho na frente), em lugar nenhum, e o clipboard
        # voltaria ao de antes: a ata ficaria só no Histórico, e no modo privado nem lá.
        if _foco_numa_janela_do_willy() or _foco_no_shell():
            return _COPIADO_SEM_ALVO
        return None

    def _limpar_cacoetes(self, texto: str) -> str:
        """A limpeza de cacoetes com o vocabulário da pessoa: os termos dele com maiúscula ficam com ela
        depois da vírgula ("Liguei pra operadora, Claro não atende")."""
        return TextProcessor.clean_filler_words(texto, self.config_mgr.get_vocab_terms())

    def _transcrever_whisper(self, wav_buf: io.BytesIO, tamanho_bytes: int, context: PipelineContext,
                             aviso_do_fatiamento: str, traduzir: bool = False) -> str:
        """O Whisper no áudio inteiro, ou em blocos de 10 min acima de _LIMITE_SEM_FATIAR, em
        qualquer modo. Cada bloco transcrito vai para self._blocos assim que sai: numa falha que
        passa (rede, 429, 5xx), eles ficam ao lado do item da fila (_tratar_erro), e o reenvio
        transcreve só os que faltam. `traduzir`: a tradução para o inglês, bloco a bloco."""
        prompt, idioma = self.config_mgr.get_prompt_context(), self.config_mgr.input_language
        if tamanho_bytes <= _LIMITE_SEM_FATIAR:
            if traduzir:
                return self.groq_service.translate(wav_buf, prompt)
            return self.groq_service.transcribe(wav_buf, prompt, language=idioma)
        self._notificar_ui("processing", aviso_do_fatiamento)
        chunks = fatiar_audio_para_whisper(
            wav_buf,
            chunk_seconds=600,
            fatiador=self.audio_mgr.split_audio_into_chunks,
        )

        def _prog(cur, tot):
            self._notificar_ui("processing", f"Transcrevendo bloco {cur} de {tot}...")

        ja = self.fila.ler_blocos(context.retry_path) if context.retry_path else {}
        self._blocos = dict(ja)
        return self.groq_service.transcribe_chunks(
            chunks, prompt, progress_callback=_prog, ja_transcritos=ja,
            ao_transcrever=self._blocos.__setitem__, language=idioma, traduzir=traduzir)

    def _enriquecer_texto(self, texto: str, context: PipelineContext) -> tuple[str, str, bool]:
        """Aplica comandos de voz, copiloto de ações, templates/snippets e refino LLM."""
        if context.modo in ("translate", "translate_es", "meeting", "prompt", "transform"):
            return texto, "paste", False
        # Na fala crua, antes de os comandos de voz virarem sinal: quem ditou "interrogação" ou
        # "ponto" escolheu o sinal, e a etapa de pergunta ou afirmação não passa por cima dele.
        pontuar = (lambda t: t) if TextProcessor.ditou_pontuacao(texto) else TextProcessor.pontuar_perguntas

        # Formatação Rápida de Código por Voz (CamelCase, snake_case, etc.), sobre a fala crua
        # sem o prefixo de envio, sem o de tom e sem as hesitações (como a cadeia de antes os
        # tirava): depois dos comandos de voz, o "ponto" de "variável ponto de venda" já era
        # um ".", e o identificador não saía. Caixa alta e caixa baixa devolvem prosa, e nela
        # os comandos de voz valem: "caixa alta atenção vírgula equipe" é "ATENÇÃO, EQUIPE".
        cru, envio_no_cru = TextProcessor.detect_send_command(texto)
        cru = TextProcessor.detect_voice_tone(cru)[0]
        # O separador falado, que os comandos de voz virariam ":" ("Willy enviar dois pontos
        # variável total"): na fala crua ele sobra na frente do prefixo do identificador.
        cru = re.sub(r"^\s*dois\s+pontos\b[\s,]*", "", cru, flags=re.IGNORECASE)
        if self.config_mgr.clean_fillers:
            cru = self._limpar_cacoetes(cru)
        estilo = TextProcessor.estilo_de_identificador(cru)
        if estilo is not None:
            alvo = TextProcessor.apply_voice_commands(cru) if estilo in ESTILOS_EM_PROSA else cru
            code_id = TextProcessor.format_code_identifier(alvo)
            if code_id is not None:
                self._texto_e_a_fala = False
                return code_id, "paste", envio_no_cru

        texto = TextProcessor.apply_voice_commands(texto)

        # Detecta comando de voz "Willy enviar:" / "Willy mande:"
        texto, voice_send = TextProcessor.detect_send_command(texto)
        auto_send_enter = voice_send

        # Detecta prefixo de tom. Ele tira o "Willy" da frente: o copiloto, mais abaixo, já não
        # o veria, e "Willy em tópicos: resuma este contrato" ia ao refino e era colado como
        # ditado. Um pedido de transformação depois do tom continua sendo ação.
        com_willy = bool(re.match(r"^\s*(?:ei\s+)?willy\b", texto, flags=re.IGNORECASE))
        texto, voice_tone = TextProcessor.detect_voice_tone(texto)
        # Precedência do tom: o falado ("Willy, em tópicos: ...") > o da regra do app > o da config.
        regra = self._regra_do_app or {}
        tom_da_regra = regra.get("tone") if regra.get("tone") not in (None, "", "default") else None
        tom_ativo = voice_tone or tom_da_regra or getattr(self.config_mgr, "output_tone", "natural")
        acao_com_tom = selecao_do_tom = None
        if com_willy and voice_tone and ActionManager.is_transform_command(texto)[0]:
            # Só com texto selecionado: sem seleção, "Willy, em tom formal: corrija o relatório
            # até amanhã" é ditado nesse tom, e virava o aviso "Selecione um texto".
            selecao_do_tom = ActionManager.get_selected_text()
            if selecao_do_tom and selecao_do_tom.strip():
                frase_do_tom = _TOM_NA_INSTRUCAO.get(voice_tone, "")
                acao_com_tom = f"{texto.rstrip(' .!?;:')} {frase_do_tom}".strip()

        if self.config_mgr.clean_fillers and texto:
            texto = self._limpar_cacoetes(texto)

        # Snippets / Templates, antes do copiloto: "Willy, inserir ata de reunião" começa com
        # "Willy," e caía no copiloto, que mandava a frase ao LLM e colava a resposta no lugar
        # do template. O gatilho casa com a fala inteira, então não rouba pedidos ao copiloto.
        if self.snippet_mgr:
            expanded = self.snippet_mgr.match_and_expand(texto)
            if expanded:
                self._texto_e_a_fala = False
                return expanded, "paste", auto_send_enter

        # Copiloto de Ações
        is_action, cmd = ActionManager.is_action_command(texto)
        if acao_com_tom:
            is_action, cmd = True, acao_com_tom
        if is_action:
            self._texto_e_a_fala = False
            is_transf, transf_inst = ActionManager.is_transform_command(cmd)
            if is_transf:
                self._tocar_som("action")
                # A do tom já foi lida: um segundo Ctrl+C só repetiria a volta do clipboard.
                sel_text = selecao_do_tom if acao_com_tom else ActionManager.get_selected_text()
                if not sel_text or not sel_text.strip():
                    # Sem seleção, o transform_text devolvia vazio, o ramo acabava e o refino
                    # colava a própria frase do comando.
                    self._motivo_sem_texto = "Selecione um texto antes de transformar"
                    return "", "paste", auto_send_enter
                self._notificar_ui("processing", "Willy transformando seleção com IA... 🪄")
                try:
                    transf_res = self.groq_service.transform_text(sel_text, transf_inst, estrito=True)
                    self._registrar_fallback_429()
                except FalhaDoLLM as falha:
                    # Sem isto, a seleção era colada sobre ela mesma, ou a frase do comando era
                    # refinada e colada no lugar.
                    self._falha_llm = falha
                    return "", "paste", auto_send_enter
                if not transf_res:
                    self._falha_llm = FalhaDoLLM("transformar", "")
                    return "", "paste", auto_send_enter
                return transf_res, "paste", auto_send_enter
            elif ActionManager.is_speak_command(cmd):
                self._tocar_som("action")
                self._notificar_ui("speaking", "Lendo texto em voz alta... 🔊")
                sel_text = ActionManager.get_selected_text()
                if not sel_text or not sel_text.strip():
                    sel_text = cmd
                if self.tts_mgr:
                    self.tts_mgr.speak_async(
                        sel_text,
                        on_done=lambda: (self._tocar_som("success"), self._notificar_ui("idle", "Leitura concluída ✅"))
                    )
                return sel_text, "speak", auto_send_enter
            else:
                self._tocar_som("action")
                self._notificar_ui("processing", "Willy executando ação...")
                sel_text = ActionManager.get_selected_text()
                try:
                    action_res = ActionManager.process_action(cmd, self.groq_service, sel_text)
                    self._registrar_fallback_429()
                except FalhaDoLLM as falha:
                    if falha.transitoria and falha.causa is not None:
                        raise falha.causa from falha
                    self._falha_llm = FalhaDoLLM("acao", "", falha.causa)
                    return "", "paste", auto_send_enter
                if action_res:
                    return action_res, "paste", auto_send_enter
                # A ação não saiu: seguir para o refino colaria a própria frase do comando.
                self._falha_llm = FalhaDoLLM("acao", "")
                return "", "paste", auto_send_enter

        # Pergunta ou afirmação pelo que as palavras dizem: antes do refino, que confia no sinal
        # que recebe, e valendo também sem ele (perfil Puro, refino desligado, falha do LLM).
        texto = pontuar(texto)

        # Refino LLM. O que entra nele é a fala sem IA: comandos de voz, hesitações e pontuação,
        # o mesmo que sai com o refino desligado. É para isso que o "Restaurar original" volta.
        self._texto_cru = texto
        app_exe, _app_title, app_cat = context.app_context or ContextManager.get_foreground_app()
        context_instr = ContextManager.get_context_prompt_instruction(app_cat, app_exe)
        if regra.get("custom_instruction"):
            context_instr = f"{context_instr}\n\nInstrução da pessoa para este aplicativo: {regra['custom_instruction']}".strip()
        try:
            texto_refinado = self.groq_service.refine_text(
                texto,
                enabled=self.config_mgr.refine_prompt,
                extra_context=context_instr,
                tone=tom_ativo,
                smart_paragraphing=getattr(self.config_mgr, "smart_paragraphing", True),
                profile=getattr(self.config_mgr, "processing_profile", "dev"),
                estrito=True,
            )
            self._registrar_fallback_429()
        except FalhaDoLLM as falha:
            # O texto cru ainda é o melhor que há: entrega, e a pílula diz que veio sem polimento.
            self._falha_llm = falha
            texto_refinado = falha.reserva
        # O refino às vezes devolve o sinal que a etapa acima corrigiu ("Quero saber se posso...?"):
        # as mesmas regras valem na saída dele.
        return pontuar(texto_refinado), "paste", auto_send_enter

    def _aplicar_substituicoes(self, texto: str, texto_cru: str | None) -> tuple[str, str | None]:
        """Aplica substituições fonéticas/personalizadas tanto ao texto final quanto ao texto cru."""
        try:
            reps = self.config_mgr.load_replacements()
            if reps:
                texto = TextProcessor.apply_replacements(texto, reps)
                if texto_cru:
                    texto_cru = TextProcessor.apply_replacements(texto_cru, reps)
        except Exception as rep_err:  # noqa: BLE001 — fronteira defensiva: leitura/aplicação do dicionário fonético
            print(f"[Pipeline] Erro ao aplicar substituições: {rep_err}", file=sys.stderr)
        return texto, texto_cru

    def _entregar_resultado(self, texto: str, auto_send: bool, modo: str, raw_wav: bytes,
                            retry_path: str | None = None,
                            alvo: tuple[int, int] = (0, 0)) -> PipelineResult:
        # Legenda / Teleprompter
        if callable(self.on_caption):
            self.on_caption(texto)

        # Substituições fonéticas. No texto cru também: são regras da pessoa, sem IA, e restaurar
        # o original não pode trazer de volta o "vily" que ela já corrigiu.
        texto, texto_cru = self._aplicar_substituicoes(texto, self._texto_cru)

        # Entrega via Clipboard ou Injeção, na janela-alvo (ver _ir_para_a_janela_de_entrega). O Ctrl+V nunca
        # sai com o foco numa janela do Willy: colaria dentro dele (o painel, o campo da chave), e
        # o texto se perderia. Sem a janela-alvo ou sem conseguir voltar a ela, copia e avisa.
        aviso_da_copia = None
        if not self.config_mgr.clipboard_only:
            aviso_da_copia = self._ir_para_a_janela_de_entrega(alvo)
        copiar_por_foco = aviso_da_copia is not None
        copiar = self.config_mgr.clipboard_only or copiar_por_foco
        action_type = "copy" if copiar else "paste"
        entregue = True
        if copiar:
            entregue = ActionManager.secure_copy(texto)
        else:
            entregue = self.injector.paste_text(texto, auto_send=auto_send)

        if callable(self.on_pill_text):
            self.on_pill_text(texto, action_type == "paste" and bool(entregue))

        msg_fallback_429 = None
        if entregue and self._falha_llm is None and self._fallback_429 is not None:
            escolhido_nome = modelos_llm.nome_amigavel(self._fallback_429[0])
            usado_nome = modelos_llm.nome_amigavel(self._fallback_429[1])
            verbo = "Copiado" if copiar else ("Enviado" if auto_send else "Colado")
            msg_fallback_429 = f"{verbo} com {usado_nome} (limite no {escolhido_nome})"

        if copiar:
            if entregue:
                self._tocar_som("success")
                if copiar_por_foco:
                    self._notificar_ui("success", aviso_da_copia)
                elif msg_fallback_429:
                    self._notificar_ui("success", msg_fallback_429)
                else:
                    self._notificar_ui("success", "Copiado p/ Área de Transferência! 📋")
        else:
            if entregue:
                self._tocar_som("success")
                if msg_fallback_429:
                    self._notificar_ui("success", msg_fallback_429)
                elif auto_send:
                    self._notificar_ui("success", "Enviado com Enter! 🚀")
                else:
                    self._notificar_ui("success")

        if not entregue:
            # O clipboard não foi escrito (ocupado por outro programa): nada foi colado. O
            # texto segue para o histórico abaixo, de onde o usuário consegue copiá-lo.
            self._tocar_som("error")
            if self.config_mgr.private_mode:
                self._notificar_ui("error", "Não consegui colar (clipboard ocupado)")
            else:
                self._notificar_ui("error", "Não consegui colar. O texto ficou no histórico")

        # Ata que falhou: a transcrição foi entregue, mas o áudio fica (ou continua) na fila,
        # para a ata sair num reenvio.
        # No modo privado, o áudio novo não vai para o disco; um item que já estava na fila (de
        # antes de ligar o modo) continua lá, sem ganhar os blocos transcritos, e recebe só o
        # marcador vazio de entregue.
        privado = bool(self.config_mgr.private_mode)
        # Num reenvio, só a falha que passa sozinha guarda o item: a recusa voltaria igual.
        guarda_para_a_ata = (self._falha_llm is not None and self._falha_llm.etapa == "ata"
                             and ((bool(retry_path) and self._falha_que_passa())
                                  or (not retry_path and not privado)))
        if guarda_para_a_ata:
            try:
                item = retry_path or self.fila.guardar(raw_wav, modo)
                if not item:
                    guarda_para_a_ata = False
                else:
                    if not privado:
                        # Com os blocos ao lado, o reenvio só gera a ata, sem transcrever de novo.
                        self.fila.gravar_blocos(item, self._blocos)
                    if entregue:
                        # Um marcador vazio, sem áudio nem texto: no modo privado também, senão o
                        # reenvio seguinte colaria a transcrição outra vez.
                        self.fila.marcar_entregue(item)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: persistência de áudio para reenvio da ata
                guarda_para_a_ata = False
                print(f"[Pipeline] Ata não gerada, e o áudio não pôde ser salvo: {e!r}", file=sys.stderr)

        if entregue:
            # Só o reenvio entregue consome o seu item. Um ditado comum não apaga nada da fila,
            # e, havendo áudio guardado, a pílula volta a oferecer o reenvio: sem isso o estado
            # clicável sumia no primeiro ditado que desse certo.
            if retry_path and not guarda_para_a_ata:
                self.fila.remover(retry_path)
            pendentes = len(self.fila)
            if pendentes:
                # Sem dizer "entregue" quando o reenvio só copiou: a pessoa ainda precisa colar.
                inicio = "Copiado: cole onde quiser" if copiar_por_foco else "Texto entregue"
                self._notificar_ui("offline_retry", f"{inicio}. Áudios salvos: {pendentes}. Clique p/ reenviar")
        if entregue and self._falha_llm is not None and self._falha_llm.etapa in _AVISO_DA_FALHA:
            # Por último, para não ser atropelado: o texto foi, mas não como deveria. Com áudio na
            # fila, o aviso vai junto do reenvio, senão apagaria o estado clicável.
            estado, mensagem, curto = (
                _AVISO_DA_RECUSA[self._falha_llm.etapa]
                if isinstance(self._falha_llm.causa, RecusaDoLLM)
                and self._falha_llm.etapa in _AVISO_DA_RECUSA
                else _AVISO_DA_FALHA[self._falha_llm.etapa]
            )
            nao_salvo = _NAO_GUARDADO_NO_PRIVADO if privado else "o áudio não pôde ser salvo"
            if self._falha_llm.etapa == "ata" and not guarda_para_a_ata:
                # Sem o áudio guardado, não há o que reenviar.
                estado, mensagem = "error", (_ATA_RECUSADA if retry_path else f"Ata não gerada ({nao_salvo})")
            pendentes = len(self.fila)
            # A cópia no lugar da colagem também é notícia: o aviso da falha cobriria o dela, e a
            # pessoa não saberia que precisa colar.
            if curto and copiar_por_foco:
                mensagem = f"{curto}: copiado, cole com Ctrl+V"
            elif copiar_por_foco and self._falha_llm.etapa == "ata":
                if estado == "offline_retry":
                    mensagem = "Ata não gerada; transcrição copiada. Clique p/ reenviar"
                elif retry_path:
                    mensagem = "Ata recusada: saiu da fila; transcrição copiada"
                else:
                    # No modo privado, a transcrição não vai para o Histórico nem para o disco: o
                    # clipboard é o único lugar em que ela está.
                    mensagem = f"Ata não gerada; transcrição copiada ({nao_salvo})"
            if curto and pendentes:
                copiado = ", copiado" if copiar_por_foco else ""
                self._notificar_ui("offline_retry", f"{curto}{copiado}. Áudios salvos: {pendentes}. Clique p/ reenviar")
            else:
                self._notificar_ui(estado, mensagem)

        # Persistência. Fica fora do caminho de erro da transcrição: o texto JÁ foi entregue,
        # e cair em _tratar_erro ofereceria um "reenviar" que colaria tudo de novo.
        file_path = None
        if not self.config_mgr.private_mode:
            modo_reg = "send" if (auto_send and modo not in ("translate", "translate_es")) else modo
            try:
                file_path = self.config_mgr.save_output_file(texto, modo=modo_reg, wav_bytes=raw_wav)
                wav_salvo = getattr(self.config_mgr, "last_saved_wav_path", None)
                kwargs_hist: dict[str, Any] = {
                    "modo": modo_reg,
                    "file_path": file_path,
                    "duracao_s": _segundos_do_wav(raw_wav) if self._texto_e_a_fala else None,
                    "raw_text": texto_cru,
                }
                if isinstance(wav_salvo, str) and wav_salvo:
                    kwargs_hist["audio_path"] = wav_salvo
                self.config_mgr.save_history_item(texto, **kwargs_hist)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: persistência pós-entrega em arquivo/histórico
                print(f"[Pipeline] Texto entregue, mas a persistência falhou: {e!r}", file=sys.stderr)
                self._notificar_ui("error", "Texto entregue, mas o histórico não foi salvo")

        if callable(self.on_success_sync):
            self.on_success_sync()

        return PipelineResult(
            success=True,
            text=texto,
            modo=modo,
            auto_send=auto_send,
            action_type=action_type,
            file_path=file_path
        )

    def _tratar_erro(self, exc: Exception, wav_bytes: bytes | io.BytesIO, modo: str,
                     retry_path: str | None = None) -> PipelineResult:
        self._tocar_som("error")

        cat = _classificar_erro(exc)
        raw_to_save = wav_bytes.getvalue() if isinstance(wav_bytes, io.BytesIO) else wav_bytes
        privado = bool(self.config_mgr.private_mode)
        salvo = avulso = False
        # 403 é permissão (modelo bloqueado para a conta, organização restrita): trocar a chave nem
        # sempre resolve, e o item ficaria eterno no topo da fila, reoferecido a cada ditado.
        vai_para_a_fila = cat in _CATEGORIAS_DA_FILA and not isinstance(exc, groq.PermissionDeniedError)
        try:
            if vai_para_a_fila:
                # O reenvio que falha de novo continua na fila: guardar outra vez duplicaria.
                # No modo privado, só ele: o que ainda não está no disco não vai.
                if retry_path or not privado:
                    item = retry_path or self.fila.guardar(raw_to_save, modo)
                    salvo = True
                    if not privado:
                        # Reunião que caiu no meio: os blocos já transcritos ficam ao lado do item.
                        self.fila.gravar_blocos(item, self._blocos)
            else:
                # O mesmo áudio não passa (413, 403, bug nosso): fica a cópia avulsa, fora da
                # fila, que a pílula não oferece reenviar.
                if not privado:
                    with open(self.failed_audio_path, "wb") as f:
                        f.write(raw_to_save)
                    avulso = True
                if retry_path:
                    self.fila.remover(retry_path)
        except Exception as cache_err:  # noqa: BLE001 — fronteira defensiva: gravação de cache de áudio falho em disco
            print(f"[Pipeline] Erro ao salvar cache de áudio: {cache_err}", file=sys.stderr)

        status = getattr(exc, "status_code", None)
        # Sem o áudio guardado, "áudio salvo. Clique p/ reenviar" mentia: o clique não tem o quê.
        nao_salvo = _NAO_GUARDADO_NO_PRIVADO if privado else "o áudio não pôde ser salvo"
        if cat == "prompt_length":
            self._notificar_ui("error", "Erro: Prompt muito longo para Whisper")
        elif cat == "rate_limit":
            if salvo:
                # Estado clicável: depois da espera, o MESMO áudio passa.
                self._notificar_ui("offline_retry", "Limite da Groq atingido: áudio salvo. Clique p/ reenviar")
            else:
                self._notificar_ui("error", f"Limite da Groq ({nao_salvo})")
        elif cat == "invalid_key":
            if salvo:
                self._notificar_ui("error", "Chave Groq inválida ou sem permissão: o áudio ficou salvo")
            else:
                self._notificar_ui("error", "Chave Groq inválida ou sem permissão")
        elif cat == "offline_retry":
            causa = "Groq instável" if isinstance(exc, groq.InternalServerError) else "Sem internet"
            if salvo:
                self._notificar_ui("offline_retry", f"{causa}: áudio salvo. Clique p/ reenviar")
            else:
                self._notificar_ui("error", f"{causa} ({nao_salvo})")
        elif cat == "bad_request":
            # 400/413/422: reenviar o mesmo arquivo nunca vai funcionar, então sem "reenviar".
            self._notificar_ui("error", f"A Groq recusou o áudio (HTTP {status})")
        elif avulso:
            self._notificar_ui("error", "Erro interno do Willy: áudio salvo em last_failed_audio.wav")
        else:
            self._notificar_ui("error", f"Erro interno ({nao_salvo})")

        print(f"[Pipeline] Erro ({cat}): {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            log_path = os.path.join(self.user_data_dir, "willy_errors.log")
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erro pipeline ({modo}, {cat}): "
                         f"{type(exc).__name__}: {exc}\n")
                if cat == "internal":
                    # Bug nosso: o traceback é o que permite consertar.
                    lf.write("".join(traceback.format_exception(exc)))
        except Exception as log_err:  # noqa: BLE001 — fronteira defensiva: gravação de willy_errors.log
            print(f"[Pipeline] Erro ao gravar willy_errors.log: {log_err!r}", file=sys.stderr)

        return PipelineResult(
            success=False,
            error_message=str(exc),
            error_category=cat,
            modo=modo
        )

    def transcrever_arquivo_externo(self, caminho_arquivo: str, gerar_ata: bool = False) -> str | None:
        """
        Transcreve um arquivo de áudio local (.mp3, .wav, .m4a, .ogg, .flac).
        Se gerar_ata=True, resume estruturadamente em formato de Ata Executiva.
        Salva no histórico (com duracao_s e audio_path), copia para o clipboard e notifica a UI.
        """
        if not self.config_mgr.groq_api_key or self.config_mgr.groq_api_key in ("", "sua_chave_aqui"):
            self._tocar_som("error")
            self._notificar_ui("error", "Configure sua chave Groq")
            return None

        with self.audio_mgr.lock:
            ocupado = self.audio_mgr.is_processing or self.audio_mgr.is_recording
            if not ocupado:
                self.audio_mgr.is_processing = True
        if ocupado:
            self._notificar_ui("error", "Aguarde o processo atual...", por_cima=True)
            self._tocar_som("error")
            return None

        try:
            self._notificar_ui("processing", "Transcrevendo arquivo...")

            def _prog(msg: str) -> None:
                self._notificar_ui("processing", msg)

            texto = self.groq_service.transcribe_file(
                caminho_arquivo,
                self.config_mgr.get_prompt_context(),
                progress_callback=_prog,
                language=self.config_mgr.input_language,
            )

            if not texto:
                self._notificar_ui("cancelled")
                return None

            if self.config_mgr.clean_fillers and not gerar_ata:
                texto = self._limpar_cacoetes(texto)
            if not gerar_ata:
                texto = TextProcessor.pontuar_perguntas(texto)

            modo_registro = "transcribe"
            texto_cru = None
            if gerar_ata:
                texto_cru = texto
                self._notificar_ui("processing", "Willy gerando Ata Executiva...")
                try:
                    texto = self.groq_service.summarize_meeting(texto, estrito=True)
                except FalhaDoLLM as falha:
                    texto = _ATA_AUSENTE + falha.reserva
                modo_registro = "meeting"

            texto, texto_cru = self._aplicar_substituicoes(texto, texto_cru)

            if ActionManager.secure_copy(texto, ocultar_do_historico=bool(self.config_mgr.private_mode)):
                self._tocar_som("success")
                self._notificar_ui("success")
            else:
                self._tocar_som("error")
                if self.config_mgr.private_mode:
                    self._notificar_ui("error", "Transcrito, mas não consegui copiar (clipboard ocupado)")
                else:
                    self._notificar_ui("error", "Transcrito, mas não consegui copiar. O texto ficou no histórico")

            if not self.config_mgr.private_mode:
                try:
                    file_path = self.config_mgr.save_output_file(texto, modo=modo_registro)
                    wav_salvo = getattr(self.config_mgr, "last_saved_wav_path", None)
                    caminho_audio = (
                        wav_salvo
                        if isinstance(wav_salvo, str) and wav_salvo
                        else (caminho_arquivo if caminho_arquivo and os.path.exists(caminho_arquivo) else None)
                    )
                    self.config_mgr.save_history_item(
                        texto,
                        modo=modo_registro,
                        file_path=file_path,
                        audio_path=caminho_audio,
                        duracao_s=_segundos_do_arquivo_audio(caminho_arquivo),
                        raw_text=texto_cru,
                    )
                except Exception as e:  # noqa: BLE001 — fronteira defensiva: persistência de transcrição externa
                    print(f"[Willy] Transcrição entregue, mas o histórico não foi salvo: {e!r}", file=sys.stderr)
                    self._notificar_ui("error", "Transcrito e copiado, mas o histórico não foi salvo")

            if callable(self.on_success_sync):
                self.on_success_sync()

            return texto
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: transcrição de arquivo externo
            self._tocar_som("error")
            self._notificar_ui("error", f"Erro: {e}")
            print(f"[Willy] Erro na transcrição de arquivo: {e}", file=sys.stderr)
            return None
        finally:
            with self.audio_mgr.lock:
                self.audio_mgr.is_processing = False
