"""
Os modelos de LLM do Willy são os que a Groq ainda serve.

Em 23/10/2026, os três modelos do Willy estavam desligados na Groq para os planos free e
developer: llama-3.1-8b-instant e llama-3.3-70b-versatile desde 16/08/2026, gemma2-9b-it desde
08/10/2025. Refino, prompt de agente, ata e transformar falhavam em todo ditado, e a config
recusava os substitutos ("gpt-oss" e "qwen" voltavam para o Llama desligado).
"""

import glob
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from dotenv import dotenv_values

from core import modelos_llm
from core.config import ConfigManager
from core.groq_service import GroqService
from tests.config_isolada import isolar_config
from tests.willy_isolado import _resposta
from ui.overlays.tray import TrayManager
from ui.tabs.tab_settings import MODELOS_NA_TELA, ROTULO_DO_PADRAO

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestModeloEmUso(unittest.TestCase):
    def test_desligados_viram_o_substituto(self):
        self.assertEqual(modelos_llm.SMART, modelos_llm.modelo_em_uso("llama-3.3-70b-versatile"))
        self.assertEqual(modelos_llm.FLASH, modelos_llm.modelo_em_uso("llama-3.1-8b-instant"))
        self.assertEqual(modelos_llm.CODER, modelos_llm.modelo_em_uso("gemma2-9b-it"))
        self.assertEqual(modelos_llm.SMART, modelos_llm.modelo_em_uso("  LLAMA-3.3-70B-Versatile "))

    def test_vazio_vira_o_padrao_e_os_atuais_ficam(self):
        self.assertEqual(modelos_llm.PADRAO, modelos_llm.modelo_em_uso(""))
        self.assertEqual(modelos_llm.PADRAO, modelos_llm.modelo_em_uso(None))
        for modelo in (modelos_llm.FLASH, modelos_llm.SMART, modelos_llm.CODER):
            self.assertEqual(modelo, modelos_llm.modelo_em_uso(modelo))
            self.assertEqual(modelo, modelos_llm.modelo_em_uso(modelo.upper()))

    def test_modelo_desconhecido_cai_para_o_padrao(self):
        # AUD-032: strings arbitrárias/inválidas no .env ou perfil devem cair para PADRAO
        for invalido in ("moonshotai/kimi-k2", "modelo-invalido-123", "gpt-4o"):
            with self.subTest(invalido=invalido):
                self.assertEqual(modelos_llm.PADRAO, modelos_llm.modelo_em_uso(invalido))

    def test_os_substitutos_nao_estao_desligados(self):
        for modelo in (modelos_llm.FLASH, modelos_llm.SMART, modelos_llm.CODER, modelos_llm.PADRAO):
            self.assertNotIn(modelo, modelos_llm.DESLIGADOS)

    def test_modelo_desconhecido_distingue_valido_desligado_e_desconhecido(self):
        for descon in ("modelo-experimental-1", "moonshotai/kimi-k2", "  gpt-4o  "):
            with self.subTest(descon=descon):
                self.assertIs(True, modelos_llm.modelo_desconhecido(descon))
        for ok in ("", "   ", None, modelos_llm.FLASH, modelos_llm.SMART.upper(), modelos_llm.CODER,
                   "llama-3.3-70b-versatile", "GEMMA2-9B-IT"):
            with self.subTest(ok=ok):
                self.assertIs(False, modelos_llm.modelo_desconhecido(ok))


class TestConfig(unittest.TestCase):
    def setUp(self):
        pasta = isolar_config(self)
        self.env = os.path.join(pasta, ".env")
        os.environ.pop("GROQ_LLM_MODEL", None)

    def _env_com(self, modelo):
        with open(self.env, "w", encoding="utf-8") as f:
            f.write(f"GROQ_API_KEY=gsk_teste\nGROQ_LLM_MODEL={modelo}\n")

    def test_env_com_modelo_desligado_passa_para_o_substituto(self):
        self._env_com("llama-3.3-70b-versatile")
        self.assertEqual(modelos_llm.SMART, ConfigManager().llm_model)
        self.assertEqual(modelos_llm.SMART, dotenv_values(self.env)["GROQ_LLM_MODEL"])

    def test_substitutos_nao_sao_mais_recusados(self):
        for modelo in (modelos_llm.FLASH, modelos_llm.SMART, modelos_llm.CODER):
            with self.subTest(modelo=modelo):
                self._env_com(modelo)
                with open(self.env, encoding="utf-8") as f:
                    antes = f.read()
                self.assertEqual(modelo, ConfigManager().llm_model)
                with open(self.env, encoding="utf-8") as f:
                    self.assertEqual(antes, f.read(), "modelo atual não pede regravar o .env")

    def test_perfil_antigo_com_modelo_desligado(self):
        cfg = ConfigManager()
        cfg.save_settings({"GROQ_LLM_MODEL": "gemma2-9b-it"})
        self.assertEqual(modelos_llm.CODER, cfg.llm_model)
        self.assertEqual(modelos_llm.CODER, dotenv_values(self.env)["GROQ_LLM_MODEL"])
        self.assertIsNone(cfg.modelo_llm_substituido)

    def test_env_com_modelo_desconhecido_registra_aviso_recreve_env_e_sobrevive_na_sessao(self):
        import io
        from contextlib import redirect_stderr

        self._env_com("modelo-fora-catalogo-99")
        err = io.StringIO()
        with redirect_stderr(err):
            cfg = ConfigManager()
        self.assertEqual(modelos_llm.SMART, cfg.llm_model)
        self.assertEqual("modelo-fora-catalogo-99", cfg.modelo_llm_substituido)
        self.assertEqual(modelos_llm.SMART, dotenv_values(self.env)["GROQ_LLM_MODEL"])
        self.assertIn("modelo-fora-catalogo-99", err.getvalue())

        # Salvar um modelo válido limpa o aviso.
        cfg.save_settings({"GROQ_LLM_MODEL": modelos_llm.FLASH})
        self.assertIsNone(cfg.modelo_llm_substituido)

        # Próxima sessão com o .env já reescrito não mostra aviso de novo.
        cfg2 = ConfigManager()
        self.assertIsNone(cfg2.modelo_llm_substituido)

    def test_import_profile_com_modelo_desconhecido_grava_smart_e_registra_aviso(self):
        import io
        import json
        from contextlib import redirect_stderr

        cfg = ConfigManager()
        with tempfile.TemporaryDirectory() as td:
            perfil = os.path.join(td, "perfil_modelo_desconhecido.json")
            with open(perfil, "w", encoding="utf-8") as f:
                json.dump({"settings": {"GROQ_LLM_MODEL": "modelo-externo-desconhecido"}}, f)
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertTrue(cfg.import_profile(perfil))
        self.assertEqual(modelos_llm.SMART, cfg.llm_model)
        self.assertEqual(modelos_llm.SMART, dotenv_values(self.env)["GROQ_LLM_MODEL"])
        self.assertEqual("modelo-externo-desconhecido", cfg.modelo_llm_substituido)
        self.assertIn("modelo-externo-desconhecido", err.getvalue())

    def test_aviso_pilula_modelo_desconhecido_trunca_em_45_chars_e_partida_chama_no_main(self):
        import ast

        from tests.willy_isolado import _arvore_do_willy, _funcao_do_willy

        formatar = _funcao_do_willy("_aviso_pilula_modelo_desconhecido")
        curto = formatar("gpt-4o")
        self.assertEqual("Modelo gpt-4o desconhecido: usando Smart", curto)
        self.assertLessEqual(len(curto), 45)

        longo = formatar("provedor/modelo-experimental-muito-longo-2026")
        self.assertLessEqual(len(longo), 45)
        self.assertIn("…", longo)
        self.assertIn("Smart", longo)

        codigo_main = ast.unparse(
            next(n for n in _arvore_do_willy().body if isinstance(n, ast.FunctionDef) and n.name == "main")
        )
        self.assertIn("modelo_llm_substituido", codigo_main)
        self.assertIn("_aviso_pilula_modelo_desconhecido", codigo_main)


class TestChamadaAoLLM(unittest.TestCase):
    def _cliente(self, conteudo="Texto polido."):
        cliente = MagicMock()
        cliente.with_options.return_value = cliente  # completar_com_reserva desliga as tentativas do SDK
        cliente.chat.completions.create.return_value = _resposta(conteudo)
        return cliente

    def test_gpt_oss_pensa_pouco_sem_devolver_o_raciocinio_e_com_margem(self):
        cliente = self._cliente()
        GroqService.completar(cliente, modelos_llm.SMART, [], temperature=0.0, max_tokens=1024, timeout=4.5)
        kwargs = cliente.chat.completions.create.call_args.kwargs
        self.assertEqual("low", kwargs["reasoning_effort"])
        self.assertIs(False, kwargs["include_reasoning"])
        self.assertEqual(1024 + modelos_llm.MARGEM_DO_RACIOCINIO, kwargs["max_tokens"])

    def test_qwen_3_nao_pensa(self):
        cliente = self._cliente()
        GroqService.completar(cliente, modelos_llm.CODER, [], temperature=0.0, max_tokens=750, timeout=4.5)
        kwargs = cliente.chat.completions.create.call_args.kwargs
        self.assertEqual("none", kwargs["reasoning_effort"])
        self.assertNotIn("include_reasoning", kwargs)  # a Groq não aceita os dois juntos com reasoning_format

    def test_modelo_comum_vai_como_antes(self):
        cliente = self._cliente()
        GroqService.completar(cliente, "moonshotai/kimi-k2", [], temperature=0.0, max_tokens=750, timeout=4.5)
        kwargs = cliente.chat.completions.create.call_args.kwargs
        self.assertEqual(750, kwargs["max_tokens"])
        self.assertNotIn("reasoning_effort", kwargs)

    def test_o_raciocinio_escrito_no_texto_nao_e_colado(self):
        for conteudo, esperado in (("<think>a pessoa quer x</think>\n\nTexto polido.", "Texto polido."),
                                   ("<THINK>pensando</THINK>Ok", "Ok"),
                                   ("<think>cortado no limite de tokens", ""),
                                   (None, "")):
            with self.subTest(conteudo=conteudo):
                cliente = self._cliente(conteudo)
                self.assertEqual(esperado, GroqService.completar(
                    cliente, modelos_llm.CODER, [], temperature=0.0, max_tokens=10, timeout=1))

    def test_refino_entrega_o_texto_sem_o_raciocinio(self):
        servico = GroqService(api_key="gsk_x", llm_model=modelos_llm.CODER)
        servico._client = self._cliente("<think>limpar o éee</think>Vamos subir o deploy.")
        self.assertEqual("Vamos subir o deploy.", servico.refine_text("éee vamos subir o deploy", estrito=True))

    def test_prompt_de_agente_so_tenta_modelos_que_existem(self):
        servico = GroqService(api_key="gsk_x", llm_model=modelos_llm.CODER)
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.side_effect = RuntimeError("model_decommissioned")
        servico._client = cliente
        servico.generate_agent_prompt("refatorar o módulo de áudio")
        tentados = [c.kwargs["model"] for c in cliente.chat.completions.create.call_args_list]
        self.assertEqual([modelos_llm.CODER, modelos_llm.SMART, modelos_llm.FLASH], tentados)

    def test_padrao_do_servico(self):
        self.assertEqual(modelos_llm.PADRAO, GroqService(api_key="").llm_model)


class TestTelaEBandeja(unittest.TestCase):
    def test_seletor_dos_ajustes(self):
        self.assertEqual({modelos_llm.FLASH, modelos_llm.SMART, modelos_llm.CODER}, set(MODELOS_NA_TELA.values()))
        self.assertEqual(modelos_llm.PADRAO, MODELOS_NA_TELA[ROTULO_DO_PADRAO])

    def test_menu_da_bandeja(self):
        escolher = MagicMock()
        tray = TrayManager({"on_set_model": escolher}, tempfile.gettempdir())
        menu = tray.build_menu(True, True, False, "centro_inferior", "ctrl+space", "ctrl+alt+space",
                               "ctrl+shift+space", "ctrl+alt+r", modelos_llm.CODER, [])

        def itens(m):
            for item in m.items:
                yield item
                if getattr(item, "submenu", None):
                    yield from itens(item.submenu)

        modelos = [i for i in itens(menu) if any(n in str(i.text) for n in ("Flash", "Smart", "Coder"))]
        self.assertEqual(3, len(modelos))
        for item in modelos:
            item(MagicMock())
        self.assertEqual([modelos_llm.FLASH, modelos_llm.SMART, modelos_llm.CODER],
                         [c.args[0] for c in escolher.call_args_list])
        marcados = [str(i.text) for i in modelos if str(i.text).startswith("●")]
        self.assertEqual(1, len(marcados))
        self.assertIn("Coder", marcados[0])


class TestNenhumModeloDesligadoNoCodigo(unittest.TestCase):
    def test_ids_desligados_so_aparecem_na_tabela_de_migracao(self):
        arquivos = [os.path.join(RAIZ, n) for n in ("willy.py", os.path.join("ui", "dashboard.py"), ".env.template")]
        for pacote in ("core", "ui"):
            arquivos += glob.glob(os.path.join(RAIZ, pacote, "**", "*.py"), recursive=True)
        tabela = os.path.join(RAIZ, "core", "modelos_llm.py")
        achados = []
        for caminho in arquivos:
            if os.path.samefile(caminho, tabela):
                continue
            with open(caminho, encoding="utf-8") as f:
                texto = f.read().lower()
            achados += [f"{os.path.relpath(caminho, RAIZ)}: {m}" for m in modelos_llm.DESLIGADOS if m in texto]
        self.assertEqual([], achados)


if __name__ == "__main__":
    unittest.main()
