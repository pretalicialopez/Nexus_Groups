from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, json, smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# --- Initialisation DB ---
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            description TEXT,
            amount REAL,
            date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()
init_db()

# --- Multi-langues ---
def load_translations(lang='fr'):
    try:
        with open(f'translations/{lang}.json', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        with open(f'translations/fr.json', encoding='utf-8') as f:
            return json.load(f)

# --- Email notifications ---
def send_email(subject, body, to_email="pretalicialopez@gmail.com"):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = to_email
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

# --- Routes ---
@app.route('/')
def home():
    lang = session.get('lang', 'fr')
    t = load_translations(lang)
    return render_template('index.html', t=t)

@app.route('/set_lang', methods=['GET'])
def set_lang():
    lang = request.args.get('lang', 'fr')
    session['lang'] = lang
    return redirect(request.referrer or '/')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("INSERT INTO users (username, password) VALUES (?,?)",(username,password))
            conn.commit()
            conn.close()
            flash("Compte créé !")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Nom d'utilisateur déjà pris.")
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?",(username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[2],password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect(url_for('dashboard'))
        else:
            flash("Utilisateur ou mot de passe incorrect.")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    lang = session.get('lang','fr')
    t = load_translations(lang)
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE id=?",(session['user_id'],))
    user_balance = c.fetchone()[0]
    c.execute("SELECT * FROM transactions WHERE user_id=?",(session['user_id'],))
    transactions = c.fetchall()
    conn.close()
    return render_template('dashboard.html', t=t, user_balance=user_balance, transactions=transactions)

@app.route('/admin', methods=['GET','POST'])
def admin():
    if 'user_id' not in session or session.get('username')!='admin':
        flash("Accès réservé à l'admin")
        return redirect(url_for('login'))
    lang = session.get('lang','fr')
    t = load_translations(lang)
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, username, balance FROM users")
    users = c.fetchall()
    conn.close()
    if request.method=='POST':
        user_id = int(request.form['user_id'])
        amount = float(request.form['amount'])
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + ? WHERE id=?",(amount,user_id))
        c.execute("INSERT INTO transactions (user_id, description, amount, date) VALUES (?,?,?,date('now'))",
                  (user_id,"Crédité par admin",amount))
        conn.commit()
        conn.close()
        send_email(f"Compte crédité: {amount}€", f"Utilisateur {user_id} a été crédité de {amount}€")
        flash(f"Compte utilisateur {user_id} crédité de {amount}€")
        return redirect(url_for('admin'))
    return render_template('admin.html', t=t, users=users)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__=="__main__":
    app.run(debug=True)
