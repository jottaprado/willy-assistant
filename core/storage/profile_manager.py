"""
Gerenciador de Perfis e Backup do Willy.
Permite exportar e importar configurações, vocabulário, snippets, histórico e substituições.

Um arquivo de perfil é entrada externa: pode ter sido editado ou recebido de outra pessoa.
Por isso o import valida o arquivo INTEIRO antes de aplicar qualquer parte dele.
"""

import json
import math
import os
import sys
import time
from typing import Any

from core.storage.caminhos import caminho_dentro_de
from core.storage.history_store import _atomic_write_json
from core.storage.settings_store import sanitizar_regras_de_app
from versao import __version__

_MAX_HISTORICO = 100
_ESCALARES = (str, int, float, bool)


class ProfileManager:
    """Gerencia a serialização, validação e restauração de perfis portáteis do Willy."""

    def __init__(self, config_mgr):
        self.config_mgr = config_mgr
        # O último import trouxe uma chave diferente da configurada, e ela foi descartada.
        self.chave_ignorada = False

    def export_profile(self, target_path: str, snippet_mgr=None, include_api_key: bool = False,
                       include_history: bool = False) -> bool:
        """
        Exporta os dados do Willy (configurações, vocabulário, snippets e, se pedido, o
        histórico) para um arquivo JSON portátil.

        O perfil é feito para ser copiado e compartilhado. A chave da Groq só entra com
        include_api_key=True, e as 100 últimas transcrições, em texto puro, só com
        include_history=True (decisão do dono, 22/10). Sem o histórico, a chave "history" nem
        entra no arquivo, e restaurá-lo não mexe no histórico de quem importa.
        """
        try:
            snippets = snippet_mgr.get_snippets() if snippet_mgr else []
            vocab_text = self.config_mgr.load_vocab_text()

            settings = {
                "VOICE_HOTKEY": self.config_mgr.hotkey,
                "TRANSLATE_HOTKEY": self.config_mgr.translate_hotkey,
                "TRANSLATE_ES_HOTKEY": self.config_mgr.translate_es_hotkey,
                "MASTER_HOTKEY": self.config_mgr.master_hotkey,
                "MEETING_HOTKEY": self.config_mgr.meeting_hotkey,
                "PROMPT_HOTKEY": self.config_mgr.prompt_hotkey,
                "HISTORY_HOTKEY": self.config_mgr.history_hotkey,
                "SPEAK_HOTKEY": self.config_mgr.speak_hotkey,
                "STICKY_HOTKEY": self.config_mgr.sticky_hotkey,
                "CAPTIONS_HOTKEY": self.config_mgr.captions_hotkey,
                "TRANSFORM_HOTKEY": self.config_mgr.transform_hotkey,
                "PROFILE_HOTKEY": self.config_mgr.profile_hotkey,
                "GROQ_MODEL": self.config_mgr.model,
                "GROQ_TRANSLATE_MODEL": self.config_mgr.translate_model,
                "GROQ_LLM_MODEL": self.config_mgr.llm_model,
                "PROCESSING_PROFILE": self.config_mgr.processing_profile,
                "REFINE_PROMPT": self.config_mgr.refine_prompt,
                "SILENT_MODE": self.config_mgr.silent_mode,
                "WHISPER_MODE": self.config_mgr.whisper_mode,
                "PILL_POSITION": self.config_mgr.pill_position,
                "AUTO_SILENCE": self.config_mgr.auto_silence,
                "SILENCE_SECONDS": self.config_mgr.silence_seconds,
                "SILENCE_THRESHOLD": self.config_mgr.silence_threshold,
                "SPEECH_THRESHOLD": self.config_mgr.speech_threshold,
                "MIC_GAIN": self.config_mgr.mic_gain,
                "AUDIO_DEVICE": self.config_mgr.audio_device,
                "SYSTEM_AUDIO_DEVICE": self.config_mgr.system_audio_device,
                "PRIVATE_MODE": self.config_mgr.private_mode,
                "OUTPUTS_DIR": self.config_mgr.outputs_dir,
                "CLEAN_FILLERS": self.config_mgr.clean_fillers,
                "CLIPBOARD_ONLY": self.config_mgr.clipboard_only,
                "OUTPUT_TONE": self.config_mgr.output_tone,
                "INPUT_LANGUAGE": self.config_mgr.input_language,
                "UNDO_HOTKEY": self.config_mgr.undo_hotkey,
                "SEND_HOTKEY": self.config_mgr.send_hotkey,
                "SMART_PARAGRAPHING": self.config_mgr.smart_paragraphing,
                "SAVE_AUDIO_FILES": self.config_mgr.save_audio_files,
                "SILERO_VAD": self.config_mgr.silero_vad,
                "WAKE_WORD_ENABLED": self.config_mgr.wake_word_enabled
            }
            if include_api_key:
                settings["GROQ_API_KEY"] = self.config_mgr.groq_api_key

            dados = {
                "willy_version": __version__,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "settings": settings,
                "vocabulary": vocab_text,
                "snippets": snippets,
                "replacements": self.config_mgr.load_replacements(),
                "app_rules": self.config_mgr.get_app_context_rules(),
            }
            if include_history:
                dados["history"] = self.config_mgr.load_history()

            # Atômico: exportar por cima de um backup anterior não pode deixá-lo pela metade.
            _atomic_write_json(target_path, dados)
            return True
        except Exception as e:  # noqa: BLE001 — fronteira de exportação de perfil
            print(f"[ProfileManager] Erro ao exportar perfil: {e}", file=sys.stderr)
            return False

    def import_profile(self, source_path: str, snippet_mgr=None) -> bool:
        """
        Restaura o perfil completo do Willy a partir de um arquivo JSON.
        """
        if not os.path.exists(source_path):
            return False

        try:
            with open(source_path, "r", encoding="utf-8") as f:
                dados = json.load(f)

            if not isinstance(dados, dict):
                return False

            # Os caminhos do histórico são conferidos contra a pasta de saída de ANTES do
            # import: o próprio perfil não pode alargar a regra que o valida.
            pasta_saida = self.config_mgr.outputs_dir

            settings = self._sanitizar_settings(dados.get("settings"))
            # Um perfil é feito para ser copiado: o de outra pessoa trocava a sua chave sem aviso, e
            # as suas transcrições passavam a ir para a conta dela. A chave do perfil só vale sem
            # chave configurada (decisão do dono, 22/10).
            self.chave_ignorada = False
            chave_do_perfil = settings.get("GROQ_API_KEY")
            chave_atual = self.config_mgr.chave_configurada()
            if chave_do_perfil and chave_atual:
                settings.pop("GROQ_API_KEY")
                self.chave_ignorada = chave_do_perfil.strip() != chave_atual
            vocab = dados.get("vocabulary")
            reps = self._sanitizar_substituicoes(dados.get("replacements"))
            snippets = self._sanitizar_snippets(dados.get("snippets"))
            historico = self._sanitizar_historico(dados.get("history"), pasta_saida)
            # Perfil de antes das regras por aplicativo, sem a chave: as de agora ficam. Com ela,
            # inclusive vazia, o perfil manda (como o vocabulário).
            regras_de_app = dados.get("app_rules")
            regras_de_app = sanitizar_regras_de_app(regras_de_app) if isinstance(regras_de_app, list) else None

            # O perfil de antes do Bloco 11 não tem o atalho do espanhol: se um atalho dele usa a
            # tecla que o espanhol tem agora, o espanhol fica sem atalho, como na atualização
            # (ConfigManager.reload). Sem isso, o espanhol tomava a tecla, e o outro voltava ao de antes.
            from core.config import tecla_do_atalho
            tecla_do_espanhol = tecla_do_atalho(getattr(self.config_mgr, "translate_es_hotkey", ""))
            if ("TRANSLATE_ES_HOTKEY" not in settings and tecla_do_espanhol is not None
                    and any(tecla_do_atalho(v) == tecla_do_espanhol for k, v in settings.items() if k.endswith("_HOTKEY"))):
                settings["TRANSLATE_ES_HOTKEY"] = ""

            if settings:
                self.config_mgr.save_settings(settings)

            # Vazio também: o perfil foi exportado sem vocabulário, e restaurá-lo deixava o
            # vocabulário de agora no lugar. Sem a chave (perfil antigo, ou de outra versão),
            # o vocabulário fica como está.
            if isinstance(vocab, str):
                self.config_mgr.save_vocab_text(vocab)

            if reps is not None:
                self.config_mgr.save_replacements(reps)

            if snippet_mgr and snippets is not None:
                snippet_mgr.replace_snippets(snippets)

            if historico is not None:
                self.config_mgr.history_store.save_history(historico)

            if regras_de_app is not None:
                self.config_mgr.save_app_context_rules(regras_de_app)

            return True
        except Exception as e:  # noqa: BLE001 — fronteira de importação de perfil externo
            print(f"[ProfileManager] Erro ao importar perfil: {e}", file=sys.stderr)
            return False

    @staticmethod
    def _sanitizar_settings(st: Any) -> dict[str, Any]:
        """Só chaves texto com valor escalar; o tipo e a faixa de cada uma o save_settings confere."""
        if not isinstance(st, dict):
            return {}
        limpo = {k: v for k, v in st.items()
                 if isinstance(k, str) and (v is None or isinstance(v, _ESCALARES))}
        # Perfil exportado sem a chave (o padrão), ou com chave vazia, não apaga a chave atual.
        chave = limpo.get("GROQ_API_KEY")
        if not isinstance(chave, str) or not chave.strip() or chave.strip() == "sua_chave_aqui":
            limpo.pop("GROQ_API_KEY", None)
        return limpo

    @staticmethod
    def _sanitizar_substituicoes(reps: Any) -> dict[str, str] | None:
        if not isinstance(reps, dict):
            return None
        return {k: v for k, v in reps.items() if isinstance(k, str) and isinstance(v, str)}

    @staticmethod
    def _sanitizar_snippets(snips: Any) -> list[dict[str, str]] | None:
        if not isinstance(snips, list):
            return None
        validos: list[dict[str, str]] = []
        for s in snips:
            if not isinstance(s, dict):
                continue
            trigger = s.get("trigger")
            content = s.get("content") or s.get("expansion")
            if not isinstance(trigger, str) or not trigger.strip() or not isinstance(content, str) or not content:
                continue
            title = s.get("title")
            if not isinstance(title, str) or not title:
                title = trigger.title()
            validos.append({"trigger": trigger, "title": title, "content": content})
        return validos

    @staticmethod
    def _sanitizar_historico(hist: Any, pasta_saida: Any) -> list[dict[str, Any]] | None:
        """Reconstrói cada entrada só com os campos que o Willy conhece.

        file_path e audio_path viram alvo de os.startfile e do player: de um perfil externo,
        só ficam se forem .md/.wav dentro da pasta de saída do usuário.
        """
        if not isinstance(hist, list):
            return None
        limpos: list[dict[str, Any]] = []
        for item in hist:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                continue
            texto = item["text"]
            entrada: dict[str, Any] = {"text": texto}
            for campo in ("id", "mode", "timestamp"):
                valor = item.get(campo)
                if isinstance(valor, (str, int)) and not isinstance(valor, bool):
                    entrada[campo] = str(valor)
            palavras = item.get("words")
            if isinstance(palavras, int) and not isinstance(palavras, bool) and palavras >= 0:
                entrada["words"] = palavras
            else:
                entrada["words"] = len(texto.split())
            # A duração da gravação é o que dá a velocidade da fala nas métricas: sem ela, o
            # histórico restaurado sumia das palavras por minuto.
            duracao = item.get("duration_s")
            if (isinstance(duracao, (int, float)) and not isinstance(duracao, bool)
                    and math.isfinite(duracao) and duracao >= 0):
                entrada["duration_s"] = float(duracao)
            # A fala antes da IA: sem ela, o item restaurado perdia o "Restaurar original".
            cru = item.get("raw_text")
            if isinstance(cru, str) and cru.strip():
                entrada["raw_text"] = cru
            for campo, extensao in (("file_path", ".md"), ("audio_path", ".wav")):
                if caminho_dentro_de(item.get(campo), pasta_saida, extensao):
                    entrada[campo] = item[campo]
            limpos.append(entrada)
        return limpos[-_MAX_HISTORICO:]
