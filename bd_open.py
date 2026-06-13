import sqlite3
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 300)           # ← ширина вывода
pd.set_option('display.max_colwidth', 30)     # ← макс. ширина колонки
pd.set_option('display.expand_frame_repr', False)  # ← не переносить

conn = sqlite3.connect('hh_vacancies.db')
df = pd.read_sql("SELECT * FROM vacancies", conn)
print(df)  # ← сначала 5 строк для проверки

conn.close()

