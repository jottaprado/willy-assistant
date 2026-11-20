"""
Análise estática por AST dos módulos do Willy.

Existe porque dois crashes certos passaram por toda a suíte sem serem notados:
willy.py e dashboard.py somam mais de 5000 linhas e quase nenhuma delas é exercitada
por teste — willy.py nunca é sequer importado, e dashboard.py tem um único teste de UI.
Os dois bugs eram puramente léxicos, então AST prova em milissegundos o que um teste de
execução só alcançaria com mock de hardware e display real.

Não importa nenhum módulo do projeto: lê o código-fonte e analisa a árvore. Roda headless,
sem áudio, sem Tk, sem rede.
"""

import ast
import builtins
import functools
import os
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _descobrir_modulos():
    """Descobre dinamicamente todos os módulos .py da raiz, core/, ui/ e scripts/.

    Antes, MODULOS era uma lista fixa de 16 arquivos: mais de 45 módulos criados ou
    extraídos em refatorações (como ui/overlays/pill.py e ui/overlays/spotlight.py)
    ficavam invisíveis para a análise estática.
    """
    modulos = []
    for arq_raiz in ("willy.py", "versao.py", "build_installer.py"):
        if os.path.isfile(os.path.join(RAIZ, arq_raiz)):
            modulos.append(arq_raiz)
    for pacote in ("core", "ui", "scripts"):
        pasta_pacote = os.path.join(RAIZ, pacote)
        if not os.path.isdir(pasta_pacote):
            continue
        for dirpath, dirnames, filenames in os.walk(pasta_pacote):
            dirnames[:] = [d for d in sorted(dirnames) if d != "__pycache__"]
            for fn in sorted(filenames):
                if fn.endswith(".py"):
                    modulos.append(os.path.relpath(os.path.join(dirpath, fn), RAIZ))
    return modulos


MODULOS = _descobrir_modulos()

BUILTINS = set(dir(builtins))


@functools.cache
def _fonte(caminho_rel: str) -> str:
    caminho = os.path.join(RAIZ, caminho_rel)
    with open(caminho, encoding="utf-8") as f:
        return f.read()


@functools.cache
def _carregar(caminho_rel: str) -> ast.Module:
    caminho = os.path.join(RAIZ, caminho_rel)
    return ast.parse(_fonte(caminho_rel), filename=caminho)


def _nomes_ligados(no):
    """Todo nome que recebe um valor em qualquer lugar da subárvore.

    Cobre atribuição, for, with, except-as, comprehension, import, def/class e
    argumentos de função — ou seja, tudo que faz um nome existir num escopo.
    """
    ligados = set()
    for n in ast.walk(no):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            ligados.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                ligados.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ligados.add(n.name)
        elif isinstance(n, ast.arg):
            ligados.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            ligados.add(n.name)
    return ligados


class TestNomesDefinidos(unittest.TestCase):
    """Nenhum nome em caixa alta pode ser lido sem existir em lugar nenhum do módulo.

    Foi assim que ACCENT_PURPLE_HOVER sobreviveu desde o commit inicial e ainda
    atravessou a extração dos tokens para ui/theme.py: o nome era lido num callback
    que só executa depois de dois cliques, então nada no boot nem na suíte o tocava.
    """

    def test_constantes_lidas_existem(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                arvore = _carregar(modulo)
                ligados = _nomes_ligados(arvore) | BUILTINS

                indefinidos = {}
                for no in ast.walk(arvore):
                    if not isinstance(no, ast.Name) or not isinstance(no.ctx, ast.Load):
                        continue
                    # Só constantes: um nome em SCREAMING_SNAKE_CASE nunca é local
                    # neste projeto, então ausência de ligação é erro, não escopo.
                    if not no.id.isupper() or not no.id[0].isalpha():
                        continue
                    if no.id in ligados:
                        continue
                    indefinidos.setdefault(no.id, no.lineno)

                self.assertEqual(
                    {}, indefinidos,
                    "nome(s) em caixa alta lidos mas nunca definidos em "
                    f"{modulo} (nome -> primeira linha de uso): {indefinidos}",
                )


def _pais(func):
    pais = {}
    for p in ast.walk(func):
        for f in ast.iter_child_nodes(p):
            pais[f] = p
    return pais


def _termina_fluxo(bloco: list[ast.stmt]) -> bool:
    return any(isinstance(s, (ast.Return, ast.Raise, ast.Break, ast.Continue)) for s in bloco)


def _ligados_garantidos_bloco(stmts: list[ast.stmt]) -> set[str]:
    garantidos: set[str] = set()
    for s in stmts:
        garantidos |= _ligados_garantidos_stmt(s)
    return garantidos


def _ligados_garantidos_stmt(s: ast.stmt) -> set[str]:
    if isinstance(
        s,
        (
            ast.Assign,
            ast.AnnAssign,
            ast.AugAssign,
            ast.Import,
            ast.ImportFrom,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        ),
    ):
        return _nomes_ligados(s)
    if isinstance(s, (ast.With, ast.AsyncWith)):
        nomes: set[str] = set()
        for item in s.items:
            if item.optional_vars:
                nomes |= _nomes_ligados(item.optional_vars)
        return nomes | _ligados_garantidos_bloco(s.body)
    if isinstance(s, ast.If):
        if not s.orelse:
            return set()
        b_term, o_term = _termina_fluxo(s.body), _termina_fluxo(s.orelse)
        b_lig, o_lig = _ligados_garantidos_bloco(s.body), _ligados_garantidos_bloco(s.orelse)
        if b_term and not o_term:
            return o_lig
        if o_term and not b_term:
            return b_lig
        return b_lig & o_lig
    if isinstance(s, ast.Try):
        ramos = []
        if not _termina_fluxo(s.body):
            ramos.append(_ligados_garantidos_bloco(s.body) | _ligados_garantidos_bloco(s.orelse))
        for h in s.handlers:
            if not _termina_fluxo(h.body):
                h_lig = _ligados_garantidos_bloco(h.body)
                if h.name:
                    h_lig.add(h.name)
                ramos.append(h_lig)
        base = set.intersection(*ramos) if ramos else set()
        return base | _ligados_garantidos_bloco(s.finalbody)
    return set()


def _ligados_antes_de(no: ast.AST, func: ast.AST, pais: dict[ast.AST, ast.AST]) -> set[str]:
    """Nomes cuja ligação é garantida em todos os caminhos que chegam até `no`."""
    garantidos: set[str] = set()
    atual: ast.AST | None = no
    while atual is not None and atual is not func:
        pai = pais.get(atual)
        if pai is None:
            break
        for campo in ("body", "orelse", "finalbody"):
            lista = getattr(pai, campo, None)
            if isinstance(lista, list) and atual in lista:
                idx = lista.index(atual)
                garantidos |= _ligados_garantidos_bloco(lista[:idx])
                if isinstance(pai, ast.ExceptHandler) and pai.name and campo == "body":
                    garantidos.add(pai.name)
                if isinstance(pai, (ast.For, ast.AsyncFor)) and campo == "body":
                    garantidos |= _nomes_ligados(pai.target)
                if isinstance(pai, (ast.With, ast.AsyncWith)) and campo == "body":
                    for item in pai.items:
                        if item.optional_vars:
                            garantidos |= _nomes_ligados(item.optional_vars)
                break
        atual = pai
    return garantidos


class TestVariavelNaoLigada(unittest.TestCase):
    """Nenhuma variável pode ser atribuída só dentro de um `if` e lida no `elif`/`else`.

    É a forma exata do bug que matava a wake word: `cur_sr` recebia valor dentro do
    ramo `if volume > speech_th`, e o `elif` logo abaixo avaliava uma expressão que a
    lia. Como qualquer atribuição dentro da função torna o nome local, o ramo alternativo
    levantava UnboundLocalError — dentro do callback de tempo real do sounddevice, que
    aborta a stream quando o callback lança.
    """

    def _infracoes(self, arvore):
        achados = []
        for func in ast.walk(arvore):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            pais = _pais(func)
            declarados = set()
            for n in ast.walk(func):
                if isinstance(n, (ast.Global, ast.Nonlocal)):
                    declarados.update(n.names)
            parametros = {a.arg for a in ast.walk(func) if isinstance(a, ast.arg)}

            for no in ast.walk(func):
                if not isinstance(no, ast.If) or not no.orelse:
                    continue

                ligados_no_corpo = set()
                for item in no.body:
                    ligados_no_corpo |= _nomes_ligados(item)

                # Só ligações garantidas em escopos ancestrais anteriores (ou definidas em
                # todos os ramos de um if/else anterior) protegem a leitura no ramo alternativo.
                ligados_antes = _ligados_antes_de(no, func, pais)
                ligados_no_alternativo = set()
                for item in no.orelse:
                    ligados_no_alternativo |= _nomes_ligados(item)

                for alt in no.orelse:
                    for n in ast.walk(alt):
                        if not isinstance(n, ast.Name) or not isinstance(n.ctx, ast.Load):
                            continue
                        if n.id not in ligados_no_corpo:
                            continue
                        if n.id in ligados_antes or n.id in parametros:
                            continue
                        if n.id in declarados or n.id in ligados_no_alternativo:
                            continue
                        achados.append(
                            f"{func.name}(): '{n.id}' e atribuido apenas dentro do "
                            f"`if` da linha {no.lineno} mas lido na linha {n.lineno}"
                        )
        return achados

    def test_sem_leitura_de_variavel_possivelmente_nao_ligada(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                infracoes = self._infracoes(_carregar(modulo))
                self.assertEqual(
                    [], infracoes,
                    f"UnboundLocalError garantido no ramo alternativo em {modulo}: "
                    + "; ".join(infracoes),
                )

    def test_atribuicao_em_if_anterior_nao_mascara_unbound_local(self):
        """AUD-133: Atribuição num `if` condicional anterior sem `else` não garante a variável."""
        arvore_invalida = ast.parse(
            "def f(a, b):\n"
            "    if a:\n"
            "        taxa = 16000\n"
            "    if b:\n"
            "        taxa = 48000\n"
            "    else:\n"
            "        return taxa\n"
        )
        self.assertEqual(1, len(self._infracoes(arvore_invalida)))

        arvore_valida = ast.parse(
            "def f(a, b):\n"
            "    if a:\n"
            "        taxa = 16000\n"
            "    else:\n"
            "        taxa = 44100\n"
            "    if b:\n"
            "        taxa = 48000\n"
            "    else:\n"
            "        return taxa\n"
        )
        self.assertEqual([], self._infracoes(arvore_valida))


class TestImportsLocaisResolvem(unittest.TestCase):
    """Todo nome importado de um módulo do próprio projeto tem que existir lá.

    Sem esta checagem os dois testes acima ficam cegos justamente onde o bug mora hoje:
    `from ui.theme import ACCENT_PURPLE_HOVER` liga o nome dentro de dashboard.py, então
    a análise local o considera definido — mesmo quando ui/theme.py não o define e o
    import estoura em runtime. Foi a prova por mutação que expôs esse ponto cego.
    """

    PACOTES_LOCAIS = ("ui", "core")

    def _nomes_de_modulo(self, dotted):
        """Nomes ligados no topo do módulo, ou None se não der para resolver com certeza."""
        base = os.path.join(RAIZ, *dotted.split("."))
        caminho = base + ".py"
        if not os.path.isfile(caminho):
            caminho = os.path.join(base, "__init__.py")
            if not os.path.isfile(caminho):
                return None

        with open(caminho, encoding="utf-8") as f:
            arvore = ast.parse(f.read(), filename=caminho)

        nomes = set()
        for no in arvore.body:  # só o topo: é o que um import enxerga
            if isinstance(no, (ast.Import, ast.ImportFrom)):
                for alias in no.names:
                    if alias.name == "*":
                        return None  # reexport por estrela: não dá para resolver aqui
                    nomes.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nomes.add(no.name)
            else:
                nomes |= _nomes_ligados(no)
        if caminho.endswith("__init__.py"):
            # `from core import modelos_llm` importa o submódulo, mesmo sem o __init__ citá-lo.
            for item in os.listdir(base):
                if item.endswith(".py") or os.path.isfile(os.path.join(base, item, "__init__.py")):
                    nomes.add(item.removesuffix(".py"))
        return nomes

    def test_nomes_importados_existem_na_origem(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                quebrados = []
                for no in ast.walk(_carregar(modulo)):
                    if not isinstance(no, ast.ImportFrom) or no.level:
                        continue
                    if not no.module or no.module.split(".")[0] not in self.PACOTES_LOCAIS:
                        continue
                    disponiveis = self._nomes_de_modulo(no.module)
                    if disponiveis is None:
                        continue
                    for alias in no.names:
                        if alias.name != "*" and alias.name not in disponiveis:
                            quebrados.append(
                                f"linha {no.lineno}: '{alias.name}' nao existe "
                                f"em {no.module}"
                            )
                self.assertEqual(
                    [], quebrados,
                    f"import quebrado em {modulo}: " + "; ".join(quebrados),
                )


_FABRICAS = {"WinDLL", "CDLL", "OleDLL", "PyDLL"}


def _chave(no):
    """'u', 'self._u', 'ctypes.windll.user32' ... ou None."""
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        base = _chave(no.value)
        return f"{base}.{no.attr}" if base else None
    return None


def _eh_windll_global(no):
    # ctypes.windll.user32 / windll.user32
    return (isinstance(no, ast.Attribute) and isinstance(no.value, (ast.Attribute, ast.Name))
            and _chave(no.value) in ("ctypes.windll", "windll", "ctypes.oledll", "oledll"))


def _eh_fabrica(no):
    return isinstance(no, ast.Call) and (
        (isinstance(no.func, ast.Attribute) and no.func.attr in _FABRICAS)
        or (isinstance(no.func, ast.Name) and no.func.id in _FABRICAS))


def _alvos(no):
    if isinstance(no, ast.Assign):
        alvos = no.targets
    elif isinstance(no, (ast.AnnAssign, ast.AugAssign)):
        alvos = [no.target]
    else:
        return []
    saida = []
    for t in alvos:
        if isinstance(t, (ast.Tuple, ast.List)):
            saida.extend(t.elts)
        else:
            saida.append(t)
    return saida


def _var_dll_local(func, nome):
    for no in ast.walk(func):
        if (isinstance(no, ast.Assign)
                and (_eh_fabrica(no.value) or _eh_windll_global(no.value))
                and any(_chave(t) == nome for t in _alvos(no))):
            return True
    return False


def _fabricas_de_dll(arvore: ast.AST) -> set[str]:
    """Funções que devolvem uma instância de DLL Win32 (em até 2 níveis)."""
    fabricas: set[str] = set()
    for _ in range(2):
        for f in ast.walk(arvore):
            if not isinstance(f, ast.FunctionDef):
                continue
            for r in ast.walk(f):
                if not isinstance(r, ast.Return) or r.value is None:
                    continue
                vals = r.value.elts if isinstance(r.value, ast.Tuple) else [r.value]
                for v in vals:
                    if (
                        _eh_fabrica(v)
                        or _eh_windll_global(v)
                        or (isinstance(v, ast.Name) and _var_dll_local(f, v.id))
                        or (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in fabricas)
                    ):
                        fabricas.add(f.name)
    return fabricas


def _variaveis_dll(arvore: ast.AST, fabricas: set[str]) -> set[str]:
    """Variáveis e atributos que armazenam uma instância de DLL Win32."""
    dlls: set[str] = set()
    for no in ast.walk(arvore):
        valor = getattr(no, "value", None)
        if not isinstance(no, (ast.Assign, ast.AnnAssign)) or valor is None:
            continue
        eh = (
            _eh_fabrica(valor)
            or _eh_windll_global(valor)
            or (isinstance(valor, ast.Call) and isinstance(valor.func, ast.Name) and valor.func.id in fabricas)
        )
        if eh:
            for t in _alvos(no):
                k = _chave(t)
                if k:
                    dlls.add(k)
    return dlls


def _prototipos_em_laco_for(no: ast.For, argt: set, rest: set) -> None:
    """Extrai declarações de argtypes/restype feitas num laço `for _f, _a, _r in (...)`."""
    if not isinstance(no.iter, (ast.Tuple, ast.List)):
        return
    alvo = no.target.elts[0] if isinstance(no.target, ast.Tuple) and no.target.elts else no.target
    if not isinstance(alvo, ast.Name):
        return
    declara = set()
    for corpo in no.body:
        for sub in ast.walk(corpo):
            for t in _alvos(sub):
                if (
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == alvo.id
                    and t.attr in ("argtypes", "restype")
                ):
                    declara.add(t.attr)
    for elt in no.iter.elts:
        f = elt.elts[0] if isinstance(elt, ast.Tuple) and elt.elts else elt
        if isinstance(f, ast.Attribute):
            par = (_chave(f.value), f.attr)
            if "argtypes" in declara:
                argt.add(par)
            if "restype" in declara:
                rest.add(par)


def _herdar_prototipos_de_fabrica(arvore: ast.AST, argt: set, rest: set) -> None:
    """Propaga para `_user32 = _carregar()` os protótipos declarados na DLL local devolvida."""
    defs = {f.name: f for f in ast.walk(arvore) if isinstance(f, ast.FunctionDef)}
    for no in ast.walk(arvore):
        if not (
            isinstance(no, ast.Assign)
            and isinstance(no.value, ast.Call)
            and isinstance(no.value.func, ast.Name)
            and no.value.func.id in defs
        ):
            continue
        f = defs[no.value.func.id]
        retornos = [r.value for r in ast.walk(f) if isinstance(r, ast.Return) and r.value is not None]
        dentro: dict[str, set] = {"argtypes": set(), "restype": set()}
        for sub in ast.walk(f):
            for t in _alvos(sub):
                if isinstance(t, ast.Attribute) and t.attr in dentro and isinstance(t.value, ast.Attribute):
                    dentro[t.attr].add((_chave(t.value.value), t.value.attr))
        alvos = no.targets[0].elts if isinstance(no.targets[0], ast.Tuple) else [no.targets[0]]
        for r in retornos:
            locais = r.elts if isinstance(r, ast.Tuple) else [r]
            if len(alvos) != len(locais):
                continue
            for local, alvo in zip(locais, alvos):
                kl, ka = _chave(local), _chave(alvo)
                if kl and ka:
                    argt |= {(ka, fn) for (k, fn) in dentro["argtypes"] if k == kl}
                    rest |= {(ka, fn) for (k, fn) in dentro["restype"] if k == kl}


def _prototipos_declarados(arvore: ast.AST) -> tuple[set, set]:
    argt: set = set()
    rest: set = set()
    for no in ast.walk(arvore):
        for t in _alvos(no):
            if isinstance(t, ast.Attribute) and t.attr in ("argtypes", "restype") and isinstance(t.value, ast.Attribute):
                par = (_chave(t.value.value), t.value.attr)
                (argt if t.attr == "argtypes" else rest).add(par)
        if isinstance(no, ast.For):
            _prototipos_em_laco_for(no, argt, rest)
    _herdar_prototipos_de_fabrica(arvore, argt, rest)
    return argt, rest


def _apelidos_dll(arvore: ast.AST, dlls: set[str]) -> dict[str, tuple[str | None, str]]:
    apelidos: dict[str, tuple[str | None, str]] = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Attribute) and _chave(no.value.value) in dlls:
            for t in _alvos(no):
                if isinstance(t, ast.Name):
                    apelidos[t.id] = (_chave(no.value.value), no.value.attr)
    return apelidos


def prototipos_faltando(arvore):
    fabricas = _fabricas_de_dll(arvore)
    dlls = _variaveis_dll(arvore, fabricas)
    argt, rest = _prototipos_declarados(arvore)
    apelidos = _apelidos_dll(arvore, dlls)
    infracoes = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        par = None
        if isinstance(no.func, ast.Attribute):
            alvo = no.func.value
            if _eh_windll_global(alvo) or _eh_fabrica(alvo):
                infracoes.append(
                    f"linha {no.lineno}: {_chave(alvo) or 'WinDLL(...)'}.{no.func.attr} "
                    "chamada inline (sem protótipo próprio)"
                )
                continue
            k = _chave(alvo)
            if k in dlls:
                par = (k, no.func.attr)
        elif isinstance(no.func, ast.Name) and no.func.id in apelidos:
            par = apelidos[no.func.id]
        if par is None:
            continue
        falta = [n for n, s in (("argtypes", argt), ("restype", rest)) if par not in s]
        if falta:
            infracoes.append(f"linha {no.lineno}: {par[0]}.{par[1]} sem {' e '.join(falta)}")
    return infracoes


_GEOM = {"geometry", "wm_geometry", "reposicionar", "_ajustar_largura"}
_SHOW = {"ShowWindow", "ShowWindowAsync"}
_FLUSH = {"update_idletasks", "update"}


def _condicional(no, pais, func):
    """O no esta dentro de if/for/while/except (pode nao rodar)?"""
    p = pais.get(no)
    while p is not None and p is not func:
        if isinstance(p, (ast.If, ast.IfExp, ast.For, ast.While, ast.ExceptHandler, ast.BoolOp)):
            return True
        p = pais.get(p)
    return False


def showwindow_sem_flush(arvore):
    funcs = [f for f in ast.walk(arvore) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    geom = set(_GEOM)
    mudou = True
    while mudou:  # fecho: metodo que chama geometria tambem e geometria
        mudou = False
        for f in funcs:
            if f.name in geom:
                continue
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in geom
                   for c in ast.walk(f)):
                geom.add(f.name)
                mudou = True
    infracoes = []
    for f in funcs:
        pais = _pais(f)
        chamadas = sorted((c for c in ast.walk(f) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)),
                          key=lambda c: (c.lineno, c.col_offset))
        for show in [c for c in chamadas if c.func.attr in _SHOW]:
            antes = [c for c in chamadas if (c.lineno, c.col_offset) < (show.lineno, show.col_offset)]
            geoms = [c for c in antes if c.func.attr in geom]
            if not geoms:
                continue
            ultima = geoms[-1]
            ok = any(c.func.attr in _FLUSH and not c.args and not c.keywords
                     and (c.lineno, c.col_offset) > (ultima.lineno, ultima.col_offset)
                     and not _condicional(c, pais, f)
                     for c in antes)
            if not ok:
                infracoes.append(f"{f.name}() linha {show.lineno}: {show.func.attr} depois de "
                                 f"{ultima.func.attr}() (linha {ultima.lineno}) sem update_idletasks() incondicional entre eles")
    return infracoes


class TestAssinaturasWin32Declaradas(unittest.TestCase):
    """Toda função chamada numa DLL Win32 por ctypes tem que declarar .argtypes e .restype
    na própria instância de WinDLL (sem chamadas inline em ctypes.windll global).
    """

    def test_toda_chamada_em_windll_declara_argtypes(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                infracoes = prototipos_faltando(_carregar(modulo))
                self.assertEqual(
                    [], infracoes,
                    f"chamada(s) Win32 sem .argtypes/.restype em {modulo}: " + "; ".join(infracoes),
                )

    def test_showwindow_win32_apos_reposicionar_exige_update_idletasks(self):
        for modulo in MODULOS:
            with self.subTest(modulo=modulo):
                infracoes = showwindow_sem_flush(_carregar(modulo))
                self.assertEqual(
                    [], infracoes,
                    f"ShowWindow sem flush incondicional do Tk em {modulo}: {infracoes}",
                )


def escritas_diretas_no_clipboard() -> list[str]:
    """Varre as árvores AST de MODULOS procurando escrita direta no clipboard fora de core/actions.py."""
    dono = os.path.normpath(os.path.join("core", "actions.py"))
    achados = []
    for modulo in MODULOS:
        if os.path.normpath(modulo) == dono:
            continue
        arvore = _carregar(modulo)
        for no in ast.walk(arvore):
            pyperclip_copy = (
                isinstance(no, ast.Call)
                and getattr(no.func, "attr", None) == "copy"
                and getattr(getattr(no.func, "value", None), "id", None) == "pyperclip"
            )
            importa_copy = (
                isinstance(no, ast.ImportFrom)
                and no.module == "pyperclip"
                and any(a.name == "copy" for a in no.names)
            )
            clipboard_tk = isinstance(no, ast.Call) and getattr(no.func, "attr", None) == "clipboard_append"
            if pyperclip_copy or importa_copy or clipboard_tk:
                achados.append(f"{modulo}:{no.lineno}")
    return achados


def chamadas_chat_fora_do_completar() -> list[str]:
    """Varre as árvores AST de MODULOS procurando chamadas a .completions.create fora de completar()."""
    achados = []
    for modulo in MODULOS:
        arvore = _carregar(modulo)
        dentro = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.FunctionDef) and no.name == "completar":
                dentro |= {id(n) for n in ast.walk(no)}
        for no in ast.walk(arvore):
            if (
                isinstance(no, ast.Attribute)
                and no.attr == "create"
                and getattr(no.value, "attr", None) == "completions"
                and id(no) not in dentro
            ):
                achados.append(f"{modulo}:{no.lineno}")
    return achados


def ocorrencias_nos_modulos(agulha: str) -> list[tuple[str, int]]:
    """Devolve (caminho_rel_posix, linha) de cada ocorrência de `agulha` nos módulos de MODULOS."""
    achados = []
    for modulo in MODULOS:
        rel_posix = modulo.replace("\\", "/")
        for n, linha in enumerate(_fonte(modulo).splitlines(), 1):
            if agulha in linha:
                achados.append((rel_posix, n))
    return achados


class TestFronteirasUnicas(unittest.TestCase):
    """Garante por AST que pontos únicos de fronteira (clipboard, LLM e InputStream) não sejam furados."""

    def test_nenhuma_escrita_de_clipboard_fora_do_secure_copy(self):
        self.assertEqual([], escritas_diretas_no_clipboard(), "escreva no clipboard com ActionManager.secure_copy")

    def test_nenhuma_chamada_de_chat_fora_do_completar(self):
        self.assertEqual([], chamadas_chat_fora_do_completar(), "chame o LLM por GroqService.completar")

    def test_so_core_audio_abre_input_stream(self):
        fora = [f"{rel}:{n}" for rel, n in ocorrencias_nos_modulos("sd.InputStream(") if rel != "core/audio.py"]
        self.assertEqual([], fora, f"InputStream aberto fora de core/audio.py: {fora}")


if __name__ == "__main__":
    unittest.main()
