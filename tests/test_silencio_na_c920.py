"""
O corte por silêncio funciona num microfone com ruído acima do limiar fixo (a C920 do dono).

Medido na máquina do dono, em silêncio: RMS mínimo 0,023, mediana 0,032, p75 0,038, com o .env
em SILENCE_THRESHOLD=0,005 e SPEECH_THRESHOLD=0,009. No 1º quadro o piso ainda era 0, o
limiar de fala era o fixo (0,009) e o ruído (0,032) já virava fala: has_spoken ficava True, o
piso nunca era medido (só se media antes da fala), o silêncio ficava em 0,005, abaixo do ruído,
e o ditado não terminava sozinho (nem o cancelamento por 7 s sem fala funcionava).

Aqui o callback_audio de verdade (do willy.py) roda com um AudioManager de verdade, um relógio
falso e o som gerado com semente fixa. Nada toca o microfone. Os cenários são os dos dois juízes
do Bloco 7A: zeros e fade-in quando o stream abre, queda no meio,
fala fluente desde o 1º quadro, o clique da tecla e o bipe de início do Willy, um microfone
mudo, um com supressão de ruído, o modo sussurro, e um microfone quieto ao lado da C920.
"""

import math
import random
import unittest
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock

import numpy as np

from core.audio import AudioManager
from core.audio_processing.vad import NoiseFloorTracker
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy

TAXA = 16000
INICIO = 1000.0  # o relógio falso não começa em 0: o callback lê no_speech_start_time = 0 como "sem hora"
SIGMA_C920 = math.log(0.038 / 0.032) / 0.6745  # p75 / mediana medidos

# (ruído de um quadro, mediana da fala)
MICROFONES = {
    "c920": (lambda rng: 0.032 * math.exp(rng.gauss(0, SIGMA_C920)), 0.12),
    "quieto": (lambda rng: 0.0015 * math.exp(rng.gauss(0, 0.3)), 0.04),
}


class _Cena:
    """Uma gravação descrita no tempo: o ruído, os sons por cima dele (palavras, o clique, o bipe)
    e os trechos zerados. Um quadro que pega parte de um som recebe a fração da energia dele,
    como no microfone: o bipe de 45 ms ocupa 2 ou 3 quadros de 20 ms, e não 1."""

    def __init__(self, rng, ruido, mediana_fala):
        self.rng, self.ruido, self.mediana_fala = rng, ruido, mediana_fala
        self.sons, self.zeros, self.ganhos, self.palavras = [], [], [], []

    def som(self, t0, duracao, nivel, fala=False):
        self.sons.append((t0, t0 + duracao, nivel))
        if fala:
            self.palavras.append((t0, t0 + duracao))

    def falar(self, t0, segundos, pausa=(0.04, 0.25)):
        """Palavras de 150 a 400 ms com pausas entre elas; devolve quando a fala acabou."""
        t = t0
        while t < t0 + segundos:
            d = min(self.rng.uniform(0.15, 0.4), t0 + segundos - t)
            self.som(t, d, lambda rng: self.mediana_fala * math.exp(rng.gauss(0, 0.5)), fala=True)
            t += d + self.rng.uniform(*pausa)
        return t

    def inicio_do_willy(self, t0=0.0):
        """O clique da tecla (30 a 50 ms, alto) e, 30 a 120 ms depois, o bipe de início
        (sound_start: Beep(1320, 45))."""
        self.som(t0, self.rng.uniform(0.03, 0.05), lambda rng: rng.uniform(0.15, 0.4))
        self.som(t0 + self.rng.uniform(0.03, 0.12), 0.045, lambda rng: rng.uniform(0.08, 0.25))

    def zerar(self, t0, duracao):
        """Silêncio digital: o stream abrindo, uma queda do microfone."""
        self.zeros.append((t0, t0 + duracao))

    def ganho_do_ruido(self, fator):
        """O ruído multiplicado por fator(t): o microfone acordando, o ganho automático."""
        self.ganhos.append(fator)

    def quadros(self, dt, total_s):
        """[(volume, instante do fim do quadro)]."""
        saida = []
        for i in range(round(total_s / dt)):
            a, b = i * dt, (i + 1) * dt
            ruido = self.ruido(self.rng)
            for fator in self.ganhos:
                ruido *= fator(a)
            energia = ruido * ruido
            for (s0, s1, nivel) in self.sons:
                junto = min(b, s1) - max(a, s0)
                if junto > 0:
                    energia += junto / dt * nivel(self.rng) ** 2
            for (z0, z1) in self.zeros:
                junto = min(b, z1) - max(a, z0)
                if junto > 0:
                    energia *= max(0.0, 1 - junto / dt)
            saida.append((math.sqrt(energia), b))
        return saida


def _fade(segundos):
    return lambda t: min(1.0, max(0.02, t / segundos))


COM_FALA = {
    "normal": lambda c: c.falar(0.4, 3.0),
    "inicio_do_willy_e_fala": lambda c: (c.inicio_do_willy(), c.falar(0.5, 3.0)),
    # 3 s até a primeira palavra: o clique e o bipe não podem virar fala, senão o silêncio depois
    # deles mandava a gravação só com ruído.
    "inicio_do_willy_e_pausa_de_3_s": lambda c: (c.inicio_do_willy(), c.falar(3.0, 2.0)),
    "fala_fluente_desde_o_1o_quadro": lambda c: c.falar(0.0, c.rng.uniform(8.0, 12.0), pausa=(0.02, 0.08)),
    "frase_curta_logo_no_comeco": lambda c: c.falar(0.0, c.rng.uniform(0.8, 1.2)),
    "zeros_no_inicio": lambda c: (c.zerar(0.0, 0.12), c.falar(0.4, 3.0)),
    "fade_in_no_inicio": lambda c: (c.ganho_do_ruido(_fade(0.3)), c.inicio_do_willy(0.3), c.falar(0.8, 3.0)),
    "queda_no_meio": lambda c: c.zerar(c.falar(0.4, 2.0), 1.2) or c.falar(c.palavras[-1][1] + 1.3, 2.0),
}

SO_RUIDO = {
    "so_ruido": lambda c: None,
    "inicio_do_willy_e_so_ruido": lambda c: c.inicio_do_willy(),
    "zeros_e_so_ruido": lambda c: c.zerar(0.0, 0.12),
    "fade_in_e_so_ruido": lambda c: c.ganho_do_ruido(_fade(0.3)),
}


def _cena(cenarios, cenario, microfone, semente, ruido=None):
    ruido_do_mic, mediana_fala = MICROFONES[microfone]
    cena = _Cena(random.Random(f"{cenario}-{microfone}-{semente}"), ruido or ruido_do_mic, mediana_fala)
    cenarios[cenario](cena)
    return cena


class _Gravacao:
    """Roda o callback_audio do willy.py quadro a quadro e diz quando ele parou ou cancelou."""

    def __init__(self, dt, sussurro=False, modo="transcribe"):
        from unittest.mock import patch
        self.dt, self.agora, self.disparou = dt, INICIO, None
        self.audio = AudioManager()
        self.audio.stream = MagicMock(active=True)  # start_recording exige o microfone aberto
        self.audio.actual_sample_rate = TAXA
        if sussurro:
            self.audio.set_whisper_mode(True)
        with patch("core.audio.time.time", return_value=INICIO):
            self.audio.start_recording(modo)
        assert self.audio.recording_start_time == INICIO, "start_recording deve iniciar recording_start_time"
        assert self.audio.no_speech_start_time == INICIO, "start_recording deve iniciar no_speech_start_time" 
        config = SimpleNamespace(wake_word_enabled=False, auto_silence=True, silero_vad=False,
                                 speech_threshold=0.009, silence_threshold=0.005, silence_seconds=2.2)
        threading = SimpleNamespace(Thread=lambda target, daemon=None: SimpleNamespace(
            start=lambda: setattr(self, "disparou", (target, self.agora))))
        self.callback = _funcao_do_willy(
            "callback_audio", audio_mgr=self.audio, config_mgr=config, pill=None, safe_dispatch_ui=MagicMock(),
            time=SimpleNamespace(time=lambda: self.agora), threading=threading,
            parar_gravacao="parou", cancelar_gravacao="cancelou", FLUTUANTE_TEXTO="", FLUTUANTE_AMARELO="",
            _DITADO_LONGO_S=10.0, _FOLEGO_EXTRA_S=0.6)

    def quadro(self, volume):
        n = max(1, round(self.dt * TAXA))
        self.callback(np.full((n, 1), volume, dtype=np.float32), n, None, None)

    def rodar(self, cena, total_s=25.0):
        """(o que disparou, quando), ou None, e o instante da última palavra da cena."""
        ultima_fala = INICIO + max(fim for _, fim in cena.palavras) if cena.palavras else None
        for volume, fim in cena.quadros(self.dt, total_s):
            self.agora = INICIO + fim
            self.quadro(volume)
            if self.disparou:
                break
        return self.disparou, ultima_fala


class TestSilencioNaC920(unittest.TestCase):
    QUADROS_S = (0.010, 0.020, 0.032)  # o stream abre com 20 ms (core/audio.py)
    SEMENTES = range(3)

    # Depois de uma queda, os zeros valem os limiares base por até ~2,7 s: na C920 o ruído passa
    # do silêncio de 0,005 nesse tempo, e o fim atrasa até ~2 s (achado aceito do 2º juiz).
    FOLGA_S: ClassVar[dict] = {"queda_no_meio": 3.0}

    def _assert_parou_depois_da_fala(self, disparou, ultima_fala, folga_s=1.0):
        self.assertIsNotNone(disparou, "o ditado não terminou sozinho")
        alvo, quando = disparou
        self.assertEqual("parou", alvo)
        # Depois da última palavra, e até ~1 s além dos 2,2 s de silêncio.
        self.assertGreaterEqual(quando, ultima_fala + 1.5, "parou antes do fim da fala")
        self.assertLessEqual(quando, ultima_fala + 2.2 + folga_s)

    def _assert_cancelou(self, disparou):
        self.assertIsNotNone(disparou, "a gravação sem fala não terminou")
        self.assertEqual("cancelou", disparou[0])
        self.assertAlmostEqual(INICIO + 7.0, disparou[1], delta=0.1)

    def test_ruido_da_c920_no_primeiro_quadro_nao_vira_fala(self):
        # O deadlock: com o ruído logo no 1º quadro, has_spoken travava e nada terminava a gravação.
        for dt in self.QUADROS_S:
            with self.subTest(dt=dt):
                gravacao = _Gravacao(dt)
                for i in range(round(8.0 / dt)):
                    gravacao.agora = INICIO + (i + 1) * dt
                    gravacao.quadro(0.032)
                    if gravacao.disparou:
                        break
                self._assert_cancelou(gravacao.disparou)

    def test_ditado_termina_sozinho_depois_da_fala(self):
        for cenario in COM_FALA:
            for microfone in MICROFONES:
                for dt in self.QUADROS_S:
                    for semente in self.SEMENTES:
                        with self.subTest(cenario=cenario, microfone=microfone, dt=dt, semente=semente):
                            cena = _cena(COM_FALA, cenario, microfone, semente)
                            self._assert_parou_depois_da_fala(*_Gravacao(dt).rodar(cena),
                                                              folga_s=self.FOLGA_S.get(cenario, 1.0))

    def test_so_ruido_cancela_aos_7_s(self):
        for cenario in SO_RUIDO:
            for microfone in MICROFONES:
                for dt in self.QUADROS_S:
                    for semente in self.SEMENTES:
                        with self.subTest(cenario=cenario, microfone=microfone, dt=dt, semente=semente):
                            cena = _cena(SO_RUIDO, cenario, microfone, semente)
                            self._assert_cancelou(_Gravacao(dt).rodar(cena)[0])

    def test_microfone_mudo_ou_abaixo_de_1e4_cancela_aos_7_s(self):
        # Achado do 2º juiz: só zeros (ou ruído abaixo do silêncio digital), a calibração nunca
        # acabava, e o cancelamento por 7 s não rodava nela: a gravação ficava aberta.
        for nome, ruido in (("mudo", lambda rng: 0.0), ("5e-5", lambda rng: 5e-5 * math.exp(rng.gauss(0, 0.3)))):
            for dt in self.QUADROS_S:
                with self.subTest(microfone=nome, dt=dt):
                    cena = _cena(SO_RUIDO, "inicio_do_willy_e_so_ruido", "c920", 0, ruido=ruido)
                    self._assert_cancelou(_Gravacao(dt).rodar(cena)[0])

    def test_reuniao_nao_encerra_por_silencio_mesmo_com_auto_silence(self):
        cena = _cena(COM_FALA, "normal", "c920", 0)
        disparou, _ = _Gravacao(0.02, modo="meeting").rodar(cena)
        self.assertIsNone(disparou, "Modo reunião nunca deve parar nem cancelar por silêncio")

    def test_cancelamento_por_7_s_vale_mesmo_calibrando(self):
        # Defesa no callback: se a calibração não acabasse (era o microfone mudo), o cancelamento
        # por 7 s sem fala tem que valer assim mesmo, senão a gravação fica aberta.
        gravacao = _Gravacao(0.02)
        gravacao.audio._noise_tracker.calibracao_max_s = 1e9
        for i in range(round(8.0 / 0.02)):
            gravacao.agora = INICIO + (i + 1) * 0.02
            gravacao.quadro(0.0)
            if gravacao.disparou:
                break
        self.assertTrue(gravacao.audio.calibrando_ruido)
        self._assert_cancelou(gravacao.disparou)

    def test_microfone_com_supressao_de_ruido(self):
        # Achado do 2º juiz: com zeros entre as palavras (NVIDIA Broadcast, Krisp), o piso saía só
        # da fala, o limiar de fala passava do pico, e a fala era descartada aos 7 s.
        for mediana in (0.03, 0.08, 0.15):
            for cenario in ("normal", "fala_fluente_desde_o_1o_quadro"):
                for dt in self.QUADROS_S:
                    with self.subTest(fala=mediana, cenario=cenario, dt=dt):
                        cena = _Cena(random.Random(f"gate-{mediana}-{cenario}-{dt}"), lambda rng: 0.0, mediana)
                        COM_FALA[cenario](cena)
                        self._assert_parou_depois_da_fala(*_Gravacao(dt).rodar(cena))

    def test_modo_sussurro_na_c920_termina(self):
        # Achado do 2º juiz: os limiares do sussurro eram fixos (x 0,45), abaixo do ruído da C920,
        # e nenhum ditado terminava sozinho.
        for dt in self.QUADROS_S:
            with self.subTest(dt=dt):
                self._assert_parou_depois_da_fala(
                    *_Gravacao(dt, sussurro=True).rodar(_cena(COM_FALA, "normal", "c920", 0)))
                self._assert_cancelou(_Gravacao(dt, sussurro=True).rodar(_cena(SO_RUIDO, "so_ruido", "c920", 0))[0])

    def test_nan_no_volume_nao_derruba_o_callback(self):
        # Achado do 2º juiz: um NaN dessincronizava a janela do piso e levantava IndexError, e a
        # exceção no callback aborta o stream do sounddevice.
        gravacao = _Gravacao(0.02)
        cena = _cena(COM_FALA, "normal", "c920", 0)
        quadros = cena.quadros(0.02, 15.0)
        for i, (volume, fim) in enumerate(quadros):
            gravacao.agora = INICIO + fim
            gravacao.quadro(float("nan") if i % 37 == 5 else volume)
            if gravacao.disparou:
                break
        self._assert_parou_depois_da_fala(gravacao.disparou, INICIO + max(f for _, f in cena.palavras))

    def test_calibracao_conta_o_tempo_do_quadro_de_verdade(self):
        # O callback passa a duração do quadro (len(indata) / taxa): o começo que só mede o
        # ambiente (aquecimento de 150 ms + 0,5 s de piso) é o mesmo tempo em quadros de 10 a 32 ms.
        for dt in self.QUADROS_S:
            with self.subTest(dt=dt):
                gravacao = _Gravacao(dt)
                quadros = 0
                while gravacao.audio.calibrando_ruido:
                    gravacao.quadro(0.032)
                    quadros += 1
                self.assertAlmostEqual(0.66, quadros * dt, delta=0.03)

    def test_fala_baixa_tambem_termina(self):
        # Fala a 2,8x a mediana do ruído da C920.
        for dt in self.QUADROS_S:
            with self.subTest(dt=dt):
                ruido, _ = MICROFONES["c920"]
                cena = _Cena(random.Random(f"baixa-{dt}"), ruido, 0.09)
                COM_FALA["normal"](cena)
                self._assert_parou_depois_da_fala(*_Gravacao(dt).rodar(cena))


class TestPisoDeRuido(unittest.TestCase):
    @staticmethod
    def _calibrado(ruido=0.032, dt=0.01):
        piso = NoiseFloorTracker()
        while piso.calibrando:
            piso.update(ruido, dt)
        return piso

    def test_piso_desde_a_primeira_amostra(self):
        piso = NoiseFloorTracker()
        self.assertAlmostEqual(0.032, piso.update(0.032, 0.01))
        self.assertTrue(piso.calibrando)

    def test_aquecimento_dura_150_ms_e_ao_menos_4_quadros(self):
        # O aquecimento guarda as amostras dele em noise_samples; depois, elas param de entrar.
        for dt, quadros in ((0.010, 15), (0.064, 4)):
            with self.subTest(dt=dt):
                piso = NoiseFloorTracker()
                for _ in range(400):
                    piso.update(0.032, dt)
                self.assertEqual(quadros, len(piso.noise_samples))

    def test_aquecimento_espera_o_fade_in_do_stream(self):
        # 300 ms subindo de 0 até o ruído: o aquecimento não para no meio da subida, e o piso não
        # fica com os quadros baixos do fade.
        piso = NoiseFloorTracker()
        for i in range(30):
            piso.update(0.032 * (i + 1) / 30, 0.01)
        for _ in range(400):
            piso.update(0.032, 0.01)
        self.assertGreater(len(piso.noise_samples), 30)
        self.assertAlmostEqual(0.032, piso.ambient_noise_floor)

    def test_microfone_mudo_sai_do_aquecimento_aos_2_s(self):
        piso = NoiseFloorTracker()
        for _ in range(250):
            piso.update(0.0, 0.01)
        self.assertEqual([], piso.noise_samples)
        self.assertFalse(piso.calibrando)
        self.assertEqual(0.0, piso.ambient_noise_floor)  # limiares base

    def test_silencio_digital_do_comeco_nao_entra_no_aquecimento(self):
        piso = NoiseFloorTracker()
        for _ in range(12):
            piso.update(0.0, 0.01)
        for _ in range(200):
            piso.update(0.032, 0.01)
        self.assertEqual(15, len(piso.noise_samples))
        self.assertAlmostEqual(0.032, piso.ambient_noise_floor)

    def test_zeros_frequentes_zeram_o_piso_e_ele_volta(self):
        # Supressão de ruído ou queda: 20% de zeros nos últimos 3 s valem os limiares base. Quando
        # os zeros saem da janela, o piso volta ao ruído.
        piso = self._calibrado()
        for i in range(300):
            piso.update(0.0 if i % 5 == 0 else 0.032, 0.01)
        self.assertEqual(0.0, piso.ambient_noise_floor)
        self.assertEqual((0.009, 0.005), piso.get_adaptive_thresholds(0.009, 0.005))
        for _ in range(300):
            piso.update(0.032, 0.01)
        self.assertAlmostEqual(0.032, piso.ambient_noise_floor)

    def test_queda_no_meio_nao_muda_o_nivel_do_piso(self):
        # 1 s de zeros: o nível vai a 0 (é silêncio), e o piso de ruído medido continua o mesmo.
        piso = self._calibrado()
        for _ in range(100):
            piso.update(0.0, 0.01)
        self.assertEqual(0.0, piso.nivel)
        self.assertAlmostEqual(0.032, piso._ordenados[int(piso.percentil * (len(piso._ordenados) - 1))])
        self.assertAlmostEqual(0.032, piso._ordenados[0])

    def test_quadro_vazio_nao_conta(self):
        # len(indata) / taxa = 0: sem tempo nem som, ele não pode valer 20 ms de ruído.
        piso = NoiseFloorTracker()
        for _ in range(20):
            piso.update(0.5, 0.0)
        self.assertEqual(([], 0.0, 0.0, 0.0), (piso.noise_samples, piso.ambient_noise_floor, piso.nivel, piso.pico))

    def test_nan_e_inf_contam_como_silencio_digital(self):
        piso = self._calibrado()
        for i in range(600):
            piso.update(float("nan") if i % 40 == 0 else (float("inf") if i % 40 == 20 else 0.032), 0.01)
        self.assertAlmostEqual(0.032, piso.ambient_noise_floor)
        self.assertTrue(all(math.isfinite(v) for v in piso._ordenados))
        self.assertEqual(sorted(v for v, _ in piso._janela), piso._ordenados)
        self.assertFalse(piso.houve_fala_acima(1.0))

    def test_decisao_espera_o_piso_ter_amostras(self):
        # Depois do aquecimento, o p10 de poucos quadros é o mínimo deles, baixo demais: a decisão
        # espera 16 quadros e 0,5 s.
        for dt, depois_do_aquecimento in ((0.010, 50), (0.032, 16)):
            with self.subTest(dt=dt):
                piso = NoiseFloorTracker()
                while piso._aquecendo:
                    piso.update(0.032, dt)
                for _ in range(depois_do_aquecimento - 1):
                    piso.update(0.032, dt)
                self.assertTrue(piso.calibrando)
                piso.update(0.032, dt)
                self.assertFalse(piso.calibrando)

    def test_piso_desce_quando_a_fala_do_comeco_para(self):
        # Fala logo no começo: o aquecimento mede a fala, e o piso desce quando vem o ruído.
        piso = NoiseFloorTracker()
        for _ in range(100):
            piso.update(0.15, 0.01)
        alto = piso.ambient_noise_floor
        for _ in range(200):
            piso.update(0.032, 0.01)
        self.assertGreater(alto, 0.1)
        self.assertAlmostEqual(0.032, piso.ambient_noise_floor)

    def test_fala_longa_nao_arrasta_o_piso(self):
        # 30 s de fala com 8% de pausas: o piso (p5 de 10 s) fica no ruído das pausas, não sobe
        # com a fala. Com o p10 de 3 s, ele ia para dentro da fala, e o ditado era cortado no meio.
        piso = self._calibrado()
        for _ in range(250):
            for _ in range(11):
                piso.update(0.2, 0.01)
            piso.update(0.032, 0.01)
        self.assertAlmostEqual(0.032, piso.ambient_noise_floor)

    def test_nivel_e_a_mediana_baixa_recente(self):
        # Maioria estrita: metade da janela de 200 ms alta não é fala.
        piso = self._calibrado()
        for _ in range(10):
            piso.update(0.3, 0.01)
        self.assertAlmostEqual(0.032, piso.nivel)
        piso.update(0.3, 0.01)
        self.assertAlmostEqual(0.3, piso.nivel)

    def test_clique_e_bipe_do_comeco_nao_entram_no_pico(self):
        # Achado do 2º juiz: o clique e o bipe espalhados pelos quadros somavam a maioria da janela,
        # e a gravação ia antes de a pessoa falar. Os primeiros 0,4 s ficam fora do pico.
        piso = NoiseFloorTracker()
        for volume in [0.3] * 15 + [0.2] * 15 + [0.032] * 200:
            piso.update(volume, 0.01)
        fala, _ = piso.get_adaptive_thresholds(0.009, 0.005)
        self.assertFalse(piso.houve_fala_acima(fala))

    def test_pico_pega_a_fala_da_calibracao_depois_do_comeco(self):
        # Fala de 0,4 a 0,8 s, quando nada é decidido ainda: o pico a guarda para quando o piso for
        # conhecido.
        piso = NoiseFloorTracker()
        for volume in [0.032] * 40 + [0.15] * 40:
            piso.update(volume, 0.01)
            calibrava = piso.calibrando
        for _ in range(200):
            piso.update(0.032, 0.01)
        self.assertTrue(calibrava or piso.houve_fala_acima(0.1))
        self.assertTrue(piso.houve_fala_acima(0.1))
        self.assertFalse(piso.houve_fala_acima(0.2))

    def test_limiares_3_3x_e_2_2x_o_piso(self):
        # O piso é o p5 (o mais quieto do ruído): na C920, 0,021. Silêncio a 2,2x (0,046, ~1,45x
        # a mediana do ruído); com 1,5x (~1x a mediana), o ruído passava do limiar e o silêncio
        # não fechava.
        piso = NoiseFloorTracker()
        piso.ambient_noise_floor = 0.021
        fala, silencio = piso.get_adaptive_thresholds(0.009, 0.005)
        self.assertAlmostEqual(0.0693, fala)
        self.assertAlmostEqual(0.0462, silencio)

    def test_sussurro_respeita_o_piso(self):
        piso = NoiseFloorTracker()
        piso.ambient_noise_floor = 0.021
        self.assertEqual(piso.get_adaptive_thresholds(0.009, 0.005),
                         piso.get_adaptive_thresholds(0.009, 0.005, is_whisper=True))
        piso.ambient_noise_floor = 0.0
        fala, silencio = piso.get_adaptive_thresholds(0.009, 0.005, is_whisper=True)
        self.assertAlmostEqual(0.009 * 0.45, fala)
        self.assertAlmostEqual(0.005 * 0.45, silencio)


if __name__ == "__main__":
    unittest.main()
