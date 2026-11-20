"""
Cálculos estatísticos e analíticos de produtividade do Willy.
Módulo puro (sem dependência de GUI/Tkinter) com alta testabilidade e manutenibilidade.
"""

import datetime
import re
from collections import Counter
from typing import Any

FORMATOS_TIMESTAMP = (
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)

STOPWORDS = {
    "de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "é", "com", "não", "uma", "os", "no", "se", "na",
    "por", "mais", "as", "dos", "como", "mas", "foi", "ao", "ele", "das", "tem", "à", "seu", "sua", "ou", "ser",
    "quando", "muito", "nos", "já", "eu", "também", "só", "pelo", "pela", "até", "isso", "ela", "entre", "era",
    "depois", "sem", "mesmo", "aos", "ter", "seus", "quem", "nas", "me", "esse", "eles", "está", "você", "tinha",
    "foram", "essa", "num", "nem", "suas", "meu", "às", "minha", "têm", "numa", "pelos", "elas", "havia", "seja",
    "qual", "será", "nós", "tenho", "lhe", "deles", "essas", "esses", "pelas", "este", "fosse", "dele", "tu",
    "te", "vocês", "vos", "lhes", "meus", "minhas", "teu", "tua", "teus", "tuas", "nosso", "nossa", "nossos",
    "nossas", "dela", "delas", "esta", "estes", "estas", "aquele", "aquela", "aqueles", "aquelas", "isto", "aquilo",
    "the", "to", "and", "of", "in", "is", "it", "you", "that", "for", "on", "with", "this", "be", "at"
}


# Sem nenhum ditado medido, a fala estimada para o tempo economizado.
FALA_ESTIMADA_WPM = 145
# Modos em que o texto salvo é o que a pessoa falou. No prompt e no transformar ele é o que o LLM
# escreveu, e na reunião há outras vozes: contariam como fala muito mais rápida.
MODOS_DE_DITADO = ("transcribe", "send", "translate", "translate_es")


def parse_history_timestamp(timestamp_str: str) -> datetime.datetime | None:
    """Converte um timestamp textual do histórico (BR ou ISO) em datetime, ou None se inválido."""
    if not isinstance(timestamp_str, str):
        return None
    texto = timestamp_str.strip()
    if not texto:
        return None
    for fmt in FORMATOS_TIMESTAMP:
        try:
            return datetime.datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def classificar_data_historico(
    timestamp_str: str,
    hoje: datetime.date | None = None,
) -> tuple[str, datetime.datetime | None]:
    """Classifica `timestamp_str` em ('Hoje' | 'Ontem' | 'Esta semana' | 'Anteriores', dt)."""
    dt = parse_history_timestamp(timestamp_str)
    if dt is None:
        return "Anteriores", None
    if hoje is None:
        hoje = datetime.datetime.now().date()
    d = dt.date()
    if d == hoje:
        return "Hoje", dt
    if d == hoje - datetime.timedelta(days=1):
        return "Ontem", dt
    if 0 <= (hoje - d).days < 7:
        return "Esta semana", dt
    return "Anteriores", dt


def _palavras_por_minuto(history: list[dict[str, Any]]) -> int:
    """Palavras por minuto de gravação, nos ditados que guardaram a duração.

    Era a constante 145, mostrada como se fosse medida. A duração inclui a pausa final do corte
    por silêncio, então a medida fica um pouco abaixo da fala de verdade.
    """
    palavras, segundos = 0, 0.0
    for item in history:
        duracao = item.get("duration_s")
        if item.get("mode", "transcribe") in MODOS_DE_DITADO and isinstance(duracao, (int, float)) and duracao > 0:
            palavras += item.get("words", len(item.get("text", "").split()))
            segundos += duracao
    if segundos <= 0:
        return 0
    return round(palavras / (segundos / 60.0))


def calculate_analytics_metrics(history: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Calcula estatísticas de produtividade e tempo economizado com base no histórico.
    Considera digitação manual média de 40 palavras/minuto contra a fala medida (ver
    _palavras_por_minuto); sem medida, 145 palavras/minuto entram só na estimativa de tempo.
    """
    total_prompts = len(history)
    total_words = 0
    words_today = 0
    modes_count = {"transcribe": 0, "translate": 0, "meeting": 0}
    hoje = datetime.datetime.now().date()
    hour_counts: dict[int, int] = {}
    word_counter: Counter = Counter()

    for item in history:
        txt = item.get("text", "")
        words = item.get("words", len(txt.split()))
        total_words += words
        ts = item.get("timestamp", "")
        dt = parse_history_timestamp(ts)
        if dt is not None:
            if dt.date() == hoje:
                words_today += words
            hour_counts[dt.hour] = hour_counts.get(dt.hour, 0) + 1
        elif isinstance(ts, str) and len(ts) >= 16 and " " in ts:
            try:
                hora_part = ts.split(" ")[1].split(":")[0]
                h = int(hora_part)
                if 0 <= h <= 23:
                    hour_counts[h] = hour_counts.get(h, 0) + 1
            except ValueError:
                pass
        m = item.get("mode", "transcribe")
        modes_count[m] = modes_count.get(m, 0) + 1

        # Contagem de palavras-chave mais faladas
        for w in re.findall(r'\b[a-zA-ZÀ-ÿ0-9_]{4,}\b', txt.lower()):
            if w not in STOPWORDS:
                word_counter[w] += 1

    # Velocidade medida nos ditados que guardaram a duração; 0 sem nenhum ("-- WPM" na tela).
    avg_wpm = _palavras_por_minuto(history)

    # Tempo líquido economizado: digitação manual (40 wpm) - tempo de fala (o medido; sem ele,
    # a estimativa de 145 wpm).
    minutos_digitando = total_words / 40.0
    minutos_falando = total_words / float(avg_wpm or FALA_ESTIMADA_WPM)
    minutos_economizados = max(0.0, minutos_digitando - minutos_falando)
    horas_economizadas = int(minutos_economizados // 60)
    mins_restantes = int(minutos_economizados % 60)

    # Pico de horário de maior produtividade
    peak_hour_str = "--"
    if hour_counts:
        peak_h = max(hour_counts, key=hour_counts.get)
        peak_hour_str = f"{peak_h:02d}:00 - {peak_h+1:02d}:00"

    # Top 5 palavras-chave mais recorrentes
    top_keywords = [w.capitalize() for w, _ in word_counter.most_common(5)]

    # Modo preferido. O ditado enviado com Enter fica no histórico como "send", mas é ditado:
    # contado à parte, quem dita e envia via "Tradução EN" com uma tradução a mais.
    # Dos outros, o mais usado, se passar dos ditados: valia o primeiro da lista que passasse, e
    # 50 traduções para o espanhol contra 10 para o inglês davam "Tradução EN".
    ditados = modes_count.get("transcribe", 0) + modes_count.get("send", 0)
    outros = (
        ("translate", "Tradução EN"),
        ("translate_es", "Tradução ES"),
        ("meeting", "Reunião"),
        ("prompt", "Prompt"),
        ("transform", "Transformar"),
    )
    modo, rotulo = max(outros, key=lambda m: modes_count.get(m[0], 0))
    modo_pref = rotulo if modes_count.get(modo, 0) > ditados else "Ditado PT"

    return {
        "total_prompts": total_prompts,
        "total_words": total_words,
        "words_today": words_today,
        "saved_hours": horas_economizadas,
        "saved_minutes": mins_restantes,
        "avg_wpm": avg_wpm,
        "peak_hour": peak_hour_str,
        "top_keywords": top_keywords,
        "favorite_mode": modo_pref,
        "modes_count": modes_count
    }
