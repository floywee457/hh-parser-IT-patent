import requests
import sqlite3
import time
import random
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List
import concurrent.futures
from threading import Lock

# ==================================================
# НАСТРОЙКИ
# ==================================================
PROFESSIONS = [
    'Data Engineer', 'Python разработчик', 'Java разработчик',
    'DevOps инженер', 'Data Scientist', 'Machine Learning Engineer',
    'Backend разработчик', 'Frontend разработчик', 'Fullstack разработчик',
    'Системный аналитик',
    # Рекомендованные популярные
    'Разработчик ПО', 'Специалист по информационной безопасности',
    'Аналитик данных', 'QA инженер', 'Системный администратор',

    # Специфичные для Angels IT
    '1С разработчик', '1С консультант-аналитик',
    'Специалист технической поддержки', 'Linux администратор',
    'Специалист по компьютерному зрению', 'Мобильный разработчик',
    'PHP разработчик'
]

CLIENT_ID = "MUF52QUJ17OB0LH9RQQEFIV5INMT46FM2VK26NFRH9BI2JLPLRP772L4F8B1H3RQ"
CLIENT_SECRET = "K9IINSL93OEQCCHG17QCNM86PBIJ6CJ6QU8QENIUJ8OK4QMLK87K0TD617JSEV1B"
TOKEN_FILE = "hh_token.json"

AREA = 113
PER_PAGE = 100
MAX_PAGES = 3

# Настройки параллельности (умеренные для Windows)
MAX_WORKERS_PAGES = 3  # Потоков для загрузки страниц
MAX_WORKERS_DETAILS = 5  # Потоков для загрузки деталей
RATE_LIMIT_REQUESTS = 8  # Запросов в секунду (безопасно)

# Паузы
PAUSE_BETWEEN_PROFESSIONS = (1, 2)

hh_token = None
conn = None  # Глобальная переменная для БД (нужна в fill_experience_for_existing)


# ==================================================
# ТОКЕН
# ==================================================
def load_token():
    global hh_token
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                hh_token = data.get('access_token')
                return True
        except:
            pass
    return False


def save_token(token):
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'access_token': token}, f)


def get_token():
    global hh_token
    if hh_token:
        return True
    if load_token():
        return True

    for attempt in range(3):
        try:
            resp = requests.post("https://hh.ru/oauth/token", data={
                'grant_type': 'client_credentials',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET
            }, timeout=10)
            if resp.status_code == 200:
                hh_token = resp.json().get('access_token')
                save_token(hh_token)
                return True
        except:
            pass
        time.sleep(2)
    return False


# ==================================================
# RATE LIMITER (ПРОСТАЯ ВЕРСИЯ БЕЗ DEADLOCK)
# ==================================================
class RateLimiter:
    def __init__(self, requests_per_sec=5):
        self.interval = 1.0 / requests_per_sec
        self.last_request_time = 0
        self.lock = Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_request_time = time.time()


rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS)


# ==================================================
# БАЗА ДАННЫХ
# ==================================================
def init_db() -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
    global conn
    conn = sqlite3.connect('hh_vacancies.db', timeout=20)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS vacancies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profession TEXT,
        title TEXT,
        company TEXT,
        city TEXT,
        salary_from INTEGER,
        salary_to INTEGER,
        salary_currency TEXT,
        key_skills TEXT,
        experience TEXT,
        url TEXT UNIQUE,
        published_at TEXT,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active INTEGER DEFAULT 1
    )""")

    try:
        cur.execute("ALTER TABLE vacancies ADD COLUMN experience TEXT")
    except sqlite3.OperationalError:
        pass

    for idx in ['profession', 'published_at', 'salary_from', 'salary_to', 'last_seen', 'is_active']:
        try:
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{idx} ON vacancies({idx})")
        except:
            pass

    cur.execute("""CREATE TABLE IF NOT EXISTS profession_dynamics (
        profession TEXT PRIMARY KEY,
        demand_index REAL,
        avg_ttl_days REAL,
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()
    return conn, cur


# ==================================================
# ЗАГРУЗКА СТРАНИЦ (ПОСЛЕДОВАТЕЛЬНО - СТАБИЛЬНЕЕ)
# ==================================================
def fetch_page_vacancies(profession: str, page: int) -> Optional[List[Dict]]:
    """Загружает одну страницу вакансий"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    if hh_token:
        headers['Authorization'] = f'Bearer {hh_token}'

    rate_limiter.wait()

    for attempt in range(3):
        try:
            date_from = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            date_to = datetime.now().strftime('%Y-%m-%d')

            resp = requests.get("https://api.hh.ru/vacancies", headers=headers, timeout=(10, 30), params={
                "text": profession,
                "area": AREA,
                "per_page": PER_PAGE,
                "page": page,
                "search_field": "name",
                "date_from": date_from,
                "date_to": date_to,
                "order_by": "publication_time"
            })

            if resp.status_code == 200:
                return resp.json().get('items', [])
            elif resp.status_code == 429:
                wait_time = int(resp.headers.get('Retry-After', 5))
                print(f"    ⏳ 429 на странице {page + 1}, ждем {wait_time} сек...")
                time.sleep(wait_time)
                continue
            else:
                print(f"    ⚠️ Страница {page + 1}: статус {resp.status_code}")
                return None
        except Exception as e:
            print(f"    ⚠️ Страница {page + 1}: ошибка - {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                return None
    return None


def fetch_all_vacancies(profession: str, max_pages: int) -> List[Dict]:
    """Загружает все страницы для профессии ПОСЛЕДОВАТЕЛЬНО (стабильнее)"""
    all_items = []

    for page in range(max_pages):
        items = fetch_page_vacancies(profession, page)
        if items:
            all_items.extend(items)
            print(f"    └─ Страница {page + 1}: {len(items)} вакансий")
        else:
            print(f"    └─ Страница {page + 1}: нет вакансий или ошибка")
            # Не прерываем, пробуем следующие страницы

        # Пауза между страницами
        time.sleep(0.5)

    return all_items


# ==================================================
# ЗАГРУЗКА ДЕТАЛЕЙ ВАКАНСИИ (ДЛЯ ПАРАЛЛЕЛЬНОЙ ЗАГРУЗКИ)
# ==================================================
def fetch_and_parse_one(vacancy: Dict, profession: str) -> Optional[Dict]:
    """Загружает детали ОДНОЙ вакансии"""
    try:
        rate_limiter.wait()

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        if hh_token:
            headers['Authorization'] = f'Bearer {hh_token}'

        resp = requests.get(
            f"https://api.hh.ru/vacancies/{vacancy.get('id')}",
            headers=headers,
            timeout=(10, 30)
        )

        if resp.status_code == 429:
            wait_time = int(resp.headers.get('Retry-After', 5))
            time.sleep(wait_time)
            return fetch_and_parse_one(vacancy, profession)

        if resp.status_code != 200:
            return None

        details = resp.json()

        # Проверяем наличие ключевых навыков
        skills_list = details.get('key_skills', [])
        if not skills_list:
            return None

        # Проверяем зарплату
        salary = vacancy.get('salary', {}) or {}
        salary_from = salary.get('from')
        salary_to = salary.get('to')
        if not salary_from and not salary_to:
            return None

        # Формируем строку навыков
        skills = ", ".join([s.get('name', '') for s in skills_list if s.get('name')])

        # Опыт
        experience = vacancy.get('experience', {})
        experience_name = experience.get('name', '') if experience else ''

        return {
            'profession': profession,
            'title': vacancy.get('name', '')[:200],
            'company': vacancy.get('employer', {}).get('name', '')[:200],
            'city': vacancy.get('area', {}).get('name', '')[:100],
            'salary_from': salary_from,
            'salary_to': salary_to,
            'salary_currency': salary.get('currency'),
            'key_skills': skills,
            'experience': experience_name,
            'url': vacancy.get('alternate_url', ''),
            'published_at': vacancy.get('published_at', '')
        }
    except Exception as e:
        return None


def fetch_details_parallel(vacancies: List[Dict], profession: str) -> List[Dict]:
    """Загружает детали всех вакансий ПАРАЛЛЕЛЬНО"""
    if not vacancies:
        return []

    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_DETAILS) as executor:
        future_to_vac = {
            executor.submit(fetch_and_parse_one, vac, profession): vac
            for vac in vacancies
        }

        completed = 0
        for future in concurrent.futures.as_completed(future_to_vac):
            completed += 1
            try:
                result = future.result(timeout=45)
                if result:
                    results.append(result)
            except Exception as e:
                pass

            # Показываем прогресс каждые 50 вакансий
            if completed % 50 == 0:
                print(f"    📊 Прогресс деталей: {completed}/{len(vacancies)}")

    return results


# ==================================================
# СОХРАНЕНИЕ В БД
# ==================================================
def save_or_update_vacancy(cur: sqlite3.Cursor, data: Dict) -> str:
    """Сохраняет или обновляет вакансию в БД"""
    try:
        cur.execute("SELECT id, is_active FROM vacancies WHERE url = ?", (data['url'],))
        row = cur.fetchone()

        if row:
            # Обновляем существующую
            if data.get('experience'):
                cur.execute("""
                    UPDATE vacancies 
                    SET last_seen = CURRENT_TIMESTAMP, 
                        is_active = 1,
                        experience = ?
                    WHERE id = ?
                """, (data['experience'], row[0]))
            else:
                cur.execute("""
                    UPDATE vacancies 
                    SET last_seen = CURRENT_TIMESTAMP, 
                        is_active = 1
                    WHERE id = ?
                """, (row[0],))
            return 'updated'
        else:
            # Новая вакансия
            cur.execute("""INSERT INTO vacancies (
                profession, title, company, city,
                salary_from, salary_to, salary_currency,
                key_skills, experience, url, published_at, last_seen, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1)""", (
                data['profession'], data['title'], data['company'],
                data['city'], data['salary_from'], data['salary_to'],
                data['salary_currency'], data['key_skills'],
                data['experience'], data['url'], data['published_at']
            ))
            return 'new'
    except sqlite3.IntegrityError:
        return 'error'
    except Exception as e:
        return 'error'


def mark_inactive_vacancies(cur: sqlite3.Cursor):
    """Помечает старые вакансии как неактивные"""
    cur.execute("""
        UPDATE vacancies 
        SET is_active = 0 
        WHERE date(last_seen) < date('now', '-7 days')
    """)


def save_logs(status: int, message):
    """Логирование"""
    DateAndTime = datetime.now().strftime("%d.%m.%Y %H:%M")
    with open('logs.txt', 'a', encoding='utf-8') as file:
        if status == 1:
            file.write(f"✅ | {DateAndTime} | Проверено: {message[0]} | Сохранено: {message[1]}\n")
        elif status == 0:
            file.write(f"🚫 | {DateAndTime} | {message}\n")
        else:
            file.write(f"❌ | {DateAndTime} | {message}\n")


# ==================================================
# ДИНАМИКА РЫНКА
# ==================================================
def compute_demand_index(cur: sqlite3.Cursor, profession: str) -> float:
    """Вычисляет индекс спроса"""
    today = datetime.now().date()
    period1_start = today - timedelta(days=14)
    period1_end = today
    period2_start = today - timedelta(days=28)
    period2_end = today - timedelta(days=14)

    cur.execute("""
        SELECT COUNT(*) FROM vacancies
        WHERE profession = ? 
          AND is_active = 1
          AND date(published_at) BETWEEN ? AND ?
    """, (profession, period1_start.isoformat(), period1_end.isoformat()))
    count_recent = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM vacancies
        WHERE profession = ?
          AND is_active = 1
          AND date(published_at) BETWEEN ? AND ?
    """, (profession, period2_start.isoformat(), period2_end.isoformat()))
    count_prev = cur.fetchone()[0]

    if count_prev == 0:
        return 0.0
    return round((count_recent - count_prev) / count_prev, 4)


def compute_avg_ttl(cur: sqlite3.Cursor, profession: str) -> Optional[float]:
    """Среднее время жизни вакансии"""
    cur.execute("""
        SELECT AVG(julianday(last_seen) - julianday(published_at))
        FROM vacancies
        WHERE profession = ?
          AND is_active = 0
          AND last_seen IS NOT NULL
          AND published_at IS NOT NULL
    """, (profession,))
    row = cur.fetchone()
    if row and row[0]:
        return round(row[0], 1)
    return None


def update_profession_dynamics(cur: sqlite3.Cursor):
    """Обновляет динамику по всем профессиям"""
    for prof in PROFESSIONS:
        demand = compute_demand_index(cur, prof)
        ttl = compute_avg_ttl(cur, prof)
        cur.execute("""INSERT OR REPLACE INTO profession_dynamics 
                       (profession, demand_index, avg_ttl_days, calculated_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                    (prof, demand, ttl))


# ==================================================
# ОБНОВЛЕНИЕ EXPERIENCE ДЛЯ СТАРЫХ ЗАПИСЕЙ
# ==================================================
def fill_experience_for_existing(cur: sqlite3.Cursor):
    """Дозаполняет опыт для старых вакансий"""
    cur.execute("SELECT id, url FROM vacancies WHERE experience IS NULL OR experience = ''")
    rows = cur.fetchall()

    if not rows:
        print("\n✅ Все записи уже с experience")
        return

    print(f"\n📋 Заполняем experience для {len(rows)} старых записей...")
    updated = 0

    for idx, (vac_id, url) in enumerate(rows):
        try:
            vac_hh_id = url.split('/')[-1]

            rate_limiter.wait()

            resp = requests.get(
                f"https://api.hh.ru/vacancies/{vac_hh_id}",
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                experience = data.get('experience', {}).get('name', '')
                if experience:
                    cur.execute("UPDATE vacancies SET experience = ? WHERE id = ?", (experience, vac_id))
                    updated += 1

            if (idx + 1) % 50 == 0:
                print(f"  {idx + 1}/{len(rows)} | обновлено: {updated}")
                conn.commit()

            time.sleep(0.1)

        except Exception as e:
            pass

    print(f"  Готово. Обновлено: {updated}/{len(rows)}")


# ==================================================
# ГЛАВНЫЙ ЦИКЛ
# ==================================================
def main():
    global conn

    print("=" * 60)
    print("🚀 ПАРСЕР ВАКАНСИЙ HH.RU (СТАБИЛЬНАЯ ВЕРСИЯ)")
    print("=" * 60)
    print(f"⚙️ Настройки: страницы последовательно, детали в {MAX_WORKERS_DETAILS} потоков")
    print(f"⚙️ Лимит запросов: {RATE_LIMIT_REQUESTS}/сек")
    print("=" * 60)

    if not get_token():
        print("❌ Не удалось получить токен")
        save_logs(-1, "Не удалось получить токен")
        return

    print("🔑 Авторизация OK")

    conn, cur = init_db()
    total_new = 0
    total_updated = 0
    total_checked = 0
    start_time = datetime.now()

    # Помечаем старые вакансии
    mark_inactive_vacancies(cur)
    conn.commit()

    for prof_idx, profession in enumerate(PROFESSIONS):
        print(f"\n📌 [{prof_idx + 1}/{len(PROFESSIONS)}] {profession}")

        # 1. Загружаем все страницы с вакансиями (ПОСЛЕДОВАТЕЛЬНО)
        all_vacancies = fetch_all_vacancies(profession, MAX_PAGES)

        if not all_vacancies:
            print("  🚫 Нет вакансий")
            continue

        print(f"  └─ Всего получено: {len(all_vacancies)} вакансий")

        # 2. Загружаем детали ПАРАЛЛЕЛЬНО
        print(f"  → Загрузка деталей {len(all_vacancies)} вакансий в {MAX_WORKERS_DETAILS} потоков...")
        parsed_list = fetch_details_parallel(all_vacancies, profession)

        print(f"  → Сохранение {len(parsed_list)} вакансий в БД...")

        prof_new = 0
        prof_updated = 0

        for parsed in parsed_list:
            total_checked += 1
            if parsed:
                status = save_or_update_vacancy(cur, parsed)
                if status == 'new':
                    total_new += 1
                    prof_new += 1
                elif status == 'updated':
                    total_updated += 1
                    prof_updated += 1

        conn.commit()
        print(f"  ✅ Новых: {prof_new}, обновлено: {prof_updated}, обработано: {len(parsed_list)}/{len(all_vacancies)}")

        # Пауза между профессиями
        if prof_idx < len(PROFESSIONS) - 1:
            wait = random.uniform(*PAUSE_BETWEEN_PROFESSIONS)
            print(f"  ⏳ Пауза {wait:.1f} сек...")
            time.sleep(wait)

    # Обновляем динамику
    update_profession_dynamics(cur)
    conn.commit()

    # Выводим динамику
    print("\n" + "=" * 60)
    print("📈 РЫНОЧНАЯ ДИНАМИКА ПО ПРОФЕССИЯМ")
    print("=" * 60)
    cur.execute("SELECT * FROM profession_dynamics ORDER BY profession")
    for row in cur.fetchall():
        prof, demand_idx, ttl, calc_at = row
        ttl_str = f"{ttl} дн." if ttl else "нет данных"
        demand_str = f"{demand_idx:+.1%}" if demand_idx else "нет данных"
        print(f"  {prof}: спрос = {demand_str}, средний TTL = {ttl_str}")

    # Дозаполняем experience
    fill_experience_for_existing(cur)
    conn.commit()

    elapsed = datetime.now() - start_time
    print("\n" + "=" * 60)
    print(f"✅ ГОТОВО | Новых: {total_new} | Обновлено: {total_updated} | Проверено: {total_checked}")
    print(f"⏱️  Время: {elapsed.total_seconds():.1f} сек ({elapsed.total_seconds() / 60:.1f} мин)")
    print("=" * 60)

    save_logs(1, [total_checked, total_new])

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()