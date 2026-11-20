# Regras deste repositório (Willy)

- O Willy em %LOCALAPPDATA%\Programs\Willy é a ferramenta de trabalho do dono. Para atualizar, suba `versao.py`, rode `.venv\Scripts\python.exe build_installer.py --sem-instalar --instalador` e entregue o caminho do `dist_installer\Willy-Setup-v<versão>.exe`. Quem roda o instalador é o dono.
- Pelo terminal do agente, nunca: rodar o instalador ou o `Willy.exe`, `Stop-Process`/`taskkill` no Willy, `robocopy`/`Copy-Item` em `Programs\Willy`, `schtasks`. O terminal do Antigravity roda num desktop isolado (`exebox-*`) e num job. O Willy aberto dali morre com o comando ou fica invisível, sem bandeja e sem atalhos. O `schtasks /IT` o deixa em prioridade BelowNormal.
- Instalador com o número de uma release já publicada é proibido. Dois binários diferentes com o mesmo número confundem o que está instalado.
- "Willy sumiu da barra" ou "atalho morto": liste as janelas do processo em cada desktop (EnumDesktopsW + EnumDesktopWindows) antes de suspeitar do código.
