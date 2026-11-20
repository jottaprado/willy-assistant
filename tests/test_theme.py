"""
Coerência do design system em ui/theme.py.

O ACCENT_PURPLE_HOVER que faltava não era um erro de digitação: era assimetria. A família
azul tinha os quatro estados e a roxa tinha três, então um widget roxo copiado de um azul
pedia um nome que ninguém tinha criado. O NameError ficou dormindo desde o commit inicial
porque só executava depois de dois cliques.

`tests/test_static_analysis.py` pega o nome usado e não definido. Este arquivo pega um
degrau antes: o buraco na paleta, antes de alguém escrever o nome que vai faltar.
"""

import glob
import os
import re
import unittest

from ui import theme

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAMILIAS = ["BLUE", "CYAN", "GREEN", "AMBER", "RED", "PURPLE"]

# base e _HOVER formam o botão sólido; _LIGHT e _LIGHT_HOVER, o fantasma; _BORDER, o
# contorno. Faltar um deles é o defeito que este arquivo existe para impedir.
VARIANTES = ["", "_HOVER", "_LIGHT", "_LIGHT_HOVER", "_BORDER"]

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class TestSimetriaDaPaleta(unittest.TestCase):
    def test_toda_familia_tem_o_conjunto_completo(self):
        faltando = [
            f"ACCENT_{familia}{variante}"
            for familia in FAMILIAS
            for variante in VARIANTES
            if not hasattr(theme, f"ACCENT_{familia}{variante}")
        ]
        self.assertEqual(
            [], faltando,
            "família de acento incompleta em ui/theme.py — um widget que copie o padrão "
            f"de outra família vai pedir um nome que não existe: {faltando}",
        )

    def test_todo_token_de_acento_e_hex_valido(self):
        invalidos = {}
        for familia in FAMILIAS:
            for variante in VARIANTES:
                nome = f"ACCENT_{familia}{variante}"
                valor = getattr(theme, nome, None)
                if not isinstance(valor, str) or not HEX.match(valor):
                    invalidos[nome] = valor
        self.assertEqual({}, invalidos, f"valor de cor inválido: {invalidos}")

    def test_familias_nao_compartilham_cor(self):
        """Duas famílias com o mesmo hex quase sempre é copiar-e-colar esquecido."""
        por_valor = {}
        for familia in FAMILIAS:
            for variante in VARIANTES:
                nome = f"ACCENT_{familia}{variante}"
                valor = getattr(theme, nome, "").upper()
                por_valor.setdefault(valor, []).append(nome)

        repetidos = {v: nomes for v, nomes in por_valor.items() if len(nomes) > 1}
        self.assertEqual({}, repetidos, f"cor repetida entre famílias: {repetidos}")

    def test_hover_solido_difere_do_tom_base(self):
        """Hover igual à base é hover invisível: o botão não responde ao mouse."""
        iguais = [
            f"ACCENT_{familia}"
            for familia in FAMILIAS
            if getattr(theme, f"ACCENT_{familia}", "").upper()
            == getattr(theme, f"ACCENT_{familia}_HOVER", "").upper()
        ]
        self.assertEqual([], iguais, f"hover idêntico à cor base: {iguais}")

    def test_niveis_de_hover_neutro_sao_distintos(self):
        """O hover neutro tem dois degraus e eles precisam ser visualmente diferentes.

        BTN_NEUTRAL_HOVER (Gray 100) é o hover sobre branco; BG_HOVER_STRONG (Gray 200)
        é o hover sobre superfície já cinza. Iguais, um dos dois não existe e metade dos
        widgets deixa de responder ao mouse.

        Unicidade geral não serve como regra aqui: #FFFFFF é compartilhado de propósito
        por cinco tokens, porque o mesmo valor cumpre papéis diferentes.
        """
        self.assertNotEqual(
            theme.BTN_NEUTRAL_HOVER.upper(), theme.BG_HOVER_STRONG.upper(),
            "os dois degraus de hover neutro têm o mesmo valor",
        )

    def test_degraus_da_escala_de_superficie_sao_distintos(self):
        """A escala neutra tem três degraus de profundidade e nenhum pode repetir outro.

        BG_SUBTLE (Gray 50) é o painel suave, BG_MUTED (Gray 100) a superfície recuada,
        BG_RECESSED (Gray 200) o sulco. Dois degraus iguais colapsam a escala: o widget
        que escolher o degrau errado fica indistinguível do vizinho e ninguém vê o erro,
        porque a tela continua funcionando.

        Mesma regra dos dois degraus de hover, pela mesma razão — a primeira versão
        desta suíte não tinha nenhuma das duas, e a prova por mutação encontrou as duas.
        """
        escala = {n: getattr(theme, n).upper()
                  for n in ("BG_SUBTLE", "BG_MUTED", "BG_RECESSED")}
        repetidos = {}
        for nome, valor in escala.items():
            repetidos.setdefault(valor, []).append(nome)
        colididos = {v: ns for v, ns in repetidos.items() if len(ns) > 1}
        self.assertEqual({}, colididos, f"degraus da escala de superfície iguais: {colididos}")

    def test_hover_do_fantasma_difere_do_fundo_claro(self):
        iguais = [
            f"ACCENT_{familia}_LIGHT"
            for familia in FAMILIAS
            if getattr(theme, f"ACCENT_{familia}_LIGHT", "").upper()
            == getattr(theme, f"ACCENT_{familia}_LIGHT_HOVER", "").upper()
        ]
        self.assertEqual([], iguais, f"hover idêntico ao fundo claro: {iguais}")


class TestUiUsaSomenteTokens(unittest.TestCase):
    """Nenhuma cor da interface pode ser escrita como hex literal.

    Esta regra substituiu três mais estreitas (hover, texto, botão) que foram surgindo
    conforme cada grupo era migrado. Cada uma pegava uma família de kwargs e deixava as
    outras passarem — e o que entrou pelos buracos entre elas foi justamente o pior:

    - `ACCENT_PURPLE_HOVER` usado sem existir, NameError desde o commit inicial;
    - nove rótulos da paleta dark sobre fundo branco, um deles a 1.72:1 de contraste;
    - um hover escrito à mão como `fg_color` dentro de `_on_enter`, que nenhuma regra
      sobre o nome do kwarg encontraria.

    A regra ampla não tem buraco: se a cor não tem nome, o teste reprova e o nome
    precisa nascer. É o que mantém os testes de simetria e de contraste com valor
    prático — a paleta pode estar completa e correta enquanto a tela a ignora inteira.

    `ui/theme.py` é o único isento: é onde os valores moram.

    A regra olhava só os argumentos `*_color="#..."`, e por esse furo passaram 90 hex dos
    elementos flutuantes: `fill=` do canvas, `bg=` do Tk, constantes de módulo como
    `BG_DARK = "#161618"` e as cores que o willy.py manda para a pílula. Agora qualquer hex
    entre aspas reprova.
    """

    COR_COM_HEX = re.compile(r'''(?:([A-Za-z_]+)\s*[=:]\s*)?["']#[0-9A-Fa-f]{3,8}["']''')

    def _arquivos_de_ui(self):
        caminhos = [os.path.join(RAIZ, "ui", "dashboard.py"), os.path.join(RAIZ, "willy.py")]
        caminhos += glob.glob(os.path.join(RAIZ, "ui", "**", "*.py"), recursive=True)
        return [c for c in caminhos
                if os.path.isfile(c) and "__pycache__" not in c
                and os.path.basename(c) != "theme.py"]

    def test_nenhuma_cor_hardcoded_na_interface(self):
        infracoes = []
        for caminho in self._arquivos_de_ui():
            with open(caminho, encoding="utf-8") as f:
                for n, linha in enumerate(f, 1):
                    for achado in self.COR_COM_HEX.finditer(linha):
                        rel = os.path.relpath(caminho, RAIZ).replace("\\", "/")
                        infracoes.append(f"{rel}:{n} {achado.group(0)}")

        self.assertEqual(
            [], infracoes,
            "cor escrita como hex em vez de token de ui/theme.py. Se o papel que você "
            "precisa não tem nome, crie o token: é assim que a próxima família nasce "
            f"completa em vez de virar NameError dois cliques adiante. {infracoes}",
        )


class TestTrilhosSaoConsistentes(unittest.TestCase):
    """Todo trilho de controle usa o mesmo degrau da escala.

    Havia três trilhos e três fundos diferentes: o medidor de volume em Gray 100, o
    slider em Gray 200 e o VU meter em BG_INPUT — branco, isto é, invisível contra o
    cartão. Nenhum dos três estava errado sozinho; eles só eram incoerentes entre si, e
    tokenizar foi o que tornou isso visível — antes eram hex soltos em arquivos distintos.

    O trilho é o fundo (`fg_color`); a parte preenchida é o `progress_color` e varia de
    propósito, porque carrega significado.
    """

    TRILHOS = ("CTkProgressBar", "CTkSlider")

    def _arquivos(self):
        caminhos = [os.path.join(RAIZ, "ui", "dashboard.py")]
        caminhos += glob.glob(os.path.join(RAIZ, "ui", "**", "*.py"), recursive=True)
        return [c for c in caminhos
                if os.path.isfile(c) and "__pycache__" not in c
                and os.path.basename(c) != "theme.py"]

    def test_todos_os_trilhos_usam_o_mesmo_token(self):
        import ast

        encontrados = {}
        for caminho in self._arquivos():
            with open(caminho, encoding="utf-8") as f:
                arvore = ast.parse(f.read(), filename=caminho)
            for no in ast.walk(arvore):
                if not isinstance(no, ast.Call):
                    continue
                func = no.func
                nome = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if nome not in self.TRILHOS:
                    continue
                for kw in no.keywords:
                    if kw.arg == "fg_color" and isinstance(kw.value, ast.Name):
                        rel = os.path.relpath(caminho, RAIZ).replace("\\", "/")
                        encontrados[f"{rel}:{no.lineno}"] = kw.value.id

        self.assertTrue(encontrados, "nenhum trilho encontrado — o teste perdeu o alvo")
        distintos = set(encontrados.values())
        self.assertEqual(
            1, len(distintos),
            f"trilhos com fundos diferentes, sem motivo aparente: {encontrados}",
        )


def _luminancia(hex_cor):
    """Luminância relativa conforme WCAG 2.1."""
    h = hex_cor.lstrip("#")
    canais = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    canais = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]


def _contraste(cor_a, cor_b):
    maior, menor = sorted([_luminancia(cor_a), _luminancia(cor_b)], reverse=True)
    return (maior + 0.05) / (menor + 0.05)


class TestContrasteDosFlutuantes(unittest.TestCase):
    """Texto e cores de estado da pílula, do Spotlight e das legendas legíveis no fundo escuro.

    Os flutuantes são sempre escuros, então as cores deles respondem só ao FLUTUANTE_FUNDO:
    4.5:1 para os textos, 3:1 para as cores de estado (ícones e mensagens curtas em negrito).
    """

    TEXTOS = ("FLUTUANTE_TEXTO", "FLUTUANTE_TEXTO_APAGADO", "FLUTUANTE_TEXTO_SUAVE", "FLUTUANTE_TEXTO_BOTAO")
    ESTADOS = ("FLUTUANTE_AZUL", "FLUTUANTE_AZUL_ACAO", "FLUTUANTE_CIANO", "FLUTUANTE_CIANO_CLARO",
               "FLUTUANTE_VERDE", "FLUTUANTE_VERMELHO", "FLUTUANTE_LARANJA", "FLUTUANTE_AMARELO",
               "FLUTUANTE_ROXO", "FLUTUANTE_LILAS")

    def test_contraste_sobre_o_fundo(self):
        fundo = theme.FLUTUANTE_FUNDO
        baixos = [f"{nome} {_contraste(getattr(theme, nome), fundo):.2f}:1"
                  for nomes, piso in ((self.TEXTOS, 4.5), (self.ESTADOS, 3.0)) for nome in nomes
                  if _contraste(getattr(theme, nome), fundo) < piso]
        self.assertEqual([], baixos)

    def test_todo_token_flutuante_e_hex_valido(self):
        for nome in dir(theme):
            if nome.startswith(("FLUTUANTE_", "BANDEJA_")):
                with self.subTest(token=nome):
                    self.assertRegex(getattr(theme, nome), HEX)


class TestContrasteDeTexto(unittest.TestCase):
    """Toda cor de texto da paleta tem que ser legível sobre as superfícies claras.

    O teste acima garante que a cor venha de um token. Este garante que o token preste:
    juntos, fecham o buraco por onde entraram nove rótulos a 1.72:1 de contraste.

    Limiares do WCAG 2.1 AA: 4.5:1 para texto normal, 3:1 para texto grande (≥18pt, ou
    ≥14pt em negrito). Os acentos são usados em cabeçalhos de card 14pt bold, então
    respondem pelo piso de 3:1.

    `TEXT_MUTED` esteve fora desta lista enquanto media 2.41:1 — uma exclusão declarada,
    porque incluí-la seria reprovar de saída e escolher um limiar que a acomodasse seria
    fabricar aprovação. Subiu de Gray 400 para Gray 500 (4.59:1) e entrou. Nenhuma cor de
    texto da paleta fica de fora agora, e é isso que dá valor à regra.
    """

    ACENTOS = ("ACCENT_BLUE", "ACCENT_CYAN", "ACCENT_GREEN",
               "ACCENT_AMBER", "ACCENT_RED", "ACCENT_PURPLE")
    TEXTO_CORRIDO = ("TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED")

    def _superficies(self):
        return {"BG_APP": theme.BG_APP, "BG_CARD": theme.BG_CARD, "BG_SIDEBAR": theme.BG_SIDEBAR}

    def test_acentos_passam_no_piso_de_texto_grande(self):
        ruins = []
        for nome in self.ACENTOS:
            cor = getattr(theme, nome)
            for sup, valor in self._superficies().items():
                razao = _contraste(cor, valor)
                if razao < 3.0:
                    ruins.append(f"{nome} sobre {sup}: {razao:.2f}:1")
        self.assertEqual([], ruins, f"contraste abaixo de 3:1 (WCAG AA texto grande): {ruins}")

    def test_texto_corrido_passa_no_piso_normal(self):
        ruins = []
        for nome in self.TEXTO_CORRIDO:
            cor = getattr(theme, nome)
            for sup, valor in self._superficies().items():
                razao = _contraste(cor, valor)
                if razao < 4.5:
                    ruins.append(f"{nome} sobre {sup}: {razao:.2f}:1")
        self.assertEqual([], ruins, f"contraste abaixo de 4.5:1 (WCAG AA texto normal): {ruins}")

    def test_texto_de_botao_solido_e_legivel(self):
        """Branco sobre o preenchimento do botão — o par mais usado da interface."""
        ruins = []
        for nome in self.ACENTOS:
            razao = _contraste(theme.BTN_PRIMARY_TEXT, getattr(theme, nome))
            if razao < 3.0:
                ruins.append(f"BTN_PRIMARY_TEXT sobre {nome}: {razao:.2f}:1")
        self.assertEqual([], ruins, f"texto de botão ilegível: {ruins}")


class TestContrasteDeComponente(unittest.TestCase):
    """WCAG 1.4.11: o que identifica o estado de um controle precisa de 3:1.

    Eu medi isto errado antes. Comparei o TRILHO contra o cartão (1.24:1) e concluí que
    a interface tinha um gap grande, que só um redesenho fecharia. O trilho é fundo — o
    que identifica o estado é o PREENCHIMENTO, e o vizinho dele é o trilho, não o cartão.

    Medindo os pares certos, seis de sete passavam. Falhava um: o VU meter em nível médio,
    ACCENT_AMBER sobre o trilho, a 2.57:1. Amber 600 é claro demais para servir de
    preenchimento sobre cinza claro. Daí os tokens METER_*, com o âmbar um degrau mais
    escuro e a razão registrada em ui/theme.py.
    """

    PISO = 3.0
    TRILHO = "BG_RECESSED"

    def _arquivos(self):
        caminhos = [os.path.join(RAIZ, "ui", "dashboard.py")]
        caminhos += glob.glob(os.path.join(RAIZ, "ui", "**", "*.py"), recursive=True)
        return [c for c in caminhos
                if os.path.isfile(c) and "__pycache__" not in c
                and os.path.basename(c) != "theme.py"]

    def test_preenchimentos_sao_distinguiveis_do_trilho(self):
        usados = {}
        padrao = re.compile(r"progress_color\s*=\s*([A-Z][A-Z0-9_]*)")
        for caminho in self._arquivos():
            with open(caminho, encoding="utf-8") as f:
                for n, linha in enumerate(f, 1):
                    for token in padrao.findall(linha):
                        rel = os.path.relpath(caminho, RAIZ).replace("\\", "/")
                        usados.setdefault(token, f"{rel}:{n}")

        self.assertTrue(usados, "nenhum progress_color encontrado — o teste perdeu o alvo")

        trilho = getattr(theme, self.TRILHO)
        ruins = []
        for token, onde in sorted(usados.items()):
            cor = getattr(theme, token, None)
            self.assertIsNotNone(cor, f"{onde}: '{token}' não existe em ui/theme.py")
            razao = _contraste(cor, trilho)
            if razao < self.PISO:
                ruins.append(f"{token} ({onde}): {razao:.2f}:1 sobre {self.TRILHO}")

        self.assertEqual(
            [], ruins,
            "preenchimento indistinguível do trilho; quem depende de contraste não "
            f"consegue ler o estado do controle: {ruins}",
        )


if __name__ == "__main__":
    unittest.main()
