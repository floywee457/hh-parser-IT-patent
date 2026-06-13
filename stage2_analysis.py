import sqlite3
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from itertools import combinations
from datetime import datetime, timedelta

# ==================================================
# НАСТРОЙКИ
# ==================================================
PROFESSIONS = [
    'Data Engineer', 'Python разработчик', 'Java разработчик',
    'DevOps инженер', 'Data Scientist', 'Machine Learning Engineer',
    'Backend разработчик', 'Frontend разработчик', 'Fullstack разработчик',
    'Системный аналитик'
]

REGIONAL_COEFFS = {
    'Москва': 1.40, 'Санкт-Петербург': 1.35, 'Новосибирск': 1.05,
    'Екатеринбург': 1.20, 'Казань': 1.25, 'Нижний Новгород': 1.20,
    'Челябинск': 1.15, 'Красноярск': 1.10, 'Самара': 1.15,
    'Ростов-на-Дону': 0.90, 'Уфа': 0.90, 'Омск': 0.90,
    'Воронеж': 0.90, 'Пермь': 1.05, 'Волгоград': 0.85
}

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)


# ==================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==================================================
def calc_base_salary(row):
    has_from = pd.notna(row['salary_from'])
    has_to = pd.notna(row['salary_to'])
    if has_from and has_to:
        return (row['salary_from'] + row['salary_to']) / 2
    elif has_from:
        return row['salary_from']
    elif has_to:
        return row['salary_to']
    return None


def detect_grade(title: str, experience: str, base_salary: float, median_total: float, city: str = '') -> str:
    if not title:
        title = ''
    if not experience or not isinstance(experience, str):
        experience = ''

    title_lower = title.lower()
    exp_lower = experience.lower()

    # Этап 1: Опыт из API
    if any(w in exp_lower for w in ['более 6 лет', 'более 6', '6 лет', 'свыше 6', 'от 6 лет']):
        return 'Senior'
    if any(w in exp_lower for w in ['3–6 лет', '3-6 лет', '3 до 6', 'от 3 до 6']):
        return 'Middle'
    if any(w in exp_lower for w in ['1–3 года', '1-3 года', '1 до 3', 'от 1 до 3', 'от 1 года до 3']):
        return 'Junior'
    if any(w in exp_lower for w in ['нет опыта', 'без опыта', 'начинающий', 'не имеет значения', 'менее года', 'до 1 года']):
        return 'Junior'

    # Этап 2: Название вакансии
    senior_words = ['senior', 'сеньор', 'sen ', 'ведущий', 'lead', 'старший', 'sen.', 'ст.']
    junior_words = ['junior', 'младший', 'jun ', 'стажер', 'intern', 'млад', 'jun.', 'мл.']

    for word in senior_words:
        if word in title_lower:
            return 'Senior'
    for word in junior_words:
        if word in title_lower:
            return 'Junior'

    # Этап 3: Зарплата с поправкой на регион
    if median_total > 0 and base_salary > 0:
        city_coeff = REGIONAL_COEFFS.get(city, 1.0)
        adjusted_salary = base_salary / city_coeff
        ratio = adjusted_salary / median_total
        if ratio < 0.7:
            return 'Junior'
        elif ratio > 1.4:
            return 'Senior'

    return 'Middle'


# ==================================================
# 1. НАДБАВКИ ЗА НАВЫКИ
# ==================================================
def calculate_skill_premiums(df: pd.DataFrame) -> pd.DataFrame:
    all_skills = set()
    for skills in df['skills_list']:
        if skills:
            all_skills.update(skills)

    median_total = df['base_salary'].median()
    results = []

    for skill in all_skills:
        with_skill = df[df['skills_list'].apply(lambda x: skill in x if x else False)]
        without_skill = df[df['skills_list'].apply(lambda x: skill not in x if x else True)]

        sample_size = len(with_skill)
        if sample_size < 10:
            continue

        median_with = with_skill['base_salary'].median()
        median_without = without_skill['base_salary'].median() if len(without_skill) > 0 else median_total
        premium = round((median_with - median_without) / median_without * 100, 1) if median_without > 0 else 0

        if premium > 0:
            results.append({
                'skill': skill,
                'median_with_skill': int(median_with),
                'median_without_skill': int(median_without),
                'median_total': int(median_total),
                'premium_percent': premium,
                'sample_size': sample_size
            })

    return pd.DataFrame(results).sort_values('premium_percent', ascending=False)


# ==================================================
# 2. ПОТОЛОК ЗАРПЛАТ
# ==================================================
def calculate_salary_ceiling(df: pd.DataFrame, profession: str) -> dict:
    return {
        'profession': profession, 'grade': 'all', 'count': len(df),
        'median': int(df['base_salary'].median()),
        'p25': int(df['base_salary'].quantile(0.25)),
        'p75': int(df['base_salary'].quantile(0.75)),
        'p90': int(df['base_salary'].quantile(0.90)),
        'p95': int(df['base_salary'].quantile(0.95)),
        'max': int(df['base_salary'].max()),
        'min': int(df['base_salary'].min())
    }


def calculate_salary_ceiling_by_grade(df: pd.DataFrame, profession: str) -> list:
    results = []
    for grade in ['Junior', 'Middle', 'Senior']:
        df_grade = df[df['grade'] == grade]
        if len(df_grade) < 5:
            continue
        results.append({
            'profession': profession, 'grade': grade, 'count': len(df_grade),
            'median': int(df_grade['base_salary'].median()),
            'p25': int(df_grade['base_salary'].quantile(0.25)),
            'p75': int(df_grade['base_salary'].quantile(0.75)),
            'p90': int(df_grade['base_salary'].quantile(0.90)),
            'p95': int(df_grade['base_salary'].quantile(0.95)),
            'max': int(df_grade['base_salary'].max()),
            'min': int(df_grade['base_salary'].min())
        })
    return results


# ==================================================
# 3. БАЗОВЫЕ НАВЫКИ
# ==================================================
def calculate_base_skills(df: pd.DataFrame) -> pd.DataFrame:
    total_vacancies = len(df)
    all_skills = set()
    for skills in df['skills_list']:
        if skills:
            all_skills.update(skills)

    results = []
    for skill in all_skills:
        with_skill = df[df['skills_list'].apply(lambda x: skill in x if x else False)]
        without_skill = df[df['skills_list'].apply(lambda x: skill not in x if x else True)]
        penetration = len(with_skill) / total_vacancies * 100

        if penetration >= 50 and len(without_skill) >= 10:
            median_with = with_skill['base_salary'].median()
            median_without = without_skill['base_salary'].median()
            penalty = round((median_without - median_with) / median_with * 100, 1)
            if penalty < 0:
                results.append({
                    'skill': skill, 'penetration_percent': round(penetration, 1),
                    'median_with_skill': int(median_with), 'median_without_skill': int(median_without),
                    'penalty_percent': penalty, 'is_base': penetration >= 70
                })

    if len(results) == 0:
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values('penetration_percent', ascending=False)


# ==================================================
# ГЛАВНЫЙ ЦИКЛ
# ==================================================
def main():
    print("=" * 60)
    print("📊 ЭТАП 2: АНАЛИТИКА НАВЫКОВ + РЕГРЕССИЯ")
    print("=" * 60)

    conn = sqlite3.connect('hh_vacancies.db')
    cur = conn.cursor()
    three_months_ago = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

    # Явная транзакция — все изменения атомарны
    cur.execute("BEGIN")

    cur.execute("""CREATE TABLE IF NOT EXISTS skill_prices (
        profession TEXT, skill TEXT, median_with_skill INTEGER, median_without_skill INTEGER,
        median_total INTEGER, premium_percent REAL, sample_size INTEGER,
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (profession, skill))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS salary_ceilings (
        profession TEXT, grade TEXT, count_vacancies INTEGER,
        median INTEGER, p25 INTEGER, p75 INTEGER, p90 INTEGER, p95 INTEGER,
        max_salary INTEGER, min_salary INTEGER,
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (profession, grade))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS base_skills (
        profession TEXT, skill TEXT, penetration_percent REAL, median_with_skill INTEGER,
        median_without_skill INTEGER, penalty_percent REAL, is_base INTEGER,
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (profession, skill))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS skill_coefficients (
        profession TEXT, skill TEXT, coefficient REAL, intercept REAL,
        sample_size INTEGER, r2_score REAL,
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (profession, skill))""")

    for prof_idx, prof in enumerate(PROFESSIONS):
        print(f"\n{'=' * 60}")
        print(f"📌 [{prof_idx + 1}/{len(PROFESSIONS)}] {prof}")
        print('=' * 60)

        df = pd.read_sql_query("""
            SELECT profession, city, title, salary_from, salary_to, key_skills, experience
            FROM vacancies WHERE profession = ? AND substr(published_at, 1, 10) >= ?
            AND key_skills IS NOT NULL AND key_skills != ''
            AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)
        """, conn, params=[prof, three_months_ago])

        if len(df) < 20:
            print(f"  ⚠️ Недостаточно данных ({len(df)} вакансий), пропускаем")
            continue

        df['base_salary'] = df.apply(calc_base_salary, axis=1)
        df = df.dropna(subset=['base_salary'])
        df['skills_list'] = df['key_skills'].str.split(', ')
        median_total = df['base_salary'].median()

        df['grade'] = df.apply(lambda row: detect_grade(
            title=row['title'], experience=row.get('experience', ''),
            base_salary=row['base_salary'], median_total=median_total, city=row.get('city', '')
        ), axis=1)

        print(f"  Вакансий: {len(df)}")
        print(f"  Junior: {(df['grade'] == 'Junior').sum()}, Middle: {(df['grade'] == 'Middle').sum()}, Senior: {(df['grade'] == 'Senior').sum()}")
        print(f"  Медианная з/п: {median_total:,.0f} ₽")

        # 1. Надбавки за навыки
        df_skills = calculate_skill_premiums(df)
        if len(df_skills) > 0:
            for _, row in df_skills.iterrows():
                cur.execute("""INSERT OR REPLACE INTO skill_prices
                    (profession, skill, median_with_skill, median_without_skill, median_total, premium_percent, sample_size, calculated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (prof, row['skill'], row['median_with_skill'], row['median_without_skill'],
                     row['median_total'], row['premium_percent'], row['sample_size']))
            print(f"\n  ✅ skill_prices: {len(df_skills)} навыков")
        else:
            print(f"  ⚠️ skill_prices: нет навыков")

        # 1.5 РЕГРЕССИЯ
        top_skills = df_skills.head(10)['skill'].tolist() if len(df_skills) > 0 else []

        pair_features = []
        for s1, s2 in combinations(top_skills, 2):
            pair_count = df[df['skills_list'].apply(
                lambda x: s1 in x and s2 in x if x else False
            )].shape[0]
            if pair_count >= 5:
                pair_features.append(f"{s1} + {s2}")

        if len(top_skills) >= 2:
            grade_dummies = pd.get_dummies(df['grade'], prefix='grade')
            city_dummies = pd.get_dummies(df['city'], prefix='city')
            feature_cols = top_skills + pair_features + list(grade_dummies.columns) + list(city_dummies.columns)

            X = np.zeros((len(df), len(feature_cols)))
            y = df['base_salary'].values

            for i, skills in enumerate(df['skills_list']):
                for j, skill in enumerate(top_skills):
                    if skills and skill in skills:
                        X[i, j] = 1

            for j, pair_name in enumerate(pair_features):
                s1, s2 = pair_name.split(' + ', 1)
                col_idx = len(top_skills) + j
                for i, skills in enumerate(df['skills_list']):
                    if skills and s1 in skills and s2 in skills:
                        X[i, col_idx] = 1

            offset = len(top_skills) + len(pair_features)
            for j, col in enumerate(grade_dummies.columns):
                X[:, offset + j] = grade_dummies[col].values

            offset2 = offset + len(grade_dummies.columns)
            for j, col in enumerate(city_dummies.columns):
                X[:, offset2 + j] = city_dummies[col].values

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

            model = LinearRegression()
            model.fit(X_train, y_train)

            r2_train = model.score(X_train, y_train)
            r2_test = model.score(X_test, y_test)

            cur.execute("DELETE FROM skill_coefficients WHERE profession = ?", (prof,))
            cur.execute("""INSERT INTO skill_coefficients
                (profession, skill, coefficient, intercept, sample_size, r2_score, calculated_at)
                VALUES (?, 'INTERCEPT', ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (prof, float(model.intercept_), float(model.intercept_), len(df), r2_test))
            for j, name in enumerate(feature_cols):
                cur.execute("""INSERT INTO skill_coefficients
                    (profession, skill, coefficient, intercept, sample_size, r2_score, calculated_at)
                    VALUES (?, ?, ?, 0, ?, ?, CURRENT_TIMESTAMP)""",
                    (prof, name, float(model.coef_[j]), len(df), r2_test))

            print(f"\n  ✅ Регрессия: R² train = {r2_train:.3f}, R² test = {r2_test:.3f}, базовая ставка: {int(model.intercept_):,} ₽")
            print(f"  Признаков: {len(feature_cols)} (навыков: {len(top_skills)}, пар: {len(pair_features)}, грейдов: {len(grade_dummies.columns)}, городов: {len(city_dummies.columns)})")
            if r2_test > 0:
                print(f"  Топ-5 по вкладу:")
                contributions = sorted(zip(feature_cols, model.coef_), key=lambda x: x[1], reverse=True)
                for name, coef in contributions[:5]:
                    if coef > 0:
                        print(f"    {name:30s} +{int(coef):,} ₽")

        # 2. Потолки
        ceiling_all = calculate_salary_ceiling(df, prof)
        cur.execute("""INSERT OR REPLACE INTO salary_ceilings
            (profession, grade, count_vacancies, median, p25, p75, p90, p95, max_salary, min_salary, calculated_at)
            VALUES (?, 'all', ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (prof, ceiling_all['count'], ceiling_all['median'], ceiling_all['p25'],
             ceiling_all['p75'], ceiling_all['p90'], ceiling_all['p95'], ceiling_all['max'], ceiling_all['min']))
        for gd in calculate_salary_ceiling_by_grade(df, prof):
            cur.execute("""INSERT OR REPLACE INTO salary_ceilings
                (profession, grade, count_vacancies, median, p25, p75, p90, p95, max_salary, min_salary, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (prof, gd['grade'], gd['count'], gd['median'], gd['p25'], gd['p75'],
                 gd['p90'], gd['p95'], gd['max'], gd['min']))
        print(f"\n  ✅ salary_ceilings: общий + грейды")

        # 3. Базовые навыки
        df_base = calculate_base_skills(df)
        if len(df_base) > 0 and len(df_base.columns) > 0:
            for _, row in df_base.iterrows():
                cur.execute("""INSERT OR REPLACE INTO base_skills
                    (profession, skill, penetration_percent, median_with_skill, median_without_skill, penalty_percent, is_base, calculated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (prof, row['skill'], row['penetration_percent'], row['median_with_skill'],
                     row['median_without_skill'], row['penalty_percent'], int(row['is_base'])))
            base = df_base[df_base['is_base'] == True]
            near = df_base[df_base['is_base'] == False]
            print(f"\n  📌 Базовые навыки (без них зарплата ниже рынка):")
            for _, row in pd.concat([base, near]).iterrows():
                icon = '🔴' if row['is_base'] else '🟡'
                print(f"    {icon} {row['skill']:25s} есть у {row['penetration_percent']:5.1f}% вакансий, без него з/п ниже на {row['penalty_percent']:+.1f}%")
        else:
            print(f"\n  📌 Базовые навыки: не выявлено")

    # Один коммит в конце — все таблицы обновлены атомарно
    conn.commit()
    print(f"\n✅ ЭТАП 2 ЗАВЕРШЕН")
    for table in ['skill_prices', 'salary_ceilings', 'base_skills', 'skill_coefficients']:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {cur.fetchone()[0]} записей")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()