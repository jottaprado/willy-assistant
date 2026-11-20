"""
Bloco 12, funcionalidade 1: a fala antes da IA (raw_text) no histórico, e o "Reformatar /
Traduzir / Restaurar original" do cartão e do Spotlight.

Direto, sem teatro: HistoryStore, ConfigManager e ProfileManager de verdade em arquivos
temporários (isolar_config), o TranscriptionPipeline de verdade com a Groq em autospec, e a
HistoryTab e o HistorySpotlight com widgets Tk/CTk de verdade. A cópia do cartão é trocada por
um registro: nenhum teste toca no clipboard da sessão.
"""

import gc
import json
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

import customtkinter as ctk

from core.config import ConfigManager
from core.groq_service import FalhaDoLLM, GroqService
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.storage.history_store import _HISTORY_LOCK, HistoryStore
from core.system.injector import TextInjector
from tests.config_isolada import isolar_config
from tests.willy_isolado import destruir_tk
from ui.overlays import spotlight as sp
from ui.overlays.spotlight import HistorySpotlight
from ui.tabs.tab_history import build_tab_history

WAV = b"RIFF" + b"\0" * 40


def _bombear(root, ate, segundos=3.0):
    """Roda o laço do Tk até `ate()` ser verdade (ou o prazo acabar). Devolve `ate()`."""
    fim = time.time() + segundos
    while time.time() < fim:
        root.update()
        if ate():
            return True
        time.sleep(0.01)
    return ate()


class TestHistoryStoreGuardaOTextoCru(unittest.TestCase):
    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        self.caminho = os.path.join(pasta.name, ".history.json")
        self.store = HistoryStore(self.caminho)

    def _no_disco(self):
        with open(self.caminho, encoding="utf-8") as f:
            return json.load(f)

    def test_raw_text_diferente_do_texto_fica(self):
        self.store.save_history_item("Olá, tudo bem?", raw_text="ola tudo bem")
        self.assertEqual("ola tudo bem", self._no_disco()[0]["raw_text"])

    def test_raw_text_igual_vazio_ou_ausente_nao_fica(self):
        self.store.save_history_item("igual", raw_text="igual")
        self.store.save_history_item("vazio", raw_text="   ")
        self.store.save_history_item("sem")
        self.assertEqual([False, False, False], ["raw_text" in it for it in self._no_disco()])

    def test_primeira_troca_guarda_o_original_e_as_seguintes_o_mantem(self):
        item = self.store.save_history_item("texto ditado sem IA")[0]
        self.assertTrue(self.store.update_item_text(item["id"], "Texto formal número um", "transcribe"))
        self.assertTrue(self.store.update_item_text(item["id"], "Text in English", "translate"))
        salvo = self._no_disco()[0]
        self.assertEqual(("Text in English", "translate", 3, "texto ditado sem IA"),
                         (salvo["text"], salvo["mode"], salvo["words"], salvo["raw_text"]))

    def test_raw_text_que_ja_existe_nao_e_trocado_pelo_preservar_raw(self):
        item = self.store.save_history_item("Refinado.", raw_text="a fala")[0]
        self.store.update_item_text(item["id"], "Outro.", preservar_raw="não é a fala")
        self.assertEqual("a fala", self._no_disco()[0]["raw_text"])

    def test_preservar_raw_vale_sem_raw_text(self):
        item = self.store.save_history_item("refinado")[0]
        self.store.update_item_text(item["id"], "novo", preservar_raw="a fala crua")
        self.assertEqual("a fala crua", self._no_disco()[0]["raw_text"])

    def test_modo_fica_quando_nao_e_informado(self):
        item = self.store.save_history_item("pedido", modo="prompt")[0]
        self.store.update_item_text(item["id"], "pedido reescrito")
        self.assertEqual("prompt", self._no_disco()[0]["mode"])

    def test_sem_o_item_ou_com_texto_vazio_nada_e_gravado(self):
        self.store.save_history_item("fica")
        antes = os.path.getmtime(self.caminho)
        time.sleep(0.02)
        self.assertFalse(self.store.update_item_text("nao-existe", "novo"))
        item_id = self._no_disco()[0]["id"]
        self.assertFalse(self.store.update_item_text(item_id, "   "))
        self.assertEqual(antes, os.path.getmtime(self.caminho))
        self.assertEqual("fica", self._no_disco()[0]["text"])

    def test_historico_ilegivel_nao_e_sobrescrito(self):
        with open(self.caminho, "w", encoding="utf-8") as f:
            f.write('[{"id": "1", "text": "trunca')
        self.assertFalse(self.store.update_item_text("1", "novo"))
        with open(self.caminho, encoding="utf-8") as f:
            self.assertEqual('[{"id": "1", "text": "trunca', f.read())

    def test_update_item_text_espera_o_lock_e_nao_apaga_ditado_concorrente(self):
        item1 = self.store.save_history_item("um")[0]
        leu = threading.Event()
        load_real = self.store._load_strict

        def _load_sondado():
            leu.set()
            return load_real()

        with patch.object(self.store, "_load_strict", side_effect=_load_sondado):
            with _HISTORY_LOCK:
                t = threading.Thread(target=self.store.update_item_text, args=(item1["id"], "um editado"))
                self.addCleanup(lambda: t.is_alive() and t.join(timeout=2.0))
                t.start()
                self.assertFalse(leu.wait(0.2), "update_item_text leu o disco sem esperar o _HISTORY_LOCK")
                self.store.save_history_item("dois")
            t.join(timeout=2.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(["um editado", "dois"], [it["text"] for it in self._no_disco()])


class TestConfigEPerfilLevamORaw(unittest.TestCase):
    def setUp(self):
        self.pasta = isolar_config(self)
        self.cfg = ConfigManager()

    def test_config_manager_repassa_o_raw_text(self):
        self.cfg.save_history_item("Final.", modo="meeting", raw_text="transcrição da reunião")
        self.assertEqual("transcrição da reunião", self.cfg.load_history()[0]["raw_text"])

    def test_exportar_e_importar_o_historico_preserva_o_raw_text(self):
        self.cfg.save_history_item("Refinado.", raw_text="a fala crua")
        perfil = os.path.join(self.pasta, "perfil.json")
        self.assertTrue(self.cfg.export_profile(perfil, include_history=True))
        self.cfg.clear_history()
        self.assertTrue(self.cfg.import_profile(perfil))
        self.assertEqual(("Refinado.", "a fala crua"),
                         (self.cfg.load_history()[0]["text"], self.cfg.load_history()[0]["raw_text"]))

    def test_raw_text_que_nao_e_texto_sai_no_import(self):
        perfil = os.path.join(self.pasta, "perfil.json")
        with open(perfil, "w", encoding="utf-8") as f:
            json.dump({"history": [{"id": "1", "text": "a", "raw_text": 42},
                                   {"id": "2", "text": "b", "raw_text": "  "},
                                   {"id": "3", "text": "c", "raw_text": "fala"}]}, f)
        self.assertTrue(self.cfg.import_profile(perfil))
        self.assertEqual([None, None, "fala"], [it.get("raw_text") for it in self.cfg.load_history()])


class _PipelineDeVerdade(unittest.TestCase):
    """TranscriptionPipeline com ConfigManager de verdade (isolado) e a Groq em autospec."""

    def setUp(self):
        self.pasta = isolar_config(self)
        for funcao in ("_foco_numa_janela_do_willy", "_foco_no_shell"):
            p = patch(f"core.pipeline.transcription_pipeline.{funcao}", return_value=False)
            p.start()
            self.addCleanup(p.stop)
        # Sem janela-alvo nem foco no Willy, o pipeline cola pelo injector (autospec); a cópia de
        # reserva, se acontecesse, iria ao clipboard da sessão: vira registro.
        copia = patch("core.actions.ActionManager.secure_copy", return_value=True)
        self.copia = copia.start()
        self.addCleanup(copia.stop)
        self.cfg = ConfigManager()
        # Todo ajuste de que o teste depende, explícito: o os.environ pode chegar com o de um teste
        # anterior (o reload usa load_dotenv com override).
        self.cfg.save_settings({"GROQ_API_KEY": "gsk_teste", "OUTPUTS_DIR": os.path.join(self.pasta, "saida"),
                                "REFINE_PROMPT": True, "CLEAN_FILLERS": False, "PROCESSING_PROFILE": "dev",
                                "CLIPBOARD_ONLY": False, "PRIVATE_MODE": False, "OUTPUT_TONE": "natural"})
        self.groq = create_autospec(GroqService, instance=True)
        self.injector = create_autospec(TextInjector, instance=True)
        self.injector.paste_text.return_value = True
        self.audio = SimpleNamespace(lock=threading.Lock(), is_processing=False, is_recording=False)
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq, config_mgr=self.cfg, audio_mgr=self.audio, injector=self.injector,
            user_data_dir=self.pasta)

    def _ditar(self, modo="transcribe", **kw):
        kw.setdefault("app_context", ("notepad.exe", "Sem título", "GENERAL"))
        return self.pipeline.process(PipelineContext(wav_bytes=WAV, modo=modo, **kw))


class TestPipelineGuardaAFalaAntesDaIA(_PipelineDeVerdade):
    def test_ditado_guarda_o_que_entrou_no_refino_com_as_substituicoes(self):
        self.cfg.add_replacement("vily", "Willy")
        self.groq.transcribe.return_value = "o vily chegou agora na reunião de hoje"
        self.groq.refine_text.side_effect = lambda texto, **kw: "O vily chegou agora à reunião de hoje."
        self.assertTrue(self._ditar().success)
        item = self.cfg.load_history()[-1]
        entrou_no_refino = self.groq.refine_text.call_args.args[0]
        self.assertIn("vily", entrou_no_refino)
        self.assertEqual("O Willy chegou agora à reunião de hoje.", item["text"])
        self.assertEqual(entrou_no_refino.replace("vily", "Willy"), item["raw_text"])

    def test_refino_desligado_nao_guarda_texto_cru(self):
        self.cfg.save_settings({"REFINE_PROMPT": False})
        self.groq.transcribe.return_value = "ditado sem refino nenhum aqui"
        self.groq.refine_text.side_effect = lambda texto, enabled=True, **kw: texto
        self._ditar()
        self.assertNotIn("raw_text", self.cfg.load_history()[-1])

    def test_espanhol_guarda_o_portugues_ditado(self):
        self.groq.transcribe.return_value = "bom dia equipe"
        self.groq.translate_to_spanish.return_value = "Buenos días, equipo"
        self._ditar(modo="translate_es")
        item = self.cfg.load_history()[-1]
        # O português depois dos comandos de voz (que põem a maiúscula), antes do LLM.
        self.assertEqual(("Buenos días, equipo", "Bom dia equipe", "translate_es"),
                         (item["text"], item["raw_text"], item["mode"]))
        self.assertEqual("Bom dia equipe", self.groq.translate_to_spanish.call_args.args[0])

    def test_reuniao_guarda_a_transcricao_antes_da_ata(self):
        self.groq.transcribe.return_value = "falamos do orçamento e do prazo"
        self.groq.summarize_meeting.return_value = "## Ata\n- Orçamento\n- Prazo"
        self._ditar(modo="meeting")
        self.assertEqual("falamos do orçamento e do prazo", self.cfg.load_history()[-1]["raw_text"])

    def test_modo_prompt_guarda_o_pedido_falado_antes_do_goal(self):
        self.cfg.save_settings({"CLEAN_FILLERS": True})
        self.cfg.add_replacement("vily", "Willy")
        self.groq.transcribe.return_value = "ééé crie um teste para o vily"
        self.groq.generate_agent_prompt.return_value = "/goal Crie um teste para o vily"
        self.assertTrue(self._ditar(modo="prompt").success)
        item = self.cfg.load_history()[-1]
        self.assertEqual(("/goal Crie um teste para o Willy", "Crie um teste para o Willy", "prompt"),
                         (item["text"], item["raw_text"], item["mode"]))

    def test_arquivo_externo_com_ata_guarda_a_transcricao_no_raw_text(self):
        self.cfg.add_replacement("vily", "Willy")
        caminho_wav = os.path.join(self.pasta, "reuniao.wav")
        with open(caminho_wav, "wb") as f:
            f.write(WAV)
        self.groq.transcribe_file.return_value = "reunião com o vily sobre o orçamento"
        self.groq.summarize_meeting.return_value = "## Ata\n- Reunião com o vily"
        res = self.pipeline.transcrever_arquivo_externo(caminho_wav, gerar_ata=True)
        self.assertEqual("## Ata\n- Reunião com o Willy", res)
        item = self.cfg.load_history()[-1]
        self.assertEqual(("## Ata\n- Reunião com o Willy", "reunião com o Willy sobre o orçamento", "meeting"),
                         (item["text"], item["raw_text"], item["mode"]))

    def test_modo_privado_nao_grava_nada(self):
        self.cfg.save_settings({"PRIVATE_MODE": True})
        self.groq.transcribe.return_value = "segredo ditado agora mesmo"
        self.groq.refine_text.return_value = "Segredo ditado agora mesmo."
        self.assertTrue(self._ditar().success)
        self.assertEqual([], self.cfg.load_history())


class _AbaDeHistorico(unittest.TestCase):
    """HistoryTab de verdade sobre um histórico de verdade (isolado). A cópia vira registro."""

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
        gc.collect()  # o lixo Tk de antes, coletado aqui, e não na thread da IA (ver Font.__del__)
        isolar_config(self)
        self.store = HistoryStore()
        self.copias = []
        copia = patch("ui.tabs.tab_history.copiar_pelo_clique",
                      side_effect=lambda texto, ocultar: (self.copias.append((texto, ocultar)), True)[1])
        copia.start()
        self.addCleanup(copia.stop)
        self.pedidos = []
        self.chave = "gsk_teste"

    def _reformatar(self, texto, acao):
        self.pedidos.append((texto, acao, threading.current_thread() is threading.main_thread()))
        return f"[{acao}] {texto}"

    def _aba(self, **callbacks):
        base = {"get_history": self.store.load_history, "on_reformat_text": self._reformatar,
                "get_settings": lambda: {"api_key": self.chave, "private_mode": True}}
        base.update(callbacks)
        tab = build_tab_history(self.root, callbacks=base, history_items=self.store.load_history())
        self.addCleanup(lambda: tab.winfo_exists() and tab.destroy())
        tab.atualizar_lista_historico()
        return tab

    @staticmethod
    def _botoes_do_hover(tab, indice=0):
        cartao = tab.scroll_historico.winfo_children()[indice]
        linha = next(w for w in cartao.winfo_children() if isinstance(w, ctk.CTkFrame))
        enter = linha._canvas.bind("<Enter>")
        tab.tk.call(enter.split("[", 1)[1].split()[0], *(["0"] * 19))
        meta = next(w for w in linha.winfo_children() if isinstance(w, ctk.CTkFrame))
        caixa = next(w for w in meta.winfo_children() if isinstance(w, ctk.CTkFrame))
        return [w for w in caixa.winfo_children() if isinstance(w, ctk.CTkButton)]

    def _abrir_reformatar(self, tab, indice=0):
        # Sem áudio: [Reusar, Abrir .md, Reformatar, ...]
        self._botoes_do_hover(tab, indice)[-2].invoke()
        self.assertIsNotNone(tab._item_menu_popup)
        return {b.cget("text"): b for b in tab._item_menu_popup.winfo_children() if isinstance(b, ctk.CTkButton)}

    def _do_disco(self, item_id):
        return next(it for it in self.store.load_history() if it["id"] == item_id)


class TestReformatarNoCartao(_AbaDeHistorico):
    def test_menu_tem_tons_traducoes_e_editar(self):
        self.store.save_history_item("um ditado qualquer")
        opcoes = self._abrir_reformatar(self._aba())
        for rotulo in ("Formal", "Conciso", "Tópicos (Bullet Points)", "Técnico", "Natural",
                       "Traduzir para Inglês (EN)", "Traduzir para Espanhol (ES)", "Editar e ensinar ao Willy..."):
            self.assertIn(rotulo, opcoes)
        self.assertNotIn("Restaurar original", opcoes, "sem raw_text não há o que restaurar")

    def test_tom_parte_da_fala_crua_fora_da_thread_e_grava_copia_e_destaca(self):
        item = self.store.save_history_item("Tópico um.\n- Tópico dois.", raw_text="a fala crua")[0]
        tab = self._aba()
        self._abrir_reformatar(tab)["Formal"].invoke()
        self.assertTrue(_bombear(self.root, lambda: "[formal]" in self._do_disco(item["id"])["text"]))
        salvo = self._do_disco(item["id"])
        self.assertEqual(("[formal] a fala crua", "a fala crua", "transcribe"),
                         (salvo["text"], salvo["raw_text"], salvo["mode"]))
        self.assertEqual([("a fala crua", "formal", False)], self.pedidos, "a Groq não pode rodar na thread da interface")
        self.assertEqual([("[formal] a fala crua", True)], self.copias, "no modo privado, fora do Win+V")
        self.assertIn("Reformatado e copiado", tab.lbl_toast.cget("text"))
        self.assertEqual("[formal] a fala crua", tab.history_items[0]["text"])

    def test_traducao_muda_o_modo_e_guarda_o_original(self):
        item = self.store.save_history_item("bom dia equipe")[0]
        tab = self._aba()
        self._abrir_reformatar(tab)["Traduzir para Espanhol (ES)"].invoke()
        self.assertTrue(_bombear(self.root, lambda: self._do_disco(item["id"])["mode"] == "translate_es"))
        salvo = self._do_disco(item["id"])
        self.assertEqual(("[translate_es] bom dia equipe", "bom dia equipe"), (salvo["text"], salvo["raw_text"]))
        self.assertIn("Traduzido para o espanhol", tab.lbl_toast.cget("text"))

    def test_restaurar_original_sem_ia(self):
        item = self.store.save_history_item("Good morning, team.", modo="translate_es", raw_text="bom dia equipe")[0]
        tab = self._aba()
        self._abrir_reformatar(tab)["Restaurar original"].invoke()
        salvo = self._do_disco(item["id"])
        self.assertEqual(("bom dia equipe", "transcribe"), (salvo["text"], salvo["mode"]))
        self.assertEqual([], self.pedidos, "restaurar não chama a IA")
        self.assertEqual([("bom dia equipe", True)], self.copias)
        self.assertNotIn("Restaurar original", self._abrir_reformatar(tab))

    def test_falha_da_ia_nao_mexe_no_item(self):
        item = self.store.save_history_item("fica como está")[0]

        def _falha(texto, acao):
            raise FalhaDoLLM("refino", texto)

        tab = self._aba(on_reformat_text=_falha)
        self._abrir_reformatar(tab)["Conciso"].invoke()
        self.assertTrue(_bombear(self.root, lambda: "não respondeu" in tab.lbl_toast.cget("text")))
        self.assertEqual("fica como está", self._do_disco(item["id"])["text"])
        self.assertEqual([], self.copias)
        self.assertEqual(set(), tab._ia_em_andamento)

    def test_sem_chave_nao_chama_a_ia(self):
        self.store.save_history_item("sem chave")
        self.chave = ""
        tab = self._aba()
        self._abrir_reformatar(tab)["Formal"].invoke()
        self.assertEqual([], self.pedidos)
        self.assertIn("chave da Groq", tab.lbl_toast.cget("text"))

    def test_segundo_pedido_no_mesmo_item_espera_o_primeiro(self):
        self.store.save_history_item("um item")
        liberar = threading.Event()

        def _lento(texto, acao):
            liberar.wait(3)
            return "pronto"

        tab = self._aba(on_reformat_text=_lento)
        self._abrir_reformatar(tab)["Formal"].invoke()
        self._abrir_reformatar(tab)["Técnico"].invoke()
        self.assertIn("ainda está com a IA", tab.lbl_toast.cget("text"))
        liberar.set()
        self.assertTrue(_bombear(self.root, lambda: not tab._ia_em_andamento))

    def test_aba_destruida_antes_da_resposta_nao_quebra(self):
        item = self.store.save_history_item("um item")[0]
        liberar, respondeu = threading.Event(), threading.Event()

        def _lento(texto, acao):
            liberar.wait(3)
            respondeu.set()
            return "tarde demais"

        tab = self._aba(on_reformat_text=_lento)
        self._abrir_reformatar(tab)["Formal"].invoke()
        tab.destroy()
        liberar.set()
        self.assertTrue(respondeu.wait(3))
        _bombear(self.root, lambda: False, 0.3)
        self.assertEqual("um item", self._do_disco(item["id"])["text"])

    def test_a_rolagem_fica_onde_estava(self):
        for i in range(30):
            self.store.save_history_item(f"ditado número {i} com algumas palavras para ocupar a linha")
        alvo = self.store.load_history()[-12]  # o 12º cartão de cima para baixo
        tab = self._aba()
        tab.pack(fill="both", expand=True)
        self.root.geometry("900x500")
        self.root.deiconify()
        _bombear(self.root, lambda: tab._cartoes_mostrados >= 20, 3)
        canvas = tab._canvas_da_lista()
        canvas.yview_moveto(0.4)
        self.root.update()
        topo = tab._topo_da_rolagem()
        self.assertGreater(topo, 0)
        self._abrir_reformatar(tab, indice=11)["Natural"].invoke()
        self.assertTrue(_bombear(self.root, lambda: "[natural]" in self._do_disco(alvo["id"])["text"]))
        self.root.update()
        self.assertLessEqual(abs(tab._topo_da_rolagem() - topo), 2)
        self.root.withdraw()


class TestSpotlightAlternaOOriginal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gc.collect()
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        _bombear(cls.root, lambda: False, 0.5)
        destruir_tk(cls.root)
        gc.collect()

    def setUp(self):
        gc.collect()
        self.colados = []
        self.colou = threading.Event()
        self.s = HistorySpotlight(master=self.root)
        self.addCleanup(self.s.destroy)
        self.s.focus_force = lambda: None  # o focus_force de verdade tiraria o foco de quem testa
        for nome, valor in (("get_foreground_hwnd", lambda: 0), ("eh_janela_do_willy", lambda h: False),
                            ("focus_window", lambda *a, **k: True)):
            p = patch.object(sp.ContextManager, nome, staticmethod(valor))
            p.start()
            self.addCleanup(p.stop)
        self.itens = [{"id": "1", "text": "Sem original.", "mode": "transcribe", "timestamp": "30/10/2026 10:00"},
                      {"id": "2", "text": "Texto refinado.", "raw_text": "texto cru", "mode": "transcribe",
                       "timestamp": "30/10/2026 10:01"}]
        self.s.mostrar(self.itens, on_paste_callback=lambda t: (self.colados.append(t), self.colou.set()))

    def test_tab_alterna_o_card_e_o_enter_cola_o_original(self):
        self.assertEqual("break", self.s._alternar_original())
        self.assertEqual("texto cru", self.s.pool_cards[0]["lbl_txt"].cget("text"))
        self.assertEqual("↺ Original", self.s.pool_cards[0]["lbl_tag"].cget("text"))
        self.s._confirmar_selecao()
        self.assertTrue(self.colou.wait(2))
        self.assertEqual(["texto cru"], self.colados)

    def test_tab_de_novo_volta_ao_refinado(self):
        self.s._alternar_original()
        self.s._alternar_original()
        self.assertEqual("Texto refinado.", self.s.pool_cards[0]["lbl_txt"].cget("text"))
        self.s._confirmar_selecao()
        self.assertTrue(self.colou.wait(2))
        self.assertEqual(["Texto refinado."], self.colados)

    def test_item_sem_original_nao_muda(self):
        self.s._navegar_baixo()
        self.assertEqual("break", self.s._alternar_original())
        self.assertEqual("Sem original.", self.s.pool_cards[1]["lbl_txt"].cget("text"))

    def test_o_tab_esta_ligado_na_busca_e_reabrir_volta_ao_refinado(self):
        self.assertIn("_alternar_original", self.s.entry_busca._entry.bind("<Tab>"))
        self.s._alternar_original()
        self.s.mostrar(self.itens, on_paste_callback=lambda t: None)
        self.assertEqual("Texto refinado.", self.s.pool_cards[0]["lbl_txt"].cget("text"))


class TestTraducaoDeTextoNaGroq(unittest.TestCase):
    def test_traduzir_para_ingles_usa_prompt_de_ingles_e_espanhol_usa_prompt_de_espanhol(self):
        svc = GroqService(api_key="gsk_teste")
        mensagens_enviadas = []

        def _completar(_client, msgs, **_kw):
            mensagens_enviadas.append(msgs)
            return "Translated text"

        with patch.object(svc, "get_client", return_value=object()), \
                patch.object(svc, "completar_com_reserva", side_effect=_completar):
            self.assertEqual("Translated text", svc.translate_to_english("bom dia", extra_context="Termos: Willy"))
            self.assertEqual("Translated text", svc.translate_to_spanish("bom dia", extra_context="Termos: Willy"))

        sistema_en = mensagens_enviadas[0][0]["content"]
        sistema_es = mensagens_enviadas[1][0]["content"]
        self.assertIn("Devolva esse texto em inglês.", sistema_en)
        self.assertNotIn("Devolva esse texto em espanhol.", sistema_en)
        self.assertIn("Termos: Willy", sistema_en)
        self.assertIn("Devolva esse texto em espanhol.", sistema_es)
        self.assertNotIn("Devolva esse texto em inglês.", sistema_es)
        self.assertIn("Termos: Willy", sistema_es)


if __name__ == "__main__":
    unittest.main()
