"""International HRM - Streamlit + SQLite
Run: pip install streamlit pandas && streamlit run hrm_app.py
"""
import sqlite3, hashlib, io, html, calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones
import pandas as pd
import streamlit as st

DB = "hrm.db"
CODE = {"Present": "P", "Absent": "A", "Leave": "L", "Off": "O"}
REV = {v: k for k, v in CODE.items()}
LBL = {"P": "🟢 P", "A": "🔴 A", "L": "🟡 L", "O": "⚪ O"}
st.set_page_config(page_title="HRM", layout="wide")
st.markdown("""<style>
.stApp{background:#eef5ef;color:#1b2b22}
.stApp h1,.stApp h2,.stApp h3{color:#1b2b22}
[data-testid="stSidebar"]{background:#14472f}
[data-testid="stSidebar"] *{color:#e8f5ec !important}
[data-testid="stSidebar"] .stButton button{background:transparent;border:1px solid #6fae8a}
.card{background:#fff;color:#1b2b22;border-radius:14px;padding:16px 18px;box-shadow:0 2px 10px rgba(20,71,47,.08)}
.kpi{display:flex;align-items:center;gap:14px}
.kpi .ic{font-size:24px;width:46px;height:46px;border-radius:12px;display:flex;align-items:center;justify-content:center}
.kpi .lb{font-size:13px;color:#6b7c72}
.kpi .v{font-size:28px;font-weight:700}
.ttl{font-weight:600;font-size:16px;margin-bottom:10px}
.row{display:flex;align-items:center;gap:18px}
.donut{width:130px;height:130px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.donut div{width:84px;height:84px;border-radius:50%;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:12px;color:#6b7c72}
.donut b{font-size:24px;color:#1b2b22}
.leg{font-size:13px;line-height:2;flex:1}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}
.ci{display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid #eef2ee}
.av{width:36px;height:36px;border-radius:50%;background:#2e7d4f;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600}
.badge{margin-left:auto;background:#e3f4e8;color:#2e7d4f;padding:2px 12px;border-radius:8px;font-size:12px}
.bars{display:flex;align-items:flex-end;gap:12px;height:130px;margin-top:8px}
.bars div{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;font-size:11px;color:#6b7c72}
.bars span{width:70%;background:#2e7d4f;border-radius:4px 4px 0 0;display:block}
[data-baseweb="select"]>div{background:#eaf5ee;border:1.5px solid #2e7d4f}
[data-baseweb="tag"]{background-color:#2e7d4f !important;color:#fff !important}
</style>""", unsafe_allow_html=True)
_COL = {"co": "#1f3a5f", "sec": "#e67e22", "spn": "#7d3c98", "lab": "#117a8b", "pay": "#2ea05a", "st": "#b7950b", "dt": "#c0392b"}
# each coloured frame is preceded by an invisible marker (<span class="cb cb-co">); CSS colours the frame that follows it
_css = '[data-testid="stElementContainer"]:has(.cb){display:none}.element-container:has(.cb){display:none}'
for _k, _c in _COL.items():
    for _w in ('[data-testid="stElementContainer"]', ".element-container"):
        _s = f"{_w}:has(.cb-{_k}) + {_w}"
        _css += (f'{_s}{{background:{_c};border-radius:14px;padding:8px 10px 8px;box-shadow:0 2px 6px rgba(0,0,0,.14)}}'
                 f'{_s} label p{{color:#fff !important;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}'
                 f'{_s} [data-baseweb="tag"]{{background-color:{_c} !important;color:#fff !important}}')
st.markdown("<style>" + _css + "</style>", unsafe_allow_html=True)


def q(sql, p=(), fetch=True):
    with sqlite3.connect(DB) as c:
        c.execute("PRAGMA foreign_keys=ON")
        cur = c.execute(sql, p)
        if fetch:
            return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        c.commit()


def pw(p):
    return hashlib.sha256(("hrm$" + p).encode()).hexdigest()


def ot_rate_of(rate, pay_type, ot_rate, ref):
    """OT rate/hour: the employee's own OT rate, else hourly rate (Hourly) or daily rate/std hrs x multiplier (Monthly)."""
    if ot_rate and ot_rate > 0:
        return round(ot_rate, 2)
    if pay_type != "Monthly":
        return round(rate, 2)
    d = date.fromisoformat(ref)
    n = calendar.monthrange(d.year, d.month)[1]
    wd_m = n - sum(date(d.year, d.month, k).weekday() == int(S("weekend")) for k in range(1, n + 1))
    return round(rate / wd_m / float(S("std_hours")) * float(S("ot_mult")), 2)


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
    money = {"Rate", "Basic", "Food", "OT Pay", "Wknd OT", "Allowances", "Advance", "Deduction", "GOSI", "Net"}
    for k in r.index:
        if k in ("Invoice", "Bank", "Cash"):
            continue
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
                "std_hours": "8", "work_days": "26", "ot_mult": "1.5", "date_fmt": "%d-%m-%Y", "gosi_pct": "0", "gosi_nat": "Saudi", "vat_pct": "15", "weekend": "4", "def_normal": "10", "def_ot": "2"}
    for k, v in defaults.items():
        q("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v), fetch=False)
    q("CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, name TEXT UNIQUE, vat TEXT)", fetch=False)
    q("CREATE TABLE IF NOT EXISTS costs(id INTEGER PRIMARY KEY, day TEXT, category TEXT, emp_id INT, company_id INT, amount REAL, note TEXT)", fetch=False)
    for t_, c_ in [("employees", "id_expiry TEXT"), ("employees", "company_id INT"), ("employees", "food_allow REAL DEFAULT 0"),
                   ("employees", "ot_rate REAL DEFAULT 0"), ("employees", "bill_rate REAL DEFAULT 0"),
                   ("employees", "pay_mode TEXT DEFAULT 'Bank'"), ("attendance", "company_id INT"), ("attendance", "dept_id INT"), ("attendance", "ot_hours REAL")]:
        try:
            q(f"ALTER TABLE {t_} ADD COLUMN {c_}", fetch=False)
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
    return q("""SELECT e.id, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type,
        e.pay_type, e.pay_mode, e.rate, e.food_allow, e.ot_rate, e.bill_rate, e.nationality, e.id_no, e.phone,
        e.join_date, e.id_expiry, e.company_id, e.dept_id, e.sponsor_id
        FROM employees e LEFT JOIN companies c ON c.id=e.company_id LEFT JOIN departments d ON d.id=e.dept_id
        LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE e.active=?""", (1 if active else 0,))


def save_emp(d):
    cols = list(d)
    q(f"INSERT INTO employees({','.join(cols)}) VALUES({','.join('?' * len(cols))}) ON CONFLICT(code) DO UPDATE SET "
      + ",".join(f"{k}=excluded.{k}" for k in cols if k != "code"), tuple(d.values()), fetch=False)


def _norm_cb(key):
    """'All' is an option inside the box: choosing it clears the rest; choosing a specific item removes 'All'."""
    new, prev = st.session_state.get(key, []), st.session_state.get(key + "_prev", [])
    if "All" in new and len(new) > 1:
        new = ["All"] if "All" not in prev else [x for x in new if x != "All"]
    st.session_state[key] = st.session_state[key + "_prev"] = new


def msel(label, options, key, default_all=False, ph="All"):
    """Multiselect that has an 'All' option inside the box. Returns the selected list."""
    options = list(options)
    if key not in st.session_state:
        st.session_state[key] = st.session_state[key + "_prev"] = ["All"] if default_all else []
    st.session_state[key] = [x for x in st.session_state[key] if x == "All" or x in options]
    kind = key.rsplit("_", 1)[-1]
    if kind in _COL:
        st.markdown(f'<span class="cb cb-{kind}"></span>', unsafe_allow_html=True)
    try:
        st.multiselect(label, ["All"] + options, key=key, on_change=_norm_cb, args=(key,), placeholder=ph)
    except TypeError:   # very old Streamlit without 'placeholder'
        st.multiselect(label, ["All"] + options, key=key, on_change=_norm_cb, args=(key,))
    return list(st.session_state[key])


def eff(sel, options=()):
    """'All' (or every item) selected = no filter, so rows with empty company/section/kofil are kept too."""
    return [] if "All" in sel or (options and set(options) <= set(sel)) else sel


def dbox(col, label, value, key):
    """Date input inside a coloured frame (same look as the select frames)."""
    with col:
        st.markdown('<span class="cb cb-dt"></span>', unsafe_allow_html=True)
        return st.date_input(label, value, key=key)


def filters(key):
    """Every page, ONE row: From, To, Company, Section, Labour, Pay type, Sponsor/Kofil (+ search below)."""
    cos, secs, spns = (q(f"SELECT name FROM {t}").name.tolist() for t in ("companies", "departments", "sponsors"))
    c = st.columns([1, 1, 1.15, 1.15, 1, 1, 1.15])
    d1 = dbox(c[0], "From", today().replace(day=1), key + "a")
    d2 = dbox(c[1], "To", today(), key + "b")
    with c[2]:
        co = eff(msel("Company", cos, key + "_co"), cos)
    with c[3]:
        sec = eff(msel("Section", secs, key + "_sec"), secs)
    with c[4]:
        lt = eff(msel("Labour", ["Company", "Outside"], key + "_lab"), ["Company", "Outside"])
    with c[5]:
        pt = eff(msel("Pay type", ["Monthly", "Hourly"], key + "_pay"), ["Monthly", "Hourly"])
    with c[6]:
        spn = eff(msel("Sponsor / Kofil", spns, key + "_spn"), spns)
    qs = st.text_input("🔎 Search code / name", key=key + "h")
    return str(d1), str(d2), sec, lt, pt, spn, co, qs


def apply_f(df, sec=(), lt=(), pt=(), spn=(), co=(), qs=""):
    for col, v in (("section", sec), ("labour_type", lt), ("pay_type", pt), ("sponsor", spn), ("company", co)):
        if v and col in df:
            df = df[df[col].isin(v)]
    cols = [c for c in ("code", "name", "employee") if c in df]
    if qs and cols:
        m = pd.Series(False, index=df.index)
        for c in cols:
            m |= df[c].astype(str).str.contains(qs, case=False, na=False, regex=False)
        df = df[m]
    return df


def df_pdf(df, title):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    b, n = io.BytesIO(), max(len(df.columns), 1)
    ps = landscape(A3 if n > 18 else A4)
    doc = SimpleDocTemplate(b, pagesize=ps, leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    fs = 8 if n <= 10 else (7 if n <= 18 else 6)
    w = (ps[0] - 40) / n
    cut = max(4, int(w / (fs * 0.52)))
    fmt = lambda v: "" if pd.isna(v) else (f"{v:,.2f}" if isinstance(v, float) else str(v))[:cut]
    data = [[str(c)[:cut] for c in df.columns]] + [[fmt(v) for v in row] for row in df.itertuples(index=False)]
    t = Table(data, colWidths=[w] * n, repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), fs), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14472f")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef5ef")])]))
    sty = getSampleStyleSheet()
    doc.build([Paragraph(f"{S('company')} - {title}", sty["Title"]),
               Paragraph(f"Generated {today()}  |  {len(df)} rows", sty["Normal"]), Spacer(1, 8), t])
    return b.getvalue()


def download(df, name):
    c = st.columns([1, 1, 6])
    c[0].download_button("⬇ CSV", df.to_csv(index=False).encode("utf-8-sig"), f"{name}_{today()}.csv", "text/csv",
                         key="csv_" + name)
    try:
        c[1].download_button("⬇ PDF", df_pdf(df, name.replace("_", " ")), f"{name}_{today()}.pdf", "application/pdf",
                             key="pdf_" + name)
    except ImportError:
        c[1].caption("pip install reportlab")


PCOLS = ["Code", "Name", "Company", "Section", "Sponsor", "Labour", "Pay", "Mode", "Rate", "Days", "Leave", "Absent",
         "Hours", "OT Hrs", "Wknd Hrs", "Basic", "Food", "OT Pay", "Wknd OT", "Allowances", "Advance", "Deduction",
         "GOSI", "Net", "Bank", "Cash", "Invoice"]


def calc_payroll(d1, d2, sec=(), lt=(), pt=(), spn=(), co=(), qs=""):
    """Per employee x company x section (from daily attendance), for any date range."""
    e = apply_f(emp_df(), (), lt, pt, spn, (), qs)
    att = q("SELECT * FROM attendance WHERE day BETWEEN ? AND ?", (d1, d2))
    adj = q("SELECT * FROM adjustments WHERE day BETWEEN ? AND ?", (d1, d2))
    cn = dict(q("SELECT id,name FROM companies").values)
    sn = dict(q("SELECT id,name FROM departments").values)
    nm = lambda d, k: d.get(int(k), "-") if pd.notna(k) else "-"
    std, otm, wd, we = float(S("std_hours")), float(S("ot_mult")), float(S("work_days")), int(S("weekend"))
    gp, gn = float(S("gosi_pct")), S("gosi_nat").strip().lower()
    months = max(1, round(((date.fromisoformat(d2) - date.fromisoformat(d1)).days + 1) / 30.4))
    rows = []
    for _, r in e.iterrows():
        a = att[att.emp_id == r.id].copy()
        if a.empty:
            continue
        a["cid"], a["sid"] = a.company_id.fillna(r.company_id), a.dept_id.fillna(r.dept_id)
        a["ot_hours"], a["hours"] = a.ot_hours.fillna(0), a.hours.fillna(0)
        ad = adj[adj.emp_id == r.id]
        tp = max((a.status == "Present").sum(), 1)
        first = True
        for (cid, sid), g in a.groupby(["cid", "sid"], dropna=False):
            pres = g[g.status == "Present"]
            wkd = pres[pd.to_datetime(pres.day).dt.weekday == we]
            nor = pres.drop(wkd.index)
            ot_h, wk_h = nor.ot_hours.sum(), (wkd.hours + wkd.ot_hours).sum()
            reg_h = nor.hours.sum()
            ld = (g.status == "Leave").sum()
            g = g.assign(m=g.day.str[:7], wk=pd.to_datetime(g.day).dt.weekday == we)
            if r.pay_type == "Monthly":
                # salary / (days in that month - weekend days) per paid day; weekend work = OT only
                basic = ot_pay = wk_pay = 0.0
                for mth, gm in g.groupby("m"):
                    y_, m_ = int(mth[:4]), int(mth[5:])
                    nd_ = calendar.monthrange(y_, m_)[1]
                    wd_m = nd_ - sum(date(y_, m_, k).weekday() == we for k in range(1, nd_ + 1))
                    otr = r.ot_rate if r.ot_rate > 0 else r.rate / wd_m / std * otm
                    p_, w_ = gm[(gm.status == "Present") & ~gm.wk], gm[(gm.status == "Present") & gm.wk]
                    basic += r.rate / wd_m * (len(p_) + len(gm[(gm.status == "Leave") & ~gm.wk]))
                    ot_pay += p_.ot_hours.sum() * otr
                    wk_pay += (w_.hours + w_.ot_hours).sum() * otr
                food = r.food_allow * months * len(pres) / tp
            elif r.ot_rate > 0:     # Hourly with its own OT rate
                basic, ot_pay, wk_pay, food = reg_h * r.rate, ot_h * r.ot_rate, wk_h * r.ot_rate, 0
            else:                   # Hourly: no month basis, all hours worked x rate
                basic, ot_pay, wk_pay, food = (reg_h + ot_h + wk_h) * r.rate, 0, 0, 0
            add = ad[~ad.kind.isin(["Advance", "Deduction"])].amount.sum() if first else 0
            adv = ad[ad.kind == "Advance"].amount.sum() if first else 0
            ded = ad[ad.kind == "Deduction"].amount.sum() if first else 0
            first = False
            gosi = basic * gp / 100 if str(r.nationality).strip().lower() == gn else 0
            net = basic + food + ot_pay + wk_pay + add - adv - ded - gosi
            rows.append({"Code": r.code, "Name": r["name"], "Company": nm(cn, cid), "Section": nm(sn, sid),
                         "Sponsor": r.sponsor or "-", "Labour": r.labour_type, "Pay": r.pay_type, "Mode": r.pay_mode,
                         "Rate": r.rate, "Days": len(pres), "Leave": ld, "Absent": (g.status == "Absent").sum(),
                         "Hours": (pres.hours + pres.ot_hours).sum(), "OT Hrs": ot_h, "Wknd Hrs": wk_h, "Basic": basic, "Food": food,
                         "OT Pay": ot_pay, "Wknd OT": wk_pay, "Allowances": add, "Advance": adv,
                         "Deduction": ded, "GOSI": gosi, "Net": net, "Bank": net if r.pay_mode == "Bank" else 0,
                         "Cash": net if r.pay_mode != "Bank" else 0, "Invoice": (pres.hours + pres.ot_hours).sum() * r.bill_rate})
    df = pd.DataFrame(rows, columns=PCOLS).round(2)
    if sec: df = df[df.Section.isin(sec)]
    if co: df = df[df.Company.isin(co)]
    return df


init()
cur_ = S("currency")
LOGIN_CSS = """<style>
[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="collapsedControl"],[data-testid="stSidebarCollapsedControl"]{display:none}
.stApp{background:#f3f6fb}
.block-container{padding:0 !important;max-width:100% !important}
[data-testid="stHorizontalBlock"]{gap:0 !important}
.lg-left{min-height:100vh;box-sizing:border-box;padding:34px 56px;display:flex;flex-direction:column;justify-content:space-between;color:#fff;background:radial-gradient(circle at 88% 6%,rgba(255,255,255,.13) 0,rgba(255,255,255,0) 24%),radial-gradient(circle at 72% 60%,rgba(222,196,96,.30) 0,rgba(222,196,96,0) 16%),radial-gradient(circle at 6% 94%,rgba(70,110,210,.55) 0,rgba(70,110,210,0) 26%),linear-gradient(160deg,#0f2447 0%,#0f4c75 55%,#0e7c86 100%)}
.lg-left,.lg-left *{color:#fff !important}
.lg-brand{display:flex;align-items:center;gap:12px;font-size:17px}
.lg-logo{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:12px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);font-weight:800;font-size:15px}
.lg-mid h1{font-size:46px;line-height:1.08;font-weight:800;margin:0 0 18px;padding:0;letter-spacing:-.02em}
.lg-mid p{font-size:16px;line-height:1.6;max-width:470px;opacity:.9;margin:0 0 26px}
.lg-mid ul{list-style:none;padding:0;margin:0}
.lg-mid li{display:flex;align-items:center;gap:12px;margin:0 0 14px;font-size:15px}
.lg-mid li i{font-style:normal;width:26px;height:26px;border-radius:8px;background:rgba(255,255,255,.14);display:inline-flex;align-items:center;justify-content:center;font-size:13px}
.lg-foot{font-size:12px;opacity:.75}
[data-testid="stColumn"]:nth-child(2)>[data-testid="stVerticalBlock"],[data-testid="column"]:nth-child(2)>div>[data-testid="stVerticalBlock"]{min-height:100vh;justify-content:center;padding:0 12%}
[data-testid="stForm"]{background:#fff;border:none !important;border-radius:22px;padding:34px 32px 26px;box-shadow:0 20px 50px rgba(30,60,120,.12)}
.lg-head{text-align:center;margin-bottom:10px}
.lg-head h2{margin:12px 0 2px;padding:0;font-size:26px;font-weight:800;color:#0f2447 !important}
.lg-head p{margin:0;color:#64748b !important;font-size:14px}
.lg-head .lg-logo.big{width:58px;height:58px;border-radius:16px;font-size:20px;background:linear-gradient(135deg,#14808f,#2c6db3);color:#fff !important;border:none}
[data-testid="stForm"] label p{font-size:11px !important;font-weight:700 !important;letter-spacing:.05em;text-transform:uppercase;color:#334155 !important}
[data-testid="stTextInputRootElement"]{border-radius:12px;background:#f8fafc;border:1px solid #dbe3ee}
[data-testid="stFormSubmitButton"] button{width:100%;height:48px;border:none;border-radius:12px;font-weight:700;background:linear-gradient(90deg,#14808f,#2c6db3);box-shadow:0 8px 18px rgba(30,110,170,.30)}
[data-testid="stFormSubmitButton"] button p{color:#fff !important}
</style>"""

if "user" not in st.session_state:
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    nm_ = S("company")
    ini = ("".join(w[0] for w in nm_.split()[:2]) or "HR").upper()
    left, right = st.columns([1.15, 1], gap="small")
    left.markdown(
        f'<div class="lg-left"><div class="lg-brand"><span class="lg-logo">{html.escape(ini)}</span>'
        f'<b>{html.escape(nm_)}</b></div><div class="lg-mid"><h1>Your whole workforce,<br>one clear dashboard.</h1>'
        '<p>Attendance, leave, payroll and Iqama / ID dates for every company, section and kofil, '
        'always up to date and always in one place.</p><ul>'
        '<li><i>✓</i>Alerts before any Iqama / ID expires</li>'
        '<li><i>✓</i>Company, section and kofil wise reports</li>'
        '<li><i>✓</i>Custom date range on every page</li>'
        '<li><i>✓</i>Secure sign in with your own access level</li></ul></div>'
        f'<div class="lg-foot">© {html.escape(nm_)}</div></div>', unsafe_allow_html=True)
    with right:
        with st.form("login"):
            st.markdown(f'<div class="lg-head"><span class="lg-logo big">{html.escape(ini)}</span>'
                        '<h2>Welcome back</h2><p>Sign in to continue</p></div>', unsafe_allow_html=True)
            u = st.text_input("Username", placeholder="👤  your username")
            p_ = st.text_input("Password", type="password", placeholder="🔒  your password")
            if st.form_submit_button("Sign in", use_container_width=True):
                r_ = q("SELECT * FROM users WHERE username=? AND pw=?", (u.strip(), pw(p_)))
                if len(r_):
                    st.session_state.user, st.session_state.role = r_.username[0], r_.role[0]
                    st.rerun()
                else:
                    st.error("Wrong username or password")
        if q("SELECT COUNT(*) AS n FROM users WHERE username='admin' AND pw=?", (pw("admin123"),)).n[0]:
            st.caption("First login: admin / admin123 - change it in Users after signing in.")
        else:
            st.caption("Forgot your password? Ask your administrator to reset it.")
    st.stop()
role = st.session_state.role
ALL = ["Dashboard", "Employees", "Setup", "Attendance", "Leave", "Adjustments", "Costs", "Payroll",
       "Invoices", "Reports", "Import", "Settings"]
MENU = {"Admin": ALL + ["Users"], "HR": ALL, "Manager": ["Dashboard", "Attendance", "Leave", "Reports"]}[role]
st.sidebar.title(f"🏢 {S('company')}")
st.sidebar.write(f"👤 {st.session_state.user} ({role})")
if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()
ICON = {"Dashboard": "🏠", "Employees": "👥", "Setup": "🏷️", "Attendance": "🗓️", "Leave": "🌴", "Adjustments": "➕",
        "Costs": "🧾", "Payroll": "💵", "Invoices": "📑", "Reports": "📊", "Import": "📥", "Settings": "⚙️", "Users": "🔑"}
page = st.sidebar.radio("Menu", MENU, format_func=lambda x: f"{ICON.get(x, '')}  {x}")
st.sidebar.caption(f"Today: {today().strftime(S('date_fmt'))} ({S('timezone')})")

# ---------------- Dashboard
if page == "Dashboard":
    st.header("Dashboard")
    e = emp_df()
    t = str(today())
    m1 = today().replace(day=1)
    me = (m1.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    a = q("""SELECT a.status, COALESCE(a.hours,0) AS hours, COALESCE(a.ot_hours,0) AS ot_hours, e.name FROM attendance a JOIN employees e ON e.id=a.emp_id
        WHERE a.day=? AND e.active=1 ORDER BY a.id DESC""", (t,))
    n = len(e)
    pr, ab, lv = (int((a.status == x).sum()) for x in ("Present", "Absent", "Leave"))
    nm = max(n - pr - ab - lv, 0)

    def donut(parts, center, label):
        tot = sum(v for _, v, _ in parts)
        acc, stops = 0, []
        for _, v, col in parts:
            if v:
                stops.append(f"{col} {acc / tot * 100:.1f}% {(acc + v) / tot * 100:.1f}%")
                acc += v
        bg = ",".join(stops) or "#dfe8e1 0% 100%"
        leg = "".join(f'<div><span class="dot" style="background:{col}"></span>{nme}'
                      f'<b style="float:right">{v}</b></div>' for nme, v, col in parts)
        return (f'<div class="row"><div class="donut" style="background:conic-gradient({bg})"><div>'
                f'<b>{center}</b>{label}</div></div><div class="leg">{leg}</div></div>')

    kp = [("👥", "Total Employees", n, "#e3f4e8"), ("🧍", "Present Today", pr, "#e3f4e8"),
          ("🌴", "On Leave", lv, "#fdf1d6"), ("🚫", "Absent", ab, "#fbe3df")]
    for col_, (ic, lb, v, bg) in zip(st.columns(4), kp):
        col_.markdown(f'<div class="card kpi"><div class="ic" style="background:{bg}">{ic}</div>'
                      f'<div><div class="lb">{lb}</div><div class="v">{v}</div></div></div>',
                      unsafe_allow_html=True)
    st.write("")
    c1, c2 = st.columns(2)
    c1.markdown('<div class="card"><div class="ttl">Attendance Overview</div>' + donut(
        [("Present", pr, "#2e7d4f"), ("Absent", ab, "#d64933"), ("On Leave", lv, "#f0b429"),
         ("Not marked", nm, "#cfd8d2")], pr, "Present") + "</div>", unsafe_allow_html=True)
    lvs = q("SELECT status FROM leaves WHERE start<=? AND end>=?", (str(me), str(m1))).status
    L = lambda x: int((lvs == x).sum())
    c2.markdown('<div class="card"><div class="ttl">Leave Overview (this month)</div>' + donut(
        [("Approved", L("Approved"), "#2e7d4f"), ("Pending", L("Pending"), "#f0b429"),
         ("Rejected", L("Rejected"), "#d64933")], len(lvs), "Total") + "</div>", unsafe_allow_html=True)
    st.write("")
    c3, c4 = st.columns(2)
    rc = a[a.status == "Present"].head(5)
    items = "".join(
        f'<div class="ci"><div class="av">{html.escape(str(r["name"])[:1].upper())}</div>'
        f'<div><b>{html.escape(str(r["name"]))}</b><br><small>{r.hours:g}h + OT {r.ot_hours:g}h</small></div>'
        f'<span class="badge">{r.status}</span></div>' for _, r in rc.iterrows()
    ) or "<small>No check-ins today yet.</small>"
    c3.markdown(f'<div class="card"><div class="ttl">Recent Check-ins</div>{items}</div>',
                unsafe_allow_html=True)
    vals = []
    for i in range(5, -1, -1):
        mm, yy = today().month - i, today().year
        while mm <= 0:
            mm, yy = mm + 12, yy - 1
        s0 = date(yy, mm, 1)
        e0 = (s0.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        pdf = calc_payroll(str(s0), str(e0), [], [], [], [])
        vals.append((s0.strftime("%b"), float(pdf.Net.sum()) if len(pdf) else 0.0))
    mx = max(v for _, v in vals) or 1
    bars = "".join(f'<div><span style="height:{v / mx * 80:.0f}%"></span>{l}</div>' for l, v in vals)
    c4.markdown(f'<div class="card"><div class="ttl">Monthly Payroll Summary</div>'
                f'<small>Net payroll this month</small>'
                f'<div style="font-size:26px;font-weight:700">{vals[-1][1]:,.0f} {cur_}</div>'
                f'<div class="bars">{bars}</div></div>', unsafe_allow_html=True)
    st.write("")
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
    cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    pick = lambda t, n: None if n == "-" else int(t[t.name == n].id.iloc[0])
    with st.expander("➕ Add / update employee (same code = update)"):
        with st.form("emp"):
            c = st.columns(4)
            code, name = c[0].text_input("Code"), c[1].text_input("Name")
            nat, idn = c[2].text_input("Nationality"), c[3].text_input("ID / Iqama / Residence no.")
            co = c[0].selectbox("Client company", ["-"] + cm.name.tolist())
            sec = c[1].selectbox("Section", ["-"] + ds.name.tolist())
            spn = c[2].selectbox("Sponsor / Kofil", ["-"] + sp.name.tolist())
            lt = c[3].selectbox("Labour type", ["Company", "Outside"])
            pt = c[0].selectbox("Pay type", ["Monthly", "Hourly"])
            pm = c[1].selectbox("Pay mode", ["Bank", "Cash"])
            rate = c[2].number_input("Rate (monthly basic; per hour if Hourly)", 0.0)
            food = c[3].number_input("Food allowance / month", 0.0)
            otr = c[0].number_input("OT rate / hour (0 = auto)", 0.0)
            bill = c[1].number_input("Bill rate / hour (client invoice)", 0.0)
            ph, jd = c[2].text_input("Phone"), c[3].date_input("Join date", today())
            exp = c[0].date_input("ID expiry", today() + timedelta(days=365))
            if st.form_submit_button("Save") and code and name:
                save_emp(dict(code=code, name=name, nationality=nat, id_no=idn, company_id=pick(cm, co),
                              dept_id=pick(ds, sec), sponsor_id=pick(sp, spn), labour_type=lt, pay_type=pt,
                              pay_mode=pm, rate=rate, food_allow=food, ot_rate=otr, bill_rate=bill, phone=ph,
                              join_date=str(jd), id_expiry=str(exp)))
                st.success("Saved"); st.rerun()
    f = filters("emp")
    df = apply_f(emp_df(), *f[2:]).drop(columns=["id", "company_id", "dept_id", "sponsor_id"])
    st.dataframe(df, use_container_width=True, hide_index=True)
    download(df, "employees")
    if len(df):
        x = st.selectbox("Deactivate employee", df.code + " - " + df["name"])
        if st.button("Deactivate"):
            q("UPDATE employees SET active=0 WHERE code=?", (x.split(" - ")[0],), fetch=False); st.rerun()

# ---------------- Setup
elif page == "Setup":
    st.header("Setup: Client companies, Sections, Sponsors / Kofil")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Client companies")
        n, v = st.text_input("Company name"), st.text_input("VAT / Tax no")
        if st.button("Add company") and n:
            q("INSERT OR IGNORE INTO companies(name,vat) VALUES(?,?)", (n, v), fetch=False); st.rerun()
        st.dataframe(q("SELECT name, vat FROM companies"), hide_index=True)
    with c2:
        st.subheader("Sections")
        n = st.text_input("New section")
        if st.button("Add section") and n:
            q("INSERT OR IGNORE INTO departments(name) VALUES(?)", (n,), fetch=False); st.rerun()
        st.dataframe(q("SELECT name FROM departments"), hide_index=True)
    with c3:
        st.subheader("Sponsors / Kofil")
        n, p_ = st.text_input("Sponsor / Kofil name"), st.text_input("Phone")
        if st.button("Add sponsor") and n:
            q("INSERT OR IGNORE INTO sponsors(name,phone) VALUES(?,?)", (n, p_), fetch=False); st.rerun()
        st.dataframe(q("SELECT name, phone FROM sponsors"), hide_index=True)

# ---------------- Attendance
elif page == "Attendance":
    st.header("Attendance: P / A / L, normal hours & OT hours")
    cm, ds, sp = q("SELECT * FROM companies"), q("SELECT * FROM departments"), q("SELECT * FROM sponsors")
    cn, sn = dict(zip(cm.id, cm.name)), dict(zip(ds.id, ds.name))
    ci, si = {v: int(k) for k, v in cn.items()}, {v: int(k) for k, v in sn.items()}
    cl, sl, kl = list(cn.values()), list(sn.values()), sp.name.tolist()
    c = st.columns([1, 1.2, 1.2, 1.2, 1.2])
    day = dbox(c[0], "Date", today(), "att_d")
    with c[1]:
        fco = msel("Company *", cl, "att_co", False, "Select (required)")
    with c[2]:
        fsec = msel("Section *", sl, "att_sec", False, "Select (required)")
    with c[3]:
        fspn = msel("Sponsor / Kofil *", kl, "att_spn", False, "Select (required)")
    with c[4]:
        fst = msel("Status filter", list(LBL.values()) + ["Not marked"], "att_st")
    qs = st.text_input("🔎 Search code / name", key="att_q")
    if not (fco and fsec and fspn):
        st.warning("Company, Section and Sponsor / Kofil are mandatory. Select them (or choose 'All') "
                   "to open the attendance sheet.")
    else:
        e = apply_f(emp_df(), eff(fsec, sl), (), (), eff(fspn, kl), eff(fco, cl), qs)
        old = q("SELECT * FROM attendance WHERE day=?", (str(day),))
        dn, do_ = float(S("def_normal")), float(S("def_ot"))
        wkend = day.weekday() == int(S("weekend"))
        nm = lambda v, d: d.get(int(v), "") if pd.notna(v) else ""
        rows = []
        for _, r in e.iterrows():
            o = old[old.emp_id == r.id]
            h = o.iloc[0] if len(o) else None
            cur = CODE.get(h["status"], "P") if h is not None else None
            if eff(fst) and (LBL[cur] if cur else "Not marked") not in fst:
                continue
            g = lambda col, dflt: h[col] if h is not None and pd.notna(h[col]) else dflt
            stt = cur or ("O" if wkend else "P")
            sv = h is not None and stt == "P"
            rows.append({"id": r.id, "Code": r.code, "Name": r["name"], "Labour": r.labour_type, "Sponsor": r.sponsor or "",
                         "Company": nm(g("company_id", None), cn) or (r.company or ""),
                         "Section": nm(g("dept_id", None), sn) or (r.section or ""),
                         "OT Rate": ot_rate_of(r.rate, r.pay_type, r.ot_rate, str(day)), "Status": LBL[stt],
                         "Normal Hrs": float(g("hours", dn)) if sv else dn,
                         "OT Hrs": float(g("ot_hours", 0.0)) if sv else do_})
        if wkend:
            st.info("This date is the weekend day: everyone starts as O (no work, no pay). Change to P only for those "
                    "who worked - all their hours are then paid as OT.")
        ed = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                            key=f"att{day}{fco}{fsec}{fspn}{fst}{qs}",
                            disabled=["id", "Code", "Name", "Labour", "Sponsor", "OT Rate"],
                            column_config={"id": None,
                                           "Company": st.column_config.SelectboxColumn(options=[""] + cl),
                                           "Section": st.column_config.SelectboxColumn(options=[""] + sl),
                                           "Status": st.column_config.SelectboxColumn(options=list(LBL.values()),
                                                                                      help="P=Present, A=Absent, L=Leave, O=Off"),
                                           "Normal Hrs": st.column_config.NumberColumn(min_value=0.0, max_value=24.0, step=0.5),
                                           "OT Hrs": st.column_config.NumberColumn(min_value=0.0, max_value=16.0, step=0.5)})
        st.caption("🟢 P = Present (paid), 🟡 L = Leave (paid), 🔴 A = Absent (not paid), ⚪ O = Off (not paid). Normal and "
                   "OT hours are pre-filled from Settings - change per person if different. Monthly staff are paid per "
                   "day; OT hours are paid extra. Weekend day: no work = no pay, work = all hours paid as OT. "
                   "Hourly staff: no month basis - total hours worked x hourly rate.")
        if st.button("💾 Save attendance"):
            for _, r in ed.iterrows():
                code = r.Status[-1]
                pr_ = code == "P"
                q("INSERT INTO attendance(emp_id,day,status,hours,ot_hours,company_id,dept_id) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT(emp_id,day) DO UPDATE SET status=excluded.status,hours=excluded.hours,"
                  "ot_hours=excluded.ot_hours,company_id=excluded.company_id,dept_id=excluded.dept_id",
                  (int(r.id), str(day), REV[code], float(r["Normal Hrs"]) if pr_ else 0.0,
                   float(r["OT Hrs"]) if pr_ else 0.0, ci.get(r.Company), si.get(r.Section)), fetch=False)
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
    d1, d2, sec, lt, pt, spn, co, qs = filters("lv")
    df = q("""SELECT l.id, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type, e.pay_type,
        l.ltype, l.start, l.end, l.days, l.status FROM leaves l JOIN employees e ON e.id=l.emp_id
        LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id LEFT JOIN companies c ON c.id=e.company_id
        WHERE l.start<=? AND l.end>=?""", (d2, d1))
    df = apply_f(df, sec, lt, pt, spn, co, qs)
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
        k = c[1].selectbox("Type", ["Advance", "Deduction", "Bonus", "Allowance", "Supervisor/Operator", "Foundation Day", "Skill/Villa", "Extra", "Eid Bonus"])
        am = c[2].number_input("Amount", 0.0)
        dy = c[3].date_input("Date", today())
        nt = c[4].text_input("Note")
        if st.form_submit_button("Add"):
            eid = int(e[e.code == x.split(" - ")[0]].id.iloc[0])
            q("INSERT INTO adjustments(emp_id,day,kind,amount,note) VALUES(?,?,?,?,?)",
              (eid, str(dy), k, am, nt), fetch=False)
            st.rerun()
    f = filters("adj")
    df = q("""SELECT a.id, a.day, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type,
        e.pay_type, a.kind, a.amount, a.note FROM adjustments a JOIN employees e ON e.id=a.emp_id
        LEFT JOIN departments d ON d.id=e.dept_id LEFT JOIN sponsors s ON s.id=e.sponsor_id LEFT JOIN companies c ON c.id=e.company_id
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

# ---------------- Costs
elif page == "Costs":
    st.header("Costs: ID/Iqama, permits, insurance, tickets, medical...")
    e, cm = emp_df(), q("SELECT * FROM companies")
    with st.form("cost"):
        c = st.columns(5)
        x = c[0].selectbox("Employee (optional)", ["-"] + (e.code + " - " + e["name"]).tolist())
        cat = c[1].selectbox("Category", ["ID / Iqama (Juazat)", "Work permit", "Insurance", "Transfer", "Muqeem / Monduf fee",
                                          "Exit re-entry", "Passport", "Medical", "Vacation ticket", "GOSI", "Other"])
        co_ = c[2].selectbox("Client company", ["-"] + cm.name.tolist())
        am, dy = c[3].number_input("Amount", 0.0), c[4].date_input("Date", today())
        nt = st.text_input("Note")
        if st.form_submit_button("Add"):
            eid = None if x == "-" else int(e[e.code == x.split(" - ")[0]].id.iloc[0])
            cid = None if co_ == "-" else int(cm[cm.name == co_].id.iloc[0])
            q("INSERT INTO costs(day,category,emp_id,company_id,amount,note) VALUES(?,?,?,?,?,?)",
              (str(dy), cat, eid, cid, am, nt), fetch=False); st.rerun()
    f = filters("cost")
    df = q("""SELECT x.id, x.day, x.category, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor,
        e.labour_type, e.pay_type, x.amount, x.note FROM costs x LEFT JOIN employees e ON e.id=x.emp_id
        LEFT JOIN companies c ON c.id=x.company_id LEFT JOIN departments d ON d.id=e.dept_id
        LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE x.day BETWEEN ? AND ?""", (f[0], f[1]))
    df = apply_f(df, *f[2:])
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.dataframe(df.groupby("category").amount.sum().reset_index(), hide_index=True)
    download(df, "costs")
    rid = st.number_input("Delete cost ID", 0, step=1)
    if st.button("Delete cost") and rid:
        q("DELETE FROM costs WHERE id=?", (int(rid),), fetch=False); st.rerun()

# ---------------- Invoices
elif page == "Invoices":
    st.header("Client invoices & company-wise profit")
    f = filters("inv")
    p = calc_payroll(*f)
    vat = float(S("vat_pct"))
    if len(p):
        g = p.groupby("Company").agg(Labour=("Code", "nunique"), Hours=("Hours", "sum"), Invoice=("Invoice", "sum"),
                                     Payroll=("Net", "sum")).reset_index()
        cost = q("""SELECT COALESCE(c.name,'-') AS Company, SUM(x.amount) AS Costs FROM costs x
            LEFT JOIN companies c ON c.id=x.company_id WHERE x.day BETWEEN ? AND ? GROUP BY 1""", (f[0], f[1]))
        g = g.merge(cost, how="left", on="Company").fillna({"Costs": 0})
        g["VAT"] = g.Invoice * vat / 100
        g["Invoice + VAT"] = g.Invoice + g.VAT
        g["Profit"] = g.Invoice - g.Payroll - g.Costs
        g = g.round(2)
        st.dataframe(g, use_container_width=True, hide_index=True)
        c = st.columns(3)
        c[0].metric("Invoice (ex VAT)", f"{g.Invoice.sum():,.2f} {cur_}")
        c[1].metric("Payroll + costs", f"{g.Payroll.sum() + g.Costs.sum():,.2f} {cur_}")
        c[2].metric("Profit / Loss", f"{g.Profit.sum():,.2f} {cur_}")
        download(g, "company_profit")
        who = st.selectbox("Invoice detail for company", g.Company)
        d = p[p.Company == who][["Name", "Section", "Hours", "Invoice"]].copy()
        d["Rate/hr"] = (d.Invoice / d.Hours.where(d.Hours > 0)).round(2)
        st.dataframe(d, use_container_width=True, hide_index=True)
        download(d, "invoice_" + who.replace(" ", "_"))
    else:
        st.info("No attendance in this range.")

# ---------------- Import
elif page == "Import":
    st.header("Bulk import employees (Excel / CSV)")
    T = ["Code", "Name", "Nationality", "ID No", "Phone", "Company", "Section", "Sponsor", "Labour Type", "Pay Type",
         "Pay Mode", "Rate", "Food Allow", "OT Rate", "Bill Rate", "Join Date", "ID Expiry"]
    st.download_button("⬇ Download template", pd.DataFrame(columns=T).to_csv(index=False), "employee_template.csv")
    st.caption("Labour Type: Company / Outside. Pay Type: Monthly / Hourly. Pay Mode: Bank / Cash. "
               "Companies, sections and sponsors are created automatically. Same Code = update.")
    up = st.file_uploader("Upload .xlsx or .csv", type=["xlsx", "csv"])
    if up is not None:
        df = pd.read_csv(up, dtype=str) if up.name.endswith(".csv") else pd.read_excel(up, dtype=str)
        st.dataframe(df.head(20), use_container_width=True)
        if st.button("Import now"):
            txt = lambda v: "" if pd.isna(v) else str(v).strip()
            num = lambda v: 0.0 if pd.isna(pd.to_numeric(v, errors="coerce")) else float(v)
            dt = lambda v: "" if pd.isna(pd.to_datetime(v, errors="coerce")) else str(pd.to_datetime(v).date())

            def idof(tbl, v):
                v = txt(v)
                if not v:
                    return None
                q(f"INSERT OR IGNORE INTO {tbl}(name) VALUES(?)", (v,), fetch=False)
                return int(q(f"SELECT id FROM {tbl} WHERE name=?", (v,)).id[0])

            n = 0
            for _, r in df.iterrows():
                if not txt(r.get("Code")):
                    continue
                save_emp(dict(code=txt(r.get("Code")), name=txt(r.get("Name")), nationality=txt(r.get("Nationality")),
                              id_no=txt(r.get("ID No")), phone=txt(r.get("Phone")), company_id=idof("companies", r.get("Company")),
                              dept_id=idof("departments", r.get("Section")), sponsor_id=idof("sponsors", r.get("Sponsor")),
                              labour_type=txt(r.get("Labour Type")) or "Company", pay_type=txt(r.get("Pay Type")) or "Monthly",
                              pay_mode=txt(r.get("Pay Mode")) or "Bank", rate=num(r.get("Rate")),
                              food_allow=num(r.get("Food Allow")), ot_rate=num(r.get("OT Rate")),
                              bill_rate=num(r.get("Bill Rate")), join_date=dt(r.get("Join Date")) or str(today()),
                              id_expiry=dt(r.get("ID Expiry"))))
                n += 1
            st.success(f"Imported / updated {n} employees")

# ---------------- Reports
elif page == "Reports":
    st.header("Reports (custom date range)")
    kinds = ["Attendance detail", "Attendance summary", "Attendance sheet (P/A/L)"]
    if role != "Manager":
        kinds += ["Payroll sheet", "Company-wise", "Section-wise", "Kofil-wise", "Company x Kofil matrix",
                  "Hours (hourly basis)", "ID / Iqama expiry", "EOSB provision"]
    kind = st.selectbox("Report", kinds)
    f = filters("rep")
    d1, d2 = f[0], f[1]

    def split(p, g):
        out = []
        for k, x in p.groupby(g):
            c_, o_ = x[x.Labour == "Company"], x[x.Labour == "Outside"]
            out.append({g: k, "Com. Persons": c_.Code.nunique(), "Com. Cash": c_.Cash.sum(), "Com. Bank": c_.Bank.sum(),
                        "Com. Subtotal": c_.Net.sum(), "Out Persons": o_.Code.nunique(), "Out Cash": o_.Cash.sum(),
                        "Out Bank": o_.Bank.sum(), "Out Subtotal": o_.Net.sum(), "Total": x.Net.sum()})
        t = pd.DataFrame(out)
        if len(t):
            tot = t.sum(numeric_only=True)
            tot[g] = "TOTAL"
            t = pd.concat([t, tot.to_frame().T], ignore_index=True)
        return t

    if kind == "Attendance detail":
        df = q("""SELECT a.day, e.code, e.name, COALESCE(c.name,c0.name) AS company, COALESCE(d.name,d0.name) AS section,
            s.name AS sponsor, e.labour_type, e.pay_type, a.status, a.hours, a.ot_hours
            FROM attendance a JOIN employees e ON e.id=a.emp_id
            LEFT JOIN companies c ON c.id=a.company_id LEFT JOIN companies c0 ON c0.id=e.company_id
            LEFT JOIN departments d ON d.id=a.dept_id LEFT JOIN departments d0 ON d0.id=e.dept_id
            LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE a.day BETWEEN ? AND ? ORDER BY a.day""", (d1, d2))
        df = apply_f(df, *f[2:])
    elif kind == "Attendance sheet (P/A/L)":
        df = q("""SELECT e.code, e.name, COALESCE(c.name,c0.name,'-') AS company, COALESCE(d.name,d0.name,'-') AS section,
            s.name AS sponsor, e.labour_type, e.pay_type, e.rate AS rate, e.ot_rate AS ot_rate, a.day, a.status, a.hours,
            COALESCE(a.ot_hours,0) AS ot FROM attendance a JOIN employees e ON e.id=a.emp_id
            LEFT JOIN companies c ON c.id=a.company_id LEFT JOIN companies c0 ON c0.id=e.company_id
            LEFT JOIN departments d ON d.id=a.dept_id LEFT JOIN departments d0 ON d0.id=e.dept_id
            LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE a.day BETWEEN ? AND ?""", (d1, d2))
        df = apply_f(df, *f[2:])
        if len(df):
            wk = pd.to_datetime(df.day).dt.weekday == int(S("weekend"))
            pre, hh = df.status == "Present", df.hours.fillna(0)
            df["nh"] = hh.where(pre & ~wk, 0)
            df["oh"] = df.ot.where(pre & ~wk, 0) + (hh + df.ot).where(pre & wk, 0)
            df["c"], df["d"] = df.status.map(CODE).fillna("?"), df.day.str[5:]
            rt = {x.code: ot_rate_of(x.rate, x.pay_type, x.ot_rate, d2) for x in df.drop_duplicates("code").itertuples()}
            ix = ["code", "name", "company", "section"]
            grid = df.pivot_table(index=ix, columns="d", values="c", aggfunc="first").fillna("")
            tot = df.groupby(ix).agg(P=("c", lambda x: (x == "P").sum()), A=("c", lambda x: (x == "A").sum()),
                                     L=("c", lambda x: (x == "L").sum()), Normal_Hrs=("nh", "sum"), OT_Hrs=("oh", "sum"))
            tot["OT_Rate"] = [rt[i[0]] for i in tot.index]
            tot["OT_Amount"] = (tot.OT_Hrs * tot.OT_Rate).round(2)
            df = grid.join(tot).reset_index()
            if role == "Manager":
                df = df.drop(columns=["OT_Rate", "OT_Amount"])
    elif kind == "ID / Iqama expiry":
        e = apply_f(emp_df(), *f[2:])
        x = e.id_expiry.fillna("")
        df = e[(x >= d1) & (x <= d2) & (x != "")][["code", "name", "company", "section", "sponsor", "id_no", "id_expiry"]]
        df = df.sort_values("id_expiry")
    elif kind == "EOSB provision":
        out = []
        for _, r in apply_f(emp_df(), *f[2:]).iterrows():
            y, w, a_ = eosb(r, date.fromisoformat(d2))
            out.append({"Code": r.code, "Name": r["name"], "Company": r.company, "Section": r.section,
                        "Sponsor": r.sponsor, "Join date": r.join_date, "Years": y, "Monthly wage": w, "EOSB due": a_})
        df = pd.DataFrame(out)
    else:
        p = calc_payroll(*f)
        if kind == "Attendance summary":
            df = p[["Code", "Name", "Company", "Section", "Sponsor", "Labour", "Days", "Leave", "Absent", "Hours", "OT Hrs", "Wknd Hrs"]]
        elif kind == "Payroll sheet":
            df = p
        elif kind == "Hours (hourly basis)":
            df = p[p.Pay == "Hourly"][["Code", "Name", "Company", "Section", "Sponsor", "Rate", "Hours", "OT Hrs", "Wknd Hrs", "Net"]]
        elif kind == "Company x Kofil matrix":
            df = p.pivot_table(index="Company", columns="Sponsor", values="Net", aggfunc="sum", fill_value=0,
                               margins=True, margins_name="TOTAL").reset_index() if len(p) else p
        else:
            df = split(p, {"Company-wise": "Company", "Section-wise": "Section", "Kofil-wise": "Sponsor"}[kind])
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
        wd = st.number_input("Working days/month (only for EOSB of hourly staff; monthly salary days are automatic)", 1.0, 31.0, float(S("work_days")))
        ot = st.number_input("Overtime multiplier", 1.0, 5.0, float(S("ot_mult")))
        df_ = st.selectbox("Date format", ["%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"])
        gp = st.number_input("GOSI employee deduction % (0 = off)", 0.0, 100.0, float(S("gosi_pct")))
        gn = st.text_input("GOSI applies to nationality", S("gosi_nat"))
        vp = st.number_input("VAT % on client invoices", 0.0, 100.0, float(S("vat_pct")))
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        wk = st.selectbox("Weekend OT day (hours worked this day are paid at OT rate)", days, int(S("weekend")))
        dn = st.number_input("Default normal hours (auto-filled in Attendance)", 0.0, 24.0, float(S("def_normal")))
        do_ = st.number_input("Default OT hours (auto-filled in Attendance)", 0.0, 16.0, float(S("def_ot")))
        if st.form_submit_button("Save"):
            for k, v in dict(company=co, currency=cu, timezone=tz, std_hours=sh, work_days=wd,
                             ot_mult=ot, date_fmt=df_, gosi_pct=gp, gosi_nat=gn, vat_pct=vp, weekend=days.index(wk), def_normal=dn, def_ot=do_).items():
                q("REPLACE INTO settings VALUES(?,?)", (k, str(v)), fetch=False)
            st.success("Saved"); st.rerun()


# =====================================================================================
# EDIT / DELETE  (paste this whole block at the VERY END of hrm_app.py, no indentation)
# =====================================================================================
CAN_EDIT = ("Admin", "HR")      # roles that can edit   (change here if you want)
CAN_DELETE = ("Admin",)         # roles that can delete (change here if you want)


def manage(table, sql, params=(), edit=(), fks=None, selects=None, hide=(), used_in=(), cascade=(), key="m",
           after_upd=None, before_del=None, guard=None, flt=None, cols=None):
    """Inline Edit + Delete grid for any table. `sql` must return `id` plus the columns to show."""
    can_e, can_d = role in CAN_EDIT, role in CAN_DELETE
    if not (can_e or can_d):
        return
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    fks, selects = fks or {}, selects or {}
    df = q(sql, params)
    fsig = ""
    if flt:   # Company / Section / Kofil / Labour / Pay type boxes with 'All' inside, same as the report pages
        cos, secs, spns = (q(f"SELECT name FROM {t}").name.tolist() for t in ("companies", "departments", "sponsors"))
        c = cols or st.columns(5)
        with c[0]:
            co = eff(msel("Company", cos, flt + "_co"), cos)
        with c[1]:
            sec = eff(msel("Section", secs, flt + "_sec"), secs)
        with c[2]:
            spn = eff(msel("Sponsor / Kofil", spns, flt + "_spn"), spns)
        with c[3]:
            lt = eff(msel("Labour", ["Company", "Outside"], flt + "_lab"), ["Company", "Outside"])
        with c[4]:
            pt = eff(msel("Pay type", ["Monthly", "Hourly"], flt + "_pay"), ["Monthly", "Hourly"])
        df = apply_f(df, sec, lt, pt, spn, co).reset_index(drop=True)
        fsig = str((co, sec, spn, lt, pt))
    sq_ = st.text_input("🔎 Search", key=key + "q")
    if sq_ and not df.empty:
        df = df[df.astype(str).apply(lambda col: col.str.contains(sq_, case=False, regex=False)).any(axis=1)].reset_index(drop=True)
    if df.empty:
        st.info("No records.")
        return
    lk = {c: q(f"SELECT id,name FROM {t}") for c, (_, t) in fks.items()}
    view = df.copy()
    for c in fks:
        view[c] = view[c].fillna("")
    all_del = False
    if can_d:
        all_del = st.checkbox("☑ Select all rows for Delete (only the rows shown below)", key=f"{key}da{st.session_state.get(key + 'v', 0)}")
        view.insert(1, "Delete", all_del)
    cfg = {"id": None, **{h: None for h in hide}}
    for c, t in lk.items():
        cfg[c] = st.column_config.SelectboxColumn(options=[""] + t.name.tolist())
    for c, o in selects.items():
        cfg[c] = st.column_config.SelectboxColumn(options=o)
    editable = (list(edit) + list(fks)) if can_e else []
    if can_d:
        editable.append("Delete")
    ver = st.session_state.get(key + "v", 0)
    ed = st.data_editor(view, hide_index=True, use_container_width=True, column_config=cfg,
                        disabled=[c for c in view.columns if c not in editable], key=f"{key}{ver}{sq_}{fsig}{all_del}")

    def done(msg):
        st.session_state[key + "v"] = ver + 1
        st.session_state["flash"] = msg
        st.rerun()

    if can_e and st.button("💾 Save changes", key=key + "s"):
        n = 0
        for i, r in ed.iterrows():
            o, sets = view.loc[i], {}
            for c in list(edit) + list(fks):
                a, b = r[c], o[c]
                if (pd.isna(a) and pd.isna(b)) or a == b:
                    continue
                if c in fks:
                    t = lk[c]
                    m = t[t.name == a].id
                    sets[fks[c][0]] = int(m.iloc[0]) if len(m) else None
                else:
                    sets[c] = None if pd.isna(a) else (a.item() if hasattr(a, "item") else a)
            if sets:
                try:
                    q(f"UPDATE {table} SET " + ",".join(f"{k}=?" for k in sets) + " WHERE id=?",
                      (*sets.values(), int(r["id"])), fetch=False)
                    if after_upd:
                        after_upd(o, r)
                    n += 1
                except Exception as ex:
                    st.error(f"Row {int(r['id'])}: {ex}")
                    return
        done(f"{n} row(s) updated")

    if can_d:
        sel = ed[ed["Delete"] == True]  # noqa: E712
        if len(sel):
            ok = st.checkbox(f"Yes, permanently delete {len(sel)} selected row(s)"
                             + (" together with their attendance, leave, adjustments and costs" if cascade else ""),
                             key=key + "ck")
            if st.button("🗑 Delete ticked rows", key=key + "d"):
                if not ok:
                    st.warning("Tick the confirm box first.")
                else:
                    errs, n = [], 0
                    for _, r in sel.iterrows():
                        i = int(r["id"])
                        msg = guard(r) if guard else None
                        busy = [t for t, c in used_in if q(f"SELECT COUNT(*) AS n FROM {t} WHERE {c}=?", (i,)).n[0]]
                        if msg or busy:
                            errs.append(msg or f"id {i} is still used in '{busy[0]}' - reassign it first")
                            continue
                        if before_del:
                            before_del(r)
                        for t, c in cascade:
                            q(f"DELETE FROM {t} WHERE {c}=?", (i,), fetch=False)
                        q(f"DELETE FROM {table} WHERE id=?", (i,), fetch=False)
                        n += 1
                    if n:
                        done(f"{n} row(s) deleted" + (" | skipped: " + " | ".join(errs) if errs else ""))
                    else:
                        st.error(" | ".join(errs))


def dr(key, cols=None):
    c = cols or st.columns(2)
    return str(dbox(c[0], "From", today().replace(day=1), key + "1")), str(dbox(c[1], "To", today(), key + "2"))


def lv_clear(r):  # remove the attendance rows an approved leave created
    if r["status"] == "Approved":
        q("DELETE FROM attendance WHERE emp_id=? AND status IN ('Leave','Absent') AND day BETWEEN ? AND ?",
          (int(r["emp_id"]), r["start"], r["end"]), fetch=False)


def lv_sync(o, r):  # after editing a leave: recalc days and rebuild its attendance rows
    s0, e0 = pd.to_datetime(r["start"]), pd.to_datetime(r["end"])
    days = int((e0 - s0).days + 1)
    q("UPDATE leaves SET days=? WHERE id=?", (days, int(r["id"])), fetch=False)
    if r["status"] == "Approved":
        lv_clear(o)
        for k in range(days):
            q("INSERT INTO attendance(emp_id,day,status,hours) VALUES(?,?,?,0) ON CONFLICT(emp_id,day) "
              "DO UPDATE SET status=excluded.status",
              (int(r["emp_id"]), str(s0.date() + timedelta(k)), "Absent" if r["ltype"] == "Unpaid" else "Leave"),
              fetch=False)


if role in CAN_EDIT + CAN_DELETE and page in ("Employees", "Setup", "Attendance", "Leave", "Adjustments", "Costs", "Users"):
    st.divider()
    st.subheader("✏️ Edit / 🗑 Delete")
    st.caption("Choose Company / Section / Kofil (or All), change cells, then press Save. To delete: tick 'Delete', "
               "confirm, press Delete. Dates are YYYY-MM-DD.")
    EJ = (" LEFT JOIN companies c ON c.id=e.company_id LEFT JOIN departments d ON d.id=e.dept_id"
          " LEFT JOIN sponsors s ON s.id=e.sponsor_id ")
    EC = "c.name AS company, d.name AS section, s.name AS sponsor, e.labour_type, e.pay_type"

    if page == "Employees":
        manage("employees", """SELECT e.id, e.code, e.name, c.name AS company, d.name AS section, s.name AS sponsor,
            e.labour_type, e.pay_type, e.pay_mode, e.rate, e.food_allow, e.ot_rate, e.bill_rate, e.nationality,
            e.id_no, e.phone, e.join_date, e.id_expiry, e.active FROM employees e""" + EJ + "ORDER BY e.code",
               edit=["code", "name", "labour_type", "pay_type", "pay_mode", "rate", "food_allow", "ot_rate", "bill_rate",
                     "nationality", "id_no", "phone", "join_date", "id_expiry", "active"],
               fks={"company": ("company_id", "companies"), "section": ("dept_id", "departments"),
                    "sponsor": ("sponsor_id", "sponsors")},
               selects={"labour_type": ["Company", "Outside"], "pay_type": ["Monthly", "Hourly"],
                        "pay_mode": ["Bank", "Cash"], "active": [1, 0]},
               cascade=[("attendance", "emp_id"), ("leaves", "emp_id"), ("adjustments", "emp_id"), ("costs", "emp_id")],
               key="emp", flt="xemp")

    elif page == "Setup":
        t1, t2, t3 = st.tabs(["Companies", "Sections", "Sponsors / Kofil"])
        with t1:
            manage("companies", "SELECT id, name, vat FROM companies ORDER BY name", edit=["name", "vat"],
                   used_in=[("employees", "company_id"), ("attendance", "company_id"), ("costs", "company_id")], key="mco")
        with t2:
            manage("departments", "SELECT id, name FROM departments ORDER BY name", edit=["name"],
                   used_in=[("employees", "dept_id"), ("attendance", "dept_id")], key="mse")
        with t3:
            manage("sponsors", "SELECT id, name, phone FROM sponsors ORDER BY name", edit=["name", "phone"],
                   used_in=[("employees", "sponsor_id")], key="msp")

    elif page == "Attendance":
        cc = st.columns(7)
        a1, a2 = dr("mat", cc[:2])
        manage("attendance", """SELECT a.id, a.day, e.code, e.name AS employee, c.name AS company, d.name AS section,
            s.name AS sponsor, e.labour_type, e.pay_type, a.status, a.hours, a.ot_hours FROM attendance a
            JOIN employees e ON e.id=a.emp_id LEFT JOIN companies c ON c.id=COALESCE(a.company_id,e.company_id)
            LEFT JOIN departments d ON d.id=COALESCE(a.dept_id,e.dept_id) LEFT JOIN sponsors s ON s.id=e.sponsor_id
            WHERE a.day BETWEEN ? AND ? ORDER BY a.day DESC, e.code""", (a1, a2),
               edit=["status", "hours", "ot_hours"], selects={"status": ["Present", "Absent", "Leave", "Off"]},
               key="att", flt="xatt", cols=cc[2:])

    elif page == "Leave":
        cc = st.columns(7)
        a1, a2 = dr("mlv", cc[:2])
        manage("leaves", "SELECT l.id, l.emp_id, e.code, e.name AS employee, " + EC + ", l.ltype, l.start, l.end, l.days, "
               "l.status FROM leaves l JOIN employees e ON e.id=l.emp_id" + EJ +
               "WHERE l.start<=? AND l.end>=? ORDER BY l.start DESC", (a2, a1),
               edit=["ltype", "start", "end"], hide=("emp_id",),
               selects={"ltype": ["Annual", "Sick", "Emergency", "Unpaid", "Other"]},
               after_upd=lv_sync, before_del=lv_clear, key="lv", flt="xlv", cols=cc[2:])

    elif page == "Adjustments":
        cc = st.columns(7)
        a1, a2 = dr("mad", cc[:2])
        manage("adjustments", "SELECT a.id, a.day, e.code, e.name AS employee, " + EC + ", a.kind, a.amount, a.note "
               "FROM adjustments a JOIN employees e ON e.id=a.emp_id" + EJ +
               "WHERE a.day BETWEEN ? AND ? ORDER BY a.day DESC", (a1, a2),
               edit=["day", "kind", "amount", "note"],
               selects={"kind": ["Advance", "Deduction", "Bonus", "Allowance", "Supervisor/Operator", "Foundation Day",
                                 "Skill/Villa", "Extra", "Eid Bonus"]}, key="adj", flt="xadj", cols=cc[2:])

    elif page == "Costs":
        cc = st.columns(7)
        a1, a2 = dr("mco", cc[:2])
        manage("costs", """SELECT x.id, x.day, x.category, e.code, c.name AS company, d.name AS section, s.name AS sponsor,
            e.labour_type, e.pay_type, x.amount, x.note FROM costs x LEFT JOIN employees e ON e.id=x.emp_id
            LEFT JOIN companies c ON c.id=x.company_id LEFT JOIN departments d ON d.id=e.dept_id
            LEFT JOIN sponsors s ON s.id=e.sponsor_id WHERE x.day BETWEEN ? AND ? ORDER BY x.day DESC""", (a1, a2),
               edit=["day", "category", "amount", "note"], fks={"company": ("company_id", "companies")},
               selects={"category": ["ID / Iqama (Juazat)", "Work permit", "Insurance", "Transfer", "Muqeem / Monduf fee",
                                     "Exit re-entry", "Passport", "Medical", "Vacation ticket", "GOSI", "Other"]},
               key="cst", flt="xcost", cols=cc[2:])

    elif page == "Users":
        manage("users", "SELECT id, username, role FROM users ORDER BY username", edit=["username", "role"],
               selects={"role": ["Admin", "HR", "Manager"]},
               guard=lambda r: "You cannot delete the user you are logged in as"
               if r["username"] == st.session_state.user else None, key="usr")
