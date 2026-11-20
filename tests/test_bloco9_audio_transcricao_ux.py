"""
Bloco 9: o áudio que vai para o Whisper, o texto que volta dele e a experiência do ditado.

Medido nos 33 ditados do histórico do dono, com a webcam C920 (ruído em silêncio: RMS mediano
~0,032): a cauda de 2,2 s de silêncio e o clique do começo iam inteiros para o Whisper, que neles
alucinava finais de vídeo em inglês ("I got to know, guys, thanks to the channel...") ou devolvia
restos da lista de termos do prompt ("K", "Kennis, P", "Sons, Kadesh, P"); e "Willy" saía
"Weeley" e "Willi", porque não estava no vocabulário. Aqui entram só os trechos do histórico que
o pedido do Bloco 9 cita.
"""

import ast
import gc
import io
import math
import os
import queue
import random
import statistics
import sys
import tempfile
import threading
import time
import tkinter as tk
import types
import unittest
from types import SimpleNamespace
from typing import ClassVar, Optional
from unittest.mock import MagicMock, patch

import numpy as np

from core import hotkey
from core.audio import AudioManager
from core.audio_processing.diagnostico import (
    VOLUME_SATURANDO,
    nivel_acima_do_piso,
    resumo_do_teste,
)
from core.audio_processing.dsp import (
    aparar_silencio_bordas,
    condicionar_para_whisper,
    filtrar_passa_alta,
    normalizar_nivel_voz,
)
from core.audio_processing.vad import NoiseFloorTracker, PisoDeEscuta
from core.config import (
    DEV_PROMPT_CONTEXT,
    DEV_PROMPT_CONTEXT_BILINGUAL,
    DEV_PROMPT_CONTEXT_EN,
)
from core.groq_service import (
    GroqService,
    sem_vazamento_do_prompt,
    texto_limpo_da_transcricao,
)
from core.hotkey import MOD_NOREPEAT, WM_HOTKEY, WM_QUIT, Win32HotKeyManager
from core.storage.vocabulary_store import VocabularyStore
from core.text_processing import TextProcessor
from tests.test_silencio_na_c920 import (
    INICIO,
    MICROFONES,
    SIGMA_C920,
    _Cena,
    _cena,
    _Gravacao,
)
from tests.willy_isolado import _constante_do_willy, _funcao_do_willy
from ui.overlays.pill import FloatingPill
from ui.tabs import tab_diagnostics
from ui.tabs.tab_diagnostics import DiagnosticsTab
from ui.theme import (
    FLUTUANTE_CIANO,
    FLUTUANTE_LARANJA,
    FLUTUANTE_LILAS,
    FLUTUANTE_ROXO,
    FLUTUANTE_VERDE,
    FLUTUANTE_VERMELHO,
)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAXA = 16000
PISO_C920 = 0.021  # o p5 que o NoiseFloorTracker mede no ruído da C920 (mediana 0,032)


def _ruido(rng, segundos, nivel=0.032):
    return rng.normal(0, nivel, int(TAXA * segundos)).astype(np.float32)


def _fala(rng, segundos, nivel=0.12):
    """Um tom de 220 Hz modulado a 4 Hz (as sílabas) sobre o ruído da C920."""
    t = np.arange(int(TAXA * segundos)) / TAXA
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)
    voz = nivel * math.sqrt(2) * envelope * np.sin(2 * np.pi * 220 * t)
    return (voz + rng.normal(0, 0.032, len(t))).astype(np.float32)


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def _ruido_c920(rng, n_amostras, mediana=0.032):
    """O ruído da C920 como no microfone: o nível flutua de quadro a quadro (p75 / mediana = 0,038 /
    0,032), e o 5% mais alto dos quadros passa do limiar de silêncio."""
    sigma = math.log(0.038 / 0.032) / 0.6745
    fatores = np.repeat(np.exp(rng.normal(0, sigma, n_amostras // 320 + 1)), 320)[:n_amostras]
    return rng.normal(0, mediana, n_amostras) * fatores


def _palavra(rng, silabas, nivel):
    """Uma palavra: sílabas (as durações, em s) de uma vogal com harmônicos e envelope, com 30 a
    60 ms entre elas, no RMS `nivel` em cada sílaba."""
    partes = []
    for i, duracao in enumerate(silabas):
        if i:
            partes.append(np.zeros(int(TAXA * rng.uniform(0.03, 0.06))))
        t = np.arange(int(TAXA * duracao)) / TAXA
        f0 = rng.uniform(110, 240)
        onda = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3)) * np.hanning(len(t))
        partes.append(nivel * onda / _rms(onda))
    return np.concatenate(partes)


def _ganho(frequencia, **kw):
    t = np.arange(TAXA * 2) / TAXA
    x = (0.3 * np.sin(2 * np.pi * frequencia * t)).astype(np.float32)
    y = filtrar_passa_alta(x, TAXA, **kw)
    return _rms(y[TAXA:]) / _rms(x[TAXA:])


class TestPassaAlta(unittest.TestCase):
    def test_atenua_o_ronco_e_preserva_a_voz(self):
        self.assertLess(_ganho(50), 0.6)
        self.assertLess(_ganho(60), 0.65)
        self.assertLess(_ganho(20), 0.3)
        for f in (200, 1000, 3000):
            with self.subTest(f=f):
                self.assertGreater(_ganho(f), 0.9)

    def test_tira_o_dc(self):
        t = np.arange(TAXA * 2) / TAXA
        x = (0.5 + 0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        self.assertLess(abs(float(np.mean(filtrar_passa_alta(x, TAXA)[TAXA // 2:]))), 1e-3)

    def test_blocos_dao_o_mesmo_que_a_recursao_amostra_a_amostra(self):
        rng = np.random.default_rng(3)
        x = rng.normal(0, 0.1, 3000).astype(np.float64) + 0.3
        y = filtrar_passa_alta(x, TAXA)
        a = (1 / (2 * np.pi * 80)) / (1 / (2 * np.pi * 80) + 1 / TAXA)
        ref = np.zeros_like(x)
        for n in range(1, len(x)):
            ref[n] = a * (ref[n - 1] + x[n] - x[n - 1])
        np.testing.assert_allclose(y, ref, atol=1e-9)

    def test_mantem_forma_e_tipo(self):
        x = np.zeros((1600, 2), dtype=np.float32)
        y = filtrar_passa_alta(x, TAXA)
        self.assertEqual(((1600, 2), np.float32), (y.shape, y.dtype))


class TestAparoDasBordas(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(1)

    def test_tira_o_silencio_do_comeco_e_a_cauda_de_2_2_s(self):
        fala = _fala(self.rng, 2.0)
        audio = np.concatenate([_ruido(self.rng, 0.04, 0.3), _ruido(self.rng, 0.5), fala, _ruido(self.rng, 2.2)])
        saida = aparar_silencio_bordas(audio, TAXA, PISO_C920)
        # Fica a fala (0,54 a 2,54 s) com 0,15 s antes e 0,20 s depois: ~2,35 s dos 4,74.
        self.assertAlmostEqual(2.35, len(saida) / TAXA, delta=0.15)
        # O meio da fala sai intacto.
        meio = fala[TAXA // 2:TAXA]
        inicio_na_saida = round((0.54 - 0.39) * TAXA)
        trecho = saida[inicio_na_saida + TAXA // 2:inicio_na_saida + TAXA]
        self.assertGreater(np.corrcoef(trecho, meio)[0, 1], 0.99)

    def test_fade_so_onde_houve_corte(self):
        audio = np.concatenate([_ruido(self.rng, 0.6), _fala(self.rng, 1.0), _ruido(self.rng, 2.2)])
        saida = aparar_silencio_bordas(audio, TAXA, PISO_C920)
        self.assertEqual(0.0, float(saida[0]))
        self.assertLess(abs(float(saida[-1])), 0.01)
        # Fala logo no 1º quadro: o começo não é cortado nem passa por fade.
        com_fala_no_inicio = np.concatenate([_fala(self.rng, 1.0), _ruido(self.rng, 2.2)])
        saida = aparar_silencio_bordas(com_fala_no_inicio, TAXA, PISO_C920)
        np.testing.assert_array_equal(com_fala_no_inicio[:2000], saida[:2000])
        # Fala até o último quadro (o atalho solto no meio da palavra): o fim também fica inteiro.
        com_fala_no_fim = np.concatenate([_ruido(self.rng, 0.6), _fala(self.rng, 1.0)])
        saida = aparar_silencio_bordas(com_fala_no_fim, TAXA, PISO_C920)
        np.testing.assert_array_equal(com_fala_no_fim[-2000:], saida[-2000:])

    def test_clique_do_comeco_e_atenuado(self):
        clique = _ruido(self.rng, 0.04, 0.3)
        audio = np.concatenate([clique, _ruido(self.rng, 0.08), _fala(self.rng, 1.0), _ruido(self.rng, 2.2)])
        saida = aparar_silencio_bordas(audio, TAXA, PISO_C920)
        self.assertLess(_rms(saida[:len(clique)]), 0.11 * _rms(clique))

    def test_so_ruido_ou_zeros_voltam_vazios(self):
        for nome, audio in (("ruído da C920", _ruido(self.rng, 3.0)), ("zeros", np.zeros(TAXA * 3, np.float32))):
            with self.subTest(audio=nome):
                self.assertEqual(0, len(aparar_silencio_bordas(audio, TAXA, PISO_C920)))

    def test_fala_baixa_sem_voz_confirmada_volta_inteira(self):
        # Entre o silêncio (2,2x o piso) e a fala (3,3x): não dá para saber se é voz, e perder o
        # ditado custa mais que uma chamada à Groq.
        t = np.arange(TAXA) / TAXA
        baixa = (0.009 * math.sqrt(2) * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        audio = np.concatenate([_ruido(self.rng, 0.5, 0.003), baixa])
        saida = aparar_silencio_bordas(audio, TAXA, 0.003)
        np.testing.assert_array_equal(audio, saida)

    def test_sem_piso_medido_usa_o_do_proprio_audio(self):
        audio = np.concatenate([_ruido(self.rng, 1.0), _fala(self.rng, 1.0), _ruido(self.rng, 2.2)])
        self.assertAlmostEqual(1.35, len(aparar_silencio_bordas(audio, TAXA, 0.0)) / TAXA, delta=0.15)


class TestAparoComFalaDeVerdade(unittest.TestCase):
    """Fala com sílabas, pausas entre as palavras e palavras ditas mais baixo, sobre o ruído da C920
    (que flutua de quadro a quadro). O tom contínuo dos testes acima nunca tem pausa: o juiz do
    Bloco 9 mostrou, com a voz pt-BR do Windows, que o aparo cortava o "tá?" dito mais baixo depois
    de uma pausa, a 1ª sílaba de um "ok" baixo e as pontas de uma frase toda baixa."""

    FRASE = ((0.12, 0.18, 0.15), (0.2, 0.12), (0.16, 0.22, 0.1), (0.14, 0.2))
    UM_QUADRO = 320  # a ponta do envelope de uma sílaba, quase sem som

    def _cena(self, semente, partes, cauda_s=2.2):
        """partes: ("pausa", s) ou (sílabas de uma palavra, nível). Devolve o áudio e onde fica
        cada palavra, em amostras."""
        rng = np.random.default_rng(semente)
        trechos, palavras, pos = [np.zeros(int(0.6 * TAXA))], [], int(0.6 * TAXA)
        for parte, nivel in partes:
            if parte == "pausa":
                x = np.zeros(int(nivel * TAXA))
            else:
                x = _palavra(rng, parte, nivel)
                palavras.append((pos, pos + len(x)))
            trechos.append(x)
            pos += len(x)
        trechos.append(np.zeros(int(cauda_s * TAXA)))
        voz = np.concatenate(trechos)
        return (voz + _ruido_c920(rng, len(voz))).astype(np.float32), palavras

    def _frase(self, nivel=0.12):
        partes = []
        for i, silabas in enumerate(self.FRASE):
            if i:
                partes.append(("pausa", 0.06))
            partes.append((silabas, nivel))
        return partes

    def _onde_ficou(self, audio, semente, partes):
        saida = aparar_silencio_bordas(filtrar_passa_alta(audio, TAXA), TAXA, PISO_C920)
        filtrado = filtrar_passa_alta(audio, TAXA)
        meio = len(saida) // 2
        ini = next(k - meio for k in np.flatnonzero(filtrado == saida[meio])
                   if np.array_equal(filtrado[k:k + 64], saida[meio:meio + 64]))
        return ini, ini + len(saida)

    def test_palavra_baixa_depois_de_uma_pausa_fica(self):
        # "… tá?", 8 dB abaixo da frase (0,048, 1,5x o ruído da C920), 0,3 a 0,8 s depois.
        for pausa in (0.3, 0.5, 0.8):
            for semente in range(6):
                with self.subTest(pausa=pausa, semente=semente):
                    partes = self._frase() + [("pausa", pausa), ((0.14,), 0.048)]
                    audio, palavras = self._cena(semente, partes)
                    _ini, fim = self._onde_ficou(audio, semente, partes)
                    self.assertGreaterEqual(fim, palavras[-1][1] - self.UM_QUADRO)

    def test_ok_baixo_antes_da_frase_fica(self):
        for pausa in (0.3, 0.5):
            for semente in range(6):
                with self.subTest(pausa=pausa, semente=semente):
                    partes = [((0.08, 0.15), 0.076), ("pausa", pausa)] + self._frase()
                    audio, palavras = self._cena(semente, partes)
                    ini, _fim = self._onde_ficou(audio, semente, partes)
                    self.assertLessEqual(ini, palavras[0][0] + self.UM_QUADRO)

    def test_frase_toda_baixa_fica_inteira(self):
        for semente in range(6):
            with self.subTest(semente=semente):
                partes = self._frase(nivel=0.05)
                audio, palavras = self._cena(semente, partes)
                ini, fim = self._onde_ficou(audio, semente, partes)
                self.assertLessEqual(ini, palavras[0][0] + self.UM_QUADRO)
                self.assertGreaterEqual(fim, palavras[-1][1] - self.UM_QUADRO)

    def test_cauda_que_oscila_fica(self):
        # Um "s" ou um sopro no fim da última palavra, com o nível oscilando (dois quadros acima do
        # silêncio, um abaixo, por 0,6 s): a mediana de 100 ms fica acima, e a borda vai até o fim
        # dela; a ponte, que pede 60 ms seguidos, sozinha não ia.
        for semente in range(6):
            with self.subTest(semente=semente):
                partes = self._frase()
                audio, palavras = self._cena(semente, partes)
                rng = np.random.default_rng(50 + semente)
                inicio = palavras[-1][1]
                cauda = np.zeros(30 * 320, dtype=np.float64)
                t = np.arange(320) / TAXA
                for q in range(30):
                    if q % 3 != 2:
                        cauda[q * 320:(q + 1) * 320] = 0.08 * math.sqrt(2) * np.sin(2 * np.pi * rng.uniform(2000, 4000) * t)
                audio = audio.copy()
                audio[inicio:inicio + len(cauda)] += cauda.astype(np.float32)
                _ini, fim = self._onde_ficou(audio, semente, partes)
                self.assertGreaterEqual(fim, inicio + len(cauda) - 3 * self.UM_QUADRO)

    def test_a_cauda_de_silencio_continua_saindo(self):
        # A ponte pede 60 ms seguidos acima do limiar de silêncio: o ruído da C920 não a faz, e
        # dos 2,2 s de cauda ficam a margem de 0,2 s e o fim da última sílaba.
        sobras = []
        for semente in range(20):
            audio, palavras = self._cena(semente, self._frase())
            _ini, fim = self._onde_ficou(audio, semente, self._frase())
            sobras.append((fim - palavras[-1][1]) / TAXA)
        self.assertLess(max(sobras), 0.6, sobras)
        self.assertLess(sorted(sobras)[10], 0.3, sobras)

    def _clique_e_bipe(self, semente, audio):
        """O clique da tecla (40 ms) e, 10 ms depois, o bipe de início (Beep(1320, 45))."""
        rng = np.random.default_rng(100 + semente)
        audio = audio.copy()
        audio[:640] += rng.normal(0, 0.3, 640).astype(np.float32)
        t = np.arange(720) / TAXA
        audio[800:1520] += (0.2 * math.sqrt(2) * np.sin(2 * np.pi * 1320 * t)).astype(np.float32)
        return audio

    def test_clique_e_bipe_nao_viram_fala(self):
        # Juntos, mais de 100 ms acima do limiar de fala: contavam como voz, e o começo ia inteiro.
        for semente in range(6):
            with self.subTest(semente=semente):
                audio, palavras = self._cena(semente, self._frase())
                ini, _fim = self._onde_ficou(self._clique_e_bipe(semente, audio), semente, self._frase())
                self.assertGreaterEqual(ini, palavras[0][0] - int(0.16 * TAXA))

    def test_so_o_clique_e_o_bipe_volta_vazio(self):
        rng = np.random.default_rng(7)
        audio = self._clique_e_bipe(0, _ruido_c920(rng, 3 * TAXA).astype(np.float32))
        self.assertEqual(0, len(aparar_silencio_bordas(filtrar_passa_alta(audio, TAXA), TAXA, PISO_C920)))

    def test_fala_que_comeca_no_1o_quadro_continua_inteira(self):
        rng = np.random.default_rng(8)
        voz = np.concatenate([_palavra(rng, silabas, 0.12) for silabas in self.FRASE])
        audio = np.concatenate([voz, np.zeros(2 * TAXA)])
        audio = (audio + _ruido_c920(rng, len(audio))).astype(np.float32)
        filtrado = filtrar_passa_alta(audio, TAXA)
        saida = aparar_silencio_bordas(filtrado, TAXA, PISO_C920)
        np.testing.assert_array_equal(filtrado[:4000], saida[:4000])


class TestNormalizacao(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(2)

    def test_sobe_a_fala_baixa_ate_o_alvo_sem_saturar(self):
        audio = np.concatenate([_ruido(self.rng, 0.5, 0.003), _fala(self.rng, 1.0, 0.05)]) * 0.5
        saida = normalizar_nivel_voz(audio, 0.0015)
        self.assertGreater(float(np.max(np.abs(saida))), 1.9 * float(np.max(np.abs(audio))))
        self.assertLessEqual(float(np.max(np.abs(saida))), 0.70 + 1e-6)

    def test_ganho_limitado_e_ruido_com_teto(self):
        audio = np.concatenate([_ruido(self.rng, 0.3), _fala(self.rng, 1.5, 0.12)])
        saida = normalizar_nivel_voz(audio, PISO_C920)
        ganho = float(np.max(np.abs(saida))) / float(np.max(np.abs(audio)))
        self.assertLessEqual(ganho, 2.8 + 1e-6)
        self.assertLessEqual(PISO_C920 * ganho, 0.05 + 1e-6)

    def test_ruido_puro_e_audio_alto_ficam_como_estao(self):
        ruido = _ruido(self.rng, 2.0)
        self.assertIs(ruido, normalizar_nivel_voz(ruido, PISO_C920))
        alto = _fala(self.rng, 1.0, 0.6)
        self.assertIs(alto, normalizar_nivel_voz(alto, PISO_C920))

    def test_reuniao_so_passa_pelo_passa_alta(self):
        audio = np.concatenate([_ruido(self.rng, 1.0), _fala(self.rng, 1.0), _ruido(self.rng, 2.2)])
        saida = condicionar_para_whisper(audio, TAXA, PISO_C920, aparar=False)
        self.assertEqual(len(audio), len(saida))
        np.testing.assert_allclose(filtrar_passa_alta(audio, TAXA), saida)


class TestLigacaoNoWilly(unittest.TestCase):
    """willy.py não é importável em teste (instância única, Tk): a ligação é checada no AST."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        cls.funcoes = {n.name: n for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)}

    def _chamadas(self, nome):
        return [getattr(c.func, "attr", getattr(c.func, "id", "")) for c in ast.walk(self.funcoes[nome])
                if isinstance(c, ast.Call)]

    def test_condiciona_antes_do_wav_e_cancela_sem_fala(self):
        nomes = self._chamadas("processar_transcricao")
        self.assertLess(nomes.index("para_taxa_whisper"), nomes.index("condicionar_para_whisper"))
        self.assertLess(nomes.index("condicionar_para_whisper"), nomes.index("convert_to_wav"))
        self.assertGreaterEqual(nomes.count("atualizar_ui"), 2)  # < 0,3 s antes e depois de aparar

    def test_piso_lido_no_parar_e_na_escala_do_ganho(self):
        lidos = {getattr(n, "attr", None) for n in ast.walk(self.funcoes["parar_gravacao"])}
        self.assertTrue({"ambient_noise_floor", "gain_boost"} <= lidos)


def _servico(resposta):
    servico = GroqService(api_key="gsk_teste")
    cliente = MagicMock()
    cliente.audio.transcriptions.create.return_value = resposta
    servico._client = cliente
    return servico, cliente


def _seg(texto, sem_fala=0.05, logprob=-0.2, compressao=1.2):
    return {"text": texto, "no_speech_prob": sem_fala, "avg_logprob": logprob, "compression_ratio": compressao}


def _verbose(*segmentos):
    return SimpleNamespace(text="".join(s["text"] for s in segmentos), model_extra={"segments": list(segmentos)})


class TestAntiAlucinacao(unittest.TestCase):
    def test_pede_verbose_json(self):
        servico, cliente = _servico(_verbose(_seg(" Bom dia.")))
        self.assertEqual("Bom dia.", servico.transcribe(io.BytesIO(b"RIFF"), "ctx"))
        self.assertEqual("verbose_json", cliente.audio.transcriptions.create.call_args.kwargs["response_format"])

    def test_segmentos_de_nao_fala_saem(self):
        resposta = _verbose(_seg(" Bom dia,"), _seg(" pessoal.", 0.7, -0.9), _seg(" Tudo bem?"),
                            _seg(" Hmm.", 0.9, -0.3), _seg(" Até logo."))
        self.assertEqual("Bom dia, Tudo bem? Até logo.", _servico(resposta)[0].transcribe(io.BytesIO(b"x"), ""))

    def test_repeticao_com_compressao_alta_sai(self):
        resposta = _verbose(_seg(" Vamos lá."), _seg(" Obrigado. Obrigado. Obrigado.", compressao=2.6),
                            _seg(" Texto longo sem repetição de frase nenhuma aqui.", compressao=2.5))
        self.assertEqual("Vamos lá. Texto longo sem repetição de frase nenhuma aqui.",
                         _servico(resposta)[0].transcribe(io.BytesIO(b"x"), ""))

    def test_cauda_de_legenda_em_ingles_sai(self):
        # O ditado #31: depois da fala, o Whisper inventou um final de vídeo em inglês.
        resposta = _verbose(_seg(" Como foram resolvidos, qual era o problema?"),
                            _seg(" I got to know, guys, thanks to the channel.", 0.30, -0.5),
                            _seg(" That's the exact same thing you want, guys.", 0.45, -0.7))
        self.assertEqual("Como foram resolvidos, qual era o problema?",
                         _servico(resposta)[0].transcribe(io.BytesIO(b"x"), ""))

    def test_legenda_dita_com_confianca_no_meio_nao_leva_a_fala_de_depois(self):
        resposta = _verbose(_seg(" Bom dia."), _seg(" Thanks for watching the demo, now step two."),
                            _seg(" Agora o passo dois."), _seg(" Subtitles by Amara.org", 0.5, -0.9))
        self.assertEqual("Bom dia. Thanks for watching the demo, now step two. Agora o passo dois.",
                         _servico(resposta)[0].transcribe(io.BytesIO(b"x"), ""))

    def test_frase_confiante_no_fim_fica(self):
        resposta = _verbose(_seg(" Primeiro ponto."), _seg(" Thanks to everyone for the help."))
        self.assertEqual("Primeiro ponto. Thanks to everyone for the help.",
                         _servico(resposta)[0].transcribe(io.BytesIO(b"x"), ""))

    def test_vazamentos_do_prompt_saem(self):
        # Os ditados #1, #5, #11, #13 e #23.
        for bruto, limpo in (("K", ""), ("Kennis, P", ""), ("Sons, Kadesh, P", ""),
                             ("Você consegue me ajudar a fazer esse estudo? K", "Você consegue me ajudar a fazer esse estudo?"),
                             ("Feito. and Ritmuss, Kubernetes, P", "Feito.")):
            with self.subTest(bruto=bruto):
                self.assertEqual(limpo, sem_vazamento_do_prompt(bruto))
                self.assertEqual(limpo, _servico(_verbose(_seg(" " + bruto)))[0].transcribe(io.BytesIO(b"x"), ""))

    def test_letra_no_fim_de_frase_normal_fica(self):
        for texto in ("Vamos de plano B", "Tomei vitamina C", "Escolha a opção A.", "Uso Node.js e K8s"):
            with self.subTest(texto=texto):
                self.assertEqual(texto, sem_vazamento_do_prompt(texto))

    def test_inicial_e_letra_pontuadas_ficam(self):
        # Achados do juiz do Bloco 9: com o "\.?" da regra, o ditado inteiro "Valeu, P." sumia. O
        # vazamento é a lista do prompt cortada no meio de um termo, e vem sem ponto.
        for texto in ("Valeu, P.", "Segue o relatório. Atenciosamente, J.", "Abraço, M.",
                      "Qual é a alternativa certa? B.", "Hoje eu uso Python, Java, C."):
            with self.subTest(texto=texto):
                self.assertEqual(texto, sem_vazamento_do_prompt(texto))
                self.assertEqual(texto, texto_limpo_da_transcricao(SimpleNamespace(text=texto)))
                self.assertEqual(texto, _servico(_verbose(_seg(" " + texto)))[0].transcribe(io.BytesIO(b"x"), ""))

    def test_final_de_video_em_segmento_fraco_sai(self):
        # A âncora no fim do segmento deixava estes passar (juiz do Bloco 9, 2ª rodada); o #31 do
        # histórico, com a continuação, é o terceiro. (Num segmento confiante, só sai a frase de
        # vídeo que o termina: ver test_frase_com_palavra_de_legenda_fica.)
        for cauda in ("Thanks for watching and see you next time!", "Thanks for watching, don't forget to subscribe!",
                      "I got to know, guys, thanks to the channel and see you in the next one.",
                      "Obrigado por assistir e até o próximo vídeo!", "Inscreva-se no canal e ative o sininho!",
                      "Thank you so much for watching!", "Não se esqueça de se inscrever no canal!"):
            with self.subTest(cauda=cauda):
                fraca = _verbose(_seg(" Vamos revisar o PR."), _seg(" " + cauda, 0.5, -0.7))
                self.assertEqual("Vamos revisar o PR.", _servico(fraca)[0].transcribe(io.BytesIO(b"x"), ""))

    def test_frase_com_palavra_de_legenda_fica(self):
        for texto in ("Please sort the subtitles by language.", "Captions by default should be off.",
                      "Thanks for watching the demo, now step two.", "Vou assinar: subscribe na newsletter."):
            with self.subTest(texto=texto):
                self.assertEqual(texto, _servico(_verbose(_seg(" Bom dia."), _seg(" " + texto)))[0]
                                 .transcribe(io.BytesIO(b"x"), "").replace("Bom dia. ", ""))
                self.assertEqual(texto, texto_limpo_da_transcricao(SimpleNamespace(text=texto)))

    def test_traducao_tambem_passa_pelo_filtro(self):
        # Em inglês é que o Whisper mais inventa o final de vídeo.
        servico, cliente = _servico(None)
        cliente.audio.translations.create.return_value = _verbose(
            _seg(" Let's ship it today."), _seg(" Thanks for watching!", 0.5, -0.9), _seg(" K"))
        self.assertEqual("Let's ship it today.", servico.translate(io.BytesIO(b"x"), "ctx"))
        self.assertEqual("verbose_json", cliente.audio.translations.create.call_args.kwargs["response_format"])

    def test_resposta_sem_segmentos_continua_valendo(self):
        # O json simples (ou um mock só com .text): sem segmentos, a cauda de legenda sai pela frase.
        for resposta, esperado in ((SimpleNamespace(text=" Bom dia. "), "Bom dia."),
                                   (MagicMock(text="Tudo certo. Thanks for watching!"), "Tudo certo."),
                                   (_verbose(), "")):
            with self.subTest(esperado=esperado):
                self.assertEqual(esperado, texto_limpo_da_transcricao(resposta))

    def test_arquivo_pequeno_tambem_passa_pelo_filtro(self):
        servico, cliente = _servico(_verbose(_seg(" Reunião ok."), _seg(" Legendas pela comunidade Amara.org")))
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "a.wav")
            with open(caminho, "wb") as f:
                f.write(b"RIFF")
            self.assertEqual("Reunião ok.", servico.transcribe_file(caminho, "ctx"))
        self.assertEqual("verbose_json", cliente.audio.transcriptions.create.call_args.kwargs["response_format"])

    def test_blocos_de_reuniao_tambem(self):
        servico, _ = _servico(_verbose(_seg(" Bloco."), _seg(" Subtitles by the community")))
        self.assertEqual("Bloco.\n\nBloco.", servico.transcribe_chunks([io.BytesIO(b"a"), io.BytesIO(b"b")], "ctx"))


class TestNomeDoWilly(unittest.TestCase):
    def test_grafias_do_whisper_viram_willy(self):
        # Os ditados #20 e #33.
        self.assertEqual("o problema aqui no Willy é", TextProcessor.normalizar_nome_do_willy("o problema aqui no Weeley é"))
        self.assertEqual("às vezes o Willy está", TextProcessor.normalizar_nome_do_willy("às vezes o Willi está"))
        self.assertEqual("Willy, resuma", TextProcessor.normalizar_nome_do_willy("Uili, resuma"))

    def test_outras_palavras_ficam(self):
        for texto in ("A editora Wiley", "Wylie Coyote", "o Willian chegou", "willing to help"):
            with self.subTest(texto=texto):
                self.assertEqual(texto, TextProcessor.normalizar_nome_do_willy(texto))

    def test_transcricao_sai_com_o_nome_certo(self):
        servico, _ = _servico(_verbose(_seg(" Outra coisa aqui no Weeley.")))
        self.assertEqual("Outra coisa aqui no Willy.", servico.transcribe(io.BytesIO(b"x"), ""))


class TestVocabulario(unittest.TestCase):
    def setUp(self):
        self.store = VocabularyStore(lambda: "nao-existe.txt", lambda: "nao-existe.json")

    def test_willy_no_vocabulario_base(self):
        for base in (DEV_PROMPT_CONTEXT, DEV_PROMPT_CONTEXT_BILINGUAL, DEV_PROMPT_CONTEXT_EN):
            self.assertIn("Willy", base)
        with open(os.path.join(RAIZ, "vocabulario.txt"), encoding="utf-8") as f:
            self.assertIn("Willy", [linha.strip() for linha in f])
        # E no começo da lista: o corte do orçamento tira o fim.
        self.assertIn("Willy", self.store.build_prompt_context(DEV_PROMPT_CONTEXT, ["X" * 700], {}, 850))

    def test_vocabulario_padrao_vazio_depois_do_comentario_personalizado(self):
        marcador = "# Adicione seus termos e nomes personalizados aqui embaixo:"
        with open(os.path.join(RAIZ, "vocabulario.txt"), encoding="utf-8") as f:
            conteudo = f.read()
        self.assertIn(marcador, conteudo)
        self.assertEqual("", conteudo.split(marcador, 1)[1].strip())

    def test_cabecalho_bilingue_em_portugues(self):
        self.assertIn("Vocabulário bilíngue", DEV_PROMPT_CONTEXT_BILINGUAL)
        self.assertNotIn("Bilingual", DEV_PROMPT_CONTEXT_BILINGUAL)

    def test_termos_da_pessoa_nunca_sao_cortados(self):
        base = "Vocabulário: " + ", ".join(f"Generico{i}" for i in range(150))
        termos = [f"Meu{i}" for i in range(40)] + ["Generico3"]
        ctx = self.store.build_prompt_context(base, termos, {"api": "FastAPI"}, max_prompt_len=300)
        self.assertLessEqual(len(ctx), 300)
        for termo in termos + ["FastAPI"]:
            self.assertIn(termo, ctx)
        self.assertNotIn("Generico149", ctx)  # quem encolhe é o fim da base

    def test_willy_fica_com_o_vocabulario_da_pessoa_cheio(self):
        # Com 40 termos ou mais da pessoa, a base saía inteira, e o "Willy" ia junto; quem já tinha
        # o Willy instalado não o tem no vocabulario.txt (achado do juiz do Bloco 9).
        with tempfile.TemporaryDirectory() as pasta:
            vocab = os.path.join(pasta, "vocabulario.txt")
            with open(vocab, "w", encoding="utf-8") as f:
                f.write(", ".join(f"TermoDaPessoa{i}" for i in range(60)))
            arquivos = {"VOCAB_FILE": vocab, "ENV_FILE": os.path.join(pasta, ".env"),
                        "HISTORY_FILE": os.path.join(pasta, ".history.json"),
                        "REPLACEMENTS_FILE": os.path.join(pasta, ".replacements.json")}
            with patch.multiple("core.config", **arquivos), patch.dict(os.environ, {"INPUT_LANGUAGE": "pt"}):
                from core.config import ConfigManager
                contexto = ConfigManager().get_prompt_context()
        self.assertIn("Willy", contexto)
        self.assertIn("TermoDaPessoa0", contexto)
        self.assertEqual(1, contexto.count("Willy"))

    def test_termo_que_a_base_tem_nao_se_repete(self):
        ctx = self.store.build_prompt_context("Base: Python, Docker", ["docker", "Rust"], {}, max_prompt_len=850)
        self.assertEqual(1, ctx.lower().count("docker"))
        self.assertIn("Rust", ctx)


class TestIsolamentoDoIdioma(unittest.TestCase):
    def test_tom_e_idioma_antes_do_config_passa(self):
        # O save_settings do test_tone_and_language deixava INPUT_LANGUAGE=en no os.environ, e o
        # test_vocab_operations do test_config falhava quando rodava depois dele.
        # Num processo à parte: no mesmo, os testes do test_config deixariam o ambiente deste sujo
        # para o test_config de verdade, que roda depois.
        from tests.test_config import TestConfigManager
        from tests.test_tone_and_language import TestToneAndLanguage

        suite = unittest.TestSuite([
            TestToneAndLanguage("test_config_save_and_reload"),
            TestConfigManager("test_vocab_operations"),
        ])
        resultado = unittest.TestResult()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INPUT_LANGUAGE", None)
            suite.run(resultado)
            self.assertIsNone(os.environ.get("INPUT_LANGUAGE"))
        self.assertEqual([], resultado.failures)
        self.assertEqual([], resultado.errors)






# ---------------------------------------------------------------------------------------------
# Fase 2: a experiência do ditado na C920
# ---------------------------------------------------------------------------------------------


def _ruido_da_c920(n, semente=9):
    rng = random.Random(semente)
    return [0.032 * math.exp(rng.gauss(0, SIGMA_C920)) for _ in range(n)]


def _fala_lognormal(n, mediana=0.12, ruido=0.032, semente=5):
    """O nível de n quadros de fala (sobe e desce a cada sílaba) somado ao ruído do microfone."""
    rng = random.Random(semente)
    return [math.sqrt((mediana * math.exp(rng.gauss(0, 0.5))) ** 2 + ruido ** 2) for _ in range(n)]


class TestPilulaNaC920(unittest.TestCase):
    """As barras da pílula descontam o piso de ruído: na C920, em silêncio, ficavam altas e
    vermelhas (vermelho a partir de 0,0113, e (volume - 0,005) / 0,035 enchia a barra com 0,032)."""

    MODOS: ClassVar[dict] = {"transcribe": FLUTUANTE_CIANO, "send": FLUTUANTE_VERDE, "prompt": FLUTUANTE_ROXO,
             "translate": FLUTUANTE_LILAS, "meeting": FLUTUANTE_LARANJA}

    def test_silencio_da_c920_deixa_as_barras_no_minimo(self):
        alturas = sorted(FloatingPill.altura_das_barras(v, PISO_C920) for v in _ruido_da_c920(3000))
        self.assertEqual(0.0, alturas[len(alturas) // 2])
        self.assertLess(alturas[int(0.99 * len(alturas))], 0.1)

    def test_voz_sobe_as_barras_e_a_voz_alta_enche(self):
        self.assertTrue(0.3 < FloatingPill.altura_das_barras(0.12, PISO_C920) < 0.6)
        self.assertEqual(1.0, FloatingPill.altura_das_barras(0.30, PISO_C920))

    def test_sem_piso_medido_fica_a_conta_de_antes(self):
        # Microfone quieto, ou o começo da gravação: a escala de sempre.
        for volume in (0.0, 0.004, 0.01, 0.02, 0.04, 0.1):
            with self.subTest(volume=volume):
                self.assertAlmostEqual(min(1.0, max(0.0, (volume - 0.005) / 0.035)),
                                       FloatingPill.altura_das_barras(volume, 0.0))

    def test_cor_do_modo_e_vermelho_so_perto_de_saturar(self):
        self.assertEqual(0.35, VOLUME_SATURANDO)
        for modo, cor in self.MODOS.items():
            with self.subTest(modo=modo):
                for volume in (0.032, 0.12, 0.30, 0.35):
                    self.assertEqual(cor, FloatingPill.cor_das_barras(volume, modo))
                self.assertEqual(FLUTUANTE_VERMELHO, FloatingPill.cor_das_barras(0.36, modo))

    def test_desenha_as_4_barras_no_minimo_na_cor_do_modo(self):
        canvas = MagicMock()
        pilula = SimpleNamespace(last_anim_time=0.0, bar_x=[10, 20, 30, 40], bars=[1, 2, 3, 4], canvas=canvas,
                                 altura_das_barras=FloatingPill.altura_das_barras,
                                 cor_das_barras=FloatingPill.cor_das_barras)
        FloatingPill.update_waveform(pilula, 0.032, True, "send", PISO_C920)
        self.assertEqual(4, canvas.coords.call_count)
        for chamada in canvas.coords.call_args_list:
            _, _, topo, _, base = chamada.args
            self.assertAlmostEqual(4.0, base - topo)
        self.assertEqual([FLUTUANTE_VERDE] * 4, [c.kwargs["fill"] for c in canvas.itemconfig.call_args_list])

    def test_callback_manda_o_piso_para_a_pilula(self):
        gravacao = _GravacaoComPilula(0.02, modo="send")
        for volume in _ruido_da_c920(150):
            gravacao.quadro(volume)
        self.assertTrue(gravacao.barras)
        _volume, gravando, modo, piso = gravacao.barras[-1]
        self.assertTrue(gravando)
        self.assertEqual("send", modo)
        self.assertTrue(0.015 < piso < 0.03, piso)  # o piso medido da C920, não 0


class TestPilulaCancelada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _texto(self, msg):
        pilula = FloatingPill(self.root)
        self.addCleanup(pilula.destroy)
        pilula.root.deiconify = MagicMock()
        pilula.show_state("cancelled", msg)
        return pilula.canvas.itemcget(pilula.text, "text")

    def test_esc_diz_que_cancelou(self):
        self.assertEqual("Ditado cancelado (Esc)", self._texto("Ditado cancelado (Esc)"))

    def test_sem_mensagem_continua_o_de_sempre(self):
        self.assertEqual("Willy não ouviu nada", self._texto(""))


class _GravacaoComPilula:
    """O callback_audio do willy.py com uma pílula falsa: guarda as barras e as mensagens."""

    def __init__(self, dt, modo="transcribe"):
        self.dt, self.agora, self.disparou = dt, INICIO, None
        self.barras, self.mensagens = [], []
        self.audio = AudioManager()
        self.audio.stream = MagicMock(active=True)
        self.audio.actual_sample_rate = TAXA
        self.audio.start_recording(modo)
        self.audio.no_speech_start_time = self.audio.recording_start_time = INICIO
        config = SimpleNamespace(wake_word_enabled=False, auto_silence=True, silero_vad=False,
                                 speech_threshold=0.009, silence_threshold=0.005, silence_seconds=2.2)
        threading_falso = SimpleNamespace(Thread=lambda target, daemon=None: SimpleNamespace(
            start=lambda: setattr(self, "disparou", (target, self.agora))))

        def despachar(funcao, *args):
            if funcao == "barras":
                self.barras.append(args)
            else:
                self.mensagens.append((self.agora, args[0]))

        self.callback = _funcao_do_willy(
            "callback_audio", audio_mgr=self.audio, config_mgr=config,
            pill=SimpleNamespace(update_waveform="barras", update_status_text="status"), safe_dispatch_ui=despachar,
            time=SimpleNamespace(time=lambda: self.agora), threading=threading_falso,
            parar_gravacao="parou", cancelar_gravacao="cancelou", FLUTUANTE_TEXTO="", FLUTUANTE_AMARELO="",
            _DITADO_LONGO_S=_constante_do_willy("_DITADO_LONGO_S"), _FOLEGO_EXTRA_S=_constante_do_willy("_FOLEGO_EXTRA_S"))

    def quadro(self, volume):
        self.agora += self.dt
        n = max(1, round(self.dt * TAXA))
        self.callback(np.full((n, 1), volume, dtype=np.float32), n, None, None)

    def rodar(self, cena, total_s):
        for volume, _fim in cena.quadros(self.dt, total_s):
            self.quadro(volume)
            if self.disparou:
                break
        return self.disparou


class TestFolegoNoDitadoLongo(unittest.TestCase):
    """Depois de 10 s de gravação, o corte por silêncio espera 0,6 s a mais: quem pensa entre um
    parágrafo e outro pausa mais que 2,2 s, e o ditado era enviado no meio do raciocínio."""

    def test_constantes_do_pedido(self):
        self.assertEqual(10.0, _constante_do_willy("_DITADO_LONGO_S"))
        self.assertEqual(0.6, _constante_do_willy("_FOLEGO_EXTRA_S"))

    def _depois_da_ultima_palavra(self, segundos_de_fala, semente):
        cena = _cena({"x": lambda c: c.falar(0.4, segundos_de_fala)}, "x", "c920", semente)
        gravacao = _GravacaoComPilula(0.02)
        alvo, quando = gravacao.rodar(cena, segundos_de_fala + 8)
        self.assertEqual("parou", alvo)
        contagem = [float(m.split("em ")[1].rstrip("s")) for _, m in gravacao.mensagens if m.startswith("Pausa...")]
        return quando - INICIO - max(fim for _, fim in cena.palavras), contagem

    def test_ditado_curto_para_em_2_2_s(self):
        for semente in range(3):
            with self.subTest(semente=semente):
                atraso, contagem = self._depois_da_ultima_palavra(4.0, semente)
                self.assertTrue(2.2 <= atraso < 2.8, atraso)
                self.assertLessEqual(max(contagem), 1.0)  # 2,2 - 1,2 s

    def test_ditado_longo_espera_2_8_s_e_a_contagem_mostra(self):
        for semente in range(3):
            with self.subTest(semente=semente):
                atraso, contagem = self._depois_da_ultima_palavra(12.0, semente)
                self.assertTrue(2.8 <= atraso < 3.4, atraso)
                self.assertAlmostEqual(1.6, max(contagem), delta=0.05)  # 2,8 - 1,2 s


class _CenaContinua(_Cena):
    def falar_sem_pausa(self, t0, segundos, palavra=(1.0, 3.0), pausa=(0.0, 0.02)):
        """Frases longas quase sem pausa: o caso que o juiz do 7A cortava em 8 de 30."""
        t = t0
        while t < t0 + segundos:
            d = min(self.rng.uniform(*palavra), t0 + segundos - t)
            self.som(t, d, lambda rng: self.mediana_fala * math.exp(rng.gauss(0, 0.5)), fala=True)
            t += d + self.rng.uniform(*pausa)
        return t


def _cena_continua(semente, montar, microfone="c920"):
    ruido, mediana = MICROFONES[microfone]
    cena = _CenaContinua(random.Random(f"bloco9-{semente}"), ruido, mediana)
    montar(cena)
    return cena


class TestPisoNaFalaContinua(unittest.TestCase):
    """A fala fora da janela do piso: na fala contínua de 30 s, o p5 entrava nela, o limiar de
    silêncio passava a fala, e o ditado era cortado no meio. O ruído de verdade continua mudando
    o piso: o ventilador que liga, o ruído que sobe, a música que não para."""

    def _rodar(self, cena, total_s, dt=0.02):
        disparou, _ = _Gravacao(dt).rodar(cena, total_s=total_s)
        return disparou

    def test_30_s_de_fala_continua_nao_sao_cortados(self):
        cortes = []
        for semente in range(30):
            cena = _cena_continua(semente, lambda c: c.falar_sem_pausa(0.3, 30.0))
            disparou = self._rodar(cena, 40.0)
            ultima = INICIO + max(fim for _, fim in cena.palavras)
            if disparou is None or disparou[0] != "parou" or disparou[1] < ultima:
                cortes.append((semente, disparou))
            else:
                self.assertLessEqual(disparou[1], ultima + 2.8 + 1.0)
        self.assertEqual([], cortes)

    def test_fala_logo_no_comeco_nao_arrasta_o_piso(self):
        # As 8 sementes de 230 em que o juiz do Bloco 9 achou o corte: com poucos quadros de ruído
        # antes da fala, o piso saía alto (0,032, e não 0,021), as quedas da fala abaixo de 3,3x
        # entravam, subiam o piso, que subia o limiar, até o ditado ser cortado.
        for semente in (114, 115, 118, 137, 142, 219, 221, 227):
            with self.subTest(semente=semente):
                cena = _cena_continua(semente, lambda c: c.falar_sem_pausa(0.3, 30.0))
                alvo, quando = self._rodar(cena, 40.0)
                self.assertEqual("parou", alvo)
                self.assertGreaterEqual(quando, INICIO + max(fim for _, fim in cena.palavras))

    def test_quadros_de_fala_ficam_fora_da_janela(self):
        tracker = NoiseFloorTracker()
        for volume in _ruido_da_c920(150) + _fala_lognormal(1500):
            tracker.update(volume, 0.02)
        self.assertLess(tracker.ambient_noise_floor, 0.03)  # o piso da C920 (~0,021), não a fala

    def test_ventilador_que_liga_vira_o_piso(self):
        # Na main, o ruído novo levava ~10 s para virar o piso, e o fim vinha ~12 s depois de o
        # ventilador ligar. Agora, ~4 s para ficar estável, ~2 s para a janela encurtar e os 2,2 s.
        for semente in range(5):
            with self.subTest(semente=semente):
                cena = _cena_continua(semente, lambda c: c.falar(0.5, 3.0))
                liga = max(fim for _, fim in cena.palavras) + 0.3
                cena.ganho_do_ruido(lambda t, liga=liga: 2.5 if t >= liga else 1.0)
                alvo, quando = self._rodar(cena, 30.0)
                self.assertEqual("parou", alvo)
                self.assertLess(quando - INICIO - liga, 10.0)

    def test_ruido_que_sobe_devagar_nao_trava(self):
        for semente in range(5):
            with self.subTest(semente=semente):
                # O ruído dobra a cada 3 s, de 3,5 s a 12,5 s (8x), e fica.
                cena = _cena_continua(semente, lambda c: c.falar(0.5, 3.0))
                cena.ganho_do_ruido(lambda t: 2 ** ((min(max(t, 3.5), 12.5) - 3.5) / 3))
                disparou = self._rodar(cena, 40.0)
                self.assertIsNotNone(disparou, "o ditado não terminou")
                self.assertEqual("parou", disparou[0])

    def test_musica_de_fundo_entra_no_piso(self):
        # Música a 2x o ruído (na beira do limiar de fala): entra no piso, e o ditado termina mais
        # ou menos no tempo da main (mediana ~14 s depois de ela começar). Com a fala fora do piso
        # já a partir do limiar de silêncio, ela ficava de fora, e o fim ia a 25-35 s.
        tempos = []
        for semente in range(20):
            cena = _cena_continua(semente, lambda c: c.falar(0.5, 3.0))
            inicio = max(fim for _, fim in cena.palavras) + 0.3
            cena.som(inicio, 60.0, lambda rng: 0.06 * math.exp(rng.gauss(0, 0.5)))
            disparou = self._rodar(cena, 60.0)
            self.assertIsNotNone(disparou, f"semente {semente}: o ditado não terminou")
            self.assertEqual("parou", disparou[0])
            tempos.append(disparou[1] - INICIO - inicio)
        self.assertLessEqual(sum(t > 25.0 for t in tempos), 2, tempos)
        self.assertLess(statistics.median(tempos), 18.0, tempos)

    def test_som_alto_sem_pausa_nao_trava_o_ditado(self):
        # Acima do limiar de fala, sem nunca parecer estável (dois níveis, 0,09 e 0,16) e quase sem
        # pausa (0,15 s a cada 8 s): sem a saída dos 25 s, ou com cada pausa zerando a contagem,
        # nunca entrava no piso, e o ditado não terminava. Termina em ~55 s. (A TV no volume e na
        # variação da fala não tem como terminar: 2,2x o p5 dela fica no nível dela, como na main.)
        for semente in range(2):
            with self.subTest(semente=semente):
                cena = _cena_continua(semente, lambda c: c.falar(0.5, 3.0))
                t = max(fim for _, fim in cena.palavras) + 0.3
                while t < 95.0:
                    cena.som(t, 8.0, lambda rng: rng.choice((0.09, 0.16)))
                    t += 8.15
                disparou = self._rodar(cena, 95.0)
                self.assertIsNotNone(disparou, "o ditado não terminou")
                self.assertEqual("parou", disparou[0])

    def test_ventilador_ligado_antes_da_fala_nao_engole_a_fala(self):
        # Com 2 s de janela de estabilidade, o piso virava o ventilador antes de a pessoa falar, e
        # a fala (1,8x o ventilador) não passava do limiar: o ditado era cancelado com fala.
        for semente in range(10):
            with self.subTest(semente=semente):
                cena = _cena_continua(semente, lambda c: c.falar(4.0, 3.0))
                cena.ganho_do_ruido(lambda t: 2.5 if t >= 1.5 else 1.0)
                alvo, quando = self._rodar(cena, 30.0)
                self.assertEqual("parou", alvo)
                self.assertGreater(quando - INICIO, max(fim for _, fim in cena.palavras))

    def test_microfone_quieto_rumor_baixo_entra_no_piso(self):
        # Num microfone quieto (piso 0,0015), 3,3x o piso é 0,005: sem o mínimo de 0,025 do pedido,
        # um rumor de 0,006 a 0,02 (que não é estável) contava como fala e nunca entrava no piso.
        rng = random.Random(4)
        tracker = NoiseFloorTracker()
        for _ in range(100):
            tracker.update(0.0015 * math.exp(rng.gauss(0, 0.3)), 0.02)
        for _ in range(500):
            tracker.update(rng.uniform(0.006, 0.02), 0.02)
        self.assertGreater(tracker.ambient_noise_floor, 0.005)

    def test_quadros_grandes_nao_medem_estabilidade(self):
        # 4 s de quadros de 100 ms são 40 amostras: o p75/p25 delas oscila, e a fala passava por
        # estável. Com menos de 100 quadros, nada é estável.
        tracker = NoiseFloorTracker()
        for volume in [0.032, 0.034, 0.036, 0.038] * 10:
            tracker.update(volume, 0.1)
        self.assertFalse(tracker._sinal_estavel())
        for volume in [0.032, 0.034, 0.036, 0.038] * 25:
            tracker.update(volume, 0.02)
        self.assertTrue(tracker._sinal_estavel())

    def test_janela_volta_aos_10_s_depois_do_ruido_novo(self):
        tracker = NoiseFloorTracker()
        rng = random.Random(3)
        ruido = lambda fator: 0.032 * fator * math.exp(rng.gauss(0, SIGMA_C920))
        for _ in range(250):
            tracker.update(ruido(1.0), 0.02)
        for _ in range(600):  # 12 s de ventilador: a janela encurta e o piso vira o dele
            tracker.update(ruido(2.5), 0.02)
        self.assertGreater(tracker.ambient_noise_floor, 0.045)
        for _ in range(750):  # 15 s depois, ela voltou a guardar 10 s
            tracker.update(ruido(2.5), 0.02)
        self.assertAlmostEqual(10.0, tracker._tempo_da_janela, delta=0.05)

    def test_p5_interpolado_entre_os_postos(self):
        # O int() da posição truncava: com poucos quadros (a fala logo no começo), o p5 caía um
        # posto abaixo, e um quadro baixo que entrava derrubava o limiar de silêncio junto.
        tracker = NoiseFloorTracker()
        for volume in [0.03] * 20 + [0.010, 0.011, 0.012, 0.013, 0.014, 0.015, 0.016] + [0.03] * 20:
            tracker.update(volume, 0.02)
        janela = list(tracker._ordenados)
        self.assertNotEqual(0.0, (0.05 * (len(janela) - 1)) % 1)  # a posição cai entre dois postos
        self.assertAlmostEqual(float(np.percentile(janela, 5)), tracker.ambient_noise_floor)


class TestEscSoDuranteAGravacao(unittest.TestCase):
    """O Esc cancela o ditado em curso, e só nele: o RegisterHotKey dele é feito ao começar a
    gravar e desfeito ao parar, cancelar ou dormir, na thread dos atalhos. Fora disso, o Esc é
    dos outros programas."""

    ESC = (MOD_NOREPEAT, 0x1B)

    def setUp(self):
        # Os prazos abaixo esperam a thread dos atalhos: sem coletar antes, o Font.__del__ do Tk
        # de testes anteriores rodava nela e chamava o Tcl de fora da thread principal (~1 s cada).
        gc.collect()
        self.user32 = _User32Falso()
        patcher = patch.object(hotkey, "user32", self.user32)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mgr = Win32HotKeyManager()
        self.mgr.debounce_seconds = 0.0  # o 2º Esc vem logo depois do 1º, e o debounce o engoliria
        self.mgr.register("ctrl+shift+space", lambda: None)
        self.addCleanup(self.mgr.stop)

    def _esc_registrado(self):
        return self.ESC in self.user32.registrados.values()

    def test_fila_da_thread_existe_antes_do_start_voltar(self):
        # Sem nenhum atalho permanente, um pedido postado antes do 1º GetMessageW se perdia: a fila
        # da thread nasce na 1ª chamada que a usa (juiz do Bloco 9, 2ª rodada).
        self.mgr.clear()
        self.mgr.start()
        self.assertIn("peek", [c[0] for c in self.user32.chamadas])
        self.assertEqual(self.user32.thread_do_laco or self.mgr.thread_id,
                         next(c[2] for c in self.user32.chamadas if c[0] == "peek"))

    def test_esc_so_fica_registrado_enquanto_grava(self):
        cancelados = []
        self.mgr.start()
        self.assertFalse(self._esc_registrado(), "o Esc foi pego antes de gravar")

        self.assertTrue(self.mgr.registrar_temporario("cancelar_gravacao", "esc", lambda: cancelados.append(1)))
        _esperar(self._esc_registrado)
        id_do_esc = self.mgr.temporarios["cancelar_gravacao"][0]
        registro = [c for c in self.user32.chamadas if c[:2] == ("registrar", id_do_esc)]
        self.assertEqual([self.user32.thread_do_laco], [c[2] for c in registro])
        self.assertNotEqual(threading.get_ident(), self.user32.thread_do_laco)

        self.user32.apertar(id_do_esc)
        _esperar(lambda: cancelados)

        self.mgr.soltar_temporario("cancelar_gravacao")
        _esperar(lambda: not self._esc_registrado())
        soltura = [c for c in self.user32.chamadas if c[:2] == ("soltar", id_do_esc)]
        self.assertEqual([self.user32.thread_do_laco], [c[2] for c in soltura])

        self.user32.apertar(id_do_esc)
        _esperar(self.user32.fila.empty)
        time.sleep(0.05)
        self.assertEqual([1], cancelados, "o Esc solto ainda cancelou")

    def test_soltar_logo_depois_de_pedir_nao_deixa_o_esc_preso(self):
        self.mgr.start()
        self.mgr.registrar_temporario("cancelar_gravacao", "esc", lambda: None)
        self.mgr.soltar_temporario("cancelar_gravacao")
        _esperar(self.user32.fila.empty)
        time.sleep(0.05)
        self.assertFalse(self._esc_registrado())

    def test_pedido_que_chega_depois_do_soltar_nao_registra(self):
        # A thread que pediu o Esc perde a vez entre guardar o pedido e postá-lo, e o parar o solta
        # antes: o pedido atrasado chega à fila depois do de soltar (achado do juiz do Bloco 9).
        self.mgr.start()
        with self.mgr.lock:
            self.mgr._ids_temporarios += 1
            hk_id = hotkey._PRIMEIRO_ID_TEMPORARIO + self.mgr._ids_temporarios
            self.mgr.temporarios["cancelar_gravacao"] = (hk_id, "esc", lambda: None)
        self.mgr.soltar_temporario("cancelar_gravacao")
        self.user32.fila.put((hotkey.WM_REGISTRAR_TEMPORARIO, hk_id))
        _esperar(self.user32.fila.empty)
        time.sleep(0.05)
        self.assertFalse(self._esc_registrado())

    def test_gravacao_que_atravessa_a_recarga_dos_atalhos_mantem_o_esc(self):
        self.mgr.registrar_temporario("cancelar_gravacao", "esc", lambda: None)  # antes do start
        self.assertFalse(self._esc_registrado())
        self.mgr.start()
        _esperar(self._esc_registrado)
        self.mgr.stop()
        _esperar(lambda: not self._esc_registrado())


class _User32Falso:
    """O pedaço do user32 que o Win32HotKeyManager usa, com a fila de mensagens da thread dele."""

    def __init__(self):
        self.fila = queue.Queue()
        self.registrados = {}   # id -> (modificadores, tecla)
        self.chamadas = []      # (o quê, id, thread)
        self.thread_do_laco = None

    def RegisterHotKey(self, _janela, hk_id, mods, vk):
        self.chamadas.append(("registrar", hk_id, threading.get_ident()))
        if (mods, vk) in self.registrados.values():
            return 0
        self.registrados[hk_id] = (mods, vk)
        return 1

    def UnregisterHotKey(self, _janela, hk_id):
        self.chamadas.append(("soltar", hk_id, threading.get_ident()))
        return 1 if self.registrados.pop(hk_id, None) else 0

    def PostThreadMessageW(self, _thread, mensagem, wparam, _lparam):
        self.fila.put((mensagem, wparam))
        return 1

    def PeekMessageW(self, _ref, *_):
        self.chamadas.append(("peek", None, threading.get_ident()))
        return 0

    def GetMessageW(self, ref, *_):
        self.thread_do_laco = threading.get_ident()
        try:
            mensagem, wparam = self.fila.get(timeout=5)
        except queue.Empty:
            return 0
        ref._obj.message, ref._obj.wParam = mensagem, wparam
        return 0 if mensagem == WM_QUIT else 1

    def TranslateMessage(self, _ref):
        return 0

    def DispatchMessageW(self, _ref):
        return 0

    def apertar(self, hk_id):
        """O Windows entregando o atalho: WM_HOTKEY na fila da thread que o registrou."""
        self.fila.put((WM_HOTKEY, hk_id))


def _esperar(condicao, prazo_s=2.0):
    fim = time.time() + prazo_s
    while not condicao():
        if time.time() > fim:
            raise AssertionError("a condição não aconteceu a tempo")
        time.sleep(0.005)


@unittest.skipUnless(sys.platform == "win32", "RegisterHotKey é do Windows")
class TestTemporarioNoWindowsDeVerdade(unittest.TestCase):
    """Com o Win32 de verdade, por uma combinação que ninguém usa (e não o Esc, que a pessoa pode
    estar apertando enquanto os testes rodam): o Windows só a segura enquanto o temporário vale."""

    COMBO = "ctrl+alt+shift+f8"

    @staticmethod
    def _livre(combo):
        """A combinação está livre no Windows: registrada e solta na hora, numa thread à parte. Com
        um gerenciador de prova, o start() espera a thread dele no máximo 2 s, e sob carga a prova
        voltava antes de tentar, e a combinação presa parecia livre (achado do juiz do Bloco 9)."""
        mods, vk = Win32HotKeyManager.parse_hotkey(combo)
        resultado = {}

        def provar():
            livre = bool(hotkey.user32.RegisterHotKey(None, 0xBEEF, mods, vk))
            if livre:
                hotkey.user32.UnregisterHotKey(None, 0xBEEF)
            resultado["livre"] = livre

        prova = threading.Thread(target=provar)
        prova.start()
        prova.join()
        return resultado["livre"]

    def test_o_windows_so_segura_a_tecla_enquanto_o_temporario_vale(self):
        gc.collect()  # ver TestEscSoDuranteAGravacao.setUp
        if not self._livre(self.COMBO):
            self.skipTest(f"outro programa já usa {self.COMBO} nesta máquina")
        mgr = Win32HotKeyManager()
        mgr.start()
        try:
            mgr.registrar_temporario("teste", self.COMBO, lambda: None)
            _esperar(lambda: not self._livre(self.COMBO))
            mgr.soltar_temporario("teste")
            _esperar(lambda: self._livre(self.COMBO))
        finally:
            mgr.stop()


# O _soltar_esc solta o Esc puro e o Esc com os modificadores do atalho (Bloco 10).
SOLTAR_OS_ESC = [("soltar", "cancelar_gravacao"), ("soltar", "cancelar_gravacao_segurando")]


class TestEscNoWilly(unittest.TestCase):
    """A ligação do Esc no willy.py: registrado antes de começar a gravar (fora da reunião),
    solto em todo fim de gravação, e o cancelamento descarta o áudio sem ir à Groq."""

    def setUp(self):
        self.ordem = []
        self.ui = MagicMock()
        self.som = MagicMock()
        self.hotkeys = SimpleNamespace(
            registrar_temporario=lambda nome, combo, callback: self.ordem.append(("registrar", nome, combo, callback)),
            soltar_temporario=lambda nome: self.ordem.append(("soltar", nome)))

    def _funcao(self, nome, audio, **extra):
        globais = {"audio_mgr": audio, "sound_mgr": self.som, "atualizar_ui": self.ui, "hotkey_mgr": self.hotkeys,
                       "config_mgr": SimpleNamespace(wake_word_enabled=False, auto_silence=True),
                       "_ATALHO_DO_CANCELAR": _constante_do_willy("_ATALHO_DO_CANCELAR"),
                       "_ATALHO_DO_CANCELAR_SEGURANDO": _constante_do_willy("_ATALHO_DO_CANCELAR_SEGURANDO"),
                       "Optional": Optional, "Win32HotKeyManager": Win32HotKeyManager,
                       "pill": None, "_janela_antes_do_willy": 0, "_foco_antes_do_willy": 0}
        globais["_soltar_esc"] = _funcao_do_willy("_soltar_esc", **globais)
        globais["_soltar_esc_sem_gravacao"] = _funcao_do_willy("_soltar_esc_sem_gravacao", **globais)
        globais.update(extra)
        return _funcao_do_willy(nome, **globais)

    def _audio_gravando(self):
        audio = AudioManager()
        audio.stream = MagicMock(active=True)
        audio.start_recording("transcribe")
        audio.append_audio(np.full((320, 1), 0.1, dtype=np.float32))
        return audio

    def test_esc_cancela_e_descarta_o_audio(self):
        audio = self._audio_gravando()
        audio.pause_stream = MagicMock()
        self._funcao("cancelar_por_esc", audio)()
        self.assertFalse(audio.is_recording)
        self.assertEqual([], audio.buffer)
        # Solto antes e de novo depois do cancel: a gravação cancelada podia ser uma seguinte, que
        # registrou o Esc depois do primeiro soltar (juiz do Bloco 9, 2ª rodada).
        self.assertEqual(SOLTAR_OS_ESC * 2, self.ordem)
        self.ui.assert_called_once_with("cancelled", "Ditado cancelado (Esc)")
        audio.pause_stream.assert_called_once_with()

    def test_esc_sem_gravacao_ou_com_o_envio_em_curso_nao_faz_nada(self):
        parado = AudioManager()
        enviando = self._audio_gravando()
        enviando.is_stopping = True
        for audio in (parado, enviando):
            with self.subTest(gravando=audio.is_recording):
                self.ordem.clear()
                self._funcao("cancelar_por_esc", audio)()
                self.assertTrue(self.ordem)
                self.assertTrue(all(passo in SOLTAR_OS_ESC for passo in self.ordem))
                self.ui.assert_not_called()
        self.assertTrue(enviando.is_recording, "o Esc cancelou o ditado que já estava sendo enviado")

    def _iniciar(self, modo, comeca=True, outra_gravando=False, atalho=None):
        audio = MagicMock(is_recording=False, is_processing=False, is_awake=True, system_device_index=None)
        audio.ensure_stream.return_value = True

        def gravar(m):
            self.ordem.append(("gravar", m))
            if isinstance(comeca, Exception):
                raise comeca
            audio.is_recording = comeca or outra_gravando
            return comeca

        audio.start_recording.side_effect = gravar
        self._funcao("iniciar_gravacao", audio, ContextManager=MagicMock(), callback_audio="cb",
                     cancelar_por_esc="cancelar_por_esc")(modo, atalho)
        return [passo[:3] if passo[0] == "registrar" else passo for passo in self.ordem]

    def test_start_que_levanta_solta_o_esc(self):
        # Um PortAudioError no start_recording deixava o Esc registrado sem gravação.
        with self.assertRaises(RuntimeError):
            self._iniciar("transcribe", comeca=RuntimeError("PortAudioError"))
        self.assertEqual(SOLTAR_OS_ESC, self.ordem[-2:])

    def test_outra_gravacao_que_comecou_fica_com_o_esc(self):
        # O "Ei Willy" e o atalho ao mesmo tempo: a que não começou não solta o Esc da outra.
        self.assertEqual([("registrar", "cancelar_gravacao", "esc"), ("gravar", "send")],
                         self._iniciar("send", comeca=False, outra_gravando=True))

    def test_esc_nunca_cancela_a_reuniao(self):
        # Se o Esc ficasse preso (uma corrida), ele cancelava a reunião que viesse depois.
        audio = AudioManager()
        audio.stream = MagicMock(active=True)
        audio.start_recording("meeting")
        self._funcao("cancelar_por_esc", audio)()
        self.assertTrue(audio.is_recording)
        self.ui.assert_not_called()

    def test_cancelar_solta_o_esc_depois_de_cancelar(self):
        # Um parar ou cancelar em outra thread podia encerrar a gravação que começou depois do
        # _soltar_esc do começo, e ninguém soltava o Esc dela.
        audio = MagicMock(is_recording=False)
        audio.cancel_recording.side_effect = lambda: self.ordem.append(("cancelar",)) or True
        self._funcao("cancelar_gravacao", audio)()
        self.assertEqual(SOLTAR_OS_ESC + [("cancelar",)] + SOLTAR_OS_ESC, self.ordem)

    def test_registra_antes_de_comecar_a_gravar(self):
        self.assertEqual([("registrar", "cancelar_gravacao", "esc"), ("gravar", "transcribe")],
                         self._iniciar("transcribe"))
        self.assertEqual("cancelar_por_esc", self.ordem[0][3])

    def test_reuniao_nao_pega_o_esc(self):
        self.assertEqual([("gravar", "meeting")], self._iniciar("meeting"))

    def test_gravacao_que_nao_comeca_solta_o_esc(self):
        self.assertEqual([("registrar", "cancelar_gravacao", "esc"), ("gravar", "send")] + SOLTAR_OS_ESC,
                         self._iniciar("send", comeca=False))

    def test_todo_fim_de_gravacao_solta_o_esc(self):
        with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
            funcoes = {n.name: n for n in ast.walk(ast.parse(f.read())) if isinstance(n, ast.FunctionDef)}

        def chamadas(nome):
            return [getattr(c.func, "attr", getattr(c.func, "id", "")) for c in ast.walk(funcoes[nome])
                    if isinstance(c, ast.Call)]

        nomes = chamadas("parar_gravacao")
        self.assertLess(nomes.index("_soltar_esc"), nomes.index("stop_recording_com_taxa"))
        self.assertLess(nomes.index("stop_recording_com_taxa"), nomes.index("_soltar_esc_sem_gravacao"))
        nomes = chamadas("cancelar_gravacao")
        self.assertLess(nomes.index("_soltar_esc"), nomes.index("cancel_recording"))
        nomes = chamadas("toggle_willy_awake")
        self.assertLess(nomes.index("_soltar_esc"), nomes.index("cancel_recording"))

    def test_o_esc_e_a_tecla_esc_sem_modificador(self):
        self.assertEqual("esc", next(p[2] for p in self._iniciar_e_ordem("transcribe") if p[0] == "registrar"))
        self.assertEqual((MOD_NOREPEAT, 0x1B), Win32HotKeyManager.parse_hotkey("esc"))

    def _iniciar_e_ordem(self, modo):
        self.ordem.clear()
        return self._iniciar(modo)


class TestEiWillyNaC920(unittest.TestCase):
    """A escuta do "Ei Willy" mede o ruído: o limiar era o fixo x 1,3 (0,0117), e na C920 (ruído
    ~0,032) todo bloco passava. A cada 1,8 s, ~33 vezes por minuto, ruído ia à Groq."""

    def _escutar(self, volumes, dt=0.02, speech_threshold=0.009, aberturas=None):
        """Os gatilhos (o tamanho do buffer em cada checagem) da escuta pelos `volumes`.
        `aberturas`: para cada quadro, quantas vezes o microfone já abriu."""
        gatilhos, buffer = [], []
        audio = SimpleNamespace(is_recording=False, is_awake=True, is_processing=False, actual_sample_rate=TAXA,
                                sample_rate=TAXA, compute_rms=AudioManager.compute_rms, aberturas_do_microfone=1)

        def checar():
            gatilhos.append(len(buffer))
            buffer.clear()

        callback = _funcao_do_willy(
            "callback_audio", audio_mgr=audio,
            config_mgr=SimpleNamespace(wake_word_enabled=True, speech_threshold=speech_threshold),
            _wake_word_processing=False, _wake_word_buffer=buffer, _trigger_wake_word_check=checar,
            _piso_de_escuta=PisoDeEscuta())
        n = round(dt * TAXA)
        for i, volume in enumerate(volumes):
            if aberturas:
                audio.aberturas_do_microfone = aberturas[i]
            callback(np.full((n, 1), volume, dtype=np.float32), n, None, None)
        return gatilhos

    def test_ruido_da_c920_nao_vai_a_groq(self):
        self.assertEqual([], self._escutar(_ruido_da_c920(3000)))  # 60 s

    def test_microfone_acordando_nao_vai_a_groq(self):
        # O fade-in do microfone que abre (1 s de 5% a 100%): o p5 dele, na janela de 10 s,
        # deixava o limiar no fixo (0,0117), e o ruído da C920 voltava a ir à Groq.
        ruido = _ruido_da_c920(3000)
        fade = [v * max(0.05, (i + 1) / 50) for i, v in enumerate(ruido[:50])]
        self.assertEqual([], self._escutar(fade + ruido[50:]))

    def test_audio_manager_conta_as_aberturas_do_microfone(self):
        audio = AudioManager()
        stream = MagicMock(active=False)
        with patch("core.audio.negociar_stream", return_value=(stream, TAXA)):
            audio.ensure_stream(lambda *args: None)  # criado
            self.assertEqual(1, audio.aberturas_do_microfone)
            audio.ensure_stream(lambda *args: None)  # pausado e religado
            self.assertEqual(2, audio.aberturas_do_microfone)
        stream.start.assert_called_once_with()

    def test_microfone_novo_recomeca_a_medida(self):
        # 5 s num microfone quieto e, nos Ajustes, a C920: o p5 do quieto ficava 10 s na janela.
        ruido = _ruido_da_c920(1000)
        volumes = [0.0015] * 250 + ruido
        self.assertEqual([], self._escutar(volumes, aberturas=[1] * 250 + [2] * len(ruido)))

    def test_ei_willy_dito_na_c920_e_ouvido(self):
        ruido = _ruido_da_c920(500)
        gatilhos = self._escutar(ruido[:150] + [0.12] * 40 + ruido[150:])  # 0,8 s de fala
        self.assertEqual(1, len(gatilhos))

    def test_zeros_nao_contam_como_ruido(self):
        # O stream abrindo, um microfone mudo: silêncio digital não é o ruído da sala.
        escuta = PisoDeEscuta()
        for volume in [0.0] * 200:
            escuta.update(volume, 0.02)
        self.assertTrue(escuta.calibrando)
        for volume in [0.0] * 50 + _ruido_da_c920(100):  # 1 s descartado e 1 s medido
            escuta.update(volume, 0.02)
        self.assertFalse(escuta.calibrando)
        self.assertTrue(0.015 < escuta.piso < 0.03, escuta.piso)

    def test_microfone_quieto_continua_no_limiar_fixo(self):
        escuta = PisoDeEscuta()
        for volume in [0.0015] * 200:
            escuta.update(volume, 0.02)
        self.assertAlmostEqual(0.009 * 1.3, escuta.limiar_de_fala(0.009))
        self.assertEqual(1, len(self._escutar([0.0015] * 100 + [0.03] * 40 + [0.0015] * 20)))

    def test_limiar_e_3x_o_piso_da_escuta(self):
        escuta = PisoDeEscuta()
        for volume in _ruido_da_c920(500):
            escuta.update(volume, 0.02)
        self.assertAlmostEqual(3.0 * escuta.piso, escuta.limiar_de_fala(0.009))
        self.assertTrue(0.015 < escuta.piso < 0.03)

    def test_antes_de_medir_o_ruido_nada_dispara(self):
        # 1 s descartado e 0,5 s de medida: sem o ruído medido, não há como saber o que é fala.
        self.assertEqual([], self._escutar([0.12] * 70))
        self.assertEqual(1, len(self._escutar(_ruido_da_c920(100) + [0.12] * 40 + _ruido_da_c920(20))))


class TestDiagnosticoDoMicrofone(unittest.TestCase):
    """A aba Diagnósticos mostra o microfone dos Ajustes e diz, em palavras, como ele está."""

    def _teste(self, ruido, voz, fracao_de_voz=0.4, n=100):
        quantos = int(n * fracao_de_voz)
        return ruido[:n - quantos] + voz[:quantos]

    def test_c920_com_voz_normal_esta_pronta(self):
        texto, pronto = resumo_do_teste(self._teste(_ruido_da_c920(100), _fala_lognormal(100)))
        self.assertEqual("Ruído ambiente: alto · Voz: boa · Status: pronto para ditado", texto)
        self.assertTrue(pronto)

    def test_microfone_quieto_com_voz(self):
        texto, pronto = resumo_do_teste(self._teste([0.0015] * 100, _fala_lognormal(100, mediana=0.04, ruido=0.0015)))
        self.assertEqual("Ruído ambiente: baixo · Voz: boa · Status: pronto para ditado", texto)
        self.assertTrue(pronto)

    def test_voz_baixa_na_c920(self):
        texto, pronto = resumo_do_teste(self._teste(_ruido_da_c920(100), [0.07] * 100))
        self.assertEqual("Ruído ambiente: alto · Voz: baixa · Status: fale mais perto do microfone", texto)
        self.assertFalse(pronto)

    def test_ruido_moderado_sem_voz(self):
        texto, pronto = resumo_do_teste([0.01] * 100)
        self.assertEqual("Ruído ambiente: moderado · Voz: não detectada · Status: fale durante o teste", texto)
        self.assertFalse(pronto)

    def test_um_clique_nao_passa_por_voz(self):
        # O p95, e não o máximo: um toque na mesa durante o teste não é voz.
        texto, pronto = resumo_do_teste(_ruido_da_c920(99) + [0.5])
        self.assertIn("Voz: não detectada", texto)
        self.assertFalse(pronto)

    def test_microfone_mudo(self):
        texto, pronto = resumo_do_teste([0.0] * 100)
        self.assertIn("Microfone mudo", texto)
        self.assertFalse(pronto)

    def test_barra_do_teste_acima_do_piso(self):
        self.assertEqual(0.0, nivel_acima_do_piso(0.032, 0.025))
        self.assertGreater(nivel_acima_do_piso(0.12, 0.025), 0.25)

    def _aba(self, ajustes, dispositivos):
        aba = SimpleNamespace(callbacks={"get_settings": lambda: ajustes}, lbl_mic_info=MagicMock())
        for nome in ("_microfone_dos_ajustes", "_nome_do_microfone", "atualizar_microfone"):
            setattr(aba, nome, types.MethodType(getattr(DiagnosticsTab, nome), aba))
        consulta = patch.object(tab_diagnostics.sd, "query_devices",
                                side_effect=lambda indice=None, kind=None: dispositivos[kind or indice])
        consulta.start()
        self.addCleanup(consulta.stop)
        return aba

    def test_mostra_o_microfone_dos_ajustes(self):
        aba = self._aba({"audio_device": 3}, {3: {"name": "C920 Pro"}, "input": {"name": "Realtek"}})
        aba.atualizar_microfone()
        aba.lbl_mic_info.configure.assert_called_once_with(text="Dispositivo selecionado: C920 Pro")

    def test_sem_microfone_nos_ajustes_mostra_o_padrao_do_windows(self):
        aba = self._aba({"audio_device": None}, {"input": {"name": "Realtek"}})
        self.assertEqual("Realtek (padrão do Windows)", aba._nome_do_microfone())

    def test_aba_relida_ao_abrir_e_ao_mudar_os_ajustes(self):
        with open(os.path.join(RAIZ, "ui", "dashboard.py"), encoding="utf-8") as f:
            funcoes = {n.name: n for n in ast.walk(ast.parse(f.read())) if isinstance(n, ast.FunctionDef)}
        for nome in ("mudar_aba", "recarregar_ajustes"):
            with self.subTest(funcao=nome):
                chamadas = {getattr(c.func, "attr", "") for c in ast.walk(funcoes[nome]) if isinstance(c, ast.Call)}
                self.assertIn("atualizar_microfone", chamadas)

    def test_teste_de_5_s_mede_e_diz_o_diagnostico(self):
        # O run_meter de verdade, com o microfone, o relógio e a thread falsos: 5 s de leituras a
        # cada 40 ms (125), 1,2 s de silêncio da C920, 0,8 s de fala e silêncio de novo.
        ruido = _ruido_da_c920(200)
        volumes = iter(ruido[:60] + _fala_lognormal(40) + ruido[60:])
        stream = MagicMock()
        stream.read.side_effect = lambda n: (np.full((n, 1), next(volumes), dtype=np.float32), False)
        relogio = [0.0]
        barras, textos = [], []
        aba = SimpleNamespace(mic_test_active=False, callbacks={"get_settings": lambda: {"audio_device": 3}},
                              btn_test_mic=MagicMock(), prog_volume=SimpleNamespace(set=barras.append),
                              lbl_diagnostico=SimpleNamespace(configure=lambda **kw: textos.append(kw)),
                              _safe_after=lambda _ms, funcao, *args: funcao(*args), atualizar_microfone=lambda: None)
        aba._microfone_dos_ajustes = types.MethodType(DiagnosticsTab._microfone_dos_ajustes, aba)

        def dormir(segundos):
            relogio[0] += segundos

        with patch.object(tab_diagnostics, "negociar_stream", return_value=(stream, 16000)) as negociar, \
                patch.object(tab_diagnostics.time, "time", lambda: relogio[0]), \
                patch.object(tab_diagnostics.time, "sleep", dormir), \
                patch.object(tab_diagnostics.threading, "Thread",
                             lambda target, daemon=None: SimpleNamespace(start=target)):
            DiagnosticsTab.iniciar_teste_mic(aba)
        self.assertEqual(3, negociar.call_args.args[0])  # o microfone dos Ajustes
        self.assertEqual("Ruído ambiente: alto · Voz: boa · Status: pronto para ditado", textos[-1]["text"])
        self.assertEqual(tab_diagnostics.APPLE_STATUS_ONLINE, textos[-1]["text_color"])
        medidas = barras[:-1]  # o último é o reset
        self.assertEqual(0.0, statistics.median(medidas[:60]))  # o ruído da C920, abaixo do piso
        self.assertGreater(max(medidas), 0.3)                   # a voz


if __name__ == "__main__":
    unittest.main()
