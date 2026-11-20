"""
O gatilho de um template casa com a fala com ou sem acento.

O Whisper transcreve "link da reunião", e o gatilho padrão é "link da reuniao": a
comparação era só .lower(), e falar o gatilho não colava o template.
"""

import json
import os
import tempfile
import unittest

from core.snippets import DEFAULT_SNIPPETS, SnippetManager


def _conteudo_padrao(gatilho):
    return next(s["content"] for s in DEFAULT_SNIPPETS if s["trigger"] == gatilho)


class TestGatilhoSemAcento(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mgr = SnippetManager(file_path=os.path.join(self.tmp.name, "snippets.json"))

    def test_fala_com_acento_aciona_o_gatilho_padrao_sem_acento(self):
        self.assertEqual(_conteudo_padrao("link da reuniao"), self.mgr.match_and_expand("Link da reunião."))

    def test_com_prefixo_de_comando(self):
        self.assertEqual(_conteudo_padrao("ata de reuniao"), self.mgr.match_and_expand("Inserir ata de reunião"))

    def test_gatilho_com_acento_aciona_com_fala_sem_acento(self):
        self.mgr.save_snippet("assinatura da relação", "Assinatura", "Atenciosamente")
        self.assertEqual("Atenciosamente", self.mgr.match_and_expand("assinatura da relacao"))

    def test_cedilha_e_til(self):
        self.mgr.save_snippet("template de integracao", "Integração", "### INTEGRAÇÃO")
        self.assertEqual("### INTEGRAÇÃO", self.mgr.match_and_expand("template de integração"))

    def test_vocativo_com_virgula_e_dois_prefixos(self):
        # O Whisper escreve "Willy, inserir...": com a vírgula e o segundo prefixo, não casava.
        self.assertEqual(_conteudo_padrao("ata de reuniao"), self.mgr.match_and_expand("Willy, inserir ata de reunião."))
        self.assertEqual(_conteudo_padrao("meu pix"), self.mgr.match_and_expand("Ei Willy: colar meu pix"))

    def test_fala_que_nao_e_gatilho_continua_sem_template(self):
        self.assertIsNone(self.mgr.match_and_expand("a reunião de amanhã foi cancelada"))

    # Achado do juiz: quem criou "link da reunião" porque o padrão sem acento não funcionava
    # passava a receber o link de exemplo do padrão, que vinha antes na lista.

    def test_gatilho_com_acento_da_pessoa_substitui_o_padrao_equivalente(self):
        self.mgr.save_snippet("link da reunião", "Meu link", "https://meet.exemplo/minha-sala")
        equivalentes = [s for s in self.mgr.get_snippets() if s["trigger"] in ("link da reuniao", "link da reunião")]
        self.assertEqual([("link da reunião", "https://meet.exemplo/minha-sala")],
                         [(s["trigger"], s["content"]) for s in equivalentes])
        self.assertEqual("https://meet.exemplo/minha-sala", self.mgr.match_and_expand("Link da reunião."))

    def test_arquivo_antigo_com_os_dois_vence_o_que_a_fala_escreve_igual(self):
        with open(self.mgr.file_path, "w", encoding="utf-8") as f:
            json.dump([{"trigger": "link da reuniao", "title": "Padrão", "content": "padrão"},
                       {"trigger": "link da reunião", "title": "Meu", "content": "meu"}], f)
        self.assertEqual("meu", self.mgr.match_and_expand("link da reunião"))
        self.assertEqual("padrão", self.mgr.match_and_expand("link da reuniao"))


if __name__ == "__main__":
    unittest.main()
