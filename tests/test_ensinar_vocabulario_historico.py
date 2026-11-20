"""
Bloco 12, funcionalidade 2: "Ensinar ao Willy" direto do Histórico.

A pessoa corrige um ditado no cartão; cada palavra corrigida vira um par (errado -> certo)
(extrair_correcao_vocabulario), e "Ensinar ao Willy" grava a regra de substituição e o termo no
vocabulário (learn_correction), que o Whisper passa a receber no prompt.

Direto: VocabularyStore e ConfigManager de verdade em arquivos temporários, a HistoryTab, o
editor e o WillyDashboard com widgets Tk/CTk de verdade. Nenhum teste toca no clipboard.
"""

import gc
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import customtkinter as ctk

from core.config import ConfigManager
from core.storage.vocabulary_store import VocabularyStore
from core.text_processing import TextProcessor, extrair_correcao_vocabulario
from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.tabs.tab_history import build_tab_history
from ui.tabs.tab_vocabulary import build_tab_vocabulary


def _bombear(root, ate, segundos=3.0):
    fim = time.time() + segundos
    while time.time() < fim:
        root.update()
        if ate():
            return True
        time.sleep(0.01)
    return ate()


class TestExtrairCorrecaoVocabulario(unittest.TestCase):
    def test_uma_palavra(self):
        self.assertEqual([("vily", "Willy")], extrair_correcao_vocabulario("o vily chegou", "o Willy chegou"))

    def test_palavra_composta_vira_uma(self):
        self.assertEqual([("fast api", "FastAPI")],
                         extrair_correcao_vocabulario("subi a fast api ontem", "subi a FastAPI ontem"))

    def test_erro_de_grafia(self):
        self.assertEqual([("kubernets", "Kubernetes")],
                         extrair_correcao_vocabulario("deploy no kubernets.", "deploy no Kubernetes."))

    def test_pontuacao_colada_na_palavra_nao_entra_no_par(self):
        self.assertEqual([("vily", "Willy")], extrair_correcao_vocabulario("Oi, vily, tudo bem?", "Oi, Willy, tudo bem?"))
        self.assertEqual([("dóquer", "Docker")], extrair_correcao_vocabulario("(dóquer)", "(Docker)."))

    def test_so_maiuscula_tambem_e_correcao(self):
        self.assertEqual([("willy", "Willy")], extrair_correcao_vocabulario("falei com willy", "falei com Willy"))

    def test_so_pontuacao_nao_e_correcao(self):
        self.assertEqual([], extrair_correcao_vocabulario("tudo bem. vamos", "tudo bem, vamos?"))
        self.assertEqual([], extrair_correcao_vocabulario("tudo bem.", "tudo bem!"))

    def test_varias_correcoes_na_ordem_e_sem_repetir(self):
        antes = "o vily usa kubernets e o vily gosta"
        depois = "o Willy usa Kubernetes e o Willy gosta"
        self.assertEqual([("vily", "Willy"), ("kubernets", "Kubernetes")], extrair_correcao_vocabulario(antes, depois))

    def test_frase_reescrita_nao_e_correcao(self):
        self.assertEqual([], extrair_correcao_vocabulario("eu acho que a gente devia ir amanhã cedo", "Vamos amanhã"))

    def test_limite_de_quatro_palavras_aceita_quatro_e_recusa_cinco(self):
        self.assertEqual(
            [("alfa beta gama delta", "Alfa Beta Gama Delta")],
            extrair_correcao_vocabulario("inicio alfa beta gama delta fim", "inicio Alfa Beta Gama Delta fim"),
        )
        self.assertEqual(
            [],
            extrair_correcao_vocabulario(
                "inicio alfa beta gama delta epsilon fim",
                "inicio Alfa Beta Gama Delta Epsilon fim",
            ),
        )

    def test_troca_de_sentido_nao_e_correcao(self):
        self.assertEqual([], extrair_correcao_vocabulario("reunião segunda cedo", "reunião terça cedo"))

    def test_palavra_acrescentada_ou_apagada_nao_e_correcao(self):
        self.assertEqual([], extrair_correcao_vocabulario("vamos amanhã", "vamos amanhã cedo"))
        self.assertEqual([], extrair_correcao_vocabulario("vamos amanhã cedo", "vamos amanhã"))

    def test_textos_vazios(self):
        self.assertEqual([], extrair_correcao_vocabulario("", ""))
        self.assertEqual([], extrair_correcao_vocabulario(None, "algo"))


class TestLearnCorrection(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.vocab = os.path.join(pasta.name, "vocabulario.txt")
        self.reps = os.path.join(pasta.name, ".replacements.json")
        self.store = VocabularyStore(self.vocab, self.reps)

    def _ler(self):
        with open(self.vocab, encoding="utf-8") as f:
            vocab = f.read()
        with open(self.reps, encoding="utf-8") as f:
            return vocab, json.load(f)

    def test_grava_a_regra_e_o_termo(self):
        with open(self.vocab, "w", encoding="utf-8") as f:
            f.write("# meus termos\nPython, Docker")
        self.assertTrue(self.store.learn_correction("vily", "Willy"))
        vocab, reps = self._ler()
        self.assertEqual("# meus termos\nPython, Docker\nWilly\n", vocab)
        self.assertEqual({"vily": "Willy"}, reps)

    def test_termo_que_ja_esta_no_vocabulario_nao_repete(self):
        with open(self.vocab, "w", encoding="utf-8") as f:
            f.write("python, willy\n")
        self.assertTrue(self.store.learn_correction("vily", "Willy"))
        vocab, reps = self._ler()
        self.assertEqual("python, willy\n", vocab)
        self.assertEqual({"vily": "Willy"}, reps)

    def test_vocabulario_vazio_ganha_o_termo(self):
        self.assertTrue(self.store.learn_correction("fast api", "FastAPI"))
        self.assertEqual("FastAPI\n", self._ler()[0])

    def test_regra_vale_no_proximo_ditado_em_qualquer_maiuscula(self):
        self.store.learn_correction("vily", "Willy")
        self.assertEqual("O Willy e o Willy", TextProcessor.apply_replacements("O Vily e o vily", self.store.load_replacements()))

    def test_vocabulario_ilegivel_nao_grava_nada(self):
        os.makedirs(self.vocab)  # abrir uma pasta como arquivo falha (PermissionError no Windows)
        self.assertFalse(self.store.learn_correction("vily", "Willy"))
        self.assertFalse(os.path.exists(self.reps), "a regra não pode ficar gravada sozinha")

    def test_termo_com_virgula_so_vira_regra(self):
        self.assertTrue(self.store.learn_correction("node", "Node, Express"))
        self.assertFalse(os.path.exists(self.vocab))
        self.assertEqual({"node": "Node, Express"}, self.store.load_replacements())

    def test_vazios_recusados(self):
        self.assertFalse(self.store.learn_correction("", "Willy"))
        self.assertFalse(self.store.learn_correction("vily", "  "))

    def test_config_manager_ensina_e_o_whisper_recebe_o_termo(self):
        isolar_config(self)
        cfg = ConfigManager()
        self.assertTrue(cfg.learn_correction("kubernets", "Kubernetes"))
        self.assertIn("Kubernetes", cfg.get_vocab_terms())
        self.assertIn("Kubernetes", cfg.get_prompt_context())
        self.assertEqual({"kubernets": "Kubernetes"}, cfg.load_replacements())


class _ComTk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gc.collect()
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        _bombear(cls.root, lambda: False, 0.3)
        destruir_tk(cls.root)
        gc.collect()

    def setUp(self):
        gc.collect()
        isolar_config(self)
        self.cfg = ConfigManager()
        copia = patch("ui.tabs.tab_history.copiar_pelo_clique", return_value=True)
        self.copiar = copia.start()
        self.addCleanup(copia.stop)


class TestEnsinarPeloCartao(_ComTk):
    def setUp(self):
        super().setUp()
        self.aprendidos = []
        self.item = self.cfg.save_history_item("o vily subiu a fast api no kubernets")[0]
        self.tab = build_tab_history(
            self.root,
            callbacks={"get_history": self.cfg.load_history, "on_learn_correction": self.cfg.learn_correction},
            history_items=self.cfg.load_history(),
            ao_aprender_vocabulario=self.aprendidos.extend,
        )
        self.addCleanup(lambda: self.tab.winfo_exists() and self.tab.destroy())
        self.tab.atualizar_lista_historico()

    def _abrir_editor_pelo_menu(self):
        cartao = self.tab.scroll_historico.winfo_children()[0]
        linha = next(w for w in cartao.winfo_children() if isinstance(w, ctk.CTkFrame))
        enter = linha._canvas.bind("<Enter>")
        self.tab.tk.call(enter.split("[", 1)[1].split()[0], *(["0"] * 19))
        meta = next(w for w in linha.winfo_children() if isinstance(w, ctk.CTkFrame))
        caixa = next(w for w in meta.winfo_children() if isinstance(w, ctk.CTkFrame))
        [w for w in caixa.winfo_children() if isinstance(w, ctk.CTkButton)][-2].invoke()  # Reformatar
        opcoes = {b.cget("text"): b for b in self.tab._item_menu_popup.winfo_children() if isinstance(b, ctk.CTkButton)}
        opcoes["Editar e ensinar ao Willy..."].invoke()
        dialogos = [w for w in self.tab.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        self.assertEqual(1, len(dialogos))
        return dialogos[0]

    @staticmethod
    def _botoes(dialogo):
        achados, fila = {}, [dialogo]
        while fila:
            w = fila.pop()
            if isinstance(w, ctk.CTkButton):
                achados[w.cget("text")] = w
            fila.extend(w.winfo_children())
        return achados

    def _digitar(self, dialogo, texto):
        """Troca o texto da caixa como uma colagem: sem tecla, o <<Modified>> é que avisa."""
        caixa = next(w for w in dialogo.winfo_children() if isinstance(w, ctk.CTkTextbox))
        caixa.delete("1.0", "end")
        caixa.insert("1.0", texto)

    def test_corrigir_mostra_os_pares_e_ensinar_grava_tudo(self):
        dialogo = self._abrir_editor_pelo_menu()
        self._digitar(dialogo, "o Willy subiu a FastAPI no Kubernetes")
        self.assertTrue(_bombear(self.root, lambda: any("3 correções" in t for t in self._botoes(dialogo))))
        self._botoes(dialogo)["🧠 Ensinar ao Willy (3 correções)"].invoke()

        salvo = self.cfg.load_history()[0]
        self.assertEqual(("o Willy subiu a FastAPI no Kubernetes", "o vily subiu a fast api no kubernets"),
                         (salvo["text"], salvo["raw_text"]))
        self.assertEqual({"vily": "Willy", "fast api": "FastAPI", "kubernets": "Kubernetes"}, self.cfg.load_replacements())
        for termo in ("Willy", "FastAPI", "Kubernetes"):
            self.assertIn(termo, self.cfg.get_vocab_terms())
        self.assertEqual(["Willy", "FastAPI", "Kubernetes"], self.aprendidos)
        self.assertIn("Willy aprendeu", self.tab.lbl_toast.cget("text"))
        self.assertFalse(dialogo.winfo_exists())
        self.copiar.assert_not_called()

    def test_uma_correcao_aparece_no_botao(self):
        dialogo = self._abrir_editor_pelo_menu()
        self._digitar(dialogo, "o Willy subiu a fast api no kubernets")
        self.assertTrue(_bombear(self.root, lambda: "🧠 Ensinar ao Willy (vily → Willy)" in self._botoes(dialogo)))

    def test_sem_correcao_o_ensinar_fica_desligado(self):
        dialogo = self._abrir_editor_pelo_menu()
        self.assertEqual("disabled", self._botoes(dialogo)["🧠 Ensinar ao Willy"].cget("state"))

    def test_salvar_edicao_nao_ensina(self):
        dialogo = self._abrir_editor_pelo_menu()
        self._digitar(dialogo, "o Willy subiu a fast api no kubernets")
        self._botoes(dialogo)["Salvar edição"].invoke()
        self.assertEqual("o Willy subiu a fast api no kubernets", self.cfg.load_history()[0]["text"])
        self.assertEqual({}, self.cfg.load_replacements())
        self.assertEqual([], self.aprendidos)

    def test_texto_vazio_nao_salva(self):
        dialogo = self._abrir_editor_pelo_menu()
        self._digitar(dialogo, "   ")
        self._botoes(dialogo)["Salvar edição"].invoke()
        self.assertTrue(dialogo.winfo_exists())
        self.assertEqual("o vily subiu a fast api no kubernets", self.cfg.load_history()[0]["text"])
        dialogo.destroy()

    def test_falha_ao_gravar_o_vocabulario_avisa(self):
        self.tab.callbacks["on_learn_correction"] = lambda de, para: False
        dialogo = self._abrir_editor_pelo_menu()
        self._digitar(dialogo, "o Willy subiu a fast api no kubernets")
        self.assertTrue(_bombear(self.root, lambda: "🧠 Ensinar ao Willy (vily → Willy)" in self._botoes(dialogo)))
        self._botoes(dialogo)["🧠 Ensinar ao Willy (vily → Willy)"].invoke()
        self.assertIn("não consegui gravar o vocabulário", self.tab.lbl_toast.cget("text"))
        self.assertEqual([], self.aprendidos)


class TestVocabularioRecebeOAprendizado(_ComTk):
    def _aba(self):
        tab = build_tab_vocabulary(self.root, callbacks={
            "get_vocab": self.cfg.load_vocab_text, "on_save_vocab": self.cfg.save_vocab_text,
            "get_replacements": self.cfg.load_replacements})
        self.addCleanup(tab.destroy)
        return tab

    def test_sem_edicao_pendente_rele_termos_e_regras(self):
        tab = self._aba()
        self.cfg.learn_correction("vily", "Willy")
        tab.receber_termos_aprendidos(["Willy"])
        self.assertIn("Willy", tab.txt_vocab.get("1.0", "end"))
        self.assertIn("vily", [rotulo for rotulo in self._textos(tab.frame_reps_lista)])

    def test_com_edicao_pendente_o_termo_entra_na_caixa_e_a_edicao_fica(self):
        tab = self._aba()
        tab.txt_vocab.insert("end", "\nTermoQueEuDigitei")
        tab._on_vocab_keyrelease()  # auto-save agendado: edição pendente
        self.cfg.learn_correction("vily", "Willy")
        tab.receber_termos_aprendidos(["Willy"])
        caixa = tab.txt_vocab.get("1.0", "end")
        self.assertIn("TermoQueEuDigitei", caixa)
        self.assertIn("Willy", caixa)
        tab.salvar_vocabulario()  # o auto-save grava a caixa inteira: o termo aprendido continua
        self.assertIn("Willy", self.cfg.get_vocab_terms())
        self.assertIn("TermoQueEuDigitei", self.cfg.get_vocab_terms())

    @staticmethod
    def _textos(widget):
        textos, fila = [], [widget]
        while fila:
            w = fila.pop()
            if isinstance(w, ctk.CTkLabel):
                textos.extend(w.cget("text").replace("→", " ").split())
            fila.extend(w.winfo_children())
        return textos


class TestDashboardLigaOHistoricoAoVocabulario(unittest.TestCase):
    def test_ensinar_no_historico_atualiza_a_aba_vocabulario(self):
        isolar_config(self)
        cfg = ConfigManager()
        from ui.dashboard import WillyDashboard
        dash = WillyDashboard(callbacks={"get_history": list, "get_app_rules": list, "get_vocab": cfg.load_vocab_text,
                                         "get_replacements": cfg.load_replacements})
        self.addCleanup(dash.destroy)
        dash.withdraw()
        self.assertEqual(dash._vocabulario_aprendido, dash.tab_history.ao_aprender_vocabulario)
        cfg.learn_correction("kubernets", "Kubernetes")
        dash.tab_history.ao_aprender_vocabulario(["Kubernetes"])
        self.assertIn("Kubernetes", dash.tab_vocab.txt_vocab.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
