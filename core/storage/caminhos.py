"""
Validação de caminhos que chegam de fora (perfil importado, .env, histórico).

Fica num módulo próprio, sem importar core.config, para que config, ProfileManager e a
aba de histórico usem a MESMA regra sem import circular.
"""

import ntpath
import os
import re
import sys
from typing import Any


def eh_caminho_de_rede(caminho: Any) -> bool:
    """True para \\\\servidor\\share, //servidor/share e as misturas de barra.

    Só de o Willy tocar num caminho desses (os.path.exists, makedirs, startfile), o Windows
    abre conexão SMB e entrega o hash NTLM do usuário ao servidor. Por isso a checagem é
    de texto e vem ANTES de qualquer chamada ao sistema de arquivos.
    """
    if not isinstance(caminho, str):
        return False
    return caminho.strip().replace("/", "\\").startswith("\\\\")


def caminho_local_absoluto(caminho: Any) -> bool:
    """Caminho absoluto numa unidade local (C:\\...), sem rede, sem '..' e sem NUL."""
    if not isinstance(caminho, str):
        return False
    c = caminho.strip()
    if not c or "\x00" in c or eh_caminho_de_rede(c):
        return False
    if ".." in re.split(r"[\\/]+", c):
        return False
    if sys.platform == "win32":
        unidade, resto = ntpath.splitdrive(c)
        # "C:pasta" é relativo ao diretório corrente da unidade, e ":" depois da unidade é
        # fluxo alternativo do NTFS (arquivo.exe:x.md).
        return (bool(re.fullmatch(r"[A-Za-z]:", unidade))
                and resto[:1] in ("\\", "/")
                and ":" not in resto)
    return os.path.isabs(c)


def caminho_dentro_de(caminho: Any, pasta: Any, extensao: str) -> bool:
    """True se `caminho` é um arquivo `extensao` estritamente dentro de `pasta`."""
    if not (caminho_local_absoluto(caminho) and caminho_local_absoluto(pasta)):
        return False
    if not caminho.strip().lower().endswith(extensao):
        return False
    alvo = os.path.normcase(os.path.abspath(caminho.strip()))
    raiz = os.path.normcase(os.path.abspath(pasta.strip()))
    try:
        return alvo != raiz and os.path.commonpath([alvo, raiz]) == raiz
    except ValueError:
        # Unidades diferentes (C: e D:).
        return False
