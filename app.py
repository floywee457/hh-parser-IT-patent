import streamlit as st
import pandas as pd
import sqlite3
from stage3_model import load_data, evaluate_candidate

st.set_page_config(page_title="Зарплатный навигатор IT", page_icon="💰")
st.title("💰 Зарплатный навигатор IT-специалиста")
st.caption("Инструмент для HR: объективная оценка зарплатных ожиданий кандидата")

# ==================================================
# ЗАГРУЗКА ДАННЫХ
# ==================================================
@st.cache_data(ttl=3600)
def get_data():
    return load_data()

data = get_data()

# Проверка синхронности данных
conn_check = sqlite3.connect('hh_vacancies.db')
dates = {}
for table in ['skill_prices', 'base_skills', 'skill_coefficients']:
    try:
        df_check = pd.read_sql_query(
            f"SELECT MAX(calculated_at) as last_update FROM {table}", conn_check
        )
        dates[table] = df_check['last_update'].iloc[0]
    except:
        dates[table] = None
conn_check.close()

unique_dates = set()
for d in dates.values():
    if d is not None:
        unique_dates.add(str(d)[:16])
if len(unique_dates) > 1:
    st.warning("⚠️ Данные аналитики обновлены не синхронно. Запустите stage2_analysis.py")

professions = sorted(data['medians']['profession'].unique().tolist())
grades = ['Junior', 'Middle', 'Senior']

cities = [
    'Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань',
    'Нижний Новгород', 'Челябинск', 'Красноярск', 'Самара', 'Ростов-на-Дону',
    'Уфа', 'Омск', 'Воронеж', 'Пермь', 'Волгоград', 'Краснодар',
    'Тюмень', 'Томск', 'Владивосток', 'Хабаровск', 'Иркутск'
]

# ==================================================
# ФОРМА ВВОДА
# ==================================================
st.subheader("📋 Данные кандидата")

col1, col2 = st.columns(2)

with col1:
    profession = st.selectbox("Профессия", professions)
    city = st.selectbox("Город", cities)
    grade = st.selectbox("Грейд", grades, index=1)

with col2:
    expected_salary = st.number_input(
        "Ожидания кандидата (₽)",
        min_value=0, value=200000, step=10000, format="%d"
    )

    skill_options = data['skill_prices'][
        data['skill_prices']['profession'] == profession
    ]['skill'].unique().tolist()

    selected_skills = st.multiselect("Навыки кандидата", skill_options)

# ==================================================
# БАЗОВЫЕ НАВЫКИ
# ==================================================
base_skills_list = data['base_skills'][
    data['base_skills']['profession'] == profession
]

if len(base_skills_list) > 0:
    st.divider()
    st.subheader("🔴 Базовые навыки")
    st.caption("Отметьте, если есть у кандидата. Отсутствие снижает зарплату.")

    base_selected = []
    for _, row in base_skills_list.iterrows():
        if st.checkbox(
            f"{row['skill']} (без него з/п ниже на {row['penalty_percent']:+.1f}%)",
            value=True,
            key=f"base_{row['skill']}"
        ):
            base_selected.append(row['skill'])

    all_skills = selected_skills + [s for s in base_selected if s not in selected_skills]
else:
    all_skills = selected_skills

# ==================================================
# РАСЧЕТ
# ==================================================
if st.button("Рассчитать", type="primary", use_container_width=True):
    if not all_skills:
        st.warning("⚠️ Выберите хотя бы один навык")
    else:
        result = evaluate_candidate(
            profession=profession,
            skills=all_skills,
            city=city,
            expected_salary=expected_salary,
            grade=grade,
            data=data
        )

        if 'error' in result:
            st.error(f"❌ {result['error']}")
        else:
            st.divider()

            verdict = result['verdict']
            if '✅' in verdict:
                st.success(f"### {verdict}")
            elif '🟡' in verdict:
                st.warning(f"### {verdict}")
            else:
                st.error(f"### {verdict}")

            st.write(f"**{result['recommendation']}**")

            # Метрики
            st.divider()
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Базовая ставка", f"{result['base_median']:,} ₽".replace(',', ' '))
            col2.metric("Расчетная ставка", f"{result['calculated_salary']:,} ₽".replace(',', ' '))
            col3.metric("Рыночная вилка", result['salary_range'])
            col4.metric("Отклонение", f"{result['diff_percent']:+.1f}%")

            st.caption(f"Метод расчета: {result.get('method', '?')}")

            # Детализация
            if result.get('applied_skills'):
                st.divider()
                st.subheader("📊 Вклад навыков и факторов")
                for skill in result['applied_skills']:
                    st.write(f"- {skill['skill']}: **+{skill['premium_rub']:,} ₽**".replace(',', ' '))

            if result.get('base_missing'):
                st.warning(f"⚠️ Отсутствуют базовые навыки: {', '.join(b['skill'] for b in result['base_missing'])}")

            # Состояние рынка
            if result.get('demand_index') is not None:
                st.divider()
                st.subheader("📈 Состояние рынка")

                demand = result.get('demand_index', 0)
                ttl = result.get('ttl_days')

                if demand == 0 and not ttl:
                    st.write("📊 Данные о состоянии рынка накапливаются (нужно 2+ дня парсинга)")
                else:
                    if demand > 0.05:
                        st.write(f"🔺 Спрос растет: **+{demand*100:.0f}%** за 2 недели")
                    elif demand < -0.05:
                        st.write(f"🔻 Спрос падает: **{demand*100:.0f}%** за 2 недели")
                    else:
                        st.write(f"➡️ Спрос стабилен")

                    if ttl:
                        if ttl < 7:
                            st.write(f"🔥 Среднее время закрытия: **{ttl} дн.** — дефицит специалистов")
                        elif ttl > 21:
                            st.write(f"🐢 Среднее время закрытия: **{ttl} дн.** — рынок работодателя")
                        else:
                            st.write(f"⏳ Среднее время закрытия: **{ttl} дн.** — норма")

                    adj = result.get('market_adjustment', 0)
                    if adj != 0:
                        st.write(f"💰 Поправка к зарплате: **{adj:+.1f}%**")

# ==================================================
# ДАННЫЕ РЫНКА
# ==================================================
st.divider()
with st.expander("📊 Данные рынка по профессии"):
    tab1, tab2, tab3 = st.tabs(["Надбавки за навыки", "Потолки зарплат", "Базовые навыки"])

    with tab1:
        df_skills = data['skill_prices'][data['skill_prices']['profession'] == profession]
        if len(df_skills) > 0:
            df_skills = df_skills[['skill', 'premium_percent', 'median_with_skill', 'sample_size']]
            df_skills.columns = ['Навык', 'Надбавка %', 'Медиана с навыком', 'Выборка']
            st.dataframe(df_skills, hide_index=True, use_container_width=True)
        else:
            st.write("Нет данных")

    with tab2:
        df_ceil = data['ceilings'][data['ceilings']['profession'] == profession]
        if len(df_ceil) > 0:
            df_ceil = df_ceil[['grade', 'count_vacancies', 'median', 'p90', 'p95', 'max_salary']]
            df_ceil.columns = ['Грейд', 'Вакансий', 'Медиана', '90-й %', '95-й %', 'Максимум']
            st.dataframe(df_ceil, hide_index=True, use_container_width=True)
        else:
            st.write("Нет данных")

    with tab3:
        df_base = data['base_skills'][data['base_skills']['profession'] == profession]
        if len(df_base) > 0:
            df_base = df_base[['skill', 'penetration_percent', 'penalty_percent', 'is_base']]
            df_base.columns = ['Навык', 'Охват %', 'Штраф за отсутствие %', 'База']
            df_base['База'] = df_base['База'].map({1: '🔴 База', 0: '🟡 Близко'})
            st.dataframe(df_base, hide_index=True, use_container_width=True)
        else:
            st.write("Базовые навыки не выявлены")