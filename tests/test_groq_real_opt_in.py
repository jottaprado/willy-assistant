"""
Chamada de verdade aos 3 modelos de LLM da Groq (Flash, Smart e Coder).

Só roda com WILLY_TEST_GROQ_REAL=1: gasta a cota da chave e precisa de rede. A chave vem de
GROQ_API_KEY ou, sem ela, do cofre do Windows em que o Willy a guarda, só lendo. Fora desse
pedido, nenhum teste lê o cofre de verdade.

    set WILLY_TEST_GROQ_REAL=1
    .venv\\Scripts\\python.exe -m unittest tests.test_groq_real_opt_in -v

Para cada modelo, pelo GroqService.completar que o Willy usa: a resposta crua não traz
<think> (os parâmetros de raciocínio funcionam), o texto não vem vazio e segue o pedido, e a
chamada leva menos de LIMITE_S. O tempo de cada um sai no stderr.
"""

import os
import sys
import time
import unittest

from core import modelos_llm
from core.groq_service import GroqService

PEDIDO = os.environ.get("WILLY_TEST_GROQ_REAL") == "1"
LIMITE_S = 20.0
MODELOS = (("Flash", modelos_llm.FLASH), ("Smart", modelos_llm.SMART), ("Coder", modelos_llm.CODER))


def _chave() -> str:
    chave = os.environ.get("GROQ_API_KEY", "").strip()
    if chave:
        return chave
    from core.config import COFRE_SERVICO, COFRE_USUARIO, cofre_do_sistema
    cofre = cofre_do_sistema()
    return ((cofre.get_password(COFRE_SERVICO, COFRE_USUARIO) if cofre else "") or "").strip()


class _Espiao:
    """O cliente da Groq, guardando o texto cru da última resposta (antes da limpeza)."""

    def __init__(self, cliente):
        self._cliente, self.cru = cliente, None
        self.chat = self.completions = self

    def create(self, **kwargs):
        resposta = self._cliente.chat.completions.create(**kwargs)
        self.cru = resposta.choices[0].message.content or ""
        return resposta


@unittest.skipUnless(PEDIDO, "chamada de verdade à Groq: só com WILLY_TEST_GROQ_REAL=1")
class TestGroqReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chave = _chave()
        if not chave:
            raise unittest.SkipTest("sem chave da Groq (GROQ_API_KEY ou o cofre do Willy)")
        cls.cliente = GroqService(api_key=chave).get_client()

    def test_os_tres_modelos_respondem_sem_raciocinio(self):
        for nome, modelo in MODELOS:
            with self.subTest(modelo=modelo):
                espiao = _Espiao(self.cliente)
                inicio = time.monotonic()
                texto = GroqService.completar(
                    espiao, modelo, [{"role": "user", "content": "Responda só com a palavra: pronto"}],
                    temperature=0.0, max_tokens=16, timeout=30.0)
                segundos = time.monotonic() - inicio
                print(f"[Groq real] {nome} ({modelo}): {segundos:.2f} s -> {texto!r}", file=sys.stderr)
                self.assertNotIn("<think", espiao.cru.lower())
                self.assertIn("pronto", texto.lower())
                self.assertLess(segundos, LIMITE_S)


# (texto como o Whisper entrega, [(âncora, sinal esperado)]): "?" exige "?" logo depois da
# âncora; "." aceita qualquer outro sinal (o pedido aceita "." ou ",").
CASOS_DA_GROQ = [
    ("Ok, a última versão está instalada no meu computador. Outra coisa, o atalho de desfazer parou de responder.",
     [("meu computador", "?"), ("parou de responder", ".")]),
    (("Ou seja, depois que eu pagar o frete, não vai sobrar muito, assim, mesmo se eu buscasse sem pagar o frete? "
      "Então, pelo que eu estou entendendo, hoje, o e-mail de alerta, ele cai direto na fila? "
      "Então ou é da fábrica ou é da Bahia, certo."),
     [("sem pagar o frete", "."), ("direto na fila", "."), ("da Bahia, certo", "?")]),
    ("Eu estava olhando o código aqui, né? E vi que o teste do instalador estava quebrado.",
     [("código aqui", "."), ("estava quebrado", ".")]),
    ("A gente pode cachear o resultado por cinco minutos, faz sentido.", [("faz sentido", "?")]),
    ("Qual é a diferença entre o merge e o rebase.", [("o rebase", "?")]),
    ("Como assim o build passou sem rodar os testes.", [("os testes", "?")]),
    ("Ou seja, depois do deploy a gente não precisa mais reiniciar o servidor? Isso economiza uns dez minutos por dia.",
     [("reiniciar o servidor", "."), ("por dia", ".")]),
    ("Quero saber se eu posso transformar uma loja em mercado?", [("em mercado", ".")]),
    ("Como combinamos ontem, segue o arquivo com as correções.", [("as correções", ".")]),
    ("Pode deixar que eu faço a revisão amanhã.", [("revisão amanhã", ".")]),
    ("Se não der para entregar hoje, tudo bem.", [("tudo bem", ".")]),
    ("Então você vai mandar o arquivo ainda hoje?", [("ainda hoje", "?")]),
    ("A última versão está instalada no meu computador. Agora vou testar o atalho de novo.",
     [("meu computador", "."), ("de novo", ".")]),
]


def _sinal_depois(saida: str, ancora: str, desde: int):
    i = saida.lower().find(ancora.lower(), desde)
    if i < 0:
        return None, desde
    fim = i + len(ancora)
    resto = saida[fim:].lstrip(" \"'”*_`")
    return (resto[:1] if resto[:1] in ".?!,;:" else ""), fim


@unittest.skipUnless(PEDIDO, "chamada de verdade à Groq: só com WILLY_TEST_GROQ_REAL=1")
class TestNaGroqDeVerdade(unittest.TestCase):
    """Benchmark opt-in de pontuação de perguntas e afirmações na API real da Groq."""

    def test_pontuacao_dos_casos_do_dono(self):
        from tests.test_perguntas_e_afirmacoes import _NO_EDITOR, _pipeline

        chave = _chave()
        if not chave:
            self.skipTest("sem chave da Groq (GROQ_API_KEY ou o cofre do Willy)")
        pipeline = _pipeline(GroqService(api_key=chave, llm_model=modelos_llm.SMART))
        certos, total = 0, 0
        for entrada, ancoras in CASOS_DA_GROQ:
            saida, _, _ = pipeline._enriquecer_texto(entrada, _NO_EDITOR)
            pos = 0
            for ancora, esperado in ancoras:
                sinal, pos = _sinal_depois(saida, ancora, pos)
                ok = sinal is not None and ((sinal == "?") if esperado == "?" else (sinal != "?"))
                certos, total = certos + ok, total + 1
                if not ok:
                    print(f"[Groq real] {ancora!r}: esperado {esperado!r}, veio {sinal!r} em {saida!r}", file=sys.stderr)
        print(f"[Groq real] {certos}/{total} âncoras certas", file=sys.stderr)
        self.assertGreaterEqual(certos / total, 0.85)


if __name__ == "__main__":
    unittest.main()
