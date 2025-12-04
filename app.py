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
                    subcategory TEXT,
                    amount INTEGER,
                    memo TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_fee INTEGER
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    subcategory TEXT,
                    amount INTEGER,
                    month TEXT,
                    year INTEGER
                )''')
    # 既存のrecordsテーブルにsubcategoryカラムを追加（存在しない場合）
    try:
        c.execute("ALTER TABLE records ADD COLUMN subcategory TEXT")
    except:
        pass  # カラムが既に存在する場合はスキップ
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
    
    # 詳細統計
    c.execute("SELECT COUNT(*) FROM records")
    total_records = c.fetchone()[0] or 0
    c.execute("SELECT AVG(amount) FROM records WHERE category='支出'")
    avg_expense = c.fetchone()[0] or 0
    c.execute("SELECT MAX(amount) FROM records WHERE category='支出'")
    max_expense = c.fetchone()[0] or 0
    c.execute("SELECT MIN(amount) FROM records WHERE category='支出'")
    min_expense = c.fetchone()[0] or 0
    c.execute("SELECT AVG(amount) FROM records WHERE category='収入'")
    avg_income = c.fetchone()[0] or 0
    
    # 今月のデータ
    current_month = datetime.now().strftime('%Y-%m')
    c.execute("SELECT SUM(amount) FROM records WHERE category='収入' AND strftime('%Y-%m', date) = ?", (current_month,))
    month_income = c.fetchone()[0] or 0
    c.execute("SELECT SUM(amount) FROM records WHERE category='支出' AND strftime('%Y-%m', date) = ?", (current_month,))
    month_expense = c.fetchone()[0] or 0
    
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
    
    # 並び替え
    sort_by = request.args.get('sort', 'date')
    sort_order = request.args.get('order', 'desc')
    
    if sort_by == 'date':
        records = sorted(records, key=lambda x: x[1], reverse=(sort_order == 'desc'))
    elif sort_by == 'amount':
        records = sorted(records, key=lambda x: x[4] if len(x) > 4 else 0, reverse=(sort_order == 'desc'))
    elif sort_by == 'category':
        records = sorted(records, key=lambda x: x[2], reverse=(sort_order == 'desc'))
    
    # ページネーション
    page = int(request.args.get('page', 1))
    per_page = 20
    total_pages = (len(records) + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_records = records[start_idx:end_idx]
    
    # インポート通知
    imported = request.args.get('imported', '')
    
    conn.close()
    return render_template('index.html', records=paginated_records, income=income, expense=expense,
                           balance=balance, initial_fee=initial_fee, remaining_fee=remaining_fee,
                           last_update=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           monthly_data=monthly_data, category_stats=category_stats,
                           search_query=search_query, category_filter=category_filter,
                           date_from=date_from, date_to=date_to,
                           total_records=total_records, avg_expense=avg_expense, max_expense=max_expense,
                           min_expense=min_expense, avg_income=avg_income,
                           month_income=month_income, month_expense=month_expense,
                           current_page=page, total_pages=total_pages,
                           sort_by=sort_by, sort_order=sort_order, imported=imported)

@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        # 単体登録
        if 'single' in request.form:
            date = request.form['date']
            category = request.form['category']
            subcategory = request.form.get('subcategory', '')
            amount = request.form['amount']
            memo = request.form['memo']
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO records (date, category, subcategory, amount, memo) VALUES (?, ?, ?, ?, ?)",
                      (date, category, subcategory, amount, memo))
            conn.commit()
            conn.close()
        # 複数登録
        elif 'multi' in request.form:
            dates = request.form.getlist('date[]')
            categories = request.form.getlist('category[]')
            subcategories = request.form.getlist('subcategory[]')
            amounts = request.form.getlist('amount[]')
            memos = request.form.getlist('memo[]')
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            for d, cat, subcat, amt, mem in zip(dates, categories, subcategories, amounts, memos):
                c.execute("INSERT INTO records (date, category, subcategory, amount, memo) VALUES (?, ?, ?, ?, ?)",
                          (d, cat, subcat or '', amt, mem))
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
        subcategory = request.form.get('subcategory', '')
        amount = request.form['amount']
        memo = request.form['memo']
        c.execute("UPDATE records SET date=?, category=?, subcategory=?, amount=?, memo=? WHERE id=?",
                  (date, category, subcategory, amount, memo, record_id))
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

@app.route('/api/category-pie-data')
def category_pie_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT subcategory, SUM(amount) as total
        FROM records
        WHERE category='支出' AND subcategory IS NOT NULL AND subcategory != ''
        GROUP BY subcategory
        ORDER BY total DESC
        LIMIT 10
    """)
    data = c.fetchall()
    conn.close()
    
    labels = [row[0] for row in data]
    values = [row[1] for row in data]
    
    return jsonify({
        'labels': labels,
        'values': values
    })

@app.route('/api/monthly-trend')
def monthly_trend():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN category='収入' THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN category='支出' THEN amount ELSE 0 END) as expense
        FROM records
        GROUP BY month
        ORDER BY month DESC
        LIMIT 6
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

@app.route('/reports')
def reports():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 年次レポート
    c.execute("""
        SELECT strftime('%Y', date) as year,
               SUM(CASE WHEN category='収入' THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN category='支出' THEN amount ELSE 0 END) as expense
        FROM records
        GROUP BY year
        ORDER BY year DESC
    """)
    yearly_data = c.fetchall()
    
    # 月次レポート（過去12ヶ月）
    c.execute("""
        SELECT strftime('%Y-%m', date) as month,
               SUM(CASE WHEN category='収入' THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN category='支出' THEN amount ELSE 0 END) as expense
        FROM records
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    monthly_report = c.fetchall()
    
    # サブカテゴリ別統計
    c.execute("""
        SELECT subcategory, COUNT(*) as count, SUM(amount) as total
        FROM records
        WHERE category='支出' AND subcategory IS NOT NULL AND subcategory != ''
        GROUP BY subcategory
        ORDER BY total DESC
    """)
    subcategory_stats = c.fetchall()
    
    conn.close()
    return render_template('reports.html', yearly_data=yearly_data,
                         monthly_report=monthly_report, subcategory_stats=subcategory_stats)

@app.route('/budget', methods=['GET', 'POST'])
def budget():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    if request.method == 'POST':
        category = request.form.get('category', '')
        subcategory = request.form.get('subcategory', '')
        amount = request.form.get('amount', 0)
        month = request.form.get('month', '')
        year = request.form.get('year', datetime.now().year)
        
        if request.form.get('action') == 'add':
            c.execute("INSERT INTO budgets (category, subcategory, amount, month, year) VALUES (?, ?, ?, ?, ?)",
                      (category, subcategory, amount, month, year))
        elif request.form.get('action') == 'delete':
            budget_id = request.form.get('budget_id')
            c.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
        
        conn.commit()
        conn.close()
        return redirect('/budget')
    
    # 予算一覧
    current_month = datetime.now().strftime('%Y-%m')
    c.execute("SELECT * FROM budgets WHERE month = ? OR month = '' ORDER BY year DESC, month DESC", (current_month,))
    budgets = c.fetchall()
    
    # 予算と実績の比較
    c.execute("""
        SELECT b.id, b.category, b.subcategory, b.amount as budget,
               COALESCE(SUM(r.amount), 0) as actual
        FROM budgets b
        LEFT JOIN records r ON r.category = b.category 
            AND (b.subcategory = '' OR r.subcategory = b.subcategory)
            AND strftime('%Y-%m', r.date) = b.month
        WHERE b.month = ? OR b.month = ''
        GROUP BY b.id
    """, (current_month,))
    budget_comparison = c.fetchall()
    
    conn.close()
    return render_template('budget.html', budgets=budgets, budget_comparison=budget_comparison,
                         current_month=current_month)

@app.route('/import', methods=['GET', 'POST'])
def import_csv():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect('/')
        file = request.files['file']
        if file.filename == '':
            return redirect('/')
        
        if file and file.filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.reader(stream)
            next(csv_reader)  # ヘッダー行をスキップ
            
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            count = 0
            for row in csv_reader:
                if len(row) >= 3:
                    date = row[0]
                    category = row[1]
                    amount = row[2]
                    memo = row[3] if len(row) > 3 else ''
                    subcategory = row[4] if len(row) > 4 else ''
                    try:
                        c.execute("INSERT INTO records (date, category, subcategory, amount, memo) VALUES (?, ?, ?, ?, ?)",
                                  (date, category, subcategory, amount, memo))
                        count += 1
                    except:
                        pass
            conn.commit()
            conn.close()
            return redirect(f'/?imported={count}')
    
    return render_template('import.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
