"""
Recarregar os atalhos nunca deixa o Willy sem atalho, e nunca em silêncio.

Antes: trocar um atalho nos Ajustes para uma combinação que outro programa já usa fazia o
Windows recusar a nova, e a antiga já tinha sido solta. O atalho sumia. E qualquer exceção
no meio da recarga era engolida (except: pass) depois do stop() e do clear(): o app ficava
sem NENHUM atalho e sem aviso.
"""

import sys
import unittest
from types import SimpleNamespace

from core.hotkey import Win32HotKeyManager
from core.system.hotkey_orchestrator import ATALHOS, HotkeyOrchestrator

VOZ_ANTIGO, VOZ_NOVO = "ctrl+space", "ctrl+alt+x"


class GerenciadorFalso:
    """Registra como o Win32HotKeyManager: tudo no start(), recusando o que está ocupado e,
    como o Windows, a mesma combinação pedida duas vezes."""

    def __init__(self, ocupados=(), explode_no_start=False):
        self.ocupados = set(ocupados)
        self.explode_no_start = explode_no_start
        self.pendentes = []
        self.ativos = {}
        self.falhas = []

    def stop(self):
        self.ativos = {}

    def clear(self):
        self.pendentes = []

    def register(self, combo, handler):
        self.pendentes.append((combo, handler))

    def start(self):
        if self.explode_no_start:
            raise RuntimeError("thread de atalhos não subiu")
        self.falhas, self.ativos = [], {}
        for combo, handler in self.pendentes:
            if combo in self.ocupados or combo in self.ativos:
                self.falhas.append(combo)
            else:
                self.ativos[combo] = handler


class ConfigFalsa(SimpleNamespace):
    """Como o ConfigManager: save_settings põe cada campo do .env no atributo do atalho."""

    def __init__(self, **atalhos):
        super().__init__(salvos=[], **atalhos)

    def save_settings(self, dados):
        self.salvos.append(dict(dados))
        for _, atributo, campo in ATALHOS:
            if campo in dados:
                setattr(self, atributo, dados[campo])


def _config(voz, mestre="ctrl+shift+space"):
    return ConfigFalsa(hotkey=voz, master_hotkey=mestre)


class TestRecarregarAtalhos(unittest.TestCase):
    def setUp(self):
        self.avisos = []
        self.voz = lambda: "voz"
        self.mestre = lambda: "mestre"

    def _orquestrador(self, mgr, config):
        return HotkeyOrchestrator(mgr, config, {"voice": self.voz, "master": self.mestre},
                                  on_falha=lambda falhas, mantidos: self.avisos.append((falhas, mantidos)))

    def test_combinacao_nova_ocupada_mantem_a_antiga_e_avisa(self):
        mgr = GerenciadorFalso(ocupados={VOZ_NOVO})
        config = _config(VOZ_ANTIGO)
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()
        self.assertIs(self.voz, mgr.ativos[VOZ_ANTIGO])

        config.hotkey = VOZ_NOVO  # a pessoa troca nos Ajustes
        orq.recarregar_se_necessario({"VOICE_HOTKEY": VOZ_NOVO})

        self.assertIs(self.voz, mgr.ativos.get(VOZ_ANTIGO), "o atalho de voz sumiu")
        self.assertIs(self.mestre, mgr.ativos.get("ctrl+shift+space"))
        self.assertEqual([([VOZ_NOVO], {VOZ_NOVO: VOZ_ANTIGO})], self.avisos)
        # A volta vai para a config: só na memória, a partida seguinte tentava a recusada.
        self.assertEqual([{"VOICE_HOTKEY": VOZ_ANTIGO}], config.salvos)
        self.assertEqual(VOZ_ANTIGO, config.hotkey)

    def test_na_partida_seguinte_a_combinacao_que_vale_e_a_da_config(self):
        mgr = GerenciadorFalso(ocupados={VOZ_NOVO})
        config = _config(VOZ_ANTIGO)
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()
        config.hotkey = VOZ_NOVO
        orq.recarregar_se_necessario({"VOICE_HOTKEY": VOZ_NOVO})

        outra_partida = GerenciadorFalso(ocupados={VOZ_NOVO})
        self.avisos.clear()
        self._orquestrador(outra_partida, config).registrar_todos()
        self.assertIs(self.voz, outra_partida.ativos.get(VOZ_ANTIGO), "reiniciou sem o atalho de voz")
        self.assertEqual([], self.avisos)

    def test_na_partida_sem_anterior_so_avisa(self):
        mgr = GerenciadorFalso(ocupados={VOZ_ANTIGO})
        self._orquestrador(mgr, _config(VOZ_ANTIGO)).registrar_todos()
        self.assertNotIn(VOZ_ANTIGO, mgr.ativos)
        self.assertEqual([([VOZ_ANTIGO], {})], self.avisos)

    def test_trocar_para_uma_livre_nao_avisa(self):
        mgr = GerenciadorFalso()
        config = _config(VOZ_ANTIGO)
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()
        config.hotkey = VOZ_NOVO
        self.assertTrue(orq.recarregar_se_necessario({"VOICE_HOTKEY": VOZ_NOVO}))
        self.assertIs(self.voz, mgr.ativos[VOZ_NOVO])
        self.assertEqual([], self.avisos)
        self.assertEqual([], config.salvos, "troca aceita não regrava a config")

    def test_na_partida_sem_anterior_a_config_fica_como_esta(self):
        mgr = GerenciadorFalso(ocupados={VOZ_ANTIGO})
        config = _config(VOZ_ANTIGO)
        self._orquestrador(mgr, config).registrar_todos()
        self.assertEqual([], config.salvos)
        self.assertEqual(VOZ_ANTIGO, config.hotkey)

    def test_ajuste_sem_atalho_nao_recarrega(self):
        mgr = GerenciadorFalso()
        orq = self._orquestrador(mgr, _config(VOZ_ANTIGO))
        self.assertFalse(orq.recarregar_se_necessario({"OUTPUT_TONE": "formal"}))

    def test_troca_dupla_nao_liga_a_tecla_a_funcao_errada(self):
        # Achado do segundo verificador ("Restaurar Padrões", importar perfil): o mestre vai
        # de X para Z (ocupado) e a voz vai de W para X. A volta registrava o mestre em X
        # antes da voz: a tecla nova da voz passava a ligar e desligar o Willy.
        X, Z, W = "ctrl+alt+x", "ctrl+alt+z", "ctrl+alt+w"
        mgr = GerenciadorFalso(ocupados={Z})
        config = _config(W, mestre=X)
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()

        config.master_hotkey, config.hotkey = Z, X
        orq.recarregar_se_necessario({"MASTER_HOTKEY": Z, "VOICE_HOTKEY": X})

        self.assertIs(self.voz, mgr.ativos.get(X), "a tecla nova da voz tem que ser da voz")
        self.assertEqual([([Z], {})], self.avisos)
        self.assertEqual([], config.salvos, "o mestre não voltou para X: não há o que gravar")

    def test_mesma_combinacao_em_dois_atalhos_vale_o_primeiro_e_avisa_uma_vez(self):
        mgr = GerenciadorFalso()
        self._orquestrador(mgr, _config("ctrl+space", mestre="ctrl+space")).registrar_todos()
        self.assertIs(self.mestre, mgr.ativos["ctrl+space"])  # o mestre vem antes na ordem
        self.assertEqual([(["ctrl+space"], {})], self.avisos)

    def test_o_atalho_que_ficou_com_a_repetida_ainda_pode_voltar_a_ela(self):
        # Com a repetida contada como recusa dos dois, o orquestrador achava que nenhum
        # ficou ativo: na troca seguinte o mestre não tinha para onde voltar e sumia.
        mgr = GerenciadorFalso(ocupados={"ctrl+alt+z"})
        config = _config("ctrl+space", mestre="ctrl+space")
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()
        self.avisos.clear()

        config.hotkey, config.master_hotkey = "ctrl+alt+v", "ctrl+alt+z"
        orq.recarregar_se_necessario({"VOICE_HOTKEY": "ctrl+alt+v", "MASTER_HOTKEY": "ctrl+alt+z"})

        self.assertIs(self.mestre, mgr.ativos.get("ctrl+space"), "o mestre perdeu o atalho")
        self.assertEqual([(["ctrl+alt+z"], {"ctrl+alt+z": "ctrl+space"})], self.avisos)
        self.assertEqual([{"MASTER_HOTKEY": "ctrl+space"}], config.salvos)

    def test_combinacao_de_outro_atalho_fica_com_quem_ja_tinha(self):
        # Achado do juiz do Bloco 5: pelos Ajustes, dar ao mestre o Ctrl+Espaço da voz tirava a
        # tecla da voz (o mestre vem antes na ordem), e a voz não tinha para onde voltar.
        mgr = GerenciadorFalso()
        config = _config(VOZ_ANTIGO)
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()

        config.master_hotkey = VOZ_ANTIGO
        orq.recarregar_se_necessario({"MASTER_HOTKEY": VOZ_ANTIGO})

        self.assertIs(self.voz, mgr.ativos.get(VOZ_ANTIGO), "a voz perdeu o atalho")
        self.assertIs(self.mestre, mgr.ativos.get("ctrl+shift+space"), "o mestre tinha que voltar")
        self.assertEqual([{"MASTER_HOTKEY": "ctrl+shift+space"}], config.salvos)
        self.assertEqual([([VOZ_ANTIGO], {VOZ_ANTIGO: "ctrl+shift+space"})], self.avisos)

    def test_excecao_na_recarga_nao_e_engolida_em_silencio(self):
        mgr = GerenciadorFalso()
        config = _config(VOZ_ANTIGO)
        orq = self._orquestrador(mgr, config)
        orq.registrar_todos()

        mgr.explode_no_start = True
        config.hotkey = VOZ_NOVO
        orq.recarregar_se_necessario({"VOICE_HOTKEY": VOZ_NOVO})

        self.assertTrue(self.avisos, "a recarga quebrou e ninguém foi avisado")
        falhas, _ = self.avisos[-1]
        self.assertIn(VOZ_NOVO, falhas)


@unittest.skipUnless(sys.platform == "win32", "RegisterHotKey é do Windows")
class TestRecarregarAtalhosDeVerdade(unittest.TestCase):
    """Com o Win32 de verdade: outro gerenciador segura a combinação nova."""

    ANTIGO, NOVO = "ctrl+alt+shift+f10", "ctrl+alt+shift+f9"

    def test_antigo_continua_registrado_quando_o_novo_e_recusado(self):
        intruso = Win32HotKeyManager()
        intruso.register(self.NOVO, lambda: None)
        intruso.start()
        mgr = Win32HotKeyManager()
        try:
            if intruso.falhas:
                self.skipTest(f"outro programa já usa {self.NOVO} nesta máquina")
            avisos = []
            config = ConfigFalsa(hotkey=self.ANTIGO)
            orq = HotkeyOrchestrator(mgr, config, {"voice": lambda: None},
                                     on_falha=lambda f, m: avisos.append((f, m)))
            orq.registrar_todos()
            if mgr.falhas:
                self.skipTest(f"outro programa já usa {self.ANTIGO} nesta máquina")

            config.hotkey = self.NOVO
            orq.recarregar_se_necessario({"VOICE_HOTKEY": self.NOVO})

            self.assertEqual([([self.NOVO], {self.NOVO: self.ANTIGO})], avisos)
            self.assertEqual(self.ANTIGO, config.hotkey)
            prova = Win32HotKeyManager()
            prova.register(self.ANTIGO, lambda: None)
            prova.start()
            try:
                self.assertEqual([self.ANTIGO], prova.falhas, "o atalho antigo não está mais registrado")
            finally:
                prova.stop()
        finally:
            mgr.stop()
            intruso.stop()


if __name__ == "__main__":
    unittest.main()
