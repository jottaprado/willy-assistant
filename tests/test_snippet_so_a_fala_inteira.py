"""
Um template só entra quando a fala inteira é o gatilho.

O casamento aceitava a fala que COMEÇA com o gatilho, e o resto da frase sumia: "Meu pix mudou
de banco ontem" colava a chave PIX, "Link da reunião de amanhã foi alterado" colava o link de
exemplo. É ditado comum, e a pessoa recebia um template no lugar.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from core.actions import ActionManager
from core.pipeline import PipelineContext
from core.snippets import DEFAULT_SNIPPETS, SnippetManager
from tests.test_fila_audio_falho import _Pipeline
from tests.test_velocidade_medida import _wav


def _conteudo(gatilho):
    return next(s["content"] for s in DEFAULT_SNIPPETS if s["trigger"] == gatilho)


class TestCasamento(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mgr = SnippetManager(file_path=os.path.join(self.tmp.name, "snippets.json"))

    def test_frase_que_so_comeca_com_o_gatilho_nao_vira_template(self):
        for fala in ("Meu pix mudou de banco ontem.", "Link da reunião de amanhã foi alterado.",
                     "Ata de reunião de ontem ficou ótima.", "Meu pixel quebrou", "Template de bug não existe"):
            with self.subTest(fala=fala):
                self.assertIsNone(self.mgr.match_and_expand(fala))

    def test_a_fala_que_e_o_gatilho_continua_virando_template(self):
        for fala in ("meu pix", "Meu pix.", "Willy, inserir meu pix!", "Colar meu pix?"):
            with self.subTest(fala=fala):
                self.assertEqual(_conteudo("meu pix"), self.mgr.match_and_expand(fala))


class TestDitadoComumPeloPipeline(_Pipeline):
    def setUp(self):
        super().setUp()
        self.pipeline.snippet_mgr = SnippetManager(file_path=os.path.join(self.tmp, "snippets.json"))

    def test_frase_com_o_gatilho_no_comeco_e_colada_como_foi_dita(self):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = "Meu pix mudou de banco ontem"
        with patch.object(ActionManager, "process_action"):
            self.pipeline.process(PipelineContext(wav_bytes=_wav(2.0), modo="transcribe",
                                                  app_context=("code.exe", "editor", "general")))
        colado = self.injector.paste_text.call_args.args[0]
        self.assertNotIn("Chave PIX", colado)
        self.assertIn("mudou de banco ontem", colado)


if __name__ == "__main__":
    unittest.main()
