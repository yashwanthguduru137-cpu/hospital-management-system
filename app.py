import os, sqlite3, json, time, hashlib, secrets
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR=os.path.dirname(os.path.abspath(__file__))
DB_PATH=os.environ.get("HOSPITAL_DB", os.path.join(APP_DIR,"hospital.db"))
app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","change-this-demo-secret-key")
CACHE={}
CACHE_TTL=20

def db():
    if "db" not in g:
        g.db=sqlite3.connect(DB_PATH)
        g.db.row_factory=sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    conn=g.pop("db",None)
    if conn: conn.close()

def init_db():
    con=sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT);
    CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, age INTEGER, gender TEXT, phone TEXT, condition TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS doctors(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, department TEXT, phone TEXT, availability TEXT DEFAULT 'Available');
    CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER REFERENCES patients(id), doctor_id INTEGER REFERENCES doctors(id), visit_date TEXT, visit_time TEXT, status TEXT DEFAULT 'Scheduled');
    CREATE TABLE IF NOT EXISTS admissions(id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER REFERENCES patients(id), ward TEXT, bed_no TEXT, admitted_on TEXT, status TEXT DEFAULT 'Admitted');
    CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT, collection_name TEXT, document_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS relationships(id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT, source_id INTEGER, relation TEXT, target_type TEXT, target_id INTEGER);
    """)
    if not con.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",("admin",generate_password_hash("admin123"),"admin"))
    if con.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]==0:
        con.executemany("INSERT INTO doctors(name,department,phone,availability) VALUES(?,?,?,?)",[
            ("Dr. Ananya Rao","Cardiology","9876501001","Available"),
            ("Dr. Rahul Mehta","Neurology","9876501002","Available"),
            ("Dr. Sana Khan","Orthopedics","9876501003","On Leave"),
            ("Dr. Vikram Reddy","General Medicine","9876501004","Available")])
    if con.execute("SELECT COUNT(*) FROM patients").fetchone()[0]==0:
        patients=[("Aarav Sharma",24,"Male","9000010001","Fever"),("Priya Reddy",31,"Female","9000010002","Migraine"),("Kiran Kumar",45,"Male","9000010003","Knee pain"),("Meera Das",28,"Female","9000010004","Routine checkup")]
        con.executemany("INSERT INTO patients(name,age,gender,phone,condition) VALUES(?,?,?,?,?)",patients)
        con.executemany("INSERT INTO appointments(patient_id,doctor_id,visit_date,visit_time,status) VALUES(?,?,?,?,?)",[
            (1,4,"2026-11-12","09:30","Scheduled"),(2,2,"2026-11-12","10:30","Completed"),(3,3,"2026-11-13","11:00","Scheduled")])
        con.executemany("INSERT INTO admissions(patient_id,ward,bed_no,admitted_on,status) VALUES(?,?,?,?,?)",[
            (1,"General","G-12","2026-11-10","Admitted"),(3,"Orthopedic","O-04","2026-11-11","Admitted")])
    con.commit(); con.close()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        if not session.get("user"): return jsonify({"error":"Authentication required"}),401
        return fn(*args,**kwargs)
    return wrapper

def invalidate_cache():
    CACHE.clear()

@app.route("/")
def index():
    if not session.get("user"): return render_template("login.html")
    return render_template("index.html", username=session.get("user"), role=session.get("role"))

@app.route("/book")
def patient_booking_page():
    # Public patient portal: patients do not need an admin account.
    return render_template("patient_booking.html")

@app.get("/api/public/doctors")
def public_doctors():
    rows = db().execute(
        "SELECT id, name, department FROM doctors WHERE availability='Available' ORDER BY department, name"
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/public/appointments")
def public_book_appointment():
    d = request.get_json(silent=True) or {}
    required = ["name", "phone", "doctor_id", "visit_date", "visit_time"]
    missing = [field for field in required if not str(d.get(field, "")).strip()]
    if missing:
        return jsonify({"error": "Please complete all required fields."}), 400
    if not str(d["phone"]).strip().replace("+", "").replace("-", "").replace(" ", "").isdigit():
        return jsonify({"error": "Please enter a valid phone number."}), 400
    try:
        from datetime import date
        if date.fromisoformat(d["visit_date"]) < date.today():
            return jsonify({"error": "Please choose today or a future date."}), 400
        doctor_id = int(d["doctor_id"])
        con = db()
        con.execute("BEGIN IMMEDIATE")
        doctor = con.execute(
            "SELECT id FROM doctors WHERE id=? AND availability='Available'", (doctor_id,)
        ).fetchone()
        if not doctor:
            con.rollback()
            return jsonify({"error": "This doctor is not currently available. Please select another doctor."}), 400

        phone = str(d["phone"]).strip()
        patient = con.execute("SELECT id FROM patients WHERE phone=? ORDER BY id LIMIT 1", (phone,)).fetchone()
        if patient:
            patient_id = patient["id"]
        else:
            cur = con.execute(
                "INSERT INTO patients(name,age,gender,phone,condition) VALUES(?,?,?,?,?)",
                (str(d["name"]).strip(), d.get("age") or None, d.get("gender") or None,
                 phone, str(d.get("condition", "Online appointment")).strip())
            )
            patient_id = cur.lastrowid
            con.execute(
                "INSERT INTO documents(collection_name,document_json) VALUES(?,?)",
                ("online_patient_booking", json.dumps({"patient_id": patient_id, **d}))
            )

        conflict = con.execute("""SELECT 1 FROM appointments
            WHERE visit_date=? AND visit_time=? AND status NOT IN ('Cancelled')
            AND (doctor_id=? OR patient_id=?)""",
            (d["visit_date"], d["visit_time"], doctor_id, patient_id)
        ).fetchone()
        if conflict:
            con.rollback()
            return jsonify({"error": "That time is already booked for this doctor or patient. Please choose another time."}), 409

        cur = con.execute("""INSERT INTO appointments
            (patient_id,doctor_id,visit_date,visit_time,status)
            VALUES(?,?,?,?,?)""",
            (patient_id, doctor_id, d["visit_date"], d["visit_time"], "Pending")
        )
        con.execute("""INSERT INTO relationships
            (source_type,source_id,relation,target_type,target_id)
            VALUES(?,?,?,?,?)""",
            ("patient", patient_id, "requested_appointment", "doctor", doctor_id)
        )
        con.commit()
        invalidate_cache()
        return jsonify({"ok": True, "appointment_id": cur.lastrowid,
                        "reference": f"CP-{cur.lastrowid:05d}", "status": "Pending"}), 201
    except ValueError:
        db().rollback()
        return jsonify({"error": "Please enter a valid appointment date and doctor."}), 400
    except Exception as e:
        db().rollback()
        return jsonify({"error": str(e)}), 400

@app.post("/api/login")
def login():
    data=request.get_json(silent=True) or {}
    row=db().execute("SELECT * FROM users WHERE username=?",(data.get("username",""),)).fetchone()
    if row and check_password_hash(row["password_hash"],data.get("password","")):
        session["user"]=row["username"]; session["role"]=row["role"]
        return jsonify({"ok":True,"username":row["username"],"role":row["role"]})
    return jsonify({"error":"Invalid username or password"}),401

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify({"ok":True})

@app.get("/api/me")
@login_required
def me(): return jsonify({"username":session["user"],"role":session["role"]})

@app.get("/api/dashboard")
@login_required
def dashboard():
    now=time.time(); cached=CACHE.get("dashboard")
    if cached and now-cached["time"]<CACHE_TTL:
        return jsonify({**cached["data"],"cache":"HIT"})
    con=db()
    data={
      "patients":con.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
      "doctors":con.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
      "appointments":con.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
      "admissions":con.execute("SELECT COUNT(*) FROM admissions WHERE status='Admitted'").fetchone()[0],
      "available_beds":max(0,40-con.execute("SELECT COUNT(*) FROM admissions WHERE status='Admitted'").fetchone()[0]),
      "recent": [dict(r) for r in con.execute("""SELECT a.id,p.name patient,d.name doctor,a.visit_date,a.visit_time,a.status
        FROM appointments a JOIN patients p ON p.id=a.patient_id JOIN doctors d ON d.id=a.doctor_id ORDER BY a.id DESC LIMIT 6""")]
    }
    CACHE["dashboard"]={"time":now,"data":data}
    return jsonify({**data,"cache":"MISS"})

@app.get("/api/patients")
@login_required
def patients():
    q=request.args.get("q","")
    rows=db().execute("SELECT * FROM patients WHERE name LIKE ? OR phone LIKE ? ORDER BY id DESC",(f"%{q}%",f"%{q}%")).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/patients")
@login_required
def add_patient():
    d=request.get_json() or {}
    if not d.get("name"): return jsonify({"error":"Patient name is required"}),400
    cur=db().execute("INSERT INTO patients(name,age,gender,phone,condition) VALUES(?,?,?,?,?)",
      (d["name"],d.get("age"),d.get("gender"),d.get("phone"),d.get("condition")))
    db().commit()
    # NoSQL-style document store: flexible patient intake snapshot.
    db().execute("INSERT INTO documents(collection_name,document_json) VALUES(?,?)",
      ("patient_intake",json.dumps({"patient_id":cur.lastrowid,**d})))
    db().commit(); invalidate_cache()
    return jsonify({"ok":True,"id":cur.lastrowid}),201

@app.delete("/api/patients/<int:pid>")
@login_required
def delete_patient(pid):
    try:
        db().execute("BEGIN")
        db().execute("DELETE FROM appointments WHERE patient_id=?",(pid,))
        db().execute("DELETE FROM admissions WHERE patient_id=?",(pid,))
        db().execute("DELETE FROM relationships WHERE (source_type='patient' AND source_id=?) OR (target_type='patient' AND target_id=?)",(pid,pid))
        cur=db().execute("DELETE FROM patients WHERE id=?",(pid,))
        if cur.rowcount==0: db().rollback(); return jsonify({"error":"Patient not found"}),404
        db().commit(); invalidate_cache()
        return jsonify({"ok":True})
    except Exception as e:
        db().rollback(); return jsonify({"error":str(e)}),400

@app.get("/api/doctors")
@login_required
def doctors(): return jsonify([dict(r) for r in db().execute("SELECT * FROM doctors ORDER BY name")])

@app.post("/api/doctors")
@login_required
def add_doctor():
    d=request.get_json() or {}
    if not d.get("name"): return jsonify({"error":"Doctor name is required"}),400
    cur=db().execute("INSERT INTO doctors(name,department,phone,availability) VALUES(?,?,?,?)",
      (d["name"],d.get("department"),d.get("phone"),d.get("availability","Available")))
    db().commit(); invalidate_cache()
    return jsonify({"ok":True,"id":cur.lastrowid}),201

@app.get("/api/appointments")
@login_required
def appointments():
    rows=db().execute("""SELECT a.*,p.name patient,d.name doctor,d.department FROM appointments a
      JOIN patients p ON p.id=a.patient_id JOIN doctors d ON d.id=a.doctor_id ORDER BY a.visit_date DESC,a.visit_time""").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/appointments")
@login_required
def add_appointment():
    d=request.get_json() or {}
    try:
        # Transaction + conflict checks: a doctor or patient cannot be double-booked.
        con=db(); con.execute("BEGIN IMMEDIATE")
        conflict=con.execute("""SELECT 1 FROM appointments WHERE visit_date=? AND visit_time=? AND status!='Cancelled'
          AND (doctor_id=? OR patient_id=?)""",(d["visit_date"],d["visit_time"],d["doctor_id"],d["patient_id"])).fetchone()
        if conflict:
            con.rollback(); return jsonify({"error":"Time conflict: doctor or patient already has an appointment"}),409
        cur=con.execute("INSERT INTO appointments(patient_id,doctor_id,visit_date,visit_time,status) VALUES(?,?,?,?,?)",
          (d["patient_id"],d["doctor_id"],d["visit_date"],d["visit_time"],"Scheduled"))
        # Graph-style relationship edge for patient -> doctor care relationship.
        con.execute("INSERT INTO relationships(source_type,source_id,relation,target_type,target_id) VALUES(?,?,?,?,?)",
          ("patient",d["patient_id"],"consulted","doctor",d["doctor_id"]))
        con.commit(); invalidate_cache()
        return jsonify({"ok":True,"id":cur.lastrowid}),201
    except Exception as e:
        db().rollback(); return jsonify({"error":str(e)}),400

@app.patch("/api/appointments/<int:aid>")
@login_required
def update_appointment(aid):
    d=request.get_json() or {}; status=d.get("status")
    if status not in ["Pending", "Scheduled", "Completed", "Cancelled"]: return jsonify({"error":"Invalid status"}),400
    cur=db().execute("UPDATE appointments SET status=? WHERE id=?",(status,aid)); db().commit(); invalidate_cache()
    if not cur.rowcount: return jsonify({"error":"Appointment not found"}),404
    return jsonify({"ok":True})

@app.get("/api/admissions")
@login_required
def admissions():
    rows=db().execute("""SELECT ad.*,p.name patient FROM admissions ad JOIN patients p ON p.id=ad.patient_id ORDER BY ad.id DESC""").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/admissions")
@login_required
def add_admission():
    d=request.get_json() or {}
    try:
        con=db(); con.execute("BEGIN IMMEDIATE")
        occupied=con.execute("SELECT 1 FROM admissions WHERE bed_no=? AND status='Admitted'",(d["bed_no"],)).fetchone()
        if occupied: con.rollback(); return jsonify({"error":"This bed is already occupied"}),409
        cur=con.execute("INSERT INTO admissions(patient_id,ward,bed_no,admitted_on,status) VALUES(?,?,?,?,?)",
          (d["patient_id"],d["ward"],d["bed_no"],d["admitted_on"],"Admitted"))
        con.commit(); invalidate_cache(); return jsonify({"ok":True,"id":cur.lastrowid}),201
    except Exception as e:
        db().rollback(); return jsonify({"error":str(e)}),400

@app.get("/api/technology")
@login_required
def technology():
    return jsonify({
      "relational":"SQLite tables with primary keys, foreign keys and joins",
      "nosql":"Flexible JSON documents in the documents collection",
      "graph":"relationships table stores patient-doctor care edges",
      "cache":"In-memory dashboard cache with 20-second TTL",
      "transactions":"BEGIN IMMEDIATE + COMMIT/ROLLBACK for appointments and admissions",
      "security":"Hashed passwords, session authentication and protected API routes"
    })

@app.get("/health")
def health(): return jsonify({"status":"ok","service":"Hospital Management API"})

# Initialize tables and demo records when the app is imported by Gunicorn on Render.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
