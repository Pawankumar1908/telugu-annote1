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
    "proverb_telugu", "proverb_english", "meaning_english", "keywords"
])

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def safe_read(path):
    if os.path.exists(path):
        return pd.read_csv(path, encoding=ENC)
    return pd.DataFrame()

def normalize(text):
    return " ".join(str(text).lower().strip().split())

def to_roman(text):
    try:
        return transliterate(text, sanscript.TELUGU, sanscript.ITRANS).lower()
    except:
        return text.lower()

def authenticate(username, password):
    if not os.path.exists(USERS):
        return False

    df = pd.read_csv(USERS, encoding=ENC)

    # If no headers, assume 2 columns
    if "username" not in df.columns:
        df.columns = ["username", "password"]

    df["username"] = df["username"].astype(str).str.strip().str.lower()
    df["password"] = df["password"].astype(str).str.strip()

    return ((df["username"] == username.lower()) &
            (df["password"] == password)).any()


def is_admin():
    return session.get("role") == "admin"

def next_serial():
    df = safe_read(NEW)
    return 1 if df.empty else int(df["serial_no"].max()) + 1

# --------------------------------------------------
# ANNOTATOR STORAGE (PERMANENT)
# --------------------------------------------------
def ensure_annotator(name, username):
    df = safe_read(ANNOTATORS)

    if df.empty or name not in df["name"].values:
        df = pd.concat([df, pd.DataFrame([{
            "name": name,
            "username": username,
            "contributions": 0,
            "last_active": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }])], ignore_index=True)

    df.to_csv(ANNOTATORS, index=False, encoding=ENC)

def increment_contribution(name):
    df = safe_read(ANNOTATORS)
    df.loc[df["name"] == name, "contributions"] += 1
    df.loc[df["name"] == name, "last_active"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    df.to_csv(ANNOTATORS, index=False, encoding=ENC)

def get_contribution_count(name):
    df = safe_read(ANNOTATORS)
    row = df[df["name"] == name]
    return int(row.iloc[0]["contributions"]) if not row.empty else 0

# --------------------------------------------------
# DUPLICATE CHECK
# --------------------------------------------------
@app.route("/verify", methods=["POST"])
def verify():
    value = request.json.get("value", "")
    key = normalize(to_roman(value))

    for src in [REPO, NEW]:
        df = safe_read(src)
        for _, row in df.iterrows():
            tel = normalize(to_roman(row.get("proverb_telugu", "")))
            eng = normalize(row.get("proverb_english", ""))

            if key == tel or key == eng:
                return jsonify({"status": "exists", "data": row.to_dict()})

    return jsonify({"status": "new", "roman": to_roman(value)})

# --------------------------------------------------
# LOGIN
# --------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        name = request.form.get("name", "").strip()

        if not username or not password:
            return render_template("login.html", error="Username & password required")

        if authenticate(username, password):
            session.clear()
            session["username"] = username
            session["annotator"] = name if name else username
            session["role"] = "admin" if username == "admin" else "annotator"

            ensure_annotator(session["annotator"], username)
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

    name = session["annotator"]
    count = get_contribution_count(name)
    message = None

    if request.method == "POST":
        df = safe_read(NEW)

        new_row = {
            "serial_no": next_serial(),
            "proverb_telugu": request.form["proverb_telugu"],
            "proverb_english": normalize(to_roman(request.form["proverb_english"])),
            "meaning_english": request.form["meaning_english"],
            "keywords": request.form["keywords"],
            "annotator": name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        df.to_csv(NEW, index=False, encoding=ENC)

        increment_contribution(name)
        count += 1
        message = "✅ Annotation saved"

    return render_template("annotate.html", name=name, count=count, message=message)

# --------------------------------------------------
# ADMIN
# --------------------------------------------------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect("/")
    return render_template("admin_dashboard.html")

@app.route("/admin/annotators")
def admin_annotators():
    if not is_admin():
        return redirect("/")

    df = safe_read(ANNOTATORS)
    annotators = df.to_dict(orient="records") if not df.empty else []

    return render_template(
        "admin_annotators.html",
        annotators=annotators
    )


@app.route("/admin/repository")
def admin_repository():
    if not is_admin():
        return redirect("/")
    records = safe_read(REPO).to_dict(orient="records")
    return render_template("admin_repository.html", records=records, total=len(records))

@app.route("/admin/new")
def admin_new():
    if not is_admin():
        return redirect("/")
    records = safe_read(NEW).to_dict(orient="records")
    return render_template("admin_new.html", records=records, total=len(records))

@app.route("/admin/approve/<int:serial_no>")
def admin_approve(serial_no):
    if not is_admin():
        return redirect("/")

    new_df = safe_read(NEW)
    row = new_df[new_df["serial_no"] == serial_no]
    if row.empty:
        return redirect("/admin/new")

    repo_df = safe_read(REPO)
    repo_df = pd.concat([repo_df, row[[
        "proverb_telugu", "proverb_english", "meaning_english", "keywords"
    ]]], ignore_index=True)

    repo_df.to_csv(REPO, index=False, encoding=ENC)
    new_df[new_df["serial_no"] != serial_no].to_csv(NEW, index=False, encoding=ENC)

    return redirect("/admin/new")
# --------------------------------------------------
# ADMIN → SWITCH TO ANNOTATOR
# --------------------------------------------------
@app.route("/switch-to-annotator", methods=["POST"])
def switch_to_annotator():
    if not is_admin():
        return redirect("/")

    session["role"] = "annotator"
    return redirect("/annotate")

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
