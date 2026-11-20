"""Roda um trecho que importa o willy.py num processo à parte, sem ler nem escrever nada do usuário.

Importar o willy monta o ConfigManager, o cofre e o SnippetManager no nível do módulo. Num
processo à parte, com APPDATA e WILLY_DATA_DIR temporários e o keyring desligado, o .env do
repo (no clone de quem desenvolve, o de verdade) não é lido, o .snippets.json não é criado
na raiz, o cofre não é tocado, e o estado global do willy não vaza para os outros testes.
A chave da Groq vem do ambiente: sem ela, o ConfigManager procuraria o .env antigo ao lado
do programa, que no código-fonte é o do repo.

O trecho imprime o resultado numa linha "RESULTADO=<json>".
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rodar_no_willy(script: str, *args: str) -> dict:
    with tempfile.TemporaryDirectory() as appdata:
        env = dict(
            os.environ,
            APPDATA=appdata,
            WILLY_DATA_DIR=os.path.join(appdata, "dados"),
            GROQ_API_KEY="gsk_teste_isolado",
            PYTHONPATH=RAIZ,
            PYTHONIOENCODING="utf-8",
            PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        )
        r = subprocess.run(
            [sys.executable, "-c", script, *args],
            cwd=RAIZ,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    linhas = [l for l in r.stdout.splitlines() if l.startswith("RESULTADO=")]
    if not linhas:
        raise AssertionError(f"o subprocesso não terminou (exit {r.returncode}): {r.stderr[-1500:]}")
    return json.loads(linhas[-1][len("RESULTADO="):])


def _arvore_do_willy() -> ast.Module:
    with open(os.path.join(RAIZ, "willy.py"), encoding="utf-8") as f:
        return ast.parse(f.read(), filename="willy.py")


def _constante_do_willy(nome: str):
    """O valor literal de uma constante de módulo em willy.py."""
    for no in _arvore_do_willy().body:
        if isinstance(no, ast.Assign) and any(getattr(alvo, "id", None) == nome for alvo in no.targets):
            return ast.literal_eval(no.value)
    raise KeyError(nome)


def _funcoes_do_willy(*nomes: str, **globais) -> dict:
    """Compila e executa apenas as funções pedidas de willy.py com o escopo fornecido."""
    arvore = _arvore_do_willy()
    funcoes = {n.name: n for n in arvore.body if isinstance(n, ast.FunctionDef)}
    corpo = []
    if (
        "_pronto_para_gravar" in funcoes
        and "_pronto_para_gravar" not in nomes
        and "_pronto_para_gravar" not in globais
    ):
        corpo.append(funcoes["_pronto_para_gravar"])
    corpo.extend(funcoes[n] for n in nomes)
    escopo = dict(globais)
    exec(compile(ast.Module(body=corpo, type_ignores=[]), "willy.py", "exec"), escopo)
    return escopo


def _funcao_do_willy(nome: str, **globais):
    """Compila e retorna uma única função de topo de willy.py."""
    return _funcoes_do_willy(nome, **globais)[nome]


def _todos(widget):
    """Itera recursivamente sobre todos os widgets descendentes de `widget`."""
    for filho in widget.winfo_children():
        yield filho
        yield from _todos(filho)


def _widgets(widget, tipo=object) -> list:
    """Retorna todos os descendentes de `widget` que são instância de `tipo`."""
    return [filho for filho in _todos(widget) if isinstance(filho, tipo)]


def _keycaps(widget) -> list:
    """Retorna todos os componentes Keycap descendentes de `widget`."""
    from ui.components.keycap import Keycap

    return _widgets(widget, Keycap)


def _resposta(conteudo):
    """Fábrica de resposta sintética de chat.completions.create da SDK Groq."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))])


def _erro_groq(classe, status: int, msg: str = "falhou"):
    """Fábrica de exceção HTTP tipada da SDK Groq sobre httpx.Response."""
    import httpx

    pedido = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return classe(msg, response=httpx.Response(status, request=pedido), body=None)


def _cancelar_afters_tcl(interp) -> None:
    if interp is None:
        return
    info = interp.call("after", "info")
    for after_id in interp.splitlist(info) if info else ():
        interp.call("after", "cancel", after_id)


def destruir_tk(*janelas) -> None:
    """Cancela callbacks `after` pendentes no Tcl e destrói deterministicamente janelas/widgets Tk."""
    for janela in janelas:
        if janela is None:
            continue
        alvo_tk = janela
        if not hasattr(alvo_tk, "tk"):
            for attr in ("window", "_root", "root"):
                candidato = getattr(janela, attr, None)
                if candidato is not None and hasattr(candidato, "tk"):
                    alvo_tk = candidato
                    break
        interp = getattr(alvo_tk, "tk", None)
        tcl_cmds = getattr(alvo_tk, "_tclCommands", ())
        if interp is not None and tcl_cmds is not None:
            _cancelar_afters_tcl(interp)
            eh_raiz = getattr(alvo_tk, "_w", None) == "."
            if not eh_raiz and hasattr(alvo_tk, "winfo_exists") and not alvo_tk.winfo_exists():
                continue
        elif tcl_cmds is None and alvo_tk is janela:
            continue
        janela.destroy()
        if interp is not None and getattr(alvo_tk, "_tclCommands", None) is not None:
            _cancelar_afters_tcl(interp)
