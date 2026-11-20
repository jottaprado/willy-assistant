"""
O empacotamento tem que conhecer todos os módulos do projeto.

`Willy.spec` é a fonte única de `hiddenimports` e `datas`, e `build_installer.py` invoca o
PyInstaller diretamente sobre `Willy.spec`. O PyInstaller nem sempre segue imports indiretos,
e é por isso que a lista existe — mas uma lista manual envelhece: quem criar a próxima aba
precisa atualizar `Willy.spec`, e este teste garante que nenhum módulo de `core/` ou `ui/`
fique de fora.
"""

import os
import re
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACOTES = ("core", "ui")


def _modulos_reais():
    """Todo módulo importável sob core/ e ui/, em notação pontilhada."""
    encontrados = set()
    for pacote in PACOTES:
        for pasta, subpastas, arquivos in os.walk(os.path.join(RAIZ, pacote)):
            subpastas[:] = [s for s in subpastas if s != "__pycache__"]
            for nome in arquivos:
                if not nome.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(pasta, nome), RAIZ)
                dotted = rel.replace(os.sep, ".")[:-3]
                encontrados.add(dotted.removesuffix(".__init__"))
    return encontrados


def _ler(nome):
    with open(os.path.join(RAIZ, nome), encoding="utf-8") as f:
        return f.read()


def _spec_hidden_imports():
    spec = _ler("Willy.spec")
    bloco = re.search(r"hiddenimports=\[(.*?)\]", spec, re.DOTALL)
    assert bloco is not None, "hiddenimports não encontrado em Willy.spec"
    return set(re.findall(r"'([\w.]+)'", bloco.group(1)))


class TestEmpacotamentoConheceOsModulos(unittest.TestCase):
    def test_spec_declara_todos(self):
        declarados = _spec_hidden_imports()
        faltando = sorted(_modulos_reais() - declarados)
        self.assertEqual(
            [], faltando,
            "módulo ausente de hiddenimports em Willy.spec. O código-fonte roda e a "
            f"suíte passa; quem quebra é o .exe entregue, no boot: {faltando}",
        )

    def test_build_installer_usa_willy_spec_como_fonte_unica(self):
        """AUD-085: build_installer.py invoca PyInstaller com Willy.spec sem duplicar --hidden-import."""
        build = _ler("build_installer.py")
        self.assertIn('"Willy.spec"', build)
        self.assertEqual([], re.findall(r"--hidden-import=([\w.]+)", build))
        self.assertEqual([], re.findall(r"--add-data=", build))


class TestEmpacotamentoDasDependencias(unittest.TestCase):
    """Confere dependências de terceiros em Willy.spec e limites de versão em requirements.txt."""

    # O backend do Windows importa win32ctypes dentro de função, que o PyInstaller pode não
    # seguir. Sem ele no .exe, o keyring cai no backend que falha e a chave fica no .env.
    COFRE = ("keyring", "keyring.backends", "keyring.backends.Windows", "win32ctypes",
             "win32ctypes.pywin32", "win32ctypes.pywin32.win32cred", "win32ctypes.pywin32.pywintypes")

    def test_o_cofre_da_chave_vai_para_o_executavel(self):
        declarados = _spec_hidden_imports()
        self.assertEqual([], [m for m in self.COFRE if m not in declarados])

    def test_silero_vad_lite_vai_para_o_executavel(self):
        declarados = _spec_hidden_imports()
        self.assertIn("silero_vad_lite", declarados)
        spec = _ler("Willy.spec")
        self.assertIn("silero_vad_lite", spec)
        self.assertIn("silero_vad_lite/data", spec)
        linhas = [l.strip() for l in _ler("requirements.txt").splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        self.assertIn("silero-vad-lite==0.4.0", linhas)

    def test_pastas_nativas_sao_obrigatorias_no_spec_sem_pulo_silencioso(self):
        """Parte C: _sounddevice_data, _soundfile_data e silero_vad_lite/data não podem ser
        puladas em silêncio se faltarem no ambiente do build.
        """
        spec = _ler("Willy.spec")
        for pasta in ("_sounddevice_data", "_soundfile_data", "silero_vad_lite/data"):
            self.assertIn(pasta, spec)
        self.assertIn("if not os.path.exists(", spec)
        self.assertNotIn("if os.path.exists(", spec)
        self.assertIn("pip install -r requirements.txt", spec)

    def test_keyring_esta_nos_requisitos_e_todos_tem_teto_de_versao(self):
        linhas = [l.strip() for l in _ler("requirements.txt").splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        requisitos = [re.split(r"[<>=!~ ]", l, maxsplit=1)[0].lower() for l in linhas]
        self.assertIn("keyring", requisitos)
        for linha in linhas:
            with self.subTest(requisito=linha):
                self.assertTrue(
                    "==" in linha or ("<" in linha and ">=" in linha),
                    f"requisito sem limite superior de versão (AUD-088): {linha}",
                )


if __name__ == "__main__":
    unittest.main()
