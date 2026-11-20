"""
Módulo da Pílula Flutuante (Floating Pill) do Willy.
Widget moderno estilo Dynamic Island / Obsidian com ondinha sonora em tempo real.
"""

import ctypes
import sys
import time
import tkinter as tk
from ctypes import wintypes

from core.audio_processing.diagnostico import VOLUME_SATURANDO, nivel_acima_do_piso
from ui.theme import (
    FLUTUANTE_AMARELO,
    FLUTUANTE_AZUL,
    FLUTUANTE_BORDA_PILULA,
    FLUTUANTE_CIANO,
    FLUTUANTE_CIANO_CLARO,
    FLUTUANTE_FUNDO,
    FLUTUANTE_LARANJA,
    FLUTUANTE_LILAS,
    FLUTUANTE_ROXO,
    FLUTUANTE_TEXTO,
    FLUTUANTE_TEXTO_APAGADO,
    FLUTUANTE_VERDE,
    FLUTUANTE_VERMELHO,
)

MONITOR_DEFAULTTONEAREST = 2

# Distância entre a base da pílula e a base da área de trabalho (acima da barra de tarefas).
# Com a barra padrão de 48 px, dá o mesmo lugar de antes: 130 px acima da borda da tela.
MARGEM_INFERIOR = 34
MARGEM_TOPO = 40
MARGEM_LATERAL_CURSOR = 20

# Estados que ficam na tela até o próximo (sem timer) e os avisos curtos que passam por cima
# deles. Um aviso no meio de uma gravação volta para o "ouvindo" em vez de esconder a pílula:
# a gravação continua e a pessoa precisa continuar vendo isso.
ESTADOS_PERSISTENTES = ("listening", "processing")
AVISOS_POR_CIMA = ("warning", "idle", "profile_changed", "whisper_mode", "sticky_pinned", "sticky_unpinned")
# Erro e sucesso, em geral, encerram o que está na tela (o fim do pipeline). Com por_cima=True
# (nada para desfazer, "aguarde o processo atual"), passam por cima como os avisos.
POR_CIMA_SE_PEDIDO = ("error", "success")
DURACAO_AVISO_MS = 3500
DURACAO_INFO_MS = 1400
DURACAO_ERRO_MS = 1800
DURACAO_SUCESSO_MS = 900
# O clique copia o último texto de novo só sem gravação nem processamento por baixo, nos
# estados de fim: "success" (colado) e "idle" (informação curta). Ouvindo ou processando, ou
# um aviso por cima deles, copiava o texto do ditado ANTERIOR por cima do clipboard e trocava
# o "ouvindo" por "Copiado!" no meio da gravação. No "error" só se o texto for do ditado que
# acabou de falhar ("Não consegui colar"): no modo privado, sem histórico, é o único jeito de
# recuperá-lo.
COPIA_NO_CLIQUE = ("success", "idle")
LARGURA_MIN, LARGURA_MAX = 340, 520


def largura_para(texto: str, escala: float = 1.0, largura_util: int | None = None) -> int:
    """Largura da pílula para `texto`: a 100%, 340 para os curtos, crescendo até 520.

    Com escala maior (125%, 150%) o Tk desenha a fonte maior, e a pílula fixa nos números de
    100% cortava o fim da mensagem ("…Clique p/ reenviar"): os limites e a largura por caractere
    crescem na mesma proporção. `largura_util` (a área de trabalho do monitor menos as margens)
    é o teto, para a pílula não passar da tela.
    """
    escala = max(1.0, escala)
    minimo, maximo = round(LARGURA_MIN * escala), round(LARGURA_MAX * escala)
    if largura_util:
        maximo = min(maximo, largura_util)
        minimo = min(minimo, maximo)
    return max(minimo, min(maximo, round((70 + len(texto) * 7) * escala)))


# Combinação de cada atalho citado nas mensagens, quando a pílula não sabe a configurada.
ATALHOS_PADRAO = {"hotkey": "ctrl+space", "master_hotkey": "ctrl+shift+space", "speak_hotkey": "ctrl+alt+s"}
_NOMES_DE_TECLA = {"space": "Espaço", "espaço": "Espaço", "espaco": "Espaço", "return": "Enter"}


def rotulo_do_atalho(combo: str) -> str:
    """"ctrl+shift+space" -> "Ctrl+Shift+Espaço", como as teclas aparecem no teclado."""
    partes = [p.strip().lower() for p in str(combo or "").split("+") if p.strip()]
    return "+".join(_NOMES_DE_TECLA.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in partes)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def configurar_prototipos_monitor(u) -> None:
    """Declara os protótipos Win32 de 64 bits para consulta de monitor em `u`."""
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.MonitorFromPoint.restype = wintypes.HMONITOR
    u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    u.GetMonitorInfoW.restype = wintypes.BOOL


def obter_hmonitor_e_area(
    u,
    hwnd: int,
    cursor: tuple[int, int],
) -> tuple[int, tuple[int, int, int, int]] | None:
    """Retorna `(hmonitor, (left, top, right, bottom))` da área de trabalho (`rcWork`) do monitor
    de `hwnd` ou, sem ele, do `cursor`. Retorna `None` fora do Windows ou se a API falhar."""
    if u is None:
        return None
    hmon = u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) if hwnd else None
    if not hmon:
        hmon = u.MonitorFromPoint(wintypes.POINT(*cursor), MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if hmon and u.GetMonitorInfoW(hmon, ctypes.byref(info)):
        r = info.rcWork
        return hmon, (r.left, r.top, r.right, r.bottom)
    return None


def _carregar_user32():
    """user32 próprio da pílula, com assinaturas declaradas.

    Instância separada de ctypes.windll.user32 de propósito: os restype/argtypes daqui não
    vazam para os outros módulos que usam a compartilhada. Sem restype, um HMONITOR acima
    de 2^31 voltaria truncado num int de 32 bits.
    """
    if sys.platform != "win32":
        return None
    u = ctypes.WinDLL("user32")
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetParent.restype = wintypes.HWND
    u.GetParent.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    u.SetWindowLongW.restype = ctypes.c_long
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    ]
    u.SetWindowPos.restype = wintypes.BOOL
    configurar_prototipos_monitor(u)
    return u


_user32 = _carregar_user32()


def calcular_posicao(
    modo: str,
    area: tuple[int, int, int, int],
    cursor: tuple[int, int],
    largura: int,
    altura: int,
) -> tuple[int, int]:
    """Canto superior esquerdo da pílula dentro de `area` (left, top, right, bottom).

    `area` é a área de trabalho do monitor onde a pessoa está, e não a tela primária: com
    dois monitores, a pílula no rodapé do primário fica fora do campo de visão de quem
    dita no outro.
    """
    left, top, right, bottom = area
    if modo == "seguir_cursor":
        mx, my = cursor
        x = min(right - largura - MARGEM_LATERAL_CURSOR, max(left + MARGEM_LATERAL_CURSOR, mx - largura // 2))
        y = max(top + MARGEM_TOPO, my - 70)
        return x, y
    x = left + (right - left - largura) // 2
    if modo == "topo":
        return x, top + MARGEM_TOPO
    return x, bottom - altura - MARGEM_INFERIOR


class FloatingPill:
    """Widget flutuante moderno do Willy com equalizador visual e posicionamento dinâmico."""

    def __init__(self, master, position_getter=None, atalho_getter=None, modo_privado_getter=None,
                 eh_do_willy_ou_do_shell=None):
        self.root = tk.Toplevel(master)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)

        self._get_position = position_getter or (lambda: "centro_inferior")
        # atributo do config_mgr ("hotkey", "master_hotkey"...) -> combinação configurada. As
        # mensagens citavam Ctrl+Espaço e Ctrl+Shift+Espaço fixos, mesmo com os atalhos trocados.
        self._get_atalho = atalho_getter or ATALHOS_PADRAO.get
        # Lido a cada clique: o modo privado muda com o Willy aberto. Sem ele, conta como ligado
        # (o texto copiado não vai para o histórico do Win+V).
        self._modo_privado = modo_privado_getter or (lambda: True)

        # A janela que recebe o texto do ditado em curso (willy.iniciar_gravacao); 0 sem ela. E
        # hwnd -> a janela é do Willy (o painel) ou do Windows (a barra de tarefas, o Iniciar)?
        # Sem quem diga, nenhuma é.
        self.janela_alvo = 0
        self._eh_do_willy_ou_do_shell = eh_do_willy_ou_do_shell or (lambda hwnd: False)
        self.width = LARGURA_MIN
        # A escala da fonte do texto, lida uma vez, junto com a criação da fonte (ver _escala).
        self._escala_da_fonte = self._escala()
        self.height = 48
        self.reposicionar()

        # Canvas estilo Dynamic Island da Apple
        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg=FLUTUANTE_FUNDO,
            highlightthickness=1,
            highlightbackground=FLUTUANTE_BORDA_PILULA
        )
        self.canvas.pack(fill="both", expand=True)

        # 4 barras do equalizador sonoro
        self.bar_x = [18, 25, 32, 39]
        self.bars = []
        for bx in self.bar_x:
            b = self.canvas.create_line(bx, 22, bx, 26, fill=FLUTUANTE_CIANO, width=3, capstyle=tk.ROUND)
            self.bars.append(b)

        # Ícone de transição / status
        self.status_icon = self.canvas.create_text(
            28, 24,
            text="",
            fill=FLUTUANTE_VERDE,
            font=("Segoe UI", 12, "bold"),
            state="hidden"
        )

        # Rótulo com tipografia Apple Segoe UI limpa
        self.text = self.canvas.create_text(
            52, 24,
            text="Willy ouvindo...",
            fill=FLUTUANTE_TEXTO,
            font=("Segoe UI", 10, "bold"),
            anchor="w"
        )

        self.last_text = ""
        # O last_text é do ditado em curso (ou do último, se nenhum começou depois)?
        self._texto_do_ditado_atual = False
        self.current_state: str | None = None
        # Argumentos do último estado persistente na tela, para voltar a ele depois de um aviso.
        self._persistente: tuple | None = None
        # Erro ou sucesso na tela com por_cima=True (ver POR_CIMA_SE_PEDIDO).
        self._erro_por_cima = False
        # Verdadeiro enquanto a pílula volta ao estado persistente depois de um aviso: essa
        # volta não reposiciona (a pílula está visível e não pode pular de monitor).
        self._voltando = False
        self.retry_callback = None
        self.hide_timer: str | None = None
        self.last_anim_time = 0.0

        # Interatividade estilo Dynamic Island (Hover e Clique para Re-copiar ou Reenviar)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)

        self.root.withdraw()
        self._hwnd = None
        self._configurar_janela_sem_foco()

    def _configurar_janela_sem_foco(self):
        """Aplica estilos estendidos do Windows para impedir roubo de foco (ACH-02)."""
        if _user32 is None:
            return
        try:
            self.root.update_idletasks()
            hwnd = _user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOPMOST = 0x00000008
            style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
            self._hwnd = hwnd
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro ao configurar janela sem foco: {e}", file=sys.stderr)
            self._hwnd = None

    def _mostrar_sem_foco(self):
        """Exibe a pílula no topo, no monitor de quem está ditando, sem tirar o foco dele (ACH-02).

        Se estava oculta, reposiciona antes: a pessoa pode ter mudado de monitor desde a
        última vez. Visível, fica onde está, para não pular no meio de um ditado.
        """
        try:
            # Todo estado escreve o texto e chama isto: a largura acompanha a mensagem. Fixa em
            # 340, a mensagem longa ("Transcrito, mas não consegui copiar...") saía cortada.
            self._ajustar_largura(self.canvas.itemcget(self.text, "text"))
            if not self.root.winfo_viewable():
                self.reposicionar()
            # O geometry() no Tk só agenda UpdateGeometryInfo para o próximo ciclo ocioso. Sem
            # descarregá-lo antes do ShowWindow, o WM_WINDOWPOSCHANGED do HWND oculto revertia a
            # posição e a largura do Tk para as coordenadas antigas (prendendo a pílula no monitor
            # de partida após o primeiro withdraw).
            self.root.update_idletasks()
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro ao preparar exibição sem foco: {e}", file=sys.stderr)

        if _user32 is not None and getattr(self, "_hwnd", None):
            try:
                SW_SHOWNOACTIVATE = 4
                HWND_TOPMOST = -1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                anterior = _user32.GetForegroundWindow()
                _user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
                _user32.SetWindowPos(
                    self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
                self._devolver_foco(anterior)
                return
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
                print(f"[FloatingPill] Erro ao exibir janela via Win32: {e}", file=sys.stderr)
        self.root.deiconify()
        self.root.lift()

    def _devolver_foco(self, anterior) -> None:
        """Devolve o primeiro plano à janela de quem dita, se a pílula o tomou.

        Rede de segurança, não correção de um roubo reproduzido: em 2026-10-22, com o Willy
        já aberto e outra janela na frente, nem SW_SHOWNOACTIVATE nem deiconify tiraram o
        foco (9 de 9). O roubo medido foi na criação da pílula, num processo recém-aberto.
        Só que logo depois do atalho o Willy tem direito de primeiro plano, e se a pílula
        virar a janela ativa a colagem e a digitação da pessoa vão para ela.
        """
        if not anterior or anterior == self._hwnd:
            return
        if _user32.GetForegroundWindow() == self._hwnd:
            _user32.SetForegroundWindow(anterior)

    def set_last_text(self, text: str) -> None:
        """Armazena o último texto transcrito para permitir cópia rápida por clique."""
        self.last_text = text
        self._texto_do_ditado_atual = True

    def _clique_copia(self) -> bool:
        """O clique pode copiar o last_text agora? (ver COPIA_NO_CLIQUE)"""
        if not self.last_text or self._persistente is not None:
            return False
        if self.current_state in COPIA_NO_CLIQUE:
            return True
        return self.current_state == "error" and self._texto_do_ditado_atual

    def set_retry_callback(self, callback) -> None:
        """Define o callback de retentativa acionado quando o usuário clica na pílula em estado de erro/offline."""
        self.retry_callback = callback

    def _on_enter(self, event=None):
        """Ao passar o mouse sobre a pílula, cancela o timer de ocultar para permitir inspeção."""
        try:
            self._cancelar_timer()
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro em _on_enter: {e}", file=sys.stderr)

    def _on_leave(self, event=None):
        """Ao tirar o mouse, retoma o fim que o _on_enter suspendeu (esconder ou voltar)."""
        try:
            if not self.root.winfo_viewable() or self.current_state in ESTADOS_PERSISTENTES:
                # Ouvindo e processando não têm fim agendado: tirar o mouse de cima não pode
                # esconder a pílula com a gravação em curso.
                return
            self._agendar_fim(800)
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro em _on_leave: {e}", file=sys.stderr)

    def _on_click(self, event=None):
        """Ao clicar na pílula:
        1. Se estiver no estado 'offline_retry' e houver callback de retry, reenvia o áudio salvo.
        2. Caso contrário, re-copia o texto para a área de transferência."""
        if self.current_state == "offline_retry" and self.retry_callback:
            try:
                self.canvas.itemconfig(self.status_icon, state="normal", text="⚡", fill=FLUTUANTE_LARANJA)
                self.canvas.itemconfig(self.text, text="Reenviando áudio salvo...", fill=FLUTUANTE_AMARELO)
                self.current_state = None
                self._cancelar_timer()
                self.retry_callback()
                return
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
                print(f"[FloatingPill] Erro ao acionar retry_callback: {e}", file=sys.stderr)
                return

        if self._clique_copia():
            try:
                # O clique da pessoa vai para o Win+V, a não ser no modo privado.
                from ui.components.copia import copiar_pelo_clique
                if copiar_pelo_clique(self.last_text, self._modo_privado()):
                    self.canvas.itemconfig(self.text, text="Copiado para a área de transferência!", fill=FLUTUANTE_VERDE)
                else:
                    self.canvas.itemconfig(self.text, text="Não copiei: clipboard ocupado", fill=FLUTUANTE_VERMELHO)
                self._agendar_fim(1000)
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
                print(f"[FloatingPill] Erro ao copiar pelo clique: {e}", file=sys.stderr)

    def _area_de_trabalho(self, pos_mode: str, cursor: tuple[int, int]) -> tuple[int, int, int, int]:
        """Área de trabalho (sem a barra de tarefas) do monitor onde a pessoa está.

        Em seguir_cursor, o monitor do cursor. Nos outros modos, o da janela em primeiro
        plano, que é onde o texto vai ser colado. Com o painel do Willy ou o shell (a barra de
        tarefas, o Iniciar) na frente, o texto não vai para eles: o monitor da janela-alvo, e
        sem ela o do cursor. Fora do Windows, a tela inteira menos uma barra de tarefas padrão.
        """
        if _user32 is not None:
            try:
                hwnd_ref = 0
                if pos_mode != "seguir_cursor":
                    fg = _user32.GetForegroundWindow()
                    if fg and fg != getattr(self, "_hwnd", None):
                        try:
                            eh_ignorado = bool(self._eh_do_willy_ou_do_shell(fg))
                        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
                            print(f"[FloatingPill] Erro ao consultar janela do Willy/shell: {e}", file=sys.stderr)
                            eh_ignorado = True
                        if not eh_ignorado:
                            hwnd_ref = fg
                        elif self.janela_alvo:
                            hwnd_ref = self.janela_alvo
                    elif self.janela_alvo:
                        hwnd_ref = self.janela_alvo
                res = obter_hmonitor_e_area(_user32, hwnd_ref, cursor)
                if res is not None:
                    return res[1]
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
                print(f"[FloatingPill] Erro ao obter área de trabalho do monitor: {e}", file=sys.stderr)
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 48

    def reposicionar(self) -> None:
        """Posiciona o widget de acordo com a preferência configurada."""
        pos_mode = self._get_position()
        try:
            cursor = self.root.winfo_pointerxy()
            area = self._area_de_trabalho(pos_mode, cursor)
            x, y = calcular_posicao(pos_mode, area, cursor, self.width, self.height)
            self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro ao reposicionar: {e}", file=sys.stderr)

    def update_status_text(self, text: str, fill: str = FLUTUANTE_TEXTO) -> None:
        """Atualiza com segurança o rótulo de texto da pílula com ajuste elástico de largura."""
        if self.current_state in AVISOS_POR_CIMA or self._erro_por_cima:
            # O cronômetro da reunião e a contagem do silêncio chegam a cada segundo: não
            # podem apagar o aviso que está por cima. Depois da volta, o próximo tique reescreve.
            return
        try:
            # Se o texto for longo (ex: preview de fala ou resumo), expande a pílula suavemente
            self._ajustar_largura(text)

            # Trunca com reticências se exceder a capacidade visual máxima
            display_text = text if len(text) <= 65 else text[:62] + "..."
            self.canvas.itemconfig(self.text, text=display_text, fill=fill)
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro em update_status_text: {e}", file=sys.stderr)

    def _escala(self) -> float:
        """A escala em que o Tk desenha a fonte da pílula (pixels por polegada / 96).

        Lida só na criação da pílula, que é quando a fonte do texto ganha o tamanho em pixels:
        uma troca de tela depois (encaixar o notebook, ligar um monitor) faz o Tk reler o DPI,
        mas a fonte já criada não cresce (medido pelo verificador do Bloco 7B), e a pílula
        ficaria até 1,5x mais larga que o texto. No Willy de hoje o Tk sobe antes de o processo
        ligar a consciência de DPI e fica em 96 ppp: a escala é 1,0 e a pílula, a de 100%.
        """
        try:
            return self.root.winfo_fpixels("1i") / 96.0
        except tk.TclError:
            return 1.0

    def _area_da_pilula(self) -> tuple[int, int, int, int] | None:
        """A área de trabalho do monitor da pílula: o da posição atual com ela visível, o de
        onde o reposicionar a põe com ela escondida."""
        try:
            if self.root.winfo_viewable():
                x, y = self._posicao_atual()
                return self._area_de_trabalho("seguir_cursor", (x + self.width // 2, y + self.height // 2))
            return self._area_de_trabalho(self._get_position(), self.root.winfo_pointerxy())
        except Exception:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            return None

    def _largura_util(self) -> int | None:
        """Largura da área de trabalho do monitor da pílula, menos as margens laterais."""
        area = self._area_da_pilula()
        if area is None:
            return None
        left, _, right, _ = area
        return right - left - 2 * MARGEM_LATERAL_CURSOR

    def _ajustar_largura(self, texto: str) -> None:
        """Largura para `texto` (ver largura_para)."""
        nova_largura = largura_para(texto, self._escala_da_fonte, self._largura_util())
        if nova_largura == self.width:
            return
        antiga, self.width = self.width, nova_largura
        self.canvas.configure(width=self.width)
        if self.root.winfo_viewable():
            # Visível: mesmo centro e mesma altura. Reposicionar releria o monitor da
            # janela em primeiro plano e a pílula pularia de monitor no meio do ditado. Perto da
            # borda (seguindo o cursor), o centro empurraria a pílula para fora da tela: ela
            # para na margem do monitor em que está.
            area = self._area_da_pilula()
            x, y = self._posicao_atual()
            x += (antiga - nova_largura) // 2
            if area is not None:
                left, _, right, _ = area
                x = max(left + MARGEM_LATERAL_CURSOR, min(x, right - nova_largura - MARGEM_LATERAL_CURSOR))
            self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        else:
            self.reposicionar()

    def _posicao_atual(self) -> tuple[int, int]:
        """(x, y) da pílula, lidos da geometria do Tk (vale oculta e com x negativo)."""
        _, x, y = self.root.geometry().replace("+-", "+~").split("+")
        return int(x.replace("~", "-")), int(y.replace("~", "-"))

    def _cancelar_timer(self) -> None:
        if self.hide_timer:
            try:
                self.root.after_cancel(self.hide_timer)
            except tk.TclError:
                pass
            except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
                print(f"[FloatingPill] Erro ao cancelar timer: {e}", file=sys.stderr)
            self.hide_timer = None

    def _agendar_fim(self, duracao_ms: int) -> None:
        """Agenda o fim do que está na tela: volta ao estado persistente que está por baixo
        (ouvindo, processando) ou, sem nenhum, esconde a pílula.

        Cancela o que estava agendado: um timer só por vez. Agendar por cima sem cancelar
        deixava uma volta órfã, que disparava depois do fim da gravação e prendia a pílula
        em "ouvindo" sem gravar nada.
        """
        self._cancelar_timer()
        if self._persistente:
            volta = self._persistente
            self.hide_timer = self.root.after(duracao_ms, lambda: self._voltar(volta))
        else:
            self.hide_timer = self.root.after(duracao_ms, self.root.withdraw)

    def _voltar(self, volta: tuple) -> None:
        self._voltando = True
        try:
            self.show_state(*volta)
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro ao restaurar estado persistente: {e}", file=sys.stderr)
        finally:
            self._voltando = False

    _voltar_ao_persistente = _voltar

    def _set_bars_visibility(self, visible: bool, fill: str | None = None) -> None:
        """Alterna a visibilidade (e opcionalmente a cor) das 4 barras de onda sonora."""
        st = "normal" if visible else "hidden"
        try:
            for b in self.bars:
                if fill is not None:
                    self.canvas.itemconfig(b, state=st, fill=fill)
                else:
                    self.canvas.itemconfig(b, state=st)
        except tk.TclError:
            pass
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro ao alternar visibilidade das barras: {e}", file=sys.stderr)

    def _aviso_por_cima(self, icone: str, cor_icone: str, texto: str, cor_texto: str, duracao_ms: int) -> None:
        """Mostra um aviso curto e agenda a volta ao que estava por baixo (ver _agendar_fim)."""
        self._set_bars_visibility(False)
        self.canvas.itemconfig(self.status_icon, state="normal", text=icone, fill=cor_icone)
        self.canvas.itemconfig(self.text, text=texto, fill=cor_texto)
        self._mostrar_sem_foco()
        self._agendar_fim(duracao_ms)

    @staticmethod
    def altura_das_barras(volume: float, piso_ruido: float = 0.0) -> float:
        """De 0 a 1, quanto a voz passa do ruído (ver nivel_acima_do_piso). Na C920 (ruído
        0,032), a conta fixa de antes, (volume - 0,005) / 0,035, deixava as 4 barras altas no
        silêncio."""
        return nivel_acima_do_piso(volume, piso_ruido)

    def update_waveform(self, volume: float, is_recording: bool, mode: str = "transcribe",
                        piso_ruido: float = 0.0) -> None:
        """Atualiza as barras sonoras em tempo real, descontando o piso de ruído do microfone."""
        if not is_recording:
            return

        try:
            agora = time.time()
            if agora - self.last_anim_time < 0.035:
                return
            self.last_anim_time = agora

            factor = self.altura_das_barras(volume, piso_ruido)
            multipliers = [0.75, 1.3, 1.1, 0.7]

            for i, bx in enumerate(self.bar_x):
                h = 4 + factor * 22 * multipliers[i]
                top_y = 24 - h / 2
                bot_y = 24 + h / 2
                bar_fill = self.cor_das_barras(volume, mode)
                self.canvas.coords(self.bars[i], bx, top_y, bx, bot_y)
                self.canvas.itemconfig(self.bars[i], fill=bar_fill)
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro em update_waveform: {e}", file=sys.stderr)

    @staticmethod
    def cor_das_barras(volume: float, mode: str = "transcribe") -> str:
        """A cor do modo; vermelho só perto da saturação. Antes era vermelho a partir de 0,0113,
        e na C920 as barras ficavam vermelhas em silêncio."""
        if volume > VOLUME_SATURANDO:
            return FLUTUANTE_VERMELHO
        return {"prompt": FLUTUANTE_ROXO, "translate": FLUTUANTE_LILAS, "translate_es": FLUTUANTE_LILAS,
                "transform": FLUTUANTE_LILAS,
                "send": FLUTUANTE_VERDE,
                "meeting": FLUTUANTE_LARANJA}.get(mode, FLUTUANTE_CIANO)

    def _atalho(self, atributo: str) -> str:
        """O atalho configurado, pronto para a mensagem; "" quando não há nenhum."""
        try:
            return rotulo_do_atalho(self._get_atalho(atributo) or "")
        except Exception:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            return ""

    def _resolver_visual_estado(
        self,
        state: str,
        msg: str,
        mode: str,
        refine_enabled: bool,
    ) -> dict | None:
        """Resolve os parâmetros visuais puros de `state` sem efeitos colaterais de canvas/janela."""
        if state == "listening":
            cores_modo = {
                "meeting": (FLUTUANTE_LARANJA, "🎙️ Modo Reunião (Gravando contínuo...)"),
                "prompt": (FLUTUANTE_ROXO, "🎯 Arquiteto de Prompts... (fale a tarefa do agente)"),
                "translate": (FLUTUANTE_LILAS, "Willy ouvindo (PT-BR ➔ Inglês)..."),
                "translate_es": (FLUTUANTE_LILAS, "Willy ouvindo (PT-BR ➔ Espanhol)..."),
                "send": (FLUTUANTE_VERDE, "🚀 Ditar e Enviar... (fale sua mensagem)"),
                "transform": (FLUTUANTE_LILAS, "🪄 Willy: Fale o que fazer com o texto..."),
            }
            cor_padrao, texto_padrao = cores_modo.get(mode, (FLUTUANTE_CIANO, "Willy ouvindo... (fale seu prompt)"))
            return {
                "reposicionar": not self._voltando,
                "novo_ditado": not self._voltando,
                "mostrar_barras": True,
                "cor_barras": cor_padrao,
                "icone": None,
                "cor_icone": "",
                "texto": msg or texto_padrao,
                "cor_texto": FLUTUANTE_TEXTO,
                "duracao_ms": None,
            }

        if state == "processing":
            modos_proc = {
                "meeting": ("📝", "Willy gerando Ata Executiva da Reunião..."),
                "prompt": ("🎯", "Willy estruturando Missão de Agente (/goal)..."),
                "translate": ("🌐", "Willy traduzindo para Inglês..."),
                "translate_es": ("🌐", "Willy traduzindo para Espanhol..."),
                "send": ("🚀", "Willy enviando com Enter..."),
                "transform": ("🪄", "Willy transformando seleção com IA..."),
            }
            texto_padrao = "Willy polindo prompt com IA..." if refine_enabled else "Willy transcrevendo..."
            icone, texto_proc = modos_proc.get(mode, ("⚡", texto_padrao))
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": icone,
                "cor_icone": FLUTUANTE_LARANJA,
                "texto": texto_proc,
                "cor_texto": FLUTUANTE_AMARELO,
                "duracao_ms": None,
            }

        if state == "success":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "✓",
                "cor_icone": FLUTUANTE_VERDE,
                "texto": msg if msg else "Willy colou seu prompt!",
                "cor_texto": FLUTUANTE_VERDE,
                "duracao_ms": DURACAO_SUCESSO_MS,
            }

        if state == "cancelled":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "✕",
                "cor_icone": FLUTUANTE_TEXTO_APAGADO,
                "texto": msg or "Willy não ouviu nada",
                "cor_texto": FLUTUANTE_TEXTO_APAGADO,
                "duracao_ms": DURACAO_INFO_MS if msg else 650,
            }

        if state == "app_enabled":
            voz = self._atalho("hotkey")
            return {
                "reposicionar": True,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "✨",
                "cor_icone": FLUTUANTE_AZUL,
                "texto": f"Willy acordou! ({voz})" if voz else "Willy acordou!",
                "cor_texto": FLUTUANTE_TEXTO,
                "duracao_ms": 1400,
            }

        if state == "app_disabled":
            mestre = self._atalho("master_hotkey")
            return {
                "reposicionar": True,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "💤",
                "cor_icone": FLUTUANTE_TEXTO_APAGADO,
                "texto": f"Willy foi dormir ({mestre})" if mestre else "Willy foi dormir",
                "cor_texto": FLUTUANTE_TEXTO_APAGADO,
                "duracao_ms": 1400,
            }

        if state == "sleeping_hint":
            mestre = self._atalho("master_hotkey")
            dica = f"Acorde com {mestre}" if mestre else "Acorde pelo ícone da bandeja"
            return {
                "reposicionar": True,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "💤",
                "cor_icone": FLUTUANTE_LARANJA,
                "texto": f"Willy dormindo! {dica}",
                "cor_texto": FLUTUANTE_AMARELO,
                "duracao_ms": 1600,
            }

        if state == "speaking":
            leitura = self._atalho("speak_hotkey")
            msg_speak = msg or (
                f"Lendo texto selecionado... ({leitura} p/ parar)" if leitura else "Lendo texto selecionado..."
            )
            return {
                "reposicionar": True,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "🔊",
                "cor_icone": FLUTUANTE_AZUL,
                "texto": msg_speak,
                "cor_texto": FLUTUANTE_CIANO,
                "duracao_ms": 4000,
            }

        if state == "sticky_pinned":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "🎯",
                "cor_icone": FLUTUANTE_VERDE,
                "texto": f"Destino fixado: {msg or 'Janela'}",
                "cor_texto": FLUTUANTE_VERDE,
                "duracao_ms": 2000,
            }

        if state == "sticky_unpinned":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "🎯",
                "cor_icone": FLUTUANTE_AMARELO,
                "texto": "Destino desfixado (Modo Normal)",
                "cor_texto": FLUTUANTE_AMARELO,
                "duracao_ms": 1800,
            }

        if state == "profile_changed":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "🎛️",
                "cor_icone": FLUTUANTE_CIANO_CLARO,
                "texto": msg or "Perfil de IA alterado",
                "cor_texto": FLUTUANTE_CIANO_CLARO,
                "duracao_ms": 1400,
            }

        if state == "whisper_mode":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "🤫",
                "cor_icone": FLUTUANTE_AMARELO,
                "texto": msg or "Modo Sussurro",
                "cor_texto": FLUTUANTE_AMARELO,
                "duracao_ms": 1400,
            }

        if state == "offline_retry":
            return {
                "reposicionar": True,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "⚠️",
                "cor_icone": FLUTUANTE_LARANJA,
                "texto": msg or "Sem conexão: áudio salvo. Clique p/ reenviar",
                "cor_texto": FLUTUANTE_AMARELO,
                "duracao_ms": 5500,
            }

        if state == "error":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "!",
                "cor_icone": FLUTUANTE_VERMELHO,
                "texto": msg or "Erro na transcrição",
                "cor_texto": FLUTUANTE_VERMELHO,
                "duracao_ms": DURACAO_ERRO_MS,
            }

        if state == "warning":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "⚠",
                "cor_icone": FLUTUANTE_LARANJA,
                "texto": msg or "Atenção",
                "cor_texto": FLUTUANTE_AMARELO,
                "duracao_ms": DURACAO_AVISO_MS,
            }

        if state == "idle":
            return {
                "reposicionar": False,
                "novo_ditado": False,
                "mostrar_barras": False,
                "cor_barras": None,
                "icone": "•",
                "cor_icone": FLUTUANTE_CIANO,
                "texto": msg,
                "cor_texto": FLUTUANTE_TEXTO,
                "duracao_ms": DURACAO_INFO_MS,
            }

        return None

    def show_state(self, state: str, msg: str = "", mode: str = "transcribe", refine_enabled: bool = True,
                   por_cima: bool = False) -> None:
        """Exibe os estados visuais (ouvindo, processando, sucesso, cancelado, dormindo, acordando, offline_retry).

        `por_cima`: erro ou sucesso que não encerra o que está acontecendo (Ctrl+Alt+Z sem
        ditado para desfazer, "Aguarde o processo atual"). No meio de uma gravação, passa por
        cima e volta ao "ouvindo", como os avisos; antes escondia a pílula com a gravação em
        curso. Sem estado persistente na tela, some no tempo de sempre.
        """
        if state == "idle" and not msg:
            # "idle" sem mensagem encerra a leitura em voz alta (fim ou parada) e nada mais:
            # não pode apagar um "processando" ou um "ouvindo" que estejam na tela.
            if self.current_state == "speaking":
                self.current_state = "idle"
                self._cancelar_timer()
                self.root.withdraw()
            return

        self._erro_por_cima = por_cima and state in POR_CIMA_SE_PEDIDO
        if state in ESTADOS_PERSISTENTES:
            self._persistente = (state, msg, mode, refine_enabled)
        elif state not in AVISOS_POR_CIMA and not self._erro_por_cima:
            self._persistente = None
        self.current_state = state
        self._cancelar_timer()

        visual = self._resolver_visual_estado(state, msg, mode, refine_enabled)
        if visual is None:
            return

        if visual["novo_ditado"]:
            # Ditado novo: o last_text é do anterior até o pipeline mandar o deste.
            self._texto_do_ditado_atual = False

        try:
            if visual["reposicionar"]:
                self.reposicionar()
            self._set_bars_visibility(visual["mostrar_barras"], fill=visual["cor_barras"])
            if visual["icone"] is None:
                self.canvas.itemconfig(self.status_icon, state="hidden")
            else:
                self.canvas.itemconfig(
                    self.status_icon,
                    state="normal",
                    text=visual["icone"],
                    fill=visual["cor_icone"],
                )
            self.canvas.itemconfig(self.text, text=visual["texto"], fill=visual["cor_texto"])
            self._mostrar_sem_foco()
            if visual["duracao_ms"] is not None:
                self._agendar_fim(visual["duracao_ms"])
        except Exception as e:  # noqa: BLE001 — Fronteira defensiva de widget/Win32 na pílula
            print(f"[FloatingPill] Erro ao renderizar estado {state!r}: {e}", file=sys.stderr)

    update_state = show_state

    def destroy(self):
        """Fecha o widget."""
        try:
            self._cancelar_timer()
            self.root.destroy()
        except Exception:  # noqa: BLE001, S110 — Fronteira defensiva de widget/Win32 na pílula
            pass
