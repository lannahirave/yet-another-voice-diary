"""Populate the dev SQLite database with the same fixtures as api/mock.ts.

Usage:
    python -X utf8 backend/scripts/seed_dev_db.py

Run from web_app/ directory.
"""
import sys
import os
import uuid

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.config import BackendConfig
from backend.storage.database import Database
from backend.storage.session_repo import SessionRepo
from backend.storage.contact_repo import ContactRepo
from backend.models import Person, RecordingSession, Utterance
import sqlite3
from datetime import datetime, timedelta, timezone


config = BackendConfig.default()
db = Database(config.database)
db.init_schema()


def fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.database.path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def to_epoch(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def seed():
    conn = fresh_conn()
    c_repo = ContactRepo(conn)
    s_repo = SessionRepo(conn)

    # ------ Contacts ------
    contacts_data = [
        ("Олена Ковальчук", ""),
        ("Микола Бойко", ""),
        ("Тарас Щербань", ""),
        ("Іванна Петренко", ""),
        ("Андрій Лисенко", ""),
    ]
    contact_map: dict[str, str] = {}  # name -> id
    for name, notes in contacts_data:
        existing = [c for c in c_repo.list_contacts() if c["name"] == name]
        if existing:
            contact_map[name] = existing[0]["id"]
        else:
            row = c_repo.create_contact(Person(name=name, notes=notes))
            contact_map[name] = row["id"]

    print("Contacts:", list(contact_map.keys()))

    # ------ Sessions ------
    now = datetime.utcnow()
    sessions_data = [
        (
            "Стендап команди продукту",
            now - timedelta(days=1, hours=2),
            timedelta(minutes=18, seconds=34),
            "UK",
            [
                (contact_map["Микола Бойко"], 3000, 9000, "Добре, давайте починати. Олена, що у тебе по бекенду?", "UK"),
                (contact_map["Олена Ковальчук"], 11000, 46000, "По бекенду все добре, вчора задеплоїли нову версію API. Є невелика проблема з rate limiting але вже розбираємось.", "UK"),
                (contact_map["Микола Бойко"], 47000, 51000, "Ясно. Тарасе, як там з фронтом?", "UK"),
                (contact_map["Тарас Щербань"], 52000, 77000, "Закрив три тікети по дашборду. Ще один залишився — там складний edge case.", "UK"),
                (contact_map["Олена Ковальчук"], 78000, 107000, "Щодо edge case — мені здається це пов'язано зі станом після рефреш.", "UK"),
                (contact_map["Тарас Щербань"], 108000, 114000, "Так, було б добре.", "UK"),
                (None, 125000, 164000, "Я хотів би додати — нам треба переглянути документацію до кінця тижня.", "UK"),
            ],
        ),
        (
            "Інтерв'ю з Іванною — UX дослідження",
            now - timedelta(days=2, hours=8),
            timedelta(minutes=43, seconds=11),
            "UK",
            [
                (contact_map["Олена Ковальчук"], 4000, 11000, "Розкажіть як ви зазвичай починаєте свій робочий день.", "UK"),
                (contact_map["Іванна Петренко"], 12000, 62000, "Usually I start by checking messages and planning tasks for the day.", "EN"),
                (contact_map["Олена Ковальчук"], 63000, 102000, "А як ви пріоритизуєте задачі?", "UK"),
                (contact_map["Іванна Петренко"], 109000, 148000, "I use a simple system — urgent vs important matrix, mostly.", "EN"),
            ],
        ),
        (
            "Зустріч з Андрієм по архітектурі",
            now - timedelta(days=3, hours=12),
            timedelta(minutes=32, seconds=7),
            "UK",
            [
                (contact_map["Андрій Лисенко"], 2000, 17000, "Я думаю що нам треба переглянути підхід до мікросервісів.", "UK"),
                (contact_map["Олена Ковальчук"], 18000, 40000, "Погоджуюсь. Поточна архітектура не масштабується добре при великому навантаженні.", "UK"),
                (contact_map["Андрій Лисенко"], 41000, 95000, "Якщо ми перейдемо на event-driven підхід, то latency значно покращиться.", "UK"),
            ],
        ),
    ]

    for title, started, duration, lang_hint, utterances_data in sessions_data:
        # Skip if already seeded
        existing = [s for s in s_repo.list_sessions() if s["title"] == title]
        if existing:
            print(f"Skipping (exists): {title}")
            continue

        # Create session
        sess = RecordingSession(title=title, language_hint=lang_hint)
        row = s_repo.create_session(sess)
        session_id = row["id"]
        ended = started + duration

        conn.execute(
            "UPDATE sessions SET started_at=?, ended_at=? WHERE id=?",
            (to_epoch(started), to_epoch(ended), session_id),
        )
        conn.commit()

        # Create speaker_segments (one per unique contact in this session)
        segment_map: dict[str | None, str] = {}  # contact_id -> segment_id
        for contact_id, *_ in utterances_data:
            if contact_id not in segment_map:
                seg_id = str(uuid.uuid4())
                status = "identified" if contact_id else "unknown"
                conn.execute(
                    "INSERT INTO speaker_segments (id, session_id, contact_id, status) VALUES (?, ?, ?, ?)",
                    (seg_id, session_id, contact_id, status),
                )
                segment_map[contact_id] = seg_id
        conn.commit()

        # Create utterances linked to segments
        for contact_id, start_ms, end_ms, text, language in utterances_data:
            seg_id = segment_map.get(contact_id)
            u = Utterance(
                session_id=session_id,
                started_ms=start_ms,
                ended_ms=end_ms,
                transcript=text,
                language=language,
                confidence=0.92,
                speaker_segment_id=seg_id,
            )
            s_repo.create_utterance(u)

        print(f"Created '{title}' ({len(utterances_data)} utterances)")

    conn.close()
    print("Seed complete.")


if __name__ == "__main__":
    seed()
