"""
Módulo de Processamento e Formatação de Texto do Willy.
Converte comandos de voz em sinais de pontuação e ajusta o espaçamento e capitalização.
"""

import difflib
import re
import sys
import unicodedata
from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from typing import ClassVar

# Prefixo falado -> estilo do identificador. Caixa baixa e caixa alta devolvem prosa, não um nome.
# Casados com re.DOTALL: na prosa, o "nova linha" dos comandos de voz vira "\n", e sem ele o
# "(.+)$" não passava da quebra e a fala caía no ditado comum.
_PADROES_DE_IDENTIFICADOR = (
    # Snake case: "variável ...", "variavel ...", "snake case ..."
    (r'^(?:vari[aá]vel|snake\s+case)(?:\s*:\s*|\s+)(.+)$', 'snake'),
    # Camel case: "camel case ..."
    (r'^(?:camel\s+case)(?:\s*:\s*|\s+)(.+)$', 'camel'),
    # Pascal case: "pascal case ...", "classe ..."
    (r'^(?:pascal\s+case|classe)(?:\s*:\s*|\s+)(.+)$', 'pascal'),
    # Kebab case: "kebab case ...", "slug ..."
    (r'^(?:kebab\s+case|slug)(?:\s*:\s*|\s+)(.+)$', 'kebab'),
    # Constant / Screaming snake: "constante ...", "screaming snake ..."
    (r'^(?:constante|screaming\s+snake|upper\s+snake)(?:\s*:\s*|\s+)(.+)$', 'constant'),
    # Lowercase / Caixa Baixa
    (r'^(?:caixa\s+baixa|min[uú]sculo|minusculo|lowercase)(?:\s*:\s*|\s+)(.+)$', 'lower'),
    # Uppercase / Caixa Alta
    (r'^(?:caixa\s+alta|mai[uú]sculo|maiusculo|uppercase)(?:\s*:\s*|\s+)(.+)$', 'upper'),
)
ESTILOS_EM_PROSA = ("lower", "upper")

# "Classe" também começa frase comum: "Classe média está alta este ano" saía MediaEstaAltaEsteAno.
# Sem os dois-pontos (que deixam o pedido explícito), é prosa a frase com verbo de ligação, com
# pontuação no meio, ou com mais de 5 palavras depois de "classe". "pascal case" é sempre pedido.
_VERBOS_DE_LIGACAO = frozenset(
    ["é", "era", "foi", "será", "seria", "está", "estava", "esteve", "estará", "estão", "estavam", "são", "eram", "foram", "fica", "ficou", "ficava", "parece", "parecia", "continua", "continuava", "tem", "têm", "tinha", "vai", "vão", "anda", "andava"])
_MAX_PALAVRAS_DE_UM_NOME = 5


def _e_prosa_com_classe(texto: str, payload: str) -> bool:
    if not re.match(r"^classe\b", texto, flags=re.IGNORECASE) or re.match(r"^classe\s*:", texto, flags=re.IGNORECASE):
        return False
    palavras = re.findall(r"[A-Za-z0-9À-ÿ]+", payload)
    if len(palavras) > _MAX_PALAVRAS_DE_UM_NOME:
        return True
    if any(p.lower() in _VERBOS_DE_LIGACAO for p in palavras):
        return True
    return bool(re.search(r"[,;.!?]", payload.rstrip(" .!?…\t\r\n")))


# --- Pergunta ou afirmação ------------------------------------------------------------------
# O Whisper decide o "?" pela entonação e erra nos dois sentidos: a pergunta sai com ponto
# ("..., certo." ; "Será que ... .") e a pausa de quem segue explicando sai com "?". Estas regras
# só mudam o que a frase diz sozinha, sem a entonação. A pergunta de sim ou não ("A última versão
# já está instalada?") tem a ordem de palavras da afirmação: só o refino, pelo contexto, decide.
# Elas rodam também na saída do refino e passam por cima dela: só entra aqui o que as palavras
# decidem sem ambiguidade, e na dúvida o sinal fica como veio.

# Palavras que abrem a frase sem mudar o que ela é: "Ok, será que...", "E cadê...". O separador é
# vírgula ou espaço: "\s*,?\s+" repetido retrocedia em exponencial numa fila longa de aberturas
# com espaço duplo (9 s numa frase de 24, medido pelo juiz do Bloco 8).
_ABERTURA = r'^(?:(?:ok|okay|então|e|mas|olha|tá|bom|agora|aí|enfim|gente|pessoal|willy)(?:\s*,\s*|\s+))*'

# Tag de confirmação depois da vírgula: ", certo." é ", certo?".
_TAG_DE_PERGUNTA = re.compile(
    r',\s*(?:certo|né|sabe|entendeu|entende|percebe|concorda|(?:você\s+|vocês\s+)?não\s+(?:acha|acham)'
    r'|não\s+é(?:\s+mesmo)?|ou\s+não|tá)\s*$', re.IGNORECASE)
# Antes da tag só concordância ("Ah, tá, certo."; "Ok, combinado, certo."): não pergunta nada.
_SO_CONCORDANCIA = re.compile(
    r'(?:(?:ah|ok|okay|tá|ta|então|beleza|combinado|obrigad[oa]|valeu|certo|sim|claro|fechado|fechou|show'
    r'|bom|perfeito|entendi|entendido|anotado|pronto|feito|legal|ótimo|isso)\W*)+', re.IGNORECASE)
# Estas também fecham afirmação ("Se não der, tudo bem."; "O deploy saiu, beleza."): só são
# pergunta depois de uma proposta de quem fala ("Eu vou mandar amanhã, tudo bem?") e nunca depois
# de condição. "pode" e "a gente" sozinhos não bastam ("Ele não pode vir, tudo bem."; "A gente já
# subiu ontem, beleza."), nem a negação e o estado ("Não vou mentir, faz sentido."; "Posso estar
# errado, tudo bem.").
_TAG_DE_PROPOSTA = re.compile(r',\s*(?:tudo\s+bem|tá\s+bom|pode\s+ser|faz\s+sentido|beleza)\s*$', re.IGNORECASE)
_PROPOSTA = re.compile(
    r'(?<!não\s)\b(?:(?:vou|vamos|posso|podemos)(?!\s+(?:estar|ser|ficar)\b)'
    r'|a\s+gente\s+(?:pode|vai|faz|marca|sobe|deixa|manda|conversa|revisa|testa|começa|termina)'
    r'|(?:eu|te)\s+(?:mando|passo|ligo|envio|aviso|faço|marco|deixo)'
    r'|fica\s+(?:para|pra))\b', re.IGNORECASE)
_CONDICAO = re.compile(r'\b(?:se|caso|quando|assim\s+que|desde\s+que|mesmo\s+que|ainda\s+que)\b', re.IGNORECASE)

# Abertura de pergunta direta. Não entram "Como", "Quando" e "Pode" sozinhos, que abrem afirmação
# ("Como combinamos ontem, segue o arquivo."; "Pode deixar que eu faço."), nem "Você consegue"
# sozinho ("Você consegue acessar o painel pelo link abaixo."): só o pedido a quem lê ("Você
# consegue me mandar...", "Pode me ajudar...").
_ABRE_PERGUNTA = re.compile(
    _ABERTURA + r'(?:será\s+que|por\s+que|qual(?:\s+que)?\s+(?:é|era|foi|seria|vai\s+ser)'
    r'|quais\s+(?:são|eram|foram|seriam)|como\s+assim|cadê|(?:você|vocês)\s+(?:acha|acham)\s+que'
    r'|(?:(?:você|vocês)\s+)?(?:consegue|conseguem|conseguiria)\s+me\s+\w+'
    r'|(?:(?:você|vocês)\s+)?(?:pode|podem|poderia)\s+me\s+ajudar'
    r'|o\s+que\s+(?:falta|você\s+(?:acha|sugere|recomenda|prefere|faria|pensa)))\b',
    re.IGNORECASE)
# Mudam a abertura em afirmação: a explicação depois de dois-pontos ("Qual é o plano: primeiro o
# backend."), a incerteza ("Qual é a melhor opção depende do cenário."; "Por que ele saiu, ninguém
# sabe."), o contraste ("Você acha que sabe, mas não sabe.") e a oração de quem fala depois da
# pergunta ("Por que isso acontece eu explico depois."; "Quais são os riscos, a gente discute
# amanhã."). O "eu" de "Por que eu...", "Será que a gente..." e "acha que eu..." é da pergunta.
_ABERTURA_QUE_AFIRMA = re.compile(
    r':\s|;|\b(?:não\s+sei|nem\s+sei|não\s+faço\s+ideia|não\s+lembro|tanto\s+faz|ninguém\s+sabe|depende)\b'
    r'|,\s*(?:mas|porém|só\s+que)\b'
    r'|(?<!\bque)(?<!\bse)(?<!\bpra)(?<!\bpara)(?<!\bquando)(?<!\bonde)(?<!\bassim)'
    r'\s(?:eu|a\s+gente)\s', re.IGNORECASE)
_O_QUE_FALTA_E = re.compile(
    _ABERTURA + r'o\s+que\s+falta\b.*\b(?:é|são|era|foi|está|estão|fica|ficou|continua)\b', re.IGNORECASE)

# Pergunta indireta ("Quero saber se posso..."; "Não sei o que é"): afirmação, mesmo com a subida
# no fim. Com vírgula fica como está: "Não sei se dá, você consegue ver?" termina em pergunta.
_PERGUNTA_INDIRETA = re.compile(
    _ABERTURA + r'(?:eu\s+)?(?:(?:quero|queria|gostaria\s+de|preciso)\s+(?:saber|entender|descobrir)'
    r'|não\s+sei|me\s+pergunto|vamos\s+ver)(?:\s+(?:melhor|exatamente|bem|direito|ainda))?'
    r'\s+(?:se|o\s+que|como|qual|quais|quando|onde|por\s+que|quem|quanto|quantos|quantas)\b',
    re.IGNORECASE)

# Conclusão de quem fala ("Ou seja, não vai sobrar muito?"; "Então, pelo que eu estou entendendo,
# ele vive de imposto?"): afirmação, por decisão do dono, mesmo soando como pedido de confirmação.
# O refino recebia a instrução e mantinha o "?" (medido na Groq). Fica pergunta a que fala com
# "você", a que termina numa tag e a que, depois da abertura, pergunta de fato: com palavra de
# pergunta ("Ou seja, o que eu faço agora?"; "Ou seja, por quê?"), com alternativa ("Ou seja, pago
# agora ou depois?"), puxando com "e" ("Ou seja, e o cliente?") ou curta ("Ou seja, não precisa?").
_DEDUCAO = re.compile(
    _ABERTURA + r'(?:ou\s+seja|quer\s+dizer\s*,|pelo\s+que\s+(?:eu\s+)?(?:(?:estou|tô|to)\s+entendendo|entendi|entendo))',
    re.IGNORECASE)
_PERGUNTA_DEPOIS_DA_DEDUCAO = re.compile(
    r'\b(?:o\s+que|qual|quais|quanto|quanta|quantos|quantas|como|quando|onde|aonde|por\s+que|quem'
    r'|será\s+que|cadê|ou|quê)\b', re.IGNORECASE)
_MINIMO_DA_CONCLUSAO = 4  # palavras depois da abertura
_VOCE = re.compile(r'\bvocês?\b', re.IGNORECASE)
# O "né?" que pergunta tem "você" como sujeito da frase ("Você viu o e-mail, né?"); o "você" de
# "Como você sabe, né?" e de "o código que você mandou, né?" não faz dele pergunta.
_FALA_COM_VOCE = re.compile(_ABERTURA + r'(?:você|vocês)\b', re.IGNORECASE)

# Fim de frase: ponto, "?" ou "!" antes de espaço ou do fim (não o de "3.5" nem o de "github.com",
# que vêm antes de letra ou número), reticências ou uma quebra de linha. As reticências separam
# ("Será que dá... Acho que não." são duas frases) e nunca mudam, e "??" ou "?!" também não.
_FIM_DE_FRASE = re.compile(r'\.{2,}|…|[?!]*[.?!](?=\s|$)|\n')
# O ponto de uma abreviatura: "Você consegue falar com o Dr. Carlos hoje." virava "o Dr? Carlos".
# Título, "vs." e "nº." vêm antes de alguma coisa e nunca fecham a frase. As outras podem fechar
# ("…Kafka etc. Acho que não."; "…voltou com a ex. Ninguém entende."): antes de minúscula a frase
# segue, e antes de maiúscula ou número, na dúvida, a que termina na abreviatura fica como veio (a
# seguinte é avaliada sozinha).
_SEMPRE_NO_MEIO = frozenset(["dr", "dra", "drs", "dras", "sr", "sra", "srs", "sras", "srta", "prof", "profa", "eng", "av", "vs", "nº", "núm"])
_ABREVIATURAS = frozenset(
    ["etc", "ex", "obs", "pág", "pag", "tel", "cel", "art", "fig", "cap", "vol", "ltda", "cia", "jr", "aprox", "depto", "min", "máx", "mín"])


def _palavras(texto: str) -> int:
    return len(re.findall(r'\w+', texto))


def _abreviatura(texto: str, ponto: int, *, inicial_conta: bool = True) -> str | None:
    """"no_meio" ("Dr.", "vs."), "abreviatura" ("etc.", "S.A.", a inicial "J.") ou None para o "."
    em texto[ponto]. Olha só o fim antes do ponto: a busca no texto inteiro, a cada ponto, levava
    198 s numa transcrição de 690 mil caracteres."""
    antes = re.search(r'(\S+)$', texto[max(0, ponto - 40):ponto])
    if not antes:
        return None
    palavra = antes.group(1).lstrip('("\'“[')
    if palavra.lower() in _SEMPRE_NO_MEIO:
        return "no_meio"
    if palavra.lower() in _ABREVIATURAS or (
        inicial_conta and len(palavra) == 1 and palavra.isalpha() and palavra.isupper()
    ):
        return "abreviatura"
    partes = palavra.split('.')
    if len(partes) > 1 and all(p.isalpha() and len(p) <= 2 for p in partes):
        return "abreviatura"
    return None


def _e_pergunta_pela_forma(frase: str) -> bool:
    """A frase (sem o sinal do fim) é pergunta só pelas palavras: tag ou abertura de pergunta."""
    tag = _TAG_DE_PERGUNTA.search(frase)
    if tag:
        antes = frase[:tag.start()].strip()
        return not _SO_CONCORDANCIA.fullmatch(antes)
    tag = _TAG_DE_PROPOSTA.search(frase)
    if tag:
        antes = frase[:tag.start()]
        return bool(_PROPOSTA.search(antes)) and not _CONDICAO.search(antes)
    return (bool(_ABRE_PERGUNTA.match(frase)) and not _ABERTURA_QUE_AFIRMA.search(frase)
            and not _O_QUE_FALTA_E.match(frase))


def _e_afirmacao_pela_forma(frase: str) -> bool:
    """A frase (sem o "?" do fim) é afirmação só pelas palavras: indireta ou conclusão."""
    if _PERGUNTA_INDIRETA.match(frase) and not re.search(r'[,:;]', frase):
        return True
    deducao = _DEDUCAO.match(frase)
    if not deducao:
        return False
    resto = frase[deducao.end():]
    return (_palavras(resto) >= _MINIMO_DA_CONCLUSAO and not re.match(r'[\s,]*e\b(?!-)', resto, re.IGNORECASE)
            and not _PERGUNTA_DEPOIS_DA_DEDUCAO.search(resto) and not _VOCE.search(frase)
            and not _TAG_DE_PERGUNTA.search(frase) and not _TAG_DE_PROPOSTA.search(frase))


def _casar_identificador(text: str) -> tuple[str, str] | None:
    """(estilo, o que vem depois do prefixo) para uma fala que pede identificador, ou None."""
    clean_text = (text or "").strip().strip('"\'')
    for pat, style in _PADROES_DE_IDENTIFICADOR:
        m = re.match(pat, clean_text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            if style == "pascal" and _e_prosa_com_classe(clean_text, m.group(1)):
                return None
            return style, m.group(1)
    return None


# --- Fala natural: gaguejo, retratação e maiúscula depois da vírgula (Bloco 10) ---------------
# Nos ditados do dono, a mesma palavra repetida por hesitação passava para o texto ("pesquisa
# Pesquisa a loja", "até até dois ou três arquivos", "consegue, consegue me dar", "Gostei,
# Gostei"): a limpeza só conhecia 43 palavras curtas (29 em português, 14 em inglês), e exigia
# espaço antes da vírgula.

# Repetição que é a própria palavra, e não gaguejo: "muito, muito bom", "não, não precisa", "já
# já chego", "tchau tchau", "calma, calma", "obrigado, obrigado mesmo".
_REPETICAO_EXPRESSIVA = frozenset(
    ["muito", "muita", "muitos", "muitas", "bem", "não", "nao", "sim", "já", "ja", "logo", "tchau", "ha", "blá", "bla", "corre", "pega", "quero", "bye", "no", "very", "so", "isso", "calma", "ok", "okay", "obrigado", "obrigada", "oi", "olá", "ola", "opa", "ei", "nossa", "valeu", "parabéns", "cuidado", "socorro", "espera", "pera", "anda", "vamos", "certo", "sei", "entendi", "claro", "beleza"])
# Duas palavras iguais da própria gramática, só com espaço: "ele para para descansar", "eu como
# como um leão", "I had had enough". Com vírgula ou reticências entre elas, é gaguejo. O "that that"
# sai, como antes do Bloco 10.
_DOBRA_GRAMATICAL = frozenset(["para", "como", "had"])
# Número por extenso: "zero zero sete" é o número. O "um" e o "uma" são também o artigo ("comprei
# um, um carro"): só são número ao lado de outro número.
_NUMEROS = frozenset(["zero", "um", "uma", "dois", "duas", "três", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze", "quatorze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa", "cem", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos", "mil", "meia"])
# Os gaguejos que a limpeza já tirava antes do Bloco 10, só com espaço entre eles ("Eu Eu acho",
# "que que"): continuam saindo como antes, fora o número ("um um dois") e as dobras da gramática.
_GAGUEJO_DE_SEMPRE = frozenset(["eu", "tu", "ele", "ela", "nós", "eles", "elas", "o", "a", "os", "as", "um", "uma", "que", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "para", "pra", "com", "por", "se", "i", "you", "the", "that", "this", "to", "in", "for", "we", "they", "he", "she", "it", "is"])
# Na mesma linha: a quebra de linha separa itens ("leite\nleite condensado"), não gagueja. E a palavra
# inteira: "react react-dom" e "flask flask-cors" são dois termos.
_GAGUEJO = re.compile(r'(?<![\w.-])(\w+)([ \t]*(?:,|\.{2,3}|…)[ \t]*|[ \t]+)(\1)\b(?![-.]\w)', re.IGNORECASE)
# Depois da repetida, um item de lista: "maçã, maçã verde e banana", "café, café com leite e suco"
# (até três palavras e "e", "ou" ou vírgula). O gaguejo segue a frase: "consegue, consegue me dar
# um exemplo".
_ITEM_DE_LISTA = re.compile(r'[ \t]+\w+(?:[ \t]+\w+){0,2}(?:[ \t]+(?:e|ou)\b|,)', re.IGNORECASE)
# O começo de uma palavra largado antes dela, no começo da frase: "O, oi, Willy", "A, amanhã a gente
# vê". No meio da frase, o "A" e o "O" antes da vírgula são a letra: "Bloco A, apartamento 12",
# "Vitamina A, antioxidante". O "E" fica: "E, eu acho" é a conjunção.
_FRAGMENTO = re.compile(r'\b([oa])\s*(?:,|\.{2,3}|…)\s*(?=\1\w)', re.IGNORECASE)

# Retratação dita: a frase interrompida ("então vou ter que...") seguida de "Esqueça disso.",
# "Esquece isso." ou "Cancela isso." sai inteira, com o marcador, e fica a frase que veio depois (o
# exemplo do pedido: "Esse computador tá sem microfone, então vou ter que... Esqueça disso. É
# microfone" -> "É microfone"). Interrompida é a que para numa palavra que pede continuação ("ter
# que...", "fui ao banco e...", "ele vai...") antes das reticências ou do travessão, e o marcador é
# uma frase (com ponto). Fora disso o marcador pode ser o recado: "O pedido entrou duplicado...
# cancela isso, por favor" e "Aquela reunião de amanhã... esquece isso, foi cancelada" pedem ao
# leitor (juiz do Bloco 10, 2ª rodada). O resto ("deixa pra lá", "cancela tudo", "quer dizer", "ou
# melhor") é com o refino, que vê o contexto. O hífen não conta: "Item 3 - esquece isso". O "é" e o
# "tá" não entram: também são a hesitação e o "ok" ("duplicado, é...", "Então tá...", "Pois é...",
# "Tudo bem tá..."), e o marcador depois deles é o recado (juiz do Bloco 10, 5ª a 7ª rodadas); "O
# problema é... Esquece isso." fica para o refino. Entre a palavra e as reticências do marcador, na
# mesma linha, podem vir hesitações e a própria palavra repetida (o Whisper põe maiúscula depois das
# reticências), depois de uma vírgula ou de reticências (também de dois pontos, como no gaguejo):
# "ter que, né...", "ter que... ééé...", "ter que... é... Que... Que...." (juiz do Bloco 10, 7ª e 8ª
# rodadas), até 8 delas: sem teto, uma sequência longa sem o marcador no fim fazia cada começo
# percorrer o resto dela. Só com espaço, a hesitação de uma letra só é o verbo: "o que é..." fica.
# As hesitações fonéticas que a limpeza tira (o passo 1 da clean_filler_words) são as que a
# retratação aceita antes das reticências: com uma lista só para as duas, "ter que, hmm... Esqueça
# disso." não deixa mais o marcador no meio da frase (juiz do Bloco 10, 14ª rodada). O "hum" de um m
# só não sai da limpeza (em inglês é palavra), mas é hesitação antes das reticências da retratação.
_HESITACOES = r'é{2,}|e{2,}h+|h+u+m{2,}|u+h+m+|h+m+|ã+h*|a{2,}h+|u+m{2,}|u+h{2,}|e+r{2,}'
_RETRATACAO = re.compile(
    r'\b(que|de|do|da|dos|das|e|ou|mas|a|o|as|os|um|uma|pra|para|pro|com|em|no|na|nos|nas|por|pelo|'
    r'pela|se|quando|como|porque|vou|vai|vamos|vão|ia|iam|tenho|tem|temos|preciso|precisa|quero|queria|'
    r'posso|pode|era|foi|está|estava)\b'
    r'(?:(?:,|[ \t]*(?:\.{2,}|…))[ \t]*(?:né|tipo|é+|hum+|' + _HESITACOES + r'|\1)\b'
    r'|[ \t]+(?:né|tipo|hum+|' + _HESITACOES + r')\b){0,8}'
    r'(?:\s*(?:\.{3}|…)|\s+[—–])\s*'
    r'(?:esque[çc][ae]\s+(?:disso|isso)|cancela\s+isso)\s*[.!]+\s+(?=\S)', re.IGNORECASE)
# Fim de frase de verdade, para achar o começo da que foi interrompida: o ponto, a interrogação e a
# exclamação (também antes de aspas ou parêntese: '"tudo certo." Agora'), as reticências antes de
# maiúscula ("O cliente reclamou de novo... Amanhã eu vou ter que..."), os dois-pontos e a quebra de
# linha. Não as reticências antes de minúscula ("Então... vou ter que..."), nem o ponto de um título
# ("o Sr. João e ele vai... Esquece isso."). O de "etc.", "Ltda." ou de uma letra ("bloco A.") pode
# fechar a frase de antes, e na dúvida fecha: a frase completa fica (juiz do Bloco 10, 2ª e 3ª
# rodadas).
_FIM_DE_FRASE_ANTERIOR = re.compile(
    r'(?<!\.)[.?!]["”’\')\]»]*\s|(?:\.{3}|…)["”’\')\]»]*\s+(?=[A-ZÀ-Ý])|:\s|\n')

# Maiúscula depois de vírgula: o Whisper capitaliza depois de uma pausa ("E, Fica mais razoável";
# "pequenas casas, Me parece"), e a limpeza que tira a muleta da vírgula deixa a maiúscula solta.
# Só as palavras comuns voltam à minúscula: um nome, uma sigla ou um termo do vocabulário fora
# desta lista ficam como vieram.
_COMUNS = frozenset(["a", "o", "as", "os", "um", "uma", "uns", "umas", "e", "é", "ou", "mas", "nem", "que", "se", "me", "te", "lhe", "nos", "vos", "eu", "tu", "ele", "ela", "eles", "elas", "você", "vocês", "nós", "gente", "isso", "isto", "aquilo", "esse", "essa", "este", "esta", "esses", "essas", "estes", "estas", "aquele", "aquela", "aqueles", "aquelas", "meu", "minha", "meus", "minhas", "teu", "tua", "seu", "sua", "seus", "suas", "nosso", "nossa", "nossos", "nossas", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "num", "numa", "para", "pra", "pro", "por", "pelo", "pela", "pelos", "pelas", "com", "sem", "sobre", "entre", "até", "após", "desde", "não", "sim", "já", "ainda", "também", "só", "sempre", "nunca", "agora", "hoje", "ontem", "amanhã", "depois", "antes", "então", "aí", "ali", "aqui", "lá", "cá", "assim", "bem", "mal", "mais", "menos", "muito", "muita", "muitos", "muitas", "pouco", "tão", "quase", "talvez", "logo", "cedo", "tarde", "realmente", "basicamente", "principalmente", "inclusive", "enfim", "aliás", "porém", "contudo", "entretanto", "todavia", "portanto", "porque", "pois", "quando", "onde", "como", "quanto", "qual", "quais", "quem", "tudo", "nada", "algo", "alguém", "ninguém", "cada", "todo", "toda", "todos", "todas", "outro", "outra", "outros", "outras", "mesmo", "mesma", "é", "são", "era", "foi", "será", "seria", "está", "estava", "estão", "estou", "tá", "tô", "vou", "vai", "vamos", "vão", "fui", "tem", "tinha", "tenho", "temos", "têm", "há", "havia", "fica", "fico", "ficou", "ficar", "parece", "pareceu", "acho", "achei", "acha", "achamos", "gostei", "gosto", "gosta", "vale", "valeu", "dá", "deu", "dar", "faz", "fez", "fazer", "pode", "posso", "podia", "podemos", "quero", "queria", "preciso", "precisa", "sei", "sabe", "sabia", "vejo", "vê", "viu", "olha", "olhe", "veja", "diz", "disse", "falou", "falei", "acredito", "imagino", "lembro", "entendi", "entendo", "funciona", "funcionou", "consegue", "consigo", "conseguiu", "tipo", "ok", "beleza", "certo", "claro", "bom", "ah", "oh", "pronto", "perfeito", "ótimo", "legal", "show", "obrigado", "obrigada"])
# Com outra maiúscula logo depois, na mesma linha, é nome de duas palavras ("São Paulo"): fica. A da
# linha de baixo é outra linha ("aguardo, Obrigado\nJoão"; juiz do Bloco 10, 14ª rodada).
_DEPOIS_DA_VIRGULA = re.compile(r',(\s+)([A-ZÀ-Ý][a-zà-ÿ]*)\b(?![ \t]+[A-ZÀ-Ý])')
# A mesma palavra com maiúscula no meio de uma frase, depois de outra palavra ("a Vale
# anunciou", "A Vale anunciou"): é nome, e fica com maiúscula também depois da vírgula.
_MAIUSCULA_NO_MEIO = re.compile(r'(?<=\w\s)([A-ZÀ-Ý][a-zà-ÿ]+)')


# Quanto texto as regras do gaguejo olham em volta da repetição. Copiar o texto inteiro a cada uma
# levava 38 s numa transcrição de 500 mil caracteres com muitas repetições (a main, 0,3 s).
_VIZINHANCA = 200


def _no_comeco_da_frase(texto: str, posicao: int) -> bool:
    # O começo da linha não conta como começo da frase (o rstrip() tira a quebra): numa lista ditada
    # linha a linha, "Leite, Leite condensado" são dois itens. Na dúvida, a palavra fica.
    antes = texto[max(0, posicao - _VIZINHANCA):posicao].rstrip()
    return not antes or antes[-1] in '.?!'


def _depois_da_virgula(texto: str, posicao: int) -> bool:
    return texto[max(0, posicao - _VIZINHANCA):posicao].rstrip(' \t').endswith(',')


def _e_repeticao_de_verdade(m: re.Match) -> bool:
    """A palavra repetida é a própria fala, e não gaguejo. Na dúvida, fica: o gaguejo que sobra o
    refino ainda tira, e a palavra apagada aqui não volta."""
    palavra, separador, repetida = m.group(1), m.group(2), m.group(3)
    base = palavra.lower()
    if not palavra.isalpha():
        return True
    so_espaco = not separador.strip()
    # Só com espaço, o "no no" é o gaguejo de sempre ("Deixei no no armário"); com vírgula, a ênfase
    # do inglês ("No, no, I said") (juiz do Bloco 10, 11ª rodada).
    if base in _REPETICAO_EXPRESSIVA and not (so_espaco and base in _GAGUEJO_DE_SEMPRE):
        return True
    if so_espaco and base in _DOBRA_GRAMATICAL:
        return True
    depois = m.string[m.end():m.end() + _VIZINHANCA]
    if base in _NUMEROS:
        seguinte = re.match(r'\W*(\w+)', depois)
        if base not in ("um", "uma") or (seguinte and seguinte.group(1).lower() in _NUMEROS):
            return True
    if so_espaco and base in _GAGUEJO_DE_SEMPRE:
        return False
    comum = base in _COMUNS
    # "Bora Bora", "Walla Walla": duas maiúsculas só com espaço é nome, também no começo da frase. A
    # letra também ("B B são as notas"): o "I I" e o "A A" já saíram pelos gaguejos de sempre.
    if so_espaco and not comum and palavra[0].isupper() and repetida[0].isupper():
        return True
    # A maiúscula no meio da frase é a letra ou o nome: "A, B, B e C", "Tipo O, o mais comum". O nome
    # também dos dois lados da vírgula: "Eu moro em Curitiba, Curitiba é fria". Não logo depois de
    # outra vírgula, onde a maiúscula é a do Whisper depois da pausa: "Ontem eu, Liguei, Liguei pro
    # cliente" (juiz do Bloco 10, 5ª rodada); nem em palavra comum ("Gostei, Gostei").
    if (not _no_comeco_da_frase(m.string, m.start()) and palavra[0].isupper()
            and (len(palavra) == 1 or repetida[0].islower()
                 or (not comum and not _depois_da_virgula(m.string, m.start())))):
        return True
    # Reticências e maiúscula depois: outra frase ("Ele foi embora... Embora eu não quisesse").
    if separador.strip() in ('...', '..', '…') and palavra[0].islower() and repetida[0].isupper():
        return True
    # O item de lista: "maçã, maçã verde e banana", e o repetido em minúscula com outro item
    # depois: "positivo, positivo, negativo". "Gostei, Gostei, Vale" (a maiúscula do Whisper
    # depois da pausa) é gaguejo.
    if (not comum and ',' in separador
            and (_ITEM_DE_LISTA.match(depois) or (repetida[0].islower() and re.match(r'[ \t]*,[ \t]*\w', depois)))):
        return True
    # A repetida que fecha a frase é a própria fala: "Quem sabe, sabe.", "O que é, é.", "Se tem, tem."
    # Com a maiúscula do Whisper ("Gostei, Gostei."), é o gaguejo.
    if ',' in separador and repetida[0].islower() and re.match(r'[ \t]*(?:[.?!…]|$)', depois):
        return True
    # A ênfase antes de "e" ou "mas", também em três: "Procurei, procurei e não achei", "Tentei,
    # tentei, mas não deu", "Falei, falei, falei e ninguém ouviu".
    if base not in _GAGUEJO_DE_SEMPRE and re.match(
            r'(?:[ \t]*,[ \t]*' + re.escape(base) + r'\b)*[ \t]*,?[ \t]*(?:e|mas)\b', depois, re.IGNORECASE):
        return True
    # A frase exclamativa repete de propósito: "Vai, vai, vai!", "Para, para, para com isso!".
    fim = re.search(r'[.?!\n]', depois)
    return bool(fim and fim.group() == '!')


def _sem_gaguejo(m: re.Match) -> str:
    return m.group(0) if _e_repeticao_de_verdade(m) else m.group(1)


def _sem_fragmento(m: re.Match) -> str:
    return '' if _no_comeco_da_frase(m.string, m.start()) else m.group(0)


def _sem_gaguejos(texto: str) -> str:
    # "até até até": cada passada junta um par.
    for _ in range(4):
        novo = _GAGUEJO.sub(_sem_gaguejo, texto)
        if novo == texto:
            break
        texto = novo
    return _FRAGMENTO.sub(_sem_fragmento, texto)


def _sem_retratacao(texto: str) -> str:
    """Tira cada frase interrompida e o marcador dela (ver _RETRATACAO). Numa passada: o começo da
    frase é procurado só entre a retratação anterior e esta (antes, o texto inteiro a cada uma)."""
    partes, desde = [], 0
    for m in _RETRATACAO.finditer(texto):
        # Até um caractere depois do começo da retratação: as reticências antes de maiúscula só fecham a
        # frase de antes vendo a maiúscula, e ela é a primeira letra da interrompida quando esta tem
        # uma palavra só ("Ficou tudo pronto... Mas... Esquece isso.", juiz do Bloco 10, 6ª rodada).
        # Nenhum fim termina depois do começo: a retratação começa numa letra.
        # O ponto de um título não fecha a frase, a não ser com uma quebra de linha depois ("Liguei pro
        # Dr...\nVou... Esquece isso.", juiz do Bloco 10, 7ª rodada).
        fins = [f for f in _FIM_DE_FRASE_ANTERIOR.finditer(texto, desde, m.start() + 1)
                if f.group()[0] != '.' or '\n' in f.group() or _abreviatura(texto, f.start()) != "no_meio"]
        inicio = fins[-1].end() if fins else desde
        antes = texto[desde:inicio]
        if antes and not antes[-1].isspace():
            antes += " "
        partes.append(antes)
        desde = m.end()
    partes.append(texto[desde:])
    return "".join(partes)


def _minuscula_depois_da_virgula(texto: str, protegidas: AbstractSet[str] = frozenset()) -> str:
    """`protegidas`: as palavras com maiúscula dos termos do vocabulário ("Claro", "Vale"), que
    ficam como vieram mesmo sendo também palavras comuns."""
    nomes = set(_MAIUSCULA_NO_MEIO.findall(texto))

    def _troca(m: re.Match) -> str:
        palavra = m.group(2)
        if palavra.lower() not in _COMUNS or palavra in nomes or palavra in protegidas:
            return m.group(0)
        # Lista de nomes: "Petrobras, Vale e Itaú". O de antes da vírgula, com maiúscula no meio da
        # frase e fora das palavras comuns, é nome, e o seguinte também.
        # Só o trecho antes da vírgula: copiar o texto inteiro a cada vírgula levava 33 s numa
        # transcrição de 500 mil caracteres com 3 mil delas antes de maiúscula (a main, 0,3 s).
        inicio = max(0, m.start() - _VIZINHANCA)
        antes = m.string[inicio:m.start()].rstrip()
        anterior = re.search(r'(\S+)$', antes)
        if anterior:
            palavra_antes = anterior.group(1).strip('"\'“”(')
            comeco = antes[:anterior.start()].rstrip()
            no_comeco = not comeco or comeco[-1] in '.?!:'
            if palavra_antes[:1].isupper() and palavra_antes.lower() not in _COMUNS and not no_comeco:
                return m.group(0)
        return ',' + m.group(1) + palavra.lower()

    return _DEPOIS_DA_VIRGULA.sub(_troca, texto)


class TextProcessor:
    """Processador de transcrições e comandos de pontuação por voz."""

    # Domínios de internet comuns falados com "ponto"
    DOMAIN_EXTENSIONS = r'(com|net|org|br|io|dev|ai|app|gov|edu|me)'

    # Trade-off aceito: em "Número um ponto." e "Espera um segundo ponto", "ponto" fica como palavra; em "Esse ponto, por exemplo, é bom.", vira "." (como na main).
    _ARTIGO_OU_CONTRACAO = r'(?:o|um|do|no|ao|pelo|num|dum)'
    _DET_COM_ARTIGO = r'(?:mesmo|primeiro|segundo|último|único|meu|seu|teu|nosso|outro)'
    _DET_SEM_ARTIGO = (
        r'(?:meu|seu|teu|nosso|esse|este|aquele|desse|deste|daquele|nesse|neste|naquele'
        r'|algum|nenhum|cada|outro|qualquer)'
    )
    _SINAL_DE_PONTO = r'(?:\s+de\s+(?:interrogação|exclamação))?'
    _SINAL_OU_FINAL = r'(?:\s+final|\s+de\s+(?:interrogação|exclamação))?+'
    _PONTO_SUBSTANTIVO = (
        rf'[ \t]*[,.;:!?]*[ \t]*\b(?:'
        rf'(?:{_ARTIGO_OU_CONTRACAO}\s+{_DET_COM_ARTIGO}|{_ARTIGO_OU_CONTRACAO}|em)\s+ponto{_SINAL_DE_PONTO}'
        rf'|{_DET_SEM_ARTIGO}\s+ponto{_SINAL_OU_FINAL}(?=[ \t]+[A-Za-zÀ-ÿ0-9])'
        rf'|ponto\s+de\s+(?!(?:interrogação|exclamação)\b)[A-Za-zÀ-ÿ]+)\b'
        rf'(?!\s+e\s+vírgula\b)(?!\s+{DOMAIN_EXTENSIONS}\b)'
    )

    # Fonte única para apply_voice_commands e ditou_pontuacao: (padrão, substituto ou None se substantivo, fecha_frase).
    # O sinal ditado descarta [,.;:!?] que o Whisper colocou ao redor da palavra do comando.
    _REGRAS_DE_COMANDO_DE_VOZ: ClassVar[tuple[tuple[str, str | None, bool], ...]] = (
        (_PONTO_SUBSTANTIVO, None, False),
        (rf'[ \t]*[,.;:!?]*[ \t]*\bponto\s+(?P<dominio>{DOMAIN_EXTENSIONS})\b', '.', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\bponto\s+e\s+vírgula\b(?:[ \t]*[,.;:!?]+)?', ';', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\bdois\s+pontos\b(?:[ \t]*[,.;:!?]+)?', ':', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\bponto\s+de\s+interrogação\b(?:[ \t]*[,.;:!?]+)?', '?', True),
        (r'[ \t]*[,.;:!?]*[ \t]*\bponto\s+de\s+exclamação\b(?:[ \t]*[,.;:!?]+)?', '!', True),
        (r'[ \t]*[,.;:!?]*[ \t]*\bponto\s+final\b(?:[ \t]*[,.;:!?]+)?', '.', True),
        (r'\bnovo\s+parágrafo\b(?:[ \t]*[,.;:!?]+)?', '\n\n', False),
        (r'\b(?:nova\s+linha|quebra\s+de\s+linha)\b(?:[ \t]*[,.;:!?]+)?', '\n', False),
        (r'\b(?:abrir\s+aspas|abre\s+aspas)\b[ \t]*[,.;:!?]*[ \t]*', '"', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\b(?:fechar\s+aspas|fecha\s+aspas)\b', '"', False),
        (r'\b(?:abrir\s+parênteses|abre\s+parênteses)\b[ \t]*[,.;:!?]*[ \t]*', '(', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\b(?:fechar\s+parênteses|fecha\s+parênteses)\b', ')', False),
        (r'\b(?:abrir\s+chaves|abre\s+chaves)\b[ \t]*[,.;:!?]*[ \t]*', '{', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\b(?:fechar\s+chaves|fecha\s+chaves)\b', '}', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\binterrogação\b(?:[ \t]*[,.;:!?]+)?', '?', True),
        (r'[ \t]*[,.;:!?]*[ \t]*\bexclamação\b(?:[ \t]*[,.;:!?]+)?', '!', True),
        (r'[ \t]*[,.;:!?]*[ \t]*\bvírgula\b(?:[ \t]*[,.;:!?]+)?', ',', False),
        (r'[ \t]*[,.;:!?]*[ \t]*\bponto\b(?:[ \t]*[,.;:!?]+)?', '.', True),
    )
    _COMANDO_DE_VOZ = re.compile(
        '|'.join(f'(?P<c{i}>{padrao})' for i, (padrao, _, _) in enumerate(_REGRAS_DE_COMANDO_DE_VOZ)),
        re.IGNORECASE,
    )

    VOICE_COMMANDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("ponto ou ponto final", "Insere '.'"),
        ("vírgula", "Insere ','"),
        ("dois pontos", "Insere ':'"),
        ("ponto e vírgula", "Insere ';'"),
        ("interrogação ou ponto de interrogação", "Insere '?'"),
        ("exclamação ou ponto de exclamação", "Insere '!'"),
        ("nova linha ou quebra de linha", "Insere quebra de linha (\\n)"),
        ("novo parágrafo", "Insere linha em branco (\\n\\n)"),
        ("abrir aspas ou fechar aspas", 'Insere aspas (")'),
        ("abrir parênteses ou fechar parênteses", "Insere parênteses ( e )"),
        ("abrir chaves ou fechar chaves", "Insere chaves { e }"),
        ("ponto com / ponto br", "Insere domínio colado (.com, .br, .io, .dev...)"),
    )

    # Como o Whisper escreve o nome do assistente quando ele não está no vocabulário ("no Weeley",
    # "o Willi está com dificuldade"). Só grafias que não são outra palavra: Wiley e Wylie são
    # sobrenomes, e ficam.
    _NOME_DO_WILLY = re.compile(r"\b(?:weeley|weely|willi|wili|wíli|uili|uíli|uilli|uilly|uíly)\b", re.IGNORECASE)

    @classmethod
    def normalizar_nome_do_willy(cls, text: str) -> str:
        """Escreve "Willy" onde o Whisper grafou o nome do assistente de outro jeito."""
        return cls._NOME_DO_WILLY.sub("Willy", text) if text else text

    @classmethod
    def apply_voice_commands(cls, text: str) -> str:
        """Substitui comandos falados por pontuações e quebras de linha."""
        if not text:
            return ""

        def _substituir_comando(m: re.Match) -> str:
            _, substituto, _ = cls._REGRAS_DE_COMANDO_DE_VOZ[int(m.lastgroup[1:])]
            if substituto is None:
                return m.group(0)
            if m.group("dominio"):
                return f".{m.group('dominio').lower()}"
            return substituto

        res = cls._COMANDO_DE_VOZ.sub(_substituir_comando, text)

        # Remove espaços antes de pontuações (sem comer quebras de linha)
        res = re.sub(r'[ \t]+([.,:;?!])', r'\1', res)

        # Normaliza espaços após pontuações (se houver 1 ou mais espaços na mesma linha, colapsa para 1)
        res = re.sub(r'([.,:;?!])[ \t]+', r'\1 ', res)

        # Garante espaço após pontuações quando seguido diretamente por letra (exceto números decimais e domínios)
        res = re.sub(r'([,:;?!])([A-Za-zÀ-ÿ])', r'\1 \2', res)

        # Ajusta espaços ao redor de quebras de linha
        res = re.sub(r'[ \t]*\n[ \t]*', '\n', res)

        # Capitalização inteligente após pontuação terminal (. ? !) ou nova linha
        res = cls.capitalize_sentences(res)

        return res.strip()

    @classmethod
    def capitalize_sentences(cls, text: str) -> str:
        """Capitaliza a primeira letra e as letras após sinais de fim de frase ou novas linhas."""
        if not text:
            return ""

        def _cap_fim_frase(m: re.Match) -> str:
            if m.group(1)[0] == "." and _abreviatura(m.string, m.start(), inicial_conta=False) is not None:
                return m.group(0)
            return m.group(1) + m.group(2).upper()

        def _cap_linha(m: re.Match) -> str:
            return m.group(1) + m.group(2).upper()

        s = text
        # Início do texto
        if s and s[0].islower():
            s = s[0].upper() + s[1:]

        # Após ponto, interrogação ou exclamação seguidos de espaço (exceto abreviaturas)
        s = re.sub(r'([.?!]\s+)([a-zà-öø-ÿ])', _cap_fim_frase, s)
        # Após nova linha
        s = re.sub(r'(\n+)([a-zà-öø-ÿ])', _cap_linha, s)

        return s

    @classmethod
    def strip_accents(cls, text: str) -> str:
        """Remove acentos e diacríticos de uma string preservando caracteres ASCII."""
        if not text:
            return ""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    @classmethod
    def estilo_de_identificador(cls, text: str) -> str | None:
        """O estilo pedido pelo prefixo da fala ("snake", "upper"...), ou None sem prefixo."""
        casado = _casar_identificador(text)
        return casado[0] if casado else None

    @classmethod
    def format_code_identifier(cls, text: str) -> str | None:
        """
        Detecta comandos de formatação de código por voz e formata as palavras subsequentes.
        Exemplos:
          - "variável nome do usuário" -> "nome_do_usuario"
          - "snake case total de vendas" -> "total_de_vendas"
          - "camel case data de nascimento" -> "dataDeNascimento"
          - "pascal case cliente especial" -> "ClienteEspecial"
          - "classe pedido de compra" -> "PedidoDeCompra"
          - "kebab case meu novo artigo" -> "meu-novo-artigo"
          - "slug post do blog" -> "post-do-blog"
          - "constante chave de api" -> "CHAVE_DE_API"
          - "caixa baixa Título Aqui" -> "título aqui"
          - "caixa alta aviso importante" -> "AVISO IMPORTANTE"
        Retorna None se o texto não contiver nenhum prefixo de formatação.
        """
        if not text:
            return None

        casado = _casar_identificador(text)
        if casado:
            style, payload = casado
            payload = payload.strip()
            if not payload:
                return None

            if style == 'lower':
                return payload.strip(".,;:?! \t\n\r").lower()
            elif style == 'upper':
                return payload.strip(".,;:?! \t\n\r").upper()

            # Para identificadores de programação, extrai palavras e remove acentos
            raw_words = re.findall(r'[A-Za-z0-9À-ÿ]+', payload)
            if not raw_words:
                return None

            clean_words = [cls.strip_accents(w) for w in raw_words if w]
            if not clean_words:
                return None

            if style == 'snake':
                return "_".join(w.lower() for w in clean_words)
            elif style == 'camel':
                first = clean_words[0].lower()
                rest = "".join(w.capitalize() for w in clean_words[1:])
                return first + rest
            elif style == 'pascal':
                return "".join(w.capitalize() for w in clean_words)
            elif style == 'kebab':
                return "-".join(w.lower() for w in clean_words)
            elif style == 'constant':
                return "_".join(w.upper() for w in clean_words)

        return None

    @classmethod
    def apply_replacements(cls, text: str, replacements: dict[str, str] | None = None) -> str:
        """
        Aplica regras de substituição fonética/determinística (De -> Para).
        Usa limites de palavra e substituição case-insensitive de forma segura.
        """
        if not text or not replacements:
            return text

        res = text
        for de, para in replacements.items():
            if not de or not para:
                continue
            de_clean = str(de).strip()
            para_clean = str(para).strip()
            if not de_clean or not para_clean:
                continue
            pattern = r'(?<!\w)' + re.escape(de_clean) + r'(?!\w)'
            try:
                res = re.sub(pattern, lambda _, p=para_clean: p, res, flags=re.IGNORECASE)
            except Exception as e:  # noqa: BLE001 — fronteira defensiva: falha inesperada em substituição de usuário
                print(
                    f"[TextProcessor] Erro ao aplicar substituição ({de_clean!r} -> {para_clean!r}): {e!r}",
                    file=sys.stderr,
                )

        return res

    @classmethod
    def detect_voice_tone(cls, text: str) -> tuple[str, str | None]:
        """
        Detecta comandos de tom de voz falados no início da transcrição.
        Exemplos:
          - "Willy formal: Prezado cliente, segue..." -> ("Prezado cliente, segue...", "formal")
          - "Willy executivo: Aprovamos o orçamento..." -> ("Aprovamos o orçamento...", "formal")
          - "Willy conciso: Reunião adiada para amanhã" -> ("Reunião adiada para amanhã", "concise")
          - "Willy direto: Deploy finalizado" -> ("Deploy finalizado", "concise")
          - "Willy em tópicos: comprar café, revisar PR" -> ("Comprar café, revisar PR", "bullet_points")
          - "Willy bullet points: item um, item dois" -> ("Item um, item dois", "bullet_points")
          - "Willy técnico: rode npm run build" -> ("Rode npm run build", "technical")
          - "Willy dev: crie um commit assinado" -> ("Crie um commit assinado", "technical")
          - "Willy natural: Apenas transcreva sem mudar nada" -> ("Apenas transcreva sem mudar nada", "natural")
          - "Modo formal: Prezado senhor..." -> ("Prezado senhor...", "formal")
        Retorna (texto_restante, tom_identificado) ou (texto_original, None).
        """
        if not text:
            return ("", None)

        clean = text.strip()
        tone_map = {
            "formal": "formal",
            "executivo": "formal",
            "conciso": "concise",
            "direto": "concise",
            "rápido": "concise",
            "rapido": "concise",
            "concise": "concise",
            "em tópicos": "bullet_points",
            "em topicos": "bullet_points",
            "tópicos": "bullet_points",
            "topicos": "bullet_points",
            "bullet points": "bullet_points",
            "bullets": "bullet_points",
            "bullet": "bullet_points",
            "técnico": "technical",
            "tecnico": "technical",
            "technical": "technical",
            "dev": "technical",
            "natural": "natural",
            "fiel": "natural",
        }

        # 1. Prefixo com "Willy" ou "Ei Willy"
        pattern_willy = (
            r'^(?:ei\s+)?willy\s*[,:]?\s*(?:em\s+tom\s+|modo\s+)?'
            r'(formal|executivo|conciso|direto|r[aá]pido|concise|em\s+t[oó]picos|t[oó]picos|bullet\s+points|bullets|bullet|t[eé]cnico|technical|dev|natural|fiel)'
            # \b: sem ele, "Willy, formalize este e-mail" virava "Ize este e-mail" em tom formal.
            r'\b\s*[:,-]?\s*(.+)$'
        )
        m = re.match(pattern_willy, clean, flags=re.IGNORECASE | re.DOTALL)
        if m:
            raw_tone = m.group(1).lower().strip()
            rest = m.group(2).strip()
            if rest:
                tone = tone_map.get(raw_tone, "natural")
                rest = cls.capitalize_sentences(rest)
                return (rest, tone)

        # 2. Prefixo explícito "Modo <tom>:" ou "Tom <tom>:"
        pattern_modo = (
            r'^(?:modo|tom)\s+'
            r'(formal|executivo|conciso|direto|r[aá]pido|concise|t[oó]picos|bullet\s+points|bullets|t[eé]cnico|technical|dev|natural|fiel)'
            r'\b\s*[:,-]?\s*(.+)$'
        )
        m2 = re.match(pattern_modo, clean, flags=re.IGNORECASE | re.DOTALL)
        if m2:
            raw_tone = m2.group(1).lower().strip()
            rest = m2.group(2).strip()
            if rest:
                tone = tone_map.get(raw_tone, "natural")
                rest = cls.capitalize_sentences(rest)
                return (rest, tone)

        return (text, None)

    @classmethod
    def clean_filler_words(cls, text: str, vocabulario: Iterable[str] = ()) -> str:
        """
        Remove hesitações vocais, vícios de fala e repetições gaguejadas de transcrição (PT-BR e EN).
        Exemplos:
          - "então... ééé... vamos começar" -> "Então vamos começar"
          - "humm, precisamos tipo assim aprovar o PR, né?" -> "Precisamos aprovar o PR?"
          - "eu eu acho que que vai dar certo" -> "Eu acho que vai dar certo"
          - "umm, we should definitely try that, you know?" -> "We should definitely try that?"
          - "pesquisa Pesquisa a loja", "consegue, consegue me dar" -> uma palavra só
          - "Tá sem microfone, então vou ter que... Esqueça disso. É microfone" -> "É microfone"
          - "E, Fica mais razoável" -> "E, fica mais razoável"

        `vocabulario`: os termos do vocabulário da pessoa. Os com maiúscula ficam com ela depois da
        vírgula ("Liguei pra operadora, Claro não atende").
        """
        if not text:
            return ""

        # 0. Retratação dita: a frase interrompida e o "Esqueça disso." saem (ver _RETRATACAO). Antes
        # de tirar as hesitações: "Terminei a parte um... ééé... Agora vou ter que..." perdia as
        # reticências que fecham a frase de antes, e ela saía junto.
        res = _sem_retratacao(text)

        # 1. Hesitações fonéticas puras (ééé, ehhh, humm, uhmm, ãhh, umm, uhh, err) incluindo pontuações de pausa adjacentes.
        # "hum" com um m só fica: em inglês é palavra ("I hum a song" virava "I a song"). E o
        # ponto final encostado na hesitação fica: "Terminei. Ééé, vamos" virava "Terminei vamos".
        def _sem_hesitacao(m: re.Match) -> str:
            ponto_final = m.start() > 0 and re.search(r'(?<!\.)\.(?!\.)', m.group(0))
            return '. ' if ponto_final else ' '

        res = re.sub(rf'(?i)(?:[.,…-]+\s*)?\b({_HESITACOES})\b(?:[.,…\s-]*)', _sem_hesitacao, res)

        # 2. Vícios compostos: "tipo assim" e "aí tipo"
        res = re.sub(r'(?i)\b(tipo assim|aí tipo)\b[,.\s]*', ' ', res)

        # 3. Interjeições de cacoete: ", né?", ", né,", " né.", " né?" e English "you know"
        # O "?" era do "né": com mais fala depois, é a pausa de quem segue explicando ("o código
        # aqui, né? E vi que..."), e ficava colado na afirmação ("aqui? E vi"), que o refino
        # mantinha. No fim do texto, o "né?" é a tag de confirmação, e o "?" fica; falando com
        # alguém ("Você viu o meu e-mail, né? Responde..."), também.
        def _sem_cacoete(m: re.Match) -> str:
            pontuacao = m.group(1)
            if not pontuacao.startswith('?') or not m.string[m.end():].strip():
                return pontuacao
            inicio_da_frase = max(m.string.rfind(c, 0, m.start()) for c in '.?!\n"“') + 1
            if _FALA_COM_VOCE.match(m.string[inicio_da_frase:m.start()].lstrip()):
                return pontuacao
            return pontuacao.replace('?', '') or '.'  # "?!" fica "!"

        res = re.sub(r'(?i)[,;\s]+\bné\b([?.,!]*)', _sem_cacoete, res)
        res = re.sub(r'(?i)\bné\b[,;]?', '', res)
        # Só depois de vírgula: em "Do you know? I don't." o "you know" é a pergunta.
        res = re.sub(r'(?i)[,;]\s*\byou know\b([?.,!]*)', _sem_cacoete, res)

        # 4. Gaguejos: a mesma palavra repetida em seguida (ver _sem_gaguejo), e o começo de uma
        # palavra largado antes dela ("O, oi")
        res = _sem_gaguejos(res)

        # 5. Limpa pontuações órfãs ou duplas resultantes das remoções
        res = re.sub(r'([,;])\s*([,;])', r'\1', res)
        res = re.sub(r'\s+([.,:;?!])', r'\1', res)
        res = re.sub(r'([.,:;?!])\s+', r'\1 ', res)
        res = re.sub(r'^[,\s;:-]+', '', res)
        res = re.sub(r'[ \t]+', ' ', res)

        # 6. Recapitaliza frases se a limpeza removeu o início da frase, e tira a maiúscula que o
        # Whisper pôs depois de uma vírgula
        res = cls.capitalize_sentences(res)
        protegidas = {p for termo in vocabulario for p in re.findall(r'\w+', termo) if p[:1].isupper()}
        res = _minuscula_depois_da_virgula(res, protegidas)

        return res.strip()

    @classmethod
    def pontuar_perguntas(cls, text: str) -> str:
        """
        Corrige o fim de cada frase quando as palavras dizem se ela é pergunta, sem a entonação:
          - "Vai rodar depois do merge, certo." -> "Vai rodar depois do merge, certo?"
          - "Será que o problema está no cache." -> "Será que o problema está no cache?"
          - "Quero saber se posso transformar a loja em mercado?" -> "... em mercado."
          - "Ou seja, não vai sobrar muito?" -> "Ou seja, não vai sobrar muito."
        O resto fica como veio: "Como combinamos ontem, segue o arquivo." e "Se não der, tudo
        bem." continuam afirmação, e a pergunta de sim ou não é com o refino.
        """
        if not text:
            return ""
        partes, inicio = [], 0
        for fim in _FIM_DE_FRASE.finditer(text):
            abreviatura = _abreviatura(text, fim.start()) if fim.group() == "." else None
            # Só os caracteres logo depois: fatiar o resto do texto a cada ponto é quadrático.
            seguinte = text[fim.end():fim.end() + 8].lstrip()[:1]
            if abreviatura == "no_meio" or (abreviatura and not (seguinte.isupper() or seguinte.isdigit())):
                continue  # "o Dr. Carlos", "Kafka etc. nessa fase": a frase segue
            frase = text[inicio:fim.start()]
            sinal = fim.group()
            if abreviatura:
                pass  # "Kafka etc. Acho que não.": pode fechar a frase ou não; fica como veio
            elif sinal == "." and _e_pergunta_pela_forma(frase.strip()):
                sinal = "?"
            elif sinal == "?" and _e_afirmacao_pela_forma(frase.strip()):
                sinal = "."
            partes.append(frase + sinal)
            inicio = fim.end()
        partes.append(text[inicio:])
        return "".join(partes)

    @classmethod
    def ditou_pontuacao(cls, text: str) -> bool:
        """A fala crua tem "interrogação", "exclamação" ou "ponto" ditados (os comandos de voz que
        fecham frase): quem dita o sinal escolheu, e pontuar_perguntas não passa por cima dele."""
        return any(
            cls._REGRAS_DE_COMANDO_DE_VOZ[int(m.lastgroup[1:])][2]
            for m in cls._COMANDO_DE_VOZ.finditer(text or "")
        )

    @classmethod
    def detect_send_command(cls, text: str) -> tuple[str, bool]:
        """
        Detecta se a transcrição inicia com um comando de envio automático ('Willy enviar:', 'Willy mande:', etc.).
        Exemplos:
          - "Willy enviar: já cheguei no escritório" -> ("Já cheguei no escritório", True)
          - "Willy mande: Reunião confirmada para amanhã" -> ("Reunião confirmada para amanhã", True)
          - "Willy envie: o deploy foi finalizado" -> ("O deploy foi finalizado", True)
          - "Ei Willy enviar: bom dia a todos" -> ("Bom dia a todos", True)
          - "Texto normal sem comando" -> ("Texto normal sem comando", False)
        Retorna (texto_limpo, deve_enviar_enter).
        """
        if not text:
            return ("", False)

        clean = text.strip()
        # \b: sem ele, "Willy, mandei o arquivo?" virava "I o arquivo?" e ainda apertava Enter.
        pattern = r'^(?:ei\s+)?willy\s*[,:]?\s*(?:enviar|envie|mande|mandar|send)\b\s*[:,-]?\s*(.+)$'
        m = re.match(pattern, clean, flags=re.IGNORECASE | re.DOTALL)
        if m:
            payload = m.group(1).strip()
            if payload:
                payload = cls.capitalize_sentences(payload)
                return (payload, True)

        return (text, False)


def normalize_for_search(text: str) -> str:
    """Normaliza texto para busca case-insensitive e insensível a acentuação (ex: 'reunião' -> 'reuniao')."""
    if not text:
        return ""
    return TextProcessor.strip_accents(text.lower()).strip()


# A pontuação colada numa palavra não faz parte dela: "Willy," e "(Willy)" são "Willy". A de
# dentro fica ("Node.js", "e-mail").
_PONTUACAO_EM_VOLTA = ".,;:!?…\"'“”‘’«»()[]{}"
# Uma correção de vocabulário troca de 1 a 4 palavras; um trecho maior é frase reescrita.
_MAX_PALAVRAS_DA_CORRECAO = 4
# O quanto o errado precisa lembrar o certo (sem acento, maiúscula nem espaço): "vily"/"Willy"
# dá 0,67, "kubernets"/"Kubernetes" 0,95 e "fast api"/"FastAPI" 1,0. Trocar "segunda" por
# "terça" (0,17) muda o que foi dito: não é palavra que o Whisper ouviu errado.
_SEMELHANCA_MINIMA = 0.5


def _sem_pontuacao_em_volta(palavra: str) -> str:
    return palavra.strip(_PONTUACAO_EM_VOLTA)


def extrair_correcao_vocabulario(texto_antes: str, texto_depois: str) -> list[tuple[str, str]]:
    """Os pares (errado, certo) que a pessoa corrigiu ao editar um ditado, na ordem do texto.

    Compara as palavras sem a pontuação em volta (difflib): a pontuação que mudou não conta, e
    "vily," -> "Willy," dá ("vily", "Willy"). Cada trecho trocado de 1 a 4 palavras, dos dois
    lados, que lembre o original vira um par: "fast api" -> "FastAPI", "kubernets" ->
    "Kubernetes", e também a troca só de maiúscula ("willy" -> "Willy"). Frase reescrita,
    palavra acrescentada ou apagada e troca de sentido ficam de fora.
    """
    antes = [p for p in map(_sem_pontuacao_em_volta, (texto_antes or "").split()) if p]
    depois = [p for p in map(_sem_pontuacao_em_volta, (texto_depois or "").split()) if p]
    pares: list[tuple[str, str]] = []
    trechos = difflib.SequenceMatcher(None, antes, depois, autojunk=False).get_opcodes()
    for operacao, i1, i2, j1, j2 in trechos:
        if operacao != "replace":
            continue
        if not (i2 - i1 <= _MAX_PALAVRAS_DA_CORRECAO and j2 - j1 <= _MAX_PALAVRAS_DA_CORRECAO):
            continue
        errado, certo = " ".join(antes[i1:i2]), " ".join(depois[j1:j2])
        semelhanca = difflib.SequenceMatcher(
            None, normalize_for_search(errado).replace(" ", ""), normalize_for_search(certo).replace(" ", "")
        ).ratio()
        if semelhanca >= _SEMELHANCA_MINIMA and (errado, certo) not in pares:
            pares.append((errado, certo))
    return pares




