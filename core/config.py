"""
Módulo de Configuração & Persistência do Willy.
Gerencia caminhos de diretórios (AppData vs Local), leitura e escrita do .env,
histórico de transcrições e vocabulário personalizado.
"""

import math
import os
import re
import sys
import time

try:
    import keyring
except ImportError:
    keyring = None
from typing import Any

from dotenv import dotenv_values, load_dotenv

# Diretório base da aplicação
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Diretório padrão para armazenamento estruturado de arquivos do usuário (Documentos\Willy)
DEFAULT_OUTPUTS_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Willy")

USER_DATA_DIR = ""
ENV_FILE = ""
HISTORY_FILE = ""
REPLACEMENTS_FILE = ""
VOCAB_FILE = ""
APP_RULES_FILE = ""
FAILED_AUDIO_PATH = ""
FLAG_SHOW_DASHBOARD = ""


def definir_diretorio_dados(diretorio: str | None = None) -> str:
    """Atualiza as constantes de caminho de dados do usuário sem efeitos colaterais de I/O em disco."""
    global USER_DATA_DIR, ENV_FILE, HISTORY_FILE, REPLACEMENTS_FILE, VOCAB_FILE, APP_RULES_FILE, FAILED_AUDIO_PATH, FLAG_SHOW_DASHBOARD
    if diretorio:
        USER_DATA_DIR = diretorio
    elif getattr(sys, "frozen", False):
        USER_DATA_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "Willy")
    else:
        # Rodando do código-fonte, os dados ficam na pasta do repositório. WILLY_DATA_DIR troca essa
        # pasta: os testes que importam o willy.py num processo à parte a apontam para uma pasta
        # temporária, e o .env de verdade, o histórico e os snippets do repo não são lidos nem
        # criados.
        USER_DATA_DIR = os.environ.get("WILLY_DATA_DIR") or BASE_DIR
    ENV_FILE = os.path.join(USER_DATA_DIR, ".env")
    HISTORY_FILE = os.path.join(USER_DATA_DIR, ".history.json")
    REPLACEMENTS_FILE = os.path.join(USER_DATA_DIR, ".replacements.json")
    VOCAB_FILE = os.path.join(USER_DATA_DIR, "vocabulario.txt")
    APP_RULES_FILE = os.path.join(USER_DATA_DIR, ".app_rules.json")
    FAILED_AUDIO_PATH = os.path.join(USER_DATA_DIR, "last_failed_audio.wav")
    # Flag para sinalização de foco entre instâncias
    FLAG_SHOW_DASHBOARD = os.path.join(USER_DATA_DIR, ".show_dashboard")
    return USER_DATA_DIR


definir_diretorio_dados()


def criar_env_do_template() -> None:
    """Inicializa a pasta de dados, o .env a partir do .env.template (e o vocabulario.txt no executável).

    Era feito na importação deste módulo: num clone novo (o CI, uma worktree), todo teste que
    importa core.config deixava um .env na raiz, e uma segunda instância tocava o AppData antes
    da trava de instância única.
    """
    import shutil

    try:
        os.makedirs(USER_DATA_DIR, exist_ok=True)
    except OSError as e:
        print(f"[Config] Falha ao criar diretório de dados ({USER_DATA_DIR}): {e!r}", file=sys.stderr)
        return

    em_frozen = getattr(sys, "frozen", False)
    if not os.path.exists(ENV_FILE):
        template_env = os.path.join(BASE_DIR, ".env.template")
        if not os.path.exists(template_env) and hasattr(sys, "_MEIPASS"):
            template_env = os.path.join(sys._MEIPASS, ".env.template")
        if os.path.exists(template_env):
            try:
                shutil.copyfile(template_env, ENV_FILE)
            except OSError as e:
                print(f"[Config] Falha ao copiar .env.template para {ENV_FILE}: {e!r}", file=sys.stderr)
        elif em_frozen:
            try:
                with open(ENV_FILE, "w", encoding="utf-8") as f:
                    f.write("GROQ_API_KEY=\nONBOARDING_COMPLETED=false\n")
            except OSError as e:
                print(f"[Config] Falha ao inicializar {ENV_FILE}: {e!r}", file=sys.stderr)

    if em_frozen and not os.path.exists(VOCAB_FILE):
        default_vocab = os.path.join(BASE_DIR, "vocabulario.txt")
        if not os.path.exists(default_vocab) and hasattr(sys, "_MEIPASS"):
            default_vocab = os.path.join(sys._MEIPASS, "vocabulario.txt")
        if os.path.exists(default_vocab):
            try:
                shutil.copyfile(default_vocab, VOCAB_FILE)
            except OSError as e:
                print(f"[Config] Falha ao copiar vocabulario.txt para {VOCAB_FILE}: {e!r}", file=sys.stderr)

# "Willy" primeiro: é o nome do assistente, e fora do vocabulário o Whisper escrevia "Weeley" e
# "Willi". O corte do orçamento tira o fim da base; com o vocabulário da pessoa cheio, a base
# inteira sai, e por isso o get_prompt_context também o põe entre os termos dela.
DEV_PROMPT_CONTEXT = (
    "Vocabulário técnico de programação e desenvolvimento de software: "
    "Willy, TypeScript, JavaScript, Python, API, async, await, Docker, SQL, Git, GitHub, "
    "bug, frontend, backend, endpoint, deploy, CSS, HTML, React, Node, JSON, return, "
    "function, pull request, PR, merge, commit, branch, test, class, interface, enum, "
    "payload, token, database, webhook, middleware, websocket, cache, route, query."
)

# O cabeçalho em português: o "Bilingual software, tech and business vocabulary:" em inglês
# induzia o Whisper a trocar de idioma nas pausas de um ditado em português.
DEV_PROMPT_CONTEXT_BILINGUAL = (
    f"{DEV_PROMPT_CONTEXT} "
    "Vocabulário bilíngue de software, tecnologia e negócios: "
    "meeting, feedback, schedule, budget, deadline, roadmap, sprint, pipeline, release."
)

DEV_PROMPT_CONTEXT_EN = (
    "Technical programming, software development, and professional vocabulary: "
    "Willy, TypeScript, JavaScript, Python, API, async, await, Docker, SQL, Git, GitHub, "
    "bug, frontend, backend, endpoint, deploy, CSS, HTML, React, Node, JSON, return, "
    "function, pull request, PR, merge, commit, branch, test, class, interface, enum, "
    "payload, token, database, webhook, middleware, websocket, cache, route, query, "
    "meeting, schedule, feedback, sprint, backlog, release, architecture."
)

SAMPLE_RATE = 16000
CHANNELS = 1


from core import modelos_llm
from core.storage.caminhos import caminho_local_absoluto
from core.storage.history_store import HistoryStore
from core.storage.settings_store import AppRulesStore, SettingsStore
from core.storage.vocabulary_store import VocabularyStore

# Faixas aceitas de fora (perfil importado, .env editado à mão). A UI fica dentro delas:
# silêncio de 1,0 a 3,5 s e ganho de 1,0x a 2,5x.
SILENCE_SECONDS_MIN, SILENCE_SECONDS_MAX = 0.5, 10.0
MIC_GAIN_MIN, MIC_GAIN_MAX = 0.5, 4.0
# Os limiares de silêncio e de fala comparam o RMS do áudio, que vai de 0 a 1. Em 0, tudo é
# fala e o silêncio nunca chega; acima de 0,5, só um grito conta como fala.
LIMIAR_RMS_MIN, LIMIAR_RMS_MAX = 0.0001, 0.5

TONS_DE_SAIDA_VALIDOS = ("natural", "formal", "concise", "bullet_points", "technical")
IDIOMAS_DE_ENTRADA_VALIDOS = ("auto", "pt", "en")
POSICOES_DA_PILULA_VALIDAS = ("centro_inferior", "topo", "seguir_cursor")

# os.startfile executa o que receber: um .exe ou .lnk vindo de um perfil importado rodaria
# com um clique no histórico.
EXTENSOES_ABRIVEIS = (".md", ".wav", ".txt")


def _parse_bool(valor: Any, atual: bool = False) -> bool:
    """Converte o valor de uma opção liga/desliga.

    bool("false") é True: um perfil com "false" LIGAVA a opção. Strings seguem a mesma
    regra do reload(); o que não for reconhecível mantém `atual`.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int) and valor in (0, 1):
        return bool(valor)
    if isinstance(valor, str):
        texto = valor.strip().lower()
        if texto in ("true", "1", "yes"):
            return True
        if texto in ("false", "0", "no", ""):
            return False
    return atual


def _parse_indice_dispositivo(valor: Any) -> int | None:
    """Índice de dispositivo de áudio, ou None.

    isdecimal e não isdigit ("²".isdigit() é True e int("²") levanta), e no máximo 6
    dígitos: com mais de 4300 o int() levanta ValueError, no meio do save_settings.
    """
    texto = "" if valor is None else str(valor).strip()
    return int(texto) if texto.isdecimal() and len(texto) <= 6 else None


def _parse_float_limitado(valor: Any, minimo: float, maximo: float, atual: float) -> float:
    """float finito dentro de [minimo, maximo]; qualquer outra coisa mantém `atual`."""
    if isinstance(valor, bool):
        return atual
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return atual
    if not math.isfinite(numero) or not (minimo <= numero <= maximo):
        return atual
    return numero


# Onde a chave da Groq mora no Windows Credential Manager.
COFRE_SERVICO, COFRE_USUARIO = "WillyAssistant", "GROQ_API_KEY"

# Catálogo extensível de credenciais suportadas pelo Willy: novos provedores futuros
# entram aqui para aparecer automaticamente no guia inicial e no card de Credenciais.
CREDENCIAS_DO_WILLY: tuple[dict[str, Any], ...] = (
    {
        "id": "groq",
        "env_var": "GROQ_API_KEY",
        "nome": "Groq Cloud",
        "obrigatoria": True,
        "gratuita": True,
        "sem_cartao": True,
        "url_chaves": "https://console.groq.com/keys",
        "resumo": "Transcrição Whisper e refino inteligente de texto em nuvem.",
        "passos": [
            "Acesse console.groq.com/keys e entre com sua conta Google ou GitHub.",
            "Clique em Create API Key, dê um nome como Willy e confirme.",
            "Copie a chave que começa com gsk_ e cole no campo abaixo.",
        ],
    },
)


def credenciais_do_willy(cfg_mgr: "ConfigManager | None" = None) -> list[dict[str, Any]]:
    """Lista de credenciais com status atual de preenchimento em memória/cofre."""
    resultado: list[dict[str, Any]] = []
    for item in CREDENCIAS_DO_WILLY:
        env_var = item["env_var"]
        if cfg_mgr is not None and env_var == "GROQ_API_KEY":
            configurada = bool(cfg_mgr.chave_configurada())
        else:
            configurada = bool(os.getenv(env_var, "").strip())
        copia = dict(item)
        copia["passos"] = list(item["passos"])
        copia["configurada"] = configurada
        resultado.append(copia)
    return resultado


def cofre_do_sistema():
    """O keyring do sistema, para ConfigManager(cofre=...); None se o pacote faltar."""
    return keyring


from core.hotkey import tecla_do_atalho


class ConfigManager:
    """Gerenciador centralizado de preferências e persistência do Willy."""

    def __init__(self, cofre=None):
        """`cofre` guarda a chave da Groq (get_password/set_password, a interface do keyring).

        Sem cofre, a chave fica no .env. O padrão é None de propósito: só o app de verdade
        passa cofre_do_sistema(), e nenhum teste que constrói ConfigManager() alcança o
        Credential Manager da máquina.
        """
        self.cofre = cofre
        self.cofre_ilegivel = False
        # O último import_profile descartou a chave do perfil porque já havia uma configurada.
        self.chave_do_perfil_ignorada = False
        self.history_store = HistoryStore(lambda: HISTORY_FILE)
        self.vocab_store = VocabularyStore(lambda: VOCAB_FILE, lambda: REPLACEMENTS_FILE)
        self.settings_store = SettingsStore(lambda: ENV_FILE)
        self.app_rules_store = AppRulesStore(lambda: APP_RULES_FILE)
        self.reload()

    def chave_configurada(self) -> str:
        """A chave em uso, ou "" se não há nenhuma (o placeholder não conta).

        Confere também o cofre: se a leitura dele falhou no boot, a memória fica vazia com uma
        chave guardada lá, e quem pergunta "há chave?" (o import de perfil) a trocaria.
        """
        chave = (self.groq_api_key or "").strip()
        if not chave or chave == "sua_chave_aqui":
            chave = self._ler_cofre()
        return "" if chave == "sua_chave_aqui" else chave

    def _ler_cofre(self) -> str:
        self.cofre_ilegivel = False
        if self.cofre is None:
            return ""
        try:
            return (self.cofre.get_password(COFRE_SERVICO, COFRE_USUARIO) or "").strip()
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: backend keyring do sistema operacional
            self.cofre_ilegivel = True
            print(f"[ConfigManager] Cofre ilegível: {type(e).__name__}", file=sys.stderr)
            return ""

    def _gravar_cofre(self, chave: str) -> bool:
        if self.cofre is None:
            return False
        try:
            self.cofre.set_password(COFRE_SERVICO, COFRE_USUARIO, chave)
            return True
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: escrita no cofre de credenciais do SO
            print(f"[ConfigManager] Cofre indisponível, a chave fica no .env: {type(e).__name__}",
                  file=sys.stderr)
            return False

    def _apagar_cofre(self) -> None:
        if self.cofre is None:
            return
        try:
            self.cofre.delete_password(COFRE_SERVICO, COFRE_USUARIO)
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: remoção no cofre de credenciais do SO
            # PasswordDeleteError é "já não estava lá"; o resto, cofre fora do ar.
            print(f"[ConfigManager] Não apaguei a chave do cofre: {type(e).__name__}", file=sys.stderr)

    def _carregar_chave_e_migrar(self, incluir_os_env: bool = True) -> str:
        """Lê a chave do .env, do cofre ou de pastas candidatas e migra do arquivo para o cofre."""
        # O que está escrito no arquivo, e não no ambiente: é isso que a migração limpa.
        chave_no_env = (dotenv_values(ENV_FILE).get("GROQ_API_KEY") or "").strip()
        chave_no_cofre = self._ler_cofre()
        # Com o cofre funcionando, o Willy nunca grava a chave no .env. A que estiver lá é a
        # mais recente (o .env de antes do cofre, uma edição à mão, um save em que o cofre
        # falhou), então ganha da que está no cofre.
        chave_real_no_env = "" if chave_no_env == "sua_chave_aqui" else chave_no_env
        fallback_env = os.getenv("GROQ_API_KEY", "").strip() if incluir_os_env else ""
        if fallback_env == "sua_chave_aqui":
            fallback_env = ""
        chave = chave_real_no_env or chave_no_cofre or fallback_env

        # Busca chave em pastas candidatas caso ainda esteja vazia (o .env antigo ao lado do
        # executável). Aqui havia um self.save_settings(), chamado antes de existirem os
        # atributos que ele lê: levantava AttributeError, o except engolia, e nada era gravado.
        env_candidato = None
        if not chave or chave == "sua_chave_aqui":
            candidate_dirs = [
                BASE_DIR,
                os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else BASE_DIR,
            ]
            for d in candidate_dirs:
                cand_env = os.path.join(d, ".env")
                if os.path.exists(cand_env) and os.path.abspath(cand_env) != os.path.abspath(ENV_FILE):
                    try:
                        cand_k = (dotenv_values(cand_env).get("GROQ_API_KEY") or "").strip()
                    except (OSError, ValueError) as e:
                        print(f"[ConfigManager] .env candidato ilegível ({cand_env}): {e!r}", file=sys.stderr)
                        continue
                    if cand_k and cand_k != "sua_chave_aqui":
                        chave = cand_k
                        env_candidato = cand_env
                        break

        # Migração: a chave vai para o cofre e sai do .env. Sem cofre, ou com ele falhando,
        # fica no .env, como antes.
        if chave and chave != "sua_chave_aqui":
            no_cofre = chave_no_cofre == chave or self._gravar_cofre(chave)
            if no_cofre and chave_no_env:
                self.settings_store.save_settings({"GROQ_API_KEY": ""})
            if no_cofre and env_candidato:
                # A chave guardada no cofre também sai do .env antigo; as outras linhas ficam.
                SettingsStore(env_candidato).save_settings({"GROQ_API_KEY": ""})

        if (not chave or chave == "sua_chave_aqui") and self.cofre_ilegivel:
            return ""

        self.groq_api_key = "" if chave == "sua_chave_aqui" else chave
        return self.groq_api_key

    def recarregar_chave_do_cofre(self) -> bool:
        """Reverifica cofre do sistema e .env sem reiniciar o app; devolve True se há chave."""
        return bool(self._carregar_chave_e_migrar(incluir_os_env=False))

    def precisa_onboarding(self) -> bool:
        """Indica se o guia inicial de boas-vindas deve ser exibido ao usuário."""
        return not self.onboarding_completed

    def reload(self):
        """Recarrega os valores a partir do arquivo .env (e a chave da Groq, do cofre)."""
        load_dotenv(ENV_FILE, override=True)
        self.groq_api_key = ""
        self._carregar_chave_e_migrar(incluir_os_env=True)

        self.hotkey = os.getenv("VOICE_HOTKEY", "ctrl+space").strip()
        self.translate_hotkey = os.getenv("TRANSLATE_HOTKEY", "ctrl+alt+space").strip()
        self.translate_es_hotkey = os.getenv("TRANSLATE_ES_HOTKEY", "ctrl+alt+n").strip()
        self.master_hotkey = os.getenv("MASTER_HOTKEY", "ctrl+shift+space").strip()
        self.meeting_hotkey = os.getenv("MEETING_HOTKEY", "ctrl+alt+r").strip()
        self.prompt_hotkey = os.getenv("PROMPT_HOTKEY", "ctrl+alt+p").strip()
        self.history_hotkey = os.getenv("HISTORY_HOTKEY", "ctrl+alt+h").strip()
        self.undo_hotkey = os.getenv("UNDO_HOTKEY", "ctrl+alt+z").strip()
        self.send_hotkey = os.getenv("SEND_HOTKEY", "ctrl+shift+enter").strip()
        self.speak_hotkey = os.getenv("SPEAK_HOTKEY", "ctrl+alt+s").strip()
        self.sticky_hotkey = os.getenv("STICKY_HOTKEY", "ctrl+alt+f").strip()
        self.captions_hotkey = os.getenv("CAPTIONS_HOTKEY", "ctrl+alt+l").strip()
        self.transform_hotkey = os.getenv("TRANSFORM_HOTKEY", "ctrl+alt+t").strip()
        self.profile_hotkey = os.getenv("PROFILE_HOTKEY", "ctrl+alt+e").strip()
        # O atalho do espanhol chegou no Bloco 11. No .env de antes, sem ele, quem já tinha posto o
        # Ctrl+Alt+N noutro atalho do Willy perderia esse atalho na partida (vale o primeiro do
        # ATALHOS, e o espanhol vem logo no começo): o espanhol fica sem atalho até a pessoa dar um.
        if (os.getenv("TRANSLATE_ES_HOTKEY") is None
                and tecla_do_atalho(self.translate_es_hotkey) in self._teclas_dos_outros_atalhos("translate_es_hotkey")):
            self.translate_es_hotkey = ""

        self.model = os.getenv("GROQ_MODEL", "whisper-large-v3-turbo").strip()
        self.translate_model = os.getenv("GROQ_TRANSLATE_MODEL", "whisper-large-v3").strip()
        # Um modelo desligado na Groq vira o substituto, e o .env é corrigido: sem isso, todo
        # refino falhava. A config recusava "gpt-oss" e "qwen", que são os substitutos.
        raw_llm = os.getenv("GROQ_LLM_MODEL", "").strip()
        self.llm_model = modelos_llm.modelo_em_uso(raw_llm)
        if raw_llm and self.llm_model != raw_llm:
            self.settings_store.save_settings({"GROQ_LLM_MODEL": self.llm_model})
        self.processing_profile = os.getenv("PROCESSING_PROFILE", "dev").strip().lower()
        if self.processing_profile not in ("dev", "executivo", "puro"):
            self.processing_profile = "dev"

        self.refine_prompt = os.getenv("REFINE_PROMPT", "true").strip().lower() in ("true", "1", "yes")
        self.silent_mode = os.getenv("SILENT_MODE", "false").strip().lower() in ("true", "1", "yes")
        self.whisper_mode = os.getenv("WHISPER_MODE", "false").strip().lower() in ("true", "1", "yes")
        self.pill_position = os.getenv("PILL_POSITION", "centro_inferior").strip().lower()
        if self.pill_position not in POSICOES_DA_PILULA_VALIDAS:
            self.pill_position = "centro_inferior"

        self.audio_device: int | None = _parse_indice_dispositivo(os.getenv("AUDIO_DEVICE"))
        self.system_audio_device: int | None = _parse_indice_dispositivo(os.getenv("SYSTEM_AUDIO_DEVICE"))

        self.mic_gain = _parse_float_limitado(os.getenv("MIC_GAIN", "1.0"), MIC_GAIN_MIN, MIC_GAIN_MAX, 1.0)

        self.auto_silence = os.getenv("AUTO_SILENCE", "true").strip().lower() in ("true", "1", "yes")
        self.silence_seconds = _parse_float_limitado(
            os.getenv("SILENCE_SECONDS", "2.2"), SILENCE_SECONDS_MIN, SILENCE_SECONDS_MAX, 2.2
        )
        # Com float() direto, um valor torto no .env (texto, vírgula decimal) derrubava o
        # ConfigManager, e o Willy não abria; NaN ou negativo desligavam a detecção de silêncio.
        self.silence_threshold = _parse_float_limitado(
            os.getenv("SILENCE_THRESHOLD", "0.005"), LIMIAR_RMS_MIN, LIMIAR_RMS_MAX, 0.005
        )
        self.speech_threshold = _parse_float_limitado(
            os.getenv("SPEECH_THRESHOLD", "0.009"), LIMIAR_RMS_MIN, LIMIAR_RMS_MAX, 0.009
        )
        self.private_mode = os.getenv("PRIVATE_MODE", "false").strip().lower() in ("true", "1", "yes")
        # Um perfil importado antes desta checagem pode ter deixado \\servidor\share no .env.
        outputs_raw = os.getenv("OUTPUTS_DIR", "").strip()
        self.outputs_dir = outputs_raw if caminho_local_absoluto(outputs_raw) else DEFAULT_OUTPUTS_DIR
        self.clean_fillers = os.getenv("CLEAN_FILLERS", "true").strip().lower() in ("true", "1", "yes")
        self.clipboard_only = os.getenv("CLIPBOARD_ONLY", "false").strip().lower() in ("true", "1", "yes")
        self.output_tone = os.getenv("OUTPUT_TONE", "natural").strip().lower()
        if self.output_tone not in TONS_DE_SAIDA_VALIDOS:
            self.output_tone = "natural"
        self.input_language = os.getenv("INPUT_LANGUAGE", "auto").strip().lower()
        if self.input_language not in IDIOMAS_DE_ENTRADA_VALIDOS:
            self.input_language = "auto"
        self.smart_paragraphing = os.getenv("SMART_PARAGRAPHING", "true").strip().lower() in ("true", "1", "yes")
        self.save_audio_files = os.getenv("SAVE_AUDIO_FILES", "false").strip().lower() in ("true", "1", "yes")
        self.silero_vad = os.getenv("SILERO_VAD", "true").strip().lower() in ("true", "1", "yes")
        self.wake_word_enabled = os.getenv("WAKE_WORD_ENABLED", "false").strip().lower() in ("true", "1", "yes")
        raw_onboarding = dotenv_values(ENV_FILE).get("ONBOARDING_COMPLETED")
        if raw_onboarding is None:
            raw_onboarding = os.getenv("ONBOARDING_COMPLETED", "")
        onboarding_norm = str(raw_onboarding).strip().lower()
        if onboarding_norm in ("true", "1", "yes"):
            self.onboarding_completed = True
        elif onboarding_norm in ("false", "0", "no"):
            self.onboarding_completed = False
        else:
            # Instalação antiga atualizada sem ONBOARDING_COMPLETED: preserva o fluxo normal
            # para quem já configurou chave ou já tem histórico de uso.
            self.onboarding_completed = bool(self.chave_configurada() or self.load_history())
        # As regras por aplicativo (ver AppRulesStore), lidas aqui como os ajustes do .env: o
        # pipeline consulta esta lista a cada ditado, sem ler o disco.
        self.app_context_rules: list[dict[str, str]] = self.app_rules_store.load_rules()

    def get_app_context_rules(self) -> list[dict[str, str]]:
        """As regras por aplicativo em vigor (cópia: quem edita não mexe na do pipeline)."""
        return [dict(regra) for regra in self.app_context_rules]

    def save_app_context_rules(self, regras: Any) -> bool:
        """Grava as regras por aplicativo e as põe em vigor no próximo ditado. Devolve se gravou;
        sem gravar, as de antes continuam valendo, as mesmas que o disco tem."""
        if not self.app_rules_store.save_rules(regras):
            return False
        self.app_context_rules = self.app_rules_store.load_rules()
        return True

    def save_settings(self, novos_dados: dict[str, Any]) -> None:
        """Salva as configurações alteradas no arquivo .env mantendo comentários."""
        chave_anterior = self.groq_api_key
        if "GROQ_API_KEY" in novos_dados:
            self.groq_api_key = str(novos_dados["GROQ_API_KEY"]).strip()
        if "GROQ_MODEL" in novos_dados:
            modelo_whisper = str(novos_dados["GROQ_MODEL"] or "").strip()
            if modelo_whisper:
                self.model = modelo_whisper
        if "GROQ_TRANSLATE_MODEL" in novos_dados:
            modelo_traducao = str(novos_dados["GROQ_TRANSLATE_MODEL"] or "").strip()
            if modelo_traducao:
                self.translate_model = modelo_traducao
        if "SILENCE_THRESHOLD" in novos_dados:
            self.silence_threshold = _parse_float_limitado(
                novos_dados["SILENCE_THRESHOLD"], LIMIAR_RMS_MIN, LIMIAR_RMS_MAX, self.silence_threshold
            )
        if "SPEECH_THRESHOLD" in novos_dados:
            self.speech_threshold = _parse_float_limitado(
                novos_dados["SPEECH_THRESHOLD"], LIMIAR_RMS_MIN, LIMIAR_RMS_MAX, self.speech_threshold
            )
        if "SILENCE_SECONDS" in novos_dados:
            self.silence_seconds = _parse_float_limitado(
                novos_dados["SILENCE_SECONDS"], SILENCE_SECONDS_MIN, SILENCE_SECONDS_MAX, self.silence_seconds
            )
        if "REFINE_PROMPT" in novos_dados:
            self.refine_prompt = _parse_bool(novos_dados["REFINE_PROMPT"], self.refine_prompt)
        if "SILENT_MODE" in novos_dados:
            self.silent_mode = _parse_bool(novos_dados["SILENT_MODE"], self.silent_mode)
        if "WHISPER_MODE" in novos_dados:
            self.whisper_mode = _parse_bool(novos_dados["WHISPER_MODE"], self.whisper_mode)
        if "PROCESSING_PROFILE" in novos_dados:
            prof = str(novos_dados["PROCESSING_PROFILE"]).strip().lower()
            if prof in ("dev", "executivo", "puro"):
                self.processing_profile = prof
        if "PRIVATE_MODE" in novos_dados:
            self.private_mode = _parse_bool(novos_dados["PRIVATE_MODE"], self.private_mode)
        if "OUTPUTS_DIR" in novos_dados:
            pasta = novos_dados["OUTPUTS_DIR"]
            if pasta is None or (isinstance(pasta, str) and not pasta.strip()):
                self.outputs_dir = DEFAULT_OUTPUTS_DIR
            elif caminho_local_absoluto(pasta):
                self.outputs_dir = pasta.strip()
            else:
                # \\servidor\share vaza o hash NTLM no primeiro makedirs; relativo e '..' não
                # dizem onde os arquivos vão parar. Fica a pasta atual.
                print(f"[ConfigManager] OUTPUTS_DIR recusado: {pasta!r}", file=sys.stderr)
        if "AUTO_SILENCE" in novos_dados:
            self.auto_silence = _parse_bool(novos_dados["AUTO_SILENCE"], self.auto_silence)
        if "CLEAN_FILLERS" in novos_dados:
            self.clean_fillers = _parse_bool(novos_dados["CLEAN_FILLERS"], self.clean_fillers)
        if "CLIPBOARD_ONLY" in novos_dados:
            self.clipboard_only = _parse_bool(novos_dados["CLIPBOARD_ONLY"], self.clipboard_only)
        if "OUTPUT_TONE" in novos_dados:
            tom = str(novos_dados["OUTPUT_TONE"]).strip().lower()
            if tom in TONS_DE_SAIDA_VALIDOS:
                self.output_tone = tom
        if "INPUT_LANGUAGE" in novos_dados:
            idioma = str(novos_dados["INPUT_LANGUAGE"]).strip().lower()
            if idioma in IDIOMAS_DE_ENTRADA_VALIDOS:
                self.input_language = idioma
        if "SMART_PARAGRAPHING" in novos_dados:
            self.smart_paragraphing = _parse_bool(novos_dados["SMART_PARAGRAPHING"], self.smart_paragraphing)
        if "PILL_POSITION" in novos_dados:
            pos = str(novos_dados["PILL_POSITION"]).strip().lower()
            if pos in POSICOES_DA_PILULA_VALIDAS:
                self.pill_position = pos
        if "GROQ_LLM_MODEL" in novos_dados:
            # Um perfil exportado antes da troca traz o modelo desligado.
            self.llm_model = modelos_llm.modelo_em_uso(novos_dados["GROQ_LLM_MODEL"])
        if "MEETING_HOTKEY" in novos_dados:
            self.meeting_hotkey = str(novos_dados["MEETING_HOTKEY"]).strip()
        if "PROMPT_HOTKEY" in novos_dados:
            self.prompt_hotkey = str(novos_dados["PROMPT_HOTKEY"]).strip()
        if "HISTORY_HOTKEY" in novos_dados:
            self.history_hotkey = str(novos_dados["HISTORY_HOTKEY"]).strip()
        if "UNDO_HOTKEY" in novos_dados:
            self.undo_hotkey = str(novos_dados["UNDO_HOTKEY"]).strip()
        if "SEND_HOTKEY" in novos_dados:
            self.send_hotkey = str(novos_dados["SEND_HOTKEY"]).strip()
        if "SPEAK_HOTKEY" in novos_dados:
            self.speak_hotkey = str(novos_dados["SPEAK_HOTKEY"]).strip()
        if "STICKY_HOTKEY" in novos_dados:
            self.sticky_hotkey = str(novos_dados["STICKY_HOTKEY"]).strip()
        if "CAPTIONS_HOTKEY" in novos_dados:
            self.captions_hotkey = str(novos_dados["CAPTIONS_HOTKEY"]).strip()
        if "TRANSFORM_HOTKEY" in novos_dados:
            self.transform_hotkey = str(novos_dados["TRANSFORM_HOTKEY"]).strip()
        if "PROFILE_HOTKEY" in novos_dados:
            self.profile_hotkey = str(novos_dados["PROFILE_HOTKEY"]).strip()
        if "SAVE_AUDIO_FILES" in novos_dados:
            self.save_audio_files = _parse_bool(novos_dados["SAVE_AUDIO_FILES"], self.save_audio_files)
        if "SILERO_VAD" in novos_dados:
            self.silero_vad = _parse_bool(novos_dados["SILERO_VAD"], self.silero_vad)
        if "WAKE_WORD_ENABLED" in novos_dados:
            self.wake_word_enabled = _parse_bool(novos_dados["WAKE_WORD_ENABLED"], self.wake_word_enabled)
        if "ONBOARDING_COMPLETED" in novos_dados:
            self.onboarding_completed = _parse_bool(novos_dados["ONBOARDING_COMPLETED"], self.onboarding_completed)
        if "VOICE_HOTKEY" in novos_dados:
            self.hotkey = str(novos_dados["VOICE_HOTKEY"]).strip()
        if "TRANSLATE_HOTKEY" in novos_dados:
            self.translate_hotkey = str(novos_dados["TRANSLATE_HOTKEY"]).strip()
        if "TRANSLATE_ES_HOTKEY" in novos_dados:
            self.translate_es_hotkey = str(novos_dados["TRANSLATE_ES_HOTKEY"]).strip()
        if "MASTER_HOTKEY" in novos_dados:
            self.master_hotkey = str(novos_dados["MASTER_HOTKEY"]).strip()
        if "AUDIO_DEVICE" in novos_dados:
            self.audio_device = _parse_indice_dispositivo(novos_dados["AUDIO_DEVICE"])
        if "SYSTEM_AUDIO_DEVICE" in novos_dados:
            self.system_audio_device = _parse_indice_dispositivo(novos_dados["SYSTEM_AUDIO_DEVICE"])
        if "MIC_GAIN" in novos_dados:
            self.mic_gain = _parse_float_limitado(novos_dados["MIC_GAIN"], MIC_GAIN_MIN, MIC_GAIN_MAX, self.mic_gain)

        mapeamento = {
            "GROQ_API_KEY": self.groq_api_key,
            "VOICE_HOTKEY": self.hotkey,
            "TRANSLATE_HOTKEY": self.translate_hotkey,
            "TRANSLATE_ES_HOTKEY": self.translate_es_hotkey,
            "MASTER_HOTKEY": self.master_hotkey,
            "MEETING_HOTKEY": self.meeting_hotkey,
            "PROMPT_HOTKEY": self.prompt_hotkey,
            "HISTORY_HOTKEY": self.history_hotkey,
            "UNDO_HOTKEY": self.undo_hotkey,
            "SEND_HOTKEY": self.send_hotkey,
            "SPEAK_HOTKEY": self.speak_hotkey,
            "STICKY_HOTKEY": self.sticky_hotkey,
            "CAPTIONS_HOTKEY": self.captions_hotkey,
            "TRANSFORM_HOTKEY": self.transform_hotkey,
            "PROFILE_HOTKEY": self.profile_hotkey,
            "GROQ_MODEL": self.model,
            "GROQ_TRANSLATE_MODEL": self.translate_model,
            "GROQ_LLM_MODEL": self.llm_model,
            "PROCESSING_PROFILE": self.processing_profile,
            "AUDIO_DEVICE": "" if self.audio_device is None else str(self.audio_device),
            "SYSTEM_AUDIO_DEVICE": "" if self.system_audio_device is None else str(self.system_audio_device),
            "MIC_GAIN": f"{self.mic_gain:.1f}",
            "REFINE_PROMPT": "true" if self.refine_prompt else "false",
            "SILENT_MODE": "true" if self.silent_mode else "false",
            "WHISPER_MODE": "true" if self.whisper_mode else "false",
            "PRIVATE_MODE": "true" if self.private_mode else "false",
            "OUTPUTS_DIR": self.outputs_dir,
            "PILL_POSITION": self.pill_position,
            "AUTO_SILENCE": "true" if self.auto_silence else "false",
            "CLEAN_FILLERS": "true" if self.clean_fillers else "false",
            "CLIPBOARD_ONLY": "true" if self.clipboard_only else "false",
            "OUTPUT_TONE": self.output_tone,
            "INPUT_LANGUAGE": self.input_language,
            "SMART_PARAGRAPHING": "true" if self.smart_paragraphing else "false",
            "SAVE_AUDIO_FILES": "true" if self.save_audio_files else "false",
            "SILERO_VAD": "true" if self.silero_vad else "false",
            "WAKE_WORD_ENABLED": "true" if self.wake_word_enabled else "false",
            "ONBOARDING_COMPLETED": "true" if self.onboarding_completed else "false",
            "SILENCE_SECONDS": f"{self.silence_seconds:.1f}",
            "SILENCE_THRESHOLD": f"{self.silence_threshold}",
            "SPEECH_THRESHOLD": f"{self.speech_threshold}"
        }

        # Gravada no cofre, a chave vai ao .env como linha vazia. Só tirá-la do mapeamento não
        # bastava: o SettingsStore preserva as linhas que não recebe, e a antiga, com a chave
        # em texto puro, ficava no arquivo.
        chave_secreta = mapeamento.pop("GROQ_API_KEY")
        if chave_secreta and chave_secreta != "sua_chave_aqui" and self._gravar_cofre(chave_secreta):
            mapeamento["GROQ_API_KEY"] = ""
        else:
            mapeamento["GROQ_API_KEY"] = chave_secreta
            if not chave_secreta and "GROQ_API_KEY" in novos_dados and chave_anterior:
                # A pessoa esvaziou um campo que mostrava a chave, e a tela diz "nenhuma chave
                # configurada". Sem isto, a antiga voltava do cofre no boot seguinte, sem
                # aparecer em lugar algum. Com o campo já vazio (o cofre não leu no boot),
                # salvar outro ajuste não pode apagar uma chave que a pessoa nem viu.
                self._apagar_cofre()
                
        mapeamento_seguro = {}
        for k, v in mapeamento.items():
            mapeamento_seguro[k] = re.sub(r'[\r\n]+', ' ', str(v)).strip()

        self.settings_store.save_settings(mapeamento_seguro)

    def toggle_auto_silence(self) -> bool:
        """Alterna entre o modo Automático (corte por silêncio) e Manual (toggle/pressione p/ parar)."""
        novo_estado = not self.auto_silence
        self.save_settings({"AUTO_SILENCE": novo_estado})
        return novo_estado

    def load_history(self) -> list[dict[str, Any]]:
        """Lê o histórico de transcrições do arquivo JSON."""
        return self.history_store.load_history()

    def save_history_item(self, texto: str, modo: str = "transcribe", file_path: str | None = None,
                          audio_path: str | None = None, duracao_s: float | None = None,
                          raw_text: str | None = None) -> list[dict[str, Any]]:
        """Adiciona um item ao histórico e salva no disco. `raw_text`: a fala antes da IA."""
        return self.history_store.save_history_item(texto, modo, file_path, audio_path, duracao_s,
                                                    raw_text=raw_text)

    def clear_history(self) -> None:
        """Limpa todo o histórico de transcrições."""
        self.history_store.clear_history()

    def load_vocab_text(self) -> str:
        """Lê o conteúdo bruto do arquivo vocabulario.txt."""
        return self.vocab_store.load_vocab_text()

    def save_vocab_text(self, conteudo: str) -> bool:
        """Salva texto no arquivo vocabulario.txt. Devolve se gravou."""
        return self.vocab_store.save_vocab_text(conteudo)

    def get_vocab_terms(self) -> list[str]:
        """Extrai os termos limpos de vocabulario.txt."""
        return self.vocab_store.get_vocab_terms()

    def get_prompt_context(self) -> str:
        """
        Retorna o contexto de vocabulário otimizado para o Whisper da Groq.
        Combina o vocabulário base com os termos personalizados do usuário,
        removendo duplicatas e garantindo estrita observância ao limite de 896 caracteres da Groq.
        """
        base_context = DEV_PROMPT_CONTEXT
        lang = getattr(self, "input_language", "auto")
        if lang == "auto":
            base_context = DEV_PROMPT_CONTEXT_BILINGUAL
        elif lang == "en":
            base_context = DEV_PROMPT_CONTEXT_EN

        # "Willy" conta como termo da pessoa, que nunca é cortado: com 40 termos dela, a base saía
        # inteira e o nome ia junto (achado do juiz do Bloco 9). Quem instalou antes não o tem no
        # vocabulario.txt. Se a base ainda o tiver, ele não se repete.
        termos = self.vocab_store.get_vocab_terms()
        if not any(t.strip().lower() == "willy" for t in termos):
            termos = ["Willy"] + list(termos)
        return self.vocab_store.build_prompt_context(base_context, custom_terms=termos)

    def load_replacements(self) -> dict[str, str]:
        """Lê o dicionário de substituições fonéticas/automáticas do arquivo JSON."""
        return self.vocab_store.load_replacements()

    def save_replacements(self, replacements: dict[str, str]) -> bool:
        """Salva o dicionário de substituições no arquivo JSON."""
        return self.vocab_store.save_replacements(replacements)

    def add_replacement(self, de: str, para: str) -> bool:
        """Adiciona ou atualiza uma regra de substituição."""
        return self.vocab_store.add_replacement(de, para)

    def delete_replacement(self, de: str) -> bool:
        """Remove uma regra de substituição."""
        return self.vocab_store.delete_replacement(de)

    def learn_correction(self, de: str, para: str) -> bool:
        """A correção feita no Histórico vira regra e termo do vocabulário (ver VocabularyStore)."""
        return self.vocab_store.learn_correction(de, para)

    @staticmethod
    def sanitize_filename(name: str, max_length: int = 50) -> str:
        """Limpa e formata uma string para ser usada com segurança como nome de arquivo no Windows/Linux."""
        # Remove caracteres proibidos no Windows: \ / : * ? " < > |
        cleaned = re.sub(r'[\\/*?:"<>|\n\r\t]', '', name)
        # Substitui espaços por underscores e colapsa múltiplos underscores
        cleaned = re.sub(r'[\s_]+', '_', cleaned).strip('_.-')
        if not cleaned:
            return "Documento"
        return cleaned[:max_length]

    def _teclas_dos_outros_atalhos(self, proprio: str) -> set:
        """As teclas (ver tecla_do_atalho) dos outros atalhos do Willy, o do atributo `proprio` fora."""
        from core.system.hotkey_orchestrator import ATALHOS
        return {tecla_do_atalho(getattr(self, atributo, "")) for _nome, atributo, _campo in ATALHOS
                if atributo != proprio} - {None}

    def get_subfolder_for_mode(self, mode: str) -> str:
        """Retorna o nome da subpasta de acordo com a categoria de transcrição."""
        folder_map = {
            "meeting": "Atas",
            "prompt": "Prompts",
            "transcribe": "Textos",
            "send": "Textos",
            "translate": "Traducoes",
            "translate_es": "Traducoes",
            "action": "Acoes",
            "transform": "Acoes",
        }
        return folder_map.get(mode, "Textos")

    def save_output_file(self, text: str, modo: str = "transcribe", wav_bytes: bytes | None = None) -> str | None:
        """
        Salva o texto transcrito em um arquivo Markdown (.md) individual dentro de
        Documentos/Willy/<Subpasta>/ com nome cronológico e metadados no topo.
        Se wav_bytes for fornecido e save_audio_files estiver ativo (ou em modo meeting),
        salva o arquivo de áudio (.wav) correspondente ao lado do Markdown.
        Retorna o caminho do arquivo gerado ou None se o modo privado estiver ativo.
        """
        self.last_saved_wav_path: str | None = None
        if self.private_mode or not text or not text.strip():
            return None

        try:
            subfolder_name = self.get_subfolder_for_mode(modo)
            target_dir = os.path.join(self.outputs_dir, subfolder_name)
            os.makedirs(target_dir, exist_ok=True)

            # Extrai título inteligente para o arquivo
            titulo = ""
            lines = [l.strip() for l in text.splitlines() if l.strip()]

            if modo == "prompt":
                # Tenta extrair a síntese do comando /goal
                m = re.search(r'/goal\s*"([^"]+)"', text, flags=re.IGNORECASE)
                if m:
                    titulo = m.group(1).strip()
                elif lines:
                    titulo = lines[0].replace("#", "").strip()
            elif modo == "meeting":
                # Procura primeiro subtópico relevante ou usa Ata_Reuniao
                for l in lines:
                    if l.startswith("### 📌") or "Visão Geral" in l or "Ata Executiva" in l:
                        continue
                    if l.startswith(("- ", "## ")):
                        clean_l = l.lstrip("-# ").strip()
                        if len(clean_l) > 3:
                            titulo = clean_l
                            break
                if not titulo:
                    titulo = "Ata_Reuniao"
            else:
                if lines:
                    primeira_linha = lines[0].replace("#", "").strip()
                    palavras = primeira_linha.split()[:6]
                    titulo = " ".join(palavras)

            if not titulo:
                titulo = subfolder_name

            safe_titulo = self.sanitize_filename(titulo, max_length=45)
            timestamp_file = time.strftime("%Y-%m-%d_%H-%M-%S")
            # As traduções para o espanhol ficam na pasta das traduções, com o prefixo que as
            # separa das para o inglês.
            prefixo = "traducao_es_" if modo == "translate_es" else ""
            filename = f"{prefixo}{timestamp_file}_{safe_titulo}.md"
            file_path = os.path.join(target_dir, filename)

            # Salva áudio correspondente se fornecido e habilitado
            wav_line = ""
            if wav_bytes and (self.save_audio_files or modo == "meeting"):
                wav_filename = f"{prefixo}{timestamp_file}_{safe_titulo}.wav"
                wav_path = os.path.join(target_dir, wav_filename)
                try:
                    with open(wav_path, "wb") as wf:
                        wf.write(wav_bytes)
                    self.last_saved_wav_path = wav_path
                    wav_line = f"> 🎧 **Áudio Original:** [{wav_filename}](./{wav_filename})\n"
                except Exception as we:  # noqa: BLE001 — fronteira defensiva: escrita opcional do .wav ao lado do .md
                    print(f"[ConfigManager] Erro ao gravar arquivo wav: {we}", file=sys.stderr)

            # Monta metadados no topo do arquivo Markdown
            human_mode = {
                "meeting": "Ata Executiva & Transcrição",
                "prompt": "Prompt de Agente (/goal)",
                "transcribe": "Ditado de Voz",
                "send": "Ditado e Envio Automático",
                "translate": "Tradução para Inglês",
                "translate_es": "Tradução para Espanhol",
                "action": "Ação do Copiloto de Voz",
                "transform": "Transformação de Seleção por Voz",
            }.get(modo, "Ditado")

            data_hora_human = time.strftime("%d/%m/%Y às %H:%M:%S")
            words_count = len(text.split())

            conteudo_md = (
                f"# {safe_titulo.replace('_', ' ')}\n\n"
                f"> 📅 **Data:** {data_hora_human}\n"
                f"> 🏷️ **Categoria:** {human_mode}\n"
                f"> 📊 **Total:** {words_count} palavras\n"
                f"{wav_line}\n"
                f"---\n\n"
                f"{text.strip()}\n"
            )

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(conteudo_md)

            return file_path
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: persistência de arquivo de saída em disco
            print(f"[ConfigManager] Erro ao salvar arquivo em {self.outputs_dir}: {e}", file=sys.stderr)
            return None

    def open_outputs_folder(self, subfolder: str | None = None) -> bool:
        """Abre a pasta de arquivos no Windows Explorer."""
        try:
            target = self.outputs_dir
            if subfolder:
                target = os.path.join(self.outputs_dir, subfolder)
            os.makedirs(target, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(target)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", target])
            return True
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: os.startfile / xdg-open na pasta de saídas
            print(f"[ConfigManager] Erro ao abrir pasta {self.outputs_dir}: {e}", file=sys.stderr)
            return False

    @staticmethod
    def open_file(file_path: str) -> bool:
        """Abre um .md, .wav ou .txt local no aplicativo padrão do sistema (VS Code, Notepad, etc.)."""
        # Checagens de texto antes do os.path.exists: em \\servidor\share, o exists já vaza o hash.
        if not isinstance(file_path, str) or not file_path.strip():
            return False
        if (not caminho_local_absoluto(file_path)
                or os.path.splitext(file_path.strip())[1].lower() not in EXTENSOES_ABRIVEIS):
            print(f"[ConfigManager] Abertura recusada: {file_path!r}", file=sys.stderr)
            return False
        try:
            if os.path.exists(file_path):
                if sys.platform == "win32":
                    os.startfile(file_path)
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", file_path])
                return True
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: os.startfile / xdg-open em arquivo de saída
            print(f"[ConfigManager] Erro ao abrir arquivo {file_path}: {e}", file=sys.stderr)
        return False

    def get_analytics_metrics(self) -> dict[str, Any]:
        """
        Calcula estatísticas de produtividade e tempo economizado com base no histórico.
        Considera digitação manual média de 40 palavras/minuto vs fala a 145 palavras/minuto.
        """
        from core.analytics.metrics import calculate_analytics_metrics
        return calculate_analytics_metrics(self.load_history())


    def export_profile(self, target_path: str, snippet_mgr=None, include_api_key: bool = False,
                       include_history: bool = False) -> bool:
        """Exporta os dados do Willy para um JSON portátil (sem a chave e sem o histórico, por padrão)."""
        from core.storage.profile_manager import ProfileManager
        return ProfileManager(self).export_profile(
            target_path, snippet_mgr=snippet_mgr, include_api_key=include_api_key,
            include_history=include_history,
        )

    def import_profile(self, source_path: str, snippet_mgr=None) -> bool:
        """Restaura o perfil completo do Willy a partir de um arquivo JSON."""
        from core.storage.profile_manager import ProfileManager
        gerente = ProfileManager(self)
        ok = gerente.import_profile(source_path, snippet_mgr=snippet_mgr)
        self.chave_do_perfil_ignorada = ok and gerente.chave_ignorada
        return ok


