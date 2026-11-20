"""
Sem microfone, o Willy diz que não está ouvindo, em vez de fingir que está.

Antes: ensure_stream engolia a falha (só stderr) e start_recording entrava em gravação sem
stream nenhum. A pílula mostrava "ouvindo", nenhum bloco de áudio chegava, e a pessoa
falava para o nada até desistir.
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from core.audio import AudioManager
from tests.willy_isolado import rodar_no_willy

CALLBACK = lambda *a: None


class TestEnsureStreamDizSeAbriu(unittest.TestCase):
    def test_falha_ao_abrir_devolve_false(self):
        mgr = AudioManager()
        with patch("core.audio.negociar_stream", side_effect=OSError("nenhum dispositivo")):
            self.assertFalse(mgr.ensure_stream(CALLBACK))
        self.assertIsNone(mgr.stream)

    def test_reabertura_que_falha_nao_deixa_o_stream_fechado_como_se_fosse_microfone(self):
        mgr = AudioManager()
        fechado = MagicMock(active=False)
        fechado.start.side_effect = OSError("device sumiu")
        mgr.stream = fechado
        with patch("core.audio.negociar_stream", side_effect=OSError("device sumiu")):
            self.assertFalse(mgr.ensure_stream(CALLBACK))
        fechado.close.assert_called_once()
        self.assertIsNone(mgr.stream)

    def test_abriu_devolve_true(self):
        mgr = AudioManager()
        with patch("core.audio.negociar_stream", return_value=(MagicMock(active=True), 16000)):
            self.assertTrue(mgr.ensure_stream(CALLBACK))

    def test_dormindo_nao_abre(self):
        mgr = AudioManager()
        mgr.is_awake = False
        with patch("core.audio.negociar_stream") as negociar:
            self.assertFalse(mgr.ensure_stream(CALLBACK))
        negociar.assert_not_called()


class TestGravacaoExigeMicrofone(unittest.TestCase):
    def test_sem_stream_nao_entra_em_gravacao(self):
        mgr = AudioManager()
        self.assertFalse(mgr.start_recording("transcribe"))
        self.assertFalse(mgr.is_recording)

    def test_stream_parado_nao_entra_em_gravacao(self):
        mgr = AudioManager()
        mgr.stream = MagicMock(active=False)
        self.assertFalse(mgr.start_recording("transcribe"))
        self.assertFalse(mgr.is_recording)

    def test_com_stream_ativo_grava(self):
        mgr = AudioManager()
        mgr.stream = MagicMock(active=True)
        self.assertTrue(mgr.start_recording("transcribe"))
        self.assertTrue(mgr.is_recording)


class TestReuniaoSoComAudioDoSistema(unittest.TestCase):
    """Achado do verificador adversarial: exigir microfone quebrou a reunião de quem está sem
    ele mas tem o áudio do sistema configurado, que antes gravava o lado de lá da chamada."""

    def _mgr(self):
        mgr = AudioManager()
        mgr.system_device_index = 3
        return mgr

    def test_sem_microfone_a_reuniao_grava_o_audio_do_sistema(self):
        mgr = self._mgr()
        callbacks = []

        def negociar(_idx, cb, *_a):
            callbacks.append(cb)
            return MagicMock(active=True), 16000

        with patch("core.audio.negociar_stream", side_effect=negociar):
            self.assertTrue(mgr.start_recording("meeting"))
        callbacks[0](np.ones((1600, 1), dtype=np.float32) * 0.1, 1600, None, None)
        audio, modo = mgr.stop_recording()
        self.assertEqual(("meeting", 1600), (modo, len(audio)))

    def test_sem_microfone_e_sem_audio_do_sistema_nao_grava(self):
        mgr = self._mgr()
        with patch("core.audio.negociar_stream", side_effect=OSError("sem loopback")):
            self.assertFalse(mgr.start_recording("meeting"))
        self.assertFalse(mgr.is_recording)

    def test_ditado_sem_microfone_continua_recusado(self):
        mgr = self._mgr()
        self.assertFalse(mgr.start_recording("transcribe"))


# O iniciar_gravacao de verdade, do willy.py, isolado num processo à parte. A negociação de
# áudio é sempre falsa: nenhum dispositivo real é aberto.
_SCRIPT = r"""
import json, sys
from unittest.mock import MagicMock
import core.audio
import willy

modo = sys.argv[2] if len(sys.argv) > 2 else "transcribe"
sistema = sys.argv[3] if len(sys.argv) > 3 else "sem_sistema"
willy.audio_mgr.system_device_index = None if sistema == "sem_sistema" else 3

def negociar(*a, **k):
    if sistema != "sistema_ok":
        raise OSError("sem dispositivo")
    return MagicMock(active=True), 16000

core.audio.negociar_stream = negociar

ui = []
willy.atualizar_ui = lambda estado, msg="": ui.append([estado, msg])
willy.sound_mgr = MagicMock()
willy.ContextManager = MagicMock()
willy.ContextManager.get_foreground_app.return_value = ("app.exe", "", None)
abre = sys.argv[1] == "abre"

def ensure_stream(cb):
    if abre:
        willy.audio_mgr.stream = MagicMock(active=True)
    return abre

willy.audio_mgr.ensure_stream = ensure_stream
willy.iniciar_gravacao(modo)
print("RESULTADO=" + json.dumps({
    "ui": ui,
    "gravando": willy.audio_mgr.is_recording,
    "som_erro": willy.sound_mgr.sound_error.called,
    "som_inicio": willy.sound_mgr.sound_start.called,
}))
"""


class TestIniciarGravacaoNoWilly(unittest.TestCase):
    def _rodar(self, microfone, modo="transcribe", sistema="sem_sistema"):
        return rodar_no_willy(_SCRIPT, microfone, modo, sistema)

    def test_sem_microfone_a_pilula_mostra_o_erro_e_nao_grava(self):
        r = self._rodar("falha")
        self.assertEqual([["error", "Microfone indisponível: confira em Ajustes"]], r["ui"])
        self.assertFalse(r["gravando"])
        self.assertTrue(r["som_erro"])
        self.assertFalse(r["som_inicio"])

    def test_reuniao_sem_microfone_com_audio_do_sistema_grava_e_avisa(self):
        r = self._rodar("falha", "meeting", "sistema_ok")
        self.assertEqual([["listening", "Sem microfone: só o áudio do sistema"]], r["ui"])
        self.assertTrue(r["gravando"])

    def test_reuniao_sem_microfone_e_sem_audio_do_sistema_mostra_o_erro(self):
        r = self._rodar("falha", "meeting", "sistema_falha")
        self.assertEqual([["error", "Sem microfone e sem áudio do sistema"]], r["ui"])
        self.assertFalse(r["gravando"])
        self.assertTrue(r["som_erro"])

    def test_com_microfone_a_pilula_diz_ouvindo(self):
        r = self._rodar("abre")
        self.assertEqual(["listening"], [estado for estado, _ in r["ui"]])
        self.assertTrue(r["gravando"])
        self.assertTrue(r["som_inicio"])
        self.assertFalse(r["som_erro"])


if __name__ == "__main__":
    unittest.main()
