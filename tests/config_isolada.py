"""ConfigManager numa pasta temporária: o teste não lê nem grava o .env de verdade.

Sem isto, `ConfigManager()` lia o .env da pasta do repositório (no clone de quem desenvolve,
o de verdade) e, desde a migração dos modelos desligados da Groq, também o reescrevia.
"""

import os
import tempfile
from unittest.mock import patch

ARQUIVOS = (
    ("ENV_FILE", ".env"),
    ("HISTORY_FILE", ".history.json"),
    ("VOCAB_FILE", "vocabulario.txt"),
    ("REPLACEMENTS_FILE", ".replacements.json"),
    ("APP_RULES_FILE", ".app_rules.json"),
    ("FAILED_AUDIO_PATH", "last_failed_audio.wav"),
    ("FLAG_SHOW_DASHBOARD", ".show_dashboard"),
)


def isolar_config(teste) -> str:
    """Aponta os arquivos do core.config, core.snippets e fila de áudio para uma pasta temporária até o fim do teste ou da classe."""
    registrar_limpeza = teste.addClassCleanup if isinstance(teste, type) else teste.addCleanup
    pasta = tempfile.TemporaryDirectory()
    registrar_limpeza(pasta.cleanup)
    patches = [patch(f"core.config.{alvo}", os.path.join(pasta.name, nome)) for alvo, nome in ARQUIVOS]
    # BASE_DIR e USER_DATA_DIR também: sem chave, o ConfigManager procura o .env antigo ao lado do programa,
    # e SnippetManager() / TranscriptionPipeline() consultam USER_DATA_DIR, SNIPPETS_FILE e FAILED_AUDIO_PATH.
    patches += [
        patch("core.config.BASE_DIR", pasta.name),
        patch("core.config.USER_DATA_DIR", pasta.name),
        patch("core.snippets.SNIPPETS_FILE", os.path.join(pasta.name, ".snippets.json")),
        patch("core.pipeline.transcription_pipeline.USER_DATA_DIR", pasta.name),
        patch(
            "core.pipeline.transcription_pipeline.FAILED_AUDIO_PATH",
            os.path.join(pasta.name, "last_failed_audio.wav"),
        ),
        patch.dict(os.environ),
    ]
    for p in patches:
        p.start()
        registrar_limpeza(p.stop)
    return pasta.name
