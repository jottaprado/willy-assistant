"""
Módulo de Síntese de Voz (Text-to-Speech - TTS) do Willy.
Utiliza a API nativa SAPI.SpVoice do Windows com voz neural em Português Brasileiro (Maria).
Executa de forma assíncrona com cancelamento e interrupção imediata.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable


class TTSManager:
    """Gerenciador de fala do Willy com voz nativa do Windows."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._is_speaking = False
        self._stop_requested = False
        # Cada leitura recebe um numero. O worker so age enquanto o seu ainda for o
        # corrente: _stop_requested sozinho nao serve, porque speak_async o zera ao
        # iniciar a leitura seguinte, liberando o worker antigo a falar por cima.
        self._geracao = 0
        self._on_finish_callback: Callable[[], None] | None = None

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            if self._process is not None:
                if self._process.poll() is None:
                    return True
                else:
                    self._is_speaking = False
                    self._process = None
            return self._is_speaking

    @staticmethod
    def escolher_voz(text: str) -> str:
        """Determina se a voz deve ser PT-BR (Maria) ou EN-US (Zira) com base no texto."""
        if not text:
            return "TTS_MS_PT-BR_MARIA_11.0"
        import re
        palavras_en = {"the", "to", "and", "of", "in", "is", "it", "you", "that", "he", "was", "for", "on", "are", "as", "with", "his", "they", "at", "be", "this", "from", "have", "or", "by", "one", "had", "not", "but", "what", "all", "were", "when", "we", "there", "can", "an", "your", "which", "their", "said", "if", "do", "will", "each", "about", "how", "up", "out", "them", "then", "she", "many", "some", "so", "these", "would", "other", "into", "has", "more", "her", "two", "like", "him", "see", "time", "could", "no", "make", "than", "first", "been", "its", "who", "now", "people", "my", "made", "over", "did", "down", "only", "way", "find", "use", "may", "water", "long", "little", "very", "after", "words", "called", "just", "where", "most", "know"}
        tokens = re.findall(r'\b[a-zA-Z]+\b', text.lower())
        if not tokens:
            return "TTS_MS_PT-BR_MARIA_11.0"
        en_matches = sum(1 for t in tokens if t in palavras_en)
        if en_matches / len(tokens) >= 0.25:
            return "TTS_MS_EN-US_ZIRA_11.0"
        return "TTS_MS_PT-BR_MARIA_11.0"

    def _leitura_obsoleta(self, geracao: int) -> bool:
        """A leitura de numero `geracao` foi interrompida ou substituida por outra.

        Checar apenas `_stop_requested` nao basta: `speak_async` o zera ao iniciar a
        leitura seguinte. Sem o numero de geracao, dois cliques seguidos em "Ler" faziam
        o worker antigo acordar do `proc.wait()`, ver returncode != 0 (porque o stop
        matou o processo), concluir que o cscript falhou e recitar o TEXTO VELHO por cima
        da leitura nova, pelo caminho do PowerShell.

        Nao pega o lock: os chamadores dentro do worker ja o seguram.
        """
        return self._stop_requested or self._geracao != geracao

    def speak_async(self, text: str, voice_pref: str = "auto", rate: int = 1,
                    on_finish: Callable[[], None] | None = None,
                    on_done: Callable[[], None] | None = None) -> bool:
        """
        Inicia a leitura assíncrona do texto em voz alta.
        Se já houver uma leitura em andamento, interrompe-a antes de iniciar a nova.
        """
        if not text or not text.strip():
            return False

        self.stop()
        callback_final = on_done or on_finish
        with self._lock:
            self._is_speaking = True
            self._stop_requested = False
            self._geracao += 1
            minha_geracao = self._geracao
            self._on_finish_callback = callback_final

        if voice_pref == "auto":
            selected_voice = self.escolher_voz(text)
            voice_pattern = "EN-US" if "zira" in selected_voice.lower() else "PT-BR"
        else:
            voice_pattern = "PT-BR" if voice_pref.lower().startswith("pt") else "EN-US"

        def _worker():
            pid_tid = f"{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000)}"
            temp_txt_path = os.path.join(tempfile.gettempdir(), f"willy_tts_{pid_tid}.txt")
            temp_vbs_path = os.path.join(tempfile.gettempdir(), f"willy_tts_{pid_tid}.vbs")
            clamped_rate = max(-10, min(10, int(rate)))

            vbs_script = """Dim stream, txt, voice, t, pattern, rate
Set stream = CreateObject("ADODB.Stream")
stream.Open
stream.Type = 2
stream.Charset = "utf-8"
stream.LoadFromFile WScript.Arguments(0)
txt = stream.ReadText
stream.Close

pattern = WScript.Arguments(1)
rate = CInt(WScript.Arguments(2))

Set voice = CreateObject("SAPI.SpVoice")
For Each t In voice.GetVoices
    If InStr(1, t.Id, pattern, 1) > 0 Then
        Set voice.Voice = t
        Exit For
    End If
Next
voice.Rate = rate
voice.Speak txt
"""
            try:
                with self._lock:
                    if self._stop_requested:
                        return

                with open(temp_txt_path, "w", encoding="utf-8") as f:
                    f.write(text.strip())

                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                # Tenta executar via cscript (latência ultrabaixa < 50ms)
                cscript_success = False
                if sys.platform == "win32":
                    try:
                        with open(temp_vbs_path, "w", encoding="utf-8") as f:
                            f.write(vbs_script)

                        with self._lock:
                            if self._leitura_obsoleta(minha_geracao):
                                return
                            proc = subprocess.Popen(
                                ["cscript", "//nologo", temp_vbs_path, temp_txt_path, voice_pattern, str(clamped_rate)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                startupinfo=startupinfo,
                                creationflags=subprocess.CREATE_NO_WINDOW
                            )
                            self._process = proc

                        proc.wait()
                        with self._lock:
                            cscript_success = (proc.returncode == 0) and not self._leitura_obsoleta(minha_geracao)
                    except (OSError, ValueError):
                        cscript_success = False

                # Fallback para PowerShell caso cscript falhe ou não esteja disponível
                if not cscript_success:
                    with self._lock:
                        if self._leitura_obsoleta(minha_geracao):
                            return

                    # AUD-052: Em strings literais simples ('...') do PowerShell, apóstrofos no
                    # caminho temporário (ex.: C:\Users\D'Angelo\...) devem ser dobrados ('').
                    temp_txt_escaped = temp_txt_path.replace("'", "''")
                    voice_pattern_escaped = voice_pattern.replace("'", "''")
                    ps_script = f"""
$txt = [System.IO.File]::ReadAllText('{temp_txt_escaped}', [System.Text.Encoding]::UTF8)
$v = New-Object -ComObject SAPI.SpVoice
foreach ($t in $v.GetVoices()) {{
    if ($t.Id -like "*{voice_pattern_escaped}*") {{
        $v.Voice = $t
        break
    }}
}}
$v.Rate = {clamped_rate}
$v.Speak($txt)
"""
                    with self._lock:
                        if self._leitura_obsoleta(minha_geracao):
                            return
                        proc = subprocess.Popen(
                            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            startupinfo=startupinfo,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                        )
                        self._process = proc

                    proc.wait()

            except Exception as e:  # noqa: BLE001 — fronteira de thread worker de síntese de voz
                print(f"[TTSManager] Erro na leitura de voz: {e}", file=sys.stderr)
            finally:
                with self._lock:
                    # So limpa se ainda formos a leitura corrente: limpar o _process de
                    # uma leitura mais nova a tornaria impossivel de parar.
                    if self._geracao == minha_geracao:
                        self._is_speaking = False
                        self._process = None
                for p in (temp_txt_path, temp_vbs_path):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError as e:
                        print(f"[TTSManager] Aviso ao remover arquivo temporário ({p}): {e!r}", file=sys.stderr)

                with self._lock:
                    stopped = self._leitura_obsoleta(minha_geracao)

                if not stopped and callback_final:
                    try:
                        callback_final()
                    except Exception as e:  # noqa: BLE001 — fronteira de callback_final externo
                        print(f"[TTSManager] Erro ao executar callback final de TTS: {e!r}", file=sys.stderr)

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def stop(self) -> None:
        """Interrompe imediatamente qualquer leitura em andamento."""
        with self._lock:
            self._stop_requested = True
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.kill()
                except Exception as e:  # noqa: BLE001 — fronteira de encerramento de processo externo
                    print(f"[TTSManager] Aviso ao encerrar processo TTS: {e!r}", file=sys.stderr)
                self._process = None
            self._is_speaking = False
