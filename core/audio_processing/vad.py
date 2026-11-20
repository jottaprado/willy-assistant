"""
Detecção de Atividade de Voz (VAD), cálculo de RMS e rastreamento do piso de ruído adaptativo.
"""

import bisect
import math
import statistics
import sys
import threading
import time
from collections import deque

import numpy as np

# Duração de um quadro quando quem chama não diz (o callback diz: len(indata) / taxa).
_QUADRO_PADRAO_S = 0.02
# Abaixo disto o quadro é silêncio digital (o stream abrindo ou caindo, um microfone mudo ou com
# supressão de ruído), não ruído do ambiente.
ZERO_DIGITAL = 1e-4
_ZERO_DIGITAL = ZERO_DIGITAL
FATOR_FALA = 3.3
FATOR_SILENCIO = 2.2
LIMIAR_FALA_BASE = 0.009
LIMIAR_SILENCIO_BASE = 0.005
# A fala fora da janela do piso (Bloco 9): o nível acima do limiar de fala e deste mínimo, a não
# ser que o sinal dos últimos ~4 s esteja estável como ruído.
_VOZ_MINIMA_FORA_DO_PISO = 0.025
_JANELA_DE_ESTABILIDADE_S = 4.0
_ESPALHAMENTO_DE_RUIDO = 1.6
# O p75/p25 de poucos quadros oscila: com 2 s de quadros de 100 ms (20), a fala passava por
# estável, e o piso pulava para dentro dela. Com quadros de 20 ms (core/audio.py), são 200.
_QUADROS_PARA_ESTABILIDADE = 100
# Um som sem pausa por mais que isto entra no piso mesmo acima do limiar: música ou TV de fundo
# travavam o ditado para sempre. A fala respira antes. A conta é o som menos as pausas: a queda
# breve de uma música não a zera (zerando, uma pausa de 0,15 s a cada 8 s a travava).
_SOM_CONTINUO_MAX_S = 25.0
# Enquanto o ruído novo estiver estável, a janela do p5 encurta 10 s por segundo, até 1 s: em ~1 s
# o ruído velho saiu. Fora dele, ela volta a crescer 1 s por segundo, até janela_s.
_ENCURTA_POR_SEGUNDO = 10.0
_JANELA_DO_RUIDO_NOVO_S = 1.0


def compute_rms(indata: np.ndarray) -> float:
    """Calcula o nível RMS (Root Mean Square) do sinal de áudio."""
    if indata is None or len(indata) == 0:
        return 0.0
    try:
        return float(np.sqrt(np.mean(indata ** 2)))
    except (TypeError, ValueError, FloatingPointError):
        return 0.0


class NoiseFloorTracker:
    """Piso de ruído e nível de voz de uma gravação, para os limiares do corte por silêncio.

    O bug: o piso só saía da 3ª amostra e só era medido antes da primeira fala. Na webcam C920 do
    dono (ruído em silêncio: mínimo 0,023, mediana 0,032, p75 0,038; o .env em fala 0,009 e
    silêncio 0,005), o 1º quadro já passava do limiar fixo de fala: has_spoken travava em True,
    o piso nunca era medido e o limiar de silêncio ficava abaixo do próprio ruído. O ditado não
    terminava sozinho.

    Como funciona agora:
    - Aquecimento: os primeiros quadros (ao menos `min_samples` e `calibracao_s` de ruído) só
      medem. O piso vale desde a 1ª amostra (a mediana delas), mas nada vira fala. Ele se
      estende enquanto o nível ainda sobe (o microfone acordando, um fade-in, o ganho automático),
      até `calibracao_max_s` de gravação, e o silêncio digital do stream abrindo não conta.
    - Depois dele, o piso é o p5 (interpolado) dos quadros de ruído dos últimos `janela_s` (10 s),
      a gravação inteira: os mais silenciosos, o ruído puro que sempre há entre as palavras (com o
      p10 de 3 s, o ditado era cortado no meio). A decisão espera `piso_min_quadros` e
      `piso_min_s` depois do aquecimento: com menos, o p5 é o mínimo de poucos quadros, baixo
      demais, e o ruído alto passava do limiar de fala.
    - O quadro dentro de fala (nível suavizado acima do limiar de fala e de 0,025) não entra na
      janela do p5: o ruído de antes da fala fica nela, e a fala contínua de 30 s não arrasta mais
      o piso para dentro dela (cortava 8 em 30). Duas saídas, para nada travar o ditado: o sinal
      estável como ruído nos últimos ~4 s entra, e, se o nível dele já passa do limiar de
      silêncio (um ventilador que ligou), a janela encurta até ele virar o piso, em ~2 s (antes,
      ~10 s); e um som sem pausa por mais de 25 s (música, TV) volta a entrar.
    - Silêncio digital em `fracao_de_zeros` ou mais dos últimos `janela_de_zeros_s` (microfone
      mudo, supressão de ruído que zera as pausas, uma queda) zera o piso, e valem os limiares
      base: o silêncio de verdade é zero, e o piso medido só na fala não deixava nada virar fala.
    - O nível de voz é a mediana baixa dos últimos `suave_s` (vence a maioria estrita): um quadro
      solto do ruído não zera a contagem do silêncio.
    - O pico guarda o maior nível da gravação, aquecimento incluído, menos o começo
      (`inicio_ignorado_s`): a fala que veio antes de o piso ser conhecido (logo no 1º quadro)
      conta quando ele é conhecido. O começo fica de fora porque nele caem o clique da tecla e o
      bipe de início (45 ms, espalhados por 2 ou 3 quadros): somados, eles viravam fala, e a
      gravação ia antes de a pessoa falar, ou só com ruído.
    - Fala acima de 3,3x o piso, silêncio abaixo de 2,2x. Na C920, o p5 do ruído é 0,021: fala
      a 0,069 e silêncio a 0,046, ~1,45x a mediana do ruído. Com 1,5x o p5 (~1x a mediana), o
      nível do próprio ruído passava do limiar, e a maioria dos ditados na C920 não terminava.
    """

    FATOR_FALA = 3.3
    FATOR_SILENCIO = 2.2

    def __init__(self, min_samples: int = 4, calibracao_s: float = 0.15, calibracao_max_s: float = 2.0,
                 subida_no_aquecimento: float = 1.25, suave_s: float = 0.20, suave_min: int = 5,
                 janela_s: float = 10.0, percentil: float = 0.05, piso_min_quadros: int = 16,
                 piso_min_s: float = 0.5, janela_de_zeros_s: float = 3.0, fracao_de_zeros: float = 0.10,
                 inicio_ignorado_s: float = 0.4):
        self.min_samples, self.calibracao_s, self.calibracao_max_s = min_samples, calibracao_s, calibracao_max_s
        self.subida_no_aquecimento = subida_no_aquecimento
        self.suave_s, self.suave_min = suave_s, suave_min
        self.janela_s, self.percentil = janela_s, percentil
        self.piso_min_quadros, self.piso_min_s = piso_min_quadros, piso_min_s
        self.janela_de_zeros_s, self.fracao_de_zeros = janela_de_zeros_s, fracao_de_zeros
        self.inicio_ignorado_s = inicio_ignorado_s
        self.reset()

    def reset(self) -> None:
        """Começa uma gravação nova: sem amostras, piso 0."""
        self.noise_samples: list[float] = []  # as do aquecimento
        self.ambient_noise_floor: float = 0.0
        self.nivel: float = 0.0
        self.pico: float = 0.0
        self._aquecendo = True
        self._tempo = 0.0
        self._tempo_aquecendo = 0.0
        self._quadros_do_suave = self.suave_min
        self._recentes: deque[tuple[float, float]] = deque()  # (volume, início) do nível e do pico
        self._depois: deque[tuple[bool, float]] = deque()      # (é zero, duração) depois do aquecimento
        self._tempo_depois = 0.0
        self._tempo_de_zeros = 0.0
        self._janela: deque[tuple[float, float]] = deque()     # (volume, duração) do p10
        self._tempo_da_janela = 0.0
        self._ordenados: list[float] = []
        self._estaveis: deque[tuple[float, float]] = deque()   # (volume, duração) dos últimos ~4 s
        self._tempo_estaveis = 0.0
        self._estaveis_ordenados: list[float] = []
        self._som_sem_pausa_s = 0.0  # há quanto tempo o nível não cai abaixo do limiar de silêncio
        self._limite_da_janela_s = self.janela_s
        self._em_fala = False  # a fala que fica fora da janela do piso, com histerese

    def _sinal_estavel(self) -> bool:
        """Os últimos ~4 s parecem ruído, não fala: o nível quase não varia (p75/p25 baixo). Um
        ventilador fica perto de 1,4; a fala, que sobe e desce a cada sílaba, perto de 2. Em 2 s,
        a fala lisa de 30 s passava por estável vez ou outra (2 em 20)."""
        ordenados = self._estaveis_ordenados
        if len(ordenados) < _QUADROS_PARA_ESTABILIDADE:
            return False
        p25 = ordenados[int(0.25 * (len(ordenados) - 1))]
        p75 = ordenados[int(0.75 * (len(ordenados) - 1))]
        return p25 > 0 and p75 / p25 <= _ESPALHAMENTO_DE_RUIDO

    def _acima(self, fator: float) -> bool:
        piso = self.ambient_noise_floor
        return piso > 0.001 and self.nivel > max(piso * fator, _VOZ_MINIMA_FORA_DO_PISO)

    def _acima_do_silencio(self) -> bool:
        return self._acima(self.FATOR_SILENCIO)

    def _quadro_de_fala_fora_do_piso(self) -> bool:
        """O quadro está dentro de fala e não entra na janela do piso. Numa fala contínua e lisa,
        de 30 s, o p5 subia para dentro dela, o limiar de silêncio passava a fala, e o ditado era
        cortado no meio.

        Fala é o nível suavizado (~200 ms) acima do limiar de fala, e não o quadro: o ruído entra
        inteiro. Pelo quadro, os quadros altos do próprio ruído saíam, o p5 descia, e o silêncio
        da C920 passava a ser fala. E acima do de fala, não do de silêncio: o que fica entre os
        dois (música baixa, um ruído que oscila) entra, e o piso o acompanha; pelo de silêncio, o
        ditado com música de fundo não terminava. Sinal estável entra mesmo alto (ver
        _ruido_novo), e um som que não pausa por mais de _SOM_CONTINUO_MAX_S também."""
        # Com a histerese do corte por silêncio: a fala começa acima do limiar de fala e só acaba
        # abaixo do de silêncio. Sem ela, com o piso alto de poucos quadros de ruído (a fala logo
        # no começo), as quedas da fala abaixo de 3,3x entravam, subiam o piso, que subia o limiar,
        # e mais fala entrava, até o ditado ser cortado (8 de 230 no juiz do Bloco 9).
        if self._acima(self.FATOR_FALA):
            self._em_fala = True
        elif not self._acima_do_silencio():
            self._em_fala = False
        return self._em_fala and not self._sinal_estavel() and self._som_sem_pausa_s < _SOM_CONTINUO_MAX_S

    def _ruido_novo(self) -> bool:
        """Os últimos ~4 s estão estáveis como ruído e acima do limiar de silêncio: o ruído mudou
        (um ventilador ligou), e o piso velho não deixaria o ditado terminar. Pela janela de 10 s,
        o ruído novo levava ~10 s para virar o piso; e, com a fala fora dela, ainda mais."""
        return self._sinal_estavel() and self._acima_do_silencio()

    @property
    def calibrando(self) -> bool:
        """Ainda não dá para decidir: o ruído sozinho não pode virar fala."""
        if self._aquecendo or len(self._recentes) < self._quadros_do_suave:
            return True
        return len(self._depois) < self.piso_min_quadros or self._tempo_depois < self.piso_min_s

    def _fim_do_aquecimento(self) -> bool:
        if self._tempo >= self.calibracao_max_s:
            return True
        amostras = self.noise_samples
        if len(amostras) < max(self.min_samples, 4) or self._tempo_aquecendo < self.calibracao_s:
            return False
        # Metade contra metade: com terços, em quadros de 10 ms, a flutuação do ruído encerrava o
        # aquecimento no meio de um fade-in, e os quadros baixos dele puxavam o piso para baixo.
        meio = len(amostras) // 2
        return statistics.median(amostras[meio:]) <= statistics.median(amostras[:meio]) * self.subida_no_aquecimento

    def update(self, volume: float, duracao_s: float | None = None) -> float:
        """Soma um quadro de `duracao_s` segundos (sem ela, ~20 ms); devolve o piso."""
        if duracao_s is not None and duracao_s <= 0:
            return self.ambient_noise_floor  # quadro vazio: nem tempo nem som
        if not math.isfinite(volume):
            volume = 0.0  # um NaN no bisect dessincronizava a janela e derrubava o stream
        dt = duracao_s or _QUADRO_PADRAO_S
        inicio, self._tempo = self._tempo, self._tempo + dt
        self._quadros_do_suave = max(self.suave_min, round(self.suave_s / dt))
        self._recentes.append((volume, inicio))
        while len(self._recentes) > self._quadros_do_suave:
            self._recentes.popleft()
        self.nivel = statistics.median_low(v for v, _ in self._recentes)
        if len(self._recentes) == self._quadros_do_suave and self._recentes[0][1] >= self.inicio_ignorado_s:
            self.pico = max(self.pico, self.nivel)
        zero = volume < _ZERO_DIGITAL
        if not zero:
            self._estaveis.append((volume, dt))
            self._tempo_estaveis += dt
            bisect.insort(self._estaveis_ordenados, volume)
            while len(self._estaveis) > 1 and self._tempo_estaveis > _JANELA_DE_ESTABILIDADE_S:
                antigo, duracao = self._estaveis.popleft()
                self._tempo_estaveis -= duracao
                del self._estaveis_ordenados[bisect.bisect_left(self._estaveis_ordenados, antigo)]

        if self._aquecendo:
            if not zero:
                self.noise_samples.append(volume)
                self._tempo_aquecendo += dt
                self.ambient_noise_floor = float(statistics.median(self.noise_samples))
            self._aquecendo = not self._fim_do_aquecimento()
            return self.ambient_noise_floor

        self._depois.append((zero, dt))
        self._tempo_depois += dt
        self._tempo_de_zeros += dt if zero else 0.0
        while len(self._depois) > 1 and self._tempo_depois > self.janela_de_zeros_s:
            era_zero, duracao = self._depois.popleft()
            self._tempo_depois -= duracao
            self._tempo_de_zeros -= duracao if era_zero else 0.0
        if not zero:
            if self._quadro_de_fala_fora_do_piso():
                self._som_sem_pausa_s += dt
            else:
                ruido_novo = self._ruido_novo()
                # O ruído velho sai mais rápido enquanto o novo estiver estável: em ~2 s, e não em
                # 10. Encurtando a janela, e não tirando quadros: a fala lisa passa por estável em
                # um quadro ou outro, e assim só perde o que tem mais de ~9 s (uma janela pequena,
                # de uma fala que começou cedo, fica inteira).
                if ruido_novo:
                    self._limite_da_janela_s = max(_JANELA_DO_RUIDO_NOVO_S,
                                                   self._limite_da_janela_s - dt * _ENCURTA_POR_SEGUNDO)
                else:
                    self._limite_da_janela_s = min(self.janela_s, self._limite_da_janela_s + dt)
                self._janela.append((volume, dt))
                self._tempo_da_janela += dt
                bisect.insort(self._ordenados, volume)
                while len(self._janela) > 1 and self._tempo_da_janela > self._limite_da_janela_s:
                    antigo, duracao = self._janela.popleft()
                    self._tempo_da_janela -= duracao
                    del self._ordenados[bisect.bisect_left(self._ordenados, antigo)]
                # Só a pausa desconta: o som que passou dos 25 s continua entrando.
                if ruido_novo:
                    self._som_sem_pausa_s = 0.0
                elif not self._acima_do_silencio():
                    self._som_sem_pausa_s = max(0.0, self._som_sem_pausa_s - dt)
        else:
            if not self._acima_do_silencio():
                self._em_fala = False
                self._som_sem_pausa_s = max(0.0, self._som_sem_pausa_s - dt)
        if self._tempo_de_zeros >= self.fracao_de_zeros * self._tempo_depois:
            self.ambient_noise_floor = 0.0
        elif self._ordenados:
            # Com a fala fora da janela, a fala logo no começo a deixa com poucos quadros de ruído.
            # Interpolado entre os dois postos vizinhos (como o numpy): com poucos quadros, um quadro
            # baixo que entrava pulava o piso um posto inteiro, e o limiar de silêncio junto.
            posicao = self.percentil * (len(self._ordenados) - 1)
            abaixo = int(posicao)
            acima = min(abaixo + 1, len(self._ordenados) - 1)
            fracao = posicao - abaixo
            self.ambient_noise_floor = (self._ordenados[abaixo] * (1 - fracao) + self._ordenados[acima] * fracao)
        # Sem quadro de ruído ainda (a fala começou junto com a gravação), o piso fica o do
        # aquecimento.
        return self.ambient_noise_floor

    def houve_fala_acima(self, limiar: float) -> bool:
        """O nível da gravação já passou de `limiar`. A fala que veio antes de o piso ser conhecido
        (logo no 1º quadro) só se revela quando ele é: sem isto, o ditado era cancelado pelos 7 s
        sem fala com a pessoa falando."""
        return self.pico > limiar

    def get_adaptive_thresholds(
        self,
        base_speech_th: float,
        base_silence_th: float,
        is_whisper: bool = False,
    ) -> tuple[float, float]:
        """
        Calcula os limiares dinâmicos adaptados ao nível real de ruído de fundo do ambiente.
        Evita cortes falsos ou travamento do silêncio em locais com ar-condicionado ou teclados.

        O modo sussurro baixa os limiares base, mas também respeita o piso: com os limiares fixos,
        num microfone de ruído alto, o silêncio ficava abaixo do ruído e o ditado não terminava.
        """
        if is_whisper:
            eff_speech, eff_silence = max(0.0025, base_speech_th * 0.45), max(0.0015, base_silence_th * 0.45)
        else:
            eff_speech, eff_silence = base_speech_th, base_silence_th

        floor = self.ambient_noise_floor
        if floor > 0.001:
            eff_speech = max(eff_speech, floor * self.FATOR_FALA)
            eff_silence = max(eff_silence, floor * self.FATOR_SILENCIO)
            if eff_silence >= eff_speech:
                eff_silence = eff_speech * 0.7
        return eff_speech, eff_silence


class PisoDeEscuta:
    """O ruído da escuta do "Ei Willy", fora da gravação: o p5 dos quadros dos últimos `janela_s`,
    a escuta inteira (o NoiseFloorTracker é de uma gravação, e zera a cada uma).

    O limiar de fala da escuta era o fixo x 1,3 (0,0117): na C920 (ruído ~0,032), todo bloco
    passava, e 1,8 s de ruído iam à Groq cerca de 33 vezes por minuto.

    Recomeça a cada abertura do microfone (`reset`), e o primeiro `descarte_s` de som de cada uma
    não conta: o fade-in e o ganho automático do microfone acordando ficavam na janela de 10 s, o
    p5 deles deixava o limiar no fixo, e o ruído voltava a ir à Groq.
    """

    FATOR_FALA = 3.0
    FATOR_DO_LIMIAR_FIXO = 1.3

    def __init__(self, janela_s: float = 10.0, percentil: float = 0.05, descarte_s: float = 1.0,
                 calibracao_s: float = 0.5):
        self.janela_s, self.percentil = janela_s, percentil
        self.descarte_s, self.calibracao_s = descarte_s, calibracao_s
        self.reset()

    def reset(self, abertura: int = 0) -> None:
        """Mede de novo, desde o começo: o microfone abriu (o app subindo, outro microfone)."""
        self.abertura = abertura
        self.piso = 0.0
        self._ouvido_s = 0.0
        self._janela: deque[tuple[float, float]] = deque()
        self._tempo = 0.0
        self._ordenados: list[float] = []

    @property
    def calibrando(self) -> bool:
        """Menos de `calibracao_s` de ruído medido: ainda não dá para saber o que é fala."""
        return self._tempo < self.calibracao_s

    def update(self, volume: float, duracao_s: float | None = None) -> float:
        """Soma um quadro da escuta; devolve o piso."""
        if (duracao_s is not None and duracao_s <= 0) or not math.isfinite(volume) or volume < _ZERO_DIGITAL:
            return self.piso
        dt = duracao_s or _QUADRO_PADRAO_S
        self._ouvido_s += dt
        if self._ouvido_s <= self.descarte_s:
            return self.piso
        self._janela.append((volume, dt))
        self._tempo += dt
        bisect.insort(self._ordenados, volume)
        while len(self._janela) > 1 and self._tempo > self.janela_s:
            antigo, duracao = self._janela.popleft()
            self._tempo -= duracao
            del self._ordenados[bisect.bisect_left(self._ordenados, antigo)]
        self.piso = self._ordenados[int(self.percentil * (len(self._ordenados) - 1))]
        return self.piso

    def limiar_de_fala(self, speech_threshold: float) -> float:
        """O limiar da escuta: o fixo x 1,3, ou 3x o ruído medido, o que for maior."""
        return max(speech_threshold * self.FATOR_DO_LIMIAR_FIXO, self.piso * self.FATOR_FALA)


# Harness (sala1/sala2): P=0,35 e hangover=600 ms (janela >= 0,35 nos últimos 600 ms) enviam H1/H2 em 6,84 s e mantêm H4 em -12 dB igual ao gate-off (0,86 s / 2,94 s).
LIMIAR_SILERO_VOZ = 0.35
HANGOVER_SILERO_S = 0.60
TAXA_SILERO = 16000
JANELA_AMOSTRAS_SILERO = 512


class PorteiroSilero:
    """Confirmação de voz via Silero VAD para o corte automático por silêncio (`auto_silence`).

    Processa o `indata` cru (antes do `gain_boost`) em mono a 16 kHz em janelas de 512 amostras
    (32 ms). Enquanto o modelo ainda estiver carregando, ou se falhar no boot ou durante o
    callback, fica inativo e deixa a regra atual de energia decidir sozinha sem quebrar o stream.
    """

    def __init__(
        self,
        sample_rate: int = 44100,
        modelo=None,
        prob_min: float = LIMIAR_SILERO_VOZ,
        hangover_s: float = HANGOVER_SILERO_S,
    ):
        self._lock = threading.RLock()
        self.sample_rate = int(sample_rate) if sample_rate else 44100
        self.prob_min = float(prob_min)
        self.hangover_s = float(hangover_s)
        from .dsp import ReamostradorStreaming

        self._reamostrador = ReamostradorStreaming(self.sample_rate, TAXA_SILERO)
        self._modelo = modelo
        self._desativado_por_erro = False
        self._erro_logado = False
        self._buffer_16k = np.zeros(0, dtype=np.float32)
        self._tempo = 0.0
        self._ultimo_confirmado_t: float | None = None
        self._pico_confirmado = 0.0

    @property
    def ativo(self) -> bool:
        """Indica se o modelo Silero está carregado e apto a filtrar quadros."""
        return self._modelo is not None and not self._desativado_por_erro

    def definir_modelo(self, modelo) -> None:
        """Define explicitamente a instância do modelo (ou None) e limpa flags de falha."""
        with self._lock:
            self._modelo = modelo
            self._desativado_por_erro = False
            self._erro_logado = False
            self.reset(self.sample_rate)

    def carregar_sincrono(self, fabrica_modelo=None) -> bool:
        """Carrega `SileroVAD(16000)` e registra uma linha com o estado e o tempo em stdout."""
        t0 = time.perf_counter()
        try:
            if fabrica_modelo is None:
                from silero_vad_lite import SileroVAD

                modelo = SileroVAD(TAXA_SILERO)
            else:
                modelo = fabrica_modelo()
            ms = round((time.perf_counter() - t0) * 1000.0)
            with self._lock:
                self._modelo = modelo
                self._desativado_por_erro = False
                self._erro_logado = False
                self._reamostrador.reset(self.sample_rate, TAXA_SILERO)
                self._buffer_16k = np.zeros(0, dtype=np.float32)
                self._tempo = 0.0
                self._ultimo_confirmado_t = None
                self._pico_confirmado = 0.0
            print(f"[VAD] Silero ativo (carregou em {ms} ms)")
            return True
        except Exception as e:  # noqa: BLE001 — fronteira defensiva de carregamento de modelo nativo/ONNX
            with self._lock:
                self._modelo = None
            print(f"[VAD] Silero indisponível: {e}")
            return False

    def carregar_em_background(self, fabrica_modelo=None) -> threading.Thread:
        """Dispara o carregamento do modelo em thread daemon (nunca na thread de áudio)."""
        t = threading.Thread(
            target=self.carregar_sincrono,
            kwargs={"fabrica_modelo": fabrica_modelo},
            daemon=True,
        )
        t.start()
        return t

    def reset(self, sample_rate: int | None = None) -> None:
        """Reseta o estado recorrente do Silero, o reamostrador e o buffer de janela."""
        with self._lock:
            if sample_rate is not None and sample_rate > 0:
                self.sample_rate = int(sample_rate)
            self._reamostrador.reset(self.sample_rate, TAXA_SILERO)
            self._buffer_16k = np.zeros(0, dtype=np.float32)
            self._tempo = 0.0
            self._ultimo_confirmado_t = None
            self._pico_confirmado = 0.0
            if self._modelo is not None and not self._desativado_por_erro:
                try:
                    self._modelo.reset()
                except Exception as e:  # noqa: BLE001 — fronteira defensiva: falha em C++/ONNX no reset
                    self._desativar_na_sessao(e)

    def _desativar_na_sessao(self, erro: Exception) -> None:
        self._desativado_por_erro = True
        self._modelo = None
        if not self._erro_logado:
            self._erro_logado = True
            print(
                f"[VAD] Silero falhou durante a captura e foi desativado na sessão: {erro!r}",
                file=sys.stderr,
            )

    def observar_bloco(
        self,
        indata: np.ndarray,
        duracao_s: float | None = None,
        nivel_suave: float = 0.0,
        inicio_ignorado_s: float = 0.4,
    ) -> bool:
        """Alimenta um bloco de áudio cru (antes do ganho) e devolve se há fala confirmada."""
        with self._lock:
            modelo = self._modelo
            if modelo is None or self._desativado_por_erro:
                return True

            if indata is None or len(indata) == 0:
                return self._confirmado_no_instante()

            dt = (
                duracao_s
                if (duracao_s is not None and duracao_s > 0)
                else (len(indata) / self.sample_rate if self.sample_rate else _QUADRO_PADRAO_S)
            )
            self._tempo += dt

            try:
                mono = np.asarray(indata, dtype=np.float32)
                if mono.ndim > 1:
                    mono = (
                        mono[:, 0]
                        if mono.shape[1] == 1
                        else np.mean(mono, axis=1, dtype=np.float32)
                    )
                else:
                    mono = mono.reshape(-1)
                if not np.all(np.isfinite(mono)):
                    mono = np.nan_to_num(mono, copy=True, nan=0.0, posinf=0.0, neginf=0.0)

                s16 = self._reamostrador.processar(mono)
                if len(s16) > 0:
                    if not np.all(np.isfinite(s16)):
                        s16 = np.nan_to_num(s16, copy=True, nan=0.0, posinf=0.0, neginf=0.0)
                    self._buffer_16k = (
                        np.concatenate([self._buffer_16k, s16])
                        if len(self._buffer_16k) > 0
                        else s16
                    )

                janela_n = int(
                    getattr(modelo, "window_size_samples", JANELA_AMOSTRAS_SILERO)
                    or JANELA_AMOSTRAS_SILERO
                )
                while len(self._buffer_16k) >= janela_n:
                    janela = np.ascontiguousarray(self._buffer_16k[:janela_n], dtype=np.float32)
                    self._buffer_16k = self._buffer_16k[janela_n:]
                    prob = float(modelo.process(memoryview(janela)))
                    if not math.isfinite(prob):
                        prob = 0.0
                    if prob >= self.prob_min:
                        self._ultimo_confirmado_t = self._tempo
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: falha em process() na thread de áudio
                self._desativar_na_sessao(e)
                return True

            confirmado = self._confirmado_no_instante()
            if confirmado and self._tempo >= inicio_ignorado_s and math.isfinite(nivel_suave):
                self._pico_confirmado = max(self._pico_confirmado, float(nivel_suave))
            return confirmado

    def _confirmado_no_instante(self) -> bool:
        return bool(
            self._ultimo_confirmado_t is not None
            and (self._tempo - self._ultimo_confirmado_t) <= self.hangover_s + 1e-9
        )

    def houve_fala_confirmada_acima(self, limiar: float) -> bool:
        """Verifica se houve fala confirmada pelo Silero acima de `limiar` (para `fala_acima`)."""
        with self._lock:
            if not self.ativo:
                return True
            return self._pico_confirmado > limiar
