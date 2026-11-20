"""
A estrutura do projeto: core/ não depende da interface, e a interface mora em ui/.

Até a 1.5.0, core/ tinha quatro fachadas (pill, tray, spotlight, teleprompter) que só
reexportavam ui/overlays, e o core/__init__ as importava. Importar a pílula num processo
novo dava ImportError (import circular: ui.overlays -> core -> ui.overlays), e os testes
precisavam de um "import core" antes de tudo. O dashboard.py ficava solto na raiz.

Os testes de import rodam num interpretador novo: neste processo, outros testes já
carregaram core e ui, e o import circular não apareceria.
"""

import os
import subprocess
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python(codigo):
    return subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120, check=False)


class TestImports(unittest.TestCase):
    def test_pilula_importa_sem_importar_core_antes(self):
        r = _python("from ui.overlays.pill import FloatingPill")
        self.assertEqual(0, r.returncode, r.stderr[-1500:])

    def test_core_nao_carrega_a_interface(self):
        r = _python("import sys, core; print(sorted(m for m in sys.modules if m == 'ui' or m.startswith('ui.')))")
        self.assertEqual(0, r.returncode, r.stderr[-1500:])
        self.assertEqual("[]", r.stdout.strip(), "core/ não pode importar módulos de ui/")


class TestPastas(unittest.TestCase):
    def test_raiz_so_tem_os_pontos_de_entrada(self):
        # willy.py (o app), versao.py (fonte única da versão, sem imports para ninguém cair
        # em import circular) e build_installer.py (o build). O resto mora em core/ ou ui/.
        na_raiz = sorted(f for f in os.listdir(RAIZ) if f.endswith(".py"))
        self.assertEqual(["build_installer.py", "versao.py", "willy.py"], na_raiz)

    def test_core_sem_fachadas_da_interface(self):
        for nome in ("pill.py", "tray.py", "spotlight.py", "teleprompter.py"):
            self.assertFalse(os.path.exists(os.path.join(RAIZ, "core", nome)), f"core/{nome} voltou")


if __name__ == "__main__":
    unittest.main()
