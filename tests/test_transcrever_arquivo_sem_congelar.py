"""
"Transcrever arquivo" não congela a janela.

O botão da aba Histórico chamava transcrever_arquivo_externo na thread da interface: o envio
à Groq (minutos, num arquivo longo) travava a janela, e nem o "processando" da pílula
aparecia, porque as atualizações dela esperam a mesma thread.
"""

import ast
import os
import threading
import time
import unittest
from unittest.mock import MagicMock

from tests.willy_isolado import _funcao_do_willy

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestTranscreverArquivo(unittest.TestCase):
    def test_o_botao_volta_na_hora_e_a_transcricao_segue_em_outra_thread(self):
        terminou, threads = threading.Event(), []

        def transcrever_devagar(caminho):
            threads.append(threading.current_thread())
            time.sleep(0.3)  # a Groq transcrevendo
            terminou.set()

        disparar = _funcao_do_willy("transcrever_arquivo_em_segundo_plano", threading=threading,
                                    transcrever_arquivo_externo=transcrever_devagar)
        inicio = time.monotonic()
        disparar("C:/audio.mp3")
        self.assertLess(time.monotonic() - inicio, 0.2, "a thread da interface esperou a transcrição")
        self.assertTrue(terminou.wait(2))
        self.assertIsNot(threading.current_thread(), threads[0])
        self.assertTrue(threads[0].daemon, "fechar o Willy não pode esperar a transcrição")

    def test_passa_o_arquivo_escolhido(self):
        thread = MagicMock()
        disparar = _funcao_do_willy("transcrever_arquivo_em_segundo_plano", threading=thread,
                                    transcrever_arquivo_externo="transcrever")
        disparar("C:/reuniao.m4a")
        self.assertEqual("transcrever", thread.Thread.call_args.kwargs["target"])
        self.assertEqual(("C:/reuniao.m4a",), thread.Thread.call_args.kwargs["args"])
        thread.Thread.return_value.start.assert_called_once_with()

    def test_a_aba_recebe_a_versao_em_segundo_plano(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        valores = [v for n in ast.walk(arvore) if isinstance(n, ast.Dict)
                   for k, v in zip(n.keys, n.values)
                   if isinstance(k, ast.Constant) and k.value == "on_transcribe_file"]
        self.assertEqual(["transcrever_arquivo_em_segundo_plano"], [getattr(v, "id", None) for v in valores])


if __name__ == "__main__":
    unittest.main()
