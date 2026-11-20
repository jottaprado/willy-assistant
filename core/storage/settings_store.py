"""
Módulo de Armazenamento e Gerenciamento de Configurações (.env) do Willy.
Fornece leitura, parsing e gravação atômica preservando comentários e chaves não gerenciadas.

As regras por aplicativo (APP_CONTEXT_RULES) ficam num JSON à parte (AppRulesStore): uma lista
de regras não cabe numa linha CHAVE=valor do .env. O python-dotenv corta o valor sem aspas no
" #", e o save_settings troca quebra de linha por espaço, e a instrução extra de uma regra é
texto livre da pessoa ("use #hashtags", duas linhas).
"""

import io
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from core.storage.history_store import (
    _atomic_write_json,
    _gravar_com_tentativas,
    _quarentena_arquivo,
)

_SETTINGS_LOCK = threading.RLock()

# Uma regra muda o tom e/ou o modo do ditado feito naquele app. "default" deixa o da config.
TONS_DA_REGRA = ("default", "natural", "formal", "concise", "bullet_points", "technical")
MODOS_DA_REGRA = ("default", "transcribe", "translate", "translate_es")
MAX_REGRAS_DE_APP = 50
MAX_INSTRUCAO_DA_REGRA = 500


def sanitizar_regras_de_app(regras: Any) -> list[dict[str, str]]:
    """As regras válidas, cada uma só com os campos que o Willy conhece.

    Entrada externa (perfil importado, arquivo editado à mão): o que não for lista de dicts
    vira nenhuma regra. `app_exe` vira o nome do executável em minúsculas ("Slack" e
    "C:\\...\\Slack.exe" são "slack.exe"); `title_contains`, minúsculas. Sem nenhum dos dois, a
    regra valeria para todo app, e sai. Tom e modo desconhecidos viram "default"; a instrução
    extra fica em até MAX_INSTRUCAO_DA_REGRA caracteres, porque vai ao prompt de todo ditado
    naquele app.
    """
    if not isinstance(regras, list):
        return []
    limpas: list[dict[str, str]] = []
    for regra in regras:
        if not isinstance(regra, dict):
            continue
        app = regra.get("app_exe")
        app = os.path.basename(app.strip().replace("\\", "/")).lower() if isinstance(app, str) else ""
        if app and "." not in app:
            app += ".exe"
        titulo = regra.get("title_contains")
        titulo = " ".join(titulo.split()).lower() if isinstance(titulo, str) else ""
        if not app and not titulo:
            continue
        tom = regra.get("tone")
        modo = regra.get("action_mode")
        instrucao = regra.get("custom_instruction")
        limpas.append({
            "app_exe": app,
            "title_contains": titulo,
            "tone": tom if tom in TONS_DA_REGRA else "default",
            "action_mode": modo if modo in MODOS_DA_REGRA else "default",
            "custom_instruction": instrucao.strip()[:MAX_INSTRUCAO_DA_REGRA] if isinstance(instrucao, str) else "",
        })
        if len(limpas) == MAX_REGRAS_DE_APP:
            break
    return limpas


class AppRulesStore:
    """Persistência das regras por aplicativo (Contexto Automático) num JSON atômico."""

    def __init__(self, rules_file: str | Callable[[], str] | None = None):
        self._rules_file = rules_file

    @property
    def rules_file(self) -> str:
        if callable(self._rules_file):
            return self._rules_file()
        if self._rules_file:
            return self._rules_file
        try:
            from core.config import APP_RULES_FILE
            return APP_RULES_FILE
        except (ImportError, AttributeError):
            return os.path.join(os.path.expanduser("~"), ".willy_app_rules.json")

    def load_rules(self) -> list[dict[str, str]]:
        """As regras gravadas, já sanitizadas. Arquivo ausente ou ilegível: nenhuma regra."""
        target = self.rules_file
        if not os.path.exists(target):
            return []
        try:
            with open(target, "r", encoding="utf-8-sig") as f:
                return sanitizar_regras_de_app(json.load(f))
        except (OSError, ValueError) as e:
            print(f"[AppRulesStore] regras por aplicativo ilegíveis: {e!r}", file=sys.stderr)
            return []

    def save_rules(self, regras: Any) -> bool:
        """Grava a lista inteira (sanitizada). Devolve se gravou.

        A lista substitui a do disco, então o disco que não pôde ser lido não é sobrescrito: com
        o arquivo em uso, a tela mostrava nenhuma regra, e salvar uma apagaria todas. Corrompido
        vai para quarentena, preservado ao lado, como o histórico e as substituições.
        """
        target = self.rules_file
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8-sig") as f:
                    json.load(f)
            except ValueError as e:
                if not _quarentena_arquivo(target, e, "AppRulesStore"):
                    return False
            except OSError as e:
                print(f"[AppRulesStore] regras ilegíveis, nada gravado: {e!r}", file=sys.stderr)
                return False
        limpas = sanitizar_regras_de_app(regras)
        try:
            _gravar_com_tentativas(lambda: _atomic_write_json(target, limpas, indent=2))
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de persistência de regras por aplicativo
            print(f"[AppRulesStore] regras por aplicativo não gravadas: {e!r}", file=sys.stderr)
            return False


class SettingsStore:
    """
    Gerenciador de persistência do arquivo de configuração .env.
    Executa alterações de forma atômica utilizando arquivo temporário e os.replace.
    Preserva a estrutura do arquivo original, incluindo comentários (#), linhas em branco
    e variáveis adicionais configuradas manualmente pelo usuário.
    """

    def __init__(self, env_file: str | Callable[[], str] | None = None):
        self._env_file = env_file

    @property
    def env_file(self) -> str:
        if callable(self._env_file):
            return self._env_file()
        if self._env_file:
            return self._env_file
        try:
            from core.config import ENV_FILE
            return ENV_FILE
        except (ImportError, AttributeError):
            return os.path.join(os.path.expanduser("~"), ".willy_env")

    def load_lines(self) -> list[str]:
        """Lê todas as linhas do arquivo .env atual."""
        target = self.env_file
        if os.path.exists(target):
            try:
                with _SETTINGS_LOCK, open(target, "r", encoding="utf-8") as f:
                    return f.readlines()
            except Exception as e:  # noqa: BLE001 — fronteira de leitura de arquivo .env
                print(f"[SettingsStore] Erro ao ler {target}: {e}", file=sys.stderr)
        return []

    def save_settings(self, mapping: dict[str, Any]) -> bool:
        """
        Salva as configurações fornecidas no arquivo .env de forma atômica.
        Preserva rigorosamente comentários e ordem das linhas existentes.
        """
        target = self.env_file
        dir_name = os.path.dirname(target) or "."
        os.makedirs(dir_name, exist_ok=True)

        try:
            with _SETTINGS_LOCK:
                if os.path.exists(target):
                    with open(target, "r", encoding="utf-8") as f:
                        linhas = f.readlines()
                else:
                    linhas = []

                chaves_gravadas = set()
                linhas_atualizadas: list[str] = []

                for l in linhas:
                    strip_l = l.strip()
                    if "=" in strip_l and not strip_l.startswith("#"):
                        # .lstrip do BOM: um .env salvo no Bloco de Notas começa com \ufeff, e a
                        # primeira linha deixava de ser reconhecida (a chave ficava, e outra era acrescentada).
                        k = strip_l.split("=", 1)[0].strip().lstrip("\ufeff").strip()
                        # "export CHAVE=valor" é sintaxe válida de .env: sem tirar o prefixo, a
                        # linha (com a chave da Groq em texto puro) ficava e outra era acrescentada.
                        k = re.sub(r"^export\s+", "", k)
                        if k in mapping:
                            linhas_atualizadas.append(f"{k}={mapping[k]}\n")
                            chaves_gravadas.add(k)
                            continue
                    linhas_atualizadas.append(l)

                for k, v in mapping.items():
                    if k not in chaves_gravadas:
                        linhas_atualizadas.append(f"{k}={v}\n")

                def _gravar_atomico() -> None:
                    temp_file = os.path.join(dir_name, f".tmp_env_{os.getpid()}_{time.time()}")
                    try:
                        with open(temp_file, "w", encoding="utf-8") as f:
                            f.writelines(linhas_atualizadas)
                            f.flush()
                            try:
                                os.fsync(f.fileno())
                            except (AttributeError, io.UnsupportedOperation, OSError, TypeError):
                                pass
                        os.replace(temp_file, target)
                    except Exception:
                        if os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                            except OSError:
                                pass
                        raise

                _gravar_com_tentativas(_gravar_atomico)
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de gravação atômica do .env
            print(f"[SettingsStore] Erro ao salvar configurações em {target}: {e}", file=sys.stderr)
            return False
