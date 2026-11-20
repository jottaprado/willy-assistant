"""
Testes TDD para o porteiro Silero VAD no corte automático por silêncio (T1–T8).

Exercita o `callback_audio` real de `willy.py` com `AudioManager` real, relógio falso e
fixture de voz sintética pt-BR gerada via Windows SAPI (`tests/fixtures/fala_sapi_16k.wav`).
"""

import io
import json
import os
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import customtkinter as ctk
import numpy as np
from silero_vad_lite import SileroVAD

import core.audio_processing.dsp as dsp_mod
import core.audio_processing.vad as vad_mod
from core.audio import AudioManager
from core.audio_processing.dsp import para_taxa_whisper, reamostrar
from core.config import ConfigManager
from core.storage.profile_manager import ProfileManager
from tests.config_isolada import isolar_config
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy
from tests.willy_isolado import destruir_tk
from ui.dashboard import construir_callbacks_padrao
from ui.tabs.tab_settings import build_tab_settings

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_FIXTURE_FALA = os.path.join(RAIZ, "tests", "fixtures", "fala_sapi_16k.wav")
TAXA_STREAM = 44100
BLOCO_20MS = 882
PASSO_S = BLOCO_20MS / TAXA_STREAM  # 0.02 s


def _carregar_fala_sapi_16k() -> np.ndarray:
    with wave.open(CAMINHO_FIXTURE_FALA, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return (pcm.astype(np.float32) / 32768.0).copy()


def _ruido_c920_44k(rng: np.random.Generator, segundos: float, nivel_rms: float = 0.028) -> np.ndarray:
    """Ruído estacionário de fundo na escala da C920 (sem formantes de voz)."""
    n_amostras = round(segundos * TAXA_STREAM)
    bruto = rng.standard_normal(n_amostras).astype(np.float32)
    rms_atual = float(np.sqrt(np.mean(bruto ** 2))) or 1.0
    return (bruto * (nivel_rms / rms_atual)).astype(np.float32)


def _batida_nao_voz_44k(rng: np.random.Generator, duracao_s: float = 0.24, rms_alvo: float = 0.16) -> np.ndarray:
    """Impulso/rangido sintético de cadeira ou batida na mesa com RMS de fala e zero voz."""
    n = round(duracao_s * TAXA_STREAM)
    t = np.arange(n, dtype=np.float32) / TAXA_STREAM
    # Tom agudo + cliques de alta frequência (fora da banda de formantes vocálicos)
    portadora = np.sign(np.sin(2.0 * np.pi * 3800.0 * t)).astype(np.float32)
    ruido_hf = np.diff(rng.standard_normal(n + 1).astype(np.float32))
    bruto = 0.6 * portadora + 0.4 * ruido_hf
    rms_atual = float(np.sqrt(np.mean(bruto ** 2))) or 1.0
    return (bruto * (rms_alvo / rms_atual)).astype(np.float32)


class _ModeloSileroRoteirizado:
    """Modelo falso sem ONNX: devolve probabilidades pré-definidas a cada janela de 512 amostras."""

    window_size_samples = 512

    def __init__(self, probabilidades: list[float], padrao_apos_fim: float = 0.0):
        self._probs = [float(p) for p in probabilidades]
        self._padrao = float(padrao_apos_fim)
        self._idx = 0

    def reset(self) -> None:
        pass

    def process(self, _janela) -> float:
        if self._idx < len(self._probs):
            val = self._probs[self._idx]
            self._idx += 1
            return val
        return self._padrao


def _rodar_fluxo_callback(
    sinal_44k: np.ndarray,
    *,
    silero_vad_cfg: bool = True,
    modelo_silero="REAL",
    sil_th: float = 0.005,
    sp_th: float = 0.009,
    silence_seconds: float = 2.2,
    parar_no_primeiro_evento: bool = True,
):
    """Executa o `callback_audio` real de `willy.py` sobre `sinal_44k` em blocos de 20 ms."""
    relogio = [1000.0]
    parou_em: list[float] = []
    cancelou_em: list[float] = []
    textos_pilula: list[tuple[float, str]] = []
    traco_voz: list[tuple[float, bool, float | None]] = []

    mgr = AudioManager(sample_rate=TAXA_STREAM, channels=1)
    mgr.is_recording = True
    mgr.recording_mode = "transcribe"
    mgr.recording_start_time = relogio[0]
    mgr.no_speech_start_time = relogio[0]
    mgr.has_spoken = False
    mgr.silence_start_time = None
    mgr.is_stopping = False
    mgr._noise_tracker.reset()

    # Estado explícito do porteiro Silero (nunca depende de thread em background)
    porteiro = getattr(mgr, "porteiro_silero", None)
    if porteiro is not None:
        if modelo_silero == "REAL":
            porteiro.definir_modelo(SileroVAD(16000))
        else:
            porteiro.definir_modelo(modelo_silero)
        porteiro.reset(TAXA_STREAM)

    cfg = SimpleNamespace(
        gain_boost=1.0,
        auto_silence=True,
        silero_vad=silero_vad_cfg,
        silence_threshold=sil_th,
        speech_threshold=sp_th,
        silence_seconds=silence_seconds,
        wake_word_enabled=False,
    )

    cb = _funcao_do_willy(
        "callback_audio",
        np=np,
        time=SimpleNamespace(time=lambda: relogio[0]),
        threading=SimpleNamespace(
            Thread=lambda target, daemon=True: SimpleNamespace(start=lambda: target())
        ),
        config_mgr=cfg,
        audio_mgr=mgr,
        pill=SimpleNamespace(
            update_waveform=lambda *a: None,
            update_status_text=lambda txt, _cor: textos_pilula.append(
                (round(relogio[0] - 1000.0, 2), txt)
            ),
        ),
        safe_dispatch_ui=lambda fn, *a: fn(*a),
        FLUTUANTE_TEXTO="#fff",
        FLUTUANTE_DESTAQUE="#f00",
        FLUTUANTE_AMARELO="#ff0",
        _DITADO_LONGO_S=10.0,
        _FOLEGO_EXTRA_S=0.6,
        parar_gravacao=lambda: parou_em.append(round(relogio[0] - 1000.0, 2)),
        cancelar_gravacao=lambda: cancelou_em.append(round(relogio[0] - 1000.0, 2)),
    )

    n_blocos = len(sinal_44k) // BLOCO_20MS
    for b in range(n_blocos):
        bloco = sinal_44k[b * BLOCO_20MS : (b + 1) * BLOCO_20MS].reshape(-1, 1).astype(np.float32)
        relogio[0] = round(1000.0 + (b + 1) * PASSO_S, 4)
        cb(bloco, BLOCO_20MS, None, None)
        t_rel = round(relogio[0] - 1000.0, 2)
        sil_rel = (
            round(mgr.silence_start_time - 1000.0, 2)
            if mgr.silence_start_time is not None
            else None
        )
        traco_voz.append((t_rel, bool(mgr.has_spoken), sil_rel))
        if parar_no_primeiro_evento and (parou_em or cancelou_em):
            break

    return {
        "parou_em": parou_em,
        "cancelou_em": cancelou_em,
        "has_spoken": mgr.has_spoken,
        "traco": traco_voz,
        "mgr": mgr,
        "cfg": cfg,
    }


class TestSileroVADGate(unittest.TestCase):
    """Cobre os cenários T1 a T8 especificados para o porteiro Silero VAD."""

    @classmethod
    def setUpClass(cls):
        cls.fala_16k = _carregar_fala_sapi_16k()
        f44_bruta = reamostrar(cls.fala_16k, 16000, TAXA_STREAM)
        # Escala 0 dB de referência: pico 0,90 (como na voz normal a 0 dB antes de atenuar)
        cls.fala_44k = (f44_bruta * (0.90 / float(np.max(np.abs(f44_bruta))))).astype(np.float32)
        # Descobre onde termina a última janela de fala da fixture SAPI
        vad = SileroVAD(16000)
        probs = [
            vad.process(memoryview(np.ascontiguousarray(cls.fala_16k[i : i + 512], dtype=np.float32)))
            for i in range(0, len(cls.fala_16k) - 512 + 1, 512)
        ]
        idx_ult = max(i for i, p in enumerate(probs) if p >= 0.5)
        cls.duracao_fala_s = round((idx_ult + 1) * 0.032, 2)

    def test_t1_regressao_fala_seguida_de_batidas_altas_envia_logo_apos_a_fala(self):
        """T1: Fala seguida de batidas altas a cada ~1,5 s por 20 s.
        Sem o porteiro, só envia >= 2,2 s após a última batida.
        Com o porteiro, envia <= 2,5 s após o fim da fala.
        """
        rng = np.random.default_rng(101)
        pre_s = 1.0
        fala = self.fala_44k * 0.75
        dur_clipe_s = len(fala) / TAXA_STREAM
        fim_fala_s = pre_s + self.duracao_fala_s

        # Sinal contínuo com ruído de fundo + fala em 1,0 s + batidas a cada 1,5 s por 20 s
        sinal = _ruido_c920_44k(rng, pre_s + dur_clipe_s + 24.0, nivel_rms=0.008)
        i_fala = round(pre_s * TAXA_STREAM)
        sinal[i_fala : i_fala + len(fala)] += fala

        tempos_batidas = [fim_fala_s + 1.2 + k * 1.5 for k in range(13)]
        for t_b in tempos_batidas:
            batida = _batida_nao_voz_44k(rng, duracao_s=0.24, rms_alvo=0.16)
            i0 = round(t_b * TAXA_STREAM)
            sinal[i0 : i0 + len(batida)] += batida

        ultima_batida_fim_s = tempos_batidas[-1] + 0.24

        res_off = _rodar_fluxo_callback(sinal, silero_vad_cfg=False, modelo_silero="REAL")
        self.assertTrue(res_off["parou_em"], "Sem porteiro deveria enviar após cessarem as batidas")
        self.assertGreaterEqual(
            res_off["parou_em"][0],
            ultima_batida_fim_s + 2.2 - 0.15,
            f"Sem porteiro deveria segurar até >= 2,2 s após a última batida ({ultima_batida_fim_s:.2f}s)",
        )

        res_on = _rodar_fluxo_callback(sinal, silero_vad_cfg=True, modelo_silero="REAL")
        self.assertTrue(res_on["parou_em"], "Com porteiro deveria enviar após a fala")
        self.assertLessEqual(
            res_on["parou_em"][0],
            fim_fala_s + 2.5,
            f"Com porteiro deveria enviar <= 2,5 s após a última fala ({fim_fala_s:.2f}s), "
            f"mas enviou em {res_on['parou_em'][0]:.2f}s",
        )

    def test_t2_fala_clara_nao_corta_antes_do_gate_off(self):
        """T2: Em fala clara sobre ruído de fundo, o porteiro nunca envia antes do gate-off."""
        self.assertTrue(
            hasattr(vad_mod, "PorteiroSilero"),
            "PorteiroSilero ainda não implementado em core.audio_processing.vad",
        )
        rng = np.random.default_rng(202)
        ganho_12db = float(10.0 ** (-12.0 / 20.0))
        fala_atenuada = (self.fala_44k * ganho_12db).astype(np.float32)
        duracao_total_s = 1.5 + (len(fala_atenuada) / TAXA_STREAM) + 4.0
        fundo = _ruido_c920_44k(rng, duracao_total_s, nivel_rms=0.008)
        i_ini = int(1.5 * TAXA_STREAM)
        fundo[i_ini : i_ini + len(fala_atenuada)] += fala_atenuada

        res_off = _rodar_fluxo_callback(fundo, silero_vad_cfg=False, modelo_silero="REAL")
        res_on = _rodar_fluxo_callback(fundo, silero_vad_cfg=True, modelo_silero="REAL")

        self.assertTrue(res_off["parou_em"], "Gate-off deve detectar e enviar a fala")
        self.assertTrue(res_on["parou_em"], "Gate-on deve detectar e enviar a fala")
        self.assertGreaterEqual(
            res_on["parou_em"][0],
            res_off["parou_em"][0] - 0.05,
            f"Gate-on ({res_on['parou_em'][0]}s) cortou antes do gate-off ({res_off['parou_em'][0]}s)",
        )

    def test_r1a_limiar_janela_logo_acima_confirma_e_logo_abaixo_rejeita(self):
        """R1a: Uma janela logo acima de LIMIAR_SILERO_VOZ (0,35) confirma; logo abaixo não confirma."""
        bloco_512 = np.full(512, 0.1, dtype=np.float32)

        porteiro_acima = vad_mod.PorteiroSilero(
            sample_rate=16000,
            modelo=_ModeloSileroRoteirizado([0.36]),
        )
        self.assertTrue(
            porteiro_acima.observar_bloco(bloco_512, duracao_s=0.032),
            "Janela com probabilidade 0,36 (logo acima de 0,35) deve confirmar fala",
        )

        porteiro_abaixo = vad_mod.PorteiroSilero(
            sample_rate=16000,
            modelo=_ModeloSileroRoteirizado([0.34]),
        )
        self.assertFalse(
            porteiro_abaixo.observar_bloco(bloco_512, duracao_s=0.032),
            "Janela com probabilidade 0,34 (logo abaixo de 0,35) não deve confirmar fala",
        )

    def test_r1b_hangover_queda_mais_curta_confirma_e_mais_longa_rejeita(self):
        """R1b: Após janela confirmada, queda < HANGOVER_SILERO_S (0,60 s) confirma; queda > 0,60 s não."""
        bloco_512 = np.full(512, 0.1, dtype=np.float32)
        # Janela 0 confirmada (0,95), seguida de janelas de 32 ms abaixo do limiar (0,05)
        porteiro = vad_mod.PorteiroSilero(
            sample_rate=16000,
            modelo=_ModeloSileroRoteirizado([0.95] + [0.05] * 25),
        )
        self.assertTrue(porteiro.observar_bloco(bloco_512, duracao_s=0.032))

        # 17 janelas de 32 ms = 0,544 s (< 0,60 s): ainda dentro do hangover
        confirmado_curto = True
        for _ in range(17):
            confirmado_curto = porteiro.observar_bloco(bloco_512, duracao_s=0.032)
        self.assertTrue(
            confirmado_curto,
            "Queda de 0,544 s (< HANGOVER_SILERO_S = 0,60 s) deve continuar confirmada",
        )

        # Mais 2 janelas de 32 ms -> total 19 * 0,032 = 0,608 s (> 0,60 s): fora do hangover
        porteiro.observar_bloco(bloco_512, duracao_s=0.032)  # 18 * 0,032 = 0,576 s
        confirmado_longo = porteiro.observar_bloco(bloco_512, duracao_s=0.032)  # 19 * 0,032 = 0,608 s
        self.assertFalse(
            confirmado_longo,
            "Queda de 0,608 s (> HANGOVER_SILERO_S = 0,60 s) não deve mais confirmar",
        )

    def test_r1c_energia_alta_nao_estende_hangover_no_callback_audio(self):
        """R1c: No callback_audio real, energia alta com prob 0,0 não estende o hangover;
        envia em última_janela_confirmada + HANGOVER_SILERO_S (0,60 s) + silence_seconds (2,20 s) ± 0,10 s.
        """
        rng = np.random.default_rng(707)
        # 0,00 a 1,00 s (50 blocos = 16.000 amostras a 16 kHz = 31 janelas + 128 amostras): calibração em ruído baixo
        # 1,00 a 2,28 s (64 blocos = 20.480 amostras a 16 kHz = 40 janelas exatas, janelas 32..71): fala com prob 0,95
        # 2,28 a 9,00 s (abaixo de _DITADO_LONGO_S = 10,0 s): energia alta contínua que não para, com prob 0,0
        sinal = _ruido_c920_44k(rng, 9.0, nivel_rms=0.008)
        i_energia_alta = round(1.00 * TAXA_STREAM)
        sinal[i_energia_alta:] = 0.16

        probs_roteiro = [0.0] * 31 + [0.95] * 40
        modelo_falso = _ModeloSileroRoteirizado(probs_roteiro, padrao_apos_fim=0.0)
        res = _rodar_fluxo_callback(
            sinal,
            silero_vad_cfg=True,
            modelo_silero=modelo_falso,
            silence_seconds=2.2,
        )

        ultima_janela_s = 2.28
        esperado_s = ultima_janela_s + 0.60 + 2.20  # 5,08 s
        self.assertTrue(
            res["parou_em"],
            "Mesmo com energia alta contínua, o callback deve enviar quando o hangover + silence_seconds expira",
        )
        self.assertAlmostEqual(
            esperado_s,
            res["parou_em"][0],
            delta=0.10,
            msg=(
                f"Envio esperado em {esperado_s:.2f}s ± 0,10s "
                f"(última janela {ultima_janela_s:.2f}s + hangover 0,60s + silêncio 2,20s), "
                f"mas enviou em {res['parou_em'][0]:.2f}s"
            ),
        )

    def test_t3_fala_desde_o_primeiro_quadro_inicia_o_ditado(self):
        """T3: Fala começando já no 1º quadro (durante a calibração) ainda inicia o ditado com o porteiro."""
        self.assertTrue(
            hasattr(vad_mod, "PorteiroSilero"),
            "PorteiroSilero ainda não implementado em core.audio_processing.vad",
        )
        rng = np.random.default_rng(303)
        # Caso A: fala contínua desde o quadro 0 sobre ruído seguida de silêncio
        dur_fala = len(self.fala_44k) / TAXA_STREAM
        sinal_fala = _ruido_c920_44k(rng, dur_fala + 4.0, nivel_rms=0.008)
        sinal_fala[: len(self.fala_44k)] += self.fala_44k * 0.75
        res_fala = _rodar_fluxo_callback(sinal_fala, silero_vad_cfg=True, modelo_silero="REAL")
        self.assertTrue(res_fala["has_spoken"], "Fala desde o 1º quadro deve ligar has_spoken")
        self.assertEqual([], res_fala["cancelou_em"])
        self.assertTrue(res_fala["parou_em"], "Ditado com fala desde o 1º quadro deve enviar após a pausa")

        # Caso B: fala curta apenas durante a calibração (0,0 a 1,1 s, caminho fala_acima) seguida de 8 s de fundo
        fala_curta = (self.fala_44k[: int(1.1 * TAXA_STREAM)] * 0.75).astype(np.float32)
        sinal_curto = _ruido_c920_44k(rng, 9.1, nivel_rms=0.008)
        sinal_curto[: len(fala_curta)] += fala_curta
        res_curto = _rodar_fluxo_callback(sinal_curto, silero_vad_cfg=True, modelo_silero="REAL")
        self.assertTrue(res_curto["has_spoken"], "Fala curta na calibração (fala_acima) deve ligar has_spoken")
        self.assertEqual([], res_curto["cancelou_em"])

        # Contraste: batida não-voz durante a calibração (0,5 a 0,8 s) NÃO deve ligar has_spoken via fala_acima
        sinal_batida_cal = _ruido_c920_44k(rng, 8.0, nivel_rms=0.008)
        batida = _batida_nao_voz_44k(rng, duracao_s=0.30, rms_alvo=0.20)
        i0 = int(0.5 * TAXA_STREAM)
        sinal_batida_cal[i0 : i0 + len(batida)] += batida
        res_batida = _rodar_fluxo_callback(sinal_batida_cal, silero_vad_cfg=True, modelo_silero="REAL")
        self.assertFalse(res_batida["has_spoken"], "Batida na calibração não pode ligar has_spoken")
        self.assertEqual([7.0], res_batida["cancelou_em"])

    def test_t4_falha_no_carregamento_mantem_traco_identico_ao_gate_off(self):
        """T4: Se o modelo falhar ao carregar, o porteiro fica inativo e o traço de decisão é idêntico ao gate-off."""
        self.assertTrue(
            hasattr(vad_mod, "PorteiroSilero"),
            "PorteiroSilero ainda não implementado em core.audio_processing.vad",
        )
        buf_out = io.StringIO()
        porteiro = vad_mod.PorteiroSilero(sample_rate=TAXA_STREAM)

        def _fabrica_quebrada():
            raise OSError("DLL silero_vad_lite ausente")

        with redirect_stdout_stderr(buf_out):
            carregou = porteiro.carregar_sincrono(fabrica_modelo=_fabrica_quebrada)

        self.assertFalse(carregou)
        self.assertFalse(porteiro.ativo)
        self.assertIn("[VAD] Silero indisponível:", buf_out.getvalue())

        rng = np.random.default_rng(404)
        sinal = _ruido_c920_44k(rng, 11.0, nivel_rms=0.008)
        fala_trecho = self.fala_44k[: int(2.0 * TAXA_STREAM)] * 0.75
        i_f = int(1.0 * TAXA_STREAM)
        sinal[i_f : i_f + len(fala_trecho)] += fala_trecho
        batida = _batida_nao_voz_44k(rng, duracao_s=0.3, rms_alvo=0.16)
        i_b = int(4.2 * TAXA_STREAM)
        sinal[i_b : i_b + len(batida)] += batida

        res_loader_falho = _rodar_fluxo_callback(sinal, silero_vad_cfg=True, modelo_silero=None)
        res_gate_off = _rodar_fluxo_callback(sinal, silero_vad_cfg=False, modelo_silero="REAL")
        self.assertEqual(res_gate_off["parou_em"], res_loader_falho["parou_em"])
        self.assertEqual(res_gate_off["traco"], res_loader_falho["traco"])

    def test_t5_excecao_no_silero_no_meio_do_stream_desativa_porteiro_e_continua_energia(self):
        """T5: Se o Silero levantar exceção no meio do callback, o stream não quebra, o porteiro desliga e a regra de energia segue."""
        self.assertTrue(
            hasattr(vad_mod, "PorteiroSilero"),
            "PorteiroSilero ainda não implementado em core.audio_processing.vad",
        )

        class _SileroQueExplode:
            window_size_samples = 512

            def __init__(self):
                self.chamadas = 0

            def reset(self):
                pass

            def process(self, _data):
                self.chamadas += 1
                if self.chamadas >= 5:
                    raise RuntimeError("falha simulada no ONNX Runtime")
                return 0.95

        rng = np.random.default_rng(505)
        sinal = _ruido_c920_44k(rng, 10.0, nivel_rms=0.008)
        fala_trecho = self.fala_44k[: int(2.0 * TAXA_STREAM)] * 0.75
        i_f = int(1.0 * TAXA_STREAM)
        sinal[i_f : i_f + len(fala_trecho)] += fala_trecho
        batida = _batida_nao_voz_44k(rng, duracao_s=0.3, rms_alvo=0.16)
        i_b = int(4.2 * TAXA_STREAM)
        sinal[i_b : i_b + len(batida)] += batida

        modelo_explosivo = _SileroQueExplode()
        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf):
            res = _rodar_fluxo_callback(sinal, silero_vad_cfg=True, modelo_silero=modelo_explosivo)

        self.assertFalse(res["mgr"].porteiro_silero.ativo, "Porteiro deve desligar após exceção em process()")
        self.assertTrue(res["parou_em"], "O callback deve continuar rodando pela regra de energia até enviar")
        self.assertIn("[VAD]", err_buf.getvalue())
        # Apenas 1 log de erro na sessão, mesmo com centenas de blocos subsequentes
        self.assertEqual(1, err_buf.getvalue().count("[VAD]"))

    def test_t6_configuracao_desligada_identica_a_hoje(self):
        """T6: Com silero_vad=False, a decisão é idêntica à regra atual mesmo com o modelo carregado."""
        self.assertTrue(
            hasattr(vad_mod, "PorteiroSilero"),
            "PorteiroSilero ainda não implementado em core.audio_processing.vad",
        )
        rng = np.random.default_rng(606)
        sinal = _ruido_c920_44k(rng, 10.0, nivel_rms=0.008)
        fala_trecho = self.fala_44k[: int(2.0 * TAXA_STREAM)] * 0.75
        i_f = int(1.0 * TAXA_STREAM)
        sinal[i_f : i_f + len(fala_trecho)] += fala_trecho
        batida = _batida_nao_voz_44k(rng, duracao_s=0.3, rms_alvo=0.16)
        i_b = int(4.2 * TAXA_STREAM)
        sinal[i_b : i_b + len(batida)] += batida

        res_cfg_off = _rodar_fluxo_callback(sinal, silero_vad_cfg=False, modelo_silero="REAL")
        res_sem_modelo = _rodar_fluxo_callback(sinal, silero_vad_cfg=False, modelo_silero=None)
        self.assertEqual(res_sem_modelo["parou_em"], res_cfg_off["parou_em"])
        self.assertEqual(res_sem_modelo["traco"], res_cfg_off["traco"])

    def test_t7_reamostrador_streaming_44k_48k_16k_e_probabilidades_silero(self):
        """T7: ReamostradorStreaming em 44,1 kHz (blocos de 882 e irregulares), 48 kHz, 16 kHz e 8 kHz
        iguala para_taxa_whisper em 1e-6, e as probabilidades do Silero igualam o caminho offline em 1e-4.
        """
        self.assertTrue(
            hasattr(dsp_mod, "ReamostradorStreaming"),
            "ReamostradorStreaming ainda não implementado em core.audio_processing.dsp",
        )
        casos = (
            ("44,1k_882", 44100, 882, (882,)),
            ("48k_960", 48000, 960, (960,)),
            ("16k_320", 16000, 320, (320,)),
            ("8k_160", 8000, 160, (160,)),
            ("44,1k_irregular", 44100, 882, (1000, 37, 881, 3)),
        )
        for rotulo, taxa, multiplo_total, padrao_blocos in casos:
            with self.subTest(caso=rotulo, taxa=taxa):
                sinal_origem = reamostrar(self.fala_16k, 16000, taxa)
                n_total = (len(sinal_origem) // multiplo_total) * multiplo_total
                sinal_origem = sinal_origem[:n_total]

                fatias: list[np.ndarray] = []
                pos_fatia = 0
                idx_padrao = 0
                while pos_fatia < len(sinal_origem):
                    tam = padrao_blocos[idx_padrao % len(padrao_blocos)]
                    fatias.append(sinal_origem[pos_fatia : pos_fatia + tam])
                    pos_fatia += tam
                    idx_padrao += 1

                esperado_16k = para_taxa_whisper(sinal_origem, taxa)
                rs = dsp_mod.ReamostradorStreaming(taxa, 16000)
                partes = [rs.processar(f) for f in fatias]
                obtido_16k = np.concatenate(partes)

                self.assertLessEqual(abs(len(esperado_16k) - len(obtido_16k)), 1)
                n_comum = min(len(esperado_16k), len(obtido_16k))
                diff_amostras = float(np.max(np.abs(esperado_16k[:n_comum] - obtido_16k[:n_comum])))
                self.assertLessEqual(diff_amostras, 1e-6)

                vad_off = SileroVAD(16000)
                probs_off = np.array([
                    vad_off.process(
                        memoryview(np.ascontiguousarray(esperado_16k[i : i + 512], dtype=np.float32))
                    )
                    for i in range(0, len(esperado_16k) - 512 + 1, 512)
                ])

                vad_str = SileroVAD(16000)
                rs.reset(taxa, 16000)
                buf = np.zeros(0, dtype=np.float32)
                probs_str = []
                for f in fatias:
                    s16 = rs.processar(f)
                    if len(s16):
                        buf = np.concatenate([buf, s16])
                    while len(buf) >= 512:
                        w = np.ascontiguousarray(buf[:512], dtype=np.float32)
                        probs_str.append(vad_str.process(memoryview(w)))
                        buf = buf[512:]
                probs_str = np.array(probs_str)

                self.assertLessEqual(abs(len(probs_off) - len(probs_str)), 1)
                n_probs = min(len(probs_off), len(probs_str))
                diff_probs = float(np.max(np.abs(probs_off[:n_probs] - probs_str[:n_probs])))
                self.assertLessEqual(diff_probs, 1e-4)

    def test_t8_round_trip_configuracao_env_ui_perfil(self):
        """T8: Round-trip completo de SILERO_VAD / silero_vad (.env, UI switch, dashboard, export/import)."""
        isolar_config(self)
        cfg = ConfigManager()
        self.assertTrue(hasattr(cfg, "silero_vad"), "ConfigManager deve ter atributo silero_vad")
        self.assertTrue(cfg.silero_vad, "silero_vad deve ser True por padrão")

        # Salvar False e recarregar do .env
        cfg.save_settings({"SILERO_VAD": False})
        self.assertFalse(cfg.silero_vad)
        cfg_relido = ConfigManager()
        self.assertFalse(cfg_relido.silero_vad)

        # Exportar perfil e importar sobre instância com silero_vad=True
        with tempfile.TemporaryDirectory() as tmp:
            caminho_perfil = os.path.join(tmp, "perfil.json")
            pm = ProfileManager(cfg_relido)
            self.assertTrue(pm.export_profile(caminho_perfil))
            with open(caminho_perfil, encoding="utf-8") as f:
                dados_perfil = json.load(f)
            self.assertIs(False, dados_perfil["settings"]["SILERO_VAD"])

            cfg.save_settings({"SILERO_VAD": True})
            self.assertTrue(cfg.silero_vad)
            self.assertTrue(ProfileManager(cfg).import_profile(caminho_perfil))
            self.assertFalse(cfg.silero_vad)

        # Callbacks padrão do dashboard expõem silero_vad
        cbs_padrao = construir_callbacks_padrao(cfg, MagicMock())
        self.assertIn("silero_vad", cbs_padrao["get_settings"]())
        self.assertFalse(cbs_padrao["get_settings"]()["silero_vad"])

        # Switch na aba Ajustes
        root = ctk.CTk()
        root.withdraw()
        try:
            salvos = []
            tab = build_tab_settings(
                root,
                callbacks={
                    "get_settings": cbs_padrao["get_settings"],
                    "get_app_rules": list,
                    "on_save_settings": lambda d: salvos.append(d),
                },
            )
            self.assertTrue(hasattr(tab, "switch_silero_vad"))
            self.assertEqual(0, tab.switch_silero_vad.get())
            tab.switch_silero_vad.select()
            tab.salvar_configuracoes()
            self.assertTrue(salvos[-1]["SILERO_VAD"])
        finally:
            destruir_tk(root)


class redirect_stdout_stderr:
    def __init__(self, buf: io.StringIO):
        self.buf = buf
        self._p_out = patch("sys.stdout", buf)
        self._p_err = patch("sys.stderr", buf)

    def __enter__(self):
        self._p_out.__enter__()
        self._p_err.__enter__()
        return self.buf

    def __exit__(self, *exc):
        self._p_err.__exit__(*exc)
        self._p_out.__exit__(*exc)


if __name__ == "__main__":
    unittest.main()
