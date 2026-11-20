"""
Testes unitários para o módulo core.tts.TTSManager.
Valida seleção de voz por idioma, execução assíncrona via cscript/PowerShell,
interrupção limpa (stop), limpeza de arquivos temporários e callbacks.
"""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.tts import TTSManager


class TestTTSManager(unittest.TestCase):
    """Bateria de testes para o serviço Text-to-Speech nativo do Windows."""

    def setUp(self):
        self.tts = TTSManager()

    def tearDown(self):
        self.tts.stop()

    def test_escolher_voz_vazio_ou_sem_tokens(self):
        """Texto vazio ou sem letras deve selecionar a voz padrão PT-BR (Maria)."""
        self.assertEqual(TTSManager.escolher_voz(""), "TTS_MS_PT-BR_MARIA_11.0")
        self.assertEqual(TTSManager.escolher_voz("   12345 !!! "), "TTS_MS_PT-BR_MARIA_11.0")

    def test_escolher_voz_portugues(self):
        """Texto em português deve selecionar a voz PT-BR (Maria)."""
        texto_pt = "Olá mundo, este é um teste completo do sistema de voz do Willy."
        self.assertEqual(TTSManager.escolher_voz(texto_pt), "TTS_MS_PT-BR_MARIA_11.0")

    def test_escolher_voz_ingles(self):
        """Texto em inglês deve detectar as palavras comuns e selecionar a voz EN-US (Zira)."""
        texto_en = "Hello world, this is a test of the text to speech engine with Groq."
        self.assertEqual(TTSManager.escolher_voz(texto_en), "TTS_MS_EN-US_ZIRA_11.0")

    def test_speak_async_texto_vazio_retorna_false(self):
        """Tentativa de falar texto vazio ou espaços em branco deve retornar False imediatamente."""
        self.assertFalse(self.tts.speak_async(""))
        self.assertFalse(self.tts.speak_async("   \n\t  "))
        self.assertFalse(self.tts.is_speaking)

    @patch("core.tts.subprocess.Popen")
    @patch("core.tts.threading.Thread")
    def test_speak_async_sucesso_cscript(self, mock_thread, mock_popen):
        """Simula execução bem sucedida via cscript.exe //nologo com término limpo."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        # Executa target da thread síncronamente no teste
        mock_thread.side_effect = lambda target=None, daemon=None: MagicMock(start=lambda: target() if target else None)

        callback_chamado = []

        sucesso = self.tts.speak_async(
            "Texto de teste para síntese de voz",
            voice_pref="pt",
            rate=2,
            on_finish=lambda: callback_chamado.append(True)
        )
        self.assertTrue(sucesso)
        self.assertEqual(callback_chamado, [True])

        # Verifica chamada ao cscript
        args, _kwargs = mock_popen.call_args
        cmd = args[0]
        self.assertEqual(cmd[0], "cscript")
        self.assertEqual(cmd[1], "//nologo")
        self.assertEqual(cmd[4], "PT-BR")
        self.assertEqual(cmd[5], "2")

    @patch("core.tts.subprocess.Popen")
    @patch("core.tts.threading.Thread")
    def test_speak_async_rate_clamping(self, mock_thread, mock_popen):
        """Verifica que a taxa de velocidade é limitada entre -10 e 10."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        mock_thread.side_effect = lambda target=None, daemon=None: MagicMock(start=lambda: target() if target else None)

        self.tts.speak_async("Teste", rate=50)
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[5], "10")

        self.tts.speak_async("Teste", rate=-50)
        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[5], "-10")

    def test_stop_interrompe_leitura(self):
        """Testa se stop() mata o processo e cancela o estado is_speaking."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        self.tts._process = mock_proc
        self.tts._is_speaking = True

        self.tts.stop()

        self.assertTrue(self.tts._stop_requested)
        self.assertFalse(self.tts.is_speaking)
        mock_proc.terminate.assert_called()
        mock_proc.kill.assert_called()

    @patch("core.tts.subprocess.Popen")
    @patch("core.tts.threading.Thread")
    def test_geracao_cancela_worker_anterior(self, mock_thread, mock_popen):
        """Verifica que nova leitura invalida a geração anterior e impede sobreposição de voz."""
        self.tts._geracao = 1
        with self.tts._lock:
            self.tts._is_speaking = True
        self.tts.speak_async("Segunda leitura")
        self.assertEqual(self.tts._geracao, 2)
        mock_thread.assert_called_once()
        mock_popen.assert_not_called()

    def test_powershell_fallback_escapa_apostrofo_no_caminho_temp_e_isola_callback(self):
        """AUD-052: Fallback PowerShell deve dobrar apóstrofos (' -> '') em caminhos com aspas simples
        e vincular o callback on_done localmente à chamada."""
        comandos_ps = []
        workers = []

        def _fake_popen(cmd, **kwargs):
            proc = MagicMock()
            if cmd[0] == "cscript":
                proc.returncode = 1
                proc.poll.return_value = 1
            else:
                comandos_ps.append(cmd)
                proc.returncode = 0
                proc.poll.return_value = 0
            return proc

        with tempfile.TemporaryDirectory(prefix="willy_D'Angelo_") as tmp_com_apostrofo, \
             patch("core.tts.tempfile.gettempdir", return_value=tmp_com_apostrofo), \
             patch("core.tts.subprocess.Popen", side_effect=_fake_popen), \
             patch("core.tts.threading.Thread", side_effect=lambda target=None, daemon=None: MagicMock(start=lambda: workers.append(target))):
            cb1 = []
            self.tts.speak_async("Olá mundo", on_done=lambda: cb1.append("cb1"))
            # Antes de o worker 1 terminar, a instância tem _on_finish_callback alterado externamente:
            self.tts._on_finish_callback = lambda: cb1.append("sobrescrito")
            workers[0]()

        self.assertEqual(1, len(comandos_ps))
        ps_script = comandos_ps[0][-1]
        self.assertIn("D''Angelo", ps_script, "Apóstrofo no caminho temporário deve ser escapado como '' no PowerShell")
        self.assertEqual(["cb1"], cb1, "O callback deve estar vinculado localmente à closure da geração")


if __name__ == "__main__":
    unittest.main()
