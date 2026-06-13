import sqlite3
import pandas as pd

# ==================================================
# РЕГИОНАЛЬНЫЕ КОЭФФИЦИЕНТЫ (справочно, не для расчета)
# ==================================================
REGIONAL_COEFFS = {
    'Москва': 1.40, 'Санкт-Петербург': 1.35, 'Московская область': 1.30,
    'Калужская область': 1.30, 'Тульская область': 1.20,
    'Республика Татарстан': 1.25, 'Нижегородская область': 1.20,
    'Свердловская область': 1.20, 'Челябинская область': 1.15,
    'Самарская область': 1.15, 'Красноярский край': 1.10,
    'Новосибирская область': 1.05, 'Пермский край': 1.05,
    'Тюменская область': 0.95, 'Томская область': 0.95,
    'Липецкая область': 0.95, 'Ростовская область': 0.90,
    'Краснодарский край': 0.90, 'Воронежская область': 0.90,
    'Белгородская область': 0.90, 'Ярославская область': 0.90,
    'Кемеровская область': 0.90, 'Омская область': 0.90,
    'Удмуртская Республика': 0.90, 'Иркутская область': 0.90,
    'Архангельская область': 0.85, 'Вологодская область': 0.85,
    'Хабаровский край': 0.85, 'Приморский край': 0.85,
    'Волгоградская область': 0.85, 'Курская область': 0.85,
    'Ульяновская область': 0.85, 'Чувашская Республика': 0.85,
    'Кировская область': 0.80, 'Саратовская область': 0.80,
    'Пензенская область': 0.80, 'Тамбовская область': 0.80,
    'Орловская область': 0.80, 'Брянская область': 0.80,
    'Смоленская область': 0.80, 'Республика Карелия': 0.80,
    'Республика Коми': 0.80, 'Мурманская область': 0.90,
    'Ханты-Мансийский АО': 0.80, 'Республика Адыгея': 0.60,
    'Республика Калмыкия': 0.50, 'Республика Марий Эл': 0.60,
    'Республика Мордовия': 0.60, 'Республика Северная Осетия': 0.50,
    'Кабардино-Балкарская Республика': 0.50,
    'Карачаево-Черкесская Республика': 0.50,
    'Республика Дагестан': 0.40, 'Чеченская Республика': 0.40,
    'Республика Ингушетия': 0.40
}


def load_data(db_path: str = 'hh_vacancies.db') -> dict:
    conn = sqlite3.connect(db_path)
    medians = pd.read_sql_query("SELECT profession, median FROM salary_ceilings WHERE grade = 'all'", conn)
    skill_prices = pd.read_sql_query("SELECT * FROM skill_prices", conn)
    ceilings = pd.read_sql_query("SELECT * FROM salary_ceilings", conn)
    base_skills = pd.read_sql_query("SELECT * FROM base_skills", conn)
    try:
        skill_coefficients = pd.read_sql_query("SELECT * FROM skill_coefficients", conn)
    except:
        skill_coefficients = pd.DataFrame()
    try:
        dynamics = pd.read_sql_query("SELECT * FROM profession_dynamics", conn)
    except:
        dynamics = pd.DataFrame()
    conn.close()
    return {
        'medians': medians, 'skill_prices': skill_prices,
        'ceilings': ceilings, 'base_skills': base_skills,
        'skill_coefficients': skill_coefficients,
        'dynamics': dynamics
    }


def calculate_salary(profession: str, skills: list, city: str = 'Москва', grade: str = 'Middle', data: dict = None) -> dict:
    if data is None:
        data = load_data()

    coef_data = data['skill_coefficients']
    coef_prof = coef_data[coef_data['profession'] == profession] if len(coef_data) > 0 else pd.DataFrame()

    if len(coef_prof) > 0:
        intercept_row = coef_prof[coef_prof['skill'] == 'INTERCEPT']
        if len(intercept_row) > 0:
            base_salary = float(intercept_row['coefficient'].iloc[0])
            r2 = float(intercept_row['r2_score'].iloc[0])
            total_premium = 0
            applied_skills = []
            missing_skills = []

            for skill in skills:
                skill_row = coef_prof[coef_prof['skill'] == skill]
                if len(skill_row) > 0:
                    coef = float(skill_row['coefficient'].iloc[0])
                    total_premium += coef
                    applied_skills.append({'skill': skill, 'premium_rub': int(coef)})
                else:
                    missing_skills.append(skill)

            # Пары навыков
            for _, row in coef_prof.iterrows():
                feature = row['skill']
                if ' + ' in feature:
                    s1, s2 = feature.split(' + ', 1)
                    if s1 in skills and s2 in skills:
                        coef = float(row['coefficient'])
                        total_premium += coef
                        applied_skills.append({'skill': feature, 'premium_rub': int(coef)})

            # Грейд
            grade_row = coef_prof[coef_prof['skill'] == f'grade_{grade}']
            if len(grade_row) > 0:
                coef = float(grade_row['coefficient'].iloc[0])
                total_premium += coef
                applied_skills.append({'skill': f'Грейд: {grade}', 'premium_rub': int(coef)})

            # Город
            city_row = coef_prof[coef_prof['skill'] == f'city_{city}']
            if len(city_row) > 0:
                coef = float(city_row['coefficient'].iloc[0])
                total_premium += coef
                applied_skills.append({'skill': f'Город: {city}', 'premium_rub': int(coef)})

            calculated = base_salary + total_premium
            method = f'regression (R²={r2:.2f})'
            base_median = int(base_salary)
            total_premium_percent = round(total_premium / base_salary * 100, 1) if base_salary > 0 else 0
        else:
            median_row = data['medians'][data['medians']['profession'] == profession]
            if len(median_row) == 0:
                return {'error': f'Нет данных по профессии: {profession}'}
            base_salary = float(median_row['median'].iloc[0])
            base_median = int(base_salary)
            applied_skills, missing_skills = [], []
            total_premium = 0
            total_premium_percent = 0
            method = 'median (no regression)'
    else:
        median_row = data['medians'][data['medians']['profession'] == profession]
        if len(median_row) == 0:
            return {'error': f'Нет данных по профессии: {profession}'}
        base_salary = float(median_row['median'].iloc[0])
        base_median = int(base_salary)
        applied_skills, missing_skills = [], []
        total_premium = 0
        total_premium_percent = 0
        method = 'median (no data)'

    # Корректировка на состояние рынка
    dyn_row = data['dynamics'][data['dynamics']['profession'] == profession]
    market_adjustment = 1.0
    demand_index = 0
    ttl_days = None

    if len(dyn_row) > 0:
        demand_index = float(dyn_row['demand_index'].iloc[0]) if pd.notna(dyn_row['demand_index'].iloc[0]) else 0
        ttl_days = float(dyn_row['avg_ttl_days'].iloc[0]) if pd.notna(dyn_row['avg_ttl_days'].iloc[0]) else None

        demand_adj = demand_index * 10
        ttl_adj = 0
        if ttl_days and ttl_days < 7:
            ttl_adj = 5
        elif ttl_days and ttl_days > 21:
            ttl_adj = -5

        market_adjustment = 1 + (demand_adj + ttl_adj) / 100

    calculated = (base_salary + total_premium) * market_adjustment

    salary_min = int(calculated * 0.9)
    salary_max = int(calculated * 1.1)
    salary_mid = int(calculated)

    ceiling_row = data['ceilings'][(data['ceilings']['profession'] == profession) & (data['ceilings']['grade'] == grade)]
    market_max = int(ceiling_row['p95'].iloc[0]) if len(ceiling_row) > 0 else None

    base_missing = []
    base_rows = data['base_skills'][data['base_skills']['profession'] == profession]
    for _, row in base_rows.iterrows():
        if row['skill'] not in skills:
            base_missing.append({'skill': row['skill'], 'penalty': row['penalty_percent']})

    return {
        'profession': profession, 'grade': grade, 'city': city,
        'base_median': base_median,
        'city_coefficient': REGIONAL_COEFFS.get(city, 1.0),
        'applied_skills': applied_skills, 'missing_skills': missing_skills,
        'base_missing': base_missing, 'total_premium_percent': total_premium_percent,
        'method': method, 'calculated_salary': salary_mid,
        'salary_range': f"{salary_min//1000}–{salary_max//1000}к",
        'salary_min': salary_min, 'salary_max': salary_max,
        'market_ceiling_p95': market_max,
        'demand_index': demand_index,
        'ttl_days': ttl_days,
        'market_adjustment': round((market_adjustment - 1) * 100, 1)
    }


def evaluate_candidate(profession: str, skills: list, city: str, expected_salary: int, grade: str = 'Middle', data: dict = None) -> dict:
    result = calculate_salary(profession, skills, city, grade, data)
    if 'error' in result:
        return result

    calculated = result['calculated_salary']
    diff_percent = round((expected_salary - calculated) / calculated * 100, 1)

    if expected_salary <= result['salary_max']:
        verdict = '✅ В рынке'
        recommendation = 'Можно делать оффер'
    elif expected_salary <= calculated * 1.3:
        verdict = '🟡 Слегка завышено'
        recommendation = f'Предложить {result["salary_range"]}, обсудить навыки'
    else:
        verdict = '🔴 Сильно завышено'
        recommendation = f'Показать данные рынка. Вилка: {result["salary_range"]}'

    if result.get('market_ceiling_p95') and expected_salary > result['market_ceiling_p95']:
        verdict = '🔴 Выше рынка'
        ceiling_str = f'{result["market_ceiling_p95"]:,}'.replace(',', ' ')
        recommendation = f'Показать данные рынка. Даже топ-5% ({grade}) получают до {ceiling_str} ₽'

    if result.get('base_missing'):
        base_names = [b['skill'] for b in result['base_missing']]
        recommendation += f'. ⚠️ Нет базовых навыков: {", ".join(base_names)}'

    result.update({'expected_salary': expected_salary, 'diff_percent': diff_percent, 'verdict': verdict, 'recommendation': recommendation})
    return result