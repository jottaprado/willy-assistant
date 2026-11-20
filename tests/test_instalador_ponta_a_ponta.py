"""
O willy_installer.iss de verdade, compilado e rodado, com um Willy de mentira.

Só roda com WILLY_TESTE_INSTALADOR=1 e o Inno Setup instalado: instala e desinstala de
verdade nesta máquina (um app "WillyTeste", com outro AppId, executável e mutex, numa pasta
temporária e com o valor "WillyTeste" no Run), e gera o app de mentira com o PyInstaller.
Nada disso toca no Willy de verdade. Leva uns dois minutos.

    set WILLY_TESTE_INSTALADOR=1
    .venv\\Scripts\\python.exe -m unittest tests.test_instalador_ponta_a_ponta -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISCC = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe")
PEDIDO = os.environ.get("WILLY_TESTE_INSTALADOR") == "1"

NOME, EXE, MUTEX = "WillyTeste", "WillyTeste.exe", r"Local\WillyTeste_E2E_Mutex"
APP_ID = "{{0B5E2E00-0000-4000-8000-00000000E2E0}"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_FALSO = f'''
import ctypes, time
ctypes.windll.kernel32.CreateMutexW(None, False, r"{MUTEX}")  # como o SingleInstanceManager
time.sleep(600)
'''


@unittest.skipUnless(sys.platform == "win32" and PEDIDO and os.path.exists(ISCC),
                     "instala de verdade: só com WILLY_TESTE_INSTALADOR=1 e o Inno Setup")
class TestInstaladorDeVerdade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import ctypes
        import winreg
        cls.k32, cls.winreg = ctypes.windll.kernel32, winreg
        cls.tmp = tempfile.mkdtemp(prefix="willy_e2e_")
        cls.dir = os.path.join(cls.tmp, "instalado")
        cls.lnk = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup",
                               NOME + ".lnk")
        script = os.path.join(cls.tmp, "app_falso.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(APP_FALSO)
        fonte = os.path.join(cls.tmp, "fonte")
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--noconsole",
                        "--name", NOME, "--distpath", fonte, "--workpath", os.path.join(cls.tmp, "work"),
                        "--specpath", os.path.join(cls.tmp, "work"), script],
                       check=True, capture_output=True)
        saida = os.path.join(cls.tmp, "out")
        subprocess.run([ISCC, "/Q", "/DMyAppVersion=9.9.9", f"/DMyAppName={NOME}", f"/DMyAppId={APP_ID}",
                        f"/DMyAppExeName={EXE}", f"/DMyAppMutex={MUTEX}", f"/DMyAppSourceDir={fonte}",
                        f"/O{saida}", "/Fsetup_teste", os.path.join(RAIZ, "willy_installer.iss")],
                       cwd=RAIZ, check=True, capture_output=True)
        cls.setup = os.path.join(saida, "setup_teste.exe")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        if getattr(self, "app", None) is not None:
            self.app.kill()
        # O que o instalador reabriu (ou sobrou de um teste que falhou no meio).
        subprocess.run(["taskkill", "/F", "/IM", EXE], capture_output=True, check=False)
        if os.path.exists(os.path.join(self.dir, "unins000.exe")):
            self._desinstalar()
        self._apagar_run()
        if os.path.exists(self.lnk):
            os.remove(self.lnk)
        shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------------
    def _mutex_existe(self):
        h = self.k32.OpenMutexW(0x00100000, False, MUTEX)  # SYNCHRONIZE
        if h:
            self.k32.CloseHandle(h)
        return bool(h)

    def _run(self):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, RUN) as k:
                return self.winreg.QueryValueEx(k, NOME)[0]
        except FileNotFoundError:
            return None

    def _apagar_run(self):
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, RUN, 0, self.winreg.KEY_SET_VALUE) as k:
                self.winreg.DeleteValue(k, NOME)
        except FileNotFoundError:
            pass

    def _instalar(self, tarefas=None):
        """`tarefas` None: sem /TASKS (o padrão na primeira instalação, as de antes na atualização)."""
        cmd = [self.setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", f"/DIR={self.dir}"]
        if tarefas is not None:
            cmd.append(f"/TASKS={tarefas}")
        return subprocess.run(cmd, check=False).returncode

    def _ligar_run_pelo_ajustes(self):
        with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, RUN, 0, self.winreg.KEY_SET_VALUE) as k:
            self.winreg.SetValueEx(k, NOME, 0, self.winreg.REG_SZ, f'"{os.path.join(self.dir, EXE)}"')

    def _desinstalar(self):
        unins = os.path.join(self.dir, "unins000.exe")
        subprocess.run([unins, "/VERYSILENT", "/SUPPRESSMSGBOXES"], check=False)
        fim = time.time() + 30  # o desinstalador se copia para o temp e o original volta na hora
        while os.path.exists(unins) and time.time() < fim:
            time.sleep(0.2)

    def _abrir_app(self):
        self.app = subprocess.Popen([os.path.join(self.dir, EXE)])
        fim = time.time() + 15
        while not self._mutex_existe() and time.time() < fim:
            time.sleep(0.1)
        self.assertTrue(self._mutex_existe(), "o app de mentira não abriu")

    # ------------------------------------------------------------------------------------
    def test_atualiza_com_o_willy_aberto(self):
        self.assertEqual(0, self._instalar("startupicon"))
        os.makedirs(os.path.join(self.dir, "_internal"), exist_ok=True)
        with open(os.path.join(self.dir, "_internal", "modulo_velho.pyd"), "w", encoding="utf-8"):
            pass
        with open(self.lnk, "w", encoding="utf-8"):  # o atalho da pasta Inicializar das versões antigas
            pass
        self._abrir_app()

        self.assertEqual(0, self._instalar("startupicon"))

        self.assertIsNotNone(self.app.poll(), "o instalador não fechou o Willy aberto")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "_internal", "modulo_velho.pyd")))
        self.assertFalse(os.path.exists(self.lnk), "o atalho legado ficou: o Willy abriria duas vezes")
        self.assertTrue(os.path.exists(os.path.join(self.dir, EXE)))
        self.assertEqual(f'"{os.path.join(self.dir, EXE)}"', self._run())
        # Silenciosa, o postinstall não roda: quem reabre é o ReabrirNoSilencioso.
        fim = time.time() + 15
        while not self._mutex_existe() and time.time() < fim:
            time.sleep(0.1)
        self.assertTrue(self._mutex_existe(), "o Willy fechado para a atualização não voltou a abrir")

    def test_instalacao_silenciosa_sem_willy_aberto_nao_abre_nada(self):
        self.assertEqual(0, self._instalar(""))
        time.sleep(2)
        self.assertFalse(self._mutex_existe())

    def test_desinstala_com_o_willy_aberto(self):
        self.assertEqual(0, self._instalar("startupicon"))
        self._abrir_app()
        self._desinstalar()
        self.assertIsNotNone(self.app.poll(), "a desinstalação não fechou o Willy aberto")
        self.assertIsNone(self._run())
        self.assertFalse(os.path.exists(os.path.join(self.dir, EXE)))

    def test_run_ligado_pelo_ajustes_sai_na_desinstalacao(self):
        self.assertEqual(0, self._instalar(""))
        self.assertIsNone(self._run(), "sem a tarefa, o instalador ligou o início com o Windows")
        self._ligar_run_pelo_ajustes()
        self._desinstalar()
        self.assertIsNone(self._run())

    def test_primeira_instalacao_liga_o_inicio_por_padrao(self):
        self.assertEqual(0, self._instalar())
        self.assertEqual(f'"{os.path.join(self.dir, EXE)}"', self._run())

    def test_atualizacao_nao_religa_o_inicio_desligado_no_ajustes(self):
        self.assertEqual(0, self._instalar())
        self._apagar_run()  # o interruptor do Ajustes
        self.assertEqual(0, self._instalar())  # a atualização, com a tarefa lembrada da primeira
        self.assertIsNone(self._run(), "a atualização religou o início que a pessoa desligou")

    def test_atualizacao_com_o_run_vazio_conta_como_desligado(self):
        # Como o AutoStartManager.is_enabled: valor vazio não liga nada.
        self.assertEqual(0, self._instalar(""))
        with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, RUN, 0, self.winreg.KEY_SET_VALUE) as k:
            self.winreg.SetValueEx(k, NOME, 0, self.winreg.REG_SZ, "")
        self.assertEqual(0, self._instalar())
        self.assertEqual("", self._run())

    def test_atualizacao_mantem_o_inicio_ligado_no_ajustes(self):
        self.assertEqual(0, self._instalar(""))
        # Ligado pelo Ajustes, com um caminho velho: a atualização o mantém e o aponta para o
        # executável instalado (não basta deixar o valor como estava).
        with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, RUN, 0, self.winreg.KEY_SET_VALUE) as k:
            self.winreg.SetValueEx(k, NOME, 0, self.winreg.REG_SZ, r'"C:\caminho\antigo\WillyTeste.exe"')
        self.assertEqual(0, self._instalar())
        self.assertEqual(f'"{os.path.join(self.dir, EXE)}"', self._run())

    def test_chave_orfa_sem_a_pasta_conta_como_instalacao_nova(self):
        # A pasta apagada à mão deixa a chave de desinstalação: não é atualização, e a tarefa
        # do início volta a ser oferecida (achado do verificador do Bloco 7B). Tratada como
        # atualização, a tarefa ficava escondida e o /TASKS dela era ignorado.
        self.assertEqual(0, self._instalar(""))
        shutil.rmtree(self.dir)
        self.assertEqual(0, self._instalar("startupicon"))
        self.assertEqual(f'"{os.path.join(self.dir, EXE)}"', self._run())

    def test_atualizacao_de_quem_tinha_o_atalho_legado_liga_o_run(self):
        # O caso medido na máquina do dono: instalação sem a tarefa registrada e o Willy.lnk na
        # pasta Inicializar. A 1.7.0 apagava o atalho sem gravar o Run: o início sumia.
        self.assertEqual(0, self._instalar(""))
        with open(self.lnk, "w", encoding="utf-8"):
            pass
        self.assertEqual(0, self._instalar())
        self.assertFalse(os.path.exists(self.lnk))
        self.assertEqual(f'"{os.path.join(self.dir, EXE)}"', self._run())

    def test_willy_que_nao_fecha_impede_a_instalacao(self):
        # O mutex num processo que o taskkill não acha: a rede do AppMutex segura.
        h = self.k32.CreateMutexW(None, False, MUTEX)
        try:
            codigo = self._instalar("")
        finally:
            self.k32.CloseHandle(h)
        self.assertNotEqual(0, codigo)
        self.assertFalse(os.path.exists(os.path.join(self.dir, EXE)))


if __name__ == "__main__":
    unittest.main()
