-- Личный бот: схема SQLite
-- Принципы:
--   1. Сырое сообщение сохраняется всегда и никогда не удаляется.
--   2. Любая запись ссылается на своё сырое сообщение (raw_id) -> первоисточник поднимается всегда.
--   3. Удаление только мягкое (state), физически ничего не стирается.
--   4. Время хранится в UTC (ISO 8601), локальная зона добавляется на отображении.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- 1. Сырой вход. Пишется до любого разбора.
-- ============================================================
CREATE TABLE inbox_raw (
    id              INTEGER PRIMARY KEY,
    created_at      TEXT    NOT NULL,             -- UTC ISO 8601
    tg_message_id   INTEGER,
    kind            TEXT    NOT NULL,             -- text | voice | photo | forward
    text            TEXT,                         -- исходный текст
    transcript      TEXT,                         -- расшифровка голоса
    file_path       TEXT,                         -- путь к фото/аудио на диске
    parse_state     TEXT    NOT NULL DEFAULT 'new', -- new | parsed | unparsed | manual
    parse_json      TEXT,                         -- что вернул разбор, как есть
    parser          TEXT,                         -- rules | haiku | sonnet | manual
    confidence      REAL,                         -- 0..1, от парсера
    error           TEXT
);
CREATE INDEX idx_raw_state ON inbox_raw(parse_state, created_at);

-- ============================================================
-- 2. Общая шапка записей. Одна строка на факт.
-- ============================================================
CREATE TABLE records (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    profile_id  INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id),
    type        TEXT NOT NULL,                    -- deadline | meal | metric | wish | gift | place | note
    raw_id      INTEGER REFERENCES inbox_raw(id),
    state       TEXT NOT NULL DEFAULT 'active',   -- active | done | archived | deleted
    note        TEXT
);
CREATE INDEX idx_records_type ON records(type, state);
CREATE INDEX idx_records_profile ON records(profile_id, type);

-- ============================================================
-- 3. Сроки и напоминания
--    due_at   — когда событие
--    remind_at— когда написать (по умолчанию = due_at)
-- ============================================================
CREATE TABLE deadlines (
    record_id    INTEGER PRIMARY KEY REFERENCES records(id),
    title        TEXT NOT NULL,
    category     TEXT,                            -- home | health | car | docs | personal | NULL
    due_at       TEXT NOT NULL,
    remind_at    TEXT NOT NULL,
    repeat_rule  TEXT,                            -- NULL | yearly | monthly | every:90d
    repeat_base  TEXT NOT NULL DEFAULT 'calendar', -- calendar (счета, налоги) | done (интервал от факта)
    persist      INTEGER NOT NULL DEFAULT 1,      -- повторять, пока не отреагируешь
    persist_max  INTEGER NOT NULL DEFAULT 2,      -- сколько раз за день (см. overdue_slots)
    sent_count   INTEGER NOT NULL DEFAULT 0,      -- сколько раз уже напомнил
    snooze_count INTEGER NOT NULL DEFAULT 0,      -- сколько раз отложил (метрика поведения)
    closed_at    TEXT
);
CREATE INDEX idx_deadlines_remind ON deadlines(remind_at);

-- ============================================================
-- 4. Еда. Одна строка на приём/блюдо.
-- ============================================================
CREATE TABLE meals (
    record_id   INTEGER PRIMARY KEY REFERENCES records(id),
    eaten_at    TEXT NOT NULL,
    dish        TEXT NOT NULL,
    grams       REAL,
    kcal        REAL,
    protein_g   REAL,
    fat_g       REAL,
    carbs_g     REAL,
    place       TEXT,                             -- дом | столовая | вне дома
    confidence  REAL                              -- оценка модели по фото
);
CREATE INDEX idx_meals_date ON meals(eaten_at);

-- ============================================================
-- 5. Универсальные измерения: вес, состав тела, шаги, пробег, заправки,
--    показания счётчиков. Всё, что "значение + единица + момент".
-- ============================================================
CREATE TABLE metrics (
    record_id  INTEGER PRIMARY KEY REFERENCES records(id),
    measured_at TEXT NOT NULL,
    metric     TEXT NOT NULL,                     -- weight | body_fat | steps | odometer | fuel_rub | water_m3 | kwh
    value      REAL NOT NULL,
    unit       TEXT NOT NULL,                     -- kg | % | шт | км | руб | м3 | кВт·ч
    source     TEXT NOT NULL                      -- ha | telegram | manual
);
CREATE INDEX idx_metrics_series ON metrics(metric, measured_at);

-- ============================================================
-- 6. Вишлист
-- ============================================================
CREATE TABLE wishes (
    record_id     INTEGER PRIMARY KEY REFERENCES records(id),
    title         TEXT NOT NULL,
    price         REAL,
    url           TEXT,
    urgency       TEXT,                           -- сейчас | когда-нибудь
    last_review_at TEXT,                          -- когда бот последний раз спрашивал "актуально?"
    bought_at     TEXT
);

-- ============================================================
-- 7. Люди и подарки
-- ============================================================
CREATE TABLE people (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    birthday  TEXT,                               -- MM-DD, год не обязателен
    relation  TEXT
);

CREATE TABLE gifts (
    record_id   INTEGER PRIMARY KEY REFERENCES records(id),
    person_id   INTEGER REFERENCES people(id),
    idea        TEXT NOT NULL,
    price       REAL,
    url         TEXT,
    occasion    TEXT,                             -- др | нг | без повода
    given_at    TEXT
);

-- ============================================================
-- 8. Места
-- ============================================================
CREATE TABLE places (
    record_id      INTEGER PRIMARY KEY REFERENCES records(id),
    title          TEXT NOT NULL,
    area           TEXT,                          -- район/город
    kind           TEXT,                          -- еда | прогулка | выставка | бар | прочее
    recommended_by TEXT,
    with_whom      TEXT,                          -- один | с Кристиной | компания
    season         TEXT,                          -- любой | лето | зима
    valid_until    TEXT,                          -- для событий с датой окончания
    visited_at     TEXT
);
CREATE INDEX idx_places_unvisited ON places(visited_at);

-- ============================================================
-- 9. Выученные шаблоны разбора. Бот пишет их сам после удачных разборов,
--    чтобы не звать модель на повторяющиеся формулировки.
-- ============================================================
CREATE TABLE parse_patterns (
    id          INTEGER PRIMARY KEY,
    pattern     TEXT NOT NULL,                    -- регулярка или нормализованный шаблон
    target_type TEXT NOT NULL,
    field_map   TEXT NOT NULL,                    -- JSON: какая группа в какое поле
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'learned'   -- learned | manual
);

-- ============================================================
-- 10. Лог обращений к моделям. Нужен, чтобы видеть расход лимита
--     и понимать, где недоделаны правила.
-- ============================================================
CREATE TABLE llm_calls (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL,
    raw_id      INTEGER REFERENCES inbox_raw(id),
    model       TEXT NOT NULL,                    -- haiku | sonnet
    latency_ms  INTEGER,
    ok          INTEGER NOT NULL,                 -- 0/1
    error       TEXT
);

-- ============================================================
-- 12. Висящие уточнения. Пока строка открыта, следующее сообщение
--     трактуется как ответ на неё, а не как новая запись.
--     Ответ принимается любым способом: кнопка, текст, голосовое.
-- ============================================================
CREATE TABLE pending_questions (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL,
    raw_id        INTEGER NOT NULL REFERENCES inbox_raw(id),
    field         TEXT NOT NULL,                  -- какое поле неясно: due_at | protein_g | person | ...
    question      TEXT NOT NULL,                  -- текст вопроса, отправленный в чат
    options_json  TEXT,                           -- варианты для кнопок, если есть
    answer_raw_id INTEGER REFERENCES inbox_raw(id), -- чем ответил (в т.ч. голосовое)
    state         TEXT NOT NULL DEFAULT 'open',   -- open | answered | expired
    expires_at    TEXT NOT NULL,                  -- после этого срока уходит в инбокс
    closed_at     TEXT
);
CREATE INDEX idx_pending_open ON pending_questions(state, created_at);

-- ============================================================
-- 13. Связи между записями. Один факт может породить два объекта
--     (идея подарка + напоминание купить). Типы при этом не смешиваются:
--     каждая запись остаётся в своём разделе, связь их соединяет.
-- ============================================================
CREATE TABLE links (
    id         INTEGER PRIMARY KEY,
    from_id    INTEGER NOT NULL REFERENCES records(id),
    to_id      INTEGER NOT NULL REFERENCES records(id),
    kind       TEXT NOT NULL,                     -- reminder_for | bought_from | event_of
    created_at TEXT NOT NULL
);
CREATE INDEX idx_links_from ON links(from_id);
CREATE INDEX idx_links_to   ON links(to_id);

-- ============================================================
-- 14. Фиксированный словарь категорий. Свободный ввод запрещён:
--     иначе «быт», «Быт» и «бытовое» станут тремя разными категориями.
--     Категория может быть пустой: если тип записи понятен, а категория нет,
--     бот спросит при разборе. Отдельной категории «прочее» нет намеренно —
--     эту роль выполняет инбокс.
-- ============================================================
CREATE TABLE categories (
    code       TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    applies_to TEXT NOT NULL,                     -- для каких типов записей
    active     INTEGER NOT NULL DEFAULT 1
);

INSERT INTO categories (code, title, applies_to) VALUES
    ('home',     'Быт',        'deadline'),
    ('health',   'Здоровье',   'deadline'),
    ('car',      'Авто',       'deadline,metric'),
    ('docs',     'Документы',  'deadline'),
    ('personal', 'Личное',     'deadline');

-- ============================================================
-- 0. Профили. Сейчас пользователь один, но profile_id проставляется
--    везде с первого дня: добавить его потом в живую базу дорого,
--    а держать сейчас — бесплатно.
-- ============================================================
CREATE TABLE profiles (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    tg_user_id INTEGER UNIQUE,
    tz         TEXT NOT NULL DEFAULT 'Europe/Moscow'
);
INSERT INTO profiles (id, name) VALUES (1, 'Максим');

-- ============================================================
-- 15. Настройки. Всё, что может поменяться, живёт здесь, а не в коде.
-- ============================================================
CREATE TABLE settings (
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    PRIMARY KEY (profile_id, key)
);

INSERT INTO settings (profile_id, key, value) VALUES
    (1, 'quiet_from',        '00:00'),   -- бот не пишет
    (1, 'quiet_to',          '09:00'),
    (1, 'kcal_target_min',   '1800'),
    (1, 'kcal_target_max',   '1900'),
    (1, 'protein_target_g',  '120'),
    (1, 'day_boundary',      '04:00'),   -- поздний ужин относится к предыдущему дню
    (1, 'confidence_min',    '0.8'),     -- ниже — спрашивать
    (1, 'inbox_batch',       '5'),       -- сколько накопить до разбора
    (1, 'inbox_max_days',    '14'),      -- или сколько ждать, если не набралось
    (1, 'overdue_slots',     '09:00,19:00'), -- когда напоминать о просроченном
    (1, 'archive_days',      '90'),       -- сколько закрытое лежит в архиве до стирания
    (1, 'photo_keep_days',   '180'),      -- фото еды; бланки анализов хранятся вечно
    (1, 'advice_weekday',    'SU'),       -- когда приходит недельная сводка с советами
    (1, 'advice_min_cases',  '3');        -- меньше однотипных случаев — совет не выдаётся

-- ============================================================
-- 16. История правок. Что было, что стало, когда.
--     Запись никогда не переписывается молча.
-- ============================================================
CREATE TABLE record_edits (
    id          INTEGER PRIMARY KEY,
    record_id   INTEGER NOT NULL REFERENCES records(id),
    edited_at   TEXT NOT NULL,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    source      TEXT NOT NULL DEFAULT 'user'      -- user | system
);
CREATE INDEX idx_edits_record ON record_edits(record_id, edited_at);

-- ============================================================
-- 17. Заметки. Свободный текст без структуры.
--     Удаляются насовсем по команде — не архивируются.
-- ============================================================
CREATE TABLE notes (
    record_id INTEGER PRIMARY KEY REFERENCES records(id),
    text      TEXT NOT NULL,
    pinned    INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- 18. Список покупок. Отдельно от записей: короткий жизненный цикл,
--     высокая оборачиваемость, чистится целиком.
-- ============================================================
CREATE TABLE shopping_items (
    id         INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL DEFAULT 1 REFERENCES profiles(id),
    raw_id     INTEGER REFERENCES inbox_raw(id),
    list       TEXT NOT NULL DEFAULT 'food',      -- food (продукты) | home (домой)
    title      TEXT NOT NULL,
    qty        TEXT,
    added_at   TEXT NOT NULL,
    bought_at  TEXT
);
CREATE INDEX idx_shopping_open ON shopping_items(profile_id, list, bought_at);

-- ============================================================
-- 19. Что посмотреть. Только фильмы. Отдельно от мест: другой контекст.
--     Хранится только то, что сказал пользователь. Год, жанр и прочие
--     факты о фильме не додумываются — модель в них ошибается.
-- ============================================================
CREATE TABLE watchlist (
    record_id      INTEGER PRIMARY KEY REFERENCES records(id),
    title          TEXT NOT NULL,
    where_to_watch TEXT,                          -- кинотеатр, сервис, скачать
    recommended_by TEXT,
    with_whom      TEXT,                          -- один | с Кристиной
    watched_at     TEXT
);
CREATE INDEX idx_watchlist_unwatched ON watchlist(watched_at);

-- ============================================================
-- 11. Версионирование выводов отчётов.
--     Если через полгода вывод изменился — прежний остаётся виден.
-- ============================================================
CREATE TABLE findings (
    id            INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL,
    topic         TEXT NOT NULL,                  -- к какому ряду относится
    statement     TEXT NOT NULL,
    based_on      TEXT,                           -- JSON: период и число точек
    superseded_by INTEGER REFERENCES findings(id),
    reason        TEXT                            -- почему прежний вывод заменён
);
