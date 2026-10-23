# Martha-AI-assistant

Martha v1.2 — local Greek voice assistant for macOS, Linux and Windows: you
talk, a local Whisper backend transcribes, Krikri in LM Studio replies as
Μάρθα, the system voice speaks back. No API keys; optional web search and
SQLite memory.

## Setup (all platforms)

1. In LM Studio, load `llama-krikri-8b-instruct` and start the local server
   (default `http://127.0.0.1:1234/v1`).
2. Create the venv and install dependencies (the requirements file picks the
   right Whisper backend for each OS automatically):

   ```bash
   python -m venv venv
   # macOS / Linux
   source venv/bin/activate
   # Windows (cmd)
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Run Martha:

   ```bash
   # macOS / Linux
   python agent.py          # voice mode (Whisper + TTS)
   python agent.py --text   # type instead of talking
   python agent.py --quiet  # answers on screen only

   # Windows (cmd)
   venv\Scripts\python agent.py
   ```

   If Greek text prints garbled on Windows, run `set PYTHONUTF8=1` first.

## Platform extras

| Part            | macOS                                          | Linux                                                                                     | Windows                                                       |
| --------------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Speech-to-text  | MLX Whisper (`mlx-community/whisper-medium-mlx-q4`) | faster-whisper: CPU int8, or CUDA fp16 if available (`Systran/faster-whisper-medium`) | same as Linux                                                 |
| Text-to-speech  | system `say` with `Melina (Enhanced)`          | `spd-say` → `espeak-ng` → `espeak` (install `speech-dispatcher` or `espeak-ng`)           | system SAPI via pywin32 (Greek `Stefanos`), PowerShell fallback |
| Audio input     | PyAudio (bundled portaudio)                    | install `portaudio19-dev` before `pip install` (`sudo apt install portaudio19-dev`)       | none (PyAudio ships wheels)                                    |

A quick mic/speaker+S2T check on any OS: `python speech_to_text.py`,
and a TTS check: `python text_to_speech.py`.

## Environment variables

- `MARTHA_MODEL`, `MARTHA_BASE_URL`, `MARTHA_DB` — LM Studio model, server URL, memory db.
- `MARTHA_WHISPER_MODEL` — Whisper model for the current platform.
- `MARTHA_VOICE` — override the TTS voice (macOS e.g. `Melina (Enhanced)`;
  Windows a Greek SAPI voice name; Linux a `spd-say` voice such as `el`).
- `MARTHA_MIC_INDEX` — force a microphone device index.
