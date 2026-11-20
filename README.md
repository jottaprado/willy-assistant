# Willy

Assistente de voz para Windows: você aperta um atalho, fala, e o texto transcrito pelo Whisper da Groq e revisado por um LLM é colado no cursor de qualquer programa. Também traduz para inglês e para espanhol, transforma texto selecionado, gera prompts de agente e grava reuniões com ata executiva.

A descrição completa de cada recurso, da arquitetura e das pendências está em [docs/VISAO_GERAL_E_FUNCIONALIDADES.md](docs/VISAO_GERAL_E_FUNCIONALIDADES.md).

## Atalhos principais

| Ação | Padrão |
| --- | --- |
| Ditado | Ctrl+Espaço |
| Tradução para inglês | Ctrl+Alt+Espaço |
| Tradução para espanhol | Ctrl+Alt+N |
| Reunião com ata | Ctrl+Alt+R |
| Arquiteto de prompts | Ctrl+Alt+P |
| Ditar e enviar | Ctrl+Shift+Enter |
| Acordar / dormir | Ctrl+Shift+Espaço |

Os outros 7 atalhos e todos os comandos de voz estão no documento acima.

## Requisitos

- Windows 10 ou 11
- Python 3.12
- Uma chave da Groq: https://console.groq.com/keys

## Rodar pelo código-fonte

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe willy.py
```

Na primeira execução, o `.env` é criado a partir do `.env.template` e o Willy abre no Guia Inicial para validar a chave da Groq na nuvem e testar microfone, atalhos e primeiro ditado (também editável no topo da aba Ajustes). Rodando pelo código-fonte, configurações e histórico ficam na pasta do repositório, separados do Willy instalado (que usa `%APPDATA%\Willy`). `iniciar_com_terminal.bat` abre com um terminal para depuração.

## Gerar o executável e atualizar o Willy instalado

1. Feche o Willy pelo ícone da bandeja ("Fechar Willy por completo"); o X da janela só esconde.
2. Rode:

   ```powershell
   .venv\Scripts\python.exe -m pip install pyinstaller
   .venv\Scripts\python.exe build_installer.py
   ```

O script gera `dist\Willy\Willy.exe` e, se houver uma instalação em `%LOCALAPPDATA%\Programs\Willy`, copia o build por cima. Ele para com erro se o Willy estiver aberto. Use `--sem-instalar` para só gerar `dist\Willy`.

## Gerar o instalador

Com o [Inno Setup 6](https://jrsoftware.org/isinfo.php) instalado (`winget install JRSoftware.InnoSetup --scope user`):

```powershell
.venv\Scripts\python.exe build_installer.py --instalador
```

Gera `dist_installer\Willy-Setup-v<versão>.exe`, que instala o Willy em qualquer Windows 10/11 sem Python e sem pedir administrador. O instalador de cada versão fica anexado à Release correspondente no GitHub, não no git.

A versão vem só de `versao.py`; para lançar uma nova, mude o número lá.

## Testes

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
```

O CI (`.github/workflows/testes.yml`) roda a mesma suíte em Windows a cada push na `main` e em cada PR.

## Licença

MIT, no arquivo `LICENSE`. Os ícones de `assets/icons/` vêm dos Fluent UI System Icons, da Microsoft, também sob MIT, com o aviso deles em `assets/icons/LICENSE`.
