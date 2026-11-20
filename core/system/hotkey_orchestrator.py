"""
Orquestrador de Atalhos Globais Win32 do Willy.
Centraliza o mapeamento, registro e recarga dinâmica de atalhos globais.
"""

import sys
from collections.abc import Callable

from core.hotkey import tecla_do_atalho


def _chave_combo(combo: str | None) -> tuple[int, int] | str:
    """Chave canônica da combinação: (modificadores, vk) quando válida, ou texto normalizado."""
    chave = tecla_do_atalho(combo)
    if chave is not None:
        return chave
    return str(combo or "").strip().lower()

HOTKEY_FIELDS = (
    "VOICE_HOTKEY", "TRANSLATE_HOTKEY", "TRANSLATE_ES_HOTKEY", "MASTER_HOTKEY", "MEETING_HOTKEY",
    "PROMPT_HOTKEY", "TRANSFORM_HOTKEY", "PROFILE_HOTKEY", "HISTORY_HOTKEY",
    "UNDO_HOTKEY", "SEND_HOTKEY", "SPEAK_HOTKEY", "STICKY_HOTKEY",
    "CAPTIONS_HOTKEY"
)

# (nome do handler, atributo do config_mgr com a combinação, campo no .env)
ATALHOS = (
    ("master", "master_hotkey", "MASTER_HOTKEY"),
    ("translate", "translate_hotkey", "TRANSLATE_HOTKEY"),
    ("translate_es", "translate_es_hotkey", "TRANSLATE_ES_HOTKEY"),
    ("meeting", "meeting_hotkey", "MEETING_HOTKEY"),
    ("prompt", "prompt_hotkey", "PROMPT_HOTKEY"),
    ("transform", "transform_hotkey", "TRANSFORM_HOTKEY"),
    ("profile", "profile_hotkey", "PROFILE_HOTKEY"),
    ("history", "history_hotkey", "HISTORY_HOTKEY"),
    ("undo", "undo_hotkey", "UNDO_HOTKEY"),
    ("send", "send_hotkey", "SEND_HOTKEY"),
    ("speak", "speak_hotkey", "SPEAK_HOTKEY"),
    ("sticky", "sticky_hotkey", "STICKY_HOTKEY"),
    ("captions", "captions_hotkey", "CAPTIONS_HOTKEY"),
    ("voice", "hotkey", "VOICE_HOTKEY"),
)
CAMPO_DO_ATALHO = {nome: campo for nome, _, campo in ATALHOS}

# Padrão que outro programa costuma tomar no Windows -> a alternativa tentada na partida. O
# Ctrl+Alt+L das legendas foi recusado em todas as partidas do dono desde 08/10 (willy_debug.log),
# e o aviso de atalho em uso aparecia a cada abertura do Willy.
ALTERNATIVAS_DO_PADRAO = {"captions": ("ctrl+alt+l", "ctrl+alt+j")}

Atalho = tuple[str, str, Callable]  # (nome, combinação, handler)


class HotkeyOrchestrator:
    """Gerencia o registro e recarregamento atômico de atalhos globais do Willy."""

    def __init__(self, hotkey_mgr, config_mgr, handlers: dict[str, Callable],
                 on_falha: Callable[[list[str], dict[str, str]], None] | None = None):
        self.hotkey_mgr = hotkey_mgr
        self.config_mgr = config_mgr
        self.handlers = handlers
        # Chamado com as combinações que não ficaram valendo e, para cada uma, a anterior
        # que continua no lugar ({nova: anterior}). Sem isso, um atalho tomado por outro
        # programa ficava mudo e o aviso só ia para o stderr, invisível no .exe.
        self.on_falha = on_falha
        # nome -> combinação registrada com sucesso da última vez.
        self._ativos: dict[str, str] = {}
        # campo do .env -> combinação que o Windows não registrou na última vez (e nenhuma outra
        # ficou no lugar): a aba Atalhos mostra o aviso na linha dele.
        self._falhas: dict[str, str] = {}

    def atalhos_com_falha(self) -> dict[str, str]:
        """{campo do .env: combinação} dos atalhos que ficaram sem tecla na última vez que os
        atalhos foram registrados. O que voltou à combinação anterior não entra: ele funciona."""
        return dict(self._falhas)

    def _pedidos(self) -> list[Atalho]:
        pedidos = []
        for nome, atributo, _ in ATALHOS:
            combo = getattr(self.config_mgr, atributo, None)
            handler = self.handlers.get(nome)
            if combo and handler:
                pedidos.append((nome, combo, handler))
        return pedidos

    def _aplicar(self, atalhos: list[Atalho]) -> list[str]:
        """Solta tudo e registra `atalhos`. Devolve as combinações que não registraram.

        Exceção no meio conta como recusa de todas: antes ela era engolida depois do
        stop() e do clear(), e o app ficava sem nenhum atalho sem ninguém saber.
        """
        try:
            self.hotkey_mgr.stop()
            self.hotkey_mgr.clear()
            for _, combo, handler in atalhos:
                self.hotkey_mgr.register(combo, handler)
            self.hotkey_mgr.start()
        except Exception as e:  # noqa: BLE001 — fronteira de registro global de atalhos
            print(f"[HotkeyOrchestrator] falha ao registrar os atalhos: {e!r}", file=sys.stderr)
            return [combo for _, combo, _ in atalhos]
        return list(getattr(self.hotkey_mgr, "falhas", None) or [])

    def _registrar(self, atalhos: list[Atalho]) -> dict[str, str]:
        """Registra `atalhos` e devolve {nome: combinação} dos que ficaram valendo.

        Combinação repetida: fica com o atalho que já a tinha ativa; sem nenhum, com o primeiro
        que a pede (na ordem de ATALHOS). Os outros nem vão ao Windows. As recusas voltam como
        texto da combinação; com a mesma combinação duas vezes, o atalho que registrou contaria
        como recusado também.

        Pela ordem só, dar ao prompt o Ctrl+Espaço do ditado nos Ajustes tirava a tecla do
        ditado (o prompt vem antes), e o ditado não tinha para onde voltar.
        """
        # sorted é estável: entre os que não tinham a combinação, vale a ordem de ATALHOS.
        atalhos = sorted(
            atalhos,
            key=lambda a: _chave_combo(self._ativos.get(a[0])) != _chave_combo(a[1]),
        )
        unicos: list[Atalho] = []
        vistas = set()
        for nome, combo, handler in atalhos:
            chave = _chave_combo(combo)
            if chave not in vistas:
                vistas.add(chave)
                unicos.append((nome, combo, handler))
        recusados = {_chave_combo(c) for c in self._aplicar(unicos)}
        return {nome: combo for nome, combo, _ in unicos if _chave_combo(combo) not in recusados}

    def registrar_todos(self) -> list[str]:
        """Registra os 14 atalhos da configuração atual. Devolve os que não ficaram valendo.

        Se uma combinação nova é recusada (outro programa já a tem) e o atalho tinha uma
        anterior funcionando, a anterior volta a valer: trocar o atalho nos Ajustes não
        pode deixar a pessoa sem ele. A volta vai para a config também.
        """
        if not self.hotkey_mgr:
            return []

        pedidos = self._pedidos()
        recarga = bool(self._ativos)  # na partida, nada estava registrado ainda
        ativos = self._registrar(pedidos)
        pedidas = {_chave_combo(combo) for _, combo, _ in pedidos}

        def _volta(nome: str, combo: str) -> bool:
            anterior = self._ativos.get(nome)
            # A anterior só volta se nenhum atalho a pediu agora: num "Restaurar Padrões",
            # a antiga de um pode ser a nova de outro, e a volta ligaria a tecla à função
            # errada.
            return (
                _chave_combo(ativos.get(nome)) != _chave_combo(combo)
                and anterior is not None
                and _chave_combo(anterior) != _chave_combo(combo)
                and _chave_combo(anterior) not in pedidas
            )

        if any(_volta(nome, combo) for nome, combo, _ in pedidos):
            ativos = self._registrar([(nome, self._ativos[nome] if _volta(nome, combo) else combo, handler)
                                      for nome, combo, handler in pedidos])

        alternativas: dict[str, str] = {}
        if not recarga:
            ativos, pedidos, alternativas = self._com_alternativa_do_padrao(pedidos, ativos)

        self._ativos = ativos
        self._falhas = {CAMPO_DO_ATALHO[nome]: combo for nome, combo, _ in pedidos if nome not in ativos}
        falhas = list(
            dict.fromkeys(
                combo for nome, combo, _ in pedidos
                if _chave_combo(ativos.get(nome)) != _chave_combo(combo)
            )
        )
        voltaram = [
            (nome, combo) for nome, combo, _ in pedidos
            if ativos.get(nome) is not None and _chave_combo(ativos.get(nome)) != _chave_combo(combo)
        ]
        # A volta só valia até reiniciar: a config já tinha sido salva com a recusada, e a
        # partida seguinte a tentava de novo, sem anterior para onde voltar. As abas Atalhos e
        # Ajustes, que leem a config, também mostravam a recusada.
        gravar = {CAMPO_DO_ATALHO[nome]: ativos[nome] for nome, _ in voltaram}
        gravar.update(alternativas)
        if recarga:
            # Pediu a combinação de outro atalho e não tinha anterior: na partida seguinte, sem
            # quem já a tinha, valeria a ordem da lista, e ele podia tirar a tecla do outro (o
            # mestre levava o Ctrl+Espaço do ditado). O campo fica vazio, como o atalho ficou.
            de_outro = {_chave_combo(combo): nome for nome, combo in ativos.items()}
            gravar.update({CAMPO_DO_ATALHO[nome]: "" for nome, combo, _ in pedidos
                           if nome not in ativos and de_outro.get(_chave_combo(combo), nome) != nome})
        if gravar:
            self.config_mgr.save_settings(gravar)
        mantidos = {combo: ativos[nome] for nome, combo in voltaram}
        if falhas and self.on_falha:
            self.on_falha(falhas, mantidos)
        return falhas

    def _com_alternativa_do_padrao(self, pedidos: list[Atalho], ativos: dict[str, str]
                                   ) -> tuple[dict[str, str], list[Atalho], dict[str, str]]:
        """Na partida, um atalho no padrão que o Windows recusou tenta a alternativa livre
        (ALTERNATIVAS_DO_PADRAO). Registrada, ela vai para a config, e o aviso de atalho em uso não
        aparece mais a cada abertura. Uma combinação escolhida pela pessoa, fora do padrão, que
        falha, continua com o aviso de sempre. Devolve (ativos, pedidos, {campo: alternativa})."""
        for nome, (padrao, alternativa) in ALTERNATIVAS_DO_PADRAO.items():
            pedido = next((p for p in pedidos if p[0] == nome), None)
            if pedido is None or _chave_combo(pedido[1]) != _chave_combo(padrao) or nome in ativos:
                continue
            # Outro atalho do Willy já pede a alternativa: tomá-la tiraria a tecla dele.
            if any(_chave_combo(combo) == _chave_combo(alternativa) for n, combo, _ in pedidos if n != nome):
                continue
            com_alternativa = [(n, alternativa if n == nome else c, h) for n, c, h in pedidos]
            tentativa = self._registrar(com_alternativa)
            if tentativa.get(nome) == alternativa:
                print(f"[HotkeyOrchestrator] {padrao} em uso no Windows: {CAMPO_DO_ATALHO[nome]} passa a "
                      f"{alternativa}", file=sys.stderr)
                return tentativa, com_alternativa, {CAMPO_DO_ATALHO[nome]: alternativa}
            # A alternativa também foi recusada: os outros ficaram registrados como antes, o atalho
            # segue pedindo o padrão, e o aviso é o de sempre.
            ativos = tentativa
        return ativos, pedidos, {}

    def recarregar_se_necessario(self, dados_atualizados: dict) -> bool:
        """Recarrega os atalhos se algum campo de hotkey tiver sido alterado nas configurações.

        Devolve se recarregou: quem mostra os atalhos tem que reler a config, que pode ter
        voltado à combinação anterior.
        """
        if any(k in dados_atualizados for k in HOTKEY_FIELDS):
            self.registrar_todos()
            return True
        return False
