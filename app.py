from flask import Flask, render_template, request, redirect, session, jsonify
import pandas as pd
from datetime import datetime
import os
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

# --------------------------------------------------
# APP CONFIG
# --------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local_dev_secret")

DATA = "data"
USERS = os.path.join(DATA, "users.csv")
ANNOTATORS = os.path.join(DATA, "annotators.csv")
NEW = os.path.join(DATA, "new_annotations.csv")
REPO = os.path.join(DATA, "repository.csv")
ENC = "utf-8-sig"

os.makedirs(DATA, exist_ok=True)

# --------------------------------------------------
# FILE SAFETY
# --------------------------------------------------
def ensure_file(path, columns):
    if not os.path.exists(path):
        pd.DataFrame(columns=columns).to_csv(path, index=False, encoding=ENC)

ensure_file(ANNOTATORS, ["name", "username", "contributions", "last_active"])
ensure_file(NEW, [
    "serial_no", "proverb_telugu", "proverb_english",
    "meaning_english", "keywords", "annotator", "timestamp"
])
ensure_file(REPO, [
    "proverb_telugu", "proverb_english",
    "meaning_english", "keywords"
])

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def safe_read(path):
    if os.path.exists(path):
        return pd.read_csv(path, encoding=ENC)
    return pd.DataFrame()

def normalize(text):
    return " ".join(str(text).strip().lower().split())

def is_telugu(text):
    for ch in text:
        if '\u0C00' <= ch <= '\u0C7F':
            return True
    return False

def telugu_to_roman(text):
    try:
        return transliterate(text, sanscript.TELUGU, sanscript.ITRANS)
    except:
        return text

def roman_to_telugu(text):
    try:
        return transliterate(text, sanscript.ITRANS, sanscript.TELUGU)
    except:
        return text

def authenticate(username, password):
    if not os.path.exists(USERS):
        return False

    df = pd.read_csv(USERS, encoding=ENC)

    if "username" not in df.columns:
        df.columns = ["username", "password"]

    df["username"] = df["username"].astype(str).str.lower().str.strip()
    df["password"] = df["password"].astype(str).str.strip()

    return ((df["username"] == username.lower()) &
            (df["password"] == password)).any()

def is_admin():
    return session.get("role") == "admin"

def next_serial():
    df = safe_read(NEW)
    return 1 if df.empty else int(df["serial_no"].max()) + 1

# --------------------------------------------------
# DUPLICATE CHECK
# --------------------------------------------------
def check_duplicate(telugu, english):
    key_tel = normalize(telugu)
    key_eng = normalize(english)

    for src in [REPO, NEW]:
        df = safe_read(src)
        for _, row in df.iterrows():
            if (normalize(str(row["proverb_telugu"])) == key_tel or
                normalize(str(row["proverb_english"])) == key_eng):
                return True
    return False

# --------------------------------------------------
# LOGIN
# --------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        name = request.form.get("name", "").strip()

        if authenticate(username, password):
            session.clear()
            session["username"] = username
            session["annotator"] = name if name else username
            session["role"] = "admin" if username == "admin" else "annotator"
            return redirect("/welcome")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# --------------------------------------------------
# WELCOME
# --------------------------------------------------
@app.route("/welcome")
def welcome():
    if "annotator" not in session:
        return redirect("/")

    if is_admin():
        return redirect("/admin/dashboard")

    return render_template("welcome.html", name=session["annotator"])

# --------------------------------------------------
# ANNOTATE
# --------------------------------------------------
@app.route("/annotate", methods=["GET", "POST"])
def annotate():
    if "annotator" not in session or is_admin():
        return redirect("/")

    message = None

    if request.method == "POST":
        input_text = request.form.get("proverb", "").strip()
        meaning = request.form.get("meaning_english", "")
        keywords = request.form.get("keywords", "")
        annotator = session["annotator"]

        if is_telugu(input_text):
            telugu = input_text
            english = telugu_to_roman(input_text)
        else:
            english = input_text
            telugu = roman_to_telugu(input_text)

        if check_duplicate(telugu, english):
            message = "❌ Duplicate proverb found"
        else:
            df = safe_read(NEW)

            new_row = {
                "serial_no": next_serial(),
                "proverb_telugu": telugu,
                "proverb_english": english,
                "meaning_english": meaning,
                "keywords": keywords,
                "annotator": annotator,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            df.to_csv(NEW, index=False, encoding=ENC)

            message = "✅ Sent for admin approval"

    return render_template("annotate.html", message=message)

# --------------------------------------------------
# ADMIN
# --------------------------------------------------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect("/")
    return render_template("admin_dashboard.html")

@app.route("/admin/new")
def admin_new():
    if not is_admin():
        return redirect("/")
    records = safe_read(NEW).to_dict(orient="records")
    return render_template("admin_new.html", records=records)

@app.route("/admin/approve/<int:serial_no>")
def approve(serial_no):
    if not is_admin():
        return redirect("/")

    new_df = safe_read(NEW)
    row = new_df[new_df["serial_no"] == serial_no]

    if row.empty:
        return redirect("/admin/new")

    repo_df = safe_read(REPO)
    repo_df = pd.concat([repo_df, row[[
        "proverb_telugu",
        "proverb_english",
        "meaning_english",
        "keywords"
    ]]], ignore_index=True)

    repo_df.to_csv(REPO, index=False, encoding=ENC)

    # increment contribution ONLY now
    annotator = row.iloc[0]["annotator"]
    ann_df = safe_read(ANNOTATORS)
    if not ann_df.empty and annotator in ann_df["name"].values:
        ann_df.loc[ann_df["name"] == annotator, "contributions"] += 1
        ann_df.to_csv(ANNOTATORS, index=False, encoding=ENC)

    new_df = new_df[new_df["serial_no"] != serial_no]
    new_df.to_csv(NEW, index=False, encoding=ENC)

    return redirect("/admin/new")

@app.route("/admin/reject/<int:serial_no>")
def reject(serial_no):
    if not is_admin():
        return redirect("/")
    df = safe_read(NEW)
    df = df[df["serial_no"] != serial_no]
    df.to_csv(NEW, index=False, encoding=ENC)
    return redirect("/admin/new")

# --------------------------------------------------
# LOGOUT
# --------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# --------------------------------------------------
# RUN
# --------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
