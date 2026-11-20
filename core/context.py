"""
Módulo de Consciência de Contexto (Context-Awareness) do Willy.
Identifica o aplicativo ativo em primeiro plano via Win32 API e fornece
diretrizes contextuais automáticas para o reconhecimento de voz e refinamento da Groq.
"""

import ctypes
import os
import sys
import time
from collections.abc import Iterable
from ctypes import wintypes
from typing import Any


class GUITHREADINFO(ctypes.Structure):
    """O estado de entrada de uma thread de interface: a janela com o foco do teclado e a do
    cursor de texto (o controle em que a pessoa digitava)."""
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]

# WinDLL próprios, carregados uma vez, com os protótipos de 64 bits. O ctypes.windll global é
# compartilhado (o pyperclip reescreve protótipos nele), e sem argtypes e restype o ctypes passa e
# devolve HWND e HANDLE como int de 32 bits. eh_janela_do_shell e eh_janela_do_willy, que rodam a
# cada troca de foco, ainda carregavam um WinDLL novo por chamada.
if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    for _funcao, _argtypes, _restype in (
        (user32.GetForegroundWindow, [], wintypes.HWND),
        (user32.GetWindowTextLengthW, [wintypes.HWND], ctypes.c_int),
        (user32.GetWindowTextW, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        (user32.GetWindowThreadProcessId, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        (user32.IsIconic, [wintypes.HWND], wintypes.BOOL),
        (user32.IsWindow, [wintypes.HWND], wintypes.BOOL),
        (user32.ShowWindow, [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        (user32.SetForegroundWindow, [wintypes.HWND], wintypes.BOOL),
        (user32.GetClassNameW, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        (user32.IsWindowVisible, [wintypes.HWND], wintypes.BOOL),
        (user32.GetWindowLongW, [wintypes.HWND, ctypes.c_int], ctypes.c_long),
        (user32.GetGUIThreadInfo, [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)], wintypes.BOOL),
        (user32.AttachThreadInput, [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
        (user32.BringWindowToTop, [wintypes.HWND], wintypes.BOOL),
        (user32.IsHungAppWindow, [wintypes.HWND], wintypes.BOOL),
        (user32.SetFocus, [wintypes.HWND], wintypes.HWND),
        (user32.WindowFromPoint, [wintypes.POINT], wintypes.HWND),
        (user32.GetAncestor, [wintypes.HWND, wintypes.UINT], wintypes.HWND),
        (user32.GetCursorPos, [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        (kernel32.GetCurrentThreadId, [], wintypes.DWORD),
        (kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        (kernel32.QueryFullProcessImageNameW,
         [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        (kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
        (dwmapi.DwmGetWindowAttribute, [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD], ctypes.c_long),
    ):
        _funcao.argtypes, _funcao.restype = _argtypes, _restype
else:
    user32 = kernel32 = dwmapi = None

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class ContextCategory:
    CODING = "CODING"
    MESSAGING = "MESSAGING"
    DOCUMENT = "DOCUMENT"
    BROWSER = "BROWSER"
    GENERAL = "GENERAL"


# Mapeamento de executáveis comuns para categorias de contexto
APP_CATEGORY_MAP = {
    # Ambientes de Desenvolvimento e Terminais
    "code.exe": ContextCategory.CODING,
    "cursor.exe": ContextCategory.CODING,
    "devenv.exe": ContextCategory.CODING,
    "pycharm64.exe": ContextCategory.CODING,
    "idea64.exe": ContextCategory.CODING,
    "webstorm64.exe": ContextCategory.CODING,
    "sublime_text.exe": ContextCategory.CODING,
    "windowsterminal.exe": ContextCategory.CODING,
    "powershell.exe": ContextCategory.CODING,
    "cmd.exe": ContextCategory.CODING,
    "alacritty.exe": ContextCategory.CODING,
    "wezterm-gui.exe": ContextCategory.CODING,
    "git-bash.exe": ContextCategory.CODING,

    # Comunicação e Mensagens
    "whatsapp.exe": ContextCategory.MESSAGING,
    "slack.exe": ContextCategory.MESSAGING,
    "discord.exe": ContextCategory.MESSAGING,
    "telegram.exe": ContextCategory.MESSAGING,
    "teams.exe": ContextCategory.MESSAGING,
    "signal.exe": ContextCategory.MESSAGING,

    # Documentação e Produtividade
    "winword.exe": ContextCategory.DOCUMENT,
    "excel.exe": ContextCategory.DOCUMENT,
    "powerpnt.exe": ContextCategory.DOCUMENT,
    "notion.exe": ContextCategory.DOCUMENT,
    "obsidian.exe": ContextCategory.DOCUMENT,
    "onenote.exe": ContextCategory.DOCUMENT,
    "acrobat.exe": ContextCategory.DOCUMENT,

    # Navegadores
    "chrome.exe": ContextCategory.BROWSER,
    "msedge.exe": ContextCategory.BROWSER,
    "firefox.exe": ContextCategory.BROWSER,
    "brave.exe": ContextCategory.BROWSER,
    "opera.exe": ContextCategory.BROWSER,
}


class ContextManager:
    """Detecta a janela ativa e gera instruções contextuais para a IA."""

    @classmethod
    def get_foreground_app(cls, hwnd: int | None = None) -> tuple[str, str, str]:
        """
        Retorna (nome_executavel, titulo_janela, categoria_contexto) da janela da frente, ou de `hwnd`.
        Exemplo: ('code.exe', 'willy.py - Visual Studio Code', 'CODING')
        """
        if sys.platform != "win32" or not user32 or not kernel32:
            return ("unknown.exe", "Desktop", ContextCategory.GENERAL)

        try:
            hwnd = hwnd or user32.GetForegroundWindow()
            if not hwnd:
                return ("desktop.exe", "Área de Trabalho", ContextCategory.GENERAL)

            # 1. Obtém o título da janela
            length = user32.GetWindowTextLengthW(hwnd)
            title_buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buff, length + 1)
            title = title_buff.value

            # 2. Obtém o Process ID
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # 3. Obtém o nome do executável
            h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            exe_name = "unknown.exe"
            if h_process:
                try:
                    path_buff = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(h_process, 0, path_buff, ctypes.byref(size)):
                        exe_name = os.path.basename(path_buff.value).lower()
                finally:
                    kernel32.CloseHandle(h_process)

            # 4. Classifica a categoria
            category = APP_CATEGORY_MAP.get(exe_name, ContextCategory.GENERAL)

            # Refinamento para navegadores: se o título contiver sites de dev
            if category == ContextCategory.BROWSER:
                title_lower = title.lower()
                if any(k in title_lower for k in ("github", "gitlab", "stackoverflow", "stack overflow", "chatgpt", "claude", "gemini", "localhost", "127.0.0.1")):
                    category = ContextCategory.CODING

            return (exe_name, title, category)

        except Exception:  # noqa: BLE001 — fronteira defensiva: Win32/ctypes na inspeção da janela ativa
            return ("unknown.exe", "", ContextCategory.GENERAL)

    @classmethod
    def resolve_app_rule(cls, app_exe: str, window_title: str,
                         rules: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
        """A regra por aplicativo (Contexto Automático) que vale para esta janela, ou None.

        Uma regra casa quando todo filtro que ela tem casa: `app_exe` igual ao executável (sem
        diferenciar maiúsculas) e `title_contains` contido no título. Entre as que casam, a mais
        específica: executável e título, depois só o título, depois só o executável. O título diz
        o site ou o documento ("gmail" no Chrome); o executável sozinho é o app inteiro. No
        empate, a que vem antes na lista, na ordem em que a pessoa as pôs.
        """
        exe = os.path.basename((app_exe or "").strip()).lower()
        titulo = (window_title or "").casefold()
        melhor: dict[str, Any] | None = None
        peso_da_melhor = 0
        for regra in rules or ():
            if not isinstance(regra, dict):
                continue
            app = str(regra.get("app_exe") or "").lower()
            trecho = str(regra.get("title_contains") or "").casefold()
            if (not app and not trecho) or (app and app != exe) or (trecho and trecho not in titulo):
                continue
            peso = (2 if trecho else 0) + (1 if app else 0)
            if peso > peso_da_melhor:
                melhor, peso_da_melhor = regra, peso
        return dict(melhor) if melhor is not None else None

    @classmethod
    def get_context_prompt_instruction(cls, category: str, app_name: str = "") -> str:
        """Retorna uma instrução de contexto para guiar a formatação do modelo de linguagem."""
        if category == ContextCategory.CODING:
            return (
                "CONTEXTO DO USUÁRIO: O usuário está em um ambiente de desenvolvimento de código ou terminal (ex: VS Code/Terminal). "
                "Preserve rigorosamente nomes técnicos em inglês, comandos de terminal, camelCase, snake_case, nomes de bibliotecas e funções. "
                "Mantenha termos de código sem traduzir."
            )
        elif category == ContextCategory.MESSAGING:
            return (
                "CONTEXTO DO USUÁRIO: O usuário está em um chat de mensagens instantâneas (ex: WhatsApp/Slack). "
                "Adote pontuação limpa, ágil e tom natural e conversacional, sem prolixidade."
            )
        elif category == ContextCategory.DOCUMENT:
            return (
                "CONTEXTO DO USUÁRIO: O usuário está em um editor de texto ou documentos (ex: Word/Docs/Notion). "
                "Garanta pontuação impecável, clareza executiva e estrutura de parágrafos formal."
            )
        return ""

    @classmethod
    def get_git_context(cls, window_title: str = "", app_exe: str = "") -> str:
        """
        Inspeciona o repositório Git do projeto em foco e extrai informações essenciais:
        branch ativa, arquivos modificados e último commit.
        Executado com timeout rigoroso (0.4s) e fallback gracioso caso não haja repositório.
        """
        import subprocess

        candidate_dirs: list[str] = []

        if window_title:
            for part in window_title.split(" - "):
                part = part.strip()
                if os.path.isabs(part) and os.path.isdir(part):
                    candidate_dirs.insert(0, part)
                elif ":" in part and ("\\" in part or "/" in part):
                    cand = part.split()[-1]
                    if os.path.isdir(cand):
                        candidate_dirs.insert(0, cand)

        if not candidate_dirs:
            return ""

        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        repo_dir = None
        for cand in candidate_dirs:
            try:
                res = subprocess.run(
                    ["git", "-C", cand, "rev-parse", "--is-inside-work-tree"],
                    capture_output=True, text=True, timeout=0.4, check=False,
                    creationflags=flags,
                )
                if res.returncode == 0 and "true" in res.stdout.lower():
                    repo_dir = cand
                    break
            except Exception:  # noqa: BLE001, S112 — fronteira defensiva: subprocess git em diretório candidato
                continue

        if not repo_dir:
            return ""

        try:
            res_root = subprocess.run(
                ["git", "-C", repo_dir, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=0.4, check=False,
                creationflags=flags,
            )
            root_path = res_root.stdout.strip() if res_root.returncode == 0 else repo_dir
            repo_name = os.path.basename(root_path)

            res_b = subprocess.run(
                ["git", "-C", repo_dir, "branch", "--show-current"],
                capture_output=True, text=True, timeout=0.4, check=False,
                creationflags=flags,
            )
            branch = res_b.stdout.strip() if res_b.returncode == 0 else "main"

            res_s = subprocess.run(
                ["git", "-C", repo_dir, "status", "--short"],
                capture_output=True, text=True, timeout=0.4, check=False,
                creationflags=flags,
            )
            status_lines = [line.strip() for line in res_s.stdout.splitlines() if line.strip()][:5]
            status_summary = ", ".join(status_lines) if status_lines else "Nenhum arquivo modificado (working tree limpo)"

            res_c = subprocess.run(
                ["git", "-C", repo_dir, "log", "-1", "--oneline"],
                capture_output=True, text=True, timeout=0.4, check=False,
                creationflags=flags,
            )
            last_commit = res_c.stdout.strip() if res_c.returncode == 0 else "Nenhum commit recente"

            return (
                f"[CONTEXTO GIT ATIVO]:\n"
                f"- Repositório: {repo_name}\n"
                f"- Branch Atual: {branch}\n"
                f"- Arquivos Modificados: {status_summary}\n"
                f"- Último Commit: {last_commit}\n"
                f"(Instrução: Utilize estas informações reais para preencher comandos CLI, nomes de branch e escopo da missão)"
            )
        except Exception:  # noqa: BLE001 — fronteira defensiva: subprocess git (status/branch/log)
            return ""

    _sticky_window: tuple[int, str] | None = None

    @classmethod
    def set_sticky_window(cls, hwnd: int, title: str) -> None:
        """Define a janela alvo para injeção persistente de ditados."""
        cls._sticky_window = (hwnd, title)

    @classmethod
    def get_sticky_window(cls) -> tuple[int, str] | None:
        """Retorna (hwnd, title) da janela fixa se ela ainda existir."""
        if cls._sticky_window:
            hwnd, title = cls._sticky_window
            if user32 and user32.IsWindow(hwnd):
                return (hwnd, title)
            else:
                cls._sticky_window = None
        return None

    @classmethod
    def clear_sticky_window(cls) -> None:
        """Limpa a janela fixa voltando ao modo padrão."""
        cls._sticky_window = None

    _SW_RESTORE, _GA_ROOT = 9, 2

    @classmethod
    def focus_window(cls, hwnd: int, hwnd_focus: int | None = None, prazo_s: float = 0.0) -> bool:
        """Traz `hwnd` para o primeiro plano e devolve o foco do teclado a `hwnd_focus` (o controle
        em que a pessoa digitava), se ele ainda for daquela janela.

        O SetForegroundWindow sozinho o Windows recusa a quem não é o processo da frente (o
        foreground lock), e era só isso: com o ditado longo, o texto ia para onde o foco
        estivesse no fim. As filas de entrada desta thread, da janela da frente e da do alvo
        ficam ligadas (AttachThreadInput) durante a troca, e são soltas em qualquer caso.

        Com `prazo_s`, espera o alvo chegar à frente e devolve se chegou: colar antes disso
        cairia na janela de antes. Sem prazo, devolve o que o SetForegroundWindow disse.
        """
        if sys.platform != "win32" or not user32 or not hwnd:
            return False
        try:
            # O app travado (sem atender mensagens há 5 s) fica de fora: com a fila dele ligada à
            # desta thread, o SetFocus esperaria por ele, e a entrega ficaria presa junto.
            if not user32.IsWindow(hwnd) or user32.IsHungAppWindow(hwnd):
                return False
            atual = kernel32.GetCurrentThreadId()
            tids = []
            for janela in (user32.GetForegroundWindow(), hwnd):
                tid = user32.GetWindowThreadProcessId(janela, None) if janela else 0
                if tid and tid != atual and tid not in tids:
                    tids.append(tid)
            ligadas = []
            try:
                for tid in tids:
                    if user32.AttachThreadInput(atual, tid, True):
                        ligadas.append(tid)
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, cls._SW_RESTORE)
                user32.BringWindowToTop(hwnd)
                trouxe = bool(user32.SetForegroundWindow(hwnd))
                if (hwnd_focus and user32.IsWindow(hwnd_focus)
                        and user32.GetAncestor(hwnd_focus, cls._GA_ROOT) == hwnd):
                    user32.SetFocus(hwnd_focus)
            finally:
                for tid in ligadas:
                    user32.AttachThreadInput(atual, tid, False)
            if prazo_s > 0:
                return cls.esperar_primeiro_plano(hwnd, prazo_s)
            return trouxe
        except Exception:  # noqa: BLE001 — fronteira defensiva: AttachThreadInput / SetForegroundWindow Win32
            return False

    @classmethod
    def esperar_primeiro_plano(cls, hwnd: int, prazo_s: float) -> bool:
        """`hwnd` chegou ao primeiro plano em até `prazo_s`?"""
        fim = time.monotonic() + prazo_s
        while cls.get_foreground_hwnd() != hwnd:
            if time.monotonic() >= fim:
                return False
            time.sleep(0.02)
        return True

    @classmethod
    def janela_existe(cls, hwnd: int) -> bool:
        if sys.platform != "win32" or not user32 or not hwnd:
            return False
        try:
            return bool(user32.IsWindow(hwnd))
        except Exception:  # noqa: BLE001 — fronteira defensiva: IsWindow Win32/ctypes
            return False

    @classmethod
    def janela_externa(cls, hwnd: int) -> bool:
        """Uma janela que pode receber o texto: existe e não é do Willy nem do shell."""
        return (cls.janela_existe(hwnd) and not cls.eh_janela_do_willy(hwnd)
                and not cls.eh_janela_do_shell(hwnd))

    @classmethod
    def foco_do_teclado(cls, hwnd: int) -> int:
        """O controle com o foco do teclado (ou, sem ele, o do cursor de texto) na thread de
        `hwnd`, se for dessa janela; 0 sem como saber."""
        if sys.platform != "win32" or not user32 or not hwnd:
            return 0
        try:
            tid = user32.GetWindowThreadProcessId(hwnd, None)
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not tid or not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
                return 0
            foco = info.hwndFocus or info.hwndCaret or 0
            if foco and user32.GetAncestor(foco, cls._GA_ROOT) == hwnd:
                return foco
            return 0
        except Exception:  # noqa: BLE001 — fronteira defensiva: GetGUIThreadInfo Win32/ctypes
            return 0

    @classmethod
    def janela_sob_o_cursor(cls) -> int:
        """A janela de topo (GA_ROOT) sob o ponteiro do mouse; 0 sem ela."""
        if sys.platform != "win32" or not user32:
            return 0
        try:
            ponto = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(ponto)):
                return 0
            sob = user32.WindowFromPoint(ponto)
            return (user32.GetAncestor(sob, cls._GA_ROOT) or 0) if sob else 0
        except Exception:  # noqa: BLE001 — fronteira defensiva: GetCursorPos / WindowFromPoint Win32
            return 0

    @classmethod
    def resolver_janela_alvo(cls, antes_do_willy: tuple[int, int] = (0, 0)) -> tuple[int, int]:
        """(janela, controle com o foco) para onde vai o texto de um ditado que começa agora.

        1. A janela fixada (Ctrl+Alt+F), se ainda existe.
        2. A do primeiro plano, se não for do Willy nem do shell.
        3. Com o Willy ou o shell na frente (o painel aberto, a barra de tarefas): a de fora sob
           o cursor, e depois `antes_do_willy`, a última de fora que esteve na frente.
        (0, 0) sem nenhuma: quem entrega decide (copia, se o foco estiver no Willy).
        """
        fixada = cls.get_sticky_window()
        if fixada:
            return fixada[0], 0
        frente = cls.get_foreground_hwnd()
        if cls.janela_externa(frente):
            return frente, cls.foco_do_teclado(frente)
        sob_o_cursor = cls.janela_sob_o_cursor()
        if cls.janela_externa(sob_o_cursor):
            return sob_o_cursor, 0
        janela, foco = antes_do_willy
        if cls.janela_externa(janela):
            return janela, foco
        return 0, 0

    @classmethod
    def get_foreground_hwnd(cls) -> int:
        """Retorna o identificador HWND da janela atualmente em primeiro plano."""
        if sys.platform != "win32" or not user32:
            return 0
        try:
            return user32.GetForegroundWindow() or 0
        except Exception:  # noqa: BLE001 — fronteira defensiva: GetForegroundWindow Win32/ctypes
            return 0

    # Janelas do próprio Windows que passam pelo primeiro plano: barra de tarefas, área de
    # trabalho, ícones ocultos, e no Windows 11 o Iniciar, a Pesquisa e o Alt+Tab. Não são o
    # app em que a pessoa estava.
    CLASSES_DO_SHELL = frozenset({"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW",
                                  "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
                                  "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
                                  "MultitaskingViewFrame", "TaskSwitcherWnd", "Shell_InputSwitchTopLevelWindow"})
    _GWL_EXSTYLE, _WS_EX_TOOLWINDOW, _DWMWA_CLOAKED = -20, 0x00000080, 14

    @classmethod
    def eh_janela_do_shell(cls, hwnd: int) -> bool:
        """Janela que não é um app em que se cola: do shell, invisível, de ferramenta (menus,
        dicas) ou oculta pelo DWM (as janelas "fantasma" do Windows 11)."""
        if sys.platform != "win32" or not hwnd:
            return False
        try:
            nome = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, nome, 256)
            if nome.value in cls.CLASSES_DO_SHELL or not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindowLongW(hwnd, cls._GWL_EXSTYLE) & cls._WS_EX_TOOLWINDOW:
                return True
            oculta = wintypes.DWORD()
            return bool(dwmapi.DwmGetWindowAttribute(hwnd, cls._DWMWA_CLOAKED, ctypes.byref(oculta), ctypes.sizeof(oculta)) == 0 and oculta.value)
        except Exception:  # noqa: BLE001 — fronteira defensiva: GetClassNameW / DwmGetWindowAttribute Win32
            return False

    @classmethod
    def foco_numa_janela_do_willy(cls) -> bool:
        """A janela em primeiro plano é do próprio processo do Willy (ou houve falha ao consultar o Win32)?"""
        if sys.platform != "win32" or not user32:
            return False
        try:
            hwnd = user32.GetForegroundWindow() or 0
            if not hwnd:
                return False
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception as e:  # noqa: BLE001 — fronteira defensiva: GetWindowThreadProcessId Win32
            print(f"[ContextManager] Erro ao verificar foco no Willy: {e!r}", file=sys.stderr)
            return True

    @classmethod
    def eh_janela_do_willy(cls, hwnd: int) -> bool:
        """A janela é do próprio processo (dashboard, pílula, menu da bandeja)?"""
        if sys.platform != "win32" or not hwnd:
            return False
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception:  # noqa: BLE001 — fronteira defensiva: GetWindowThreadProcessId em eh_janela_do_willy
            return False
