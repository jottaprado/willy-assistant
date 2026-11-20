"""
Cópia pedida pela pessoa num botão "Copiar" da interface (Histórico, bandeja, pílula).
"""

from core.actions import ActionManager


def copiar_pelo_clique(texto: str, modo_privado: bool) -> bool:
    """Copia `texto` como um Ctrl+C: aparece no histórico do Win+V, a não ser no modo privado.

    Decisão do dono: o "Copiar" que a pessoa clica vai para o Win+V; a colagem automática e
    tudo no modo privado ficam fora dele (secure_copy com ocultar_do_historico=True). A área
    de transferência na nuvem fica de fora nos dois casos (o secure_copy marca o texto para não
    subir). Devolve se gravou, como o secure_copy.
    """
    return ActionManager.secure_copy(texto, ocultar_do_historico=bool(modo_privado))
