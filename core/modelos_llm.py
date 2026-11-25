"""
Os modelos de LLM que o Willy oferece, num lugar só.

Em 23/10/2026, os três que o Willy usava estavam desligados na Groq para os planos free e
developer (console.groq.com/docs/deprecations): llama-3.1-8b-instant e llama-3.3-70b-versatile
em 16/08/2026, gemma2-9b-it em 08/10/2025. Refino, prompt de agente, ata e transformar falhavam
em todo ditado. Os substitutos são os que a Groq indica.

Os IDs moravam em seis arquivos (config, serviço, Ajustes, bandeja, template do .env, docs), e
a config ainda recusava "gpt-oss" e "qwen", justamente os substitutos.
"""

import re
from typing import Any

FLASH = "openai/gpt-oss-20b"
SMART = "openai/gpt-oss-120b"
# Preview na Groq: pode sair sem o aviso de meses dos modelos de produção. O prompt de agente
# cai para o Smart e o Flash se ele falhar.
CODER = "qwen/qwen3.8-27b"
PADRAO = SMART
MODELOS_VALIDOS = frozenset({FLASH, SMART, CODER})
NOMES_AMIGAVEIS = {
    FLASH: "Flash",
    SMART: "Smart",
    CODER: "Coder",
}

# Desligados na Groq: o .env de quem escolheu um deles passa para o substituto. As datas são as
# de desligamento da página de descontinuações.
DESLIGADOS = {
    "llama-3.1-8b-instant": FLASH,        # 16/08/2026
    "llama-3.3-70b-versatile": SMART,     # 16/08/2026
    "gemma2-9b-it": CODER,                # 08/10/2025
    "qwen/qwen3.6-27b": CODER,            # 14/09/2026
    "qwen/qwen3-32b": CODER,              # 17/07/2026
    "qwen-qwq-32b": CODER,                # 14/07/2025
    "qwen-2.5-coder-32b": CODER,          # 14/04/2025
    "llama3-70b-8192": SMART,             # 30/08/2025
    "llama3-8b-8192": FLASH,              # 30/08/2025
    "deepseek-r1-distill-llama-70b": SMART,  # 02/10/2025
}

# A resposta de um modelo de raciocínio que pensa no próprio texto, entre <think> e </think> (ou
# <thinking>). O que sobra de uma abertura sem fim (resposta cortada no limite de tokens) também
# sai. E há modelos que omitem a abertura e só fecham: tudo até o último fechamento é raciocínio.
# Uma tag citada (entre crases, entre aspas ou num bloco de código) é texto, e não pensamento:
# um texto que explicava a tag, ou um XML transformado, perdia tudo o que vinha antes dela.
_PENSAMENTO = re.compile(r"<(think|thinking)>.*?(</\1>|$)\s*", re.DOTALL | re.IGNORECASE)
_FECHAMENTO = re.compile(r"</(?:think|thinking)>", re.IGNORECASE)
_PARES_DE_ASPAS = frozenset({("“", "”"), ("‘", "’"), ("«", "»")})


def _citada(texto: str, inicio: int, fim: int) -> bool:
    """A tag em texto[inicio:fim] está entre crases, entre aspas ou num bloco de código ```."""
    antes = texto[:inicio]
    if antes.count("```") % 2 == 1:
        return True
    if antes.replace("```", "").count("`") % 2 == 1:
        return True
    # Aspas dos dois lados: com uma só, um raciocínio terminado numa citação ("traduza"</think>)
    # passava por texto, e o raciocínio era colado junto. A aspa reta abre e fecha com o mesmo
    # caractere: é citação só se a da esquerda abre (ímpar antes da tag), senão 'pensei em
    # "bom dia"</think>"Good morning"' também passava.
    esquerda, direita = texto[inicio - 1:inicio], texto[fim:fim + 1]
    if esquerda == direita and esquerda in ('"', "'"):
        return antes.count(esquerda) % 2 == 1
    return (esquerda, direita) in _PARES_DE_ASPAS


def _sem_pensamento(m: "re.Match[str]") -> str:
    fim_da_abertura = m.start() + len(m.group(1)) + 2  # "<" + think + ">"
    return m.group(0) if _citada(m.string, m.start(), fim_da_abertura) else ""

# O raciocínio conta no limite de tokens da resposta: sem margem, um texto longo voltava
# cortado, ou vazio, com o modelo ainda pensando.
MARGEM_DO_RACIOCINIO = 512


def modelo_em_uso(modelo: Any) -> str:
    """O modelo que vale para um valor lido do .env ou de um perfil: vazio ou desconhecido vira o
    padrão, um desligado vira o substituto, e os suportados (FLASH, SMART, CODER) ficam."""
    nome = str(modelo or "").strip()
    if not nome:
        return PADRAO
    resolvido = DESLIGADOS.get(nome.lower(), nome)
    for valido in MODELOS_VALIDOS:
        if valido.lower() == resolvido.lower():
            return valido
    return PADRAO


def modelo_desconhecido(modelo: Any) -> bool:
    """Verdadeiro para um valor não vazio que não está em MODELOS_VALIDOS nem em DESLIGADOS."""
    nome = str(modelo or "").strip()
    if not nome:
        return False
    nome_lower = nome.lower()
    if nome_lower in DESLIGADOS:
        return False
    return all(valido.lower() != nome_lower for valido in MODELOS_VALIDOS)


def nome_amigavel(modelo: Any) -> str:
    """Nome curto do modelo para mensagens na pílula (Flash, Smart ou Coder)."""
    resolvido = modelo_em_uso(modelo)
    return NOMES_AMIGAVEIS.get(resolvido, resolvido)


def ordem_de_tentativa(modelo: Any) -> list[str]:
    """O modelo escolhido e, se ele recusar, os de reserva (Smart, depois Flash), sem repetir.

    O Coder está em preview e pode sair do ar sem aviso: sem reserva, todo refino, ata e
    transformar falhava junto com ele.
    """
    return list(dict.fromkeys([modelo_em_uso(modelo), SMART, FLASH]))


def eh_de_raciocinio(modelo: str) -> bool:
    nome = modelo.lower()
    return "gpt-oss" in nome or "qwen3" in nome


def parametros_de_raciocinio(modelo: str) -> dict[str, Any]:
    """O que pedir à Groq para que o raciocínio não chegue ao texto e não atrase o ditado."""
    nome = modelo.lower()
    if "gpt-oss" in nome:
        # O gpt-oss pensa sempre ("none" não existe nele); "low" é o mais rápido. O que ele pensa
        # vem num campo à parte, que nem precisa viajar.
        return {"reasoning_effort": "low", "include_reasoning": False}
    if "qwen3" in nome:
        # Sem isto o Qwen 3 escreve o raciocínio dentro de <think> no próprio texto.
        return {"reasoning_effort": "none"}
    return {}


def texto_sem_raciocinio(conteudo: Any) -> str:
    """O texto da resposta, sem <think>/<thinking>: o que o modelo pensou não pode ser colado."""
    texto = _PENSAMENTO.sub(_sem_pensamento, str(conteudo or ""))
    fim_do_raciocinio = None
    for m in _FECHAMENTO.finditer(texto):
        if not _citada(texto, m.start(), m.end()):
            fim_do_raciocinio = m.end()
    if fim_do_raciocinio is not None:
        texto = texto[fim_do_raciocinio:]
    return texto.strip()
