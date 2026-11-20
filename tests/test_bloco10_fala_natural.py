"""
Bloco 10, fase 1: a fala natural vira texto limpo, e o ditado longo não leva mais 413.

Fenômenos de fala espontânea que passavam para o texto final:
- gaguejos de palavras fora da lista curta de 43 ("pesquisa Pesquisa a loja", "até até dois ou
  três arquivos", "consegue, consegue me dar um exemplo?", "Gostei, Gostei"), e o começo de
  palavra largado ("O, oi, Willy");
- o trecho que a pessoa mandou esquecer ("então vou ter que... Esqueça disso. É microfone");
- a maiúscula que o Whisper põe depois de uma vírgula ("E, Fica mais razoável");
- falsos começos e autocorreções ("minha última, a última versão"; "em um mercado, em um
  conjunto de mercados"), que o refino mantinha por "fidelidade total".
E no willy_errors.log: "Erro pipeline (send, bad_request): ... 413 Request Entity Too Large",
porque só a reunião fatiava o áudio acima de 20 MB.
"""

import io
import os
import shutil
import tempfile
import time
import unittest
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np

from core.audio_processing.dsp import convert_to_wav
from core.groq_service import FalhaDoLLM, GroqService
from core.pipeline import PipelineContext, TranscriptionPipeline
from core.pipeline import transcription_pipeline as tp
from core.pipeline.transcription_pipeline import _ATA_AUSENTE
from core.text_processing import TextProcessor
from tests.test_arquivo_externo import _AudioMgr
from tests.test_ux_pasta_hold_ctrl_k import _funcao_do_willy

limpar = TextProcessor.clean_filler_words


class _Casos(unittest.TestCase):
    def _conferir(self, casos):
        for entrada, esperado in casos:
            with self.subTest(entrada=entrada):
                self.assertEqual(esperado, limpar(entrada))


class TestGaguejoDeQualquerPalavra(_Casos):
    def test_casos_do_historico_do_dono(self):
        self._conferir([
            ("Vou na pesquisa Pesquisa a loja de novo.", "Vou na pesquisa a loja de novo."),
            ("Eu quero até até dois ou três arquivos.", "Eu quero até dois ou três arquivos."),
            ("Você consegue, consegue me dar um exemplo?", "Você consegue me dar um exemplo?"),
            ("E, Gostei, Gostei, Vale também.", "E, gostei, vale também."),
            ("O, oi, Willy.", "Oi, Willy."),
        ])

    def test_reticencias_e_tres_vezes(self):
        self._conferir([
            ("Eu acho... acho que dá.", "Eu acho que dá."),
            ("Até até até amanhã.", "Até amanhã."),
            ("eu eu acho que que vai dar certo", "Eu acho que vai dar certo"),
            ("A, amanhã a gente vê.", "Amanhã a gente vê."),
        ])

    def test_repeticao_que_e_a_propria_palavra_fica(self):
        self._conferir([
            ("Isso é muito, muito bom.",) * 2,
            ("Não, não precisa.",) * 2,
            ("Já já eu chego.",) * 2,
            ("Tchau tchau, pessoal.",) * 2,
            ("Ele para para descansar.",) * 2,
            ("Eu como como um leão.",) * 2,
            ("Fomos a Bora Bora nas férias.",) * 2,
            ("A versão 1 1 2 saiu.",) * 2,
            ("E, eu acho que sim.",) * 2,
        ])

    def test_dobra_gramatical_com_virgula_e_gaguejo(self):
        self._conferir([("Ele para, para de falar.", "Ele para de falar.")])

    def test_repeticao_que_o_juiz_achou_fica(self):
        # Juiz do Bloco 10: o gaguejo de qualquer palavra apagava a repetição que é a fala. Na
        # dúvida, a palavra fica: o gaguejo que sobra o refino ainda tira.
        self._conferir([
            ("O código é zero zero sete.",) * 2,
            ("O número é nove nove oito.",) * 2,
            ("Comprei maçã, maçã verde e banana.",) * 2,
            ("Café, café com leite e suco.",) * 2,
            # A quebra de linha separa itens: a lista ditada perdia a linha do "leite".
            ("Compras:\nleite\nleite condensado\npão", "Compras: leite\nLeite condensado\nPão"),
            ("Anotei A, B, B e C.",) * 2,
            ("Bora Bora é lindo.",) * 2,
            ("Walla Walla fica longe.",) * 2,
            ("Isso, isso, isso!",) * 2,
            ("Calma, calma.",) * 2,
            ("Ok, ok.",) * 2,
            ("Obrigado, obrigado mesmo.",) * 2,
            ("Para, para, para com isso!",) * 2,
            ("Vai, vai, vai!",) * 2,
            ("Ele foi embora... Embora eu não quisesse.",) * 2,
            ("I had had enough.",) * 2,
            ("Tipo O, o mais comum.",) * 2,
        ])

    def test_juiz_da_3a_rodada(self):
        self._conferir([
            # A repetida que fecha a frase é a fala.
            ("Quem sabe, sabe.",) * 2,
            ("O que é, é.",) * 2,
            ("Se tem, tem.",) * 2,
            # O item repetido em minúscula, com outro item depois.
            ("Deu positivo, positivo, negativo.",) * 2,
            ("Saiu cara, cara, coroa.",) * 2,
            ("Entendi, entendi.",) * 2,
            ("Beleza, beleza.",) * 2,
            ("Claro, claro, pode mandar.",) * 2,
            ("Entendi, entendi, vou fazer.",) * 2,
            ("Falei, falei, falei e ninguém ouviu.",) * 2,
            # A maiúscula do Whisper depois da pausa continua sendo gaguejo, também numa palavra fora
            # das comuns.
            ("E, Gostei, Gostei, Vale também.", "E, gostei, vale também."),
            ("Ela pesquisou, Pesquisou, depois saiu.", "Ela pesquisou, depois saiu."),
        ])

    def test_juiz_da_4a_rodada(self):
        self._conferir([
            # O nome dos dois lados da vírgula fica.
            ("Eu moro em Curitiba, Curitiba é bem fria.",) * 2,
            ("Liguei pro João, João atendeu na hora.",) * 2,
            # A repetida com a maiúscula do Whisper no fim da frase é gaguejo.
            ("Gostei, Gostei.", "Gostei."),
            ("Ela gostou, Gostou.", "Ela gostou."),
        ])

    def test_cada_condicao_das_regras(self):
        # Uma varredura por mutação em cada "e"/"ou" das regras: cada caso abaixo muda se a condição
        # dele sair.
        self._conferir([
            # O número repetido fica mesmo sem outro número depois; o "um" no fim do texto, não.
            ("Ficou dois dois no placar.",) * 2,
            ("Comprei um um", "Comprei um"),
            # A letra no meio da frase, também depois de vírgula.
            ("Notas: A, B, B, C.",) * 2,
            # O nome com a repetida em minúscula fica; a palavra comum com as duas maiúsculas, não.
            ("Eu moro em Curitiba, curitiba é fria.",) * 2,
            ("Comprei ações da Vale, vale a pena.",) * 2,
            ("Falei com ele e Gostei, Gostei muito.", "Falei com ele e Gostei muito."),
            # As duas maiúsculas com reticências não são outra frase.
            ("Ele saiu. Embora... Embora eu não quisesse.", "Ele saiu. Embora eu não quisesse."),
            # Só com espaço, não é item de lista nem a repetida que fecha a frase.
            ("Comprei maçã maçã verde e banana.", "Comprei maçã verde e banana."),
            ("Instalei o pacote pacote.", "Instalei o pacote."),
            # A minúscula depois da vírgula, sem outro item depois, é gaguejo.
            ("Instalei, instalei o pacote.", "Instalei o pacote."),
            # O gaguejo de sempre não é ênfase antes do "e".
            ("Falei com ela, ela e o irmão.", "Falei com ela e o irmão."),
        ])

    def test_cada_alternativa_das_regexes(self):
        self._conferir([
            # Dois pontos e o "…" de um caractere também separam o gaguejo.
            ("Eu acho.. acho que dá.", "Eu acho que dá."),
            ("Eu acho… acho que dá.", "Eu acho que dá."),
            # Parte de um nome de arquivo, antes ou depois do ponto, é outro termo.
            ("Abre o config.py py agora.",) * 2,
            ("Instala o vue vue.js agora.",) * 2,
            # O item de lista com três palavras, e o item seguido de vírgula.
            ("Comprei maçã, maçã verde bem madura e banana.",) * 2,
            ("Comprei maçã, maçã verde, banana e pera.",) * 2,
            # O começo largado também com reticências, e só antes da mesma letra.
            ("O... oi, Willy.", "Oi, Willy."),
            ("O, eu acho que sim.",) * 2,
        ])

    def test_juiz_da_12a_rodada(self):
        self._conferir([
            # A repetida em minúscula no começo da frase é gaguejo, também fora das palavras comuns.
            ("Instala instala o pacote.", "Instala o pacote."),
            ("Pesquisa pesquisa a loja.", "Pesquisa a loja."),
            # A exclamação longe da repetição ainda é exclamação.
            ("Vai, vai, vai, que a gente chega lá!",) * 2,
            ("Empurra empurra que o carro já vai pegar!",) * 2,
            # A ênfase antes do "mas" sem vírgula, e o item de lista antes do "ou".
            ("Tentei, tentei mas não deu.",) * 2,
            ("Liguei, liguei mas ninguém atendeu.",) * 2,
            ("Quer maçã, maçã verde ou banana?",) * 2,
            ("Pode ser café, café com leite ou chá.",) * 2,
        ])

    def test_janela_de_200_caracteres_da_exclamacao(self):
        # Juiz do Bloco 10, 19ª rodada: a regra da frase exclamativa olha 200 caracteres (_VIZINHANCA)
        # depois da repetição; a ~150 caracteres o "!" protege a repetição, e a ~250 caracteres (além
        # do limite declarado da janela) a repetição é removida.
        ate_150 = (
            " que a gente já está quase chegando no final da subida da serra com toda a equipe"
            " reunida para comemorar o resultado do trimestre inteiro agora mesmo!"
        )
        ate_250 = (
            " que a gente já está quase chegando no final da subida da serra com toda a equipe"
            " reunida para comemorar o resultado do trimestre inteiro depois de tantas semanas"
            " de trabalho intenso revisando cada detalhe do relatório antes da apresentação de amanhã!"
        )
        self.assertEqual(150, len(ate_150))
        self.assertEqual(251, len(ate_250))
        self._conferir([
            ("Empurra empurra" + ate_150, "Empurra empurra" + ate_150),
            ("Empurra empurra" + ate_250, "Empurra" + ate_250),
        ])

    def test_juiz_da_11a_rodada(self):
        self._conferir([
            # Os gaguejos de sempre, só com espaço, saem como antes do Bloco 10, também o "no no".
            ("Deixei no no armário.", "Deixei no armário."),
            ("Ele chegou no no horário.", "Ele chegou no horário."),
            # Com vírgula, a ênfase do inglês fica.
            ("No, no, I said no.",) * 2,
            # A letra repetida só com espaço fica, como na main.
            ("B B são as notas.",) * 2,
            ("X X marca o lugar.",) * 2,
        ])

    def test_juiz_da_5a_rodada(self):
        self._conferir([
            # Logo depois de outra vírgula, a maiúscula é a do Whisper, e não um nome.
            ("Ontem eu, Liguei, Liguei pro cliente.", "Ontem eu, Liguei pro cliente."),
            ("So, We, We need to go.", "So, We need to go."),
            # A vírgula no fim da linha de antes não é a pausa do Whisper: a maiúscula é a da linha.
            ("Moro em Londrina,\nCuritiba, Curitiba é fria.", "Moro em Londrina, Curitiba, Curitiba é fria."),
            ("I mean, The, The problem is here.", "I mean, The problem is here."),
            # O preço do "Gostei, Gostei.": com a maiúscula do Whisper, a repetida do fim sai.
            ("Quem sabe, Sabe.", "Quem sabe."),
        ])

    def test_regras_no_comeco_de_um_texto_maior_que_a_janela(self):
        # Juiz do Bloco 10, 18ª rodada: as regras olham 200 caracteres em volta; no começo de um ditado
        # maior que isso, a janela começa no começo do texto (sem o max(0, ...), ela dava a volta e
        # lia o fim do texto).
        resto = (" Depois disso a gente conversou sobre o cronograma do projeto, sobre as entregas da próxima"
                 " semana e sobre o orçamento que ainda precisa ser aprovado pela diretoria antes do fim do mês,"
                 " porque sem isso nada anda.")
        self.assertGreater(len(resto), 200)
        self._conferir([(t + resto, esperado + resto) for t, esperado in (
            ("Fica no Bloco A, apartamento 12, perto da portaria.",) * 2,
            ("O sangue dele é Tipo O, o mais comum de todos.",) * 2,
            ("Eu moro em Curitiba, Curitiba é bem fria no inverno.",) * 2,
            ("Liguei pro João, João atendeu na hora.",) * 2,
            ("Investi na Petrobras, Vale e Itaú no ano passado.",) * 2,
            ("Moro em Florianópolis, Me parece bom aqui.",) * 2,
            ("Ontem eu, Liguei, Liguei pro cliente de novo.", "Ontem eu, Liguei pro cliente de novo."),
        )])

    def test_transcricao_longa_com_muitas_repeticoes_e_rapida(self):
        # Cada repetição procurava o fim da frase no resto do texto inteiro: num trecho longo sem
        # pontuação, 38 s em 480 mil caracteres (a main, 0,3 s).
        texto = "palavra " * 60000
        inicio = time.perf_counter()
        limpar(texto)
        self.assertLess(time.perf_counter() - inicio, 5.0)

    def test_juiz_da_2a_rodada(self):
        self._conferir([
            # O termo com hífen é outro termo.
            ("Roda npm install react react-dom.",) * 2,
            ("Instala flask flask-cors e pytest pytest-cov.",) * 2,
            ("Usa o flask-cors cors no servidor.",) * 2,
            # Ênfase antes de "e" e "mas", e as concordâncias repetidas.
            ("Procurei, procurei e não achei.",) * 2,
            ("Tentei, tentei, mas não deu.",) * 2,
            ("Certo, certo.",) * 2,
            ("Sei, sei.",) * 2,
            # Os gaguejos de sempre, só com espaço, saem como antes do Bloco 10, mesmo com "!".
            ("Eu Eu acho que vai.", "Eu acho que vai."),
            ("Que que é isso!", "Que é isso!"),
            # Palavra comum não é item de lista nem nome.
            ("Eu quero até, até dois ou três.", "Eu quero até dois ou três."),
            ("Me manda o, o arquivo.", "Me manda o arquivo."),
            ("Vou Vou na festa amanhã.", "Vou na festa amanhã."),
        ])

    def test_um_e_artigo_menos_ao_lado_de_outro_numero(self):
        self._conferir([
            ("Comprei um, um carro novo.", "Comprei um carro novo."),
            ("O ramal é um um dois.",) * 2,
        ])


class TestListasPalavraAPalavra(_Casos):
    """Cada palavra das listas, num molde em que só a lista decide: sem a palavra, o resultado muda."""

    EXPRESSIVAS = ("muito", "muita", "muitos", "muitas", "bem", "não", "nao", "sim", "já", "ja", "logo", "tchau", "ha", "blá", "bla", "corre", "pega", "quero", "bye", "no", "very", "so", "isso", "calma", "ok", "okay", "obrigado", "obrigada", "oi", "olá", "ola", "opa", "ei", "nossa", "valeu", "parabéns", "cuidado", "socorro", "espera", "pera", "anda", "vamos", "certo", "sei", "entendi", "claro", "beleza")
    NUMEROS = ("zero", "um", "uma", "dois", "duas", "três", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze", "quatorze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa", "cem", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos", "mil", "meia")
    PEDEM_CONTINUACAO = ("que", "de", "do", "da", "dos", "das", "e", "ou", "mas", "a", "o", "as", "os", "um", "uma", "pra", "para", "pro", "com", "em", "no", "na", "nos", "nas", "por", "pelo", "pela", "se", "quando", "como", "porque", "vou", "vai", "vamos", "vão", "ia", "iam", "tenho", "tem", "temos", "preciso", "precisa", "quero", "queria", "posso", "pode", "era", "foi", "está", "estava")

    def test_repeticao_expressiva_fica(self):
        self._conferir([(f"Eu falei {w}, {w} pra ele.",) * 2 for w in self.EXPRESSIVAS])

    def test_numero_por_extenso_fica(self):
        self._conferir([(f"O código é {w} {w} sete.",) * 2 for w in self.NUMEROS])

    # As hesitações que a limpeza tira (uma de cada alternativa), e as que não são hesitação para ela.
    # Também as alongadas (juiz do Bloco 10, 15ª rodada).
    HESITACOES = ("éé", "ééé", "eeh", "eehh", "humm", "hhumm", "huumm", "uhm", "uhmm", "uuhm", "uhhm", "hm", "hmm", "hhm", "ã", "ãã", "ãh", "aah", "aahh", "umm", "uumm", "uhh", "uuhh", "err", "eerr")
    NAO_SAO_HESITACAO = ("eh", "ah", "h", "hu", "uh", "er", "hhum")

    def test_cada_hesitacao_da_limpeza_antes_da_retratacao(self):
        # Juiz do Bloco 10, 14ª rodada: depois da vírgula e só com espaço.
        self._conferir([(f"Eu vou ter que{sep}{h}... Esquece isso. Fica assim.", "Fica assim.")
                        for h in self.HESITACOES for sep in (", ", " ")])

    def test_o_que_nao_e_hesitacao_nao_retrata(self):
        for h in self.NAO_SAO_HESITACAO:
            for sep in (", ", " "):
                entrada = f"Eu vou ter que{sep}{h}... Esquece isso. Fica assim."
                with self.subTest(entrada=entrada):
                    self.assertIn("Esquece isso", limpar(entrada))

    def test_cada_palavra_que_pede_continuacao(self):
        self._conferir([(f"Ontem eu fui {w}... Esquece isso. Fica assim.", "Fica assim.") for w in self.PEDEM_CONTINUACAO])


class TestFragmentoSoNoComecoDaFrase(_Casos):
    """No meio da frase, o "A" e o "O" antes da vírgula são a letra, e não o começo largado."""

    def test_letra_no_meio_da_frase_fica(self):
        self._conferir([
            ("Moro no Bloco A, apartamento 12.",) * 2,
            ("Torre A, andar 3, apto 31.",) * 2,
            ("Classe A, alto padrão.",) * 2,
            ("Vitamina A, antioxidante.",) * 2,
        ])

    def test_no_comeco_da_frase_sai(self):
        self._conferir([
            ("O, oi, Willy.", "Oi, Willy."),
            ("Fechado. A, amanhã a gente vê.", "Fechado. Amanhã a gente vê."),
        ])


class TestRetratacaoDita(_Casos):
    def test_caso_do_historico_do_dono(self):
        self._conferir([(
            ("Eu só tenho um probleminha. Esse computador tá sem microfone, então vou ter que... "
            "Esqueça disso. É microfone, ele sai daqui. Tá."),
            "Eu só tenho um probleminha. É microfone, ele sai daqui. Tá.",
        )])

    def test_outros_marcadores_e_travessao(self):
        self._conferir([
            ("Vou mandar o arquivo pro — esquece isso. Manda o link.", "Manda o link."),
            ("Então, a gente faz o deploy e... Cancela isso. Espera o QA.", "Espera o QA."),
            ("O build quebrou e eu vou ter que... Esqueça disso. O build passou.", "O build passou."),
            # O marcador com "!", depois da meia-risca, e "esqueca" sem a cedilha.
            ("Eu vou ter que... Esquece isso! Fica assim.", "Fica assim."),
            ("Vou mandar o arquivo pro – esquece isso. Manda o link.", "Manda o link."),
            ("Eu vou ter que... Esqueca disso. Fica assim.", "Fica assim."),
        ])

    def test_marcador_que_e_o_recado_fica(self):
        # Juiz do Bloco 10, 2ª rodada: o marcador também pede algo ao leitor. Sem a frase parada numa
        # palavra que pede continuação, ou sem o ponto depois do marcador, fica tudo.
        self._conferir([
            ("O pedido 4512 entrou duplicado... Cancela isso, por favor, e me avisa.",) * 2,
            ("Tem uma cobrança indevida no cartão — cancela isso, por favor.",) * 2,
            ("Aquela reunião de amanhã... Esquece isso, foi cancelada.",) * 2,
            ("O pedido 4512 entrou duplicado... Cancela isso. Me avisa depois.",) * 2,
            ("O build quebrou e eu vou ter que... Esqueça disso, o build passou.",) * 2,
            ('Ele disse "vou ter que... Esquece isso, fica pra amanhã".',) * 2,
        ])

    def test_hesitacao_antes_das_reticencias(self):
        # Juiz do Bloco 10, 4ª rodada: o "né" ou o "ééé" entre a palavra que pede continuação e as
        # reticências deixavam a retratação passar.
        self._conferir([
            ("Eu vou ter que, né... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, ééé... Esquece isso. Fica assim.", "Fica assim."),
            ("Então a gente faz o deploy e, tipo... Cancela isso. Espera o QA.", "Espera o QA."),
            # Sem a palavra que pede continuação, o marcador continua sendo o recado.
            ("O pedido entrou duplicado, né... Cancela isso. Me avisa.",
             "O pedido entrou duplicado... Cancela isso. Me avisa."),
        ])

    def test_hesitacao_sozinha_nao_e_frase_interrompida(self):
        # Juiz do Bloco 10, 5ª rodada: o "é" da lista casava o começo do "ééé", e a frase do recado
        # sumia. O "é" e o "tá" depois da vírgula ou no começo da frase são a hesitação e o "ok". Igual
        # à main.
        self._conferir([
            ("O pedido entrou duplicado ééé... Cancela isso. Me avisa.",
             "O pedido entrou duplicado Cancela isso. Me avisa."),
            ("O pedido entrou duplicado, ééé... Cancela isso. Me avisa.",
             "O pedido entrou duplicado Cancela isso. Me avisa."),
            ("Ééé... Cancela isso. Obrigado.", "Cancela isso. Obrigado."),
            ("O pedido entrou duplicado, é... Cancela isso. Me avisa.",) * 2,
            ("Ah, tá... Cancela isso. Obrigado.",) * 2,
            ("É... Cancela isso. Obrigado.",) * 2,
            # As expressões feitas (juiz do Bloco 10, 6ª rodada).
            ("Então tá... Cancela isso. Obrigado.",) * 2,
            ("Pois é... Esquece isso. Bora.",) * 2,
            ("Ah tá... Cancela isso. Obrigado.",) * 2,
            ("Ok tá... Cancela isso. Obrigado.",) * 2,
            ("Okay tá... Cancela isso. Obrigado.",) * 2,
            ("Não é... Cancela isso. Obrigado.",) * 2,
            ("Ah é... Esquece isso. Bora.",) * 2,
        ])

    def test_e_e_ta_nao_pedem_continuacao(self):
        # Juiz do Bloco 10, 7ª rodada: a lista das expressões feitas não fechava ("Tudo bem tá...",
        # "Beleza tá...", "Sim é..."). O "é" e o "tá" saíram da lista: a frase parada neles fica,
        # como na main, e o refino vê o contexto.
        self._conferir([
            ("O problema é... Esquece isso. Funciona.",) * 2,
            ("O sistema tá... Esquece isso. Funciona.",) * 2,
            ("A senha não é... Esquece isso. Te mando por e-mail.",) * 2,
            ("Tudo bem tá... Cancela isso. Obrigado.",) * 2,
            ("Beleza tá... Cancela isso. Obrigado.",) * 2,
            ("Sim é... Esquece isso. Bora.",) * 2,
            # Nem depois de outra palavra da lista, só com espaço: é o verbo (juiz do Bloco 10, 8ª rodada).
            ("É o que é... Esquece isso. Bora.",) * 2,
            ("Deixa como é... Esquece isso. Tá bom.",) * 2,
            ("Eu acho que é... Esquece isso. Bora.",) * 2,
        ])

    def test_hesitacao_depois_da_palavra_que_pede_continuacao(self):
        self._conferir([
            ("Eu vou ter que, é... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que ééé... Esquece isso. Fica assim.", "Fica assim."),
            # As outras hesitações, só com espaço ou depois da vírgula (juiz do Bloco 10, 9ª rodada).
            ("Então a gente faz o deploy e tipo... Cancela isso. Espera o QA.", "Espera o QA."),
            ("Eu vou ter que né... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que hum... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que ãh... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, ãh... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, hum... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, é, é, é... Esquece isso. Fica assim.", "Fica assim."),
            # As hesitações alongadas, e o "éé", a fronteira com o verbo (juiz do Bloco 10, 10ª rodada).
            ("Eu vou ter que éé... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, éé... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que hummm... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, hummm... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que ãhh... Esquece isso. Fica assim.", "Fica assim."),
            ("Eu vou ter que, ãhh... Esquece isso. Fica assim.", "Fica assim."),
            # A hesitação entre duas reticências (o pedido #6 com o "ééé").
            ("Esse computador tá sem microfone, então vou ter que... ééé... Esqueça disso. É microfone.",
             "É microfone."),
            ("Eu vou ter que... ééé... esqueça disso. É microfone.", "É microfone."),
            # As reticências de um caractere só.
            ("Então vou ter que… ééé… Esqueça disso. É microfone.", "É microfone."),
        ])

    def test_frase_inteira_com_reticencias_no_meio_sai(self):
        self._conferir([("Então... vou ter que... Esqueça disso. É microfone.", "É microfone.")])

    def test_sem_a_interrupcao_ou_sem_fala_depois_fica(self):
        # Retratar uma frase completa, ou o marcador como o próprio pedido, é com o refino.
        self._conferir([
            ("Esqueça disso.",) * 2,
            ("Manda o arquivo. Esquece isso. Manda o link.",) * 2,
            ("Então vou ter que... Esqueça disso.",) * 2,
            ("Esqueça disso que eu falei ontem, o prazo é sexta.",) * 2,
        ])

    def test_so_os_marcadores_do_pedido(self):
        # Juiz do Bloco 10: "cancela tudo" e "deixa pra lá" também são recado ("O cliente desistiu"
        # era a mensagem), e o hífen separa item. Esses ficam para o refino.
        self._conferir([
            ("Sobre os pedidos da semana... Cancela tudo. O cliente desistiu.",) * 2,
            ("Eu ia te contar uma coisa... Deixa pra lá, depois a gente conversa.",) * 2,
            ("Item 3 - deixa pra lá, ninguém usa.",) * 2,
            ("Item 3 - esquece isso, ninguém usa.",) * 2,
        ])

    def test_palavra_repetida_com_maiuscula_nao_comeca_outra_frase(self):
        # Juiz do Bloco 10, 7ª rodada: as reticências antes da maiúscula do Whisper na palavra repetida
        # fechavam a frase de antes, e sobrava a interrompida sem o marcador.
        self._conferir([
            ("Esse computador tá sem microfone, então vou ter que... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Mandei com o... O... Esquece isso. Já foi.", "Já foi."),
            ("Fui ao banco e... E... Esquece isso. Fiquei em casa.", "Fiquei em casa."),
            # Com hesitação ou outra repetição no meio, com quatro pontos ou com o "…" do Whisper (juiz
            # do Bloco 10, 8ª rodada).
            ("Esse computador tá sem microfone, então vou ter que... é... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Esse computador tá sem microfone, então vou ter que... ééé... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Esse computador tá sem microfone, então vou ter que... Hum... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Esse computador tá sem microfone, então vou ter que... Que... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Esse computador tá sem microfone, então vou ter que.... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Esse computador tá sem microfone, então vou ter que… Que… Esqueça disso. É microfone.", "É microfone."),
            # Com espaço antes das reticências.
            ("Esse computador tá sem microfone, então vou ter que ... Que... Esqueça disso. É microfone.",
             "É microfone."),
            # Até 8 elos (juiz do Bloco 10, 9ª rodada).
            ("Esse computador tá sem microfone, então vou ter que... é... Que... Que... Esqueça disso. É microfone.",
             "É microfone."),
            ("Ficou tudo pronto. E... E... E... E... Esquece isso. Tá ótimo.", "Ficou tudo pronto. Tá ótimo."),
            ("Ficou tudo pronto. Vou ter que" + "... Que" * 8 + "... Esqueça disso. Tá ótimo.",
             "Ficou tudo pronto. Tá ótimo."),
            # A repetição na linha de baixo não junta as linhas: a de cima fica.
            ("Comprei pão e\nE... Esquece isso. Fiquei.", "Comprei pão e\nFiquei."),
            ("Comprei pão e...\nE... Esquece isso. Fiquei.", "Comprei pão e... Fiquei."),
            # Nem a hesitação só com espaço na linha de baixo (juiz do Bloco 10, 10ª rodada): igual à main.
            ("Comprei pão e\nhum... Esquece isso. Fiquei.", "Comprei pão e\nHum... Esquece isso. Fiquei."),
            ("Lista: leite e\ntipo... Esquece isso. Ovos.", "Lista: leite e\nTipo... Esquece isso. Ovos."),
            # Outra palavra depois das reticências é outra frase.
            ("Ele foi embora... Embora eu ia... Esquece isso. Ficou.", "Ele foi embora... Ficou."),
            # Só as reticências logo antes da interrompida, e não o ponto.
            ("Ele vai. Vai... Esquece isso. Ficou.", "Ele vai. Ficou."),
            ("Eu vou... Comprei pão e vou... Esquece isso. Fiquei.", "Eu vou... Fiquei."),
        ])

    def test_sequencia_longa_de_repeticoes_e_rapida(self):
        # Sem teto, cada começo percorria o resto da sequência sem o marcador no fim: 10,5 s só na
        # retratação, em 60 mil caracteres (com o teto, 0,03 s), e 176 s com o quádruplo.
        texto = "Eu vou ter que" + "... é... Que" * 5000 + "."
        inicio = time.perf_counter()
        limpar(texto)
        self.assertLess(time.perf_counter() - inicio, 5.0)

    def test_titulo_com_quebra_de_linha_fecha_a_frase(self):
        # Juiz do Bloco 10, 7ª rodada: o ponto do título não fechava a frase nem com a quebra de linha
        # depois, e "Liguei pro Dr..." saía junto.
        self._conferir([("Liguei pro Dr...\nVou... Esquece isso. Ele ligou.", "Liguei pro Dr... Ele ligou.")])

    def test_dois_pontos_depois_do_titulo_fecham_a_frase(self):
        # Só o ponto de um título não fecha a frase: os dois-pontos depois dele, sim.
        self._conferir([("Recado do Sr: Eu vou ter que... Esquece isso. Já foi.", "Recado do Sr: Já foi.")])

    def test_titulo_nao_e_o_comeco_da_frase(self):
        # "Sr." fechava a frase, e sobrava "Falei com o Sr. Já resolvi."
        self._conferir([
            ("Falei com o Sr. João e ele vai... Esquece isso. Já resolvi.", "Já resolvi."),
            ("Tudo certo. Falei com a Dra. Ana e... Cancela isso. Ela confirmou.", "Tudo certo. Ela confirmou."),
        ])

    def test_a_frase_completa_de_antes_fica(self):
        # Juiz do Bloco 10, 3ª rodada: a frase de antes terminada em reticências (antes de maiúscula),
        # em ponto antes de aspas ou parêntese, em dois-pontos, em "?", ou numa quebra de linha, saía
        # junto com a interrompida.
        self._conferir([
            ("O cliente reclamou de novo... Amanhã eu vou ter que... Esquece isso. Eu ligo hoje.",
             "O cliente reclamou de novo... Eu ligo hoje."),
            ('Ele disse "tudo certo." Agora eu vou ter que... Esquece isso. Já foi.', 'Ele disse "tudo certo." Já foi.'),
            ('Ele disse "vou..." Agora eu vou ter que... Esquece isso. Já foi.', 'Ele disse "vou..." Já foi.'),
            ("Mandei o arquivo (o PDF.) Agora eu vou ter que... Esquece isso. Já foi.",
             "Mandei o arquivo (o PDF.) Já foi."),
            ("Você viu? Agora eu vou ter que... Esquece isso. Já foi.", "Você viu? Já foi."),
            ("Comprei pão\nAgora eu vou ter que... Esquece isso. Já foi.", "Comprei pão\nJá foi."),
            ("Lista de compras: arroz, feijão e... Esquece isso. Só arroz.", "Lista de compras: Só arroz."),
            # A interrompida de uma palavra só: as reticências de antes fecham a frase vendo a
            # maiúscula dela (juiz do Bloco 10, 6ª rodada).
            ("Ficou tudo pronto... Mas... Esquece isso. Tá ótimo.", "Ficou tudo pronto... Tá ótimo."),
            ("Ficou tudo pronto... Mas... é... Esquece isso. Tá ótimo.", "Ficou tudo pronto... Tá ótimo."),
            ("Já mandei o arquivo pro cliente... E... ééé... Esquece isso. Depois te conto.",
             "Já mandei o arquivo pro cliente... Depois te conto."),
            ("O cliente reclamou de novo... Vou, é... Esquece isso. Eu ligo hoje.",
             "O cliente reclamou de novo... Eu ligo hoje."),
            ("Ficou tudo pronto… Mas… Esquece isso. Tá ótimo.", "Ficou tudo pronto… Tá ótimo."),
            # Duas frases completas antes: as duas ficam (juiz do Bloco 10, 7ª rodada).
            ("Bom dia. Tudo certo? Agora eu vou ter que... Esquece isso. Já foi.", "Bom dia. Tudo certo? Já foi."),
            # A hesitação no meio não leva as reticências que fecham a frase de antes.
            ("Terminei a parte um... ééé... Agora eu vou ter que... Esquece isso. Já foi.",
             "Terminei a parte um Já foi."),
        ])

    def test_outras_abreviaturas_podem_fechar_a_frase_de_antes(self):
        # Juiz do Bloco 10, 2ª rodada: sem o ponto de "etc.", "Ltda." ou da letra como fim de frase, a
        # frase completa de antes saía junto. Na dúvida, ela fica.
        self._conferir([
            ("Comprei pão, leite, etc. Depois fui ao banco e... Esquece isso. Fui pra casa.",
             "Comprei pão, leite, etc. Fui pra casa."),
            ("Moro no bloco A. Ontem eu fui e... Esquece isso. Fiquei em casa.", "Moro no bloco A. Fiquei em casa."),
            ("Trabalho na Acme Ltda. A gente ia... Esquece isso. Fiquei.", "Trabalho na Acme Ltda. Fiquei."),
        ])


class TestMaiusculaDepoisDaVirgula(_Casos):
    def test_casos_do_historico_do_dono(self):
        self._conferir([
            ("E, Fica mais razoável.", "E, fica mais razoável."),
            ("Faz sentido ter pequenas casas, Me parece fazer muito mais sentido.",
             "Faz sentido ter pequenas casas, me parece fazer muito mais sentido."),
            ("Olha, Tá funcionando agora.", "Olha, tá funcionando agora."),
            # O nome no começo da frase não é lista de nomes: o seguinte é palavra comum.
            ("Willy, Me ajuda com o PR.", "Willy, me ajuda com o PR."),
        ])

    def test_termo_do_vocabulario_fica(self):
        # Marca que também é palavra comum: só com o vocabulário dá para saber.
        frase = "Liguei pra operadora, Claro não atende."
        self.assertEqual(frase, limpar(frase, ["Claro", "Mercado Livre"]))
        self.assertEqual("Liguei pra operadora, claro não atende.", limpar(frase))
        self.assertEqual("Comprei ações, Vale subiu.", limpar("Comprei ações, Vale subiu.", ["Vale"]))

    def test_nomes_siglas_e_ingles_ficam(self):
        self._conferir([
            ("Ok, Willy, abre o PR.",) * 2,
            ("Moro em Curitiba, Paraná.",) * 2,
            ("Comprei no Paraguai, Mercado Livre e Amazon.",) * 2,
            ("Isso é comum no Brasil, Paraguai e Argentina.",) * 2,
            ("Usei a API, PIX e WHG.",) * 2,
            ("Então, I think so.",) * 2,
            ("Fui pra São Paulo, São Paulo é enorme.",) * 2,
            # Nome de duas palavras que começa com uma comum, só depois da vírgula.
            ("Eu moro no Brasil, São Paulo é enorme.",) * 2,
            ("Morei no centro, Bom Retiro fica perto.",) * 2,
            ("E, São coisas diferentes.", "E, são coisas diferentes."),
        ])

    def test_lista_de_nomes_que_tambem_sao_palavras_comuns(self):
        # "Vale" é verbo e é a empresa: depois de outro nome, na lista, é a empresa.
        self._conferir([
            ("Comprei ações da Petrobras, Vale e Itaú.",) * 2,
            ("A Vale anunciou o lucro, Vale subiu na bolsa.",) * 2,
        ])

    def test_transcricao_longa_com_muitas_virgulas_e_rapida(self):
        # Juiz do Bloco 10, 4ª rodada: cada vírgula antes de maiúscula copiava o texto inteiro até ela.
        texto = "Eu acho, Me parece que sim. " * 18000
        inicio = time.perf_counter()
        limpo = limpar(texto)
        self.assertLess(time.perf_counter() - inicio, 5.0)
        self.assertTrue(limpo.startswith("Eu acho, me parece que sim. Eu acho, me parece"))

    def test_comeco_da_linha_nao_e_comeco_da_frase(self):
        # Juiz do Bloco 10, 5ª rodada: o '\n' depois do rstrip() era código morto. Contar a quebra de
        # linha como começo da frase deixava o gaguejo e o fragmento mais agressivos no começo da
        # linha; ele saiu, e fica como na main.
        self._conferir([
            ("Compras:\nLeite, Leite condensado\nPão", "Compras: Leite, Leite condensado\nPão"),
            ("Ontem\nO, o carro quebrou.",) * 2,
            ("Primeira linha sem ponto\nRoberto, Me parece bom.",) * 2,
        ])

    def test_nome_de_duas_palavras_so_na_mesma_linha(self):
        # Juiz do Bloco 10, 14ª rodada: a maiúscula da linha de baixo não faz da palavra um nome.
        self._conferir([("Fico no aguardo, Obrigado\nJoão", "Fico no aguardo, obrigado\nJoão")])

    def test_dois_pontos_comecam_a_frase(self):
        # Juiz do Bloco 10, 11ª rodada: depois dos dois-pontos, o nome não abre uma lista de nomes.
        self._conferir([("Recado: Marcelo, Me manda o arquivo.", "Recado: Marcelo, me manda o arquivo.")])

    def test_nome_antes_da_virgula_protege_a_palavra_seguinte(self):
        # Juiz do Bloco 10, 15ª e 16ª rodadas: a regra não separa a lista de nomes que também são
        # palavras comuns do vocativo e do objeto. Na dúvida, a maiúscula depois de um nome no meio da
        # frase fica, como na main ("Em aberto").
        self._conferir([
            ("Investi em Itaú, Petrobras, Vale.",) * 2,
            ("As operadoras são Vivo, Tim, Claro.",) * 2,
            ("Comprei ações da Petrobras, Vale e outras.",) * 2,
            ("Trabalho em Palo Alto, Vale do Silício.",) * 2,
            ("Assisti Matrix, Tudo em Todo Lugar ao Mesmo Tempo e Duna.",) * 2,
            ("Ele comprou “Petrobras, Vale e Itaú”.",) * 2,
            # O nome visto no meio da frase, também na linha de cima, protege a mesma palavra depois.
            ("Comprei ações da\nVale. Ontem, Vale subiu.",) * 2,
            ("Oi João, Tudo bem?",) * 2,
            ("Liguei pro João, Ele não atendeu.",) * 2,
            # Limitação declarada ("Em aberto"), igual à main: o "São" de "São Paulo", visto no meio da
            # frase, protege o "São" verbo depois da vírgula (juiz do Bloco 10, 17ª rodada).
            ("Os voos para São Paulo atrasaram, São muitos passageiros esperando.",) * 2,
            # No começo da frase, o nome é o vocativo, e a palavra comum volta à minúscula.
            ("João, Olha, eu queria saber do relatório.", "João, olha, eu queria saber do relatório."),
            ("Marcelo, Então, o que você acha?", "Marcelo, então, o que você acha?"),
        ])

    def test_conclusao_e_explicacao_ficam_inteiras(self):
        self._conferir([
            ("Isso não tem imposto, ou seja, não vai sobrar margem.",) * 2,
            ("Quer dizer, o servidor caiu porque o disco encheu.",) * 2,
        ])


class TestVocabularioNoArquivoExterno(unittest.TestCase):
    """Juiz do Bloco 10, 11ª rodada: o "Transcrever arquivo" também protege os termos do vocabulário
    na limpeza (a marca que é palavra comum, depois da vírgula)."""

    def _transcrever(self, termos):
        groq = MagicMock()
        groq.transcribe_file.return_value = "Liguei pra operadora, Claro não atende."
        config = SimpleNamespace(groq_api_key="gsk_x", get_prompt_context=lambda: "ctx", input_language="pt",
                                 clean_fillers=True, get_vocab_terms=lambda: termos, private_mode=True,
                                 load_replacements=dict, save_output_file=MagicMock(return_value=None),
                                 save_history_item=MagicMock())
        transcrever = _funcao_do_willy(
            "transcrever_arquivo_externo", Optional=Optional, config_mgr=config, sound_mgr=MagicMock(),
            atualizar_ui=MagicMock(), audio_mgr=_AudioMgr(), groq_service=groq, TextProcessor=TextProcessor,
            FalhaDoLLM=FalhaDoLLM, _ATA_AUSENTE=_ATA_AUSENTE, sincronizar_bandeja=MagicMock(), dashboard=None,
            safe_dispatch_ui=MagicMock())
        with patch("core.actions.ActionManager.secure_copy", return_value=True):
            return transcrever("C:/reuniao.mp3")

    def test_termo_do_vocabulario_fica(self):
        self.assertIn("Claro não atende", self._transcrever(["Claro"]))
        self.assertIn("claro não atende", self._transcrever([]))


class TestPromptDaAutocorrecao(unittest.TestCase):
    """O refino tinha "FIDELIDADE TOTAL" e nada sobre falso começo: mantinha "minha última, a
    última versão". Medido na Groq (Smart, 13 casos): antes 8, depois 11; os controles (ou seja,
    quer dizer explicando, listas) ficaram certos."""

    def _prompt(self):
        servico = GroqService(api_key="gsk_teste")
        cliente = MagicMock()
        cliente.with_options.return_value = cliente
        cliente.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Texto polido."))])
        servico.get_client = lambda: cliente
        servico.refine_text("Ok, minha última, a última versão já está instalada?")
        mensagens = cliente.chat.completions.create.call_args.kwargs["messages"]
        return next(m["content"] for m in mensagens if m["role"] == "system")

    def test_fidelidade_nao_e_manter_o_falso_comeco(self):
        self.assertIn("Fidelidade não é manter os falsos começos interrompidos", self._prompt())

    def test_autocorrecao_com_os_casos_do_dono(self):
        prompt = self._prompt()
        self.assertIn("a versão abandonada sai do texto", prompt)
        self.assertIn("'Ok, minha última, a última versão já está instalada?' -> 'Ok, a última versão já está instalada?'", prompt)
        self.assertIn("'transformar uma loja em um mercado, em um conjunto de mercados' -> 'transformar uma loja em um conjunto de mercados'", prompt)
        # Medido: com só "apague a versão abandonada", o Smart tirava também o contexto da frase.
        self.assertIn("Só sai o trecho que ela refez", prompt)

    def test_marcadores_de_retratacao(self):
        prompt = self._prompt()
        for marcador in ("esqueça disso", "cancela isso", "deixa pra lá", "ou melhor", "melhor dizendo", "não, espera"):
            self.assertIn(f"'{marcador}'", prompt)

    def test_ou_seja_que_conclui_fica(self):
        self.assertIn("'Ou seja' e 'quer dizer' que explicam ou concluem uma ideia válida não anulam nada", self._prompt())


class _Fatiado(unittest.TestCase):
    """O pipeline de verdade, com o limite de fatiar baixado para um WAV de 1 s (o de verdade é
    20 MB, ~11 min): o que se testa é o caminho, não o tamanho."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._patch_limite = patch.object(tp, "_LIMITE_SEM_FATIAR", 1000)
        self._patch_limite.start()
        self.addCleanup(self._patch_limite.stop)
        # Fora do Willy e do shell: com uma janela Tk deste processo na frente, ou a área de
        # trabalho, o ditado sem alvo seria copiado.
        for funcao in ("_foco_numa_janela_do_willy", "_foco_no_shell"):
            foco = patch.object(tp, funcao, return_value=False)
            foco.start()
            self.addCleanup(foco.stop)
        self.wav = convert_to_wav(np.zeros(16000, dtype=np.float32), sample_rate=16000).getvalue()
        self.servico = GroqService(api_key="gsk_teste")
        # Nenhum teste daqui vai à rede: o que não foi trocado por um MagicMock falha alto (o juiz do
        # Bloco 10 fez uma chamada de verdade à Groq por uma tradução que não estava trocada).
        self.servico.get_client = MagicMock(side_effect=AssertionError("chamada de rede num teste"))
        self.servico.transcribe = MagicMock()
        self.groq = MagicMock()
        self.groq.transcribe_chunks.side_effect = self.servico.transcribe_chunks
        self.groq.refine_text.side_effect = lambda texto, **_k: texto
        self.groq.generate_agent_prompt.side_effect = lambda texto, **_k: "/goal " + texto
        self.groq.transform_text.side_effect = lambda base, inst, **_k: f"{base} [{inst}]"
        self.groq.summarize_meeting.side_effect = lambda texto, **_k: "## Ata\n" + texto
        audio = MagicMock()
        audio.is_processing = False
        audio.split_audio_into_chunks.side_effect = lambda *a, **k: [io.BytesIO(b"c0"), io.BytesIO(b"c1"),
                                                                     io.BytesIO(b"c2")]
        self.config = MagicMock(groq_api_key="gsk_teste", clipboard_only=False, private_mode=False,
                                clean_fillers=False, refine_prompt=True)
        self.config.load_replacements.return_value = {}
        self.config.get_prompt_context.return_value = "Vocabulário: Willy, Kubernetes, FastAPI"
        snippets = MagicMock()
        snippets.match_and_expand.return_value = None
        self.injector = MagicMock()
        self.injector.paste_text.return_value = True
        self.pipeline = TranscriptionPipeline(
            groq_service=self.groq, config_mgr=self.config, audio_mgr=audio, injector=self.injector,
            sound_mgr=MagicMock(), snippet_mgr=snippets, ui_notifier=lambda *a, **k: None,
            failed_audio_path=os.path.join(self.tmp, "avulso.wav"), user_data_dir=self.tmp)
        self.fila = self.pipeline.fila
        git = patch("core.pipeline.transcription_pipeline.ContextManager.get_git_context", return_value="")
        git.start()
        self.addCleanup(git.stop)

    def _rodar(self, modo, retry_path=None):
        return self.pipeline.process(PipelineContext(
            wav_bytes=self.wav, modo=modo, app_context=("code.exe", "editor", "general"),
            selected_text="texto selecionado" if modo == "transform" else None,
            is_retry=retry_path is not None, retry_path=retry_path))


class TestFatiamentoEmTodosOsModos(_Fatiado):
    MODOS = ("transcribe", "send", "prompt", "transform", "meeting")

    def test_limite_e_20_mb(self):
        self._patch_limite.stop()
        self.assertEqual(20 * 1024 * 1024, tp._LIMITE_SEM_FATIAR)

    def test_acima_do_limite_vai_em_blocos(self):
        for modo in self.MODOS:
            with self.subTest(modo=modo):
                self.servico.transcribe.reset_mock()
                self.servico.transcribe.side_effect = ["parte 0", "parte 1", "parte 2"]
                self.assertTrue(self._rodar(modo).success)
                self.assertEqual(3, self.servico.transcribe.call_count)
                self.assertEqual(
                    ["Vocabulário: Willy, Kubernetes, FastAPI"] * 3,
                    [
                        c.args[1] if len(c.args) > 1 else c.kwargs.get("prompt_context", c.kwargs.get("prompt"))
                        for c in self.servico.transcribe.call_args_list
                    ],
                )
                self.assertNotIn(self.wav, [c.args[0] for c in self.groq.transcribe.call_args_list])

    def test_abaixo_do_limite_vai_inteiro(self):
        limite = patch.object(tp, "_LIMITE_SEM_FATIAR", len(self.wav))
        limite.start()
        self.addCleanup(limite.stop)
        self.groq.transcribe.return_value = "texto curto"
        for modo in ("transcribe", "send", "prompt", "transform"):
            with self.subTest(modo=modo):
                self.groq.transcribe_chunks.reset_mock()
                self.assertTrue(self._rodar(modo).success)
                self.groq.transcribe_chunks.assert_not_called()

    def test_queda_no_meio_guarda_os_blocos_ao_lado_do_item(self):
        for modo in ("transcribe", "send", "prompt", "transform"):
            with self.subTest(modo=modo):
                for item in self.fila.itens():
                    self.fila.remover(item)
                self.servico.transcribe.side_effect = ["parte 0", "parte 1", ConnectionError("offline")]
                self.assertEqual("offline_retry", self._rodar(modo).error_category)
                (item,) = self.fila.itens()
                self.assertTrue(item.endswith(f"_{modo}.wav"))
                self.assertEqual({0: "parte 0", 1: "parte 1"}, self.fila.ler_blocos(item))

    def test_reenvio_transcreve_so_os_que_faltam(self):
        for modo in ("transcribe", "send", "prompt", "transform"):
            with self.subTest(modo=modo):
                self.servico.transcribe.side_effect = ["parte 0", "parte 1", ConnectionError("offline")]
                self._rodar(modo)
                (item,) = self.fila.itens()
                self.servico.transcribe.reset_mock()
                self.servico.transcribe.side_effect = ["parte 2"]
                self.assertTrue(self._rodar(modo, retry_path=item).success)
                self.assertEqual(1, self.servico.transcribe.call_count)
                self.assertEqual([], self.fila.itens())
                self.assertFalse(os.path.exists(item + ".blocos.json"))

    def test_traducao_acima_do_limite_vai_em_blocos(self):
        # Juiz do Bloco 10: a tradução ia inteira, e acima de 20 MB levava 413.
        self.servico.translate = MagicMock(side_effect=["part 0", "part 1", "part 2"])
        self.assertTrue(self._rodar("translate").success)
        self.assertEqual(3, self.servico.translate.call_count)
        self.assertEqual(
            ["Vocabulário: Willy, Kubernetes, FastAPI"] * 3,
            [
                c.args[1] if len(c.args) > 1 else c.kwargs.get("prompt_context", c.kwargs.get("prompt"))
                for c in self.servico.translate.call_args_list
            ],
        )
        self.groq.translate.assert_not_called()
        self.servico.transcribe.assert_not_called()
        self.assertEqual("Part 0\n\nPart 1\n\nPart 2", self.injector.paste_text.call_args.args[0])

    def test_traducao_abaixo_do_limite_vai_inteira(self):
        limite = patch.object(tp, "_LIMITE_SEM_FATIAR", len(self.wav))
        limite.start()
        self.addCleanup(limite.stop)
        self.groq.translate.return_value = "short text"
        self.assertTrue(self._rodar("translate").success)
        self.groq.translate.assert_called_once()
        self.groq.transcribe_chunks.assert_not_called()

    def test_traducao_que_cai_no_meio_retoma_os_blocos(self):
        self.servico.translate = MagicMock(side_effect=["part 0", ConnectionError("offline")])
        self.assertEqual("offline_retry", self._rodar("translate").error_category)
        (item,) = self.fila.itens()
        self.assertEqual({0: "part 0"}, self.fila.ler_blocos(item))
        self.servico.translate = MagicMock(side_effect=["part 1", "part 2"])
        self.assertTrue(self._rodar("translate", retry_path=item).success)
        self.assertEqual(2, self.servico.translate.call_count)

    def test_limpeza_recebe_o_vocabulario(self):
        limite = patch.object(tp, "_LIMITE_SEM_FATIAR", len(self.wav))
        limite.start()
        self.addCleanup(limite.stop)
        self.config.clean_fillers = True
        self.config.get_vocab_terms.return_value = ["Claro"]
        self.groq.transcribe.return_value = "Liguei pra operadora, Claro não atende."
        self.assertTrue(self._rodar("transcribe").success)
        self.assertIn("operadora, Claro não atende", self.injector.paste_text.call_args.args[0])

    def test_limpeza_recebe_o_vocabulario_no_prompt_e_no_transformar(self):
        # Juiz do Bloco 10, 12ª rodada: o vocabulário também vale na limpeza antes do LLM.
        limite = patch.object(tp, "_LIMITE_SEM_FATIAR", len(self.wav))
        limite.start()
        self.addCleanup(limite.stop)
        self.config.clean_fillers = True
        self.config.get_vocab_terms.return_value = ["Claro"]
        self.groq.transcribe.return_value = "Liguei pra operadora, Claro não atende."
        for modo, chamada in (("prompt", self.groq.generate_agent_prompt), ("transform", self.groq.transform_text)):
            with self.subTest(modo=modo):
                self.assertTrue(self._rodar(modo).success)
                self.assertIn("operadora, Claro não atende", " ".join(map(str, chamada.call_args.args)))

    def test_no_modo_privado_os_blocos_nao_vao_para_o_disco(self):
        self.config.private_mode = True
        self.servico.transcribe.side_effect = ["parte 0", "parte 1", ConnectionError("offline")]
        self._rodar("transcribe")
        self.assertEqual([], self.fila.itens())
        self.assertEqual([], [n for n in os.listdir(self.tmp) if n.endswith(".json")])


if __name__ == "__main__":
    unittest.main()
