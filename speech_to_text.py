"""Τοπική μετατροπή ελληνικής ομιλίας σε κείμενο, με το μικρόφωνο και το MLX Whisper."""

import os
import subprocess

import mlx_whisper
import numpy as np
import speech_recognition as sr

WHISPER_MODEL = os.environ.get(
    "MARTHA_WHISPER_MODEL", "mlx-community/whisper-medium-mlx-q4"
)
SAMPLE_RATE = 16_000
_MIC_HELP_SHOWN = False


def pick_microphone_index() -> int | None:
    env = os.environ.get("MARTHA_MIC_INDEX")
    if env is not None and env.strip() != "":
        return int(env)
    try:
        names = sr.Microphone.list_microphone_names()
    except OSError:
        return None
    for index, name in enumerate(names):
        lowered = name.casefold()
        if "microphone" in lowered or "μικρόφωνο" in lowered:
            return index
        if "input" in lowered and "speaker" not in lowered:
            return index
    return 0 if names else None


def _open_microphone_privacy_settings() -> None:
    subprocess.run(
        [
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        ],
        check=False,
    )


def _hint_microphone_permission() -> None:
    global _MIC_HELP_SHOWN
    if _MIC_HELP_SHOWN:
        return
    _MIC_HELP_SHOWN = True
    print(
        "\n[Σύστημα] Το μικρόφωνο γράφει σιγή. Στο Mac πήγαινε σε "
        "Ρυθμίσεις → Απόρρητο και ασφάλεια → Μικρόφωνο και ενεργοποίησε "
        "«Terminal» ή «Cursor» (ό,τι τρέχει το agent.py). "
        "Μετά κλείσε και ξανάνοιξε το τερματικό.\n"
        "Για έλεγχο: ./venv/bin/python mic_check.py\n",
        flush=True,
    )
    _open_microphone_privacy_settings()


class SpeechToText:
    def __init__(self, model: str = WHISPER_MODEL, language: str = "el"):
        self.model = model
        self.language = language
        self.device_index = pick_microphone_index()
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.9
        self.recognizer.phrase_threshold = 0.2

    def _microphone(self) -> sr.Microphone:
        kwargs = {"sample_rate": SAMPLE_RATE}
        if self.device_index is not None:
            kwargs["device_index"] = self.device_index
        return sr.Microphone(**kwargs)

    def warmup(self) -> None:
        print(
            "[Σύστημα] Φορτώνω την αναγνώριση ομιλίας. "
            "Την πρώτη φορά κατεβαίνει το μοντέλο, οπότε περίμενε λίγο.",
            flush=True,
        )
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
        print("[Σύστημα] Η αναγνώριση είναι έτοιμη.", flush=True)

    def listen(self, timeout: float = 12, phrase_time_limit: float = 25) -> str:
        """Γράφει μία φράση από το μικρόφωνο και την επιστρέφει ως ελληνικό κείμενο."""
        with self._microphone() as source:
            print("[Ακούω...] Μίλα αμέσως μετά το μήνυμα (όχι πριν).", flush=True)
            self.recognizer.adjust_for_ambient_noise(source, duration=0.35)
            self.recognizer.energy_threshold = max(80, self.recognizer.energy_threshold)
            print(
                f"[Ακούω...] Μίλα τώρα δυνατά. (σιγή > {timeout:.0f} δευτ. = νέα προσπάθεια)",
                flush=True,
            )
            try:
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            except sr.WaitTimeoutError:
                print("[Σύστημα] Δεν άκουσα ομιλία εγκαίρως. Δοκίμασε πιο δυνατά.", flush=True)
                return ""

        samples = _samples_from_audio(audio)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if samples.size < int(SAMPLE_RATE * 0.25):
            return ""
        if peak < 0.001:
            _hint_microphone_permission()
            return ""
        if peak < 0.01:
            print(
                f"[Σύστημα] Πολύ αδύναμος ήχος (ένταση {peak:.3f}). "
                "Ανέβασε την ένταση εισόδου στις Ρυθμίσεις Ήχου.",
                flush=True,
            )
            return ""
        text = self.transcribe(samples)
        if not text:
            print("[Σύστημα] Άκουσα ήχο αλλά δεν κατάλαβα λέξεις. Ξαναπες πιο καθαρά.", flush=True)
        return text

    def transcribe(self, samples: np.ndarray) -> str:
        waveform = np.ascontiguousarray(samples, dtype=np.float32)
        result = mlx_whisper.transcribe(
            waveform,
            path_or_hf_repo=self.model,
            language=self.language,
            verbose=None,
            condition_on_previous_text=False,
            temperature=0.0,
            initial_prompt="Συνομιλία στα ελληνικά.",
        )
        segments = result.get("segments") or []
        if segments and all(segment.get("no_speech_prob", 0) >= 0.6 for segment in segments):
            return ""
        return (result.get("text") or "").strip()


def _samples_from_audio(audio: sr.AudioData) -> np.ndarray:
    raw = audio.get_raw_data(convert_rate=SAMPLE_RATE, convert_width=2)
    if not raw:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


if __name__ == "__main__":
    listener = SpeechToText()
    listener.warmup()
    heard = listener.listen()
    print(heard or "(δεν ακούστηκε κάτι)")
