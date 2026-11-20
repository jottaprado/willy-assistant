"""
Módulo de Snippets e Templates por Voz do Willy.
Permite definir gatilhos de voz que expandem automaticamente para templates pré-formatados.
"""

import json
import os
import re
import sys
import threading
from typing import Any

from . import config as _config
from .config import USER_DATA_DIR
from .storage.history_store import (
    _atomic_write_json,
    _gravar_com_tentativas,
    _quarentena_arquivo,
)
from .text_processing import normalize_for_search

# A transcrição lê os snippets a cada ditado (match_and_expand) enquanto a aba Templates grava:
# sem o lock, o os.replace da gravação falhava com o arquivo aberto pela leitura.
_SNIPPETS_LOCK = threading.RLock()

SNIPPETS_FILE = os.path.join(USER_DATA_DIR, ".snippets.json")

DEFAULT_SNIPPETS = [
    {
        "trigger": "meu pix",
        "title": "Chave PIX do Usuário",
        "content": "Chave PIX: [configure sua chave PIX na aba Templates]"
    },
    {
        "trigger": "link da reuniao",
        "title": "Link Fixo do Google Meet",
        "content": "[configure o link da sua sala na aba Templates]"
    },
    {
        "trigger": "template de pr",
        "title": "Template de Pull Request (PR)",
        "content": "## Pull Request\n\n### O que foi feito?\n- \n\n### Como testar?\n1. \n\n### Checklist de Qualidade\n- [ ] Testes automatizados adicionados/passando\n- [ ] Sem quebras de regressão"
    },
    {
        "trigger": "template de bug",
        "title": "Template de Bug Report",
        "content": "### Bug Report\n- **Descrição**:\n- **Passos para reproduzir**:\n  1. \n- **Comportamento esperado**:\n- **Comportamento observado**:"
    },
    {
        "trigger": "prompt de arquitetura",
        "title": "Prompt para Arquiteto de Software",
        "content": "Você é um Arquiteto de Software Sênior especialista. Analise a arquitetura e proponha uma solução modular, limpa e com testes automatizados para:"
    },
    {
        "trigger": "meu email comercial",
        "title": "Fechamento de E-mail Comercial",
        "content": "Olá! Muito obrigado pelo contato. Segue o material em anexo para sua avaliação. Fico à inteira disposição para alinharmos os próximos passos.\n\nAtenciosamente,"
    },
    {
        "trigger": "ata de reuniao",
        "title": "Ata de Reunião Rápida",
        "content": "**Ata de Reunião**\n- **Data**: \n- **Participantes**: \n- **Decisões Tomadas**:\n  - \n- **Próximos Passos (Action Items)**:\n  - [ ] "
    }
]


class SnippetManager:
    """Gerenciador de templates e snippets acionados por voz."""

    def __init__(self, file_path: str | None = None):
        self._file_path = file_path

    @property
    def file_path(self) -> str:
        if self._file_path:
            return self._file_path
        return os.path.join(_config.USER_DATA_DIR, ".snippets.json")

    @file_path.setter
    def file_path(self, value: str | None) -> None:
        self._file_path = value

    def _ensure_file(self) -> None:
        if not os.path.exists(self.file_path):
            self._gravar([dict(s) for s in DEFAULT_SNIPPETS])

    def _ler_estrito(self) -> list[dict[str, str]]:
        """Lê PROPAGANDO erro de leitura ou de JSON: é a única leitura que serve de base para gravar."""
        # utf-8-sig: um arquivo válido salvo com BOM (Bloco de Notas) não é "corrompido".
        with _SNIPPETS_LOCK, open(self.file_path, "r", encoding="utf-8-sig") as f:
            dados = json.load(f)
        if not isinstance(dados, list) or not all(isinstance(s, dict) for s in dados):
            raise ValueError(f"snippets em formato inesperado: {type(dados).__name__}")
        return dados

    def _base_para_gravar(self) -> list[dict[str, str]] | None:
        """Os snippets atuais como base de uma gravação, ou None quando não dá para gravar.

        Antes, um JSON corrompido virava a lista padrão, e a gravação seguinte escrevia os
        padrões por cima: os snippets da pessoa sumiam. Agora o corrompido vai para quarentena,
        e um arquivo que não pôde ser lido (em uso, sem permissão) não é sobrescrito.
        """
        if not os.path.exists(self.file_path):
            return [dict(s) for s in DEFAULT_SNIPPETS]
        try:
            return self._ler_estrito()
        except ValueError as e:  # JSONDecodeError, UnicodeDecodeError, formato inesperado
            if not _quarentena_arquivo(self.file_path, e, "SnippetManager"):
                return None
            return [dict(s) for s in DEFAULT_SNIPPETS]
        except OSError as e:
            print(f"[SnippetManager] snippets ilegíveis, nada gravado: {e!r}", file=sys.stderr)
            return None

    def _gravar(self, snippets: list[dict[str, str]]) -> bool:
        try:
            with _SNIPPETS_LOCK:
                _gravar_com_tentativas(lambda: _atomic_write_json(self.file_path, snippets))
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de persistência atômica de snippets
            print(f"[SnippetManager] Não consegui gravar os snippets: {e!r}", file=sys.stderr)
            return False

    def get_snippets(self) -> list[dict[str, str]]:
        """Carrega a lista de snippets cadastrados (só leitura: nunca grava)."""
        if not os.path.exists(self.file_path):
            return [dict(s) for s in DEFAULT_SNIPPETS]
        try:
            return self._ler_estrito()
        except (OSError, ValueError) as e:
            print(f"[SnippetManager] snippets ilegíveis, mostrando os padrões: {e!r}", file=sys.stderr)
            return [dict(s) for s in DEFAULT_SNIPPETS]

    def save_snippet(self, trigger: str, title: str, content: str, old_trigger: str | None = None) -> bool:
        """Salva ou atualiza um snippet. Devolve se gravou.

        `old_trigger` é a troca do gatilho de um template: ele fica no mesmo lugar da lista, com
        gatilho, título e conteúdo novos, numa gravação só. Antes, a troca gravava o novo no fim e
        apagava o antigo. Se o gatilho novo já é de outro template (igual, ou só com acento
        diferente), nada é gravado e volta False: a troca apagaria aquele. A variante do antigo com
        outro acento não conta (já disputava a fala com ele) e fica, salvo se for exatamente o
        gatilho novo. Cópias iguais ao antigo, num arquivo antigo, saem junto. Sem o old_trigger
        na lista (apagado no meio tempo), é um salvar comum.
        """
        trigger_clean = trigger.strip().lower()
        if not trigger_clean or not content.strip():
            return False

        with _SNIPPETS_LOCK:
            if old_trigger and old_trigger.strip():
                return self._renomear_sob_lock(old_trigger.strip().lower(), trigger_clean, title, content)
            return self._salvar_sob_lock(trigger_clean, title, content)

    def _renomear_sob_lock(self, antigo: str, trigger_clean: str, title: str, content: str) -> bool:
        snippets = self._base_para_gravar()
        if snippets is None:
            return False
        indice = next((i for i, it in enumerate(snippets) if it.get("trigger", "").lower() == antigo), None)
        if indice is None:
            return self._salvar_sob_lock(trigger_clean, title, content)
        falado, antigo_falado = normalize_for_search(trigger_clean), normalize_for_search(antigo)

        def _copia_do_antigo(item: dict[str, str]) -> bool:
            # Num arquivo antigo, o mesmo gatilho podia aparecer duas vezes: a segunda cópia
            # contava como "outro template", e a troca nunca gravava. As cópias saem, como na
            # troca de antes (o delete_snippet apagava as iguais).
            return item.get("trigger", "").lower() == antigo

        def _colide(item: dict[str, str]) -> bool:
            # Outro template com o gatilho falado do novo. A variante do antigo com outro acento
            # ("link da reunião" ao lado de "link da reuniao") é outro template, com conteúdo
            # próprio, e já disputava a fala com ele: a troca não muda isso, e ela fica. Só
            # colide se for exatamente o gatilho novo (seriam dois gatilhos iguais).
            gatilho = item.get("trigger", "").lower()
            if normalize_for_search(gatilho) != falado:
                return False
            return gatilho == trigger_clean or falado != antigo_falado

        # O próprio template é uma cópia do antigo: só conta o gatilho de outro.
        if any(not _copia_do_antigo(it) and _colide(it) for it in snippets):
            return False
        snippets[indice] = {**snippets[indice], "trigger": trigger_clean,
                            "title": title or trigger_clean.title(), "content": content}
        return self._gravar([it for i, it in enumerate(snippets) if i == indice or not _copia_do_antigo(it)])

    def _salvar_sob_lock(self, trigger_clean: str, title: str, content: str) -> bool:
        snippets = self._base_para_gravar()
        if snippets is None:
            return False
        # Se já existir o trigger, atualiza. Sem acento: "link da reunião" e o padrão "link da
        # reuniao" são o mesmo gatilho falado, e os dois na lista disputavam a mesma fala. O
        # igual vem primeiro: num arquivo antigo com os dois, renomear o outro deixaria dois
        # gatilhos idênticos.
        iguais = [it for it in snippets if it.get("trigger", "").lower() == trigger_clean]
        equivalentes = [it for it in snippets
                        if normalize_for_search(it.get("trigger", "")) == normalize_for_search(trigger_clean)]
        existente = (iguais or equivalentes or [None])[0]
        if existente is not None:
            existente["trigger"] = trigger_clean
            existente["title"] = title or trigger_clean.title()
            existente["content"] = content
        else:
            snippets.append({
                "trigger": trigger_clean,
                "title": title or trigger_clean.title(),
                "content": content
            })

        return self._gravar(snippets)

    def replace_snippets(self, itens: Any) -> bool:
        """Substitui a lista inteira de snippets de forma atômica (uma única gravação).

        Usado na restauração de perfil (import_profile) para que a lista do perfil substitua
        integralmente os snippets locais (inclusive quando vazia), preservando a quarentena de
        arquivo corrompido e deduplicando gatilhos equivalentes.
        """
        if not isinstance(itens, list):
            return False
        with _SNIPPETS_LOCK:
            if self._base_para_gravar() is None:
                return False
            novos: list[dict[str, str]] = []
            for item in itens:
                if isinstance(item, dict):
                    trigger = item.get("trigger")
                    title = item.get("title")
                    content = item.get("content") or item.get("expansion")
                elif isinstance(item, (tuple, list)) and len(item) == 3:
                    trigger, title, content = item
                else:
                    continue
                if not isinstance(trigger, str) or not isinstance(content, str):
                    continue
                trigger_clean = trigger.strip().lower()
                if not trigger_clean or not content.strip():
                    continue
                titulo_limpo = title if isinstance(title, str) and title else trigger_clean.title()
                iguais = [it for it in novos if it.get("trigger", "").lower() == trigger_clean]
                equivalentes = [
                    it for it in novos
                    if normalize_for_search(it.get("trigger", "")) == normalize_for_search(trigger_clean)
                ]
                existente = (iguais or equivalentes or [None])[0]
                if existente is not None:
                    existente["trigger"] = trigger_clean
                    existente["title"] = titulo_limpo
                    existente["content"] = content
                else:
                    novos.append({
                        "trigger": trigger_clean,
                        "title": titulo_limpo,
                        "content": content,
                    })
            return self._gravar(novos)

    def delete_snippet(self, trigger: str) -> bool:
        """Remove um snippet pelo gatilho."""
        trigger_clean = trigger.strip().lower()
        with _SNIPPETS_LOCK:
            base = self._base_para_gravar()
            if base is None:
                return False
            return self._gravar([s for s in base if s.get("trigger", "").lower() != trigger_clean])

    def match_and_expand(self, text: str) -> str | None:
        """
        Verifica se a transcrição falada é um comando de inserção de template.
        Remove prefixos como 'inserir', 'colar', 'willy' antes de comparar.

        Compara sem acento: o Whisper escreve "reunião", e os gatilhos padrão (e muitos dos
        digitados às pressas) são "reuniao". Falar o gatilho não colava nada. Antes, a mesma
        comparação com acento: num arquivo que já tem "link da reunião" e "link da reuniao",
        vence o que a fala escreve igual.
        """
        if not text:
            return None

        # Limpeza básica de prefixos de comando. O Whisper põe vírgula depois do vocativo
        # ("Willy, inserir ata de reunião"), e os prefixos vêm em sequência: com um só, sem
        # pontuação, o gatilho nunca casava nessa fala.
        normalized = text.strip().lower()
        normalized = re.sub(r'^((willy|ei willy|inserir|colar|coloque|digite|adicionar)[,.:;!]*\s+)+', '', normalized)
        normalized = re.sub(r'^(template de|template do|template da|modelo de)\s+', 'template de ', normalized)
        normalized = normalized.strip(".,;:?! ")

        # A fala inteira tem que ser o gatilho. Com "começa com", o ditado comum virava template e
        # o resto da frase sumia: "Meu pix mudou de banco ontem" colava a chave PIX.
        snippets = self.get_snippets()
        for forma in (lambda t: t.strip().lower(), normalize_for_search):
            fala = forma(normalized)
            for item in snippets:
                t = forma(item.get("trigger", ""))
                if t and fala == t:
                    return item.get("content")

        return None
