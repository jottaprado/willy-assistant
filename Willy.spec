# -*- mode: python ; coding: utf-8 -*-
# O build oficial é o build_installer.py, que invoca "PyInstaller --noconfirm --clean Willy.spec".
# Este arquivo é a fonte única de datas e hiddenimports do empacotamento, conferida por test_empacotamento.
# Os caminhos saem da pasta deste arquivo (SPECPATH, que o PyInstaller define) e do
# site-packages do Python que roda o build: escritos à mão, só funcionavam na máquina e na
# pasta em que o spec foi gerado.
import os
import sysconfig

RAIZ = SPECPATH
SITE_PACKAGES = sysconfig.get_paths()["purelib"]

datas = [
    (os.path.join(SITE_PACKAGES, 'customtkinter'), 'customtkinter'),
    (os.path.join(RAIZ, 'core'), 'core'),
    (os.path.join(RAIZ, 'ui'), 'ui'),
    (os.path.join(RAIZ, 'vocabulario.txt'), '.'),
    (os.path.join(RAIZ, '.env.template'), '.'),
    (os.path.join(RAIZ, 'assets'), 'assets'),
]
# Pacotes nativos fixados em requirements.txt: se algum faltar no ambiente do build, falha na hora.
for pasta in ('_sounddevice_data', '_soundfile_data', 'silero_vad_lite/data'):
    caminho_pasta = os.path.join(SITE_PACKAGES, pasta)
    if not os.path.exists(caminho_pasta):
        raise FileNotFoundError(
            f"Pasta obrigatória ausente no build: {pasta!r} ({caminho_pasta}). "
            "Instale as dependências com: pip install -r requirements.txt"
        )
    datas.append((caminho_pasta, pasta))

a = Analysis(
    [os.path.join(RAIZ, 'willy.py')],
    # Sem o site-packages: ele já está no caminho do Python que roda o build, e o PyInstaller
    # avisa que listá-lo vira erro na versão 7.
    pathex=[RAIZ],
    binaries=[],
    datas=datas,
    hiddenimports=['sounddevice', 'soundfile', 'silero_vad_lite', 'customtkinter', 'darkdetect', 'pystray', 'pystray._win32', 'PIL', 'PIL._tkinter_finder', 'keyboard', 'pyperclip', 'groq', 'numpy', 'dotenv', 'keyring', 'keyring.backends', 'keyring.backends.Windows', 'win32ctypes', 'win32ctypes.pywin32', 'win32ctypes.pywin32.win32cred', 'win32ctypes.pywin32.pywintypes', 'core', 'core.config', 'core.sound', 'core.text_processing', 'core.groq_service', 'core.modelos_llm', 'core.audio', 'core.audio_processing', 'core.audio_processing.devices', 'core.audio_processing.dsp', 'core.audio_processing.diagnostico', 'core.audio_processing.vad', 'core.single_instance', 'core.hotkey', 'core.context', 'core.snippets', 'core.actions', 'core.autostart', 'core.tts', 'core.analytics', 'core.analytics.metrics', 'core.storage', 'core.storage.history_store', 'core.storage.vocabulary_store', 'core.storage.settings_store', 'core.storage.profile_manager', 'core.storage.caminhos', 'core.system', 'core.system.injector', 'core.system.hotkey_orchestrator', 'core.pipeline', 'core.pipeline.transcription_pipeline', 'ui', 'ui.theme', 'ui.tabs', 'ui.tabs.tab_shortcuts', 'ui.tabs.tab_vocabulary', 'ui.tabs.tab_diagnostics', 'ui.tabs.tab_templates', 'ui.tabs.tab_history', 'ui.tabs.tab_settings', 'ui.tabs.tab_onboarding', 'ui.tabs.regras_por_app', 'ui.components', 'ui.components.button', 'ui.components.empty_state', 'ui.components.keycap', 'ui.components.page_header', 'ui.components.search_field', 'ui.components.section_header', 'ui.components.segmented_control', 'ui.components.tooltip', 'ui.components.largura', 'ui.components.confirmacao', 'ui.components.copia', 'ui.overlays', 'ui.overlays.pill', 'ui.overlays.spotlight', 'ui.overlays.teleprompter', 'ui.overlays.tray', 'ui.navigation', 'ui.navigation.sidebar', 'ui.navigation.dwm', 'ui.dashboard', 'versao'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Willy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(RAIZ, 'assets', 'willy_icon.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Willy',
)
