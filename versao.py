"""
Versão do Willy: a ÚNICA fonte.

Tela "Sobre", perfil exportado e instalador (Inno Setup) leem daqui;
tests/test_versao.py reprova qualquer número de versão escrito à mão em outro lugar.
Fica na raiz e sem imports para que core/ e ui/ possam ler sem import circular.
"""

__version__ = "1.14.2"
