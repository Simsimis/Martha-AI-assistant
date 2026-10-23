"""Τοπική εκφώνηση ελληνικού κειμένου σε macOS, Linux και Windows.

macOS: η ενσωματωμένη εντολή «say» με τη φωνή Melina. Windows: ο συνθέτης
SAPI μέσω pywin32, με εναλλακτική το PowerShell System.Speech όταν λείπει το
pywin32. Linux: spd-say (speech-dispatcher), με εναλλακτικά espeak-ng, espeak.
"""

import base64
import os
import re
import shutil
import subprocess
import sys
import unicodedata

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
VOICE = os.environ.get("MARTHA_VOICE", "Melina (Enhanced)" if IS_MACOS else "")


class TextToSpeech:
    def __init__(self, voice: str = VOICE, enabled: bool = True):
        self.voice = voice
        self.enabled = enabled
        self._sapi = None
        self._linux_engines: list[tuple[str, list[str]]] | None = None
        self._linux_engine_index = 0

    def speak(self, text: str) -> None:
        clean = clean_for_speech(text)
        if not clean:
            return
        print(f"\n[Μάρθα]: {clean}", flush=True)
        if not self.enabled:
            return
        if IS_MACOS:
            self._speak_macos(clean)
        elif IS_WINDOWS:
            self._speak_windows(clean)
        else:
            self._speak_linux(clean)

    def _speak_macos(self, clean: str) -> None:
        completed = subprocess.run(["say", "-v", self.voice, clean], check=False)
        if completed.returncode != 0:
            print(
                f"[Σύστημα] Η φωνή «{self.voice}» δεν μπόρεσε να μιλήσει. "
                "Στο Mac είναι διαθέσιμη ως Melina (Enhanced) ή Melina (Ελληνικά).",
                flush=True,
            )

    def _speak_windows(self, clean: str) -> None:
        if self._speak_sapi(clean) or self._speak_powershell(clean):
            return
        print(
            "[Σύστημα] Δεν μπόρεσε να μιλήσει ο συνθέτης των Windows. Πρόσθεσε "
            "τα ελληνικά από Ρυθμίσεις > Χρόνος και γλώσσα > Γλώσσα και "
            "κατέβασε τη φωνή εκφώνησης «Stefanos».",
            flush=True,
        )

    def _speak_sapi(self, clean: str) -> bool:
        try:
            import win32com.client
        except ImportError:
            return False
        try:
            if self._sapi is None:
                self._sapi = _new_sapi_voice(win32com.client, self.voice)
            self._sapi.Speak(clean)
            return True
        except Exception:
            self._sapi = None
            return False

    def _speak_powershell(self, clean: str) -> bool:
        try:
            completed = subprocess.run(
                [
                    _powershell_binary(),
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    _encoded_command(self.voice, clean),
                ],
                check=False,
                creationflags=NO_WINDOW,
            )
        except OSError:
            return False
        return completed.returncode == 0

    def _speak_linux(self, clean: str) -> None:
        engines = self._available_linux_engines()
        if not engines:
            print(
                "[Σύστημα] Δεν βρέθηκε συνθέτης φωνής. Εγκατέστησε το "
                "«speech-dispatcher» (εντολή spd-say) ή το «espeak-ng».",
                flush=True,
            )
            return
        index = min(self._linux_engine_index, len(engines) - 1)
        try:
            completed = subprocess.run([*engines[index][1], clean], check=False)
        except OSError:
            completed = None
        if completed is None or completed.returncode != 0:
            if index + 1 < len(engines):
                self._linux_engine_index = index + 1
                self._speak_linux(clean)
            else:
                self._linux_engine_index = 0
                print(
                    f"[Σύστημα] Ο συνθέτης «{engines[index][0]}» δεν μπόρεσε να "
                    "μιλήσει. Έλεγξε ότι είναι εγκατεστημένη ελληνική φωνή.",
                    flush=True,
                )

    def _available_linux_engines(self) -> list[tuple[str, list[str]]]:
        if self._linux_engines is None:
            greek = self.voice or "el"
            engines: list[tuple[str, list[str]]] = []
            if shutil.which("spd-say"):
                engines.append(("spd-say", ["spd-say", "-w", "-l", greek]))
            if shutil.which("espeak-ng"):
                engines.append(("espeak-ng", ["espeak-ng", "-v", greek, "-s", "140"]))
            if shutil.which("espeak"):
                engines.append(("espeak", ["espeak", "-v", greek, "-s", "140"]))
            self._linux_engines = engines
        return self._linux_engines


def _new_sapi_voice(client, wanted: str):
    try:
        voice = client.gencache.EnsureDispatch("SAPI.SpVoice")
    except Exception:
        voice = client.Dispatch("SAPI.SpVoice")
    _select_sapi_voice(voice, wanted)
    return voice


def _select_sapi_voice(voice, wanted: str) -> None:
    """Διαλέγει ελληνική φωνή SAPI (π.χ. Microsoft Stefanos) όταν υπάρχει."""
    try:
        tokens = voice.GetVoices()
    except Exception:
        return
    wanted = wanted.strip().lower()
    fallback = None
    for index in range(tokens.Count):
        token = tokens.Item(index)
        try:
            description = token.GetDescription(0).lower()
        except Exception:
            continue
        if wanted:
            if wanted in description:
                voice.Voice = token
                return
            continue
        if "el-gr" in description or "ελλην" in description or "greek" in description:
            fallback = token
            break
    if not wanted and fallback is not None:
        voice.Voice = fallback


def _powershell_binary() -> str:
    return shutil.which("pwsh") or "powershell"


def _encoded_command(voice: str, text: str) -> str:
    wanted = _ps_single(voice or "")
    spoken = _ps_single(text)
    script = (
        "$ErrorActionPreference = 'Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$tts = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$wanted = '{wanted}';"
        "if ($wanted) { try { $tts.SelectVoice($wanted) } catch {} }"
        "else {"
        "$greek = $tts.GetInstalledVoices() |"
        "Where-Object { $_.VoiceInfo.Culture.Name -like 'el*' } |"
        "Select-Object -First 1;"
        "if ($greek) { $tts.SelectVoice($greek.VoiceInfo.Name) }"
        "}"
        f"$tts.Speak('{spoken}')"
    )
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _ps_single(value: str) -> str:
    return value.replace("'", "''")


def clean_for_speech(text: str) -> str:
    """Βγάζει markdown, emojis και κλήσεις εργαλείων, ώστε η φωνή να διαβάζει μόνο λόγο."""
    if not text:
        return ""
    text = _drop_tool_json(text)
    text = text.replace("°C", " βαθμοί").replace("°", " βαθμοί")
    text = re.sub(r"```(?:json|text)?", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"`+", " ", text)
    text = re.sub(r"[#*_~>\[\]]+", " ", text)
    text = "".join(
        char for char in text if unicodedata.category(char) not in {"So", "Cs"}
    )
    text = re.sub(r"\s*\n+\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" \t-•")
    return text


def _drop_tool_json(text: str) -> str:
    kept: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "{":
            end = _matching_brace(text, index)
            chunk = text[index:end] if end != -1 else ""
            if end != -1 and '"tool"' in chunk:
                index = end
                continue
        kept.append(text[index])
        index += 1
    return "".join(kept)


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


if __name__ == "__main__":
    TextToSpeech().speak("Γεια σου. Είμαι η Μάρθα και σε ακούω.")
