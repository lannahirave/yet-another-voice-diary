# Voice diary — архітектура і схема БД

Desktop-застосунок для голосових нотаток, що працює як щоденник розмов, голосова адресна книга і система реідентифікації мовців.

---

## Вимоги

1. **Щоденник розмов** — записує сесії, перетворює мовлення в текст і зберігає це як історію, по якій можна шукати.
2. **Голосова контактна книга** — розрізняє мовців, впізнає знайомих людей за voiceprint і накопичує їх профілі.
3. **Система з "невизначеними мовцями"** — якщо когось не впізнано, такий мовець потрапляє в окрему чергу, де ти вручну маппуєш його на існуючу або нову людину.
4. **Near-real-time** — результати з'являються поступово під час запису (за паузами/утерансами), а не тільки після завершення сесії.
5. **Гнучка архітектура** — ASR/diarization/identification-компоненти можна міняти без переписування всього застосунку.
6. **Мультимовний сценарій** — фокус на українській і українсько-англійському IT code-mixing у межах тієї самої розмови.

---

## Архітектура: 6 шарів

### Шар 1 — Audio layer

Мікрофон → VAD → utterance chunking.

VAD (Voice Activity Detection) нарізає потік на утеренси по паузах, щоб конвеєр міг обробляти шматки в реальному часі. Рекомендований варіант — **Silero VAD**: легкий, точний, працює офлайн.

### Шар 2 — Provider bus (pluggable)

Серцевина гнучкості. Кожен з трьох компонентів живе за інтерфейсом:

```python
class ASRProvider(Protocol):
    def transcribe(self, audio: np.ndarray, language_hint: str) -> Utterance: ...

class DiarizationProvider(Protocol):
    def segment(self, audio: np.ndarray) -> list[Segment]: ...

class EmbeddingProvider(Protocol):
    def embed(self, audio: np.ndarray) -> np.ndarray: ...
```

Провайдери:

| Компонент | Варіанти |
|---|---|
| ASR | Whisper large-v3, Faster-Whisper, Deepgram API |
| Diarization | PyAnnote 3.x, NVIDIA Streaming Sortformer |
| Speaker embedding | ECAPA-TDNN, WavLM Large, TitaNet |

Для мультимовності і code-mixing: `whisper-large-v3` або `faster-whisper` з `language=None` (автодетект по утерансу). Вони добре справляються з UK/EN mix.

### Шар 3 — Pipeline engine (near-real-time)

Per-utterance loop. На кожен чанк аудіо:

```
аудіо-чанк → транскрибувати → виділити сегмент → отримати embedding → emit event → UI
```

Архітектурно — `asyncio` або worker thread з черговою шиною (EventEmitter / `asyncio.Queue`). UI підписується на події і апендить рядки в реальному часі без очікування кінця сесії.

Поточний компроміс для діаризації:

- `PyAnnote` і `Sortformer` живуть за однаковим контрактом `segment(audio)`
- навіть streaming Sortformer зараз запускається **не** на live chunk-ах, а на вже закритій VAD-репліці
- це спрощує pluggable architecture, але не дає повного streaming-потенціалу Sortformer у цій версії

### Шар 4 — Speaker identity resolver

Порівнює новий embedding з базою через косинусне сходство. Поріг ~0.82 (залежить від моделі).

Три гілки виходу:

- **Known** → прикріпити утеренс до існуючого контакту
- **Unknown** → покласти в `unknown_queue` (ручне розв'язання)
- **New** → створити заглушку контакту

### Шар 5 — Storage layer

- **SQLite** для всього реляційного (сесії, утеренси, контакти)
- **FAISS** або `sqlite-vss` для пошуку по векторах (при > 500 контактів)
- **FTS5** (вбудований у SQLite) для повнотекстового пошуку по транскриптах

### Шар 6 — UI layer

**Tauri** (рекомендовано) або Electron. Tauri краще: менше пам'яті, Rust backend, менший бінарник.

React frontend слухає WebSocket або IPC-канал від pipeline і рендерить:

- Live transcript (поточна сесія, рядки з'являються по мірі обробки)
- Session timeline (пошук по історії)
- Contact book (voiceprint-профілі)
- Unknown queue (невирішені мовці)

---

## Порядок побудови

Починай із заглушок. Провайдери за інтерфейсом → конвеєр з фейковими даними → UI що відображає потік. Потім підключаєш реальні моделі по одній. Так ніколи не зависнеш на інтеграції кількох складних компонентів одночасно.

---

## Схема БД

### Таблиці

#### `sessions`

| Колонка | Тип | Опис |
|---|---|---|
| `id` | `TEXT PK` | UUID сесії |
| `title` | `TEXT` | Назва (авто або задана вручну) |
| `started_at` | `INTEGER` | Unix timestamp початку |
| `ended_at` | `INTEGER` | Unix timestamp кінця |
| `notes` | `TEXT` | Вільний текст |
| `language_hint` | `TEXT` | Підказка для ASR (`uk`, `en`, `null`) |

#### `utterances`

| Колонка | Тип | Опис |
|---|---|---|
| `id` | `TEXT PK` | UUID утеренсу |
| `session_id` | `TEXT FK` | → sessions |
| `started_ms` | `INTEGER` | Початок у мілісекундах від старту сесії |
| `ended_ms` | `INTEGER` | Кінець у мілісекундах |
| `transcript` | `TEXT` | Текст |
| `language` | `TEXT` | Detected language (`uk`, `en`, …) |
| `confidence` | `REAL` | ASR confidence score |
| `speaker_segment_id` | `TEXT FK` | → speaker_segments |

#### `speaker_segments`

Найважливіша таблиця для re-ID.

| Колонка | Тип | Опис |
|---|---|---|
| `id` | `TEXT PK` | UUID |
| `session_id` | `TEXT FK` | → sessions |
| `contact_id` | `TEXT FK` | → contacts (NULL поки не вирішено) |
| `status` | `TEXT` | `identified` / `unknown` / `rejected` |
| `embedding` | `BLOB` | float32 вектор (192–512 d) |
| `sim_score` | `REAL` | Косинусне сходство на момент авто-ID |
| `reviewed_at` | `INTEGER` | Коли людина підтвердила / відхилила |

#### `contacts`

| Колонка | Тип | Опис |
|---|---|---|
| `id` | `TEXT PK` | UUID |
| `name` | `TEXT` | Ім'я |
| `notes` | `TEXT` | Вільний текст |
| `created_at` | `INTEGER` | Unix timestamp |

#### `voice_profiles`

Один контакт може мати кілька профілів (різні мікрофони, різна якість).

| Колонка | Тип | Опис |
|---|---|---|
| `id` | `TEXT PK` | UUID |
| `contact_id` | `TEXT FK` | → contacts |
| `embedding` | `BLOB` | float32 вектор |
| `quality_score` | `REAL` | Якість профілю (0–1) |
| `recorded_at` | `INTEGER` | Unix timestamp |
| `source_session_id` | `TEXT FK` | З якої сесії взято |

При реідентифікації береться профіль з `MAX(quality_score)` або середнє — залежно від стратегії.

#### `unknown_queue`

| Колонка | Тип | Опис |
|---|---|---|
| `id` | `TEXT PK` | UUID |
| `speaker_segment_id` | `TEXT FK` | → speaker_segments |
| `created_at` | `INTEGER` | Коли потрапив у чергу |
| `resolved_contact_id` | `TEXT FK` | → contacts (NULL до вирішення) |
| `resolved_at` | `INTEGER` | Коли вирішено вручну |

Дозволяє в UI показати "X невирішених" без джойну по всіх сегментах.

### Зв'язки

```
sessions      ||--o{  utterances        : contains
sessions      ||--o{  speaker_segments  : has
speaker_segments ||--o{  utterances     : groups
contacts      ||--o{  speaker_segments  : identified_as
contacts      ||--o{  voice_profiles    : owns
voice_profiles }o--|| sessions          : sourced_from
speaker_segments ||--o| unknown_queue   : queued_as
```

### Повнотекстовий пошук

```sql
CREATE VIRTUAL TABLE utterances_fts
USING fts5(transcript, content='utterances', content_rowid='rowid');
```

Пошук по всій історії розмов:

```sql
SELECT u.session_id, u.started_ms, u.transcript, c.name
FROM utterances_fts f
JOIN utterances u ON u.rowid = f.rowid
LEFT JOIN speaker_segments ss ON ss.id = u.speaker_segment_id
LEFT JOIN contacts c ON c.id = ss.contact_id
WHERE utterances_fts MATCH 'kubernetes OR k8s'
ORDER BY rank;
```

### Векторний пошук (реідентифікація)

Для невеликих баз (< 500 контактів) — косинус прямо в Python:

```python
import numpy as np

def find_contact(new_emb: np.ndarray, profiles: list[dict], threshold=0.82):
    best_score, best_id = 0.0, None
    for p in profiles:
        stored = np.frombuffer(p["embedding"], dtype=np.float32)
        score = np.dot(new_emb, stored) / (np.linalg.norm(new_emb) * np.linalg.norm(stored))
        if score > best_score:
            best_score, best_id = score, p["contact_id"]
    if best_score >= threshold:
        return best_id, best_score
    return None, best_score
```

При > 500 контактів — переносимо пошук у FAISS, SQLite залишається source of truth.

---

## Вибір моделей

| Ціль | Рекомендація |
|---|---|
| Максимальна якість embedding | WavLM Large + fine-tune |
| Баланс швидкість / якість | ECAPA-TDNN (SpeechBrain) |
| Готовий pipeline з діаризацією | PyAnnote 3.x |
| Другий локальний backend діаризації | NVIDIA Streaming Sortformer 4spk v2.1 |
| Edge / продакшн | TitaNet (NeMo) |
| Мультимовність | WavLM або Wav2Vec2-large-xlsr |

### Швидкий старт — ECAPA-TDNN через SpeechBrain

```python
from speechbrain.inference import SpeakerRecognition

model = SpeakerRecognition.from_hdf5("speechbrain/spkrec-ecapa-voxceleb")
embedding = model.encode_batch(audio_tensor)  # → (1, 192) float32
```

### PyAnnote — діаризація + embedding разом

```python
from pyannote.audio import Pipeline, Model

pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
emb_model = Model.from_pretrained("pyannote/embedding")
```

### TitaNet через NVIDIA NeMo

```python
import nemo.collections.asr as nemo_asr

model = nemo_asr.models.EncDecSpeakerLabelModel.from_pretrained(
    "nvidia/speakerverification_en_titanet_large"
)
```
