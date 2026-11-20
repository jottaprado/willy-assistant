"""
O willy.py importado num processo à parte não toca a pasta do repositório.

Rodando do código-fonte, a pasta de dados é a raiz do repo: importar o willy lia o .env de
lá (no clone de quem desenvolve, o de verdade) e criava o .snippets.json na raiz num clone
novo. Com WILLY_DATA_DIR, o rodar_no_willy aponta tudo para uma pasta temporária.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from tests.willy_isolado import RAIZ, _arvore_do_willy, _funcao_do_willy, rodar_no_willy

_SCRIPT = r"""
import json
import willy
from core import config
print("RESULTADO=" + json.dumps({"dados": config.USER_DATA_DIR, "env": config.ENV_FILE,
                                 "historico": config.HISTORY_FILE, "snippets": willy.snippet_mgr.file_path}))
"""

_IMPORTA_CONFIG = r"""
import os, sys
import core.config as c
antes = os.path.exists(c.ENV_FILE)
c.criar_env_do_template()
print(antes, os.path.exists(c.ENV_FILE))
"""


class TestWillyIsolado(unittest.TestCase):
    def test_dados_do_processo_isolado_ficam_fora_do_repo(self):
        raiz = os.path.normcase(os.path.abspath(RAIZ))
        for nome, caminho in rodar_no_willy(_SCRIPT).items():
            with self.subTest(arquivo=nome):
                self.assertFalse(os.path.normcase(os.path.abspath(caminho)).startswith(raiz), caminho)

    def test_a_partida_do_willy_cria_o_env_a_partir_do_template(self):
        script = (
            "import json, os\nimport willy\nfrom core import config\n"
            "antes_env = os.path.exists(config.ENV_FILE)\n"
            "antes_snippets = os.path.exists(willy.snippet_mgr.file_path)\n"
            "cofre_antes = willy.config_mgr.cofre is not None\n"
            "willy.inicializar_ambiente_partida()\n"
            "print('RESULTADO=' + json.dumps({"
            "'antes_env': antes_env, 'antes_snippets': antes_snippets, 'cofre_antes': cofre_antes, "
            "'criado': os.path.exists(config.ENV_FILE)}))"
        )
        self.assertEqual(
            {"antes_env": False, "antes_snippets": False, "cofre_antes": False, "criado": True},
            rodar_no_willy(script),
        )

    def test_snippet_manager_resolve_caminho_dinamico_e_nao_grava_no_init(self):
        """AUD-025 e AUD-036: definir_diretorio_dados atualiza caminhos e SnippetManager() é dinâmico e preguiçoso."""
        from core import config
        from core.snippets import SnippetManager

        original_dir = config.USER_DATA_DIR
        with tempfile.TemporaryDirectory() as pasta_nova:
            try:
                config.definir_diretorio_dados(pasta_nova)
                mgr = SnippetManager()
                esperado = os.path.join(pasta_nova, ".snippets.json")
                self.assertEqual(mgr.file_path, esperado)
                self.assertFalse(os.path.exists(esperado))
                snippets = mgr.get_snippets()
                self.assertGreater(len(snippets), 0)
                self.assertFalse(os.path.exists(esperado))
                self.assertTrue(mgr.save_snippet("novo gatilho", "Novo", "Conteúdo"))
                self.assertTrue(os.path.exists(esperado))
            finally:
                config.definir_diretorio_dados(original_dir)

    def test_falhas_de_inicializacao_e_log_sao_registradas_em_stderr(self):
        """AUD-007, AUD-147, AUD-201, AUD-202 e AUD-203: falhas de log/cópia/sinalização não são engolidas."""
        import ast
        import contextlib
        import io
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from core import config

        # 1. AUD-201, AUD-202, AUD-203: criar_env_do_template em modo frozen registra falhas em stderr
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = config.USER_DATA_DIR
            try:
                config.definir_diretorio_dados(tmp)
                stderr_buf = io.StringIO()
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch("shutil.copyfile", side_effect=PermissionError("bloqueado")),
                    contextlib.redirect_stderr(stderr_buf),
                ):
                    config.criar_env_do_template()
                saida = stderr_buf.getvalue()
                self.assertIn("[Config]", saida)
                self.assertIn("bloqueado", saida)
            finally:
                config.definir_diretorio_dados(original_dir)

        # 2. AUD-007 e AUD-147 em willy.py
        escopo_log = {
            "os": os,
            "sys": sys,
            "time": __import__("time"),
            "USER_DATA_DIR": "/caminho/invalido",
            "SafeStream": type("SafeStream", (), {}),
        }
        redirecionar_log = _funcao_do_willy("_redirecionar_log_debug", **escopo_log)
        err_real = io.StringIO()
        with (
            patch.object(sys, "stdout", escopo_log["SafeStream"]()),
            patch.object(sys, "__stderr__", err_real),
            patch("builtins.open", side_effect=PermissionError("log bloqueado")),
        ):
            redirecionar_log()
        self.assertIn("log bloqueado", err_real.getvalue())

        arvore = _arvore_do_willy()
        fn_main = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        fn_verif = next(n for n in ast.walk(fn_main) if isinstance(n, ast.FunctionDef) and n.name == "verificar_solicitacao")
        dash_mock = MagicMock()
        dash_mock.mostrar.side_effect = RuntimeError("falha mostrar")
        root_mock = MagicMock()
        remove_mock = MagicMock()
        escopo_verif = {
            "lembrar_janela_fora_do_willy": MagicMock(),
            "os": SimpleNamespace(path=SimpleNamespace(exists=lambda _p: True), remove=remove_mock),
            "FLAG_SHOW_DASHBOARD": "flag_teste",
            "dashboard": dash_mock,
            "root": root_mock,
        }
        exec(compile(ast.Module(body=[fn_verif], type_ignores=[]), "willy.py", "exec"), escopo_verif)
        stderr_verif = io.StringIO()
        with contextlib.redirect_stderr(stderr_verif):
            escopo_verif["verificar_solicitacao"]()
        remove_mock.assert_called_once_with("flag_teste")
        dash_mock.mostrar.assert_called_once_with()
        self.assertIn("falha mostrar", stderr_verif.getvalue())

    def test_fechar_aplicacao_encerra_loop_tk_sem_os_exit(self):
        """AUD-008: fechar_aplicacao e WillyDashboard.fechar_app encerram sem os._exit(0)."""
        from unittest.mock import MagicMock, patch

        root_mock = MagicMock()
        single_mock = MagicMock()
        fechar = _funcao_do_willy(
            "fechar_aplicacao",
            sound_mgr=MagicMock(),
            tts_mgr=MagicMock(),
            hotkey_mgr=MagicMock(),
            audio_mgr=MagicMock(),
            tray_mgr=MagicMock(),
            teleprompter=MagicMock(),
            pill=MagicMock(),
            root=root_mock,
            single_instance=single_mock,
            safe_dispatch_ui=lambda fn, *a: fn(*a),
            sys=sys,
        )
        with patch("os._exit", side_effect=AssertionError("os._exit não deve ser chamado")):
            fechar()
        root_mock.quit.assert_called_once_with()
        root_mock.destroy.assert_called_once_with()
        single_mock.release.assert_called_once_with()

    def test_importar_o_config_nao_cria_o_env_e_a_partida_cria(self):
        # Num clone novo, todo teste que importava core.config deixava um .env na raiz.
        with tempfile.TemporaryDirectory() as dados:
            env = dict(
                os.environ,
                APPDATA=dados,
                WILLY_DATA_DIR=dados,
                PYTHONPATH=RAIZ,
                PYTHONIOENCODING="utf-8",
                PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
            )
            r = subprocess.run([sys.executable, "-c", _IMPORTA_CONFIG], cwd=RAIZ, env=env,
                               capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
            self.assertEqual("False True", r.stdout.strip(), r.stderr[-800:])
            with open(os.path.join(RAIZ, ".env.template"), encoding="utf-8") as t:
                modelo = t.read()
            with open(os.path.join(dados, ".env"), encoding="utf-8") as f:
                self.assertEqual(modelo, f.read())


if __name__ == "__main__":
    unittest.main()
