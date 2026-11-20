"""
Testes unitários para o módulo core.text_processing.TextProcessor.
"""

import io
import unittest
from unittest.mock import patch

import core.groq_service as groq_service_mod
import core.text_processing as text_processing_mod
from core.text_processing import TextProcessor, normalize_for_search


class TestTextProcessor(unittest.TestCase):

    def test_empty_and_whitespace(self):
        self.assertEqual(TextProcessor.apply_voice_commands(""), "")
        self.assertEqual(TextProcessor.apply_voice_commands("   "), "")
        self.assertEqual(TextProcessor.apply_voice_commands(None), "")

    def test_single_word(self):
        self.assertEqual(TextProcessor.apply_voice_commands("olá"), "Olá")
        self.assertEqual(TextProcessor.apply_voice_commands("Python"), "Python")

    def test_punctuation_commands(self):
        cases = [
            ("olá mundo ponto", "Olá mundo."),
            ("olá vírgula como vai ponto final", "Olá, como vai."),
            ("atenção dois pontos o teste começou", "Atenção: o teste começou"),
            ("item um ponto e vírgula item dois", "Item um; item dois"),
            ("você vem hoje interrogação", "Você vem hoje?"),
            ("que dia lindo exclamação", "Que dia lindo!"),
            ("linha um nova linha linha dois", "Linha um\nLinha dois"),
            ("parágrafo um novo parágrafo parágrafo dois", "Parágrafo um\n\nParágrafo dois"),
            ("ele disse abrir aspas bom dia fechar aspas", 'Ele disse "bom dia"'),
            ("veja abrir parênteses nota dez fechar parênteses", "Veja (nota dez)"),
            ("objeto abrir chaves id um fechar chaves", "Objeto {id um}"),
        ]
        for entrada, esperado in cases:
            with self.subTest(entrada=entrada):
                res = TextProcessor.apply_voice_commands(entrada)
                self.assertEqual(res, esperado)

    def test_domain_preservation(self):
        # "ponto com" ou "ponto br" não devem virar ". com" mas sim ".com"
        res = TextProcessor.apply_voice_commands("acesse google ponto com")
        self.assertIn("google.com", res)

        res2 = TextProcessor.apply_voice_commands("site da empresa ponto com ponto br")
        self.assertIn(".com", res2)

    def test_spacing_normalization(self):
        res = TextProcessor.apply_voice_commands("teste   ,   mais texto   .   fim")
        self.assertEqual(res, "Teste, mais texto. Fim")

    def test_sinal_ditado_substitui_pontuacao_do_whisper_ao_redor_do_comando(self):
        cases = [
            ("Teste do Willy, dois pontos. Seguem os tópicos a seguir.", "Teste do Willy: Seguem os tópicos a seguir."),
            ("Até amanhã! Exclamação! Vamos começar a reunião!", "Até amanhã! Vamos começar a reunião!"),
            ("Que dia lindo! Exclamação!", "Que dia lindo!"),
            ("Você vem hoje? Interrogação.", "Você vem hoje?"),
            ("Terminei o relatório. Ponto final.", "Terminei o relatório."),
            ("Até amanhã, exclamação.", "Até amanhã!"),
            ("Pode me mandar o arquivo, interrogação.", "Pode me mandar o arquivo?"),
            ("Terminei, ponto.", "Terminei."),
            ("Comprei maçã, vírgula, pera e uva.", "Comprei maçã, pera e uva."),
            ("Até amanhã exclamação, vamos lá", "Até amanhã! Vamos lá"),
            ("Será que dá... Acho que não.", "Será que dá... Acho que não."),
            ("Primeiro item, ponto e vírgula. Segundo item.", "Primeiro item; Segundo item."),
            ("Você vem hoje? Ponto de interrogação.", "Você vem hoje?"),
            ("Que dia lindo! Ponto de exclamação!", "Que dia lindo!"),
        ]
        for entrada, esperado in cases:
            with self.subTest(entrada=entrada):
                self.assertEqual(TextProcessor.apply_voice_commands(entrada), esperado)

    def test_comandos_estruturais_e_dominio_descartam_pontuacao_colidente_do_whisper(self):
        cases = [
            ("Primeiro item. Nova linha. Segundo item.", "Primeiro item.\nSegundo item."),
            ("Primeiro bloco. Novo parágrafo. Segundo bloco.", "Primeiro bloco.\n\nSegundo bloco."),
            ("Ele disse, abrir aspas, bom dia, fechar aspas.", 'Ele disse, "bom dia".'),
            ("Veja, abrir parênteses, nota dez, fechar parênteses.", "Veja, (nota dez)."),
            ("Objeto, abrir chaves, id um, fechar chaves.", "Objeto, {id um}."),
            ("Acesse google. Ponto com.", "Acesse google.com."),
            ("Primeiro item\n... segundo item", "Primeiro item\n... Segundo item"),
        ]
        for entrada, esperado in cases:
            with self.subTest(entrada=entrada):
                self.assertEqual(TextProcessor.apply_voice_commands(entrada), esperado)

    def test_ponto_como_substantivo_nao_vira_sinal(self):
        inalterados = [
            "Do meu ponto de vista, isso funciona.",
            "A reunião começa às três em ponto.",
            "Ele coloca um ponto no final.",
            "Preciso bater o ponto antes das nove.",
            "Isso é um ponto positivo para o projeto.",
            "Qual é o ponto de partida?",
            "O segundo ponto da pauta é o orçamento.",
            "Vamos colocar um ponto final nisso.",
            "Coloca um ponto de interrogação aqui.",
            "Coloca um ponto de exclamação aqui.",
            "Ponto de vista técnico.",
            "Bom, ponto de vista importa.",
            "O mesmo ponto de antes",
            "Meu ponto final é este",
            "Número um ponto.",
            "Espera um segundo ponto",
        ]
        for frase in inalterados:
            with self.subTest(frase=frase):
                self.assertEqual(TextProcessor.apply_voice_commands(frase), frase)

        transformados = [
            ("Acesse google ponto com ponto br.", "Acesse google.com.br."),
            ("Acesse outro ponto com.", "Acesse outro.com."),
            ("item um ponto e vírgula item dois", "Item um; item dois"),
            ("o mesmo ponto de antes", "O mesmo ponto de antes"),
            ("meu ponto final é este", "Meu ponto final é este"),
            ("é isso mesmo ponto", "É isso mesmo."),
            ("é isso mesmo ponto. Agora vamos", "É isso mesmo. Agora vamos"),
            ("É isso mesmo ponto agora vamos começar.", "É isso mesmo. Agora vamos começar."),
            ("Faz agora mesmo ponto final", "Faz agora mesmo."),
            ("o problema é meu ponto", "O problema é meu."),
            ("o problema é meu ponto final", "O problema é meu."),
            ("eu quero esse ponto", "Eu quero esse."),
            ("quero outro ponto", "Quero outro."),
            ("não sobrou nenhum ponto", "Não sobrou nenhum."),
            ("faça isso primeiro ponto", "Faça isso primeiro."),
            ("é isso mesmo ponto de interrogação", "É isso mesmo?"),
            ("Esse ponto, por exemplo, é bom.", "Esse. Por exemplo, é bom."),
        ]
        for entrada, esperado in transformados:
            with self.subTest(entrada=entrada):
                self.assertEqual(TextProcessor.apply_voice_commands(entrada), esperado)

        # B3 comportamental: todas as extensões de DOMAIN_EXTENSIONS viram .<ext> e não contam como pontuação final.
        for ext in TextProcessor.DOMAIN_EXTENSIONS.strip("()").split("|"):
            with self.subTest(ext=ext):
                self.assertEqual(TextProcessor.apply_voice_commands(f"x ponto {ext}"), f"X.{ext}")
                self.assertFalse(TextProcessor.ditou_pontuacao(f"x ponto {ext}"))

    def test_sentence_capitalization(self):
        texto = "olá amigos. tudo bem? espero que sim! obrigado\nnovo texto"
        esperado = "Olá amigos. Tudo bem? Espero que sim! Obrigado\nNovo texto"
        self.assertEqual(TextProcessor.capitalize_sentences(texto), esperado)

    def test_capitalize_sentences_nao_capitaliza_apos_dois_pontos_nem_abreviaturas_e_suporta_crase_e_til_espanhol(self):
        # AUD-050: não capitaliza após ':', não capitaliza após abreviatura ('Dr.', 'etc.')
        # e capitaliza 'à' (crase) e 'ñ' após fim de frase ou quebra de linha.
        self.assertEqual(
            TextProcessor.capitalize_sentences("atenção: o teste começou"),
            "Atenção: o teste começou",
        )
        self.assertEqual(
            TextProcessor.capitalize_sentences("falei com o Dr. ontem e com a Dra. hoje"),
            "Falei com o Dr. ontem e com a Dra. hoje",
        )
        self.assertEqual(
            TextProcessor.capitalize_sentences("frutas como maçã, pera, etc. estavam frescas"),
            "Frutas como maçã, pera, etc. estavam frescas",
        )
        self.assertEqual(
            TextProcessor.capitalize_sentences("cheguei cedo. às vezes chove\nà tarde. ñoño foi"),
            "Cheguei cedo. Às vezes chove\nÀ tarde. Ñoño foi",
        )

    def test_apply_replacements_preserva_barras_invertidas_literais_e_loga_erro(self):
        # AUD-051: valores com '\Users', '\novo', '\1' não devem levantar re.error nem virar escapes.
        regras = {
            "pasta": r"C:\Users\novo\1\teste",
            "latex": r"\alpha\beta\n\t",
        }
        res = TextProcessor.apply_replacements("Abra a pasta e digite latex agora.", regras)
        self.assertEqual(res, r"Abra a C:\Users\novo\1\teste e digite \alpha\beta\n\t agora.")

        # Se re.sub levantar exceção inesperada, deve registrar no stderr em vez de engolir com pass.
        buf = io.StringIO()
        with patch("core.text_processing.re.sub", side_effect=RuntimeError("falha simulada")), \
             patch("sys.stderr", buf):
            saida = TextProcessor.apply_replacements("Abra a pasta", {"pasta": "destino"})
        self.assertEqual(saida, "Abra a pasta")
        self.assertIn("falha simulada", buf.getvalue())

    def test_strip_accents_e_normalize_for_search_unificados(self):
        # AUD-049: strip_accents e normalize_for_search compartilham a remoção de diacríticos,
        # e groq_service não mantém função duplicada _sem_acento.
        self.assertEqual(TextProcessor.strip_accents(""), "")
        self.assertEqual(TextProcessor.strip_accents("Ação, Reunião & Niño"), "Acao, Reuniao & Nino")
        self.assertFalse(hasattr(groq_service_mod, "_sem_acento"))
        self.assertIs(groq_service_mod.normalize_for_search, text_processing_mod.normalize_for_search)

    def test_format_code_identifier(self):
        cases = [
            ("variável nome do usuário", "nome_do_usuario"),
            ("variavel total_de_compras", "total_de_compras"),
            ("snake case contador de acessos", "contador_de_acessos"),
            ("camel case data de nascimento", "dataDeNascimento"),
            ("pascal case cliente especial", "ClienteEspecial"),
            ("classe manipulador de arquivos", "ManipuladorDeArquivos"),
            ("kebab case api gateway endpoint", "api-gateway-endpoint"),
            ("slug titulo do artigo", "titulo-do-artigo"),
            ("constante chave secreta", "CHAVE_SECRETA"),
            ("screaming snake timeout conexao", "TIMEOUT_CONEXAO"),
            ("caixa baixa TEXTO EM CAIXA ALTA", "texto em caixa alta"),
            ("minúsculo TÍTULO COM ACENTO", "título com acento"),
            ("caixa alta aviso importante", "AVISO IMPORTANTE"),
            ("maiúsculo atenção redobrada", "ATENÇÃO REDOBRADA"),
        ]
        for entrada, esperado in cases:
            with self.subTest(entrada=entrada):
                self.assertEqual(TextProcessor.format_code_identifier(entrada), esperado)

        # Deve ignorar pontuação final inserida pelo modelo de fala
        self.assertEqual(TextProcessor.format_code_identifier("variável id do pedido."), "id_do_pedido")
        self.assertEqual(TextProcessor.format_code_identifier('"camel case total a pagar."'), "totalAPagar")

        # Deve retornar None para textos normais
        self.assertIsNone(TextProcessor.format_code_identifier("Bom dia como você está?"))
        self.assertIsNone(TextProcessor.format_code_identifier(""))
        self.assertIsNone(TextProcessor.format_code_identifier(None))

    def test_normalize_for_search(self):
        self.assertEqual(normalize_for_search(""), "")
        self.assertEqual(normalize_for_search(None), "")
        self.assertEqual(normalize_for_search("  Reunião de Alinhamento!  "), "reuniao de alinhamento!")
        self.assertEqual(normalize_for_search("Ação & Edição"), "acao & edicao")
        self.assertEqual(normalize_for_search("ÁÉÍÓÚ ÀÈÌÒÙ ÂÊÎÔÛ ÃÕ Ç"), "aeiou aeiou aeiou ao c")
        # Teste de correspondência de busca sem acento
        query = normalize_for_search("reuniao")
        item_text = normalize_for_search("Ata da Reunião de Segunda")
        self.assertIn(query, item_text)


if __name__ == "__main__":
    unittest.main()
