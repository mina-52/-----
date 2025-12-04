import sqlite3

conn = sqlite3.connect('account.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    category TEXT,
    amount INTEGER,
    memo TEXT
)''')
conn.commit()
conn.close()