"""
Contrato entre willy.py e a interface.

A UI conversa com o núcleo por um dicionário de callbacks montado em `willy.py`. Nada
verifica esse contrato: ler uma chave que ninguém registrou não levanta erro nenhum,
porque toda leitura é defensiva — `callbacks.get(...)` devolve None e o código cai num
fallback silencioso.

Duas vezes nesta branch a mesma coisa aconteceu, e nas duas a funcionalidade parecia
existir enquanto não fazia nada:

- `get_actual_sample_rate`: a aba de diagnóstico lia para testar o microfone na taxa real
  da gravação. Nunca foi registrado, então caía sempre em 16000 — exatamente a divergência
  que o teste de microfone deveria detectar.
- `safe_dispatch_ui`: as abas despachavam atualizações de UI por ele. Nunca foi registrado,
  então o despacho centralizado pela janela raiz nunca aconteceu.

Nenhum dos dois quebrava nada visível. É por isso que precisam de teste.
"""

import os
import re
import unittest

from tests.test_contrato_willy import _chaves_registradas_no_willy

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Uma leitura de callback: callbacks["x"] ou callbacks.get("x")
LEITURA = re.compile(r'callbacks(?:\.get\(|\[)\s*["\']([a-z_]+)["\']')


def _arquivos_de_ui():
    import glob
    caminhos = [os.path.join(RAIZ, "ui", "dashboard.py")]
    caminhos += glob.glob(os.path.join(RAIZ, "ui", "**", "*.py"), recursive=True)
    return [c for c in caminhos if os.path.isfile(c) and "__pycache__" not in c]


def _chaves_registradas():
    """As chaves do dicionário que willy.py entrega ao dashboard."""
    return _chaves_registradas_no_willy("callbacks_dash")


class TestContratoDeCallbacks(unittest.TestCase):
    def test_o_dicionario_existe(self):
        """Se o nome mudar, o teste abaixo passaria vazio e não protegeria nada."""
        self.assertIsNotNone(
            _chaves_registradas(),
            "callbacks_dash não foi encontrado em willy.py — este arquivo procura por "
            "esse nome, e sem ele a verificação vira um teste que sempre passa",
        )

    def test_toda_chave_lida_pela_ui_esta_registrada(self):
        registradas = _chaves_registradas() or set()
        orfas = {}
        for caminho in _arquivos_de_ui():
            with open(caminho, encoding="utf-8") as f:
                for n, linha in enumerate(f, 1):
                    for chave in LEITURA.findall(linha):
                        if chave not in registradas:
                            rel = os.path.relpath(caminho, RAIZ).replace("\\", "/")
                            orfas.setdefault(chave, []).append(f"{rel}:{n}")

        self.assertEqual(
            {}, orfas,
            "a interface lê callbacks que willy.py nunca registra. Não levanta erro: a "
            "leitura é defensiva e o código cai num fallback, então a funcionalidade "
            f"parece existir enquanto não faz nada. {orfas}",
        )



if __name__ == "__main__":
    unittest.main()
