"""
Instalador (willy_installer.iss), Willy.spec e a atualização local do build_installer.py.

- Atualizar com o Willy aberto na bandeja falhava no Willy.exe travado ou deixava a pasta
  pela metade, e nada no instalador o fechava.
- O início com o Windows era um atalho na pasta Inicializar, enquanto o Ajustes liga e
  desliga o valor "Willy" no Run: o interruptor não via o que o instalador ligou, e com os
  dois o Willy abria duas vezes.
- O Willy.spec tinha os caminhos absolutos da máquina de build escritos à mão.
- O build copiava a versão nova por cima da velha, deixando módulos e DLLs que saíram.

O comportamento do instalador de verdade (fechar o app, apagar, registrar) é provado pelo
test_instalador_ponta_a_ponta, que instala um Willy de mentira e só roda quando pedido.
"""

import ast
import os
import re
import shutil
import tempfile
import unittest
import unittest.mock
import zipfile
import zlib

from core.autostart import APP_NAME, REG_KEY_PATH
from core.single_instance import SingleInstanceManager

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ler(nome):
    with open(os.path.join(RAIZ, nome), encoding="utf-8") as f:
        return f.read()


ISS = _ler("willy_installer.iss")


def _define(nome):
    m = re.search(rf'#define {nome} "(.*)"', ISS)
    return m.group(1) if m else None


def _secao(nome):
    m = re.search(rf"^\[{nome}\]\s*$(.*?)(?=^\[\w+\]\s*$|\Z)", ISS, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    return [l.strip() for l in m.group(1).splitlines() if l.strip() and not l.strip().startswith(";")]


def _diretiva(nome):
    for linha in _secao("Setup"):
        chave, _, valor = linha.partition("=")
        if chave.strip() == nome:
            return valor.strip()
    return None


class TestFechaOWilly(unittest.TestCase):
    def test_app_mutex_e_o_mesmo_do_willy(self):
        self.assertEqual("{#MyAppMutex}", _diretiva("AppMutex"))
        self.assertEqual(SingleInstanceManager().mutex_name, _define("MyAppMutex"),
                         "o instalador procura um mutex que o Willy não cria")

    def test_fecha_os_aplicativos_que_usam_a_pasta(self):
        self.assertEqual("force", _diretiva("CloseApplications"))

    def test_fecha_o_willy_antes_de_instalar_e_de_desinstalar(self):
        codigo = ISS.split("[Code]", 1)[1]
        for evento in ("InitializeSetup", "InitializeUninstall"):
            # Pode ter um bloco var antes do begin.
            corpo = re.search(rf"function {evento}\(\): Boolean;.*?begin(.*?)end;", codigo, re.DOTALL)
            self.assertIsNotNone(corpo, f"{evento} sumiu do [Code]")
            self.assertIn("PodeFecharWilly(", corpo.group(1))
        # AUD-091: tenta primeiro taskkill gracioso (sem /F) e só depois usa o fallback /F.
        pos_gracioso = codigo.find("'/IM {#MyAppExeName}'")
        pos_forcado = codigo.find("'/F /IM {#MyAppExeName}'")
        self.assertNotEqual(-1, pos_gracioso, "EncerrarWilly deve tentar taskkill gracioso antes de /F")
        self.assertNotEqual(-1, pos_forcado, "EncerrarWilly deve manter fallback /F")
        self.assertLess(pos_gracioso, pos_forcado)

    def test_o_willy_fechado_volta_a_abrir(self):
        # Silenciosa, o [Run] postinstall (skipifsilent) não roda; e quem desiste no assistente
        # depois do Willy fechado ficava sem ele.
        reabre = [l for l in _secao("Run") if "Check: ReabrirNoSilencioso" in l]
        self.assertEqual(1, len(reabre), _secao("Run"))
        self.assertNotIn("skipifsilent", reabre[0])
        codigo = ISS.split("[Code]", 1)[1]
        self.assertRegex(codigo, r"Result := WizardSilent\(\) and WillyFechado;")
        for evento in ("DeinitializeSetup", "DeinitializeUninstall"):
            corpo = re.search(rf"procedure {evento}\(\);\s*begin(.*?)end;", codigo, re.DOTALL)
            self.assertIsNotNone(corpo, f"{evento} sumiu do [Code]")
            self.assertIn("WillyFechado and not Concluido", corpo.group(1))
            self.assertIn("ReabrirWilly()", corpo.group(1))


class TestInicioComOWindows(unittest.TestCase):
    def _run(self):
        return [l for l in _secao("Registry") if "CurrentVersion\\Run" in l]

    def test_nao_usa_mais_o_atalho_da_pasta_inicializar(self):
        self.assertEqual([], [l for l in _secao("Icons") if "{userstartup}" in l])

    def test_grava_no_run_que_o_ajustes_le(self):
        grava = [l for l in self._run() if "ValueType: string" in l]
        self.assertEqual(1, len(grava), self._run())
        linha = grava[0]
        # Quem decide é a função, não a tarefa: numa atualização vale o estado de antes.
        self.assertIn("Check: LigarInicioComOWindows", linha)
        self.assertNotIn("Tasks:", linha)
        self.assertIn(f'Subkey: "{REG_KEY_PATH}"', linha)
        self.assertIn('ValueName: "{#MyAppName}"', linha)
        self.assertEqual(APP_NAME, _define("MyAppName"))
        # Entre aspas, como o AutoStartManager grava: o caminho tem espaço.
        self.assertIn('ValueData: """{app}\\{#MyAppExeName}"""', linha)
        self.assertIn("uninsdeletevalue", linha)

    def test_desinstalar_tira_o_run_mesmo_sem_a_tarefa(self):
        sem_tarefa = [l for l in self._run() if "ValueType" not in l]
        self.assertEqual(1, len(sem_tarefa), self._run())
        self.assertIn("uninsdeletevalue", sem_tarefa[0])
        self.assertIn("dontcreatekey", sem_tarefa[0])
        self.assertNotIn("ValueType", sem_tarefa[0], "sem ValueType o Inno não cria valor nenhum")

    def test_tarefa_do_inicio_so_na_primeira_instalacao(self):
        tarefa = [l for l in _secao("Tasks") if l.startswith('Name: "startupicon"')]
        self.assertEqual(1, len(tarefa))
        self.assertIn("Check: PrimeiraInstalacao", tarefa[0])
        self.assertNotIn("Flags: unchecked", tarefa[0], "na primeira instalação vem marcada")

    def test_atualizacao_segue_o_estado_de_antes(self):
        codigo = ISS.split("[Code]", 1)[1]
        decide = re.search(r"function LigarInicioComOWindows\(\): Boolean;\s*begin(.*?)end;", codigo, re.DOTALL)
        self.assertIsNotNone(decide)
        self.assertRegex(decide.group(1), r"if EhAtualizacao then\s*Result := InicioLigadoAntes\s*else\s*"
                                          r"Result := WizardIsTaskSelected\('startupicon'\)")
        # O estado de antes: o Run do Ajustes ou o Willy.lnk legado, lidos antes de a instalação
        # apagar o atalho.
        inicio = re.search(r"function InitializeSetup\(\): Boolean;.*?begin(.*?)end;", codigo, re.DOTALL).group(1)
        self.assertRegex(inicio, r"InicioLigadoAntes := \(RegQueryStringValue\(HKCU, CHAVE_RUN, '\{#MyAppName\}', ValorRun\) "
                                 r"and \(Trim\(ValorRun\) <> ''\)\) or\s*"
                                 r"FileExists\(ExpandConstant\('\{userstartup\}\\{#MyAppName\}\.lnk'\)\)")
        # Atualização é a chave de desinstalação E o Willy.exe na pasta que ela registra.
        self.assertIn("RegQueryStringValue(HKCU, ChaveDesinstalacao, 'InstallLocation', PastaAnterior)", inicio)
        self.assertIn("EhAtualizacao := FileExists(AddBackslash(PastaAnterior) + '{#MyAppExeName}');", inicio)

    def test_apaga_o_atalho_legado(self):
        self.assertIn('Type: files; Name: "{userstartup}\\{#MyAppName}.lnk"', _secao("InstallDelete"))


class TestAtualizacaoLimpa(unittest.TestCase):
    def test_instalador_tira_o_runtime_anterior(self):
        self.assertIn('Type: filesandordirs; Name: "{app}\\_internal"', _secao("InstallDelete"))


class TestSpecPortatil(unittest.TestCase):
    def test_sem_caminho_absoluto_de_uma_maquina(self):
        spec = _ler("Willy.spec")
        self.assertEqual([], re.findall(r"[A-Za-z]:[/\\]", spec))
        self.assertIn("RAIZ = SPECPATH", spec)
        self.assertIn('sysconfig.get_paths()["purelib"]', spec)


def _limpar_instalacao():
    """A função do build_installer.py, que não é importável (o build roda no import)."""
    arvore = ast.parse(_ler("build_installer.py"))
    funcao = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "_limpar_instalacao")
    escopo = {"os": os, "shutil": shutil}
    exec(compile(ast.Module(body=[funcao], type_ignores=[]), "build_installer.py", "exec"), escopo)
    return escopo["_limpar_instalacao"]


def _copiar_artefatos_dist():
    """Extrai _copiar_artefatos_dist de build_installer.py via AST."""
    import sys as _sys
    arvore = ast.parse(_ler("build_installer.py"))
    funcao = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "_copiar_artefatos_dist")
    escopo = {"os": os, "shutil": shutil, "sys": _sys}
    exec(compile(ast.Module(body=[funcao], type_ignores=[]), "build_installer.py", "exec"), escopo)
    return escopo["_copiar_artefatos_dist"]


class TestBuildLimpaAInstalacaoLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = os.path.join(self.tmp.name, "Willy")
        for rel in ("Willy.exe", "unins000.exe", "unins000.dat", "vocabulario.txt",
                    os.path.join("_internal", "modulo_velho.pyd"), os.path.join("assets", "x.ico")):
            os.makedirs(os.path.dirname(os.path.join(self.pasta, rel)), exist_ok=True)
            with open(os.path.join(self.pasta, rel), "w", encoding="utf-8"):
                pass

    def test_tira_a_versao_anterior_e_mantem_o_desinstalador(self):
        _limpar_instalacao()(self.pasta)
        self.assertEqual(["unins000.dat", "unins000.exe"], sorted(os.listdir(self.pasta)))

    def test_falha_no_meio_deixa_a_pasta_reconhecivel(self):
        # O Willy.exe saía primeiro: com o _internal travado, a próxima execução recusava a
        # pasta ("não parece uma instalação") e ela ficava quebrada até limpar à mão.
        real = shutil.rmtree

        def _travado(caminho, *a, **k):
            if os.path.basename(caminho) == "_internal":
                raise PermissionError("em uso")
            return real(caminho, *a, **k)

        limpar = _limpar_instalacao()
        with unittest.mock.patch.object(shutil, "rmtree", side_effect=_travado), self.assertRaises(PermissionError):
            limpar(self.pasta)
        self.assertTrue(os.path.exists(os.path.join(self.pasta, "Willy.exe")))
        limpar(self.pasta)  # de novo, sem a trava: termina
        self.assertEqual(["unins000.dat", "unins000.exe"], sorted(os.listdir(self.pasta)))

    def test_nao_apaga_pasta_que_nao_e_do_willy(self):
        os.remove(os.path.join(self.pasta, "Willy.exe"))
        with self.assertRaises(SystemExit):
            _limpar_instalacao()(self.pasta)
        self.assertIn("vocabulario.txt", os.listdir(self.pasta))

    def test_nao_apaga_caminho_relativo(self):
        # Relativo à pasta corrente, como "Programs\Willy" com o LOCALAPPDATA vazio. Pelo
        # chdir, e não pelo relpath: no CI o temporário fica em C: e o checkout em D:.
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        with self.assertRaises(SystemExit):
            _limpar_instalacao()("Willy")
        self.assertIn("Willy.exe", os.listdir(self.pasta))

    def test_limpa_antes_de_copiar(self):
        fonte = _ler("build_installer.py")
        limpa = fonte.find("_limpar_instalacao(local_app_dir)")
        copia = fonte.find("shutil.copytree(dist_dir, local_app_dir")
        self.assertNotEqual(-1, limpa, "a atualização local não limpa mais a pasta")
        self.assertLess(limpa, copia)

    def test_falha_ao_copiar_vocabulario_ou_assets_aborta_o_build(self):
        """AUD-086, AUD-198: falha ao copiar vocabulario.txt ou assets/ para dist/Willy aborta com SystemExit."""
        copiar = _copiar_artefatos_dist()
        base = os.path.join(self.tmp.name, "base")
        dist = os.path.join(self.tmp.name, "dist_willy")
        os.makedirs(os.path.join(base, "assets"), exist_ok=True)
        os.makedirs(dist, exist_ok=True)
        with open(os.path.join(base, "vocabulario.txt"), "w", encoding="utf-8") as f:
            f.write("Willy\n")
        with open(os.path.join(base, "assets", "willy_icon.ico"), "wb") as f:
            f.write(b"\x00")

        with (
            unittest.mock.patch.object(shutil, "copyfile", side_effect=PermissionError("vocab bloqueado")),
            self.assertRaises(SystemExit),
        ):
            copiar(base, dist)

        with (
            unittest.mock.patch.object(shutil, "copytree", side_effect=PermissionError("assets bloqueado")),
            self.assertRaises(SystemExit),
        ):
            copiar(base, dist)

    def test_generate_all_icons_nao_cria_pasta_no_import(self):
        """AUD-090: scripts/generate_all_icons.py não executa os.makedirs no top-level do módulo."""
        arvore = ast.parse(_ler(os.path.join("scripts", "generate_all_icons.py")))
        chamadas_topo = [
            ast.unparse(n) for n in arvore.body
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        ]
        self.assertEqual([], chamadas_topo)

    def test_ci_executa_ruff_e_ruff_toml_nao_ignora_globalmente_ble001_s110_s112(self):
        """AUD-083, AUD-087, AUD-089: CI roda ruff, ruff.toml não ignora BLE001/S110/S112 globalmente e doc alinhada."""
        import tomllib

        workflow = _ler(os.path.join(".github", "workflows", "testes.yml"))
        self.assertIn("ruff check .", workflow)

        cfg = tomllib.loads(_ler("ruff.toml"))
        ign_global = set(cfg.get("lint", {}).get("ignore", []))
        self.assertTrue(ign_global.isdisjoint({"BLE001", "S110", "S112"}))
        per_file = cfg.get("lint", {}).get("per-file-ignores", {})
        self.assertEqual({"tests/*.py": ["S102"]}, per_file)

        doc = _ler(os.path.join("docs", "VISAO_GERAL_E_FUNCIONALIDADES.md"))
        self.assertIn("(38 chaves)", doc)
        self.assertIn("até 20 resultados", doc)
        self.assertNotIn("Não gera o instalador", doc)
        self.assertIn("ruff check .", doc)


def _funcao_do_build(nome):
    """Uma função do build_installer.py, extraída via AST (o build roda no import)."""
    import sys as _sys
    arvore = ast.parse(_ler("build_installer.py"))
    funcao = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    escopo = {"os": os, "shutil": shutil, "sys": _sys, "zipfile": zipfile, "zlib": zlib}
    exec(compile(ast.Module(body=[funcao], type_ignores=[]), "build_installer.py", "exec"), escopo)
    return escopo[nome]


class TestDistSemOCaminhoDaMaquina(unittest.TestCase):
    """O último instalador publicado levava 109 .pyc com o caminho da pasta de quem gerou o build.

    O Willy.spec copia pastas inteiras como datas (core/, ui/ e, da .venv, customtkinter/,
    _sounddevice_data/ e _soundfile_data/), e com elas os __pycache__ compilados na máquina de
    build. Cada .pyc guarda o caminho absoluto do .py de origem.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = os.path.join(self.tmp.name, "Willy")

    def _gravar(self, rel, conteudo=b""):
        caminho = os.path.join(self.dist, rel)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "wb") as f:
            f.write(conteudo)

    def _restantes(self):
        return sorted(os.path.relpath(os.path.join(p, n), self.dist).replace(os.sep, "/")
                      for p, _, nomes in os.walk(self.dist) for n in nomes)

    def test_tira_os_pycache_e_mantem_o_resto(self):
        for rel in (os.path.join("_internal", "core", "__pycache__", "audio.cpython-313.pyc"),
                    os.path.join("_internal", "customtkinter", "windows", "__pycache__", "ctk_tk.cpython-313.pyc"),
                    os.path.join("_internal", "_soundfile_data", "__pycache__", "__init__.cpython-313.pyc"),
                    os.path.join("_internal", "core", "audio.py"),
                    os.path.join("_internal", "base_library.zip"),
                    os.path.join("_internal", "customtkinter", "assets", "themes", "blue.json"),
                    "Willy.exe"):
            self._gravar(rel)
        _funcao_do_build("_remover_pycache")(self.dist)
        self.assertEqual(["Willy.exe", "_internal/base_library.zip", "_internal/core/audio.py",
                          "_internal/customtkinter/assets/themes/blue.json"], self._restantes())
        self.assertEqual([], [p for p, _, _ in os.walk(self.dist) if os.path.basename(p) == "__pycache__"])

    def test_pyc_fora_do_pycache_fica(self):
        # Fora do __pycache__, o .pyc pode ser o próprio módulo (sem o .py ao lado): apagá-lo
        # quebraria o import. Se ele levar o caminho da máquina, a conferência é que acusa.
        self._gravar(os.path.join("_internal", "pacote", "modulo.pyc"))
        _funcao_do_build("_remover_pycache")(self.dist)
        self.assertEqual(["_internal/pacote/modulo.pyc"], self._restantes())

    def test_conferencia_acusa_o_caminho_da_maquina(self):
        self._gravar("limpo.json", b'{"ok": true}')
        # Como o marshal grava o co_filename, e com outra caixa: no Windows é o mesmo caminho.
        self._gravar(os.path.join("_internal", "a.pyc"), b"\xe3\x00C:\\Users\\Fulano\\willy\\core\\a.py\x00")
        self._gravar(os.path.join("_internal", "b.dat"), "c:/users/fulano/x".encode("utf-16-le"))
        # A contrabarra escapada de JSON, TOML e repr (o DELVEWHEEL do numpy grava assim).
        self._gravar(os.path.join("_internal", "c.json"), b'{"url": "C:\\\\Users\\\\fulano\\\\willy"}')
        with self.assertRaises(SystemExit) as erro:
            _funcao_do_build("_conferir_sem_caminho_da_maquina")(self.dist, "C:\\Users\\fulano")
        mensagem = str(erro.exception)
        self.assertIn("a.pyc", mensagem)
        self.assertIn("b.dat", mensagem)
        self.assertIn("c.json", mensagem)
        self.assertNotIn("limpo.json", mensagem)

    def test_conferencia_passa_com_caminho_de_outra_maquina(self):
        # As wheels do PyPI trazem o caminho de quem as compilou (C:/Users/runneradmin no
        # pydantic_core): não é desta máquina. Nem o nome que só começa igual.
        self._gravar(os.path.join("_internal", "x.pyd"), b"C:/Users/runneradmin/.cargo/registry")
        self._gravar(os.path.join("_internal", "y.txt"), b"C:\\Users\\fulanobeltrano\\z")
        _funcao_do_build("_conferir_sem_caminho_da_maquina")(self.dist, "C:\\Users\\fulano")

    def _exe_falso(self, *blocos):
        """Monta um Willy.exe falso com cabeçalho MZ, lixo com falso 0x78 0x9c e blocos zlib."""
        partes = [b"MZ\x90\x00lixo\x78\x9c\xff\xff\x00\x01"]
        for bloco in blocos:
            partes.append(zlib.compress(bloco))
            partes.append(b"\x00\x00pad\x78\xda\x00\x00")
        return b"".join(partes)

    def _zip_falso(self, rel, membros):
        caminho = os.path.join(self.dist, rel)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with zipfile.ZipFile(caminho, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for nome, dados in membros.items():
                zf.writestr(nome, dados)

    def test_conferencia_acusa_caminho_em_bloco_zlib_do_exe(self):
        exe = self._exe_falso(
            b"\xe3\x00core\\config.py\x00willy.py\x00",
            b"\xe3\x00C:\\Users\\Fulano\\willy\\core\\audio.py\x00",
        )
        self._gravar("Willy.exe", exe)
        with self.assertRaises(SystemExit) as erro:
            _funcao_do_build("_conferir_sem_caminho_da_maquina")(self.dist, "C:\\Users\\fulano")
        self.assertIn("Willy.exe", str(erro.exception))

    def test_conferencia_acusa_caminho_em_membro_de_zip(self):
        self._zip_falso(
            os.path.join("_internal", "base_library.zip"),
            {
                "limpo.pyc": b"sem caminho nenhum",
                "vaza.pyc": b"\xe3\x00C:\\Users\\Fulano\\projeto\\mod.py\x00",
                "vaza_u16.dat": "c:/users/fulano/x".encode("utf-16-le"),
            },
        )
        with self.assertRaises(SystemExit) as erro:
            _funcao_do_build("_conferir_sem_caminho_da_maquina")(self.dist, "C:\\Users\\fulano")
        msg = str(erro.exception)
        self.assertIn("base_library.zip", msg)
        self.assertIn("vaza.pyc", msg)
        self.assertIn("vaza_u16.dat", msg)
        self.assertNotIn("limpo.pyc", msg)

    def test_conferencia_passa_com_exe_limpo_e_controles_positivos(self):
        exe = self._exe_falso(
            b"\xe3\x00core\\config.py\x00",
            b"\xe3\x00willy.py\x00C:/Users/runneradmin/.cargo/x",
        )
        self._gravar("Willy.exe", exe)
        self._zip_falso(
            os.path.join("_internal", "base_library.zip"),
            {"os.pyc": b"C:/Users/runneradmin/lib/os.py"},
        )
        _funcao_do_build("_conferir_sem_caminho_da_maquina")(self.dist, "C:\\Users\\fulano")

    def test_conferencia_reprova_exe_sem_controles_positivos(self):
        exe = self._exe_falso(b"apenas um bloco sem os nomes de controle")
        self._gravar("Willy.exe", exe)
        with self.assertRaises(SystemExit) as erro:
            _funcao_do_build("_conferir_sem_caminho_da_maquina")(self.dist, "C:\\Users\\fulano")
        msg = str(erro.exception)
        self.assertIn("Willy.exe", msg)
        self.assertIn("core\\config.py", msg)

    def test_build_limpa_e_confere_antes_do_instalador_e_da_copia_local(self):
        fonte = _ler("build_installer.py")
        copia_artefatos = fonte.find("_copiar_artefatos_dist(BASE_DIR, dist_dir)")
        remove = fonte.find("_remover_pycache(dist_dir)")
        confere = fonte.find('_conferir_sem_caminho_da_maquina(dist_dir, os.path.expanduser("~"))')
        self.assertNotEqual(-1, remove, "o build não tira mais os __pycache__ de dist/Willy")
        self.assertNotEqual(-1, confere, "o build não confere mais o caminho da máquina")
        self.assertLess(copia_artefatos, remove)
        self.assertLess(remove, confere)
        self.assertLess(confere, fonte.find("if GERAR_INSTALADOR:"))
        self.assertLess(confere, fonte.find("_limpar_instalacao(local_app_dir)"))



if __name__ == "__main__":
    unittest.main()
