"""
A chave da Groq mora no cofre do sistema e sai do .env.

Até a 1.4.0, o keyring nem estava instalado: todo o código do cofre era morto e a chave
ficava em texto puro no .env. E quando o cofre gravava, o save_settings só tirava a chave
do mapeamento, e o SettingsStore (que preserva as linhas que não recebe) deixava a linha
antiga, com a chave, no arquivo.

Nenhum teste daqui toca o Credential Manager da máquina: o cofre é um dicionário em
memória, e o ConfigManager() sem argumento não usa cofre nenhum.
"""

import ast
import os
import unittest
from unittest.mock import MagicMock, patch

import core.config as cfg_module
from core.config import COFRE_SERVICO, COFRE_USUARIO, ConfigManager, cofre_do_sistema
from tests.config_isolada import isolar_config

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CofreDeMentira:
    """A interface do keyring que o ConfigManager usa, sobre um dicionário."""

    def __init__(self, chave=None, falha=False):
        self.guardado = {} if chave is None else {(COFRE_SERVICO, COFRE_USUARIO): chave}
        self.falha = falha

    def get_password(self, servico, usuario):
        if self.falha:
            raise RuntimeError("cofre fora do ar")
        return self.guardado.get((servico, usuario))

    def set_password(self, servico, usuario, senha):
        if self.falha:
            raise RuntimeError("cofre fora do ar")
        self.guardado[(servico, usuario)] = senha

    def delete_password(self, servico, usuario):
        if self.falha:
            raise RuntimeError("cofre fora do ar")
        del self.guardado[(servico, usuario)]  # KeyError, como o PasswordDeleteError

    @property
    def chave(self):
        return self.guardado.get((COFRE_SERVICO, COFRE_USUARIO))


class _EnvTemporario(unittest.TestCase):
    def setUp(self):
        d = isolar_config(self)
        self.env_file = os.path.join(d, ".env")

    def _escrever_env(self, conteudo):
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write(conteudo)

    def _ler_env(self):
        with open(self.env_file, encoding="utf-8") as f:
            return f.read()


class TestMigracaoNoReload(_EnvTemporario):
    def test_chave_em_texto_puro_vai_para_o_cofre_e_sai_do_env(self):
        self._escrever_env("# minhas configs\nGROQ_API_KEY=gsk_texto_puro\nVOICE_HOTKEY=ctrl+space\n")
        cofre = CofreDeMentira()
        cfg = ConfigManager(cofre=cofre)

        self.assertEqual("gsk_texto_puro", cfg.groq_api_key)
        self.assertEqual("gsk_texto_puro", cofre.chave)
        env = self._ler_env()
        self.assertNotIn("gsk_texto_puro", env)
        self.assertIn("GROQ_API_KEY=\n", env)
        self.assertIn("# minhas configs\n", env)
        self.assertIn("VOICE_HOTKEY=ctrl+space\n", env)
        # A próxima abertura acha a chave no cofre.
        self.assertEqual("gsk_texto_puro", ConfigManager(cofre=cofre).groq_api_key)

    def test_cofre_que_falha_deixa_a_chave_no_env(self):
        self._escrever_env("GROQ_API_KEY=gsk_texto_puro\n")
        cfg = ConfigManager(cofre=CofreDeMentira(falha=True))
        self.assertEqual("gsk_texto_puro", cfg.groq_api_key)
        self.assertIn("GROQ_API_KEY=gsk_texto_puro", self._ler_env())

    def test_chave_no_env_ganha_da_que_esta_no_cofre(self):
        """Uma chave no .env é mais nova: edição à mão, ou um save em que o cofre falhou."""
        self._escrever_env("GROQ_API_KEY=gsk_nova\n")
        cofre = CofreDeMentira(chave="gsk_antiga")
        cfg = ConfigManager(cofre=cofre)
        self.assertEqual("gsk_nova", cfg.groq_api_key)
        self.assertEqual("gsk_nova", cofre.chave)
        self.assertNotIn("gsk_", self._ler_env())

    def test_linha_com_export_e_substituida_e_nao_duplicada(self):
        for linha in ("export GROQ_API_KEY=gsk_exportada\n", "export\tGROQ_API_KEY=gsk_exportada\n"):
            with self.subTest(linha=linha):
                self._escrever_env(linha)
                cofre = CofreDeMentira()
                ConfigManager(cofre=cofre)
                self.assertEqual("gsk_exportada", cofre.chave)
                env = self._ler_env()
                self.assertNotIn("gsk_exportada", env)
                self.assertEqual(1, env.count("GROQ_API_KEY="))

    def test_env_com_bom_tambem_perde_a_chave(self):
        """Salvo no Bloco de Notas, o .env começa com BOM e a primeira linha não era reconhecida."""
        with open(self.env_file, "w", encoding="utf-8-sig") as f:
            f.write("GROQ_API_KEY=gsk_com_bom\nVOICE_HOTKEY=ctrl+space\n")
        cofre = CofreDeMentira()
        ConfigManager(cofre=cofre)
        self.assertEqual("gsk_com_bom", cofre.chave)
        env = self._ler_env()
        self.assertNotIn("gsk_com_bom", env)
        self.assertEqual(1, env.count("GROQ_API_KEY="))

    def test_env_ja_limpo_nao_e_regravado(self):
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_no_cofre")
        with patch.object(cfg_module.SettingsStore, "save_settings") as gravar:
            cfg = ConfigManager(cofre=cofre)
        self.assertEqual("gsk_no_cofre", cfg.groq_api_key)
        gravar.assert_not_called()


class TestEnvCandidato(unittest.TestCase):
    """O .env antigo ao lado do executável, de onde a chave é lida quando falta no do app."""

    def setUp(self):
        d = isolar_config(self)
        os.makedirs(os.path.join(d, "appdata"))
        os.makedirs(os.path.join(d, "instalacao"))
        self.env_app = os.path.join(d, "appdata", ".env")
        self.env_antigo = os.path.join(d, "instalacao", ".env")
        with open(self.env_app, "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=\n")
        with open(self.env_antigo, "w", encoding="utf-8") as f:
            f.write("# do instalador antigo\nGROQ_API_KEY=gsk_antiga_no_exe\nVOICE_HOTKEY=ctrl+space\n")
        for p in (
            patch.object(cfg_module, "ENV_FILE", self.env_app),
            patch.object(cfg_module, "BASE_DIR", os.path.join(d, "instalacao")),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _antigo(self):
        with open(self.env_antigo, encoding="utf-8") as f:
            return f.read()

    def test_chave_do_env_antigo_vai_ao_cofre_e_sai_de_la(self):
        cofre = CofreDeMentira()
        cfg = ConfigManager(cofre=cofre)
        self.assertEqual("gsk_antiga_no_exe", cfg.groq_api_key)
        self.assertEqual("gsk_antiga_no_exe", cofre.chave)
        antigo = self._antigo()
        self.assertNotIn("gsk_antiga_no_exe", antigo)
        self.assertIn("GROQ_API_KEY=\n", antigo)
        self.assertIn("# do instalador antigo\n", antigo)
        self.assertIn("VOICE_HOTKEY=ctrl+space\n", antigo)
        # A próxima abertura acha a chave no cofre.
        self.assertEqual("gsk_antiga_no_exe", ConfigManager(cofre=cofre).groq_api_key)

    def test_sem_cofre_o_env_antigo_nao_e_tocado(self):
        antes = self._antigo()
        self.assertEqual("gsk_antiga_no_exe", ConfigManager().groq_api_key)
        self.assertEqual(antes, self._antigo())

    def test_cofre_que_falha_tambem_nao_toca_no_env_antigo(self):
        antes = self._antigo()
        ConfigManager(cofre=CofreDeMentira(falha=True))
        self.assertEqual(antes, self._antigo())

    def test_erro_que_nao_e_de_leitura_nao_e_engolido(self):
        """O except Exception engolia o AttributeError do save_settings chamado cedo demais."""
        with patch.object(cfg_module, "dotenv_values", side_effect=[{}, AttributeError("bug")]), self.assertRaises(AttributeError):
            ConfigManager()


class TestSaveSettings(_EnvTemporario):
    def test_chave_nova_vai_ao_cofre_e_nao_ao_env(self):
        self._escrever_env("GROQ_API_KEY=gsk_antiga\n")
        cofre = CofreDeMentira()
        cfg = ConfigManager(cofre=cofre)
        cfg.save_settings({"GROQ_API_KEY": "gsk_nova"})
        self.assertEqual("gsk_nova", cofre.chave)
        self.assertNotIn("gsk_", self._ler_env())
        self.assertIn("GROQ_API_KEY=\n", self._ler_env())

    def test_save_com_o_cofre_de_volta_tira_o_texto_puro_que_ficou(self):
        """O bug original: só tirar a chave do mapeamento deixava a linha antiga no arquivo.

        A migração do reload limpa o .env antes de qualquer save, e esconderia o bug. Aqui o
        cofre falha na abertura (a chave fica no .env) e volta antes do save.
        """
        self._escrever_env("GROQ_API_KEY=gsk_antiga\nAUTO_SILENCE=true\n")
        cofre = CofreDeMentira(falha=True)
        cfg = ConfigManager(cofre=cofre)
        self.assertIn("gsk_antiga", self._ler_env())
        cofre.falha = False
        cfg.save_settings({"AUTO_SILENCE": False})
        self.assertEqual("gsk_antiga", cofre.chave)
        self.assertNotIn("gsk_antiga", self._ler_env())
        self.assertIn("AUTO_SILENCE=false\n", self._ler_env())

    def test_salvar_outra_opcao_nao_devolve_a_chave_ao_env(self):
        self._escrever_env("GROQ_API_KEY=gsk_x\n")
        cfg = ConfigManager(cofre=CofreDeMentira())
        cfg.save_settings({"AUTO_SILENCE": False})
        self.assertNotIn("gsk_x", self._ler_env())

    def test_esvaziar_o_campo_apaga_a_chave_do_cofre(self):
        """Sem apagar, a chave antiga voltava do cofre no boot seguinte, invisível."""
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_antiga")
        cfg = ConfigManager(cofre=cofre)
        cfg.save_settings({"GROQ_API_KEY": ""})
        self.assertIsNone(cofre.chave)
        self.assertEqual("", ConfigManager(cofre=cofre).groq_api_key)

    def test_campo_vazio_porque_o_cofre_nao_leu_no_boot_nao_apaga_a_chave(self):
        """Leitura que falha no boot deixa o campo vazio; salvar outro ajuste manda a chave
        vazia, e apagar ali perdia de vez uma chave que a pessoa nem viu."""
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_guardada", falha=True)
        cfg = ConfigManager(cofre=cofre)
        self.assertEqual("", cfg.groq_api_key)
        cofre.falha = False
        cfg.save_settings({"GROQ_API_KEY": "", "AUTO_SILENCE": False})
        self.assertEqual("gsk_guardada", cofre.chave)

    def test_salvar_outra_opcao_nao_apaga_a_chave_do_cofre(self):
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_guardada")
        ConfigManager(cofre=cofre).save_settings({"AUTO_SILENCE": False})
        self.assertEqual("gsk_guardada", cofre.chave)

    def test_cofre_fora_do_ar_no_save_mantem_a_chave_no_env(self):
        self._escrever_env("GROQ_API_KEY=\n")
        cofre = CofreDeMentira(chave="gsk_antiga")
        cfg = ConfigManager(cofre=cofre)
        cofre.falha = True
        cfg.save_settings({"GROQ_API_KEY": "gsk_nova"})
        self.assertIn("GROQ_API_KEY=gsk_nova\n", self._ler_env())
        # E a reabertura usa a nova, não a velha que ficou no cofre.
        cofre.falha = False
        self.assertEqual("gsk_nova", ConfigManager(cofre=cofre).groq_api_key)


class TestIsolamentoDoCofreReal(_EnvTemporario):
    def test_construtor_sem_cofre_nao_toca_no_keyring(self):
        self._escrever_env("GROQ_API_KEY=gsk_teste\n")
        keyring_falso = MagicMock()
        with patch.object(cfg_module, "keyring", keyring_falso):
            cfg = ConfigManager()
            cfg.save_settings({"GROQ_API_KEY": "gsk_outra"})
        self.assertIsNone(cfg.cofre)
        self.assertEqual([], keyring_falso.mock_calls)
        # Sem cofre, a chave segue no .env, como antes.
        self.assertIn("GROQ_API_KEY=gsk_outra\n", self._ler_env())

    def test_cofre_do_sistema_e_o_keyring_sem_chamar_nada(self):
        keyring_falso = MagicMock()
        with patch.object(cfg_module, "keyring", keyring_falso):
            self.assertIs(keyring_falso, cofre_do_sistema())
        self.assertEqual([], keyring_falso.mock_calls)

    def test_nenhum_teste_constroi_com_o_cofre_do_sistema(self):
        """cofre=cofre_do_sistema() ou cofre=keyring num teste gravaria na máquina de quem roda."""
        def _e_o_cofre_real(no):
            if isinstance(no, ast.Call):
                no = no.func
            return getattr(no, "id", getattr(no, "attr", None)) in ("cofre_do_sistema", "keyring")

        achados = []
        for nome in sorted(os.listdir(os.path.join(RAIZ, "tests"))):
            if not nome.endswith(".py"):
                continue
            with open(os.path.join(RAIZ, "tests", nome), encoding="utf-8") as f:
                arvore = ast.parse(f.read())
            for no in ast.walk(arvore):
                if not isinstance(no, ast.Call):
                    continue
                cofre = [kw.value for kw in no.keywords if kw.arg == "cofre"]
                if getattr(no.func, "id", getattr(no.func, "attr", None)) == "ConfigManager":
                    cofre += no.args[:1]  # ConfigManager(cofre_do_sistema()), posicional
                achados += [f"{nome}:{no.lineno}" for valor in cofre if _e_o_cofre_real(valor)]
        self.assertEqual([], achados, "teste usando o Credential Manager real da máquina")

    def test_so_o_app_liga_o_cofre_do_sistema(self):
        for arquivo in ("willy.py", os.path.join("ui", "dashboard.py")):
            with open(os.path.join(RAIZ, arquivo), encoding="utf-8") as f:
                self.assertIn("ConfigManager(cofre=cofre_do_sistema())", f.read(), arquivo)


if __name__ == "__main__":
    unittest.main()
