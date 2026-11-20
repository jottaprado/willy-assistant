"""
Módulo de Armazenamento e Gerenciamento de Vocabulário e Substituições do Willy.
"""

import json
import os
import sys
import threading
from collections.abc import Callable

from core.storage.history_store import (
    _atomic_write_json,
    _atomic_write_text,
    _gravar_com_tentativas,
    _quarentena_arquivo,
)

# A transcrição lê vocabulário e substituições a cada ditado enquanto a aba Vocabulário grava:
# sem o lock, o os.replace da gravação falhava com o arquivo aberto pela leitura.
_VOCAB_LOCK = threading.RLock()


class VocabularyStore:
    """
    Gerencia a leitura e escrita do dicionário de jargões técnicos (vocabulario.txt)
    e das substituições fonéticas personalizadas (.replacements.json).
    Suporta caminhos dinâmicos permitindo compatibilidade transparente com testes unitários.
    """

    def __init__(
        self,
        vocab_file: str | Callable[[], str] | None = None,
        replacements_file: str | Callable[[], str] | None = None
    ):
        self._vocab_file = vocab_file
        self._replacements_file = replacements_file

    @property
    def vocab_file(self) -> str:
        if callable(self._vocab_file):
            return self._vocab_file()
        if self._vocab_file:
            return self._vocab_file
        try:
            from core.config import VOCAB_FILE
            return VOCAB_FILE
        except (ImportError, AttributeError):
            return os.path.join(os.path.expanduser("~"), "vocabulario.txt")

    @property
    def replacements_file(self) -> str:
        if callable(self._replacements_file):
            return self._replacements_file()
        if self._replacements_file:
            return self._replacements_file
        try:
            from core.config import REPLACEMENTS_FILE
            return REPLACEMENTS_FILE
        except (ImportError, AttributeError):
            return os.path.join(os.path.expanduser("~"), ".replacements.json")

    def load_vocab_text(self) -> str:
        """Lê o conteúdo bruto do arquivo de vocabulário."""
        target = self.vocab_file
        if os.path.exists(target):
            try:
                with _VOCAB_LOCK, open(target, "r", encoding="utf-8-sig") as f:
                    return f.read()
            except Exception as e:  # noqa: BLE001 — fronteira de leitura de vocabulário
                print(f"[VocabularyStore] Erro ao carregar vocabulário: {e!r}", file=sys.stderr)
        return ""

    def save_vocab_text(self, conteudo: str) -> bool:
        """Salva texto no arquivo de vocabulário, de forma atômica. Devolve se gravou.

        A escrita direta truncava o arquivo antes de gravar: um desligamento no meio deixava
        o vocabulário vazio, e o erro era engolido.
        """
        target = self.vocab_file
        try:
            with _VOCAB_LOCK:
                if os.path.exists(target):
                    try:
                        with open(target, "r", encoding="utf-8-sig") as f:
                            f.read()
                    except UnicodeDecodeError as e:
                        if not _quarentena_arquivo(target, e, "VocabularyStore"):
                            return False
                    except OSError as e:
                        print(f"[VocabularyStore] vocabulário ilegível, nada gravado: {e!r}", file=sys.stderr)
                        return False
                _gravar_com_tentativas(lambda: _atomic_write_text(target, conteudo))
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de gravação atômica de vocabulário
            print(f"[VocabularyStore] Não consegui gravar o vocabulário: {e!r}", file=sys.stderr)
            return False

    def get_vocab_terms(self) -> list[str]:
        """Extrai os termos limpos do vocabulário."""
        return _termos_do_vocabulario(self.load_vocab_text())

    def load_replacements(self) -> dict[str, str]:
        """Lê o dicionário de substituições fonéticas/automáticas do arquivo JSON."""
        target = self.replacements_file
        try:
            if os.path.exists(target):
                with _VOCAB_LOCK, open(target, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k).strip(): str(v).strip() for k, v in data.items() if k and v}
        except Exception as e:  # noqa: BLE001 — fronteira de leitura de substituições JSON
            print(f"[VocabularyStore] Erro ao carregar replacements: {e}", file=sys.stderr)
        return {}

    def save_replacements(self, replacements: dict[str, str]) -> bool:
        """Salva o dicionário de substituições no arquivo JSON com escrita atômica."""
        target = self.replacements_file
        try:
            clean_rep = {str(k).strip(): str(v).strip() for k, v in replacements.items() if k and v}
            with _VOCAB_LOCK:
                _gravar_com_tentativas(lambda: _atomic_write_json(target, clean_rep, indent=2))
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de gravação atômica de substituições
            print(f"[VocabularyStore] Erro ao salvar replacements: {e}", file=sys.stderr)
            return False

    def _base_replacements(self) -> dict[str, str] | None:
        """As substituições atuais como base de uma gravação, ou None quando não dá para gravar.

        load_replacements devolve {} para um JSON corrompido, e add_replacement gravava por cima:
        as regras da pessoa sumiam. Corrompido vai para quarentena; ilegível não é sobrescrito.
        """
        target = self.replacements_file
        if not os.path.exists(target):
            return {}
        try:
            with _VOCAB_LOCK, open(target, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"substituições em formato inesperado: {type(data).__name__}")  # noqa: TRY004 — contrato de quarentena captura ValueError junto com JSONDecodeError
            return {str(k).strip(): str(v).strip() for k, v in data.items() if k and v}
        except ValueError as e:  # JSONDecodeError, UnicodeDecodeError, formato inesperado
            return {} if _quarentena_arquivo(target, e, "VocabularyStore") else None
        except OSError as e:
            print(f"[VocabularyStore] substituições ilegíveis, nada gravado: {e!r}", file=sys.stderr)
            return None

    def add_replacement(self, de: str, para: str) -> bool:
        """Adiciona ou atualiza uma regra de substituição."""
        if not de or not para:
            return False
        with _VOCAB_LOCK:
            reps = self._base_replacements()
            if reps is None:
                return False
            reps[de.strip()] = para.strip()
            return self.save_replacements(reps)

    def learn_correction(self, de: str, para: str) -> bool:
        """O "Ensinar ao Willy" do Histórico: a pessoa corrigiu `de` para `para` num ditado.

        Vira a regra `de -> para` (as substituições valem sem diferenciar maiúsculas, então
        "willy -> Willy" também é regra) e, se o vocabulário ainda não tem `para`, ele entra
        numa linha nova: o Whisper o recebe no prompt dos próximos ditados e passa a acertar
        na origem. Os dois arquivos sob o mesmo lock, cada um com gravação atômica.
        Devolve False se algum dos dois não gravou. Os dois são lidos antes de qualquer gravação:
        com o vocabulário ilegível, a regra não é gravada sozinha.
        """
        de = " ".join(str(de or "").split())
        para = " ".join(str(para or "").split())
        if not de or not para:
            return False
        with _VOCAB_LOCK:
            atual = self._base_vocab()
            if atual is None:
                return False
            if de != para and not self.add_replacement(de, para):
                return False
            # A vírgula separa termos numa linha do vocabulário, e o "#" abre comentário: um
            # termo assim viraria outros termos, ou nenhum. A regra acima já vale para ele.
            if "," in para or para.startswith("#"):
                return True
            if any(t.casefold() == para.casefold() for t in _termos_do_vocabulario(atual)):
                return True
            atual = atual.rstrip()
            return self.save_vocab_text(f"{atual}\n{para}\n" if atual else f"{para}\n")

    def _base_vocab(self) -> str | None:
        """O vocabulário como base de uma gravação, ou None quando não deu para lê-lo.

        load_vocab_text devolve "" na falha de leitura (arquivo em uso, sem permissão), e
        acrescentar um termo a isso gravaria o vocabulário inteiro por cima só com ele.
        """
        target = self.vocab_file
        if not os.path.exists(target):
            return ""
        try:
            with _VOCAB_LOCK, open(target, "r", encoding="utf-8-sig") as f:
                return f.read()
        except (OSError, ValueError) as e:
            print(f"[VocabularyStore] vocabulário ilegível, nada gravado: {e!r}", file=sys.stderr)
            return None

    def delete_replacement(self, de: str) -> bool:
        """Remove uma regra de substituição."""
        with _VOCAB_LOCK:
            reps = self._base_replacements()
            if reps is None:
                return False
            if de in reps:
                del reps[de]
                return self.save_replacements(reps)
            return False

    def build_prompt_context(
        self,
        base_context: str,
        custom_terms: list[str] | None = None,
        replacements: dict[str, str] | None = None,
        max_prompt_len: int = 850
    ) -> str:
        """
        Retorna o contexto de vocabulário otimizado para o Whisper da Groq.
        Combina o vocabulário base com os termos personalizados do usuário e do dicionário de substituições,
        removendo duplicatas e garantindo estrita observância ao limite seguro de caracteres.

        Os termos da pessoa têm prioridade no orçamento: passando do limite, quem é cortado é o
        fim da lista genérica do vocabulário base. Antes, a base entrava inteira e os termos da
        pessoa, que vinham depois, eram os truncados.
        """
        if custom_terms is None:
            custom_terms = self.get_vocab_terms()
        if replacements is None:
            replacements = self.load_replacements()

        termos: list[str] = []
        vistos = set()
        for t in list(custom_terms) + [str(v) for v in replacements.values()]:
            t_clean = t.strip()
            if t_clean and t_clean.lower() not in vistos:
                vistos.add(t_clean.lower())
                termos.append(t_clean)

        # 1. Os termos da pessoa primeiro, até o limite inteiro. 2. A base fica com o que sobra.
        # 3. O termo que essa base já tem sai da lista (não se repete). 4. A base cresce no espaço
        # liberado: ela só cresce, então o termo que saiu continua nela.
        proprios = _que_cabem(termos, max_prompt_len)
        base = _cortar_na_palavra(base_context, _sobra(max_prompt_len, proprios))
        na_base = _palavras(base)
        proprios = [t for t in proprios if t.lower() not in na_base]
        base = _cortar_na_palavra(base_context, _sobra(max_prompt_len, proprios))
        sufixo = ", ".join(proprios)
        return f"{base} {sufixo}".strip() if base else sufixo


def _termos_do_vocabulario(raw: str) -> list[str]:
    """Os termos do vocabulario.txt: um ou mais por linha, separados por vírgula; "#" comenta."""
    termos: list[str] = []
    for linha in raw.splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#"):
            termos.extend(p.strip() for p in linha.split(",") if p.strip())
    return termos


def _palavras(texto: str) -> set:
    return {w.strip(".,;:()[]{}\"'").lower() for w in texto.split() if len(w.strip(".,;:()[]{}\"'")) > 1}


def _que_cabem(termos: list[str], limite: int) -> list[str]:
    """Os termos, na ordem, enquanto a lista separada por vírgula couber em `limite`."""
    escolhidos: list[str] = []
    tamanho = 0
    for termo in termos:
        custo = len(termo) + (2 if escolhidos else 0)
        if tamanho + custo > limite:
            break
        escolhidos.append(termo)
        tamanho += custo
    return escolhidos


def _sobra(limite: int, termos: list[str]) -> int:
    """O espaço da base, com os termos e o espaço que os separa dela."""
    sufixo = ", ".join(termos)
    return limite - len(sufixo) - (1 if sufixo else 0)


def _cortar_na_palavra(texto: str, limite: int) -> str:
    """O texto inteiro se cabe; senão, cortado no último espaço antes do limite."""
    if limite <= 0:
        return ""
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rfind(" ")
    return texto[:corte].strip() if corte > 0 else ""
