"""
A versão do Willy tem uma fonte única: versao.py.

Em 08/10/2026 havia quatro números ao mesmo tempo: 1.2.0 no instalador, 1.4.0 na tela
"Sobre", 1.9.0 no perfil exportado e no ZIP portátil. Estes testes reprovam qualquer
versão escrita à mão fora de versao.py.
"""

import os
import re
import unittest
from unittest.mock import MagicMock, patch

from versao import __version__

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Arquivos que mostram ou gravam a versão: nenhum pode ter o número escrito à mão.
QUEM_USA_A_VERSAO = [
    "ui/theme.py",
    "core/storage/profile_manager.py",
    "build_installer.py",
    "willy_installer.iss",
]
VERSAO_LITERAL = re.compile(r"""["']v?\d+\.\d+\.\d+["']|v\d+\.\d+\.\d+""")


def _ler(rel):
    with open(os.path.join(RAIZ, rel), encoding="utf-8") as f:
        return f.read()


class TestVersaoUnica(unittest.TestCase):
    def test_versao_e_semver(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_nenhum_numero_de_versao_escrito_fora_de_versao_py(self):
        for rel in QUEM_USA_A_VERSAO:
            with self.subTest(arquivo=rel):
                self.assertEqual([], VERSAO_LITERAL.findall(_ler(rel)))

    def test_tela_sobre_mostra_a_versao_unica(self):
        from ui.theme import APP_VERSION
        self.assertEqual(f"v{__version__}", APP_VERSION)

    def test_perfil_exportado_grava_a_versao_unica(self):
        from core.storage.profile_manager import ProfileManager
        gravado = {}
        with patch("core.storage.profile_manager._atomic_write_json",
                   side_effect=lambda _caminho, dados, *_a, **_k: gravado.update(dados)):
            self.assertTrue(ProfileManager(MagicMock()).export_profile("perfil.json"))
        self.assertEqual(__version__, gravado["willy_version"])

    def test_instalador_recebe_a_versao_do_build(self):
        """O .iss não define a versão; o build_installer a lê de versao.py e passa ao Inno."""
        iss = _ler("willy_installer.iss")
        self.assertNotRegex(iss, r'#define\s+MyAppVersion\s+"')
        self.assertIn("#ifndef MyAppVersion", iss)
        build = _ler("build_installer.py")
        self.assertIn('"versao.py"', build)
        self.assertIn("/DMyAppVersion={VERSAO}", build)


if __name__ == "__main__":
    unittest.main()
