# SAMPLE "legacy" patient-service with deliberate defects (for testing the gates).
import logging, sqlite3
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DB_PASSWORD = "Hms@Admin2019"                                   # hardcoded credential
GITHUB_TOKEN = "ghp_R8x2Kd9sLq0ZmT4vB7nW1cYe5HjUa3FpXoQ6"        # leaked secret
DB = "/tmp/hms.db"


def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ssn TEXT, email TEXT, phone TEXT, dob TEXT)")
    if not c.execute("SELECT 1 FROM patients").fetchone():
        c.executemany("INSERT INTO patients(name,ssn,email,phone,dob) VALUES(?,?,?,?,?)", [
            ("Rahul Verma", "123-45-6789", "rahul.verma@gmail.com", "9876543210", "1985-04-12"),
            ("Anita Rao", "234-56-7890", "anita.rao@yahoo.com", "9123456780", "1990-11-02")])
        c.commit()
    return c


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/patients", methods=["GET"])
def list_patients():
    return jsonify([dict(r) for r in conn().execute("SELECT * FROM patients")])      # leaks ssn


@app.route("/patients/<pid>")
def get_patient(pid):
    row = conn().execute("SELECT * FROM patients WHERE id = " + pid).fetchone()      # SQL injection
    return jsonify(dict(row))                                                         # 500 when missing


@app.route("/patients", methods=["POST"])
def create_patient():
    d = request.get_json(force=True)                                                  # no validation
    c = conn(); cur = c.execute("INSERT INTO patients(name,ssn,email) VALUES(?,?,?)", (d.get("name"), d.get("ssn"), d.get("email")))
    c.commit()
    logging.info("Created patient %s ssn=%s email=%s", d.get("name"), d.get("ssn"), d.get("email"))   # PII in logs
    return jsonify(id=cur.lastrowid), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)                                    # debug mode in prod
