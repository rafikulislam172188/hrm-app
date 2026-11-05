"""International HRM - Streamlit + SQLite
Run: pip install streamlit pandas && streamlit run hrm_app.py
"""
import sqlite3, hashlib, io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones
import pandas as pd
import streamlit as st

DB = "hrm.db"
st.set_page_config(page_title="HRM", layout="wide")


def q(sql, p=(), fetch=True):
    with sqlite3.connect(DB) as c:
        c.execute("PRAGMA foreign_keys=ON")
        cur = c.execute(sql, p)
        if fetch:
            return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        c.commit()


def pw(p):
    return hashlib.sha256(("hrm$" + p).encode()).hexdigest()


def eosb(r, upto):
    """End-of-service: half month wage/yr for first 5 yrs, one month wage/yr after (Saudi labour law style)."""
    yrs = max((upto - datetime.strptime(r.join_date, "%Y-%m-%d").date()).days / 365.25, 0)
    wage = r.rate if r.pay_type == "Monthly" else r.rate * float(S("std_hours")) * float(S("work_days"))
    return round(yrs, 2), round(wage, 2), round(wage / 2 * min(yrs, 5) + wage * max(yrs - 5, 0), 2)


def payslip_pdf(r, d1, d2):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    y = 800
    c.setFont("Helvetica-Bold", 16); c.drawString(50, y, f"{S('company')} - PAYSLIP"); y -= 25
    c.setFont("Helvetica", 11); c.drawString(50, y, f"Period: {d1} to {d2}"); y -= 30
    money = {"Rate", "Basic", "OT Pay", "Allow/Bonus", "Advance", "Deduction", "GOSI", "Net"}
    for k in ["Code", "Name", "Section", "Labour", "Sponsor", "Pay", "Rate", "Present", "Leave", "Absent",
              "Hours", "OT Hrs", "Basic", "OT Pay", "Allow/Bonus", "Advance", "Deduction", "GOSI", "Net"]:
        c.setFont("Helvetica-Bold" if k == "Net" else "Helvetica", 11)
        c.drawString(50, y, k)
        c.drawString(250, y, f"{r[k]}" + (f" {S('currency')}" if k in money else ""))
        y -= 18
    c.drawString(50, y - 20, "Employee signature: ____________        HR signature: ____________")
    c.save()
    return b.getvalue()


def init():
    for s in [
        "CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)",
        "CREATE TABLE IF NOT EXISTS departments(id INTEGER PRIMARY KEY, name TEXT UNIQUE)",
        "CREATE TABLE IF NOT EXISTS sponsors(id INTEGER PRIMARY KEY, name TEXT UNIQUE, phone TEXT)",
        """CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT,
            dept_id INT, sponsor_id INT, labour_type TEXT, pay_type TEXT, rate REAL,
            nationality TEXT, id_no TEXT, phone TEXT, join_date TEXT, active INT DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY, emp_id INT, day TEXT,
            status TEXT, in_t TEXT, out_t TEXT, hours REAL, UNIQUE(emp_id, day))""",
        "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT, role TEXT)",
        "CREATE TABLE IF NOT EXISTS adjustments(id INTEGER PRIMARY KEY, emp_id INT, day TEXT, kind TEXT, amount REAL, note TEXT)",
        """CREATE TABLE IF NOT EXISTS leaves(id INTEGER PRIMARY KEY, emp_id INT, ltype TEXT,
            start TEXT, end TEXT, days INT, status TEXT)""",
    ]:
        q(s, fetch=False)
    defaults = {"company": "My Company", "currency": "SAR", "timezone": "Asia/Riyadh",
                "std_hours": "8", "work_days": "30", "ot_mult": "1.5", "date_fmt": "%d-%m-%Y", "gosi_pct": "0", "gosi_nat": "Saudi"}
    for k, v in defaults.items():
        q("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v), fetch=False)
    try:
        q("ALTER TABLE employees ADD COLUMN id_expiry TEXT", fetch=False)
    except Exception:
        pass
    if q("SELECT COUNT(*) AS n FROM users").n[0] == 0:
        q("INSERT INTO users(username,pw,role) VALUES(?,?,?)", ("admin", pw("admin123"), "Admin"), fetch=False)


def S(k):
    return q("SELECT v FROM settings WHERE k=?", (k,)).iloc[0, 0]


def today():
    return datetime.now(ZoneInfo(S("timezone"))).date()


def hrs(i, o):
    try:
        a = datetime.strptime(i, "%H:%M")
        b = datetime.strptime(o, "%H:%M")
        d = (b - a).total_seconds() / 3600
        return round(d + 24 if d < 0 else d, 2)
    except Exception:
        return 0.0


def emp_df(active=True):
    return q("""SELECT e.id, e.code, e.name, d.name AS section, s.name AS sponsor, e.labour_type,
        e.pay_type, e.rate, e.nationality, e.id_no, e.phone, e.join_date, e.id_expiry
        FROM employees e LEFT JOIN departments d ON d.id=e.dept_id
        LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE e.active=?""", (1 if active else 0,))


def filters(key):
    """Common filter bar used in every report/page: date range, section, labour type, pay type, sponsor."""
    c = st.columns(5)
    d1 = c[0].date_input("From", today().replace(day=1), key=key + "a")
    d2 = c[1].date_input("To", today(), key=key + "b")
    secs = q("SELECT name FROM departments").name.tolist()
    sp = q("SELECT name FROM sponsors").name.tolist()
    sec = c[2].multiselect("Section", secs, key=key + "c")
    lt = c[3].multiselect("Labour", ["Company", "Outside"], key=key + "d")
    pt = c[4].multiselect("Pay type", ["Monthly", "Hourly"], key=key + "e")
    spn = st.multiselect("Sponsor / Kafeel / Agency", sp, key=key + "f")
    return str(d1), str(d2), sec, lt, pt, spn


def apply_f(df, sec, lt, pt, spn):
    if sec: df = df[df.section.isin(sec)]
    if lt: df = df[df.labour_type.isin(lt)]
    if pt: df = df[df.pay_type.isin(pt)]
    if spn: df = df[df.sponsor.isin(spn)]
    return df


def download(df, name):
    st.download_button("⬇ Download CSV", df.to_csv(index=False).encode("utf-8-sig"),
                       f"{name}_{today()}.csv", "text/csv")


def calc_payroll(d1, d2, sec, lt, pt, spn):
    e = apply_f(emp_df(), sec, lt, pt, spn)
    att = q("SELECT * FROM attendance WHERE day BETWEEN ? AND ?", (d1, d2))
    std, wd, otm = float(S("std_hours")), float(S("work_days")), float(S("ot_mult"))
    adj = q("SELECT * FROM adjustments WHERE day BETWEEN ? AND ?", (d1, d2))
    gp, gn = float(S("gosi_pct")), S("gosi_nat").strip().lower()
    rows = []
    for _, r in e.iterrows():
        a = att[att.emp_id == r.id]
        pres = a[a.status == "Present"]
        pd_, ld = len(pres), len(a[a.status == "Leave"])
        tot = pres.hours.sum()
        ot = (pres.hours - std).clip(lower=0).sum()
        reg = tot - ot
        if r.pay_type == "Monthly":
            daily = r.rate / wd
            basic, hr = daily * (pd_ + ld + len(a[a.status == "Off"])), daily / std
        else:
            basic, hr = reg * r.rate, r.rate
        otp = ot * hr * otm
        ad = adj[adj.emp_id == r.id]
        add = ad[ad.kind.isin(["Bonus", "Allowance"])].amount.sum()
        adv = ad[ad.kind == "Advance"].amount.sum()
        ded = ad[ad.kind == "Deduction"].amount.sum()
        gosi = basic * gp / 100 if str(r.nationality).strip().lower() == gn else 0
        rows.append({"Code": r.code, "Name": r["name"], "Section": r.section, "Labour": r.labour_type,
                     "Sponsor": r.sponsor, "Pay": r.pay_type, "Rate": r.rate, "Present": pd_,
                     "Leave": ld, "Absent": len(a[a.status == "Absent"]), "Hours": round(tot, 2),
                     "OT Hrs": round(ot, 2), "Basic": round(basic, 2), "OT Pay": round(otp, 2),
                     "Allow/Bonus": round(add, 2), "Advance": round(adv, 2), "Deduction": round(ded, 2),
                     "GOSI": round(gosi, 2), "Net": round(basic + otp + add - adv - ded - gosi, 2)})
    return pd.DataFrame(rows)


init()
cur_ = S("currency")
if "user" not in st.session_state:
    st.title(f"🏢 {S('company')} - Login")
    with st.form("login"):
        u, p_ = st.text_input("Username"), st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            r_ = q("SELECT * FROM users WHERE username=? AND pw=?", (u, pw(p_)))
            if len(r_):
                st.session_state.user, st.session_state.role = u, r_.role[0]
                st.rerun()
            else:
                st.error("Wrong username or password")
    st.caption("First login: admin / admin123 (change it in Users)")
    st.stop()
role = st.session_state.role
ALL = ["Dashboard", "Employees", "Sections & Sponsors", "Attendance", "Leave", "Adjustments",
       "Payroll", "Reports", "Settings"]
MENU = {"Admin": ALL + ["Users"], "HR": ALL, "Manager": ["Dashboard", "Attendance", "Leave", "Reports"]}[role]
st.sidebar.title(f"🏢 {S('company')}")
st.sidebar.write(f"👤 {st.session_state.user} ({role})")
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()
page = st.sidebar.radio("Menu", MENU)
st.sidebar.caption(f"Today: {today().strftime(S('date_fmt'))} ({S('timezone')})")

# ---------------- Dashboard
if page == "Dashboard":
    st.header("Dashboard")
    e = emp_df()
    t = str(today())
    a = q("SELECT status FROM attendance WHERE day=?", (t,))
    c = st.columns(5)
    c[0].metric("Total", len(e))
    c[1].metric("Company", (e.labour_type == "Company").sum())
    c[2].metric("Outside", (e.labour_type == "Outside").sum())
    c[3].metric("Present today", (a.status == "Present").sum())
    c[4].metric("On leave today", (a.status == "Leave").sum())
    if len(e):
        st.subheader("Section-wise headcount")
        st.bar_chart(e.groupby("section").size())
        e["days_left"] = (pd.to_datetime(e.id_expiry, errors="coerce") - pd.Timestamp(today())).dt.days
        ex = e[e.days_left <= 60][["code", "name", "section", "sponsor", "id_expiry", "days_left"]]
        if len(ex):
            st.subheader("⚠ ID / Iqama expired or expiring within 60 days")
            st.dataframe(ex.sort_values("days_left"), hide_index=True, use_container_width=True)

# ---------------- Employees
elif page == "Employees":
    st.header("Employees / Labour")
    deps, sps = q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    with st.expander("➕ Add employee"):
        with st.form("emp"):
            c = st.columns(3)
            code, name = c[0].text_input("Code"), c[1].text_input("Name")
            nat = c[2].text_input("Nationality")
            sec = c[0].selectbox("Section", deps.name.tolist() or [""])
            lt = c[1].selectbox("Labour type", ["Company", "Outside"])
            pt = c[2].selectbox("Pay type", ["Monthly", "Hourly"])
            rate = c[0].number_input("Rate (monthly salary or per hour)", 0.0)
            idn, ph = c[1].text_input("ID / Iqama / Passport"), c[2].text_input("Phone")
            spn = c[0].selectbox("Sponsor / Kafeel / Agency", ["-"] + sps.name.tolist())
            jd = c[1].date_input("Join date", today())
            exp = c[2].date_input("ID / Iqama expiry", today() + timedelta(days=365))
            if st.form_submit_button("Save"):
                did = deps[deps.name == sec].id.iloc[0] if len(deps) else None
                sid = sps[sps.name == spn].id.iloc[0] if spn != "-" else None
                try:
                    q("INSERT INTO employees(code,name,dept_id,sponsor_id,labour_type,pay_type,rate,"
                      "nationality,id_no,phone,join_date,id_expiry) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (code, name, None if did is None else int(did), None if sid is None else int(sid),
                       lt, pt, rate, nat, idn, ph, str(jd), str(exp)), fetch=False)
                    st.success("Saved"); st.rerun()
                except Exception as ex:
                    st.error(ex)
    d1, d2, sec, lt, pt, spn = filters("emp")
    df = apply_f(emp_df(), sec, lt, pt, spn)
    st.dataframe(df, use_container_width=True, hide_index=True)
    download(df, "employees")
    if len(df):
        x = st.selectbox("Deactivate employee", df.code + " - " + df["name"])
        if st.button("Deactivate"):
            q("UPDATE employees SET active=0 WHERE code=?", (x.split(" - ")[0],), fetch=False); st.rerun()

# ---------------- Sections & sponsors
elif page == "Sections & Sponsors":
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Sections / Departments")
        n = st.text_input("New section")
        if st.button("Add section") and n:
            q("INSERT OR IGNORE INTO departments(name) VALUES(?)", (n,), fetch=False); st.rerun()
        st.dataframe(q("SELECT name FROM departments"), hide_index=True)
    with c2:
        st.subheader("Sponsors (Kafeel) / Agencies")
        n, p = st.text_input("Sponsor name"), st.text_input("Phone")
        if st.button("Add sponsor") and n:
            q("INSERT OR IGNORE INTO sponsors(name,phone) VALUES(?,?)", (n, p), fetch=False); st.rerun()
        st.dataframe(q("SELECT name, phone FROM sponsors"), hide_index=True)

# ---------------- Attendance
elif page == "Attendance":
    st.header("Attendance")
    day = st.date_input("Date", today())
    secs = ["All"] + q("SELECT name FROM departments").name.tolist()
    sec = st.selectbox("Section", secs)
    e = emp_df()
    if sec != "All": e = e[e.section == sec]
    old = q("SELECT * FROM attendance WHERE day=?", (str(day),))
    rows = []
    for _, r in e.iterrows():
        o = old[old.emp_id == r.id]
        rows.append({"id": r.id, "Code": r.code, "Name": r["name"], "Labour": r.labour_type,
                     "Status": o.status.iloc[0] if len(o) else "Present",
                     "In": o.in_t.iloc[0] if len(o) else "08:00",
                     "Out": o.out_t.iloc[0] if len(o) else "17:00"})
    ed = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                        disabled=["id", "Code", "Name", "Labour"],
                        column_config={"id": None, "Status": st.column_config.SelectboxColumn(
                            options=["Present", "Absent", "Leave", "Off"])})
    st.caption("Time format HH:MM (24h). Overnight shifts supported.")
    if st.button("💾 Save attendance"):
        for _, r in ed.iterrows():
            h = hrs(r.In, r.Out) if r.Status == "Present" else 0
            q("INSERT INTO attendance(emp_id,day,status,in_t,out_t,hours) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(emp_id,day) DO UPDATE SET status=excluded.status,in_t=excluded.in_t,"
              "out_t=excluded.out_t,hours=excluded.hours",
              (int(r.id), str(day), r.Status, r.In, r.Out, h), fetch=False)
        st.success("Saved")

# ---------------- Leave
elif page == "Leave":
    st.header("Leave")
    e = emp_df()
    with st.expander("➕ New leave request"):
        with st.form("lv"):
            x = st.selectbox("Employee", e.code + " - " + e["name"])
            lt = st.selectbox("Type", ["Annual", "Sick", "Emergency", "Unpaid", "Other"])
            a, b = st.date_input("From", today()), st.date_input("To", today())
            if st.form_submit_button("Submit"):
                eid = int(e[e.code == x.split(" - ")[0]].id.iloc[0])
                q("INSERT INTO leaves(emp_id,ltype,start,end,days,status) VALUES(?,?,?,?,?,'Pending')",
                  (eid, lt, str(a), str(b), (b - a).days + 1), fetch=False); st.rerun()
    d1, d2, sec, lt, pt, spn = filters("lv")
    df = q("""SELECT l.id, e.code, e.name, d.name AS section, s.name AS sponsor, e.labour_type, e.pay_type,
        l.ltype, l.start, l.end, l.days, l.status FROM leaves l JOIN employees e ON e.id=l.emp_id
        LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id
        WHERE l.start<=? AND l.end>=?""", (d2, d1))
    df = apply_f(df, sec, lt, pt, spn)
    st.dataframe(df, use_container_width=True, hide_index=True); download(df, "leave")
    pend = df[df.status == "Pending"]
    if len(pend):
        i = st.selectbox("Pending request ID", pend.id)
        c = st.columns(2)
        if c[0].button("✅ Approve"):
            r = q("SELECT * FROM leaves WHERE id=?", (int(i),)).iloc[0]
            s = datetime.strptime(r.start, "%Y-%m-%d").date()
            for k in range(int(r.days)):
                q("INSERT INTO attendance(emp_id,day,status,hours) VALUES(?,?,?,0) ON CONFLICT(emp_id,day) "
                  "DO UPDATE SET status=?", (int(r.emp_id), str(s + timedelta(k)),
                  "Absent" if r.ltype == "Unpaid" else "Leave", "Absent" if r.ltype == "Unpaid" else "Leave"),
                  fetch=False)
            q("UPDATE leaves SET status='Approved' WHERE id=?", (int(i),), fetch=False); st.rerun()
        if c[1].button("❌ Reject"):
            q("UPDATE leaves SET status='Rejected' WHERE id=?", (int(i),), fetch=False); st.rerun()

# ---------------- Adjustments
elif page == "Adjustments":
    st.header("Advances, Deductions, Bonus & Allowance")
    e = emp_df()
    with st.form("adj"):
        c = st.columns(5)
        x = c[0].selectbox("Employee", e.code + " - " + e["name"])
        k = c[1].selectbox("Type", ["Advance", "Deduction", "Bonus", "Allowance"])
        am = c[2].number_input("Amount", 0.0)
        dy = c[3].date_input("Date", today())
        nt = c[4].text_input("Note")
        if st.form_submit_button("Add"):
            eid = int(e[e.code == x.split(" - ")[0]].id.iloc[0])
            q("INSERT INTO adjustments(emp_id,day,kind,amount,note) VALUES(?,?,?,?,?)",
              (eid, str(dy), k, am, nt), fetch=False)
            st.rerun()
    f = filters("adj")
    df = q("""SELECT a.id, a.day, e.code, e.name, d.name AS section, s.name AS sponsor, e.labour_type,
        e.pay_type, a.kind, a.amount, a.note FROM adjustments a JOIN employees e ON e.id=a.emp_id
        LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id
        WHERE a.day BETWEEN ? AND ?""", (f[0], f[1]))
    df = apply_f(df, *f[2:])
    st.dataframe(df, use_container_width=True, hide_index=True)
    download(df, "adjustments")
    rid = st.number_input("Delete entry ID", 0, step=1)
    if st.button("Delete entry") and rid:
        q("DELETE FROM adjustments WHERE id=?", (int(rid),), fetch=False)
        st.rerun()

# ---------------- Users
elif page == "Users":
    st.header("Users & Roles")
    with st.form("usr"):
        c = st.columns(3)
        u, p_, ro = c[0].text_input("Username"), c[1].text_input("Password", type="password"), \
            c[2].selectbox("Role", ["Admin", "HR", "Manager"])
        if st.form_submit_button("Save / reset password") and u and p_:
            q("INSERT INTO users(username,pw,role) VALUES(?,?,?) ON CONFLICT(username) "
              "DO UPDATE SET pw=excluded.pw, role=excluded.role", (u, pw(p_), ro), fetch=False)
            st.rerun()
    st.dataframe(q("SELECT username, role FROM users"), hide_index=True)
    others = [x for x in q("SELECT username FROM users").username if x != st.session_state.user]
    d = st.selectbox("Delete user", others)
    if st.button("Delete user") and d:
        q("DELETE FROM users WHERE username=?", (d,), fetch=False)
        st.rerun()

# ---------------- Payroll
elif page == "Payroll":
    st.header("Payroll")
    f = filters("pay")
    df = calc_payroll(*f)
    st.dataframe(df, use_container_width=True, hide_index=True)
    if len(df):
        c = st.columns(3)
        c[0].metric("Total Net", f"{df.Net.sum():,.2f} {cur_}")
        c[1].metric("Company labour", f"{df[df.Labour == 'Company'].Net.sum():,.2f} {cur_}")
        c[2].metric("Outside labour", f"{df[df.Labour == 'Outside'].Net.sum():,.2f} {cur_}")
        download(df, "payroll")
        sel = st.selectbox("Payslip for", df.Code + " - " + df.Name)
        try:
            row = df[df.Code == sel.split(" - ")[0]].iloc[0]
            st.download_button("🧾 Download payslip PDF", payslip_pdf(row, f[0], f[1]),
                               f"payslip_{row.Code}_{f[0]}_{f[1]}.pdf", "application/pdf")
        except ImportError:
            st.info("For payslip PDF run: pip install reportlab")

# ---------------- Reports
elif page == "Reports":
    st.header("Reports (custom date range)")
    kinds = ["Attendance detail", "Attendance summary"]
    if role != "Manager":
        kinds += ["Hours (hourly basis)", "Section-wise payroll", "Labour-type payroll",
                  "Sponsor-wise payroll", "EOSB provision"]
    kind = st.selectbox("Report", kinds)
    f = filters("rep")
    d1, d2 = f[0], f[1]
    if kind == "Attendance detail":
        df = q("""SELECT a.day, e.code, e.name, d.name AS section, s.name AS sponsor, e.labour_type,
            e.pay_type, a.status, a.in_t, a.out_t, a.hours FROM attendance a JOIN employees e ON e.id=a.emp_id
            LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id
            WHERE a.day BETWEEN ? AND ? ORDER BY a.day""", (d1, d2))
        df = apply_f(df, *f[2:])
    elif kind == "EOSB provision":
        out = []
        for _, r in apply_f(emp_df(), *f[2:]).iterrows():
            y, w, a_ = eosb(r, datetime.strptime(d2, "%Y-%m-%d").date())
            out.append({"Code": r.code, "Name": r["name"], "Section": r.section, "Labour": r.labour_type,
                        "Sponsor": r.sponsor, "Join date": r.join_date, "Years": y,
                        "Monthly wage": w, "EOSB due": a_})
        df = pd.DataFrame(out)
    else:
        p = calc_payroll(*f)
        if kind == "Attendance summary":
            df = p[["Code", "Name", "Section", "Labour", "Sponsor", "Present", "Leave", "Absent", "Hours", "OT Hrs"]]
        elif kind == "Hours (hourly basis)":
            df = p[p.Pay == "Hourly"][["Code", "Name", "Section", "Labour", "Sponsor", "Rate", "Hours", "OT Hrs", "Net"]]
        else:
            g = {"Section-wise payroll": "Section", "Labour-type payroll": "Labour",
                 "Sponsor-wise payroll": "Sponsor"}[kind]
            df = p.groupby(g, dropna=False).agg(Employees=("Code", "count"), Hours=("Hours", "sum"),
                                                 Basic=("Basic", "sum"), OT=("OT Pay", "sum"),
                                                 Net=("Net", "sum")).reset_index()
    st.dataframe(df, use_container_width=True, hide_index=True)
    download(df, kind.replace(" ", "_"))

# ---------------- Settings
elif page == "Settings":
    st.header("Settings")
    with st.form("set"):
        co = st.text_input("Company name", S("company"))
        cu = st.text_input("Currency", S("currency"))
        tzs = sorted(available_timezones())
        tz = st.selectbox("Time zone", tzs, tzs.index(S("timezone")))
        sh = st.number_input("Standard hours/day", 1.0, 24.0, float(S("std_hours")))
        wd = st.number_input("Working days/month (monthly salary divisor)", 1.0, 31.0, float(S("work_days")))
        ot = st.number_input("Overtime multiplier", 1.0, 5.0, float(S("ot_mult")))
        df_ = st.selectbox("Date format", ["%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"])
        gp = st.number_input("GOSI employee deduction % (0 = off)", 0.0, 100.0, float(S("gosi_pct")))
        gn = st.text_input("GOSI applies to nationality", S("gosi_nat"))
        if st.form_submit_button("Save"):
            for k, v in dict(company=co, currency=cu, timezone=tz, std_hours=sh, work_days=wd,
                             ot_mult=ot, date_fmt=df_, gosi_pct=gp, gosi_nat=gn).items():
                q("REPLACE INTO settings VALUES(?,?)", (k, str(v)), fetch=False)
            st.success("Saved"); st.rerun()
