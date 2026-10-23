"""Τοπική εκφώνηση ελληνικού κειμένου με τη φωνή Melina (Enhanced) του macOS."""

import os
import re
import subprocess
import unicodedata

VOICE = os.environ.get("MARTHA_VOICE", "Melina (Enhanced)")


class TextToSpeech:
    def __init__(self, voice: str = VOICE, enabled: bool = True):
        self.voice = voice
        self.enabled = enabled

    def speak(self, text: str) -> None:
        clean = clean_for_speech(text)
        if not clean:
            return
        print(f"\n[Μάρθα]: {clean}", flush=True)
        if not self.enabled:
            return
        completed = subprocess.run(
            ["say", "-v", self.voice, clean],
            check=False,
        )
        if completed.returncode != 0:
            print(
                f"[Σύστημα] Η φωνή «{self.voice}» δεν μπόρεσε να μιλήσει. "
                "Στο Mac είναι διαθέσιμη ως Melina (Enhanced) ή Melina (Ελληνικά).",
                flush=True,
            )


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
