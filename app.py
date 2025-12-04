from flask import Flask, render_template, request, redirect, jsonify, Response
import sqlite3
from datetime import datetime, timedelta
import csv
import io

app = Flask(__name__)
DB_NAME = 'account.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    category TEXT,
                    amount INTEGER,
                    memo TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_fee INTEGER
                )''')
    c.execute("INSERT OR IGNORE INTO settings (id, initial_fee) VALUES (1, 100000)")
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # フィルタパラメータ取得
    search_query = request.args.get('search', '')
    category_filter = request.args.get('category', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    # クエリ構築
    query = "SELECT * FROM records WHERE 1=1"
    params = []
    
    if search_query:
        query += " AND (memo LIKE ? OR amount LIKE ?)"
        params.extend([f'%{search_query}%', f'%{search_query}%'])
    
    if category_filter:
        query += " AND category = ?"
        params.append(category_filter)
    
    if date_from:
        query += " AND date >= ?"
        params.append(date_from)
    
    if date_to:
        query += " AND date <= ?"
        params.append(date_to)
    
    query += " ORDER BY date DESC"
    c.execute(query, params)
    records = c.fetchall()
    
    # 統計データ
    c.execute("SELECT SUM(amount) FROM records WHERE category='収入'")
    income = c.fetchone()[0] or 0
    c.execute("SELECT SUM(amount) FROM records WHERE category='支出'")
    expense = c.fetchone()[0] or 0
    balance = income - expense
    c.execute("SELECT initial_fee FROM settings WHERE id = 1")
    initial_fee = c.fetchone()[0]
    remaining_fee = initial_fee + balance
    
    # 月次データ（グラフ用）
    c.execute("""
        SELECT strftime('%Y-%m', date) as month, 
               category,
               SUM(amount) as total
        FROM records 
        GROUP BY month, category
        ORDER BY month DESC
        LIMIT 12
    """)
    monthly_data = c.fetchall()
    
    # カテゴリ別統計
    c.execute("""
        SELECT category, SUM(amount) as total
        FROM records
        GROUP BY category
    """)
    category_stats = c.fetchall()
    
    conn.close()
    return render_template('index.html', records=records, income=income, expense=expense,
                           balance=balance, initial_fee=initial_fee, remaining_fee=remaining_fee,
                           last_update=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           monthly_data=monthly_data, category_stats=category_stats,
                           search_query=search_query, category_filter=category_filter,
                           date_from=date_from, date_to=date_to)

@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 単体登録
        if 'single' in request.form:
            date = request.form['date']
            category = request.form['category']
            amount = request.form['amount']
            memo = request.form['memo']
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO records (date, category, amount, memo) VALUES (?, ?, ?, ?)",
                      (date, category, amount, memo))
            conn.commit()
            conn.close()
        # 複数登録
        elif 'multi' in request.form:
            dates = request.form.getlist('date[]')
            categories = request.form.getlist('category[]')
            amounts = request.form.getlist('amount[]')
            memos = request.form.getlist('memo[]')
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            for d, cat, amt, mem in zip(dates, categories, amounts, memos):
                c.execute("INSERT INTO records (date, category, amount, memo) VALUES (?, ?, ?, ?)",
                          (d, cat, amt, mem))
            conn.commit()
            conn.close()
        return redirect('/')
    return render_template('add.html')

@app.route('/set_fee', methods=['GET', 'POST'])
def set_fee():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if request.method == 'POST':
        new_fee = request.form['initial_fee']
        c.execute("UPDATE settings SET initial_fee = ? WHERE id = 1", (new_fee,))
        conn.commit()
        conn.close()
        return redirect('/')
    else:
        c.execute("SELECT initial_fee FROM settings WHERE id = 1")
        current_fee = c.fetchone()[0]
        conn.close()
        return render_template('set_fee.html', current_fee=current_fee)

@app.route('/edit/<int:record_id>', methods=['GET', 'POST'])
def edit_record(record_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if request.method == 'POST':
        date = request.form['date']
        category = request.form['category']
        amount = request.form['amount']
        memo = request.form['memo']
        c.execute("UPDATE records SET date=?, category=?, amount=?, memo=? WHERE id=?",
                  (date, category, amount, memo, record_id))
        conn.commit()
        conn.close()
        return redirect('/')
    else:
        c.execute("SELECT * FROM records WHERE id = ?", (record_id,))
        record = c.fetchone()
        conn.close()
        if record:
            return render_template('edit.html', record=record)
        return redirect('/')

@app.route('/delete/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/export')
def export_csv():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT date, category, amount, memo FROM records ORDER BY date DESC")
    records = c.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['日付', '区分', '金額', 'メモ'])
    for record in records:
        writer.writerow(record)
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=account_records.csv'}
    )

@app.route('/api/chart-data')
def chart_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT strftime('%Y-%m', date) as month, 
               SUM(CASE WHEN category='収入' THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN category='支出' THEN amount ELSE 0 END) as expense
        FROM records 
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    data = c.fetchall()
    conn.close()
    
    months = [row[0] for row in reversed(data)]
    income = [row[1] for row in reversed(data)]
    expense = [row[2] for row in reversed(data)]
    
    return jsonify({
        'months': months,
        'income': income,
        'expense': expense
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
