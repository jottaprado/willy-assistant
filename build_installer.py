"""
Script de Compilação & Empacotamento do Willy para Windows.
Gera uma versão standalone completa do Willy que funciona em qualquer
computador com Windows sem precisar de Python instalado.
Usa Willy.spec como fonte única de dados e hiddenimports do PyInstaller.
"""

import os
import shutil
import subprocess
import sys
import sysconfig

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# --sem-instalar: só gera dist/Willy, sem copiar por cima de %LOCALAPPDATA%\Programs\Willy.
SEM_INSTALAR = "--sem-instalar" in sys.argv[1:]
# --instalador: também gera dist_installer/Willy-Setup-v<versão>.exe com o Inno Setup.
GERAR_INSTALADOR = "--instalador" in sys.argv[1:]


def _ler_versao() -> str:
    """Lê __version__ de versao.py sem importar o projeto (fonte única da versão)."""
    import ast
    with open(os.path.join(BASE_DIR, "versao.py"), encoding="utf-8") as f:
        arvore = ast.parse(f.read())
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(getattr(t, "id", "") == "__version__" for t in no.targets):
            return ast.literal_eval(no.value)
    raise SystemExit("❌ versao.py não define __version__")


def _limpar_instalacao(pasta: str) -> None:
    """Tira a versão anterior de `pasta` antes da cópia da nova.

    Copiar por cima deixava o que a versão nova não tem mais (módulos e DLLs velhos no
    _internal). Ficam os unins* do Inno Setup: sem eles, a desinstalação pelo Windows quebra.
    Só age numa pasta com Willy.exe: com o LOCALAPPDATA vazio, o caminho viraria relativo.
    """
    if not os.path.isabs(pasta) or not os.path.isfile(os.path.join(pasta, "Willy.exe")):
        raise SystemExit(f"❌ {pasta!r} não parece uma instalação do Willy: nada foi apagado.")
    # O Willy.exe por último: se apagar o resto falhar no meio, ele fica, e a próxima execução
    # ainda reconhece a pasta e termina a limpeza.
    for nome in sorted(os.listdir(pasta), key=lambda n: n.lower() == "willy.exe"):
        if nome.lower().startswith("unins"):
            continue
        caminho = os.path.join(pasta, nome)
        if os.path.isdir(caminho) and not os.path.islink(caminho):
            shutil.rmtree(caminho)
        else:
            os.remove(caminho)


def _copiar_artefatos_dist(base_dir: str, dist_dir: str) -> None:
    """Copia vocabulario.txt e assets/ para a raiz de dist/Willy; aborta se a cópia falhar."""
    try:
        vocab_src = os.path.join(base_dir, "vocabulario.txt")
        if os.path.exists(vocab_src):
            shutil.copyfile(vocab_src, os.path.join(dist_dir, "vocabulario.txt"))
        assets_src = os.path.join(base_dir, "assets")
        if os.path.exists(assets_src):
            shutil.copytree(assets_src, os.path.join(dist_dir, "assets"), dirs_exist_ok=True)
    except OSError as e:
        print(f"\n❌ Falha ao copiar artefatos para {dist_dir}: {e}", file=sys.stderr)
        raise SystemExit(1) from e


def _remover_pycache(dist_dir: str) -> None:
    """Tira de dist/Willy os __pycache__ que vieram junto com as pastas de datas.

    O Willy.spec copia pastas inteiras (core/, ui/ e, da .venv, customtkinter/ e as de dados do
    sounddevice e do soundfile), e com elas o bytecode compilado na máquina de build: cada .pyc
    guarda o caminho absoluto do .py de origem, e o último instalador publicado levava 109
    deles. São cache, com o .py ao lado, e não fazem falta. O .pyc fora de um __pycache__ pode
    ser o próprio módulo e fica.
    """
    for pasta, subpastas, _ in os.walk(dist_dir):
        if "__pycache__" in subpastas:
            shutil.rmtree(os.path.join(pasta, "__pycache__"))
            subpastas.remove("__pycache__")


def _conferir_sem_caminho_da_maquina(dist_dir: str, casa: str) -> None:
    """Aborta o build se algum arquivo de dist/Willy leva o caminho da pasta de quem o gerou.

    Procura a pasta do usuário (C:\\Users\\<nome>) seguida de uma barra, com barra, contrabarra
    ou a contrabarra escapada de JSON e TOML, em qualquer caixa, em ASCII e em UTF-16. O
    instalador é público: foi assim que
    109 .pyc com esse caminho chegaram às releases sem ninguém ver. O caminho da máquina de quem
    compilou uma wheel de terceiros (C:/Users/runneradmin) não é desta máquina e passa.
    """
    base = casa.rstrip("\\/").lower()
    alvos = [(base.replace("\\", barra).replace("/", barra) + barra).encode(codificacao)
             for barra in ("\\", "/", "\\\\") for codificacao in ("utf-8", "utf-16-le")]
    achados = []
    for pasta, _, arquivos in os.walk(dist_dir):
        for nome in arquivos:
            caminho = os.path.join(pasta, nome)
            with open(caminho, "rb") as f:
                conteudo = f.read().lower()
            if any(alvo in conteudo for alvo in alvos):
                achados.append(os.path.relpath(caminho, dist_dir))
    if achados:
        lista = "\n   ".join(sorted(achados))
        raise SystemExit(f"❌ {len(achados)} arquivo(s) de {dist_dir} levam o caminho {casa}, "
                         f"e nada foi empacotado nem instalado:\n   {lista}")


def _achar_iscc():
    """Caminho do compilador do Inno Setup, ou None."""
    candidatos = [shutil.which("iscc")]
    for base in (os.getenv("ProgramFiles(x86)"), os.getenv("ProgramFiles"),
                 os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidatos.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    return next((c for c in candidatos if c and os.path.exists(c)), None)


VERSAO = _ler_versao()
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, ValueError) as e:
        print(f"[build_installer] aviso ao reconfigurar stdout para UTF-8: {e!r}", file=sys.stderr)

SITE_PACKAGES = sysconfig.get_paths()["purelib"]

print(f"Diretório base: {BASE_DIR}")
print(f"Versão (versao.py): {VERSAO}")
print(f"Site-packages: {SITE_PACKAGES}")

# Limpa pasta de build anterior para garantir compilação 100% limpa
build_dir = os.path.join(BASE_DIR, "build")
if os.path.exists(build_dir):
    try:
        shutil.rmtree(build_dir)
    except OSError as e:
        print(f"[build_installer] aviso ao limpar pasta de build anterior ({build_dir}): {e!r}", file=sys.stderr)

spec_file = os.path.join(BASE_DIR, "Willy.spec")
pyinstaller_cmd = [
    sys.executable,
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    spec_file,
]

print("\nExecutando PyInstaller com Willy.spec...")
print(" ".join(pyinstaller_cmd))

res = subprocess.run(pyinstaller_cmd, cwd=BASE_DIR, check=False)
if res.returncode == 0:
    dist_dir = os.path.join(BASE_DIR, "dist", "Willy")
    # vocabulario.txt e assets/ também na raiz de dist/Willy: o instalador usa {app}\assets\willy_icon.ico
    _copiar_artefatos_dist(BASE_DIR, dist_dir)
    # O instalador é público: nada em dist/Willy pode levar o caminho de quem gerou o build.
    _remover_pycache(dist_dir)
    _conferir_sem_caminho_da_maquina(dist_dir, os.path.expanduser("~"))

    print("\n✅ Compilação concluída com sucesso!")
    print(f"Executável gerado em: {dist_dir}")

    if GERAR_INSTALADOR:
        iscc = _achar_iscc()
        if not iscc:
            print("\n❌ Inno Setup (ISCC.exe) não encontrado: o instalador NÃO foi gerado.")
            print("   Instale com: winget install JRSoftware.InnoSetup")
            sys.exit(4)
        print(f"\n🧰 Gerando o instalador v{VERSAO} com {iscc}...")
        iss = subprocess.run([iscc, f"/DMyAppVersion={VERSAO}", "willy_installer.iss"], cwd=BASE_DIR, check=False)
        if iss.returncode != 0:
            print(f"\n❌ O Inno Setup falhou (código {iss.returncode}): o instalador NÃO foi gerado.")
            sys.exit(5)
        print(f"✅ Instalador gerado: {os.path.join(BASE_DIR, 'dist_installer', f'Willy-Setup-v{VERSAO}.exe')}")

    # Atualiza %LOCALAPPDATA%\Programs\Willy se existir
    local_app_dir = os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Willy")
    if SEM_INSTALAR:
        print("\nℹ️ --sem-instalar: a instalação em %LOCALAPPDATA%\\Programs\\Willy não foi tocada.")
    elif os.path.exists(local_app_dir):
        # Com o Willy aberto, o Willy.exe fica travado e a cópia falha NO MEIO: a pasta
        # _internal fica nova e o .exe (que carrega o código Python) fica velho. Foi assim
        # que a instalação ficou em 25/09 depois do build de 29/09, sem ninguém perceber.
        tasklist = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Willy.exe", "/NH"],
            capture_output=True, text=True, check=False,
        )
        if "Willy.exe" in tasklist.stdout:
            print("\n❌ O Willy está aberto: a instalação NÃO foi atualizada.")
            print("   Feche pelo ícone da bandeja (\"Fechar Willy por completo\") e rode de novo,")
            print("   ou use --sem-instalar para só gerar dist/Willy.")
            sys.exit(2)
        print(f"\n📦 Atualizando instalação local em: {local_app_dir}...")
        try:
            _limpar_instalacao(local_app_dir)
            shutil.copytree(dist_dir, local_app_dir, dirs_exist_ok=True)
        except OSError as e:
            print(f"\n❌ Falha ao atualizar a instalação local: {e}")
            print("   A instalação pode ter ficado parcial. Feche o Willy e rode de novo.")
            sys.exit(3)
        print("✅ Instalação em %LOCALAPPDATA%\\Programs\\Willy atualizada com sucesso!")
else:
    print(f"\n❌ Erro durante a compilação: código {res.returncode}")
    sys.exit(res.returncode)
