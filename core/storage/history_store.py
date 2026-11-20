"""
Módulo de Armazenamento e Persistência do Histórico do Willy.
Fornece operações atômicas em disco para histórico de transcrições e prompts.
"""

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Um único dono do arquivo no processo. No Windows, os.replace falha com PermissionError
# enquanto outra thread tem o arquivo aberto para leitura; sem o lock, a gravação do
# pipeline falhava em silêncio com a UI lendo, e a leitura que pegava o arquivo no meio da
# troca devolvia [] e virava a base da próxima gravação (3 threads x 15 appends deixavam
# 2 itens no disco). Reentrante porque update() chama load e save por dentro.
_HISTORY_LOCK = threading.RLock()
_REPLACE_TENTATIVAS = 5


def _atomic_write_json(filepath: str, data: Any, indent: int | None = 2) -> None:
    """Grava dados JSON de forma atômica utilizando arquivo temporário e os.replace (ACH-15)."""
    dir_name = os.path.dirname(filepath) or "."
    os.makedirs(dir_name, exist_ok=True)
    temp_file = os.path.join(dir_name, f".tmp_{os.path.basename(filepath)}_{os.getpid()}_{time.time()}")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            if indent is not None:
                json.dump(data, f, ensure_ascii=False, indent=indent)
            else:
                json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, filepath)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        raise


def _atomic_write_text(filepath: str, texto: str) -> None:
    """Grava texto de forma atômica: arquivo temporário com fsync e os.replace."""
    dir_name = os.path.dirname(filepath) or "."
    os.makedirs(dir_name, exist_ok=True)
    temp_file = os.path.join(dir_name, f".tmp_{os.path.basename(filepath)}_{os.getpid()}_{time.time()}")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, filepath)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        raise


def _gravar_com_tentativas(gravar: Callable[[], None]) -> None:
    """Roda uma gravação atômica, repetindo se o os.replace bater em PermissionError.

    No Windows o replace falha enquanto outro processo (antivírus, indexador, editor) segura o
    arquivo por um instante. Depois das tentativas, propaga o último erro.
    """
    for tentativa in range(_REPLACE_TENTATIVAS):
        try:
            gravar()
            return
        except PermissionError:
            if tentativa == _REPLACE_TENTATIVAS - 1:
                raise
            time.sleep(0.05 * (tentativa + 1))


def _quarentena_arquivo(filepath: str, erro: Exception, rotulo: str) -> bool:
    """Renomeia um arquivo corrompido para <arquivo>.corrompido-<data>. False se não conseguiu.

    Mesma regra do histórico: gravar por cima apagaria os dados da pessoa, e o conteúdo
    preservado ao lado ainda pode ser recuperado à mão.
    """
    base = f"{filepath}.corrompido-{time.strftime('%Y%m%d-%H%M%S')}"
    destino, n = base, 1
    while os.path.exists(destino):
        n += 1
        destino = f"{base}-{n}"
    try:
        os.rename(filepath, destino)
    except OSError as e:
        print(f"[{rotulo}] arquivo corrompido ({erro!r}) e a quarentena falhou: {e!r}", file=sys.stderr)
        return False
    print(f"[{rotulo}] arquivo corrompido ({erro!r}); preservado em {destino}", file=sys.stderr)
    return True


@dataclass
class HistoryEntry:
    id: str
    text: str
    mode: str
    timestamp: str
    words: int
    file_path: str | None = None
    audio_path: str | None = None
    raw_text: str | None = None
    duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "mode": self.mode,
            "timestamp": self.timestamp,
            "words": self.words,
        }
        if self.file_path:
            d["file_path"] = self.file_path
        if self.audio_path:
            d["audio_path"] = self.audio_path
        if self.duration_s is not None and self.duration_s > 0:
            d["duration_s"] = round(float(self.duration_s), 1)
        if _texto_cru_que_vale(self.raw_text, self.text):
            d["raw_text"] = self.raw_text
        return d


def _texto_cru_que_vale(raw_text: str | None, texto: str) -> bool:
    """O texto cru só é guardado quando diz algo que o `text` não diz: vazio, ou igual ao texto
    entregue (refino desligado, perfil Puro, LLM fora), o "Restaurar original" não teria o que
    restaurar."""
    return isinstance(raw_text, str) and bool(raw_text.strip()) and raw_text != texto


class HistoryStore:
    """
    Gerenciador especializado em persistência de histórico de transcrições.
    Suporta caminho dinâmico para garantir compatibilidade com monkeypatch de testes.
    """

    def __init__(self, filepath: str | Callable[[], str] | None = None):
        self._filepath = filepath

    @property
    def filepath(self) -> str:
        if callable(self._filepath):
            return self._filepath()
        if self._filepath:
            return self._filepath
        # Fallback dinâmico para core.config.HISTORY_FILE permitindo mocks/patches
        try:
            from core.config import HISTORY_FILE
            return HISTORY_FILE
        except (ImportError, AttributeError):
            return os.path.join(os.path.expanduser("~"), ".willy_history.json")

    def _load_strict(self) -> list[dict[str, Any]]:
        """Lê o histórico PROPAGANDO qualquer erro de leitura ou de JSON.

        É a única leitura que pode servir de base para uma gravação: tratar um arquivo
        ilegível como lista vazia e gravar por cima apagaria o histórico inteiro.
        """
        target = self.filepath
        if not os.path.exists(target):
            return []
        with open(target, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError(f"histórico em formato inesperado: {type(raw).__name__}")  # noqa: TRY004 — contrato de quarentena captura ValueError junto com JSONDecodeError
        itens: list[dict[str, Any]] = []
        for x in raw:
            if isinstance(x, dict):
                itens.append(x)
            elif isinstance(x, str):
                itens.append(
                    HistoryEntry(
                        id=str(int(time.time() * 1000)),
                        timestamp=time.strftime("%d/%m/%Y %H:%M"),
                        mode="transcribe",
                        text=x,
                        words=len(x.split()),
                    ).to_dict()
                )
        return itens[-100:]

    def load_history(self) -> list[dict[str, Any]]:
        """Lê o histórico para EXIBIÇÃO. Em erro devolve [] e registra; nunca use como base de escrita."""
        with _HISTORY_LOCK:
            try:
                return self._load_strict()
            except Exception as e:  # noqa: BLE001 — fronteira de leitura de exibição do histórico
                print(f"[HistoryStore] leitura do histórico falhou: {e!r}", file=sys.stderr)
                return []

    def save_history(self, itens: list[dict[str, Any]]) -> bool:
        """Salva a lista completa de itens no disco usando escrita atômica."""
        target = self.filepath
        with _HISTORY_LOCK:
            try:
                _gravar_com_tentativas(lambda: _atomic_write_json(target, itens[-100:], indent=2))
                return True
            except PermissionError:
                print(f"[HistoryStore] histórico não gravado após {_REPLACE_TENTATIVAS} tentativas "
                      "(arquivo em uso)", file=sys.stderr)
                return False
            except Exception as e:  # noqa: BLE001 — fronteira de gravação atômica do histórico
                print(f"[HistoryStore] gravação do histórico falhou: {e!r}", file=sys.stderr)
                return False

    def update(self, transformar: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> bool:
        """Lê, transforma e grava sob o mesmo lock (sem lost update).

        Conteúdo corrompido (JSON truncado por um desligamento abrupto) vai para quarentena,
        preservado ao lado, e o histórico recomeça: gravar por cima apagaria os dados, e
        recusar para sempre deixaria todo ditado seguinte sem histórico. Arquivo que não
        pôde ser LIDO (em uso, sem permissão) devolve False sem gravar nada.
        """
        with _HISTORY_LOCK:
            try:
                atuais = self._load_strict()
            except ValueError as e:  # JSONDecodeError, UnicodeDecodeError, formato inesperado
                if not self._quarentena(e):
                    return False
                atuais = []
            except Exception as e:  # noqa: BLE001 — bloqueia sobrescrita quando a leitura falha
                print(f"[HistoryStore] histórico ilegível, nada gravado: {e!r}", file=sys.stderr)
                return False
            return self.save_history(transformar(atuais))

    def _quarentena(self, erro: Exception) -> bool:
        """Renomeia o arquivo corrompido para <arquivo>.corrompido-<data>. False se não conseguiu."""
        return _quarentena_arquivo(self.filepath, erro, "HistoryStore")

    def save_history_item(
        self,
        texto: str,
        modo: str = "transcribe",
        file_path: str | None = None,
        audio_path: str | None = None,
        duracao_s: float | None = None,
        raw_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """Adiciona um item ao histórico e salva no disco atomicamente.

        `duracao_s` é a duração da gravação: com ela as métricas medem a velocidade da fala.
        `raw_text` é a fala antes da IA (refino, tom, tradução, ata, /goal): é para ele que o
        "Restaurar original" do Histórico volta. Só fica quando difere do texto entregue.

        Levanta OSError quando não consegue gravar (inclusive com o arquivo ilegível), em vez
        de perder o item em silêncio: quem chama decide como avisar o usuário.
        """
        audio_resolvido = audio_path
        if not audio_resolvido and file_path and file_path.lower().endswith(".md"):
            wav_candidato = f"{os.path.splitext(file_path)[0]}.wav"
            if os.path.exists(wav_candidato):
                audio_resolvido = wav_candidato

        novo = HistoryEntry(
            id=str(int(time.time() * 1000)),
            timestamp=time.strftime("%d/%m/%Y %H:%M"),
            mode=modo,
            text=texto,
            words=len(texto.split()),
            file_path=file_path or None,
            audio_path=audio_resolvido or None,
            raw_text=raw_text,
            duration_s=duracao_s,
        ).to_dict()

        gravados: list[dict[str, Any]] = []

        def _acrescentar(itens: list[dict[str, Any]]) -> list[dict[str, Any]]:
            # O id é o milissegundo da gravação; dois ditados no mesmo milissegundo teriam o
            # mesmo id, e excluir um (a exclusão é por id) apagaria os dois.
            usados = {str(it.get("id")) for it in itens}
            while novo["id"] in usados:
                novo["id"] = str(int(novo["id"]) + 1)
            gravados[:] = (itens + [novo])[-100:]
            return gravados

        if not self.update(_acrescentar):
            raise OSError(f"histórico não gravado em {self.filepath}")
        return list(gravados)

    def update_item_text(
        self,
        item_id: str,
        novo_texto: str,
        novo_modo: str | None = None,
        preservar_raw: str | None = None,
    ) -> bool:
        """Troca o texto de um item (reformatado, traduzido, editado ou restaurado) sob o lock.

        Na primeira troca, o `raw_text` passa a guardar o original: `preservar_raw`, quando quem
        chama conhece um mais cru, ou o texto que o item tinha. Um `raw_text` que já existe não
        muda: é a fala, e "Restaurar original" volta sempre a ela, depois de quantas trocas forem.

        Devolve False sem gravar nada com o texto vazio, sem o item (excluído enquanto a IA
        respondia) ou com o histórico ilegível: gravar por cima de um arquivo que não foi lido
        apagaria o histórico inteiro.
        """
        if not item_id or not isinstance(novo_texto, str) or not novo_texto.strip():
            return False
        with _HISTORY_LOCK:
            try:
                itens = self._load_strict()
            except Exception as e:  # noqa: BLE001 — bloqueia alteração quando o arquivo está ilegível
                print(f"[HistoryStore] histórico ilegível, nada alterado: {e!r}", file=sys.stderr)
                return False
            alvo = next((it for it in itens if str(it.get("id")) == str(item_id)), None)
            if alvo is None:
                return False
            cru = alvo.get("raw_text")
            if not (isinstance(cru, str) and cru.strip()):
                original = preservar_raw if isinstance(preservar_raw, str) and preservar_raw.strip() else alvo.get("text")
                if isinstance(original, str) and original.strip():
                    alvo["raw_text"] = original
            alvo["text"] = novo_texto
            alvo["words"] = len(novo_texto.split())
            if novo_modo:
                alvo["mode"] = novo_modo
            return self.save_history(itens)

    def delete_item(self, item_id: str) -> bool:
        """Remove um item do histórico pelo ID."""
        with _HISTORY_LOCK:
            try:
                itens = self._load_strict()
            except Exception as e:  # noqa: BLE001 — bloqueia remoção quando o arquivo está ilegível
                print(f"[HistoryStore] histórico ilegível, nada removido: {e!r}", file=sys.stderr)
                return False
            novos = [it for it in itens if str(it.get("id")) != str(item_id)]
            if len(novos) != len(itens):
                return self.save_history(novos)
            return False

    def clear_history(self) -> None:
        """Limpa todo o histórico de transcrições de forma atômica."""
        with _HISTORY_LOCK:
            try:
                _atomic_write_json(self.filepath, [], indent=None)
            except Exception as e:  # noqa: BLE001 — fronteira de limpeza atômica do histórico
                print(f"[HistoryStore] limpeza do histórico falhou: {e!r}", file=sys.stderr)

    def search(self, query: str = "", mode_filter: str | None = None) -> list[dict[str, Any]]:
        """Pesquisa itens no histórico por texto e/ou modo."""
        itens = self.load_history()
        q = (query or "").lower().strip()
        resultado: list[dict[str, Any]] = []
        for it in reversed(itens):
            if mode_filter and mode_filter != "all" and it.get("mode") != mode_filter:
                continue
            if q and q not in it.get("text", "").lower():
                continue
            resultado.append(it)
        return resultado

