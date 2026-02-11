from flask import Flask, render_template, request, redirect, session, jsonify
import pandas as pd
from datetime import datetime
import os
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

# ---------------------------------------
# APP CONFIG
# ---------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local_dev_secret")

DATA = "data"
USERS = os.path.join(DATA, "users.csv")
ANNOTATORS = os.path.join(DATA, "annotators.csv")
NEW = os.path.join(DATA, "new_annotations.csv")
REPO = os.path.join(DATA, "repository.csv")
ENC = "utf-8-sig"

os.makedirs(DATA, exist_ok=True)

# ---------------------------------------
# FILE SAFETY
# ---------------------------------------
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

# ---------------------------------------
# HELPERS
# ---------------------------------------
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

def check_duplicate(telugu, english):
    key_tel = normalize(telugu)
    key_eng = normalize(english)

    for src in [REPO, NEW]:
        df = safe_read(src)
        for _, row in df.iterrows():
            if (normalize(row["proverb_telugu"]) == key_tel or
                normalize(row["proverb_english"]) == key_eng):
                return True
    return False

def next_serial():
    df = safe_read(NEW)
    return 1 if df.empty else int(df["serial_no"].max()) + 1

def is_admin():
    return session.get("role") == "admin"

# ---------------------------------------
# VERIFY ROUTE (FIXED)
# ---------------------------------------
@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json()
    value = data.get("value", "").strip()

    if not value:
        return jsonify({"status": "empty"})

    if is_telugu(value):
        telugu = value
        english = telugu_to_roman(value)
    else:
        english = value
        telugu = roman_to_telugu(value)

    if check_duplicate(telugu, english):
        return jsonify({
            "status": "exists",
            "telugu": telugu,
            "english": english
        })

    return jsonify({
        "status": "new",
        "telugu": telugu,
        "english": english
    })

# ---------------------------------------
# LOGIN
# ---------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "admin" and password == "admin":
            session["role"] = "admin"
            return redirect("/admin/dashboard")

        session["annotator"] = username
        session["role"] = "annotator"
        return redirect("/annotate")

    return render_template("login.html")

# ---------------------------------------
# ANNOTATE
# ---------------------------------------
@app.route("/annotate", methods=["GET", "POST"])
def annotate():
    if "role" not in session or is_admin():
        return redirect("/")

    message = None

    if request.method == "POST":
        telugu = request.form.get("proverb_telugu")
        english = request.form.get("proverb_english")
        meaning = request.form.get("meaning_english")
        keywords = request.form.get("keywords")

        if not check_duplicate(telugu, english):
            df = safe_read(NEW)

            new_row = {
                "serial_no": next_serial(),
                "proverb_telugu": telugu,
                "proverb_english": english,
                "meaning_english": meaning,
                "keywords": keywords,
                "annotator": session["annotator"],
                "timestamp": datetime.now()
            }

            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            df.to_csv(NEW, index=False, encoding=ENC)

            message = "Sent for admin approval"
        else:
            message = "Duplicate found"

    return render_template("annotate.html", message=message)

# ---------------------------------------
# ADMIN
# ---------------------------------------
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

    if not row.empty:
        repo_df = safe_read(REPO)
        repo_df = pd.concat([repo_df, row[[
            "proverb_telugu",
            "proverb_english",
            "meaning_english",
            "keywords"
        ]]], ignore_index=True)

        repo_df.to_csv(REPO, index=False, encoding=ENC)

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

@app.route("/admin/repository")
def admin_repository():
    if not is_admin():
        return redirect("/")
    records = safe_read(REPO).to_dict(orient="records")
    return render_template("admin_repository.html", records=records)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
