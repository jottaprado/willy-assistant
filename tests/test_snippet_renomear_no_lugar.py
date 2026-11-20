"""
Trocar o gatilho de um template mantém a posição dele na lista.

A troca gravava o template com o gatilho novo no fim da lista e apagava o antigo: quem
organizava os templates via o editado pular para o último lugar. Com old_trigger, o
save_snippet troca gatilho, título e conteúdo no mesmo índice, numa gravação só.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from core.snippets import SnippetManager


class TestSnippetRenomearNoLugar(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.mgr = SnippetManager(file_path=os.path.join(pasta.name, "snippets.json"))
        for gatilho in ("primeiro", "do meio", "último"):
            self.assertTrue(self.mgr.save_snippet(gatilho, gatilho.title(), f"conteúdo de {gatilho}"))
        self.gatilhos_antes = [s["trigger"] for s in self.mgr.get_snippets()]

    def _gatilhos(self):
        return [s["trigger"] for s in self.mgr.get_snippets()]

    def test_renomear_fica_no_mesmo_lugar(self):
        i = self.gatilhos_antes.index("do meio")
        with patch.object(self.mgr, "_gravar", wraps=self.mgr._gravar) as gravar:
            self.assertTrue(self.mgr.save_snippet("Do Centro", "Centro", "novo conteúdo", old_trigger="do meio"))
        gravar.assert_called_once()
        self.assertEqual(self.gatilhos_antes[:i] + ["do centro"] + self.gatilhos_antes[i + 1:], self._gatilhos())
        editado = self.mgr.get_snippets()[i]
        self.assertEqual(("Centro", "novo conteúdo"), (editado["title"], editado["content"]))

    def test_trocar_so_o_conteudo_com_o_mesmo_gatilho(self):
        self.assertTrue(self.mgr.save_snippet("do meio", "Do Meio", "outro conteúdo", old_trigger="do meio"))
        self.assertEqual(self.gatilhos_antes, self._gatilhos())

    def test_gatilho_de_outro_template_e_recusado(self):
        for novo in ("primeiro", "Último", "ultimo"):
            with self.subTest(novo=novo):
                self.assertFalse(self.mgr.save_snippet(novo, "X", "y", old_trigger="do meio"))
                self.assertEqual(self.gatilhos_antes, self._gatilhos())

    def test_antigo_que_sumiu_vira_salvar_comum(self):
        self.assertTrue(self.mgr.save_snippet("novo", "Novo", "conteúdo", old_trigger="não existe"))
        self.assertEqual(self.gatilhos_antes + ["novo"], self._gatilhos())

    def test_sem_old_trigger_continua_como_antes(self):
        self.assertTrue(self.mgr.save_snippet("do meio", "Do Meio", "mudou"))
        self.assertEqual(self.gatilhos_antes, self._gatilhos())
        self.assertTrue(self.mgr.save_snippet("mais um", "Mais", "conteúdo"))
        self.assertEqual("mais um", self._gatilhos()[-1])

    def test_arquivo_antigo_com_o_gatilho_repetido(self):
        # Achado do 7B: a segunda cópia do gatilho antigo contava como "outro template", e a aba
        # mostrava "Não salvei" para sempre. As cópias saem, como na troca de antes.
        self.assertTrue(self.mgr._gravar([
            {"trigger": "primeiro", "title": "P", "content": "p"},
            {"trigger": "link da reuniao", "title": "L", "content": "url antiga"},
            {"trigger": "do meio", "title": "M", "content": "m"},
            {"trigger": "link da reuniao", "title": "L2", "content": "url repetida"},
        ]))
        self.assertTrue(self.mgr.save_snippet("link da reunião", "Link", "url nova", old_trigger="link da reuniao"))
        self.assertEqual(["primeiro", "link da reunião", "do meio"], self._gatilhos())
        self.assertEqual("url nova", self.mgr.get_snippets()[1]["content"])

    def test_trocar_so_o_conteudo_mantem_a_variante_de_acento(self):
        # Achado do 2º juiz do 7A: editar só o conteúdo do "link da reuniao" apagava o "link da
        # reunião" (outro template, com outra URL).
        self.assertTrue(self.mgr._gravar([
            {"trigger": "link da reuniao", "title": "L", "content": "url padrão"},
            {"trigger": "link da reunião", "title": "L2", "content": "url dela"},
        ]))
        self.assertTrue(self.mgr.save_snippet("link da reuniao", "L", "url nova", old_trigger="link da reuniao"))
        self.assertEqual([("link da reuniao", "url nova"), ("link da reunião", "url dela")],
                         [(s["trigger"], s["content"]) for s in self.mgr.get_snippets()])

    def test_troca_so_de_acento_para_o_gatilho_de_outro_e_recusada(self):
        # Trocar "link da reuniao" por "link da reunião", que já é outro template: dois gatilhos
        # iguais, ou um deles apagado. Nada é gravado, como para qualquer gatilho de outro.
        itens = [{"trigger": "link da reuniao", "title": "L", "content": "url padrão"},
                 {"trigger": "link da reunião", "title": "L2", "content": "url dela"}]
        self.assertTrue(self.mgr._gravar([dict(it) for it in itens]))
        self.assertFalse(self.mgr.save_snippet("link da reunião", "L", "url nova", old_trigger="link da reuniao"))
        self.assertEqual(itens, self.mgr.get_snippets())

    def test_variante_com_outro_acento_e_outro_template(self):
        # Achado do juiz do 7A: trocar "link da reuniao" por "zoom" apagava junto o "link da
        # reunião", outro template, com outro conteúdo (a troca de antes o mantinha).
        self.assertTrue(self.mgr._gravar([
            {"trigger": "link da reuniao", "title": "L", "content": "url sem acento"},
            {"trigger": "link da reunião", "title": "L2", "content": "url com acento"},
            {"trigger": "link da reuniao", "title": "L3", "content": "url repetida"},
        ]))
        self.assertTrue(self.mgr.save_snippet("zoom", "Zoom", "url do zoom", old_trigger="link da reuniao"))
        self.assertEqual(["zoom", "link da reunião"], self._gatilhos())
        self.assertEqual("url com acento", self.mgr.get_snippets()[1]["content"])

    def test_old_trigger_aceita_maiusculas_e_espacos(self):
        self.assertTrue(self.mgr.save_snippet("centro", "C", "z", old_trigger="  Do Meio "))
        self.assertIn("centro", self._gatilhos())
        self.assertNotIn("do meio", self._gatilhos())


if __name__ == "__main__":
    unittest.main()
