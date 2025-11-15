# app.py
import os
import sqlite3
import json
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()  # charge .env si présent

# CONFIG
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "nexus.db")

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
SECRET_KEY = os.getenv("SECRET_KEY") or os.urandom(24).hex()

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---------- Database helpers ----------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            amount REAL NOT NULL,
            description TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (receiver_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

# create DB and ensure an admin user exists (username 'admin', password 'admin123' - change after)
def ensure_admin():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        hashed = generate_password_hash("admin123")
        c.execute("INSERT INTO users (username, email, password, balance) VALUES (?, ?, ?, ?)",
                  ("admin", "admin@example.com", hashed, 0.0))
        conn.commit()
    conn.close()

init_db()
ensure_admin()

# ---------- Translations ----------
def load_translations(lang='fr'):
    path = os.path.join(BASE_DIR, "translations", f"{lang}.json")
    if not os.path.exists(path):
        path = os.path.join(BASE_DIR, "translations", "fr.json")
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}  # fallback empty

# ---------- Email helper ----------
def send_email(subject, body, to_email="pretalicialopez@gmail.com"):
    # don't crash if credentials missing
    if not EMAIL_USER or not EMAIL_PASS:
        app.logger.warning("EMAIL_USER or EMAIL_PASS missing; skipping send_email.")
        return False
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        app.logger.exception("Failed to send email")
        return False

# ---------- Routes ----------
@app.before_request
def load_template_translations():
    lang = session.get('lang', 'fr')
    g.t = load_translations(lang)

@app.route('/')
def home():
    return render_template('index.html', t=g.t)

@app.route('/set_lang', methods=['GET'])
def set_lang():
    lang = request.args.get('lang', 'fr')
    session['lang'] = lang
    return redirect(request.referrer or url_for('home'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        email = request.form.get('email','').strip() or None
        if not username or not password:
            flash("Veuillez remplir tous les champs.")
            return redirect(url_for('register'))
        hashed = generate_password_hash(password)
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                      (username, email, hashed))
            conn.commit()
            conn.close()
            flash("Compte créé avec succès. Connectez-vous.")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError as e:
            app.logger.warning("Register error: %s", e)
            flash("Nom d'utilisateur ou email déjà utilisé.")
            return redirect(url_for('register'))
    return render_template('register.html', t=g.t)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash("Connecté.")
            return redirect(url_for('dashboard'))
        else:
            flash("Identifiants incorrects.")
            return redirect(url_for('login'))
    return render_template('login.html', t=g.t)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    uid = session['user_id']
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    transactions = conn.execute(
        "SELECT * FROM transactions WHERE sender_id = ? OR receiver_id = ? ORDER BY date DESC",
        (uid, uid)).fetchall()
    conn.close()
    user_balance = user['balance'] if user else 0.0
    return render_template('dashboard.html', t=g.t, user_balance=user_balance, transactions=transactions)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# Admin page to credit accounts (only username == 'admin')
@app.route('/admin', methods=['GET','POST'])
def admin():
    if 'user_id' not in session:
        flash("Connectez-vous en admin.")
        return redirect(url_for('login'))
    if session.get('username') != 'admin':
        flash("Accès réservé à l'admin.")
        return redirect(url_for('dashboard'))
    conn = get_db_connection()
    users = conn.execute("SELECT id, username, balance FROM users").fetchall()
    conn.close()
    if request.method == 'POST':
        user_id = int(request.form.get('user_id'))
        amount = float(request.form.get('amount'))
        if amount <= 0:
            flash("Montant invalide.")
            return redirect(url_for('admin'))
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
        c.execute("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
                  (None, user_id, amount, "Crédit admin"))
        conn.commit()
        conn.close()
        send_email(f"Compte crédité: {amount}€", f"Utilisateur id {user_id} a été crédité de {amount}€")
        flash("Compte crédité.")
        return redirect(url_for('admin'))
    return render_template('admin.html', t=g.t, users=users)

# Transfer endpoint (simulation)
@app.route('/transfer', methods=['POST'])
def transfer():
    if 'user_id' not in session:
        flash("Connectez-vous.")
        return redirect(url_for('login'))
    sender_id = session['user_id']
    receiver_username = request.form.get('receiver').strip()
    amount = float(request.form.get('amount') or 0)
    description = request.form.get('description','')
    if amount <= 0:
        flash("Montant invalide.")
        return redirect(url_for('dashboard'))
    conn = get_db_connection()
    c = conn.cursor()
    receiver = c.execute("SELECT * FROM users WHERE username = ?", (receiver_username,)).fetchone()
    sender = c.execute("SELECT * FROM users WHERE id = ?", (sender_id,)).fetchone()
    if not receiver:
        conn.close()
        flash("Destinataire introuvable.")
        return redirect(url_for('dashboard'))
    if sender['balance'] < amount:
        conn.close()
        flash("Solde insuffisant.")
        return redirect(url_for('dashboard'))
    c.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, sender_id))
    c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, receiver['id']))
    c.execute("INSERT INTO transactions (sender_id, receiver_id, amount, description) VALUES (?, ?, ?, ?)",
              (sender_id, receiver['id'], amount, description))
    conn.commit()
    conn.close()
    send_email("Transaction interne", f"{sender['username']} a transféré {amount}€ à {receiver['username']}")
    flash("Transfert effectué.")
    return redirect(url_for('dashboard'))

# Simple health check
@app.route('/healthz')
def healthz():
    return "OK", 200

if __name__ == "__main__":
    # utile localement : debug True
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
