"""
Perfil importado é entrada externa.

Um arquivo de perfil pode ter sido editado à mão ou recebido de outra pessoa, e o import
aplicava tudo como veio:

- bool("false") é True: um perfil com "false" LIGAVA a opção;
- SILENCE_SECONDS "abc" levantava ValueError no meio do save_settings;
- OUTPUTS_DIR \\\\servidor\\share: o primeiro makedirs entrega o hash NTLM ao servidor;
- o file_path do histórico vai para os.startfile: um .exe no perfil rodava com um clique;
- o export gravava a chave da Groq em texto puro num arquivo feito para ser copiado;
- a UI mostrava "Perfil Restaurado ✓" com o import falho, e os atalhos não recarregavam.
"""

import ast
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.config import DEFAULT_OUTPUTS_DIR, ConfigManager, _parse_bool
from core.storage.caminhos import eh_caminho_de_rede
from tests.config_isolada import isolar_config
from tests.willy_isolado import _funcao_do_willy
from ui.tabs.tab_history import HistoryTab

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SO_WINDOWS = unittest.skipUnless(sys.platform == "win32", "regra de unidade de disco do Windows")
_EXISTS_REAL = os.path.exists


def _exists_sem_rede(caminho):
    """os.path.exists que reprova o teste se receber um caminho de rede."""
    if eh_caminho_de_rede(caminho):
        raise AssertionError(f"o código tocou num caminho de rede: {caminho!r}")
    return _EXISTS_REAL(caminho)


class _ConfigIsolada(unittest.TestCase):
    """ConfigManager real sobre arquivos temporários, com os.environ restaurado no fim."""

    def setUp(self):
        d = isolar_config(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_file = os.path.join(d, ".env")
        # Com chave no .env, o reload não sai procurando o .env do repositório.
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=gsk_chave_atual\n")
        self.saida = os.path.join(d, "Saida")
        self.cfg = ConfigManager()
        self.cfg.save_settings({"OUTPUTS_DIR": self.saida})

    def _perfil(self, dados):
        caminho = os.path.join(self.tmp.name, "perfil.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f)
        return caminho

    def _escrever_env(self, conteudo):
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write("GROQ_API_KEY=gsk_chave_atual\n" + conteudo)


class TestParseBool(unittest.TestCase):
    def test_strings_de_falso_desligam(self):
        for valor in ("false", "False", " FALSE ", "0", "no", ""):
            with self.subTest(valor=valor):
                self.assertFalse(_parse_bool(valor, True))

    def test_strings_de_verdadeiro_ligam(self):
        for valor in ("true", " True ", "1", "yes"):
            with self.subTest(valor=valor):
                self.assertTrue(_parse_bool(valor, False))

    def test_valor_irreconhecivel_mantem_o_atual(self):
        for valor in ("talvez", None, [], 2, 1.5):
            with self.subTest(valor=valor):
                self.assertTrue(_parse_bool(valor, True))
                self.assertFalse(_parse_bool(valor, False))


class TestSaveSettingsComValoresDeFora(_ConfigIsolada):
    def test_false_em_texto_desliga_a_opcao(self):
        campos = ("PRIVATE_MODE", "SAVE_AUDIO_FILES", "SILERO_VAD", "REFINE_PROMPT", "CLIPBOARD_ONLY")
        self.cfg.save_settings({c: True for c in campos})
        self.cfg.save_settings({c: "false" for c in campos})
        for attr in ("private_mode", "save_audio_files", "silero_vad", "refine_prompt", "clipboard_only"):
            self.assertIs(False, getattr(self.cfg, attr), attr)
        # E chega desligado ao disco, não só à memória.
        relido = ConfigManager()
        self.assertFalse(relido.private_mode)
        self.assertFalse(relido.save_audio_files)
        self.assertFalse(relido.silero_vad)

    def test_numero_invalido_mantem_o_atual_sem_excecao(self):
        self.cfg.save_settings({"SILENCE_SECONDS": 3.0, "MIC_GAIN": 2.0})
        for ruim in ("abc", "nan", "inf", "-inf", "1e999", 0.1, 50, True, None, [1]):
            with self.subTest(valor=ruim):
                self.cfg.save_settings({"SILENCE_SECONDS": ruim, "MIC_GAIN": ruim})
                self.assertEqual(3.0, self.cfg.silence_seconds)
                self.assertEqual(2.0, self.cfg.mic_gain)

    def test_limites_sao_inclusivos_e_texto_numerico_vale(self):
        self.cfg.save_settings({"SILENCE_SECONDS": "10", "MIC_GAIN": 0.5})
        self.assertEqual((10.0, 0.5), (self.cfg.silence_seconds, self.cfg.mic_gain))
        self.cfg.save_settings({"SILENCE_SECONDS": "0.5", "MIC_GAIN": "4.0"})
        self.assertEqual((0.5, 4.0), (self.cfg.silence_seconds, self.cfg.mic_gain))

    def test_reload_com_numero_invalido_no_env_usa_o_padrao(self):
        """float("abc") no reload derrubava o ConfigManager no boot."""
        self._escrever_env("SILENCE_SECONDS=abc\nMIC_GAIN=nan\nAUDIO_DEVICE=²\n")
        cfg = ConfigManager()
        self.assertEqual((2.2, 1.0, None), (cfg.silence_seconds, cfg.mic_gain, cfg.audio_device))

    def test_indice_de_dispositivo_gigante_nao_deixa_a_config_pela_metade(self):
        """Com mais de 4300 dígitos, int() levanta no meio do save_settings: a memória ficava
        com os atalhos do perfil e o disco sem eles, e o próximo toggle gravava a mistura."""
        perfil = {"settings": {"VOICE_HOTKEY": "ctrl+alt+q", "AUDIO_DEVICE": "9" * 5000,
                               "SYSTEM_AUDIO_DEVICE": "9" * 5000}}
        self.assertTrue(self.cfg.import_profile(self._perfil(perfil)))
        self.assertEqual((None, None), (self.cfg.audio_device, self.cfg.system_audio_device))
        self.assertEqual("ctrl+alt+q", ConfigManager().hotkey)

    def test_dispositivo_com_digito_unicode_nao_levanta(self):
        """"²".isdigit() é True e int("²") levanta ValueError no meio do save_settings."""
        self.cfg.save_settings({"AUDIO_DEVICE": "²", "SYSTEM_AUDIO_DEVICE": "3"})
        self.assertEqual((None, 3), (self.cfg.audio_device, self.cfg.system_audio_device))

    @SO_WINDOWS
    def test_outputs_dir_de_rede_relativo_ou_com_volta_e_recusado(self):
        ruins = (
            "\\\\atacante\\share\\Willy", "//atacante/share", "\\/atacante/share",
            "/\\atacante\\share", "  \\\\atacante\\share", "Willy\\relativo",
            "C:relativo", "C:\\Users\\..\\Windows", "C:\\a\x00b", "\\sem_unidade", 42,
        )
        for ruim in ruins:
            with self.subTest(valor=ruim):
                self.cfg.save_settings({"OUTPUTS_DIR": ruim})
                self.assertEqual(self.saida, self.cfg.outputs_dir)

    def test_outputs_dir_vazio_volta_ao_padrao(self):
        self.cfg.save_settings({"OUTPUTS_DIR": ""})
        self.assertEqual(DEFAULT_OUTPUTS_DIR, self.cfg.outputs_dir)

    @SO_WINDOWS
    def test_reload_recusa_caminho_de_rede_deixado_no_env(self):
        """Perfil importado antes da correção pode ter deixado o UNC gravado no .env."""
        self._escrever_env("OUTPUTS_DIR=\\\\atacante\\share\n")
        self.assertEqual(DEFAULT_OUTPUTS_DIR, ConfigManager().outputs_dir)


class TestExportSemHistorico(_ConfigIsolada):
    """As 100 últimas transcrições iam em texto puro num arquivo feito para ser copiado."""

    def _exportar(self, **kw):
        destino = os.path.join(self.tmp.name, "backup.json")
        self.assertTrue(self.cfg.export_profile(destino, **kw))
        with open(destino, encoding="utf-8") as f:
            return f.read()

    def test_export_padrao_nao_leva_o_historico(self):
        self.cfg.save_history_item("reunião com o cliente X sobre o contrato")
        bruto = self._exportar()
        self.assertNotIn("history", json.loads(bruto))
        self.assertNotIn("cliente X", bruto)

    def test_com_include_history_leva(self):
        self.cfg.save_history_item("reunião com o cliente X")
        self.assertEqual("reunião com o cliente X", json.loads(self._exportar(include_history=True))["history"][0]["text"])

    def test_restaurar_perfil_sem_historico_nao_mexe_no_historico_atual(self):
        self.cfg.save_history_item("ditado de antes")
        caminho = os.path.join(self.tmp.name, "backup.json")
        self.cfg.export_profile(caminho)
        self.cfg.save_history_item("ditado depois do export")
        self.assertTrue(self.cfg.import_profile(caminho))
        self.assertEqual(["ditado de antes", "ditado depois do export"],
                         [h["text"] for h in self.cfg.load_history()])

    def test_o_willy_passa_a_escolha_da_tela_ao_export(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        (valor,) = [v for no in ast.walk(arvore) if isinstance(no, ast.Dict)
                    for k, v in zip(no.keys, no.values)
                    if isinstance(k, ast.Constant) and k.value == "on_export_profile"]
        self.assertIsInstance(valor, ast.Lambda)
        self.assertEqual(["path", "incluir_historico"], [a.arg for a in valor.args.args])
        repassado = {kw.arg: getattr(kw.value, "id", None) for kw in valor.body.keywords}
        self.assertEqual("incluir_historico", repassado.get("include_history"))


class TestExportSemChave(_ConfigIsolada):
    def test_export_padrao_nao_leva_a_chave(self):
        destino = os.path.join(self.tmp.name, "backup.json")
        self.assertTrue(self.cfg.export_profile(destino))
        with open(destino, encoding="utf-8") as f:
            bruto = f.read()
        self.assertNotIn("GROQ_API_KEY", json.loads(bruto)["settings"])
        self.assertNotIn("gsk_chave_atual", bruto)

    def test_export_com_include_api_key_leva_a_chave(self):
        destino = os.path.join(self.tmp.name, "backup.json")
        self.assertTrue(self.cfg.export_profile(destino, include_api_key=True))
        with open(destino, encoding="utf-8") as f:
            self.assertEqual("gsk_chave_atual", json.load(f)["settings"]["GROQ_API_KEY"])

    def test_export_que_falha_no_meio_preserva_o_backup_anterior(self):
        destino = os.path.join(self.tmp.name, "backup.json")
        with open(destino, "w", encoding="utf-8") as f:
            f.write('{"backup": "anterior"}')
        with patch("json.dump", side_effect=OSError("disco cheio")):
            self.assertFalse(self.cfg.export_profile(destino))
        with open(destino, encoding="utf-8") as f:
            self.assertEqual({"backup": "anterior"}, json.load(f))
        self.assertEqual([], [n for n in os.listdir(self.tmp.name) if n.startswith(".tmp_")])


class TestImportNaoTrocaAChave(_ConfigIsolada):
    """O perfil de outra pessoa trocava a sua chave sem aviso, e as suas transcrições passavam a
    ir para a conta dela. Decisão do dono (22/10): nunca trocar uma chave já configurada."""

    def test_chave_configurada_fica_e_a_do_perfil_e_ignorada(self):
        self.assertTrue(self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "gsk_de_outra"}})))
        self.assertEqual("gsk_chave_atual", self.cfg.groq_api_key)
        with open(self.env_file, encoding="utf-8") as f:
            self.assertNotIn("gsk_de_outra", f.read())
        self.assertTrue(self.cfg.chave_do_perfil_ignorada)

    def test_sem_chave_configurada_a_do_perfil_vale(self):
        self.cfg.groq_api_key = ""
        self.assertTrue(self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "gsk_do_perfil"}})))
        self.assertEqual("gsk_do_perfil", self.cfg.groq_api_key)
        self.assertFalse(self.cfg.chave_do_perfil_ignorada)

    def test_placeholder_conta_como_sem_chave(self):
        self.cfg.groq_api_key = "sua_chave_aqui"
        self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "gsk_do_perfil"}}))
        self.assertEqual("gsk_do_perfil", self.cfg.groq_api_key)

    def test_mesma_chave_nao_gera_aviso(self):
        self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "gsk_chave_atual"}}))
        self.assertFalse(self.cfg.chave_do_perfil_ignorada)

    def test_chave_e_outras_configuracoes_no_mesmo_perfil(self):
        perfil = {"settings": {"GROQ_API_KEY": "gsk_de_outra", "VOICE_HOTKEY": "ctrl+alt+v",
                               "REFINE_PROMPT": "false"}}
        self.assertTrue(self.cfg.import_profile(self._perfil(perfil)))
        relido = ConfigManager()
        self.assertEqual(("gsk_chave_atual", "ctrl+alt+v", False),
                         (relido.groq_api_key, relido.hotkey, relido.refine_prompt))

    def test_perfil_com_placeholder_nao_gera_aviso(self):
        self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "sua_chave_aqui"}}))
        self.assertEqual("gsk_chave_atual", self.cfg.groq_api_key)
        self.assertFalse(self.cfg.chave_do_perfil_ignorada)

    def test_cofre_que_nao_leu_no_boot_ainda_conta_como_chave_configurada(self):
        """Com a leitura do cofre falhando no boot, a memória fica vazia e a chave guardada lá
        seria trocada pela do perfil."""
        cofre = MagicMock()
        cofre.get_password.return_value = "gsk_no_cofre"
        self.cfg.cofre = cofre
        self.cfg.groq_api_key = ""
        self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "gsk_de_outra"}}))
        cofre.set_password.assert_not_called()
        self.assertTrue(self.cfg.chave_do_perfil_ignorada)

    def test_import_falho_nao_deixa_aviso_velho(self):
        self.cfg.import_profile(self._perfil({"settings": {"GROQ_API_KEY": "gsk_de_outra"}}))
        self.assertTrue(self.cfg.chave_do_perfil_ignorada)
        self.assertFalse(self.cfg.import_profile(os.path.join(self.tmp.name, "nao_existe.json")))
        self.assertFalse(self.cfg.chave_do_perfil_ignorada)


class TestImportSanitizado(_ConfigIsolada):
    def test_perfil_sem_chave_ou_com_chave_vazia_nao_apaga_a_atual(self):
        for settings in ({"VOICE_HOTKEY": "ctrl+alt+v"}, {"GROQ_API_KEY": ""}, {"GROQ_API_KEY": None}):
            with self.subTest(settings=settings):
                self.assertTrue(self.cfg.import_profile(self._perfil({"settings": settings})))
                self.assertEqual("gsk_chave_atual", self.cfg.groq_api_key)

    def test_booleano_em_texto_do_perfil_e_respeitado(self):
        self.cfg.save_settings({"PRIVATE_MODE": True})
        self.assertTrue(self.cfg.import_profile(self._perfil({"settings": {"PRIVATE_MODE": "false"}})))
        self.assertFalse(self.cfg.private_mode)

    def test_historico_so_aceita_dict_com_texto(self):
        hist = ["solto", {"text": 5}, {"sem": "texto"}, None,
                {"text": "fica", "words": "muitas", "mode": ["x"], "extra": "some"}]
        self.assertTrue(self.cfg.import_profile(self._perfil({"history": hist})))
        self.assertEqual([{"text": "fica", "words": 1}], self.cfg.load_history())

    @SO_WINDOWS
    def test_caminho_de_fora_da_pasta_de_saida_e_descartado_sem_tocar_na_rede(self):
        dentro_md = os.path.join(self.saida, "Textos", "ok.md")
        dentro_wav = os.path.join(self.saida, "Atas", "ok.wav")
        hist = [
            {"text": "rede", "file_path": "\\\\atacante\\share\\x.md", "audio_path": "//atacante/s/x.wav"},
            {"text": "exe", "file_path": os.path.join(self.saida, "Textos", "x.exe")},
            {"text": "fora", "file_path": "C:\\Windows\\System32\\x.md"},
            {"text": "irma", "file_path": self.saida + "Falsa\\x.md"},
            {"text": "fluxo", "file_path": os.path.join(self.saida, "x.exe:y.md")},
            {"text": "volta", "file_path": os.path.join(self.saida, "..", "x.md")},
            {"text": "ok", "file_path": dentro_md, "audio_path": dentro_wav},
        ]
        with patch("os.path.exists", side_effect=_exists_sem_rede):
            self.assertTrue(self.cfg.import_profile(self._perfil({"history": hist})))
        por_texto = {h["text"]: h for h in self.cfg.load_history()}
        for texto in ("rede", "exe", "fora", "irma", "fluxo", "volta"):
            self.assertNotIn("file_path", por_texto[texto], texto)
            self.assertNotIn("audio_path", por_texto[texto], texto)
        self.assertEqual(dentro_md, por_texto["ok"]["file_path"])
        self.assertEqual(dentro_wav, por_texto["ok"]["audio_path"])

    @SO_WINDOWS
    def test_perfil_nao_alarga_a_regra_que_valida_o_proprio_historico(self):
        """Com OUTPUTS_DIR=C:\\ no mesmo perfil, qualquer .md da máquina passaria."""
        perfil = {"settings": {"OUTPUTS_DIR": "C:\\"},
                  "history": [{"text": "x", "file_path": "C:\\Windows\\evil.md"}]}
        self.assertTrue(self.cfg.import_profile(self._perfil(perfil)))
        self.assertEqual("C:\\", self.cfg.outputs_dir)
        self.assertNotIn("file_path", self.cfg.load_history()[0])

    def test_snippet_com_tipo_errado_nao_derruba_o_import(self):
        snippets = MagicMock()
        perfil = {"settings": {"VOICE_HOTKEY": "ctrl+alt+v"},
                  "snippets": [{"trigger": 5, "content": "x"}, "solto",
                               {"trigger": "ok", "content": "y"}]}
        self.assertTrue(self.cfg.import_profile(self._perfil(perfil), snippet_mgr=snippets))
        snippets.replace_snippets.assert_called_once_with([{"trigger": "ok", "title": "Ok", "content": "y"}])
        self.assertEqual("ctrl+alt+v", self.cfg.hotkey)


class TestAbrirArquivo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _criar(self, nome):
        caminho = os.path.join(self.tmp.name, nome)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("x")
        return caminho

    @SO_WINDOWS
    def test_recusa_o_que_nao_e_md_wav_ou_txt(self):
        for nome in ("evil.exe", "atalho.lnk", "script.bat", "pagina.html", "sem_extensao"):
            with self.subTest(nome=nome), patch("os.startfile", create=True) as startfile:
                self.assertFalse(ConfigManager.open_file(self._criar(nome)))
                startfile.assert_not_called()

    def test_recusa_caminho_de_rede_sem_tocar_no_disco(self):
        with patch("os.path.exists") as exists, patch("os.startfile", create=True) as startfile:
            self.assertFalse(ConfigManager.open_file("\\\\atacante\\share\\ata.md"))
            self.assertFalse(ConfigManager.open_file("//atacante/share/ata.md"))
        exists.assert_not_called()
        startfile.assert_not_called()

    @SO_WINDOWS
    def test_abre_md_local(self):
        caminho = self._criar("ata.md")
        with patch("os.startfile", create=True) as startfile:
            self.assertTrue(ConfigManager.open_file(caminho))
        startfile.assert_called_once_with(caminho)

    @SO_WINDOWS
    def test_aba_de_historico_sem_callback_passa_pela_mesma_porta(self):
        """O fallback da aba chamava os.startfile direto, com qualquer extensão."""
        aba = MagicMock()
        aba.callbacks = {"get_outputs_dir": lambda: ""}
        with patch("os.startfile", create=True) as startfile:
            HistoryTab._abrir_arquivo_md_card(aba, {"file_path": self._criar("evil.exe")})
        startfile.assert_not_called()

    def test_aba_de_historico_nao_toca_caminho_de_rede(self):
        aba = MagicMock()
        aba.callbacks = {"get_outputs_dir": lambda: "", "on_open_file": MagicMock()}
        with patch("os.path.exists", side_effect=_exists_sem_rede):
            HistoryTab._abrir_arquivo_md_card(aba, {"file_path": "\\\\atacante\\share\\ata.md"})
        aba.callbacks["on_open_file"].assert_not_called()
        aba._abrir_pasta_arquivos.assert_called_once()


class TestImportNaUI(unittest.TestCase):
    def _montar(self, import_ok, chave_ignorada=False):
        self.cfg = MagicMock()
        self.cfg.import_profile.return_value = import_ok
        self.cfg.chave_do_perfil_ignorada = chave_ignorada
        self.snippets = MagicMock()
        self.salvar = MagicMock()
        self.orquestrador = MagicMock()
        self.tray = MagicMock()
        self.dashboard, self.despachar = MagicMock(), MagicMock()
        return _funcao_do_willy(
            "importar_perfil", config_mgr=self.cfg, snippet_mgr=self.snippets,
            dashboard_save_settings=self.salvar, hotkey_orchestrator=self.orquestrador,
            tray_mgr=self.tray, dashboard=self.dashboard, safe_dispatch_ui=self.despachar,
        )

    def test_chave_ignorada_e_avisada_por_notificacao_do_windows(self):
        """A pílula "success" some em 900 ms e cortava o texto: o aviso vai pela bandeja."""
        self.assertIs(True, self._montar(True, chave_ignorada=True)("perfil.json"))
        self.tray.notify.assert_called_once_with(
            "Perfil restaurado", "A chave da Groq do perfil foi ignorada: a sua continua.")

    def test_sem_chave_ignorada_nao_ha_aviso(self):
        self._montar(True)("perfil.json")
        self.tray.notify.assert_not_called()

    def test_import_falho_devolve_false_e_nao_reaplica_nada(self):
        self.assertIs(False, self._montar(False)("perfil.json"))
        self.salvar.assert_not_called()
        self.orquestrador.registrar_todos.assert_not_called()

    def test_import_ok_reaplica_no_processo_e_registra_os_atalhos(self):
        self.assertIs(True, self._montar(True)("perfil.json"))
        self.cfg.import_profile.assert_called_once_with("perfil.json", snippet_mgr=self.snippets)
        self.orquestrador.registrar_todos.assert_called_once_with()
        # Achado do juiz do Bloco 5: a aba Atalhos ficava com as combinações de antes. E as
        # outras abas (Vocabulário, Templates) com o que havia antes do perfil.
        self.despachar.assert_called_once()
        self.despachar.call_args.args[0]()
        self.dashboard.recarregar_dados.assert_called_once_with(completo=True)
        aplicados = self.salvar.call_args.args[0]
        for campo in ("GROQ_LLM_MODEL", "AUDIO_DEVICE", "SYSTEM_AUDIO_DEVICE", "MIC_GAIN", "WHISPER_MODE",
                      "WAKE_WORD_ENABLED"):  # o "Ei Willy" do perfil vale na hora
            self.assertIn(campo, aplicados)

    def test_salvar_ajustes_continua_atualizando_bandeja_e_pilula(self):
        """importar_perfil chegou a ser colado no meio de dashboard_save_settings, e estas
        duas chamadas viraram código morto depois do return dele."""
        sincronizar, despachar, pill = MagicMock(), MagicMock(), MagicMock()
        pipeline = MagicMock()
        pipeline.fila.__len__.return_value = 0
        salvar = _funcao_do_willy(
            "dashboard_save_settings", config_mgr=MagicMock(), groq_service=MagicMock(),
            audio_mgr=MagicMock(), hotkey_orchestrator=None, sincronizar_bandeja=sincronizar,
            pill=pill, safe_dispatch_ui=despachar, transcription_pipeline=pipeline,
            atualizar_ui=MagicMock(),
        )
        salvar({"SILENT_MODE": True})
        sincronizar.assert_called_once_with()
        despachar.assert_called_once_with(pill.reposicionar)

    def test_nenhuma_funcao_do_willy_tem_codigo_depois_do_return(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        mortas = [f"{n.name}:{n.body[i + 1].lineno}" for n in ast.walk(arvore)
                  if isinstance(n, ast.FunctionDef)
                  for i, comando in enumerate(n.body[:-1]) if isinstance(comando, ast.Return)]
        self.assertEqual([], mortas, "código inalcançável depois de um return")

    def test_a_aba_recebe_a_funcao_e_nao_uma_lambda(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        for no in ast.walk(arvore):
            if isinstance(no, ast.Dict):
                for chave, valor in zip(no.keys, no.values):
                    if isinstance(chave, ast.Constant) and chave.value == "on_import_profile":
                        self.assertEqual("importar_perfil", getattr(valor, "id", None))
                        return
        self.fail("on_import_profile não encontrado em willy.py")


if __name__ == "__main__":
    unittest.main()
