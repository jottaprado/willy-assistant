"""
Testes de taxa de amostragem variável.

Os testes de áudio que já existiam constroem sempre `AudioManager(sample_rate=16000)`, e
o construtor faz `actual_sample_rate = sample_rate`. Isso significa que todos eles só
exercitam o caso degenerado em que as duas taxas coincidem — justamente o caso em que
nenhum dos bugs de taxa aparece. Eles continuam verdes quando o código erra.

Aqui as duas taxas divergem de propósito, que é o que acontece de verdade quando o
microfone recusa 16000 e cai para 48000 pela escada de fallback.

Primeiro arquivo do repositório a simular o sounddevice: nenhum hardware é tocado.
"""

import ast
import os
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from core import CHANNELS, SAMPLE_RATE
from core.audio import AudioManager
from core.audio_processing.dsp import reamostrar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIC = 0
SISTEMA = 1

# O microfone só aceita 48000; a placa de "Mixagem Estéreo" só aceita 16000.
# É o cenário que produzia reunião acelerada e cortada em um terço.
TAXAS_ACEITAS = {MIC: {48000}, SISTEMA: {16000}}
TAXAS_NATIVAS = {MIC: 48000, SISTEMA: 16000}


def _consulta_device(idx, *args, **kwargs):
    return {"default_samplerate": TAXAS_NATIVAS.get(idx, 44100)}


def _abre_stream(samplerate=None, device=None, **kwargs):
    if samplerate not in TAXAS_ACEITAS.get(device, {16000}):
        raise RuntimeError(f"device {device} não suporta {samplerate} Hz")
    stream = MagicMock()
    stream.samplerate = samplerate
    return stream


class BaseAudioSimulado(unittest.TestCase):
    def setUp(self):
        self.p_stream = patch("core.audio.sd.InputStream", side_effect=_abre_stream)
        self.p_query = patch("core.audio.sd.query_devices", side_effect=_consulta_device)
        self.mock_stream = self.p_stream.start()
        self.p_query.start()
        self.addCleanup(self.p_stream.stop)
        self.addCleanup(self.p_query.stop)

        self.mgr = AudioManager(sample_rate=16000, channels=1,
                                device_index=MIC, system_device_index=SISTEMA)


class TestNegociacaoDeTaxa(BaseAudioSimulado):
    def test_microfone_cai_para_a_taxa_nativa(self):
        """A taxa nominal continua 16000; a real passa a ser a que o device aceitou."""
        self.mgr.ensure_stream(lambda *a: None)
        self.assertEqual(16000, self.mgr.sample_rate)
        self.assertEqual(48000, self.mgr.actual_sample_rate)

    def test_stream_abre_com_quadros_de_20_ms_na_taxa_aceita(self):
        """O corte por silêncio foi medido com quadros de 20 ms. Sem o blocksize, o tamanho era o
        do driver; com 64 ms ou mais, a fala logo no começo podia ser cancelada (2º juiz do 7A)."""
        self.mgr.ensure_stream(lambda *a: None)
        aceito = next(c for c in self.mock_stream.call_args_list if c.kwargs["samplerate"] == 48000)
        self.assertEqual(960, aceito.kwargs["blocksize"])

    def test_stream_do_sistema_parte_da_taxa_real_do_microfone(self):
        """A primeira tentativa tem que ser a taxa REAL do mic, não a nominal.

        Usar a nominal era o bug: o mic ia a 48000 e o sistema abria a 16000.
        """
        self.mgr.ensure_stream(lambda *a: None)
        self.mock_stream.reset_mock()
        self.mgr.start_recording("meeting")

        taxas_tentadas = [c.kwargs["samplerate"] for c in self.mock_stream.call_args_list
                          if c.kwargs.get("device") == SISTEMA]
        self.assertEqual(48000, taxas_tentadas[0],
                         "a primeira tentativa deveria ser a taxa real do microfone")

    def test_stream_do_sistema_tem_escada_de_fallback(self):
        """Antes esta stream não tinha fallback: recusa em 16000 a fazia sumir calada."""
        self.mgr.ensure_stream(lambda *a: None)
        self.mgr.start_recording("meeting")
        self.assertIsNotNone(self.mgr.system_stream,
                             "a captura do sistema não deveria ter sido descartada")
        self.assertEqual(16000, self.mgr.system_actual_sample_rate)

    def test_taxa_real_e_abertura_estao_prontas_no_instante_do_start(self):
        """AUD-016: O PortAudio pode disparar o 1º callback dentro de stream.start().
        actual_sample_rate e aberturas_do_microfone já precisam valer antes de start()."""
        observado_no_start = {}

        def _abre_e_checa_no_start(samplerate=None, device=None, **kwargs):
            if samplerate not in TAXAS_ACEITAS.get(device, {16000}):
                raise RuntimeError(f"device {device} não suporta {samplerate} Hz")
            stream = MagicMock()
            stream.samplerate = samplerate

            def _no_start():
                observado_no_start["taxa"] = self.mgr.actual_sample_rate
                observado_no_start["aberturas"] = self.mgr.aberturas_do_microfone

            stream.start.side_effect = _no_start
            return stream

        self.mock_stream.side_effect = _abre_e_checa_no_start
        self.mgr.ensure_stream(lambda *a: None)
        self.assertEqual({"taxa": 48000, "aberturas": 1}, observado_no_start)
        self.assertEqual(48000, self.mgr.actual_sample_rate)
        self.assertEqual(1, self.mgr.aberturas_do_microfone)

    def test_falha_no_start_restaura_taxa_e_aberturas(self):
        """AUD-016: Se stream.start() falhar em todas as taxas, actual_sample_rate e
        aberturas_do_microfone não podem ficar sujos."""
        def _abre_mas_falha_no_start(samplerate=None, device=None, **kwargs):
            stream = MagicMock()
            stream.start.side_effect = RuntimeError("PortAudio start error")
            return stream

        self.mock_stream.side_effect = _abre_mas_falha_no_start
        self.assertFalse(self.mgr.ensure_stream(lambda *a: None))
        self.assertEqual(16000, self.mgr.actual_sample_rate)
        self.assertEqual(0, self.mgr.aberturas_do_microfone)

    def test_religar_stream_pausado_incrementa_aberturas_antes_do_start(self):
        """AUD-016: Ao religar um stream pausado em ensure_stream, aberturas_do_microfone
        já está incrementado quando stream.start() roda."""
        self.mgr.ensure_stream(lambda *a: None)
        self.assertEqual(1, self.mgr.aberturas_do_microfone)
        self.mgr.stream.active = False

        observado_no_restart = []
        self.mgr.stream.start.side_effect = lambda: observado_no_restart.append(
            self.mgr.aberturas_do_microfone
        )
        self.mgr.ensure_stream(lambda *a: None)
        self.assertEqual([2], observado_no_restart)
        self.assertEqual(2, self.mgr.aberturas_do_microfone)


class TestMixagemDeReuniao(BaseAudioSimulado):
    def _grava_reuniao(self, segundos_mic, segundos_sistema):
        self.mgr.ensure_stream(lambda *a: None)
        self.mgr.start_recording("meeting")
        taxa_mic = self.mgr.actual_sample_rate
        taxa_sis = self.mgr.system_actual_sample_rate
        if segundos_mic:
            self.mgr.buffer.append(
                np.full((int(taxa_mic * segundos_mic), 1), 0.10, dtype=np.float32))
        if segundos_sistema:
            self.mgr.system_buffer.append(
                np.full((int(taxa_sis * segundos_sistema), 1), 0.20, dtype=np.float32))
        return self.mgr.stop_recording()

    def test_taxas_divergentes_sao_igualadas_antes_de_somar(self):
        """1 s de cada lado tem que virar 1 s de mix, não um terço.

        A mixagem soma amostra a amostra e trunca pelo menor. Sem igualar as taxas,
        1 s a 48000 somado com 1 s a 16000 produzia 16000 amostras — um terço da
        reunião, com a trilha do sistema três vezes mais rápida. E sem erro nenhum.
        """
        audio, modo = self._grava_reuniao(segundos_mic=1.0, segundos_sistema=1.0)
        self.assertEqual("meeting", modo)
        self.assertEqual(48000, len(audio),
                         "o mix deveria cobrir 1 s inteiro na taxa real do microfone")

    def test_mix_contem_as_duas_trilhas(self):
        """Amplitude do mix tem que refletir a soma, senão uma das trilhas sumiu."""
        audio, _ = self._grava_reuniao(segundos_mic=1.0, segundos_sistema=1.0)
        # 0.10 do microfone + 0.20 do sistema, longe das bordas da interpolação.
        self.assertAlmostEqual(0.30, float(audio[24000, 0]), places=3)

    def test_trilha_do_sistema_sobrevive_a_microfone_mudo(self):
        """Reunião inteira no mudo não pode virar gravação descartada.

        `if not raw_buffer: return None` jogava fora a trilha do sistema junto.
        """
        resultado = self._grava_reuniao(segundos_mic=0, segundos_sistema=1.0)
        self.assertIsNotNone(resultado, "a gravação foi descartada apesar de haver áudio")
        audio, modo = resultado
        self.assertEqual("meeting", modo)
        self.assertEqual(48000, len(audio),
                         "a trilha do sistema deveria vir reamostrada para a taxa do mic")

    def test_cauda_do_microfone_sobrevive_ao_fim_da_captura_do_sistema(self):
        """Quem fala depois que a captura do sistema para não pode sumir da ata.

        A mixagem cortava pela trilha mais curta. Como as duas streams não abrem nem
        fecham no mesmo instante, o excedente da mais longa era descartado em silêncio.
        """
        audio, _ = self._grava_reuniao(segundos_mic=2.0, segundos_sistema=1.0)
        self.assertEqual(96000, len(audio), "os 2 s de microfone deveriam ter sobrevivido")
        # No segundo final só há microfone: o sistema entra como silêncio, não como corte.
        self.assertAlmostEqual(0.10, float(audio[72000, 0]), places=3)

    def test_cauda_do_sistema_sobrevive_ao_microfone_curto(self):
        """O mesmo na direção oposta: microfone mudo no fim não trunca a reunião."""
        audio, _ = self._grava_reuniao(segundos_mic=1.0, segundos_sistema=2.0)
        self.assertEqual(96000, len(audio), "os 2 s do sistema deveriam ter sobrevivido")
        self.assertAlmostEqual(0.20, float(audio[72000, 0]), places=3)

    def test_sem_audio_nenhum_continua_devolvendo_none(self):
        self.assertIsNone(self._grava_reuniao(segundos_mic=0, segundos_sistema=0))


class TestTaxaViajaComOBuffer(unittest.TestCase):
    """Áudio que não veio do microfone carrega a própria taxa.

    É o caso do arquivo importado e do WAV relido do disco no retry offline: a taxa
    está no header, e antes era descartada em favor da taxa do microfone.
    """

    def setUp(self):
        self.mgr = AudioManager(sample_rate=16000, channels=1)
        # Simula o mic tendo caído para 48000: é daqui que vinha o header errado.
        self.mgr.actual_sample_rate = 48000

    def _taxa_do_wav(self, buf):
        buf.seek(0)
        _, sr = sf.read(buf, dtype="float32")
        return sr

    def test_convert_to_wav_respeita_a_taxa_recebida(self):
        wav = self.mgr.convert_to_wav(np.zeros(44100, dtype=np.float32), sample_rate=44100)
        self.assertEqual(44100, self._taxa_do_wav(wav))

    def test_convert_to_wav_sem_taxa_usa_a_do_microfone(self):
        wav = self.mgr.convert_to_wav(np.zeros(1000, dtype=np.float32))
        self.assertEqual(48000, self._taxa_do_wav(wav))

    def test_chunking_fatia_na_taxa_do_arquivo(self):
        """25 s a 44100 em blocos de 10 s: 3 pedaços de 10, 10 e 5 segundos.

        Lendo a taxa do microfone (48000), os cortes caíam nos lugares errados e o
        último bloco saía com duração diferente.
        """
        taxa = 44100
        audio = np.zeros(taxa * 25, dtype=np.float32)
        chunks = self.mgr.split_audio_into_chunks(audio, chunk_seconds=10, sample_rate=taxa)

        self.assertEqual(3, len(chunks))
        duracoes = []
        for c in chunks:
            c.seek(0)
            dados, sr = sf.read(c, dtype="float32")
            self.assertEqual(taxa, sr, "o header do bloco tem que repetir a taxa do arquivo")
            duracoes.append(round(len(dados) / sr))
        self.assertEqual([10, 10, 5], duracoes)

    def test_chunking_sem_taxa_usa_a_do_microfone(self):
        audio = np.zeros(48000 * 25, dtype=np.float32)
        chunks = self.mgr.split_audio_into_chunks(audio, chunk_seconds=10)
        self.assertEqual(3, len(chunks))
        self.assertEqual(48000, self._taxa_do_wav(chunks[0]))


class TestFonteDaTaxaNominal(unittest.TestCase):
    """A taxa nominal vem de core/config.py, não de um literal na assinatura.

    SAMPLE_RATE e CHANNELS eram exportados por core/__init__.py e não tinham um único
    consumidor no repositório inteiro: a verdade morava num default mágico do
    AudioManager. Constante pública que ninguém lê é pior do que constante nenhuma,
    porque quem edita acredita ter mudado alguma coisa.

    A verificação é por AST de propósito. Comparar valores passaria com o literal de
    volta, já que os dois são 16000 — o que precisa ser verdade é que o default seja
    uma REFERÊNCIA ao módulo de configuração.
    """

    def _defaults_do_construtor(self):
        from tests.test_static_analysis import _carregar

        arvore = _carregar(os.path.join("core", "audio.py"))
        classe = next(n for n in arvore.body
                      if isinstance(n, ast.ClassDef) and n.name == "AudioManager")
        init = next(n for n in classe.body
                    if isinstance(n, ast.FunctionDef) and n.name == "__init__")
        # os defaults casam com os últimos parâmetros posicionais
        nomes = [a.arg for a in init.args.args][-len(init.args.defaults):]
        return dict(zip(nomes, init.args.defaults))

    def test_defaults_referenciam_o_config(self):
        defaults = self._defaults_do_construtor()
        for parametro, esperado in (("sample_rate", "SAMPLE_RATE"), ("channels", "CHANNELS")):
            no = defaults.get(parametro)
            self.assertIsInstance(
                no, ast.Name,
                f"o default de '{parametro}' voltou a ser um literal; ele tem que "
                f"referenciar {esperado} de core/config.py",
            )
            self.assertEqual(esperado, no.id)

    def test_valores_conferem_com_o_config(self):
        mgr = AudioManager()
        self.assertEqual(SAMPLE_RATE, mgr.sample_rate)
        self.assertEqual(CHANNELS, mgr.channels)


class TestUmaUnicaNegociacao(unittest.TestCase):
    """Só um lugar no projeto pode abrir um InputStream negociando a taxa.

    Havia três cópias da mesma escada: o gravador, o teste de microfone das Configurações
    e o das Ferramentas. Duas delas começavam fixo em 16000, então o VU meter podia medir
    numa taxa enquanto a gravação rodava noutra — e o defeito era invisível justamente
    porque cada tela funcionava bem sozinha.

    Território não pega esse tipo de erro: as três cópias viviam em arquivos diferentes e
    nunca colidiam. Só uma regra sobre o repositório inteiro pega.
    """

    DONO = os.path.join("core", "audio.py")

    def _ocorrencias(self, agulha):
        from tests.test_static_analysis import ocorrencias_nos_modulos

        return ocorrencias_nos_modulos(agulha)

    def test_so_core_audio_abre_input_stream(self):
        fora = [f"{rel}:{n}" for rel, n in self._ocorrencias("sd.InputStream(")
                if rel != self.DONO.replace("\\", "/")]
        self.assertEqual(
            [], fora,
            "InputStream aberto fora de core/audio.py — use negociar_stream(), senão "
            f"esta cópia vai divergir da do gravador sem ninguém perceber: {fora}",
        )

    def test_a_escada_de_fallback_existe_uma_vez_so(self):
        locais = [f"{rel}:{n}" for rel, n in self._ocorrencias("48000, 44100")]
        self.assertEqual(
            1, len(locais),
            f"a escada de taxas foi duplicada; ela mora em negociar_stream: {locais}",
        )


class TestReamostragem(unittest.TestCase):
    def test_taxa_igual_devolve_o_mesmo_objeto(self):
        audio = np.zeros(10, dtype=np.float32)
        self.assertIs(audio, reamostrar(audio, 16000, 16000))

    def test_triplica_o_numero_de_amostras(self):
        audio = np.zeros((16000, 1), dtype=np.float32)
        self.assertEqual(48000, len(reamostrar(audio, 16000, 48000)))

    def test_preserva_o_numero_de_canais(self):
        audio = np.zeros((16000, 2), dtype=np.float32)
        saida = reamostrar(audio, 16000, 48000)
        self.assertEqual((48000, 2), saida.shape)

    def test_preserva_o_nivel_do_sinal(self):
        audio = np.full((16000, 1), 0.5, dtype=np.float32)
        saida = reamostrar(audio, 16000, 48000)
        self.assertAlmostEqual(0.5, float(saida[24000, 0]), places=5)

    def test_audio_manager_nao_define_wrappers_privados_redundantes(self):
        """AUD-018: AudioManager não mantém wrappers estáticos privados _reamostrar/_preencher."""
        from core.audio_processing.vad import compute_rms

        self.assertNotIn("_reamostrar", AudioManager.__dict__)
        self.assertNotIn("_preencher", AudioManager.__dict__)
        self.assertIs(compute_rms, AudioManager.compute_rms)


if __name__ == "__main__":
    unittest.main()
