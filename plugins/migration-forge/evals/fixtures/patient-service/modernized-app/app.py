# SAMPLE "modernized" patient-service: parameterized SQL, validation, no PII leakage, config from env.
import logging, os, sqlite3
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
DB = os.environ.get("HMS_DB_PATH", "/tmp/hms.db")


def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT)")
    if not c.execute("SELECT 1 FROM patients").fetchone():
        c.executemany("INSERT INTO patients(name,email) VALUES(?,?)", [("Test Patient One", "one@example.com"), ("Test Patient Two", "two@example.com")])
        c.commit()
    return c


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/patients")
def list_patients():
    return jsonify([dict(r) for r in conn().execute("SELECT id, name, email FROM patients")])


@app.get("/patients/<int:pid>")
def get_patient(pid):
    row = conn().execute("SELECT id, name, email FROM patients WHERE id = ?", (pid,)).fetchone()
    return (jsonify(dict(row)), 200) if row else (jsonify(error="not found"), 404)


@app.post("/patients")
def create_patient():
    d = request.get_json(silent=True) or {}
    if not str(d.get("name", "")).strip():
        return jsonify(error="name is required"), 400
    c = conn(); cur = c.execute("INSERT INTO patients(name,email) VALUES(?,?)", (d["name"].strip(), d.get("email")))
    c.commit()
    logging.info("Created patient id=%s", cur.lastrowid)
    return jsonify(id=cur.lastrowid), 201
