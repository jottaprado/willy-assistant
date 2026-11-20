"""
Regressões apontadas por uma code review do PR #1.

Quatro defeitos que a suíte não pegava, cada um invisível por um motivo diferente:
o TTS falava o texto errado só quando dois cliques se cruzavam; o clipboard só ficava
sujo quando não continha texto; o chunking só mentia com um argumento grande o bastante;
e a escada de taxas só perdia o fallback quando o device abria mas não iniciava.

Todos são caminhos de exceção e de corrida — exatamente onde teste manual não chega.
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from core.actions import ActionManager
from core.audio import AudioManager, negociar_stream
from core.tts import TTSManager


class TestLeituraSubstituida(unittest.TestCase):
    """Duas leituras em sequência não podem se sobrepor.

    `stop()` mata o processo do cscript, que devolve returncode != 0. O worker antigo
    lê isso como "cscript falhou" e parte para o fallback de PowerShell. O único guarda
    era `_stop_requested` — que `speak_async` zera ao iniciar a leitura seguinte, bem
    antes de o worker antigo acordar. Resultado: o texto velho era recitado por cima do
    novo, o `_process` da leitura nova era sobrescrito (tornando-a impossível de parar)
    e o callback de fim disparava no meio da reprodução.
    """

    def setUp(self):
        self.tts = TTSManager()

    def test_a_leitura_corrente_nao_e_obsoleta(self):
        self.tts._geracao = 7
        self.assertFalse(self.tts._leitura_obsoleta(7))

    def test_leitura_anterior_fica_obsoleta(self):
        """É este o caso que o `_stop_requested` sozinho deixava passar."""
        self.tts._geracao = 7
        self.tts._stop_requested = False  # já zerado pela leitura nova
        self.assertTrue(
            self.tts._leitura_obsoleta(6),
            "o worker da leitura anterior se julgou vigente e falaria por cima",
        )

    def test_stop_obsoleta_a_leitura_corrente(self):
        self.tts._geracao = 7
        self.tts._stop_requested = True
        self.assertTrue(self.tts._leitura_obsoleta(7))

    def test_cada_leitura_recebe_um_numero_novo(self):
        with patch("threading.Thread"):   # o worker não roda; só o número interessa
            antes = self.tts._geracao
            self.tts.speak_async("primeiro")
            meio = self.tts._geracao
            self.tts.speak_async("segundo")
            depois = self.tts._geracao
        self.assertEqual([antes + 1, antes + 2], [meio, depois],
                         "sem número novo por leitura, o guarda de geração não separa nada")


class TestSentinelaDoClipboard(unittest.TestCase):
    """A sentinela de detecção nunca pode sobrar no clipboard do usuário.

    Para saber se havia seleção, o Willy escreve um marcador, manda Ctrl+C e vê se o
    conteúdo mudou. O marcador era desfeito só quando o clipboard original continha
    texto — então com uma imagem copiada, ou com o clipboard vazio, ele ficava lá, e o
    próximo Ctrl+V do usuário colava `__willy_probe_1730000000.0__`.
    """

    def _rodar(self, tinha_texto, conteudo_antigo):
        import core.actions as actions_mod
        copiados = []

        def _copiar(texto):
            copiados.append(texto)
            return True

        def _formato_disponivel(fmt):
            self.assertEqual(13, fmt, "IsClipboardFormatAvailable deve consultar CF_UNICODETEXT (13)")
            return tinha_texto

        # A escrita passa por secure_copy (fora do histórico Win+V); a leitura segue no pyperclip.
        with patch.object(actions_mod._u32, "IsClipboardFormatAvailable", side_effect=_formato_disponivel), \
             patch("core.actions.pyperclip") as clip, \
             patch.object(ActionManager, "secure_copy", side_effect=_copiar), \
             patch("core.actions.keyboard"), \
             patch("core.actions.time.sleep"):
            # Cenário "não havia seleção": o paste devolve o conteúdo original na
            # primeira chamada e, depois de a sentinela ter sido escrita, devolve a
            # própria sentinela — que é o que se lê quando o Ctrl+C não copiou nada.
            clip.paste.side_effect = lambda: copiados[-1] if copiados else conteudo_antigo
            ActionManager.get_selected_text()
        return copiados

    def test_clipboard_nao_textual_nao_fica_com_a_sentinela(self):
        copiados = self._rodar(tinha_texto=False, conteudo_antigo="")
        self.assertTrue(copiados, "nada foi copiado — o teste perdeu o alvo")
        self.assertFalse(
            copiados[-1].startswith("__willy_probe_"),
            f"a sentinela sobrou no clipboard: {copiados[-1]!r}",
        )

    def test_clipboard_com_texto_e_restaurado(self):
        copiados = self._rodar(tinha_texto=True, conteudo_antigo="meu texto")
        self.assertEqual("meu texto", copiados[-1])

    def test_sentinela_nao_gravada_nao_devolve_o_clipboard_antigo_como_selecao(self):
        """Sem a sentinela, o paste lê o conteúdo antigo e ele viraria a "seleção" transformada."""
        import core.actions as actions_mod
        with patch.object(actions_mod._u32, "IsClipboardFormatAvailable", side_effect=lambda fmt: fmt == 13), \
             patch("core.actions.pyperclip") as clip, \
             patch.object(ActionManager, "secure_copy", return_value=False), \
             patch("core.actions.keyboard") as teclado, \
             patch("core.actions.time.sleep"):
            clip.paste.return_value = "senha copiada antes"
            self.assertIsNone(ActionManager.get_selected_text())
        teclado.send.assert_not_called()


class TestChunkSecondsNaoEAdivinhado(unittest.TestCase):
    """`chunk_seconds` é sempre segundos, por maior que seja o número.

    Havia um atalho que tratava `chunk_seconds >= 8000` como se fosse a taxa, para
    aceitar uma chamada posicional. Adivinhar o significado de um argumento pela sua
    magnitude quebra o caso legítimo em silêncio: um bloco de 10000 s virava 600 s com
    um header de 10 kHz sobre amostras de 16 kHz.
    """

    def setUp(self):
        self.mgr = AudioManager(sample_rate=16000, channels=1)

    def test_valor_grande_continua_sendo_segundos(self):
        audio = np.zeros(16000 * 3, dtype=np.float32)
        chunks = self.mgr.split_audio_into_chunks(audio, chunk_seconds=10000)
        self.assertEqual(1, len(chunks), "3 s cabem num bloco de 10000 s")
        chunks[0].seek(0)
        _, sr = sf.read(chunks[0])
        self.assertEqual(16000, sr, "o header passou a mentir: 10000 virou taxa")


class TestEscadaCobreOStart(unittest.TestCase):
    """Abrir e iniciar são falhas distintas, e as duas precisam cair para a taxa seguinte.

    O `start()` ficava fora da escada. Um device que aceita 16 kHz na abertura mas recusa
    no start fazia a negociação devolver um stream morto em vez de tentar 48000 — e o
    stream aberto era descartado sem `close()`, vazando o handle a cada tentativa.
    """

    def test_falha_no_start_cai_para_a_proxima_taxa(self):
        abertos = []

        def _abrir(samplerate=None, **kwargs):
            s = MagicMock()
            s.samplerate = samplerate
            # 16000 abre, mas nao inicia; 48000 funciona
            s.start.side_effect = (RuntimeError("device ocupado") if samplerate == 16000
                                   else None)
            abertos.append(s)
            return s

        with patch("core.audio.sd.InputStream", side_effect=_abrir), \
             patch("core.audio.sd.query_devices", return_value={"default_samplerate": 48000}):
            stream, taxa = negociar_stream(0, None, 1, 16000)

        self.assertEqual(48000, taxa, "a falha no start não caiu para a taxa seguinte")
        self.assertIs(abertos[-1], stream)
        abertos[0].close.assert_called_once_with()

    def test_stream_volta_ja_iniciado(self):
        with patch("core.audio.sd.InputStream", return_value=MagicMock()) as cls, \
             patch("core.audio.sd.query_devices", return_value={"default_samplerate": 16000}):
            stream, _ = negociar_stream(None, None, 1, 16000)
        self.assertIs(cls.return_value, stream)
        stream.start.assert_called_once_with()



class TestCascaDoHistoricoNaoRola(unittest.TestCase):
    """Na aba de Histórico, só a área de cartões rola.

    A extração transformou a aba inteira em `CTkScrollableFrame`. Com histórico longo,
    a busca, os filtros e o rodapé ("Exportar Markdown", "Limpar Histórico") saíam de
    vista junto com os cartões — some justamente o que serve para lidar com o excesso.
    No dashboard original a casca era fixa e só o container de cartões rolava.

    A verificação é por AST: o invariante é estrutural e não precisa de Tk nem de tela.
    """

    def _classes(self):
        import ast
        import os
        caminho = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui", "tabs", "tab_history.py",
        )
        with open(caminho, encoding="utf-8") as f:
            return ast.parse(f.read()), ast

    def test_a_aba_nao_e_um_frame_rolavel(self):
        arvore, ast = self._classes()
        classe = next(n for n in arvore.body
                      if isinstance(n, ast.ClassDef) and n.name == "HistoryTab")
        bases = [b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                 for b in classe.bases]
        self.assertNotIn(
            "CTkScrollableFrame", bases,
            "a aba inteira voltou a rolar; busca, filtros e rodapé somem com "
            "histórico longo",
        )
        self.assertIn("CTkFrame", bases)

    def test_o_container_de_cartoes_rola(self):
        arvore, ast = self._classes()
        alvo = None
        for no in ast.walk(arvore):
            if isinstance(no, ast.Assign) and isinstance(no.value, ast.Call):
                for t in no.targets:
                    if (isinstance(t, ast.Attribute) and t.attr == "scroll_historico"):
                        f = no.value.func
                        alvo = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        self.assertEqual(
            "CTkScrollableFrame", alvo,
            "sem um container rolável, o histórico longo estoura a janela",
        )

if __name__ == "__main__":
    unittest.main()
