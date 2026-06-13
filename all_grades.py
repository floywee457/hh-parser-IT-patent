import sqlite3
import requests
import time

conn = sqlite3.connect('hh_vacancies.db')
cur = conn.cursor()

cur.execute("SELECT id, url FROM vacancies WHERE experience IS NULL OR experience = ''")
rows = cur.fetchall()

print(f"Записей без experience: {len(rows)}")

updated = 0
for idx, (vac_id, url) in enumerate(rows):
    try:
        vac_hh_id = url.split('/')[-1]

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

        if (idx + 1) % 100 == 0:
            conn.commit()
            print(f"  Обработано {idx + 1}/{len(rows)}, обновлено {updated}")

        time.sleep(0.3)

    except Exception as e:
        print(f"  Ошибка {url}: {e}")

conn.commit()
print(f"\nГотово. Обновлено: {updated}/{len(rows)}")
cur.close()
conn.close()