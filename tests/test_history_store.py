"""
Testes unitários para o módulo core.storage.history_store.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core.storage.history_store import (
    _REPLACE_TENTATIVAS,
    HistoryEntry,
    HistoryStore,
    _atomic_write_json,
    _gravar_com_tentativas,
)


class TestHistoryStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_path = os.path.join(self.temp_dir.name, ".test_history.json")
        self.store = HistoryStore(filepath=self.history_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_empty_or_missing(self):
        self.assertEqual(self.store.load_history(), [])

    def test_save_and_load_item(self):
        itens = self.store.save_history_item("teste de ditado por voz", modo="transcribe")
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["text"], "teste de ditado por voz")
        self.assertEqual(itens[0]["words"], 5)
        self.assertEqual(itens[0]["mode"], "transcribe")
        self.assertIn("timestamp", itens[0])
        self.assertIn("id", itens[0])

        loaded = self.store.load_history()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["text"], "teste de ditado por voz")

    def test_save_history_item_with_files(self):
        md_file = os.path.join(self.temp_dir.name, "doc.md")
        wav_file = os.path.join(self.temp_dir.name, "doc.wav")
        with open(wav_file, "w") as f:
            f.write("wav content")

        itens = self.store.save_history_item("prompt com arquivo", modo="prompt", file_path=md_file)
        self.assertEqual(itens[0]["file_path"], md_file)
        self.assertEqual(itens[0]["audio_path"], wav_file)

    def test_history_cap_at_100(self):
        for i in range(120):
            self.store.save_history_item(f"mensagem {i}")
        loaded = self.store.load_history()
        self.assertEqual(len(loaded), 100)
        self.assertEqual(loaded[-1]["text"], "mensagem 119")

    def test_delete_item(self):
        itens = self.store.save_history_item("item 1")
        item1_id = itens[0]["id"]
        self.store.save_history_item("item 2")

        self.assertTrue(self.store.delete_item(item1_id))
        loaded = self.store.load_history()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["text"], "item 2")

        # Deletar ID inexistente retorna False
        self.assertFalse(self.store.delete_item("id_inexistente"))

    def test_clear_history(self):
        self.store.save_history_item("item 1")
        self.store.save_history_item("item 2")
        self.assertEqual(len(self.store.load_history()), 2)

        self.store.clear_history()
        self.assertEqual(self.store.load_history(), [])

    def test_search(self):
        self.store.save_history_item("reunião de alinhamento com time", modo="meeting")
        self.store.save_history_item("tradução do relatório trimestral", modo="translate")
        self.store.save_history_item("ditado simples", modo="transcribe")

        res_meeting = self.store.search(query="alinhamento", mode_filter="meeting")
        self.assertEqual(len(res_meeting), 1)
        self.assertEqual(res_meeting[0]["mode"], "meeting")

        res_all_filter = self.store.search(query="relatório", mode_filter="all")
        self.assertEqual(len(res_all_filter), 1)

        res_empty = self.store.search(query="termo inexistente")
        self.assertEqual(len(res_empty), 0)

    def test_atomic_write_json(self):
        data = {"chave": "valor_atômico", "lista": [1, 2, 3]}
        target = os.path.join(self.temp_dir.name, "atomic_test.json")
        _atomic_write_json(target, data, indent=2)

        self.assertTrue(os.path.exists(target))
        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_escritores_e_leitor_concorrentes_nao_perdem_itens(self):
        """Sem lock: 3 threads x 15 appends com a UI lendo deixavam 2 itens no disco."""
        import threading
        parar = threading.Event()

        def leitor():
            while not parar.is_set():
                self.store.load_history()

        def escritor(n):
            for i in range(15):
                self.store.save_history_item(f"t{n}-{i}")

        t_leitor = threading.Thread(target=leitor)
        t_leitor.start()
        escritores = [threading.Thread(target=escritor, args=(n,)) for n in range(3)]
        for t in escritores:
            t.start()
        for t in escritores:
            t.join()
        parar.set()
        t_leitor.join()

        textos = {it["text"] for it in self.store.load_history()}
        self.assertEqual({f"t{n}-{i}" for n in range(3) for i in range(15)}, textos)

    def test_ids_sao_unicos_mesmo_no_mesmo_milissegundo(self):
        """A exclusão é por id: id repetido faria excluir um ditado apagar o outro."""
        from unittest.mock import patch

        import core.storage.history_store as hs
        with patch.object(hs.time, "time", return_value=1_700_000_000.0):
            self.store.save_history_item("primeiro")
            self.store.save_history_item("segundo")
        ids = [it["id"] for it in self.store.load_history()]
        self.assertEqual(2, len(set(ids)), ids)
        self.store.delete_item(ids[0])
        self.assertEqual(["segundo"], [it["text"] for it in self.store.load_history()])

    def test_arquivo_corrompido_vai_para_quarentena_e_o_historico_recomeca(self):
        """Gravar por cima apagaria os dados; recusar para sempre travaria todo ditado seguinte."""
        import glob
        conteudo = '[{"text": "cem ditados antigos"'  # truncado por um desligamento abrupto
        with open(self.history_path, "w", encoding="utf-8") as f:
            f.write(conteudo)

        self.assertFalse(self.store.delete_item("x"), "excluir de um arquivo ilegível não faz nada")
        self.store.save_history_item("novo")

        self.assertEqual(["novo"], [it["text"] for it in self.store.load_history()])
        quarentena = glob.glob(self.history_path + ".corrompido-*")
        self.assertEqual(1, len(quarentena), "o conteúdo antigo tem que ficar preservado")
        with open(quarentena[0], encoding="utf-8") as f:
            self.assertEqual(conteudo, f.read())

    def test_segunda_quarentena_no_mesmo_segundo_nao_apaga_a_primeira(self):
        import glob
        from unittest.mock import patch

        import core.storage.history_store as hs
        with patch.object(hs.time, "strftime", return_value="20260929-120000"):
            for lixo in ("lixo1", "lixo2"):
                with open(self.history_path, "w", encoding="utf-8") as f:
                    f.write(lixo)
                self.store.save_history_item("novo")
        conteudos = set()
        for caminho in glob.glob(self.history_path + ".corrompido-*"):
            with open(caminho, encoding="utf-8") as f:
                conteudos.add(f.read())
        self.assertEqual({"lixo1", "lixo2"}, conteudos)

    def test_arquivo_em_uso_na_leitura_nao_e_sobrescrito(self):
        """Falha de LEITURA (arquivo em uso) é passageira: nada de quarentena nem de gravar por cima."""
        from unittest.mock import patch
        self.store.save_history_item("antigo")
        with patch.object(self.store, "_load_strict", side_effect=PermissionError("em uso")):
            with self.assertRaises(OSError):
                self.store.save_history_item("novo")
            self.assertFalse(self.store.update(lambda itens: []))
        self.assertEqual(["antigo"], [it["text"] for it in self.store.load_history()])

    def test_arquivo_em_uso_e_regravado_na_tentativa_seguinte(self):
        from unittest.mock import patch

        import core.storage.history_store as hs
        real = hs._atomic_write_json
        falhas = [PermissionError("em uso"), PermissionError("em uso")]

        def instavel(*a, **kw):
            if falhas:
                raise falhas.pop(0)
            return real(*a, **kw)

        with patch.object(hs, "_atomic_write_json", side_effect=instavel), \
             patch.object(hs.time, "sleep"):
            self.assertTrue(self.store.save_history([{"id": "1", "text": "a"}]))
        self.assertEqual("a", self.store.load_history()[0]["text"])

    def test_arquivo_sempre_em_uso_falha_sem_gravar(self):
        from unittest.mock import patch

        import core.storage.history_store as hs
        with patch.object(hs, "_atomic_write_json", side_effect=PermissionError("em uso")) as w, \
             patch.object(hs.time, "sleep"):
            self.assertFalse(self.store.save_history([{"id": "1", "text": "a"}]))
        self.assertEqual(hs._REPLACE_TENTATIVAS, w.call_count)

    def test_history_entry_dataclass(self):
        entry = HistoryEntry(
            id="123",
            text="texto",
            mode="transcribe",
            timestamp="24/09/2026 00:00",
            words=1,
            file_path="doc.md",
            audio_path="doc.wav",
            duration_s=3.46,
        )
        d = entry.to_dict()
        self.assertEqual(d["id"], "123")
        self.assertEqual(d["file_path"], "doc.md")
        self.assertEqual(d["duration_s"], 3.5)

    def test_superficie_publica_e_higiene_core_storage(self):
        """AUD-009, AUD-010, AUD-037, AUD-039: superfície limpa e snippets padrão sem dados fictícios."""
        import core
        import core.storage as cs
        from core.actions import ActionManager
        from core.snippets import DEFAULT_SNIPPETS

        for interno in ("HistoryEntry", "HistoryStore", "SettingsStore", "VocabularyStore"):
            self.assertNotIn(interno, core.__all__)
        self.assertNotIn("_atomic_write_json", cs.__all__)
        self.assertIn("AppRulesStore", cs.__all__)
        self.assertIn("ProfileManager", cs.__all__)
        self.assertFalse(hasattr(ActionManager, "ACTION_TRIGGER_PATTERNS"))
        for s in DEFAULT_SNIPPETS:
            self.assertNotIn("contato@willy.ai", s["content"])
            self.assertNotIn("abc-defg-hij", s["content"])


class TestGravarComTentativas(unittest.TestCase):
    """Antivírus, indexador ou editor segurando o arquivo: o os.replace falha por um instante."""

    def test_arquivo_preso_por_um_instante_grava_na_tentativa_seguinte(self):
        chamadas = []

        def _gravar():
            chamadas.append(1)
            if len(chamadas) < 3:
                raise PermissionError("em uso por outro processo")

        with patch("core.storage.history_store.time.sleep"):
            _gravar_com_tentativas(_gravar)
        self.assertEqual(3, len(chamadas))

    def test_arquivo_preso_o_tempo_todo_propaga_o_erro(self):
        chamadas = []

        def _gravar():
            chamadas.append(1)
            raise PermissionError("em uso por outro processo")

        with patch("core.storage.history_store.time.sleep"), self.assertRaises(PermissionError):
            _gravar_com_tentativas(_gravar)
        self.assertEqual(_REPLACE_TENTATIVAS, len(chamadas))

    def test_outro_erro_nao_e_repetido(self):
        chamadas = []

        def _gravar():
            chamadas.append(1)
            raise OSError("disco cheio")

        with self.assertRaises(OSError):
            _gravar_com_tentativas(_gravar)
        self.assertEqual(1, len(chamadas))


if __name__ == "__main__":
    unittest.main()

