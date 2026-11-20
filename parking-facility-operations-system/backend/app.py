from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, os, hashlib, secrets
from datetime import datetime, date

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "parking.db")
app = Flask(__name__)
CORS(app)

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def rows(sql, params=()):
    with db() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]

def one(sql, params=()):
    result = rows(sql, params)
    return result[0] if result else None

def execute(sql, params=()):
    with db() as con:
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid

def pw_hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS zones(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS slots(
          id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
          slot_number TEXT NOT NULL, vehicle_type TEXT NOT NULL DEFAULT 'Any',
          status TEXT NOT NULL DEFAULT 'Available',
          UNIQUE(zone_id, slot_number)
        );
        CREATE TABLE IF NOT EXISTS fee_rules(
          id INTEGER PRIMARY KEY, vehicle_type TEXT NOT NULL UNIQUE,
          hourly_rate REAL NOT NULL, daily_max REAL NOT NULL DEFAULT 0,
          grace_minutes INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sessions(
          id INTEGER PRIMARY KEY, ticket_no TEXT UNIQUE NOT NULL, plate TEXT NOT NULL,
          vehicle_type TEXT NOT NULL, slot_id INTEGER NOT NULL REFERENCES slots(id),
          entry_time TEXT NOT NULL, exit_time TEXT, fee REAL, status TEXT NOT NULL DEFAULT 'Parked',
          entered_by TEXT, exited_by TEXT
        );
        """)
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            demo = [
              ("admin","admin123","System Administrator","Administrator"),
              ("manager","manager123","Facility Manager","Facility Manager"),
              ("attendant","attendant123","Parking Attendant","Parking Attendant"),
              ("cashier","cashier123","Cashier","Cashier")]
            con.executemany("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
                            [(u,pw_hash(p),n,r) for u,p,n,r in demo])
        if con.execute("SELECT COUNT(*) FROM zones").fetchone()[0] == 0:
            zid = con.execute("INSERT INTO zones(name,description) VALUES(?,?)",
                              ("Main Block","Main parking facility")).lastrowid
            con.executemany("INSERT INTO slots(zone_id,slot_number,vehicle_type) VALUES(?,?,?)",
                            [(zid,f"A-{i:02d}","Any") for i in range(1,11)])
        if con.execute("SELECT COUNT(*) FROM fee_rules").fetchone()[0] == 0:
            con.executemany("INSERT INTO fee_rules(vehicle_type,hourly_rate,daily_max,grace_minutes) VALUES(?,?,?,?)",
                            [("Car",30,200,10),("Bike",10,80,10),("Any",20,150,10)])

init_db()

def error(message, code=400):
    return jsonify({"error": message}), code

def current_user():
    username = request.headers.get("X-User")
    return one("SELECT id,username,name,role FROM users WHERE username=?", (username,)) if username else None

def require(*roles):
    user = current_user()
    if not user: return None, error("Please sign in again.", 401)
    if roles and user["role"] not in roles: return None, error("You do not have permission for this action.", 403)
    return user, None

@app.get("/api/health")
def health():
    return jsonify({"status":"ok","app":"Parking Facility Operations System"})

@app.post("/api/login")
def login():
    data = request.get_json() or {}
    user = one("SELECT id,username,name,role FROM users WHERE username=? AND password=?",
               (data.get("username","").strip(), pw_hash(data.get("password",""))))
    if not user: return error("Invalid username or password.", 401)
    return jsonify({"user":user})

@app.get("/api/dashboard")
def dashboard():
    parked = one("SELECT COUNT(*) n FROM sessions WHERE status='Parked'")["n"]
    total = one("SELECT COUNT(*) n FROM slots")["n"]
    today = date.today().isoformat()
    revenue = one("SELECT COALESCE(SUM(fee),0) n FROM sessions WHERE status='Completed' AND date(exit_time)=?",(today,))["n"]
    entries = one("SELECT COUNT(*) n FROM sessions WHERE date(entry_time)=?",(today,))["n"]
    return jsonify({"total_slots":total,"occupied":parked,"available":total-parked,
                    "today_revenue":round(revenue,2),"today_entries":entries})

@app.get("/api/zones")
def get_zones():
    result = rows("""SELECT z.*, COUNT(s.id) total_slots,
      SUM(CASE WHEN s.id IS NOT NULL AND s.status='Available'
        AND NOT EXISTS(SELECT 1 FROM sessions p WHERE p.slot_id=s.id AND p.status='Parked')
        THEN 1 ELSE 0 END) available_slots
      FROM zones z LEFT JOIN slots s ON s.zone_id=z.id GROUP BY z.id ORDER BY z.id DESC""")
    return jsonify(result)

@app.post("/api/zones")
def add_zone():
    user, err = require("Administrator","Facility Manager")
    if err: return err
    d=request.get_json() or {}
    name=(d.get("name") or "").strip()
    if not name: return error("Zone name is required.")
    try: zid=execute("INSERT INTO zones(name,description) VALUES(?,?)",(name,d.get("description","").strip()))
    except sqlite3.IntegrityError: return error("A zone with this name already exists.")
    return jsonify({"id":zid,"message":"Zone created."}),201

@app.get("/api/slots")
def get_slots():
    return jsonify(rows("""SELECT s.*,z.name zone_name,
      CASE WHEN EXISTS(SELECT 1 FROM sessions p WHERE p.slot_id=s.id AND p.status='Parked')
      THEN 'Occupied' ELSE s.status END current_status
      FROM slots s JOIN zones z ON z.id=s.zone_id ORDER BY z.name,s.slot_number"""))

@app.post("/api/slots")
def add_slot():
    user,err=require("Administrator","Facility Manager")
    if err:return err
    d=request.get_json() or {}
    try:
        sid=execute("INSERT INTO slots(zone_id,slot_number,vehicle_type) VALUES(?,?,?)",
                    (int(d["zone_id"]),d["slot_number"].strip(),d.get("vehicle_type","Any")))
    except (KeyError,ValueError,sqlite3.IntegrityError): return error("Check the zone and slot number. Slot numbers must be unique within a zone.")
    return jsonify({"id":sid,"message":"Slot created."}),201

@app.get("/api/rules")
def get_rules():
    return jsonify(rows("SELECT * FROM fee_rules ORDER BY vehicle_type"))

@app.post("/api/rules")
def save_rule():
    user,err=require("Administrator","Facility Manager")
    if err:return err
    d=request.get_json() or {}
    try:
        vehicle=d["vehicle_type"].strip()
        rate=float(d["hourly_rate"]); maximum=float(d.get("daily_max",0)); grace=int(d.get("grace_minutes",0))
        if not vehicle or rate<0 or maximum<0 or grace<0: raise ValueError()
        execute("""INSERT INTO fee_rules(vehicle_type,hourly_rate,daily_max,grace_minutes)
          VALUES(?,?,?,?) ON CONFLICT(vehicle_type) DO UPDATE SET
          hourly_rate=excluded.hourly_rate,daily_max=excluded.daily_max,grace_minutes=excluded.grace_minutes""",
          (vehicle,rate,maximum,grace))
    except (KeyError,ValueError,TypeError): return error("Enter valid non-negative fee rule values.")
    return jsonify({"message":"Fee rule saved."})

def calculate_fee(entry, exit_at, vehicle):
    rule=one("SELECT * FROM fee_rules WHERE vehicle_type=?",(vehicle,)) or one("SELECT * FROM fee_rules WHERE vehicle_type='Any'")
    if not rule: return 0
    start=datetime.fromisoformat(entry); end=datetime.fromisoformat(exit_at)
    minutes=max(0,(end-start).total_seconds()/60-rule["grace_minutes"])
    if minutes<=0:return 0
    hours=int((minutes+59.999)//60)
    fee=hours*rule["hourly_rate"]
    if rule["daily_max"]>0:
        days=max(1,int((minutes+1439.999)//1440))
        fee=min(fee,days*rule["daily_max"])
    return round(fee,2)

@app.post("/api/entry")
def vehicle_entry():
    user,err=require("Parking Attendant","Facility Manager","Administrator")
    if err:return err
    d=request.get_json() or {}
    plate=(d.get("plate") or "").strip().upper()
    vehicle=d.get("vehicle_type","Car")
    slot_id=d.get("slot_id")
    if not plate or not slot_id:return error("Vehicle plate and parking slot are required.")
    slot=one("SELECT * FROM slots WHERE id=?",(slot_id,))
    if not slot:return error("Selected slot does not exist.")
    if slot["vehicle_type"] not in ("Any",vehicle):return error("This slot is not suitable for that vehicle type.")
    if slot["status"]!="Available" or one("SELECT id FROM sessions WHERE slot_id=? AND status='Parked'",(slot_id,)):
        return error("This slot is already occupied or unavailable.")
    if one("SELECT id FROM sessions WHERE plate=? AND status='Parked'",(plate,)):return error("This vehicle already has an active parking ticket.")
    ticket="PK-"+datetime.now().strftime("%y%m%d%H%M%S")+"-"+secrets.token_hex(2).upper()
    now=datetime.now().isoformat(timespec="seconds")
    sid=execute("""INSERT INTO sessions(ticket_no,plate,vehicle_type,slot_id,entry_time,entered_by)
                   VALUES(?,?,?,?,?,?)""",(ticket,plate,vehicle,slot_id,now,user["username"]))
    return jsonify({"id":sid,"ticket_no":ticket,"entry_time":now,"message":"Vehicle entry recorded."}),201

@app.post("/api/exit/<int:session_id>")
def vehicle_exit(session_id):
    user,err=require("Cashier","Facility Manager","Administrator")
    if err:return err
    session=one("SELECT * FROM sessions WHERE id=? AND status='Parked'",(session_id,))
    if not session:return error("Active parking record not found.",404)
    now=datetime.now().isoformat(timespec="seconds")
    fee=calculate_fee(session["entry_time"],now,session["vehicle_type"])
    execute("UPDATE sessions SET exit_time=?,fee=?,status='Completed',exited_by=? WHERE id=?",
            (now,fee,user["username"],session_id))
    return jsonify({"message":"Vehicle exit recorded.","ticket_no":session["ticket_no"],"fee":fee,"exit_time":now})

@app.get("/api/sessions")
def get_sessions():
    status=request.args.get("status")
    sql="""SELECT p.*,s.slot_number,z.name zone_name FROM sessions p
           JOIN slots s ON p.slot_id=s.id JOIN zones z ON s.zone_id=z.id"""
    params=[]
    if status in ("Parked","Completed"):sql+=" WHERE p.status=?";params.append(status)
    sql+=" ORDER BY p.id DESC LIMIT 300"
    return jsonify(rows(sql,params))

@app.get("/api/reports")
def reports():
    today=date.today().isoformat()
    daily=rows("""SELECT date(exit_time) day,COUNT(*) vehicles,ROUND(SUM(fee),2) revenue
      FROM sessions WHERE status='Completed' AND date(exit_time)>=date('now','-6 day')
      GROUP BY date(exit_time) ORDER BY day DESC""")
    types=rows("""SELECT vehicle_type,COUNT(*) total,ROUND(COALESCE(SUM(fee),0),2) revenue
      FROM sessions WHERE status='Completed' GROUP BY vehicle_type""")
    return jsonify({"daily":daily,"by_vehicle":types,"today":today})

@app.get("/api/users")
def get_users():
    user,err=require("Administrator")
    if err:return err
    return jsonify(rows("SELECT id,username,name,role FROM users ORDER BY id"))

@app.post("/api/users")
def add_user():
    user,err=require("Administrator")
    if err:return err
    d=request.get_json() or {}
    roles=["Parking Attendant","Facility Manager","Cashier","Administrator"]
    if not all(d.get(k) for k in ("username","password","name","role")) or d["role"] not in roles:
        return error("Provide username, password, name and a valid role.")
    try: uid=execute("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
                     (d["username"].strip(),pw_hash(d["password"]),d["name"].strip(),d["role"]))
    except sqlite3.IntegrityError:return error("Username already exists.")
    return jsonify({"id":uid,"message":"User created."}),201

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
