# app.py
from datetime import datetime, date, time, timedelta
import uuid, os, re, hashlib, binascii
import pandas as pd
import streamlit as st
import gspread
import altair as alt
from gspread_dataframe import get_as_dataframe, set_with_dataframe
import secrets as pysecrets
import json

# --------------------------
# Felső vonal eltüntetése (Streamlit header)
# --------------------------
st.markdown("""
<style>
[data-testid="stHeader"]{background:none; height:0px;}
</style>
""", unsafe_allow_html=True)

# --------------------------
# Alap / theme
# --------------------------
st.set_page_config(page_title="🐴 Lovarda Időpontfoglaló", layout="wide")
st.markdown("""
<style>
:root {
  --bg:#121212; --fg:#e0e0e0; --panel:#1c1c1c; --border:#333;
  --ok:#1b5e20; --ok2:#2e7d32; --danger:#7f1d1d; --danger2:#991b1b; --muted:#aaa;
}
.stApp, body { background:var(--bg)!important; color:var(--fg)!important; }
.block-container { padding-top:1rem; padding-bottom:3rem; }
.stSidebar { background:#181818!important; }
.stButton>button, .stTextInput input, .stDateInput input, .stNumberInput input, .stTimeInput input, .stSelectbox div div {
  background:#1e1e1e!important; color:var(--fg)!important; border:1px solid var(--border)!important;
}
div.stButton:has(button:contains("Foglal")) > button { background:var(--ok)!important; border:1px solid #245a2f!important; }
div.stButton:has(button:contains("Foglal")) > button:hover { background:var(--ok2)!important; }
div.stButton:has(button:contains("Lemond")) > button,
div.stButton:has(button:contains("❌")) > button { background:var(--danger)!important; border:1px solid #5f1414!important; }
div.stButton:has(button:contains("Lemond")) > button:hover,
div.stButton:has(button:contains("❌")) > button:hover { background:var(--danger2)!important; }
.metric { padding:.6rem .8rem; background:#1b1b1b; border:1px solid #2a2a2a; border-radius:.5rem; }
.center-card { max-width:560px; margin: 10vh auto; padding: 1.5rem; background:#1b1b1b; border:1px solid #2a2a2a; border-radius:.6rem; text-align:center;}
</style>
""", unsafe_allow_html=True)

# --------------------------
# Secrets / config
# --------------------------
SECRETS = st.secrets
GOOGLE_SHEET_ID = SECRETS.get("google_sheet_id", "")
ADMIN_PW = SECRETS.get("admin_password", "")
GCP_SA = dict(SECRETS.get("gcp_service_account", {}))

START_TIME = time(9,0)
END_TIME   = time(20,30)
DEFAULT_BREAK_MIN   = 10
DEFAULT_LUNCH_START = time(12,0)
DEFAULT_LUNCH_DUR   = 45

# Árazás (Ft)
PRICE_30 = 3000
PRICE_60 = 5000

def price_for_minutes(minutes: int) -> int:
    m = int(minutes)
    if m <= 30: return PRICE_30
    if m == 60: return PRICE_60
    if m == 90: return PRICE_60 + PRICE_30  # ha régi adat lenne
    # fallback – arányos becslés
    if m < 60:  return round((m/30) * PRICE_30)
    return round((m/60) * PRICE_60)

# --------------------------
# Név-kezelő és létszám segédek
# --------------------------
def split_by_commas(s: str) -> list[str]:
    """Vesszővel elválasztott nevek -> tiszta lista (üres darabok kidobva)."""
    if s is None:
        return []
    return [p.strip() for p in str(s).split(",") if str(p).strip()]

def count_people(s: str) -> int:
    """Hány név van, vesszők alapján?"""
    return len(split_by_commas(s))

def explode_bookings_commas(df: pd.DataFrame) -> pd.DataFrame:
    """Foglalások szétbontása úgy, hogy minden lovas külön sor legyen."""
    if df.empty:
        return df.copy()
    tmp = df.copy()
    tmp["__list"] = tmp["Gyermek(ek) neve"].apply(split_by_commas)
    tmp = tmp.explode("__list").rename(columns={"__list": "Rider"})
    tmp["Rider"] = tmp["Rider"].fillna("").astype(str)
    tmp = tmp[tmp["Rider"] != ""]
    return tmp

# --------------------------
# Helpers – password hash
# --------------------------
def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 100_000)
    return "pbkdf2$" + binascii.hexlify(salt).decode() + "$" + binascii.hexlify(dk).decode()

def check_password(plain: str, stored: str) -> bool:
    try:
        if stored.startswith("pbkdf2$"):
            _, salt_hex, hash_hex = stored.split("$", 2)
            salt = binascii.unhexlify(salt_hex.encode())
            expected = binascii.unhexlify(hash_hex.encode())
            dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 100_000)
            return pysecrets.compare_digest(dk, expected)
        return plain == stored
    except Exception:
        return False

def _to_time_safe(val):
    if isinstance(val, time): return val
    s = str(val).strip()
    for fmt in ("%H:%M","%H:%M:%S"):
        try: return datetime.strptime(s, fmt).time()
        except: pass
    try: return pd.to_datetime(s).time()
    except: return time(9,0)

# --------------------------
# Router segéd – "Kész" oldal
# --------------------------
def goto_done(message: str):
    st.query_params["page"] = "done"
    st.query_params["msg"]  = message
    st.rerun()

def show_done_page():
    msg = st.query_params.get("msg", "Művelet kész.")
    st.markdown(f"<div class='center-card'><h3>{msg}</h3><p class='muted'>Az adatok frissültek.</p></div>", unsafe_allow_html=True)
    if st.button("Vissza az alkalmazásba"):
        st.query_params.clear()
        st.rerun()

# --------------------------
# Google Sheets
# --------------------------
@st.cache_resource
def get_gspread_client():
    # Elsődlegesen a st.secrets-ben kapott service account-ot használjuk
    if GCP_SA:
        return gspread.service_account_from_dict(GCP_SA)
    # Fallback: JSON fájlból (ha valamiért így futtatod)
    with open("mystic-fountain-300911-9b2c042063fa.json", "r") as f:
        creds = json.load(f)
    return gspread.service_account_from_dict(creds)

@st.cache_data(ttl=60)
def load_bookings_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try: ws = sh.worksheet("Foglalások")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("Foglalások", rows=2000, cols=10)
        ws.append_row(["Dátum","Gyermek(ek) neve","Lovak","Kezdés","Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if "Dátum" in df.columns and len(df): df["Dátum"]=pd.to_datetime(df["Dátum"]).dt.date
    if "Ismétlődik" in df.columns: df["Ismétlődik"]=df["Ismétlődik"].astype(str).str.lower().isin(["true","1","igen","y","yes"])
    # Fő normalizálása
    if "Fő" not in df.columns:
        df["Fő"] = 1
    df["Fő"] = pd.to_numeric(df["Fő"], errors="coerce").fillna(1).astype(int)
    return df

@st.cache_data(ttl=60)
def load_users_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try: ws = sh.worksheet("Felhasználók")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("Felhasználók", rows=200, cols=3)
        ws.append_row(["username","password","role"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    for c in ["username","password","role"]:
        if c not in df.columns: df[c] = ""
    return df[["username","password","role"]]

@st.cache_data(ttl=60)
def load_blocked_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try: ws = sh.worksheet("TiltottNapok")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("TiltottNapok", rows=400, cols=1); ws.append_row(["Dátum"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if "Dátum" in df.columns and len(df): df["Dátum"]=pd.to_datetime(df["Dátum"]).dt.date
    return df

@st.cache_data(ttl=300)
def load_settings_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try: ws = sh.worksheet("Beallitasok")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("Beallitasok", rows=20, cols=2)
        ws.append_rows([
            ["lunch_start","12:00"],["lunch_dur","45"],["break_min","10"],
            ["july_allowed_weekdays","0,1"],["august_allowed_weekdays","1,2,3,4,5,6"]
        ])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    df.columns = ["Key","Value"]; return df

@st.cache_data(ttl=60)
def load_lunch_overrides_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try: ws = sh.worksheet("EbédSzunet")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("EbédSzunet", rows=200, cols=3)
        ws.append_row(["Dátum","Kezdes","HosszPerc"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if not df.empty:
        df["Dátum"]=pd.to_datetime(df["Dátum"]).dt.date
        df["Kezdes"]=pd.to_datetime(df["Kezdes"]).dt.time
        df["HosszPerc"]=df["HosszPerc"].astype(int)
    return df

@st.cache_data(ttl=60)
def load_events_df():
    """Foglalás/lemondás/áthelyezés események naplója."""
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try: ws = sh.worksheet("Események")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("Események", rows=2000, cols=12)
        ws.append_row(["Idő","Típus","Felhasználó","Dátum","Kezdés","Időtartam (perc)","Nevek","Megjegyzés","RepeatGroupID","Admin?"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    # normalizálás
    if "Idő" in df.columns and len(df):
        try: df["Idő"] = pd.to_datetime(df["Idő"])
        except: pass
    return df

def save_df_to_sheet(df: pd.DataFrame, sheet: str):
    ws = get_gspread_client().open_by_key(GOOGLE_SHEET_ID).worksheet(sheet)
    ws.clear(); set_with_dataframe(ws, df, include_index=False)
    st.cache_data.clear()

def save_settings_df(df: pd.DataFrame): save_df_to_sheet(df, "Beallitasok")

def log_event(ev_type: str, user: str, d: date=None, start=None, dur=None, names:str="", note:str="", rg:str="", is_admin:bool=False):
    df = load_events_df()
    row = {
        "Idő": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Típus": ev_type,
        "Felhasználó": user or "",
        "Dátum": d.strftime("%Y-%m-%d") if d else "",
        "Kezdés": start.strftime("%H:%M") if isinstance(start, time) else (str(start) if start else ""),
        "Időtartam (perc)": int(dur) if dur else "",
        "Nevek": names or "",
        "Megjegyzés": note or "",
        "RepeatGroupID": rg or "",
        "Admin?": "igen" if is_admin else "nem",
    }
    new_df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_df_to_sheet(new_df, "Események")

# --------------------------
# ICS (TZID)
# --------------------------
def generate_ics(df: pd.DataFrame):
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Lovarda Foglaló//EN"]
    for _,r in df.iterrows():
        try:
            tm = _to_time_safe(r["Kezdés"])
            dtstart = datetime.combine(r["Dátum"], tm)
        except Exception: continue
        dtend = dtstart + timedelta(minutes=int(r["Időtartam (perc)"]))
        uid = uuid.uuid4()
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
            f"DTSTART;TZID=Europe/Budapest:{dtstart:%Y%m%dT%H%M%S}",
            f"DTEND;TZID=Europe/Budapest:{dtend:%Y%m%dT%H%M%S}",
            f"SUMMARY:Lovarda foglalás ({r['Gyermek(ek) neve']})",
            "END:VEVENT"
        ]
    lines.append("END:VCALENDAR"); return "\r\n".join(lines)

# --------------------------
# Session init
# --------------------------
raw = load_settings_df().set_index("Key")["Value"].to_dict()
st.session_state.setdefault("lunch_start", datetime.strptime(raw.get("lunch_start","12:00"), "%H:%M").time())
st.session_state.setdefault("lunch_dur",   int(raw.get("lunch_dur",   DEFAULT_LUNCH_DUR)))
st.session_state.setdefault("break_min",   int(raw.get("break_min",   DEFAULT_BREAK_MIN)))
for k in ("role","auth","user"): st.session_state.setdefault(k, None)
JUL_ALLOWED = set(int(x) for x in raw.get("july_allowed_weekdays","0,1").split(",") if str(x).strip().isdigit())
AUG_ALLOWED = set(int(x) for x in raw.get("august_allowed_weekdays","1,2,3,4,5,6").split(",") if str(x).strip().isdigit())

# --------------------------
# Router: "done" oldal kezelése
# --------------------------
if st.query_params.get("page") == "done":
    show_done_page()
    st.stop()

# --------------------------
# UI: szerep + login (form)
# --------------------------
st.title("🐴 Lovarda Időpontfoglaló")

if st.session_state.role is None:
    # kicsit látványosabb role selector
    c = st.columns(2)
    with c[0]:
        st.markdown("#### Lovas")
        if st.button("🏇 Belépés lovasként", use_container_width=True):
            st.session_state.role="rider"
    with c[1]:
        st.markdown("#### Admin")
        if st.button("🛠️ Belépés adminként", use_container_width=True):
            st.session_state.role="admin"
    if st.session_state.role is None: st.stop()

def _rider_login_submit():
    dfu=load_users_df(); u=st.session_state.get("u_rider","").strip(); p=st.session_state.get("p_rider","")
    row=dfu[dfu["username"]==u]; ok=False
    if not row.empty: ok = check_password(p, str(row.iloc[0]["password"]))
    if ok: st.session_state.update(auth=True,user=u,role="rider"); st.session_state.pop("login_error",None)
    else: st.session_state["login_error"]="Hibás belépés."

def _admin_login_submit():
    if st.session_state.get("p_admin","")==ADMIN_PW and ADMIN_PW:
        st.session_state.update(auth=True,role="admin"); st.session_state.pop("login_error",None)
    else: st.session_state["login_error"]="Hibás jelszó."

if not st.session_state.auth:
    if st.session_state.role=="rider":
        st.subheader("Lovas bejelentkezés")
        with st.form("rider_login"): 
            st.text_input("Felhasználónév", key="u_rider")
            st.text_input("Jelszó", type="password", key="p_rider")
            st.form_submit_button("Bejelentkezés", on_click=_rider_login_submit)
    else:
        st.subheader("Admin bejelentkezés")
        with st.form("admin_login"):
            st.text_input("Jelszó", type="password", key="p_admin")
            st.form_submit_button("Bejelentkezés", on_click=_admin_login_submit)
    if st.session_state.get("login_error"): st.error(st.session_state["login_error"])
    st.stop()

# --------------------------
# Dátum + tiltott napok
# --------------------------
sel_date = st.date_input("Dátum kiválasztása", value=date.today())
wd, mo = sel_date.weekday(), sel_date.month
if mo==7 and wd not in JUL_ALLOWED: st.warning("Júliusban csak engedélyezett napokon lehet foglalni."); st.stop()
elif mo==8 and wd not in AUG_ALLOWED: st.warning("Augusztusban csak engedélyezett napokon lehet foglalni."); st.stop()

blocked = load_blocked_df()
if st.session_state.role=="rider" and ("Dátum" in blocked.columns) and (sel_date in blocked["Dátum"].tolist()):
    st.warning("❌ Ezen a napon nem lehet foglalni."); st.stop()

bookings_df   = load_bookings_df()
lunch_over_df = load_lunch_overrides_df()

# --------------------------
# Slot generálás
# --------------------------
def get_free_slots(sel_date: date, duration: int):
    slots=[]; cur=datetime.combine(sel_date, START_TIME)
    odf=lunch_over_df[lunch_over_df["Dátum"]==sel_date]
    if not odf.empty: ls,ld = odf.iloc[0]["Kezdes"], int(odf.iloc[0]["HosszPerc"])
    else: ls,ld = st.session_state["lunch_start"], int(st.session_state["lunch_dur"])
    lunch_s=datetime.combine(sel_date, ls); lunch_e=lunch_s+timedelta(minutes=ld)
    break_min=int(st.session_state["break_min"])
    today=bookings_df[bookings_df["Dátum"]==sel_date].copy()
    last_start=datetime.combine(sel_date, END_TIME)-timedelta(minutes=duration)
    busy=[]
    for _,r in today.iterrows():
        bs=datetime.combine(sel_date, _to_time_safe(r["Kezdés"]))
        be=bs+timedelta(minutes=int(r["Időtartam (perc)"])); busy.append((bs,be))
    def conflict(s,e): return any(s<be and bs<e for bs,be in busy)
    while cur<=last_start:
        end=cur+timedelta(minutes=duration)
        if cur<lunch_e and end>lunch_s: cur=max(lunch_e,cur); continue
        if not conflict(cur,end):
            slots.append((cur.time(), end.time())); cur=end+timedelta(minutes=break_min)
        else:
            next_cur=cur+timedelta(minutes=5)
            for bs,be in busy:
                if cur<be and bs<end: next_cur=max(next_cur,be)
            cur=next_cur
    return slots

# --------------------------
# Rider nézet
# --------------------------
if st.session_state.role=="rider":
    st.subheader(f"Üdv, {st.session_state.user}!")
    tab_new, tab_mine = st.tabs(["🆕 Új foglalás", "📂 Saját foglalások"])

    with tab_new:
        names = st.text_input("Gyermek(ek) neve(i), vesszővel elválasztva", value=st.session_state.user)
        st.caption("Tipp: több nevet VESSZŐVEL válassz el: pl. \"Kiss Ádám, Nagy Feri\".")
        # csak 30 vagy 60 perc
        dur = st.selectbox("Időtartam (perc)", [30,60], index=1)
        c1,c2 = st.columns(2)
        with c1: weekly = st.checkbox("Heti ismétlés", value=False)
        with c2: repeat_until = st.date_input("Ismétlés vége", value=sel_date+timedelta(days=180), disabled=not weekly)

        free = get_free_slots(sel_date, int(dur))
        if not free: st.info("Nincs szabad időpont erre a napra.")
        else:
            st.write("**Szabad idősávok:**")
            for i,(s,e) in enumerate(free):
                colA,colB = st.columns(2)
                label=f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
                if colA.button(f"Foglal {label}", key=f"book_{i}"):
                    if not weekly:
                        new = {"Dátum":sel_date,"Gyermek(ek) neve":names.strip(),"Lovak":"",
                               "Kezdés":s.strftime("%H:%M"),"Időtartam (perc)":int(dur),
                               "Fő": max(1, count_people(names)),
                               "Ismétlődik":False,"RepeatGroupID":"","Megjegyzés":""}
                        new_df = pd.concat([bookings_df, pd.DataFrame([new])], ignore_index=True)
                        save_df_to_sheet(new_df, "Foglalások")
                        log_event("foglalás", st.session_state.user, sel_date, s, int(dur), names.strip(), "", "", False)
                        goto_done("Foglalás sikeres!")
                    else:
                        group_id=f"rep_{uuid.uuid4()}"
                        future=pd.date_range(start=sel_date, end=repeat_until, freq='7D').date
                        blocked_days=set(blocked["Dátum"].tolist()) if "Dátum" in blocked.columns else set()
                        entries,conflicts=[],[]
                        for d in future:
                            if d in blocked_days: continue
                            if ((bookings_df["Dátum"]==d)&(bookings_df["Kezdés"]==s.strftime("%H:%M"))).any():
                                conflicts.append(d); continue
                            entries.append({"Dátum":d,"Gyermek(ek) neve":names.strip(),"Lovak":"",
                                            "Kezdés":s.strftime("%H:%M"),"Időtartam (perc)":int(dur),
                                            "Fő": max(1, count_people(names)),
                                            "Ismétlődik":True,"RepeatGroupID":group_id,"Megjegyzés":"heti ismétlés"})
                        if conflicts: st.warning("Ütköző napok kihagyva: "+", ".join(map(str,conflicts)))
                        if entries:
                            new_df=pd.concat([bookings_df,pd.DataFrame(entries)], ignore_index=True)
                            save_df_to_sheet(new_df,"Foglalások")
                            log_event("sorozat_foglalás", st.session_state.user, sel_date, s, int(dur), names.strip(), f"{len(entries)} alkalom", group_id, False)
                            goto_done("Ismétlődő foglalás létrehozva.")
                        else:
                            st.info("Nem volt hozzáadható időpont az ismétléshez.")

    with tab_mine:
        mask = bookings_df.get("Gyermek(ek) neve","").astype(str).str.contains(st.session_state.user, case=False, na=False)
        my_df = bookings_df[mask].copy().sort_values(["Dátum","Kezdés"])
        st.markdown("### Saját foglalásaim")
        if my_df.empty: st.info("Még nincsenek foglalásaid.")
        else:
            c1,c2,c3 = st.columns(3)
            with c1: from_d = st.date_input("Dátum -tól", value=date.today())
            with c2: to_d   = st.date_input("Dátum -ig",  value=date.today()+timedelta(days=60))
            with c3: time_start = st.time_input("Napszak -tól", value=time(0,0))
            my_df = my_df[(my_df["Dátum"]>=from_d)&(my_df["Dátum"]<=to_d)]
            my_df["Kezdés_time"]=my_df["Kezdés"].apply(_to_time_safe)
            my_df = my_df[my_df["Kezdés_time"]>=time_start]
            st.dataframe(my_df[["Dátum","Kezdés","Időtartam (perc)","Gyermek(ek) neve","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"]],
                         use_container_width=True)

            st.markdown("---")
            st.write("**Foglalás lemondása (egyedi)**")
            col1,col2,col3 = st.columns([1,1,2])
            with col1: sel_idx = st.selectbox("Válassz (index)", options=list(my_df.index))
            with col3: reason = st.text_input("Indok (opcionális)", value="")
            with col2:
                if st.button("Lemondás"):
                    row=bookings_df.loc[sel_idx]; dt=row["Dátum"]; tm=_to_time_safe(row["Kezdés"])
                    if datetime.combine(dt, tm) < datetime.now(): st.error("Múltbeli foglalás nem mondható le.")
                    else:
                        log_event("lemondás", st.session_state.user, dt, tm, int(row["Időtartam (perc)"]), str(row["Gyermek(ek) neve"]), reason, str(row.get("RepeatGroupID","")), False)
                        new_df=bookings_df.drop(index=sel_idx)
                        save_df_to_sheet(new_df,"Foglalások")
                        goto_done("Foglalás lemondva.")

            st.markdown("### Ismétlődő foglalások kezelése (nyaralás/szünet)")
            rep_df = my_df[my_df["Ismétlődik"]==True].copy()
            if rep_df.empty: st.info("Nincs ismétlődő foglalásod.")
            else:
                groups = sorted([g for g in rep_df["RepeatGroupID"].unique() if g])
                gsel = st.selectbox("Válassz sorozatot (RepeatGroupID)", options=groups)
                gdata = rep_df[rep_df["RepeatGroupID"]==gsel].sort_values(["Dátum","Kezdés"])
                st.dataframe(gdata[["Dátum","Kezdés","Időtartam (perc)","Megjegyzés"]], use_container_width=True)

                opt_dates = gdata["Dátum"].tolist()
                csk1,csk2 = st.columns([2,1])
                with csk1: skip_date = st.selectbox("Alkalom kihagyása (csak egy nap szabadul fel)", options=opt_dates, format_func=str)
                with csk2:
                    if st.button("Kihagyás ezen a napon"):
                        to_drop = bookings_df[(bookings_df["RepeatGroupID"]==gsel)&(bookings_df["Dátum"]==skip_date)]
                        if not to_drop.empty:
                            row = to_drop.iloc[0]
                            log_event("sorozat_alkalom_kihagyás", st.session_state.user, skip_date, _to_time_safe(row["Kezdés"]), int(row["Időtartam (perc)"]), str(row["Gyermek(ek) neve"]), "nyaralás/egyedi kihagyás", gsel, False)
                            new_df = bookings_df.drop(index=to_drop.index)
                            save_df_to_sheet(new_df,"Foglalások")
                            goto_done(f"{skip_date} kihagyva a sorozatból.")
                        else: st.info("Nem találtam ilyen előfordulást.")

                csk3,csk4,csk5 = st.columns([2,1,1])
                with csk3: start_skip = st.date_input("Szünet kezdete", value=date.today())
                with csk4: weeks = st.number_input("Hány hét", 1, 12, 2)
                with csk5:
                    if st.button("Sorozat szüneteltetése"):
                        end_skip = start_skip + timedelta(days=7*weeks)
                        to_drop = bookings_df[(bookings_df["RepeatGroupID"]==gsel)&(bookings_df["Dátum"]>=start_skip)&(bookings_df["Dátum"]<end_skip)]
                        if not to_drop.empty:
                            log_event("sorozat_szünet", st.session_state.user, start_skip, None, None, "", f"{weeks} hét", gsel, False)
                            new_df=bookings_df.drop(index=to_drop.index)
                            save_df_to_sheet(new_df,"Foglalások")
                            goto_done(f"Szünet beállítva {start_skip} – {end_skip - timedelta(days=1)} között.")
                        else: st.info("Erre az időszakra nincs előfordulás.")

        mine = bookings_df[mask]
        if not mine.empty:
            st.download_button("ICS export (saját)", data=generate_ics(mine), file_name="sajat_foglalasok.ics", mime="text/calendar")

    st.markdown("---")
    if st.button("Kijelentkezés"): st.session_state.clear(); st.rerun()
    st.stop()

# --------------------------
# Admin nézet
# --------------------------
st.subheader("🛠️ Admin felület")
menu = st.radio("Menü", ["Foglalások","Áttekintés (heti)","Események","Felhasználók","Statisztika","Beállítások","Naptár"], horizontal=True)

def day_capacity_minutes(d: date) -> int:
    start_dt=datetime.combine(d, START_TIME); end_dt=datetime.combine(d, END_TIME)
    total=int((end_dt-start_dt).total_seconds()//60)
    odf=lunch_over_df[lunch_over_df["Dátum"]==d]
    ld=int(odf.iloc[0]["HosszPerc"]) if not odf.empty else int(st.session_state["lunch_dur"])
    return max(total-ld,0)

def bookings_minutes_on(d: date) -> int:
    df=bookings_df[bookings_df["Dátum"]==d]
    return int(df["Időtartam (perc)"].astype(int).sum()) if not df.empty else 0

def bookings_revenue_on(d: date) -> int:
    df = bookings_df[bookings_df["Dátum"]==d]
    if df.empty: return 0
    per_head = df["Időtartam (perc)"].astype(int).apply(price_for_minutes)
    heads = pd.to_numeric(df.get("Fő", 1), errors="coerce").fillna(1).astype(int)
    return int((per_head * heads).sum())

if menu=="Foglalások":
    st.markdown("### Heti foglalások (kezelés)")
    wn=sel_date.isocalendar()[1]
    wdf=bookings_df[bookings_df["Dátum"].apply(lambda d:d.isocalendar()[1])==wn].sort_values(["Dátum","Kezdés"])
    if wdf.empty: st.info("Nincs foglalás ezen a héten.")
    else:
        for idx,r in wdf.iterrows():
            st.write(f"**{r['Dátum']} {r['Kezdés']}** – {r['Gyermek(ek) neve']} ({r['Időtartam (perc)']}p, Fő: {r.get('Fő',1)}) | RG: {r.get('RepeatGroupID','')}")
            c1,c2,c3 = st.columns(3)

            if c1.button("❌ Törlés", key=f"del{idx}"):
                log_event("admin_törlés", "admin", r["Dátum"], _to_time_safe(r["Kezdés"]), int(r["Időtartam (perc)"]), str(r["Gyermek(ek) neve"]), "", str(r.get("RepeatGroupID","")), True)
                new_df=bookings_df.drop(idx); save_df_to_sheet(new_df,"Foglalások"); st.rerun()

            if st.session_state.get("edit_idx")!=idx:
                if c2.button("↻ Szerkeszt", key=f"mv{idx}"):
                    st.session_state["edit_idx"]=idx
                    st.session_state["new_time"]=_to_time_safe(r["Kezdés"])
                    st.session_state["new_names"]=str(r["Gyermek(ek) neve"])
                    st.session_state["new_dur"]=int(r["Időtartam (perc)"])
                    st.rerun()
            else:
                nt   = c2.time_input("Új kezdés", value=_to_time_safe(st.session_state.get("new_time", r["Kezdés"])), key=f"time{idx}")
                ndur = c2.number_input("Időtartam (perc)", min_value=5, max_value=240, step=5, value=int(st.session_state.get("new_dur", r["Időtartam (perc)"])), key=f"dur{idx}")
                nms  = c3.text_input("Gyermek(ek) neve (vesszőkkel)", value=st.session_state.get("new_names", str(r["Gyermek(ek) neve"])), key=f"names{idx}")

                save_col, cancel_col = st.columns(2)
                if save_col.button("Mentés", key=f"save{idx}"):
                    bookings_df.at[idx,"Kezdés"]=nt.strftime("%H:%M")
                    bookings_df.at[idx,"Időtartam (perc)"]=int(ndur)
                    bookings_df.at[idx,"Gyermek(ek) neve"]=nms.strip()
                    bookings_df.at[idx,"Fő"]=max(1, count_people(nms))
                    save_df_to_sheet(bookings_df,"Foglalások")
                    log_event("admin_módosítás", "admin", r["Dátum"], nt, int(ndur), nms.strip(), "", str(r.get("RepeatGroupID","")), True)
                    st.session_state.pop("edit_idx",None); st.rerun()

                if cancel_col.button("Mégse", key=f"cancel{idx}"):
                    st.session_state.pop("edit_idx",None); st.rerun()

            rg = r.get("RepeatGroupID","")
            if rg and c3.button("↺ Stop ismétlés", key=f"stop{idx}"):
                new_df = bookings_df[~((bookings_df["RepeatGroupID"]==rg)&(bookings_df["Dátum"]>=sel_date))]
                save_df_to_sheet(new_df,"Foglalások")
                log_event("admin_stop_sorozat", "admin", sel_date, None, None, "", "", rg, True)
                st.success("Ismétlés leállítva innen!"); st.rerun()

    # napi bevétel táblázat a hétre
    wk_days = [sel_date + timedelta(days=i) for i in range(7)]
    rev_rows = [{"Dátum":d, "Bevétel (Ft)": bookings_revenue_on(d)} for d in wk_days]
    rev_df = pd.DataFrame(rev_rows)
    st.markdown("#### Napi bevétel (kijelölt hét)")
    st.dataframe(rev_df, use_container_width=True)
    st.info(f"**Heti bevétel összesen:** {int(rev_df['Bevétel (Ft)'].sum()):,} Ft".replace(",", " "))

    st.download_button("ICS export (összes)", data=generate_ics(bookings_df), file_name="osszes_foglalas.ics", mime="text/calendar")

elif menu=="Áttekintés (heti)":
    st.markdown("### Heti áttekintő — telítettség, bevétel, rács, top lovasok")
    week_num=sel_date.isocalendar()[1]
    week_df=bookings_df[bookings_df["Dátum"].apply(lambda d:d.isocalendar()[1])==week_num].copy()
    week_ex = explode_bookings_commas(week_df)

    wk_days = [sel_date + timedelta(days=i) for i in range(7)]
    daily_rev = pd.DataFrame({
        "Dátum": wk_days,
        "Bevétel (Ft)": [bookings_revenue_on(d) for d in wk_days],
        "Perc (össz.)": [bookings_minutes_on(d) for d in wk_days],
        "Kapacitás (perc)": [day_capacity_minutes(d) for d in wk_days],
    })

    c1,c2,c3,c4 = st.columns(4)
    total_bookings=len(week_df)
    total_minutes=int(week_df["Időtartam (perc)"].astype(int).sum()) if not week_df.empty else 0
    total_revenue=int(daily_rev["Bevétel (Ft)"].sum())
    unique_riders=week_ex["Rider"].nunique() if not week_ex.empty else 0
    with c1: st.markdown(f"<div class='metric'><b>Foglalások (hét)</b><br>{total_bookings}</div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='metric'><b>Össz. perc</b><br>{total_minutes} p</div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='metric'><b>Heti bevétel</b><br>{total_revenue:,} Ft</div>".replace(",", " "), unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='metric'><b>Egyedi lovasok</b><br>{unique_riders}</div>", unsafe_allow_html=True)

    st.markdown("#### Napi telítettség és bevétel")
    st.dataframe(daily_rev, use_container_width=True)
    if not daily_rev.empty:
        ch = alt.Chart(daily_rev).mark_bar().encode(x='Dátum:T', y='Bevétel (Ft):Q', tooltip=['Dátum:T','Bevétel (Ft):Q'])
        st.altair_chart(ch, use_container_width=True)

    st.markdown("#### Heti naptár (rács)")
    if not week_df.empty:
        timeline=week_df.copy()
        timeline["start"] = pd.to_datetime(timeline["Dátum"].astype(str) + " " + timeline["Kezdés"].astype(str), errors="coerce")
        timeline["Időtartam (perc)"] = pd.to_numeric(timeline["Időtartam (perc)"], errors="coerce").fillna(0).astype(int)
        timeline["end"] = timeline["start"] + pd.to_timedelta(timeline["Időtartam (perc)"], unit="m")
        timeline["Nap"]=timeline["Dátum"].astype(str)

        ch=(alt.Chart(timeline.dropna(subset=["start", "end"]))
                .mark_bar()
                .encode(
                    y=alt.Y('Nap:N', sort=sorted(timeline["Nap"].unique())),
                    x='start:T', x2='end:T',
                    color=alt.Color('Gyermek(ek) neve:N', legend=None),
                    tooltip=['Gyermek(ek) neve','Nap','start:T','end:T']
                ).properties(height=220))
        st.altair_chart(ch, use_container_width=True)

        grid = (timeline.dropna(subset=["start"])
                .sort_values(["Nap","start"])[["Nap","Kezdés","Gyermek(ek) neve"]]
                .pivot_table(index="Kezdés", columns="Nap", values="Gyermek(ek) neve", aggfunc=lambda s:", ".join(s)))
        st.dataframe(grid, use_container_width=True)
    else:
        st.info("Nincs foglalás ezen a héten.")

    st.markdown("#### Top foglalók (perc / hét)")
    if not week_ex.empty:
        top_minutes = (week_ex.groupby("Rider")["Időtartam (perc)"].sum()
                               .sort_values(ascending=False)
                               .reset_index()
                               .rename(columns={"Rider":"Lovas","Időtartam (perc)":"Perc (össz.)"}))
        top_sessions = (week_ex.groupby("Rider").size()
                               .reset_index(name="Alkalmak")
                               .sort_values("Alkalmak", ascending=False)
                               .rename(columns={"Rider":"Lovas"}))
        st.markdown("**Top lovasok – össz. perc**")
        st.dataframe(top_minutes, use_container_width=True)
        st.markdown("**Top lovasok – alkalmak száma**")
        st.dataframe(top_sessions, use_container_width=True)

elif menu=="Események":
    st.markdown("### Foglalási események (foglalás / lemondás / áthelyezés)")
    ev = load_events_df()
    if ev.empty:
        st.info("Még nincs esemény.")
    else:
        c1,c2,c3 = st.columns(3)
        with c1: d_from = st.date_input("Dátum -tól", value=date.today()-timedelta(days=30))
        with c2: d_to   = st.date_input("Dátum -ig", value=date.today()+timedelta(days=1))
        with c3: etype  = st.selectbox("Típus", ["(mind)","foglalás","sorozat_foglalás","lemondás","sorozat_alkalom_kihagyás","sorozat_szünet","admin_törlés","admin_áthelyezés","admin_stop_sorozat","admin_módosítás"])
        ev2 = ev.copy()
        try:
            ev2["Idő_dt"] = pd.to_datetime(ev2["Idő"])
        except Exception:
            ev2["Idő_dt"] = pd.to_datetime(ev2["Idő"], errors="coerce")
        ev2 = ev2[(ev2["Idő_dt"]>=pd.to_datetime(d_from)) & (ev2["Idő_dt"]<=pd.to_datetime(d_to)+pd.Timedelta(days=1))]
        if etype!="(mind)": ev2 = ev2[ev2["Típus"]==etype]
        ev2 = ev2.sort_values("Idő_dt", ascending=False)
        show_cols = ["Idő","Típus","Felhasználó","Dátum","Kezdés","Időtartam (perc)","Nevek","Megjegyzés","RepeatGroupID","Admin?"]
        st.dataframe(ev2[show_cols], use_container_width=True)

elif menu=="Felhasználók":
    dfu=load_users_df(); st.dataframe(dfu, use_container_width=True)
    st.markdown("### Új felhasználó")
    with st.form("add_user"):
        nu=st.text_input("Felhasználónév"); npw=st.text_input("Jelszó", type="password"); role=st.selectbox("Szerep", ["rider","admin"])
        if st.form_submit_button("Regisztrálás"):
            if not nu or not npw: st.error("Hiányzó adat.")
            elif (dfu["username"]==nu).any(): st.error("Már létezik ilyen felhasználó.")
            else:
                dfu=pd.concat([dfu, pd.DataFrame([{"username":nu,"password":hash_password(npw),"role":role}])], ignore_index=True)
                save_df_to_sheet(dfu,"Felhasználók"); st.success("Felhasználó hozzáadva."); st.rerun()
    if not dfu.empty:
        st.markdown("### Felhasználó törlése")
        with st.form("del_user"):
            del_user=st.selectbox("Törlendő felhasználó", options=dfu["username"].tolist())
            if st.form_submit_button("❌ Felhasználó törlése"):
                dfu=dfu[dfu["username"]!=del_user]; save_df_to_sheet(dfu,"Felhasználók"); st.success("Törölve."); st.rerun()

elif menu=="Statisztika":
    st.write("📊 Foglalások napi bontásban")
    if bookings_df.empty: st.info("Nincs adat.")
    else:
        daily = bookings_df["Dátum"].value_counts().sort_index()
        st.bar_chart(daily)

elif menu=="Beállítások":
    st.header("⚙️ Globális & napi ebédszünet & átnyergelési idő")
    df_ = bookings_df[bookings_df["Dátum"]==sel_date].copy()
    if not df_.empty:
        df_["start"]=pd.to_datetime(df_["Dátum"].astype(str)+" "+df_["Kezdés"])
        df_["end"]=df_["start"]+pd.to_timedelta(df_["Időtartam (perc)"],unit="m")
    odf=lunch_over_df[lunch_over_df["Dátum"]==sel_date]
    base_ls,base_ld=(odf.iloc[0]["Kezdes"], int(odf.iloc[0]["HosszPerc"])) if not odf.empty else (st.session_state["lunch_start"], int(st.session_state["lunch_dur"]))
    ov_ls_dt = st.slider("Napi ebédszünet kezdete", min_value=datetime.combine(sel_date,START_TIME), max_value=datetime.combine(sel_date,END_TIME), value=datetime.combine(sel_date,base_ls), format="HH:mm")
    ov_ls=ov_ls_dt.time()
    ov_ld=st.number_input("Napi ebédszünet hossza (perc)", min_value=0, max_value=180, value=int(base_ld), step=5)
    timeline = pd.DataFrame([{"type":"Ebédszünet","start":datetime.combine(sel_date,ov_ls),"end":datetime.combine(sel_date,ov_ls)+timedelta(minutes=int(ov_ld))}])
    if not df_.empty: timeline=pd.concat([df_.assign(type="Foglalás"), timeline], ignore_index=True)
    st.altair_chart(alt.Chart(timeline).mark_bar(size=20).encode(x='start:T',x2='end:T',y=alt.value(0),color='type:N',tooltip=['type','start:T','end:T']).properties(height=80), use_container_width=True)
    col1,col2 = st.columns(2)
    with col1:
        if st.button("Mentés — Napi override"):
            new_ov=lunch_over_df[lunch_over_df["Dátum"]!=sel_date]
            new_ov=pd.concat([new_ov, pd.DataFrame([{"Dátum":sel_date,"Kezdes":ov_ls,"HosszPerc":int(ov_ld)}])], ignore_index=True)
            save_df_to_sheet(new_ov,"EbédSzunet"); st.success("Mentve."); st.rerun()
    with col2:
        br=st.number_input("Átnyergelési idő (perc)", min_value=0, max_value=60, value=int(st.session_state["break_min"]), step=1)
        if st.button("Mentés — Átnyergelési idő"):
            st.session_state["break_min"]=int(br); df=load_settings_df()
            if (df["Key"]=="break_min").any(): df.loc[df["Key"]=="break_min","Value"]=str(int(br))
            else: df.loc[len(df)] = ["break_min", str(int(br))]
            save_settings_df(df); st.success("Mentve."); st.rerun()
    st.markdown("### Globális ebédszünet")
    g1,g2 = st.columns(2)
    with g1: gls=st.time_input("Alap ebédszünet kezdete", value=st.session_state["lunch_start"])
    with g2: gld=st.number_input("Alap ebédszünet hossza (perc)", 0, 180, int(st.session_state["lunch_dur"]), 5)
    if st.button("Mentés — Globális ebédszünet"):
        st.session_state["lunch_start"]=gls; st.session_state["lunch_dur"]=int(gld)
        df=load_settings_df()
        def upsert(k,v):
            if (df["Key"]==k).any(): df.loc[df["Key"]==k,"Value"]=v
            else: df.loc[len(df)] = [k,v]
        upsert("lunch_start", gls.strftime("%H:%M")); upsert("lunch_dur", str(int(gld)))
        save_settings_df(df); st.success("Mentve."); st.rerun()

elif menu=="Naptár":
    st.header("📅 Tiltott napok — egyszerű kezelés")
    bd = load_blocked_df()

    # Egy nap gyors tiltása / feloldása
    c1,c2,c3 = st.columns([2,1,1])
    with c1: one = st.date_input("Nap", value=date.today(), key="one_day")
    with c2:
        if st.button("➕ Nap tiltása"):
            new_df = pd.concat([bd, pd.DataFrame([{"Dátum":one}])], ignore_index=True)\
                       .drop_duplicates(subset=["Dátum"]).sort_values("Dátum")
            save_df_to_sheet(new_df,"TiltottNapok"); st.success(f"{one} tiltva."); st.rerun()
    with c3:
        if st.button("✔️ Nap feloldása"):
            new_df = bd[bd["Dátum"]!=one]; save_df_to_sheet(new_df,"TiltottNapok"); st.success(f"{one} feloldva."); st.rerun()

    st.markdown("---")
    # Tartomány tiltása (egy widget)
    rng = st.date_input("Tartomány (kezdő & záró nap)", value=(date.today(), date.today()))
    if isinstance(rng, tuple) and len(rng)==2:
        a,b=rng
        if st.button("📦 Tartomány tiltása"):
            if b<a: st.error("A záró nap nem lehet korábbi.")
            else:
                days = pd.date_range(a,b).date
                new_df = pd.concat([bd, pd.DataFrame({"Dátum":days})], ignore_index=True)\
                           .drop_duplicates(subset=["Dátum"]).sort_values("Dátum")
                save_df_to_sheet(new_df,"TiltottNapok"); st.success(f"Tiltva: {a} – {b}."); st.rerun()

    st.markdown("---")
    # Tömeges kijelölés (következő 90 nap)
    st.markdown("**Több nap kijelölése (következő 90 nap)**")
    future_days = list(pd.date_range(date.today(), date.today()+timedelta(days=90)).date)
    multi = st.multiselect("Napok", options=future_days, format_func=lambda d:d.strftime("%Y-%m-%d"))
    c4,c5 = st.columns(2)
    with c4:
        if st.button("➕ Kijelöltek tiltása"):
            if not multi: st.info("Nem választottál napot.")
            else:
                new_df = pd.concat([bd, pd.DataFrame({"Dátum":multi})], ignore_index=True)\
                           .drop_duplicates(subset=["Dátum"]).sort_values("Dátum")
                save_df_to_sheet(new_df,"TiltottNapok"); st.success(f"{len(multi)} nap tiltva."); st.rerun()
    with c5:
        if st.button("✔️ Kijelöltek feloldása"):
            if not multi: st.info("Nem választottál napot.")
            else:
                new_df = bd[~bd["Dátum"].isin(multi)]
                save_df_to_sheet(new_df,"TiltottNapok"); st.success(f"{len(multi)} nap feloldva."); st.rerun()

    st.markdown("---")
    st.write("**Jelenlegi tiltott napok:**")
    st.dataframe(load_blocked_df(), use_container_width=True)

# Logout (globális)
st.markdown("---")
if st.button("Kijelentkezés"):
    st.session_state.clear(); st.rerun()
