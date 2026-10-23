import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.parse
import urllib.request

from ddgs import DDGS
from openai import OpenAI

from prompts import SYSTEM_PROMPTS
from speech_to_text import SpeechToText
from text_to_speech import TextToSpeech

# ==========================================
# 1. ΒΑΣΗ ΔΕΔΟΜΕΝΩΝ (Μνήμη χωρίς κόστος)
# ==========================================
DB_FILE = os.environ.get("MARTHA_DB", "agent_memory.db")
BASE_URL = os.environ.get("MARTHA_BASE_URL", "http://127.0.0.1:1234/v1")
PREFERRED_MODEL = os.environ.get("MARTHA_MODEL", "llama-krikri-8b-instruct")
TOOL_NAMES = {"web_search", "save_memory", "recall_memory"}


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory
           (id INTEGER PRIMARY KEY, key TEXT UNIQUE, fact TEXT)"""
    )
    conn.commit()
    conn.close()


def memory_block() -> str:
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("SELECT key, fact FROM memory ORDER BY id").fetchall()
    conn.close()
    if not rows:
        return ""
    lines = "\n".join(f"- {key}: {fact}" for key, fact in rows)
    return (
        "\n\nΑΥΤΑ ΘΥΜΑΣΑΙ ΗΔΗ ΓΙΑ ΤΟΝ ΧΡΗΣΤΗ "
        "(μην τα ξανααποθηκεύσεις αν δεν άλλαξαν):\n"
        + lines
    )


# ==========================================
# 2. ΕΡΓΑΛΕΙΑ (Tools)
# ==========================================
def web_search(query: str) -> str:
    print(f"\n[Εργαλείο] Αναζήτηση στο web για: {query}...", flush=True)
    query = (query or "").strip()
    if not query:
        return "Η αναζήτηση ήταν κενή."
    forecast = live_weather(query)
    if forecast is not None:
        return json.dumps([forecast], ensure_ascii=False)
    try:
        results = DDGS(timeout=12).text(query, region="gr-el", max_results=3)
    except Exception:
        try:
            results = DDGS(timeout=12).text(query, max_results=3)
        except Exception as exc:
            return f"Η αναζήτηση απέτυχε: {exc}"
    if not results:
        return "Δεν βρέθηκαν αποτελέσματα."
    compact = []
    for item in results:
        compact.append(
            {
                "title": item.get("title", ""),
                "body": (item.get("body") or "")[:500],
                "url": item.get("href") or item.get("url") or "",
            }
        )
    return json.dumps(compact, ensure_ascii=False)


def save_memory(key: str, fact: str) -> str:
    key = (key or "").strip()
    fact = (fact or "").strip()
    if not key or not fact:
        return "Δεν αποθηκεύτηκε, γιατί έλειπε το κλειδί ή η πληροφορία."
    print(f"\n[Εργαλείο] Αποθήκευση μνήμης -> {key}: {fact}", flush=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("REPLACE INTO memory (key, fact) VALUES (?, ?)", (key, fact))
    conn.commit()
    conn.close()
    return f"Η πληροφορία για {key} αποθηκεύτηκε."


def recall_memory(key: str) -> str:
    print(f"\n[Εργαλείο] Ανάκληση μνήμης για -> {key}", flush=True)
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT fact FROM memory WHERE key LIKE ?",
        (f"%{(key or '').strip()}%",),
    ).fetchone()
    conn.close()
    return row[0] if row else "Δεν βρέθηκε μνήμη για αυτό το θέμα."


_WEATHER_STOPWORDS = {
    "καιρος", "καιρο", "σημερα", "αυριο", "τωρα", "θερμοκρασια", "βροχη",
    "weather", "forecast", "στην", "στη", "στο", "στον", "την", "τον", "για",
    "τι", "κανει", "εχει", "απο", "με", "το", "ο", "η", "θα", "μου", "μας",
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return stripped.replace("ς", "σ")


_WEATHER_STOPWORDS = {_fold(word) for word in _WEATHER_STOPWORDS}


def _weather_phrase(code: int) -> str:
    if code == 0:
        return "αίθριος"
    if code in (1, 2):
        return "σχεδόν αίθριος"
    if code == 3:
        return "συννεφιασμένος"
    if code in (45, 48):
        return "με ομίχλη"
    if 51 <= code <= 67:
        return "με βροχή"
    if 71 <= code <= 77:
        return "με χιόνι"
    if 80 <= code <= 82:
        return "με μπόρες"
    if code >= 95:
        return "με καταιγίδα"
    return "άστατος"


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "martha-assistant"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode())


def live_weather(query: str) -> dict | None:
    """Επιστρέφει τον τωρινό καιρό όταν η ερώτηση είναι για καιρό, αλλιώς τίποτα."""
    if not re.search(r"καιρ|θερμοκρασ|βροχ|weather", query, re.IGNORECASE):
        return None
    tokens = re.findall(r"[^\W\d_]+", query, flags=re.UNICODE)
    place = " ".join(
        token for token in tokens if _fold(token) not in _WEATHER_STOPWORDS
    )
    if not place:
        return None
    try:
        geo = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode(
                {"name": place, "count": 1, "language": "el", "format": "json"}
            )
        )
        match = (geo.get("results") or [None])[0]
        if not match:
            return None
        forecast = _get_json(
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": match["latitude"],
                    "longitude": match["longitude"],
                    "current": "temperature_2m,weather_code,wind_speed_10m",
                    "timezone": "auto",
                }
            )
        )
        current = forecast["current"]
        name = match.get("name") or place
        summary = (
            f"Τώρα στην πόλη {name}: {_weather_phrase(int(current['weather_code']))}, "
            f"{round(current['temperature_2m'])} βαθμοί, "
            f"άνεμος {round(current['wind_speed_10m'])} χιλιόμετρα την ώρα."
        )
        return {"title": f"Τρέχων καιρός, {name}", "body": summary, "url": "https://open-meteo.com/"}
    except Exception:
        return None


_MEMORY_STOPWORDS = {
    _fold(word)
    for word in (
        "χρήστης", "είπε", "είπα", "είπες", "γεια", "κατάσταση", "κουβέντα",
        "αρχική", "αρχικό", "συζήτηση", "ρώτησε", "ρώτησα", "ρώτησες", "μνήμη",
        "σήμερα", "κάνεις", "κάνω", "είμαι", "είσαι", "πολύ", "καλά",
        "χαιρετισμός", "πρώτος", "όνομα", "στοιχείο", "λεπτομέρεια",
    )
}


def grounded_in_user_words(arguments: dict, user_text: str) -> bool:
    """Αποθηκεύει μνήμη μόνο αν ένα συγκεκριμένο στοιχείο υπάρχει στα λόγια του χρήστη."""
    user = _fold(user_text)
    blob = _fold(f"{arguments.get('key', '')} {arguments.get('fact', '')}")
    words = re.findall(r"[0-9a-zα-ω]{4,}", blob)
    content = [word for word in words if word not in _MEMORY_STOPWORDS]
    return any(word[:4] in user for word in content)


def run_tool(name: str, arguments: dict) -> str:
    if name == "web_search":
        return web_search(arguments.get("query", ""))
    if name == "save_memory":
        return save_memory(arguments.get("key", ""), arguments.get("fact", ""))
    if name == "recall_memory":
        return recall_memory(arguments.get("key", ""))
    return f"Άγνωστο εργαλείο: {name}"


def parse_tool_calls(text: str) -> tuple[list[tuple[str, dict]], str]:
    """Ξεχωρίζει τα JSON εργαλεία από τον λόγο που πρέπει να ακουστεί."""
    calls: list[tuple[str, dict]] = []
    spoken_parts: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "{":
            end = _matching_brace(text, index)
            if end != -1:
                call = _parse_call(text[index:end])
                if call is not None:
                    calls.append(call)
                    index = end
                    continue
        spoken_parts.append(text[index])
        index += 1
    spoken = " ".join("".join(spoken_parts).split())
    return calls, spoken


def _parse_call(chunk: str) -> tuple[str, dict] | None:
    normalized = chunk.replace("“", '"').replace("”", '"')
    try:
        data = json.loads(normalized)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("tool") or data.get("name")
    if name not in TOOL_NAMES:
        return None
    arguments = data.get("arguments") or data.get("args") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    for field in ("query", "key", "fact"):
        if field in data and field not in arguments:
            arguments[field] = data[field]
    return name, arguments


def _matching_brace(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def is_exit(text: str) -> bool:
    normalized = text.strip().lower().strip(".!… ")
    return normalized in {"τέλος", "έξοδος", "εξοδος", "αντίο", "αντιο", "stop", "exit"}


def _microphone_help() -> str:
    if sys.platform == "darwin":
        return (
            "Δώσε άδεια στο Terminal από Ρυθμίσεις > Απόρρητο και ασφάλεια > Μικρόφωνο."
        )
    if sys.platform == "win32":
        return (
            "Στις Windows άνοιξε Ρυθμίσεις > Απόρρητο και ασφάλεια > Μικρόφωνο "
            "και ενεργοποίησε την πρόσβαση για εφαρμογές επιφάνειας εργασίας."
        )
    return (
        "Στο Linux έλεγξε τη συσκευή εισόδου από τις ρυθμίσεις ήχου ή με "
        "«pavucontrol» και βεβαιώσου ότι δεν είναι κλειδωμένη σε σιγή."
    )


def resolve_model(client: OpenAI) -> str:
    try:
        model_ids = [model.id for model in client.models.list().data]
    except Exception as exc:
        raise SystemExit(
            "Το LM Studio δεν απαντά στο http://127.0.0.1:1234. "
            "Άνοιξέ το, φόρτωσε το Krikri και ξεκίνα τον τοπικό server."
        ) from exc
    if PREFERRED_MODEL in model_ids:
        return PREFERRED_MODEL
    for model_id in model_ids:
        if "krikri" in model_id.lower():
            return model_id
    chat_ids = [model_id for model_id in model_ids if "embed" not in model_id.lower()]
    if chat_ids:
        print(f"[Σύστημα] Χρησιμοποιώ το μοντέλο {chat_ids[0]}.", flush=True)
        return chat_ids[0]
    return PREFERRED_MODEL


# ==========================================
# 3. ΠΡΑΚΤΟΡΑΣ
# ==========================================
class KrikriAgent:
    def __init__(self, speak_aloud: bool = True):
        self.client = OpenAI(base_url=BASE_URL, api_key="lm-studio")
        self.model_name = resolve_model(self.client)
        self.stt = SpeechToText()
        self.tts = TextToSpeech(enabled=speak_aloud)
        self.messages = [{"role": "system", "content": SYSTEM_PROMPTS["voice"] + memory_block()}]

    def refresh_system(self) -> None:
        self.messages[0] = {
            "role": "system",
            "content": SYSTEM_PROMPTS["voice"] + memory_block(),
        }

    def listen(self) -> str:
        text = self.stt.listen()
        if text:
            print(f"\n[Εσύ]: {text}", flush=True)
        return text

    def read_text(self) -> str:
        try:
            return input("\n[Εσύ]: ").strip()
        except EOFError:
            return "τέλος"

    def speak(self, text: str) -> None:
        self.tts.speak(text)

    def process_turn(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        spoken = ""
        for _ in range(3):
            content = self._complete()
            if content is None:
                return
            calls, spoken = parse_tool_calls(content)
            self.messages.append({"role": "assistant", "content": content})
            if not calls:
                self.speak(spoken or "Συγγνώμη, δεν το έπιασα. Πες το μου άλλη μια φορά.")
                return

            notes = []
            needs_answer = False
            saved = False
            for name, arguments in calls:
                if name == "save_memory" and not grounded_in_user_words(arguments, user_text):
                    print(
                        "\n[Εργαλείο] Δεν αποθηκεύτηκε, γιατί δεν το είπε ο χρήστης.",
                        flush=True,
                    )
                    continue
                result = run_tool(name, arguments)
                if name == "save_memory":
                    saved = True
                    self.refresh_system()
                else:
                    needs_answer = True
                    notes.append(f"{name}: {result}")

            if not needs_answer:
                if spoken:
                    self.speak(spoken)
                elif saved:
                    self.speak("Το κράτησα στο μυαλό μου.")
                else:
                    self.speak("Πες το μου άλλη μια φορά, δεν το κράτησα.")
                return

            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        "Αυτά επέστρεψαν τα εργαλεία. Απάντησε τώρα σύντομα και φυσικά "
                        "στα ελληνικά, χωρίς JSON και χωρίς να πεις ότι έψαξες. "
                        "Αν υπάρχει θερμοκρασία, πες τον αριθμό όπως σου δίνεται.\n"
                        + "\n".join(notes)
                    ),
                }
            )
        self.speak(spoken or "Δεν τα κατάφερα να το βρω αυτή τη στιγμή.")

    def _complete(self) -> str | None:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.messages,
                temperature=0.6,
                max_tokens=280,
            )
        except Exception as exc:
            print(f"\n[Σύστημα] Το μοντέλο δεν απάντησε: {exc}", flush=True)
            self.speak("Δεν μπορώ να φτάσω το μοντέλο. Κοίτα αν το LM Studio τρέχει.")
            return None
        return (response.choices[0].message.content or "").strip()


# ==========================================
# 4. ΕΚΤΕΛΕΣΗ (Main Loop)
# ==========================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Μάρθα, τοπική ελληνική βοηθός")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Πληκτρολόγησε αντί να μιλήσεις στο μικρόφωνο",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Δείξε τις απαντήσεις στην οθόνη χωρίς φωνητική εκφώνηση",
    )
    args = parser.parse_args()

    init_db()
    agent = KrikriAgent(speak_aloud=not args.quiet)
    print(f"[Σύστημα] Μοντέλο: {agent.model_name}", flush=True)

    if args.text:
        print("[Σύστημα] Λειτουργία πληκτρολογίου. Γράψε «τέλος» για έξοδο.", flush=True)
    else:
        print(
            "[Σύστημα] Αν δεν σε ακούει, τρέξε πρώτα: python speech_to_text.py",
            flush=True,
        )
        try:
            agent.stt.warmup()
        except Exception as exc:
            print(f"[Σύστημα] Η αναγνώριση ομιλίας δεν ξεκίνησε: {exc}", flush=True)
            sys.exit(1)
        agent.speak("Γεια σου. Σε ακούω.")

    while True:
        try:
            if args.text:
                user_input = agent.read_text()
            else:
                user_input = agent.listen()
        except KeyboardInterrupt:
            print("\n[Σύστημα] Διακοπή.", flush=True)
            break
        except OSError as exc:
            print(f"\n[Σύστημα] Πρόβλημα με το μικρόφωνο: {exc}", flush=True)
            print(_microphone_help(), flush=True)
            break

        if not user_input:
            continue
        if is_exit(user_input):
            agent.speak("Τα λέμε.")
            print("\n[Σύστημα] Απενεργοποίηση.", flush=True)
            break

        try:
            agent.process_turn(user_input)
        except KeyboardInterrupt:
            print("\n[Σύστημα] Διακοπή.", flush=True)
            break


if __name__ == "__main__":
    main()
