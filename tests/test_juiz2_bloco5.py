"""
Achados do segundo juiz do Bloco 5, com o defeito de cada um reproduzido.

- "Willy, inserir ata de reunião" caía no copiloto de ações (começa com "Willy,"): um Ctrl+C
  ia ao app e a resposta do LLM era colada no lugar do template.
- core/actions.py chamava o LLM direto, sem a porta que tira o <think> do Qwen e dá margem
  ao raciocínio.
- Com a janela maximizada ("zoomed") ou restaurada pela barra de tarefas, o Histórico ficava
  sem os ditados novos.
- Um atalho que pedia a combinação de outro e não tinha anterior deixava a repetida na
  config, e na partida seguinte tirava a tecla do outro.
- Template e resposta de ação entravam na velocidade da fala com a duração da gravação.
- Salvar um gatilho num arquivo antigo com as duas grafias deixava dois iguais.
"""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.actions import ActionManager
from core.snippets import DEFAULT_SNIPPETS, SnippetManager
from core.system.hotkey_orchestrator import HotkeyOrchestrator
from tests.test_fila_audio_falho import _Pipeline
from tests.test_recarregar_atalhos import ConfigFalsa, GerenciadorFalso
from tests.test_static_analysis import chamadas_chat_fora_do_completar
from tests.willy_isolado import destruir_tk

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wav(segundos=3.0):
    from tests.test_velocidade_medida import _wav as gerar
    return gerar(segundos)


class TestInserirTemplatePeloPipeline(_Pipeline):
    def setUp(self):
        super().setUp()
        pasta = tempfile.mkdtemp(dir=self.tmp)
        self.pipeline.snippet_mgr = SnippetManager(file_path=os.path.join(pasta, "snippets.json"))

    def _falar(self, fala):
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = fala
        with patch.object(ActionManager, "process_action") as acao, \
             patch.object(ActionManager, "get_selected_text") as selecao:
            from core.pipeline import PipelineContext
            self.pipeline.process(PipelineContext(wav_bytes=_wav(), modo="transcribe",
                                                  app_context=("code.exe", "editor", "general")))
        return acao, selecao

    def test_willy_inserir_cola_o_template_sem_passar_pelo_copiloto(self):
        ata = next(s["content"] for s in DEFAULT_SNIPPETS if s["trigger"] == "ata de reuniao")
        acao, selecao = self._falar("Willy, inserir ata de reunião.")
        acao.assert_not_called()
        selecao.assert_not_called()  # sem o Ctrl+C mandado ao app para ler a seleção
        self.assertEqual(ata, self.injector.paste_text.call_args.args[0])

    def test_template_nao_entra_na_velocidade_da_fala(self):
        self._falar("Willy, inserir ata de reunião.")
        self.assertIsNone(self.pipeline.config_mgr.save_history_item.call_args.kwargs["duracao_s"])

    def test_pedido_ao_copiloto_continua_indo_ao_copiloto(self):
        self.groq_service.transform_text.return_value = "Três tópicos."
        self._falar("Willy, resuma em três tópicos")  # "resuma" é transformação da seleção
        self.groq_service.transform_text.assert_called_once()
        self.assertEqual("Três tópicos.", self.injector.paste_text.call_args.args[0])


class TestPortaUnicaDoLLM(unittest.TestCase):
    def test_nenhuma_chamada_de_chat_fora_do_completar(self):
        self.assertEqual([], chamadas_chat_fora_do_completar(), "chame o LLM por GroqService.completar")

    def test_acao_usa_a_porta_e_devolve_o_texto_limpo(self):
        servico = MagicMock(llm_model="qwen/qwen3.8-27b")
        servico.completar_com_reserva.return_value = "Três tópicos."
        self.assertEqual("Três tópicos.", ActionManager.process_action("resuma isso", servico, "um texto"))
        servico.completar_com_reserva.assert_called_once()


class TestHistoricoComAJanelaMaximizadaOuRestaurada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.config_isolada import isolar_config
        from ui.dashboard import WillyDashboard
        isolar_config(cls)
        cls.dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list})
        cls.dash.withdraw()

    @classmethod
    def tearDownClass(cls):
        destruir_tk(cls.dash)

    def _recarregar(self, estado):
        with patch.object(self.dash, "atualizar_lista_historico") as refazer, \
             patch.object(self.dash, "state", return_value=estado):
            self.dash.recarregar_dados()
        return refazer

    def test_maximizada_refaz(self):
        self._recarregar("zoomed").assert_called_once_with()

    def test_minimizada_deixa_pendente_e_refaz_ao_voltar(self):
        self._recarregar("iconic").assert_not_called()
        with patch.object(self.dash, "atualizar_lista_historico") as refazer, \
             patch.object(self.dash, "after_idle", side_effect=lambda f: f()):
            self.dash._on_janela_mapeada(SimpleNamespace(widget=self.dash.tab_history))  # de um widget de dentro
            refazer.assert_not_called()
            self.dash._on_janela_mapeada(SimpleNamespace(widget=self.dash))
            self.dash._on_janela_mapeada(SimpleNamespace(widget=self.dash))
        refazer.assert_called_once_with()


class TestRepetidaSemAnterior(unittest.TestCase):
    def setUp(self):
        self.voz, self.mestre = (lambda: "voz"), (lambda: "mestre")

    def _orq(self, mgr, config):
        return HotkeyOrchestrator(mgr, config, {"voice": self.voz, "master": self.mestre})

    def test_na_recarga_o_campo_fica_vazio_e_a_partida_seguinte_nao_tira_a_tecla_da_voz(self):
        config = ConfigFalsa(hotkey="ctrl+space", master_hotkey="ctrl+alt+z")
        self._orq(GerenciadorFalso(ocupados={"ctrl+alt+z"}), config).registrar_todos()  # mestre sem tecla
        orq = self._orq(mgr := GerenciadorFalso(ocupados={"ctrl+alt+z"}), config)
        orq.registrar_todos()
        config.master_hotkey = "ctrl+space"
        orq.recarregar_se_necessario({"MASTER_HOTKEY": "ctrl+space"})
        self.assertIs(self.voz, mgr.ativos["ctrl+space"])
        self.assertEqual("", config.master_hotkey)

        partida = GerenciadorFalso()
        self._orq(partida, config).registrar_todos()
        self.assertIs(self.voz, partida.ativos["ctrl+space"], "o mestre levou o Ctrl+Espaço do ditado")

    def test_na_partida_nada_e_apagado(self):
        config = ConfigFalsa(hotkey="ctrl+space", master_hotkey="ctrl+space")
        self._orq(GerenciadorFalso(), config).registrar_todos()
        self.assertEqual([], config.salvos)


class TestGatilhoNumArquivoAntigo(unittest.TestCase):
    def test_salvar_um_dos_dois_nao_cria_gatilhos_iguais(self):
        with tempfile.TemporaryDirectory() as pasta:
            mgr = SnippetManager(file_path=os.path.join(pasta, "s.json"))
            with open(mgr.file_path, "w", encoding="utf-8") as f:
                json.dump([{"trigger": "link da reuniao", "title": "Padrão", "content": "padrão"},
                           {"trigger": "link da reunião", "title": "Meu", "content": "meu"}], f)
            mgr.save_snippet("link da reunião", "Meu", "meu novo")
            gatilhos = [s["trigger"] for s in mgr.get_snippets()]
            self.assertEqual(["link da reuniao", "link da reunião"], gatilhos)
            self.assertEqual("meu novo", mgr.match_and_expand("link da reunião"))


@unittest.skipUnless(sys.platform == "win32", "janelas do Win32")
class TestJanelaDeFerramentaNaoEApp(unittest.TestCase):
    def test_janela_de_ferramenta_visivel_nao_e_para_onde_colar(self):
        import ctypes
        import tkinter as tk

        from core.context import ContextManager
        root = tk.Tk()
        try:
            root.geometry("200x100+-4000+-4000")
            root.attributes("-toolwindow", True)
            root.update()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            self.assertTrue(ContextManager.eh_janela_do_shell(hwnd))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
