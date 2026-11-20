"""
Áudio que falhou espera o reenvio numa fila, e só o reenvio entregue o apaga.

Era um único last_failed_audio.wav: a falha seguinte o sobrescrevia, e QUALQUER ditado
bem-sucedido o apagava. Uma reunião que caía offline se perdia no primeiro ditado curto
feito depois, antes do clique em "reenviar". E um corte por silêncio com outro ditado ainda
em processamento devolvia "Pipeline ocupado" e jogava o áudio fora.
"""

import ast
import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

import groq

from core.actions import ActionManager
from core.groq_service import FalhaDoLLM, GroqService
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.pipeline.transcription_pipeline import (
    FilaDeAudioFalho,
    _foco_numa_janela_do_willy,
)
from tests.willy_isolado import _erro_groq as _http
from tests.willy_isolado import _funcao_do_willy

# A Groq sem responder: a falha do LLM que passa sozinha, e que mantém o item na fila.
_IA_FORA = ConnectionError("Groq fora")


class TestFila(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fila = FilaDeAudioFalho(os.path.join(self.tmp, "failed"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cada_audio_vira_um_arquivo_com_timestamp_e_modo(self):
        caminho = self.fila.guardar(b"RIFFreuniao", "meeting")
        self.assertRegex(os.path.basename(caminho), r"^\d{8}T\d{6}\.\d{9}Z_meeting\.wav$")
        with open(caminho, "rb") as f:
            self.assertEqual(b"RIFFreuniao", f.read())

    def test_mais_recente_e_o_ultimo_guardado_mesmo_no_mesmo_instante(self):
        caminhos = [self.fila.guardar(bytes([i]), m) for i, m in enumerate(("meeting", "prompt", "send"))]
        self.assertEqual(3, len(set(caminhos)))
        self.assertEqual(caminhos, self.fila.itens())
        self.assertEqual((caminhos[-1], "send"), self.fila.mais_recente())

    def test_limite_tira_os_mais_antigos(self):
        caminhos = [self.fila.guardar(bytes([i]), "transcribe") for i in range(FilaDeAudioFalho.LIMITE + 2)]
        self.assertEqual(caminhos[2:], self.fila.itens())

    def test_modo_desconhecido_vira_ditado(self):
        self.fila.guardar(b"x", "../../evil")
        self.assertEqual("transcribe", self.fila.mais_recente()[1])

    def test_remover_so_apaga_dentro_da_fila(self):
        fora = os.path.join(self.tmp, "fora.wav")
        with open(fora, "wb") as f:
            f.write(b"x")
        self.fila.remover(fora)
        self.assertTrue(os.path.exists(fora))

    def test_fila_que_nunca_existiu_esta_vazia(self):
        self.assertIsNone(self.fila.mais_recente())
        self.assertEqual(0, len(self.fila))

    def test_dois_audios_no_mesmo_instante_nao_se_sobrescrevem(self):
        """O relógio do Windows anda em passos de ~1 ms: dois guardar() caem no mesmo ns."""
        with patch("core.pipeline.transcription_pipeline.time.time_ns", return_value=1_792_000_000_000_000_000):
            caminhos = [self.fila.guardar(bytes([i]), "transcribe") for i in range(3)]
        self.assertEqual(3, len(set(caminhos)))
        for i, caminho in enumerate(caminhos):
            with open(caminho, "rb") as f:
                self.assertEqual(bytes([i]), f.read())

    def test_duas_threads_que_calculam_o_mesmo_nome_nao_perdem_audio(self):
        """A janela da corrida: as duas leem a fila e checam o nome antes de qualquer uma
        gravar. Checar com exists() e abrir com "wb" perde um dos áudios nessa janela."""
        with patch("core.pipeline.transcription_pipeline.time.time_ns", return_value=1_792_000_000_000_000_000), \
             patch.object(FilaDeAudioFalho, "itens", return_value=[]), \
             patch("os.path.exists", return_value=False):
            primeiro = self.fila.guardar(b"RIFFprimeiro", "transcribe")
            segundo = self.fila.guardar(b"RIFFsegundo", "transcribe")
        self.assertNotEqual(primeiro, segundo)
        for caminho, esperado in ((primeiro, b"RIFFprimeiro"), (segundo, b"RIFFsegundo")):
            with open(caminho, "rb") as f:
                self.assertEqual(esperado, f.read())

    def test_relogio_que_volta_nao_poda_o_audio_que_acabou_de_ser_salvo(self):
        for i in range(FilaDeAudioFalho.LIMITE):
            self.fila.guardar(bytes([i]), "transcribe")
        uma_hora_antes = time.time_ns() - 3600 * 1_000_000_000
        with patch("core.pipeline.transcription_pipeline.time.time_ns", return_value=uma_hora_antes):
            novo = self.fila.guardar(b"RIFFnovo", "meeting")
        self.assertTrue(os.path.exists(novo))
        self.assertEqual((novo, "meeting"), self.fila.mais_recente())
        self.assertEqual(FilaDeAudioFalho.LIMITE, len(self.fila))


class TestAudioLegado(unittest.TestCase):
    """Quem atualiza com um last_failed_audio.wav à espera de reenvio não pode perdê-lo."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fila = FilaDeAudioFalho(os.path.join(self.tmp, "failed"))
        self.legado = os.path.join(self.tmp, "last_failed_audio.wav")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _gravar_legado(self, conteudo=b"RIFFpendente"):
        with open(self.legado, "wb") as f:
            f.write(conteudo)

    def test_o_pendente_entra_na_fila_e_sai_do_lugar_antigo(self):
        self._gravar_legado()
        caminho = self.fila.importar_legado(self.legado)
        self.assertEqual((caminho, "transcribe"), self.fila.mais_recente())
        with open(caminho, "rb") as f:
            self.assertEqual(b"RIFFpendente", f.read())
        self.assertFalse(os.path.exists(self.legado))

    def test_acima_do_limite_da_groq_entra_como_reuniao(self):
        """Sem o modo no arquivo, só a reunião (fatiada) passa com mais de 25 MB."""
        self._gravar_legado(b"RIFF" + b"x" * 100)
        with patch.object(FilaDeAudioFalho, "LIMITE_GROQ", 50):
            self.fila.importar_legado(self.legado)
        self.assertEqual("meeting", self.fila.mais_recente()[1])

    def test_so_uma_vez_a_copia_avulsa_gravada_depois_nao_entra(self):
        self._gravar_legado(b"RIFFpendente")
        self.fila.importar_legado(self.legado)
        self._gravar_legado(b"RIFFrecusa413")  # a cópia avulsa de uma recusa definitiva
        self.assertIsNone(self.fila.importar_legado(self.legado))
        self.assertEqual(1, len(self.fila))
        self.assertTrue(os.path.exists(self.legado))

    def test_sem_pendente_tambem_marca(self):
        self.assertIsNone(self.fila.importar_legado(self.legado))
        self._gravar_legado()
        self.assertIsNone(self.fila.importar_legado(self.legado))
        self.assertEqual(0, len(self.fila))

    def test_troca_que_falha_nao_marca_e_tenta_de_novo_na_proxima_abertura(self):
        self._gravar_legado()
        with patch("core.pipeline.transcription_pipeline.os.replace", side_effect=PermissionError("em uso")):
            self.assertIsNone(self.fila.importar_legado(self.legado))
        self.assertTrue(os.path.exists(self.legado))
        self.assertEqual(0, len(self.fila))
        self.assertIsNotNone(self.fila.importar_legado(self.legado))
        self.assertEqual(1, len(self.fila))

    def test_o_legado_e_movido_sem_ser_lido_para_a_memoria(self):
        """Uma reunião legada passa de 100 MB, e a importação roda na abertura, antes da interface."""
        self._gravar_legado()
        abrir = open

        def _sem_ler_o_legado(caminho, *a, **k):
            if os.path.abspath(str(caminho)) == os.path.abspath(self.legado):
                raise AssertionError("o legado foi aberto para leitura")
            return abrir(caminho, *a, **k)

        with patch("builtins.open", _sem_ler_o_legado):
            caminho = self.fila.importar_legado(self.legado)
        with open(caminho, "rb") as f:
            self.assertEqual(b"RIFFpendente", f.read())

    def test_o_willy_importa_na_abertura_depois_da_trava_de_instancia(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        main = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        linhas = {getattr(c.func, "attr", None): c.lineno for c in ast.walk(main) if isinstance(c, ast.Call)}
        self.assertIn("importar_audio_legado", linhas)
        self.assertLess(linhas["acquire"], linhas["importar_audio_legado"])


class _Pipeline(unittest.TestCase):
    def setUp(self):
        # Fora do Willy e do shell: com uma janela Tk deste processo na frente, ou a área de
        # trabalho, o ditado sem alvo seria copiado.
        for funcao in ("_foco_numa_janela_do_willy", "_foco_no_shell"):
            foco = patch(f"core.pipeline.transcription_pipeline.{funcao}", return_value=False)
            foco.start()
            self.addCleanup(foco.stop)
        self.tmp = tempfile.mkdtemp()
        self.avulso = os.path.join(self.tmp, "last_failed_audio.wav")
        self.groq_service = MagicMock()
        self.groq_service.refine_text.side_effect = lambda texto, **_k: texto
        config = MagicMock()
        config.groq_api_key = "gsk_teste"
        config.clipboard_only = False
        config.private_mode = False
        config.clean_fillers = False
        config.load_replacements.return_value = {}
        snippet = MagicMock()
        snippet.match_and_expand.return_value = None
        self.audio_mgr = MagicMock()
        self.audio_mgr.is_processing = False
        self.injector = MagicMock()
        self.injector.paste_text.return_value = True
        self.ui = []
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq_service, config_mgr=config, audio_mgr=self.audio_mgr,
            injector=self.injector, sound_mgr=MagicMock(), snippet_mgr=snippet, tts_mgr=MagicMock(),
            ui_notifier=lambda st, msg=None: self.ui.append((st, msg)),
            failed_audio_path=self.avulso, user_data_dir=self.tmp,
        )
        self.fila = self.pipeline.fila

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rodar(self, wav, modo="transcribe", falha=None, retry_path=None):
        self.groq_service.transcribe.side_effect = falha
        self.groq_service.transcribe.return_value = "texto ditado"
        return self.pipeline.process(PipelineContext(
            wav_bytes=wav, modo=modo, app_context=("code.exe", "editor", "general"),
            is_retry=retry_path is not None, retry_path=retry_path,
        ))

    def _conteudos(self):
        conteudo = []
        for caminho in self.fila.itens():
            with open(caminho, "rb") as f:
                conteudo.append(f.read())
        return conteudo


class TestFalhaEReenvio(_Pipeline):
    def test_ditado_curto_que_da_certo_nao_apaga_a_reuniao_que_caiu(self):
        """O cenário do bug: reunião grande cai offline, ditado curto funciona, reunião some."""
        self.assertEqual("offline_retry", self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline")).error_category)
        self.assertTrue(self._rodar(b"RIFFcurto").success)
        self.assertEqual([b"RIFFreuniao"], self._conteudos())
        # E a pílula volta a oferecer o reenvio, senão o áudio ficaria sem caminho de volta.
        self.assertEqual(("offline_retry", "Texto entregue. Áudios salvos: 1. Clique p/ reenviar"), self.ui[-1])

    def test_reenvio_entregue_apaga_so_o_item_reenviado(self):
        self._rodar(b"RIFFprimeiro", falha=ConnectionError("offline"))
        self._rodar(b"RIFFsegundo", falha=_http(groq.RateLimitError, 429))
        primeiro, segundo = self.fila.itens()
        self.assertTrue(self._rodar(b"RIFFsegundo", retry_path=segundo).success)
        self.assertEqual([primeiro], self.fila.itens())

    def test_reenvio_que_cai_de_novo_continua_na_fila_sem_duplicar(self):
        self._rodar(b"RIFFaudio", falha=ConnectionError("offline"))
        (item,) = self.fila.itens()
        self.assertFalse(self._rodar(b"RIFFaudio", falha=ConnectionError("offline"), retry_path=item).success)
        self.assertEqual([item], self.fila.itens())

    def test_reenvio_que_nao_e_colado_continua_na_fila(self):
        self._rodar(b"RIFFaudio", falha=ConnectionError("offline"))
        (item,) = self.fila.itens()
        self.injector.paste_text.return_value = False
        self._rodar(b"RIFFaudio", retry_path=item)
        self.assertEqual([item], self.fila.itens())

    def test_recusa_definitiva_nao_entra_na_fila_e_fica_a_copia_avulsa(self):
        res = self._rodar(b"RIFFgrande", falha=_http(groq.APIStatusError, 413))
        self.assertEqual("bad_request", res.error_category)
        self.assertEqual([], self.fila.itens())
        with open(self.avulso, "rb") as f:
            self.assertEqual(b"RIFFgrande", f.read())
        # Um ditado bem-sucedido depois não apaga mais a cópia avulsa.
        self.assertTrue(self._rodar(b"RIFFcurto").success)
        self.assertTrue(os.path.exists(self.avulso))

    def test_reenvio_sem_texto_sai_da_fila_e_libera_os_mais_antigos(self):
        """Áudio só de ruído: sem consumir, ele ficava no topo e o clique nunca chegava à reunião."""
        self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline"))
        self._rodar(b"RIFFruido", falha=ConnectionError("offline"))
        reuniao, ruido = self.fila.itens()
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = ""
        self.pipeline.process(PipelineContext(wav_bytes=b"RIFFruido", is_retry=True, retry_path=ruido,
                                              app_context=("code.exe", "editor", "general")))
        self.assertEqual((reuniao, "meeting"), self.fila.mais_recente())
        # E a pílula volta a oferecer o reenvio, agora da reunião.
        self.assertEqual("offline_retry", self.ui[-1][0])

    def test_reenvio_que_vira_leitura_em_voz_alta_sai_da_fila(self):
        self._rodar(b"RIFFleia", falha=ConnectionError("offline"))
        (item,) = self.fila.itens()
        with patch.object(self.pipeline, "_enriquecer_texto", return_value=("texto", "speak", False)):
            self.assertTrue(self._rodar(b"RIFFleia", retry_path=item).success)
        self.assertEqual([], self.fila.itens())

    def test_reenvio_nunca_aperta_enter(self):
        """O reenvio cola onde o foco está agora, talvez outra conversa: Enter ali não tem volta."""
        self._rodar(b"RIFFenviar", "send", ConnectionError("offline"))
        (item,) = self.fila.itens()
        self._rodar(b"RIFFenviar", "send", retry_path=item)
        self.assertFalse(self.injector.paste_text.call_args.kwargs["auto_send"])
        # Fora do reenvio, o modo "send" continua apertando Enter.
        self._rodar(b"RIFFenviar", "send")
        self.assertTrue(self.injector.paste_text.call_args.kwargs["auto_send"])

    def test_reenvio_recusado_de_vez_sai_da_fila_e_vira_copia_avulsa(self):
        self._rodar(b"RIFFaudio", falha=ConnectionError("offline"))
        (item,) = self.fila.itens()
        self._rodar(b"RIFFaudio", falha=_http(groq.APIStatusError, 413), retry_path=item)
        self.assertEqual([], self.fila.itens())
        with open(self.avulso, "rb") as f:
            self.assertEqual(b"RIFFaudio", f.read())


class TestReenvioComFocoNoWilly(_Pipeline):
    """O menu da bandeja põe a janela do pystray na frente, e depois de salvar a chave o foco fica
    no campo dela: o Ctrl+V do reenvio caía ali, e o item saía da fila com o texto perdido."""

    def setUp(self):
        super().setUp()
        self._rodar(b"RIFFaudio", falha=ConnectionError("offline"))
        (self.item,) = self.fila.itens()
        self.copiar = patch.object(ActionManager, "secure_copy", return_value=True)
        self.secure_copy = self.copiar.start()

    def tearDown(self):
        self.copiar.stop()
        super().tearDown()

    def _foco(self, no_willy):
        return patch("core.pipeline.transcription_pipeline._foco_numa_janela_do_willy", return_value=no_willy)

    def test_reenvio_com_foco_no_willy_copia_em_vez_de_colar(self):
        with self._foco(True):
            res = self._rodar(b"RIFFaudio", retry_path=self.item)
        self.assertEqual("copy", res.action_type)
        self.secure_copy.assert_called_once_with("Texto ditado")  # comandos de voz capitalizam
        self.injector.paste_text.assert_not_called()
        self.assertEqual([], self.fila.itens())
        self.assertIn(("success", "Copiado: cole onde quiser 📋"), self.ui)

    def test_copia_que_falha_mantem_o_item(self):
        self.secure_copy.return_value = False
        with self._foco(True):
            self._rodar(b"RIFFaudio", retry_path=self.item)
        self.assertEqual([self.item], self.fila.itens())

    def test_reenvio_com_foco_em_outro_app_cola(self):
        with self._foco(False):
            self._rodar(b"RIFFaudio", retry_path=self.item)
        self.injector.paste_text.assert_called_once()
        self.secure_copy.assert_not_called()

    def test_ditado_comum_com_foco_no_willy_e_sem_alvo_copia(self):
        """Era colado ali ("ditar num campo do próprio dashboard é uso legítimo"). O dono decidiu
        em 27/10 (Bloco 11): o Ctrl+V nunca sai com o foco no Willy. O ditado que começa com o
        Willy na frente vai para o app sob o cursor ou o último em que a pessoa estava; sem
        nenhum dos dois, copia."""
        with self._foco(True):
            res = self._rodar(b"RIFFnovo")
        self.injector.paste_text.assert_not_called()
        self.assertEqual("copy", res.action_type)
        self.assertIn(("success", "Copiado: cole onde quiser 📋"), self.ui)

    def _fixada(self, focou):
        return (patch("core.pipeline.transcription_pipeline.ContextManager.get_sticky_window",
                      return_value=(42, "chat")),
                patch("core.pipeline.transcription_pipeline.ContextManager.focus_window",
                      return_value=focou))

    def test_com_janela_fixada_o_reenvio_cola_nela(self):
        """A fixada recebe o foco pelo hwnd (passava a tupla inteira e o foco nunca mudava)."""
        fixada, focar = self._fixada(True)
        with fixada, focar as focus_window, self._foco(False):
            self._rodar(b"RIFFaudio", retry_path=self.item)
        self.assertEqual(42, focus_window.call_args.args[0])
        self.injector.paste_text.assert_called_once()
        self.secure_copy.assert_not_called()

    def test_fixada_que_nao_recebe_o_foco_nao_desliga_a_protecao(self):
        fixada, focar = self._fixada(False)
        with fixada, focar, self._foco(True):
            self._rodar(b"RIFFaudio", retry_path=self.item)
        self.injector.paste_text.assert_not_called()
        self.secure_copy.assert_called_once()

    def test_copia_com_mais_audio_na_fila_nao_diz_entregue(self):
        self._rodar(b"RIFFoutro", falha=ConnectionError("offline"))
        with self._foco(True):
            self._rodar(b"RIFFaudio", retry_path=self.item)
        self.assertEqual(("offline_retry", "Copiado: cole onde quiser. Áudios salvos: 1. Clique p/ reenviar"),
                         self.ui[-1])


class TestFocoNumaJanelaDoWilly(unittest.TestCase):
    def _user32(self, pid_da_janela, hwnd=123):
        user32 = MagicMock()
        user32.GetForegroundWindow.return_value = hwnd

        def _pid(_hwnd, ref):
            ref._obj.value = pid_da_janela
            return 1

        user32.GetWindowThreadProcessId.side_effect = _pid
        import core.context as context_mod
        return patch.object(context_mod, "user32", user32)

    @unittest.skipUnless(sys.platform == "win32", "Win32")
    def test_janela_do_proprio_processo(self):
        with self._user32(os.getpid()):
            self.assertTrue(_foco_numa_janela_do_willy())

    @unittest.skipUnless(sys.platform == "win32", "Win32")
    def test_janela_de_outro_processo_ou_nenhuma(self):
        with self._user32(os.getpid() + 1):
            self.assertFalse(_foco_numa_janela_do_willy())
        with self._user32(os.getpid(), hwnd=0):
            self.assertFalse(_foco_numa_janela_do_willy())


    @unittest.skipUnless(sys.platform == "win32", "Win32")
    def test_nao_carrega_windll_por_chamada_e_falha_win32_retorna_true_com_log(self):
        """AUD-028 e AUD-155: _foco_numa_janela_do_willy reutiliza core.context.user32 e retorna True (fail-safe) em exceção."""
        from contextlib import redirect_stderr

        import core.context as context_mod

        with self._user32(os.getpid()), patch("ctypes.WinDLL", side_effect=AssertionError("Não deve carregar WinDLL por chamada")):
            self.assertTrue(_foco_numa_janela_do_willy())

        user32_quebrado = MagicMock()
        user32_quebrado.GetForegroundWindow.side_effect = OSError("Falha Win32 GetForegroundWindow")
        err = io.StringIO()
        with patch.object(context_mod, "user32", user32_quebrado), redirect_stderr(err):
            self.assertTrue(_foco_numa_janela_do_willy())
        self.assertIn("Falha Win32 GetForegroundWindow", err.getvalue())


class TestPipelineOcupado(_Pipeline):
    def test_audio_que_chega_com_o_pipeline_ocupado_vai_para_a_fila(self):
        self.audio_mgr.is_processing = True
        res = self._rodar(b"RIFFcortado", "send")
        self.assertFalse(res.success)
        self.assertEqual("busy", res.error_category)
        self.groq_service.transcribe.assert_not_called()
        self.assertEqual([b"RIFFcortado"], self._conteudos())
        self.assertEqual("send", self.fila.mais_recente()[1])
        self.assertEqual("offline_retry", self.ui[-1][0])
        # O ditado em andamento continua dono do pipeline.
        self.assertTrue(self.audio_mgr.is_processing)

    def test_reenvio_com_o_pipeline_ocupado_nao_duplica(self):
        self._rodar(b"RIFFaudio", falha=ConnectionError("offline"))
        (item,) = self.fila.itens()
        self.audio_mgr.is_processing = True
        self._rodar(b"RIFFaudio", retry_path=item)
        self.assertEqual([item], self.fila.itens())


class TestSemChave(_Pipeline):
    """Sem chave da Groq, o ditado era jogado fora antes de chegar a qualquer fila."""

    def _sem_chave(self, valor=""):
        self.pipeline.config_mgr.groq_api_key = valor

    def test_sem_chave_o_audio_vai_para_a_fila_com_o_modo(self):
        for valor in ("", "sua_chave_aqui"):
            with self.subTest(chave=valor):
                for item in self.fila.itens():
                    self.fila.remover(item)
                self._sem_chave(valor)
                res = self._rodar(b"RIFFreuniao", "meeting")
                self.assertEqual("invalid_key", res.error_category)
                self.groq_service.transcribe.assert_not_called()
                self.assertEqual([b"RIFFreuniao"], self._conteudos())
                self.assertEqual("meeting", self.fila.mais_recente()[1])
                self.assertEqual(("error", "Configure sua chave Groq: o áudio ficou salvo"), self.ui[-1])

    def test_reenvio_sem_chave_nao_duplica(self):
        self._sem_chave()
        self._rodar(b"RIFFaudio")
        (item,) = self.fila.itens()
        self._rodar(b"RIFFaudio", retry_path=item)
        self.assertEqual([item], self.fila.itens())

    def test_com_a_chave_configurada_o_reenvio_transcreve_e_consome(self):
        self._sem_chave()
        self._rodar(b"RIFFaudio")
        (item,) = self.fila.itens()
        self.pipeline.config_mgr.groq_api_key = "gsk_nova"
        self.assertTrue(self._rodar(b"RIFFaudio", retry_path=item).success)
        self.assertEqual([], self.fila.itens())

    def test_chave_recusada_pela_groq_tambem_guarda_o_audio(self):
        """401: com a chave trocada, o mesmo áudio passa. Ia para a cópia avulsa e não voltava."""
        res = self._rodar(b"RIFFaudio", falha=_http(groq.AuthenticationError, 401))
        self.assertEqual("invalid_key", res.error_category)
        self.assertEqual([b"RIFFaudio"], self._conteudos())
        self.assertEqual("error", self.ui[-1][0])
        self.assertIn("o áudio ficou salvo", self.ui[-1][1])

    def test_403_fica_fora_da_fila(self):
        """Permissão (modelo bloqueado) nem sempre passa com outra chave: na fila, viraria um item
        eterno no topo, reoferecido a cada ditado e reenviado a cada clique."""
        res = self._rodar(b"RIFFaudio", falha=_http(groq.PermissionDeniedError, 403))
        self.assertEqual("invalid_key", res.error_category)
        self.assertEqual([], self.fila.itens())
        with open(self.avulso, "rb") as f:
            self.assertEqual(b"RIFFaudio", f.read())
        self.assertEqual(("error", "Chave Groq inválida ou sem permissão"), self.ui[-1])

    def test_reenvio_com_a_chave_ainda_invalida_continua_na_fila(self):
        self._rodar(b"RIFFaudio", falha=_http(groq.AuthenticationError, 401))
        (item,) = self.fila.itens()
        self._rodar(b"RIFFaudio", falha=_http(groq.AuthenticationError, 401), retry_path=item)
        self.assertEqual([item], self.fila.itens())


RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBandejaReenvio(unittest.TestCase):
    """A pílula só aceita o clique de reenvio por 5,5 s; a bandeja deixa a fila sempre ao alcance."""

    def _menu(self, pendentes):
        from ui.overlays.tray import TrayManager
        self.reenviar = MagicMock()
        tray = TrayManager({"on_retry_audio": self.reenviar}, tempfile.gettempdir())
        menu = tray.build_menu(True, True, False, "centro_inferior", "ctrl+space", "ctrl+alt+space",
                               "ctrl+shift+space", "ctrl+alt+r", "llama-3.3-70b-versatile", [],
                               pendentes=pendentes)
        return [i for i in menu.items if "Reenviar áudio salvo" in str(i.text)]

    def test_com_audio_na_fila_o_item_mostra_quantos_e_reenvia(self):
        (item,) = self._menu(3)
        self.assertEqual("🔁 Reenviar áudio salvo (3)", item.text)
        item(MagicMock())  # é assim que o pystray dispara a ação
        self.reenviar.assert_called_once_with()

    def test_sem_audio_na_fila_o_item_nao_aparece(self):
        self.assertEqual([], self._menu(0))

    def test_update_da_bandeja_leva_o_contador_ate_o_menu(self):
        """O willy chama update(), não build_menu(): o contador tem que atravessar os dois."""
        from ui.overlays.tray import TrayManager
        tray = TrayManager({}, tempfile.gettempdir())
        tray.icon = MagicMock()
        tray.update(True, True, False, "centro_inferior", "ctrl+space", "ctrl+alt+space",
                    "ctrl+shift+space", "ctrl+alt+r", "llama-3.3-70b-versatile", [], pendentes=2)
        textos = [str(i.text) for i in tray.icon.menu.items]
        self.assertIn("🔁 Reenviar áudio salvo (2)", textos)

    def test_willy_passa_o_tamanho_da_fila_para_a_bandeja(self):
        tray, pipeline = MagicMock(), MagicMock()
        pipeline.fila.__len__.return_value = 4
        sincronizar = _funcao_do_willy("sincronizar_bandeja", tray_mgr=tray, audio_mgr=MagicMock(),
                                       config_mgr=MagicMock(), transcription_pipeline=pipeline)
        sincronizar()
        self.assertEqual(4, tray.update.call_args.kwargs["pendentes"])

    def test_willy_ressincroniza_a_bandeja_depois_do_pipeline(self):
        """Uma falha põe áudio na fila sem passar pelo on_success_sync: o contador ficaria velho."""
        ordem = []
        pipeline = MagicMock()
        pipeline.process.side_effect = lambda _ctx: ordem.append("process")
        config = MagicMock()
        config.groq_api_key = "gsk_x"
        executar = _funcao_do_willy(
            "_executar_pipeline_transcricao", config_mgr=config, transcription_pipeline=pipeline,
            dashboard=None, safe_dispatch_ui=MagicMock(), PipelineContext=PipelineContext,
            current_app_context=None, selected_text_for_transform="", Optional=Optional,
            Tuple=tuple, _alvo_da_gravacao=(0, 0),
            sincronizar_bandeja=lambda: ordem.append("bandeja"),
        )
        executar(b"RIFFaudio", "transcribe")
        self.assertEqual(["process", "bandeja"], ordem)

    def test_o_clique_da_bandeja_chama_o_mesmo_reenvio_da_pilula(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        valores = [v for no in ast.walk(arvore) if isinstance(no, ast.Dict)
                   for k, v in zip(no.keys, no.values)
                   if isinstance(k, ast.Constant) and k.value == "on_retry_audio"]
        self.assertEqual(["reenviar_ultimo_audio"], [getattr(v, "id", None) for v in valores])


class TestWillySemChave(unittest.TestCase):
    def test_sem_chave_o_willy_abre_os_ajustes_e_entrega_o_audio_ao_pipeline(self):
        config, pipeline, despachar = MagicMock(), MagicMock(), MagicMock()
        config.groq_api_key = ""
        executar = _funcao_do_willy(
            "_executar_pipeline_transcricao", config_mgr=config, transcription_pipeline=pipeline,
            dashboard=MagicMock(), safe_dispatch_ui=despachar, PipelineContext=PipelineContext,
            current_app_context=None, selected_text_for_transform="", Optional=Optional,
            Tuple=tuple, _alvo_da_gravacao=(0, 0),
            sincronizar_bandeja=MagicMock(),
        )
        executar(b"RIFFaudio", "meeting")
        despachar.assert_called_once()
        self.assertEqual(b"RIFFaudio", pipeline.process.call_args.args[0].wav_bytes)

    def _salvar(self, chave_antes, chave_depois, pendentes):
        config, pipeline, ui = MagicMock(), MagicMock(), MagicMock()
        config.groq_api_key = chave_antes
        config.save_settings.side_effect = lambda _dados: setattr(config, "groq_api_key", chave_depois)
        pipeline.fila.__len__.return_value = pendentes
        salvar = _funcao_do_willy(
            "dashboard_save_settings", config_mgr=config, groq_service=MagicMock(), audio_mgr=MagicMock(),
            hotkey_orchestrator=None, sincronizar_bandeja=MagicMock(), pill=None,
            safe_dispatch_ui=MagicMock(), transcription_pipeline=pipeline, atualizar_ui=ui,
        )
        salvar({"GROQ_API_KEY": chave_depois})
        return ui

    def test_chave_nova_com_audio_guardado_oferece_o_reenvio(self):
        ui = self._salvar("", "gsk_nova", 2)
        ui.assert_called_once_with("offline_retry", "Chave salva. Áudios salvos: 2. Clique p/ reenviar")

    def test_sem_troca_de_chave_ou_sem_audio_nao_oferece(self):
        for antes, depois, pendentes in (("gsk_a", "gsk_a", 3), ("", "gsk_nova", 0), ("gsk_a", "", 3),
                                         ("", "sua_chave_aqui", 3)):
            with self.subTest(antes=antes, depois=depois, pendentes=pendentes):
                self._salvar(antes, depois, pendentes).assert_not_called()


class TestPromptDeAgenteSemRede(_Pipeline):
    def test_rede_que_cai_no_prompt_de_agente_guarda_o_audio(self):
        """A fala foi transcrita, mas a rede caiu ao gerar o prompt: o áudio vai para a fila."""
        self.groq_service.generate_agent_prompt.side_effect = ConnectionError("offline")
        res = self._rodar(b"RIFFprompt", "prompt")
        self.assertEqual("offline_retry", res.error_category)
        self.assertEqual("prompt", self.fila.mais_recente()[1])
        self.assertEqual([b"RIFFprompt"], self._conteudos())
        self.assertEqual("offline_retry", self.ui[-1][0])


class TestEtapaDeIAQueFalha(_Pipeline):
    """Cada etapa de IA que falha diz o que aconteceu e entrega o melhor texto, sem perder o áudio."""

    def _colado(self):
        return self.injector.paste_text.call_args.args[0]

    def test_refino_que_falha_entrega_o_cru_e_avisa(self):
        recebido = []

        def _falha(texto, **_k):
            recebido.append(texto)
            raise FalhaDoLLM("refino", texto)  # como o serviço: a reserva é o que ele recebeu

        self.groq_service.refine_text.side_effect = _falha
        self.assertTrue(self._rodar(b"RIFFditado").success)
        self.assertEqual(recebido, [self._colado()])
        self.assertEqual(("error", "Sem polimento: a Groq não respondeu"), self.ui[-1])
        self.assertEqual([], self.fila.itens())

    def test_ata_que_falha_entrega_a_transcricao_marcada_e_guarda_o_audio(self):
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto ditado")
        self.assertTrue(self._rodar(b"RIFFreuniao", "meeting").success)
        self.assertTrue(self._colado().startswith("> ⚠️ Ata não gerada"))
        self.assertIn("texto ditado", self._colado())
        self.assertEqual([b"RIFFreuniao"], self._conteudos())
        self.assertEqual("meeting", self.fila.mais_recente()[1])
        self.assertEqual(("offline_retry", "Ata não gerada. Clique p/ reenviar"), self.ui[-1])

    def test_reenvio_cuja_ata_falha_de_novo_continua_na_fila(self):
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto ditado", _IA_FORA)
        self._rodar(b"RIFFreuniao", "meeting")
        (item,) = self.fila.itens()
        self._rodar(b"RIFFreuniao", "meeting", retry_path=item)
        self.assertEqual([item], self.fila.itens())

    def test_reenvio_cuja_ata_sai_consome_o_item(self):
        self.groq_service.summarize_meeting.side_effect = FalhaDoLLM("ata", "texto ditado")
        self._rodar(b"RIFFreuniao", "meeting")
        (item,) = self.fila.itens()
        self.groq_service.summarize_meeting.side_effect = None
        self.groq_service.summarize_meeting.return_value = "## Ata Executiva\n- decisões"
        self._rodar(b"RIFFreuniao", "meeting", retry_path=item)
        self.assertEqual([], self.fila.itens())

    def test_transformar_que_falha_nao_cola_a_selecao_sobre_ela_mesma(self):
        self.groq_service.transform_text.side_effect = FalhaDoLLM("transformar", "seleção")
        self.groq_service.transcribe.return_value = "traduza para inglês"
        res = self.pipeline.process(PipelineContext(wav_bytes=b"RIFFinstrucao", modo="transform",
                                                    selected_text="seleção",
                                                    app_context=("code.exe", "editor", "general")))
        self.assertFalse(res.success)
        self.injector.paste_text.assert_not_called()
        self.assertEqual(("error", "Não transformei: Groq não respondeu"), self.ui[-1])

    def test_comando_de_transformar_que_falha_nao_cola_nada(self):
        self.groq_service.transform_text.side_effect = FalhaDoLLM("transformar", "seleção")
        with patch.object(ActionManager, "is_action_command", return_value=(True, "traduza isso")), \
             patch.object(ActionManager, "is_transform_command", return_value=(True, "traduza isso")), \
             patch.object(ActionManager, "get_selected_text", return_value="seleção"):
            res = self._rodar(b"RIFFcomando")
        self.assertFalse(res.success)
        self.injector.paste_text.assert_not_called()
        self.groq_service.refine_text.assert_not_called()
        self.assertEqual(("error", "Não transformei: Groq não respondeu"), self.ui[-1])

    def test_o_pipeline_pede_as_quatro_etapas_no_modo_estrito(self):
        """Sem estrito=True, cada etapa voltaria a devolver o texto cru em silêncio."""
        self.groq_service.summarize_meeting.return_value = "## Ata Executiva\n- decisões"
        self.groq_service.generate_agent_prompt.return_value = "/goal criar a tela de login"
        self.groq_service.transform_text.return_value = "selection"
        self._rodar(b"RIFFditado")
        self._rodar(b"RIFFreuniao", "meeting")
        self._rodar(b"RIFFprompt", "prompt")
        self.pipeline.process(PipelineContext(wav_bytes=b"RIFFinstrucao", modo="transform", selected_text="seleção",
                                              app_context=("code.exe", "editor", "general")))
        for etapa in (self.groq_service.refine_text, self.groq_service.summarize_meeting,
                      self.groq_service.generate_agent_prompt, self.groq_service.transform_text):
            self.assertIs(True, etapa.call_args.kwargs.get("estrito"), etapa._mock_name)

    def test_prompt_que_falha_entrega_a_fala_e_avisa(self):
        self.groq_service.generate_agent_prompt.side_effect = FalhaDoLLM("prompt", "criar a tela de login")
        self.assertTrue(self._rodar(b"RIFFprompt", "prompt").success)
        self.assertEqual("criar a tela de login", self._colado())
        self.assertEqual(("error", "Prompt sem estrutura: Groq falhou"), self.ui[-1])


class TestReuniaoFatiada(_Pipeline):
    """Uma falha no bloco 7 de 10 descartava os 6 já transcritos, e o reenvio pagava todos de novo."""

    @classmethod
    def setUpClass(cls):
        import numpy as np

        from core.audio_processing.dsp import convert_to_wav
        # Acima de 20 MB, a reunião é fatiada (11 min a 16 kHz).
        cls.wav = convert_to_wav(np.zeros(16000 * 660, dtype=np.float32), sample_rate=16000).getvalue()

    def setUp(self):
        super().setUp()
        self.audio_mgr.split_audio_into_chunks.side_effect = lambda *a, **k: [io.BytesIO(b"c0"), io.BytesIO(b"c1"),
                                                                              io.BytesIO(b"c2")]
        self.servico = GroqService(api_key="gsk_teste")
        self.servico.transcribe = MagicMock()
        self.groq_service.transcribe_chunks.side_effect = self.servico.transcribe_chunks
        self.groq_service.summarize_meeting.side_effect = lambda texto, **_k: "## Ata Executiva\n" + texto

    def _reuniao(self, retry_path=None):
        return self.pipeline.process(PipelineContext(
            wav_bytes=self.wav, modo="meeting", app_context=("code.exe", "editor", "general"),
            is_retry=retry_path is not None, retry_path=retry_path,
        ))

    def test_bloco_que_falha_guarda_os_anteriores_ao_lado_do_item(self):
        self.servico.transcribe.side_effect = ["parte 0", "parte 1", ConnectionError("offline")]
        self.assertEqual("offline_retry", self._reuniao().error_category)
        (item,) = self.fila.itens()
        self.assertEqual({0: "parte 0", 1: "parte 1"}, self.fila.ler_blocos(item))

    def test_reenvio_so_transcreve_os_que_faltam(self):
        self.servico.transcribe.side_effect = ["parte 0", "parte 1", ConnectionError("offline")]
        self._reuniao()
        (item,) = self.fila.itens()
        self.servico.transcribe.reset_mock()
        self.servico.transcribe.side_effect = ["parte 2"]
        self.assertTrue(self._reuniao(retry_path=item).success)
        self.assertEqual(1, self.servico.transcribe.call_count)
        self.assertEqual("parte 0\n\nparte 1\n\nparte 2", self.groq_service.summarize_meeting.call_args.args[0])
        self.assertEqual([], self.fila.itens())
        self.assertFalse(os.path.exists(item + ".blocos.json"))

    def test_reenvio_que_cai_de_novo_soma_os_blocos(self):
        self.servico.transcribe.side_effect = ["parte 0", ConnectionError("offline")]
        self._reuniao()
        (item,) = self.fila.itens()
        self.servico.transcribe.side_effect = ["parte 1", ConnectionError("offline")]
        self._reuniao(retry_path=item)
        self.assertEqual({0: "parte 0", 1: "parte 1"}, self.fila.ler_blocos(item))

    def test_ata_que_falha_guarda_todos_e_o_reenvio_nao_transcreve_nada(self):
        self.servico.transcribe.side_effect = ["parte 0", "parte 1", "parte 2"]
        self.groq_service.summarize_meeting.side_effect = lambda texto, **_k: (_ for _ in ()).throw(
            FalhaDoLLM("ata", texto, _IA_FORA))
        self.assertTrue(self._reuniao().success)
        (item,) = self.fila.itens()
        self.assertEqual({0: "parte 0", 1: "parte 1", 2: "parte 2"}, self.fila.ler_blocos(item))
        self.servico.transcribe.reset_mock()
        self.groq_service.summarize_meeting.side_effect = lambda texto, **_k: "## Ata Executiva\n" + texto
        self.assertTrue(self._reuniao(retry_path=item).success)
        self.servico.transcribe.assert_not_called()
        self.assertEqual([], self.fila.itens())

    def test_blocos_ilegiveis_viram_nenhum(self):
        caminho = self.fila.guardar(b"RIFF", "meeting")
        with open(caminho + ".blocos.json", "w", encoding="utf-8") as f:
            f.write("{nao e json")
        self.assertEqual({}, self.fila.ler_blocos(caminho))


class TestCorrecoesDoJuizDoBloco3(_Pipeline):
    def _ata_falha(self):
        self.groq_service.summarize_meeting.side_effect = lambda texto, **_k: (_ for _ in ()).throw(
            FalhaDoLLM("ata", texto, _IA_FORA))

    def test_reenvio_cuja_ata_falha_de_novo_nao_entrega_outra_vez(self):
        """Cada clique com a IA fora colava a transcrição de novo, com mais .md, .wav e histórico."""
        self._ata_falha()
        self._rodar(b"RIFFreuniao", "meeting")
        (item,) = self.fila.itens()
        self.injector.paste_text.reset_mock()
        self.pipeline.config_mgr.save_output_file.reset_mock()
        self.pipeline.config_mgr.save_history_item.reset_mock()
        res = self._rodar(b"RIFFreuniao", "meeting", retry_path=item)
        self.assertFalse(res.success)
        self.injector.paste_text.assert_not_called()
        self.pipeline.config_mgr.save_output_file.assert_not_called()
        self.pipeline.config_mgr.save_history_item.assert_not_called()
        self.assertEqual([item], self.fila.itens())
        self.assertEqual(("offline_retry", "Ata ainda não gerada. Clique p/ reenviar"), self.ui[-1])

    def test_transcricao_que_nunca_saiu_e_entregue_no_reenvio(self):
        """A primeira passagem caiu por rede: no reenvio, mesmo sem a ata, a transcrição vai."""
        self._rodar(b"RIFFreuniao", "meeting", ConnectionError("offline"))
        (item,) = self.fila.itens()
        self._ata_falha()
        self.assertTrue(self._rodar(b"RIFFreuniao", "meeting", retry_path=item).success)
        self.injector.paste_text.assert_called_once()
        self.assertTrue(self.fila.ja_entregue(item))

    def test_reenvio_de_transformar_que_falha_mantem_o_item_e_o_aviso(self):
        self._rodar(b"RIFFinstrucao", falha=ConnectionError("offline"))
        (item,) = self.fila.itens()
        # Como o transform_text estrito faz: rede, 429 e 5xx sobem crus, sem virar FalhaDoLLM.
        self.groq_service.transform_text.side_effect = _IA_FORA
        self.groq_service.transcribe.side_effect = None
        self.groq_service.transcribe.return_value = "traduza para inglês"
        self.pipeline.process(PipelineContext(wav_bytes=b"RIFFinstrucao", modo="transform", selected_text="seleção",
                                              is_retry=True, retry_path=item,
                                              app_context=("code.exe", "editor", "general")))
        self.assertEqual([item], self.fila.itens())
        self.assertEqual(("offline_retry", "Sem internet: áudio salvo. Clique p/ reenviar"), self.ui[-1])

    def test_aviso_do_refino_com_audio_na_fila_continua_clicavel(self):
        self._rodar(b"RIFFoutro", falha=ConnectionError("offline"))
        self.groq_service.refine_text.side_effect = lambda texto, **_k: (_ for _ in ()).throw(
            FalhaDoLLM("refino", texto))
        self.assertTrue(self._rodar(b"RIFFditado").success)
        self.assertEqual(("offline_retry", "Sem polimento. Áudios salvos: 1. Clique p/ reenviar"), self.ui[-1])

    def test_blocos_de_um_item_que_ja_saiu_nao_ficam_orfaos(self):
        caminho = self.fila.guardar(b"RIFF", "meeting")
        self.fila.remover(caminho)
        self.fila.gravar_blocos(caminho, {0: "texto da reunião"})
        self.assertFalse(os.path.exists(caminho + ".blocos.json"))

    def test_remover_apaga_tambem_a_marca_de_entregue(self):
        caminho = self.fila.guardar(b"RIFF", "meeting")
        self.fila.marcar_entregue(caminho)
        self.fila.remover(caminho)
        self.assertFalse(os.path.exists(caminho + ".entregue"))

    def test_acao_que_falha_nao_cola_a_frase_do_comando(self):
        with patch.object(ActionManager, "is_action_command", return_value=(True, "resuma isso")), \
             patch.object(ActionManager, "is_transform_command", return_value=(False, "")), \
             patch.object(ActionManager, "is_speak_command", return_value=False), \
             patch.object(ActionManager, "get_selected_text", return_value="seleção"), \
             patch.object(ActionManager, "process_action", return_value=None):
            res = self._rodar(b"RIFFcomando")
        self.assertFalse(res.success)
        self.injector.paste_text.assert_not_called()
        self.groq_service.refine_text.assert_not_called()
        self.assertEqual(("error", "Não executei: Groq não respondeu"), self.ui[-1])


if __name__ == "__main__":
    unittest.main()
