# app.py
# Teljes, beállítható Lovarda Időpontfoglaló alkalmazás
# Beállítások: napi kezdés, zárás, szünet, ebédidő → Google Sheets “Beallitasok” lap

import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from datetime import datetime, date, time, timedelta
import uuid

# ---- ICS csomag opcionális ----
try:
    from ics import Calendar, Event
    ICS_OK = True
except ImportError:
    ICS_OK = False

# ---- Biztonságos újrafuttatás (Streamlit-verziótól függetlenül) ----
def safe_rerun():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

# ---- Google Sheets beállítások ----
GOOGLE_SHEET_ID = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7FVRzz7TTGRKrSCy6Uo"
GOOGLE_JSON    = "mystic-fountain-300911-9b2c042063fa.json"

def get_gsheet():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    return gc.open_by_key(GOOGLE_SHEET_ID)

# ---- Beállítások kezelés (Settings) ----
DEFAULT_SETTINGS = {
    "start_time":    "09:00",
    "end_time":      "20:30",
    "break_minutes": "10",
    "lunch_start":   "12:00",
    "lunch_duration":"45"
}

def get_settings():
    sh = get_gsheet()
    try:
        ws = sh.worksheet("Beallitasok")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Beallitasok", rows=10, cols=2)
        df0 = pd.DataFrame(list(DEFAULT_SETTINGS.items()), columns=["key","value"])
        set_with_dataframe(ws, df0, include_index=False)
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    settings = dict(zip(df["key"], df["value"]))
    return settings, ws

# ---- Felhasználók kezelés ----
def get_users_df():
    sh = get_gsheet()
    ws = sh.worksheet("Felhasznalok")
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    return df, ws

def save_users_df(df, ws):
    set_with_dataframe(ws, df, include_index=False)

# ---- Foglalások kezelés ----
def get_bookings_df():
    sh = get_gsheet()
    ws = sh.worksheet("Foglalások")
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if df.empty or "Dátum" not in df.columns:
        df = pd.DataFrame(columns=[
            "Dátum","Gyermek(ek) neve","Lovak","Kezdés",
            "Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"
        ])
    return df, ws

def save_bookings_df(df, ws):
    set_with_dataframe(ws, df, include_index=False)

# ---- Aktivítás-naplózás ----
def log_action(actor, action, details=""):
    sh = get_gsheet()
    try:
        ws = sh.worksheet("Aktivitas")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Aktivitas", rows=1000, cols=4)
        ws.append_row(["Idő","Ki","Akció","Részletek"])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([ts, actor, action, details])

# ---- Streamlit session_state init ----
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None

# ---- Betöltjük a beállításokat ----
settings, settings_ws = get_settings()
START_TIME         = datetime.strptime(settings["start_time"],"%H:%M").time()
END_TIME           = datetime.strptime(settings["end_time"],"%H:%M").time()
st.session_state.break_minutes = int(settings["break_minutes"])
LUNCH_WINDOW_START = datetime.strptime(settings["lunch_start"],"%H:%M").time()
LUNCH_BREAK_DURATION = timedelta(minutes=int(settings["lunch_duration"]))

# ---- Általános konstansok ----
ADMIN_PASSWORD = "almakaki"
MAX_CHILDREN_PER_SLOT = 7
HORSES = ["Eni","Vera","Lord","Pinty","Szerencse lovag","Herceg"]

# ---- Oldalsáv: Admin belépés & beállítások ----
st.sidebar.title("🔐 Admin panel")
if not st.session_state.authenticated:
    pw = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Bejelentkezés"):
        if pw == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.session_state.user = "admin"
            st.sidebar.success("Admin belépve")
            safe_rerun()
        else:
            st.sidebar.error("Hibás jelszó")
    st.stop()
else:
    # 1) Új felhasználó regisztrálása
    st.sidebar.subheader("➕ Új felhasználó")
    new_uname = st.sidebar.text_input("Felhasználónév")
    new_pw    = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Regisztrálás"):
        users_df, users_ws = get_users_df()
        if not new_uname or not new_pw:
            st.sidebar.error("Töltsd ki mindkét mezőt!")
        elif new_uname in users_df["username"].values:
            st.sidebar.error("Név már létezik.")
        else:
            users_df = pd.concat([
                users_df,
                pd.DataFrame([{"username":new_uname,"password":new_pw}])
            ], ignore_index=True)
            save_users_df(users_df, users_ws)
            log_action("admin","Felhasználó regisztrálva",new_uname)
            st.sidebar.success(f"{new_uname} regisztrálva!")
            safe_rerun()

    # 2) Foglalási időablak & szünet & ebédidő szerkesztése
    st.sidebar.markdown("---")
    st.sidebar.subheader("⏰ Foglalási időablak")
    new_start = st.sidebar.time_input("Kezdés", START_TIME)
    new_end   = st.sidebar.time_input("Zárás", END_TIME)
    new_break = st.sidebar.number_input("Szünet (perc)", 0, 60, st.session_state.break_minutes)

    st.sidebar.subheader("🍽️ Ebédidő")
    new_lunch_start = st.sidebar.time_input("Ebéd kezdete", LUNCH_WINDOW_START)
    new_lunch_dur   = st.sidebar.number_input("Ebéd hossza (perc)", 0, 180, int(settings["lunch_duration"]))

    if st.sidebar.button("Mentés beállítások"):
        df2 = pd.DataFrame([
            ("start_time",    new_start.strftime("%H:%M")),
            ("end_time",      new_end.strftime("%H:%M")),
            ("break_minutes", str(new_break)),
            ("lunch_start",   new_lunch_start.strftime("%H:%M")),
            ("lunch_duration",str(new_lunch_dur))
        ], columns=["key","value"])
        set_with_dataframe(settings_ws, df2, include_index=False)
        st.sidebar.success("Beállítások mentve!")
        safe_rerun()

# ---- Főoldal ----
st.title("🐴 Lovarda Időpontfoglaló")

# ---- Dátumválasztó & korlátozások (július/augusztus) ----
selected_date = st.date_input("📅 Dátum")
wd = selected_date.weekday()
m  = selected_date.month
invalid=False; msg=""
if m==7   and wd not in (0,1): msg="Júliusban csak hétfő/kedd."; invalid=True
elif m==8 and selected_date<date(selected_date.year,8,5): msg="Aug 1–4 tiltva."; invalid=True
elif m==8 and wd==0: msg="Augusztusban hétfő nem."; invalid=True
if invalid and not st.session_state.authenticated:
    st.warning(msg); st.stop()

# ---- Foglalások betöltése ----
bookings_df, bookings_ws = get_bookings_df()

# ---- Segédfüggvények ----
def slot_overlapping(s,e,d,df):
    sd, ed = datetime.combine(d,s), datetime.combine(d,e)
    for _,r in df[df["Dátum"]==d.strftime("%Y-%m-%d")].iterrows():
        bs = datetime.combine(d, datetime.strptime(r["Kezdés"],"%H:%M").time())
        be = bs + timedelta(minutes=int(r["Időtartam (perc)"]))
        if sd<be and bs<ed:
            return True
    return False

def get_free_slots(dur,d,df):
    slots=[]; cur=datetime.combine(d,START_TIME); lunch_done=False; br=st.session_state.break_minutes
    while cur.time() <= (datetime.combine(d,END_TIME)-timedelta(minutes=dur)).time():
        if not lunch_done and LUNCH_WINDOW_START<=cur.time()< (datetime.combine(d,LUNCH_WINDOW_START)+LUNCH_BREAK_DURATION).time():
            cur+=LUNCH_BREAK_DURATION; lunch_done=True; continue
        s,e=cur.time(),(cur+timedelta(minutes=dur)).time()
        if not slot_overlapping(s,e,d,df):
            slots.append((s,e))
        cur+=timedelta(minutes=dur+br)
    return slots

def has_duplicate_name(df,name,d,sd,ed):
    for _,r in df[df["Dátum"]==d.strftime("%Y-%m-%d")].iterrows():
        bs = datetime.combine(d, datetime.strptime(r["Kezdés"],"%H:%M").time())
        be = bs + timedelta(minutes=int(r["Időtartam (perc)"]))
        if sd<be and bs<ed: return True
    return False

# ---- Vendég (csak foglalás) ----
if not st.session_state.authenticated:
    st.subheader("➕ Új foglalás")
    dur   = st.selectbox("Időtartam (perc)", [30,60,90], index=0)
    free  = get_free_slots(dur, selected_date, bookings_df)
    opts  = [f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s,e in free]
    with st.form("frm"):
        name   = st.text_input("Gyermek(ek) neve")
        cnt    = st.number_input("Fő",1,MAX_CHILDREN_PER_SLOT,1)
        note   = st.text_input("Megjegyzés")
        slot   = st.selectbox("Időpont", opts if opts else ["Nincs időpont"])
        repeat = st.checkbox("Heti ismétlődés")
        if st.form_submit_button("Foglalás"):
            if slot=="Nincs időpont":
                st.error("Nincs elérhető időpont.")
            else:
                i = opts.index(slot)
                s,e = free[i]
                sd, ed = datetime.combine(selected_date,s), datetime.combine(selected_date,e)
                if has_duplicate_name(bookings_df,name,selected_date,sd,ed):
                    st.warning("Ütköző név foglalás!")
                else:
                    rg = str(uuid.uuid4()) if repeat else ""
                    dates=[selected_date]
                    if repeat:
                        nxt=selected_date+timedelta(weeks=1)
                        while nxt.month==selected_date.month:
                            dates.append(nxt); nxt+=timedelta(weeks=1)
                    rows=[]
                    for d in dates:
                        rows.append({
                            "Dátum":d.strftime("%Y-%m-%d"),
                            "Gyermek(ek) neve":name,
                            "Lovak":"",
                            "Kezdés":s.strftime("%H:%M"),
                            "Időtartam (perc)":dur,
                            "Fő":cnt,
                            "Ismétlődik":repeat,
                            "RepeatGroupID":rg,
                            "Megjegyzés":note
                        })
                    bookings_df=pd.concat([bookings_df,pd.DataFrame(rows)],ignore_index=True)
                    save_bookings_df(bookings_df,bookings_ws)
                    log_action(name,"Foglalás",f"{selected_date} {slot}")
                    st.success("Foglalás rögzítve!"); safe_rerun()
    st.subheader("📆 Elérhető időpontok")
    if opts:
        for s,e in free:
            st.write(f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}")
    else:
        st.info("Nincsenek szabad időpontok.")
    st.stop()

# ---- Admin felület ----
st.subheader("🛠️ Admin felület")
bookings_df["Dátum"]=pd.to_datetime(bookings_df["Dátum"])
bookings_df["Hét"]=bookings_df["Dátum"].dt.isocalendar().week
bookings_df["Hónap"]=bookings_df["Dátum"].dt.month

year=selected_date.year
weeks=sorted(bookings_df["Hét"].unique())
labels=[]
for w in weeks:
    try:
        t=date.fromisocalendar(year,w,2)
        s=date.fromisocalendar(year,w,7)
        labels.append(f"{t} – {s}")
    except:
        labels.append(str(w))
sel=st.selectbox("Válassz hetet",labels,index=len(labels)-1)
w=weeks[labels.index(sel)]
week_df=bookings_df[bookings_df["Hét"]==w].sort_values(["Dátum","Kezdés"])

if week_df.empty:
    st.info("Nincs foglalás erre a hétre.")
else:
    st.write(f"Foglalások: {sel}")
    for idx,row in week_df.iterrows():
        d=row["Dátum"].strftime("%Y-%m-%d")
        st.markdown(f"**{d} {row['Kezdés']}** – {row['Gyermek(ek) neve']} – {row['Időtartam (perc)']}p – {row['Fő']} fő")
        c1,c2,c3=st.columns([1,1,2])
        with c1:
            if st.button("❌ Törlés",key=f"del{idx}"):
                bookings_df=bookings_df.drop(idx)
                save_bookings_df(bookings_df,bookings_ws)
                log_action("admin","Törlés",f"{d} {row['Gyermek(ek) neve']}")
                st.success("Törölve"); safe_rerun()
        with c2:
            if st.button("🦄 Lovak",key=f"lo{idx}"):
                st.session_state.mod_idx=idx
        with c3:
            dur=int(row["Időtartam (perc)"])
            times=[]; t0=datetime.combine(row["Dátum"].date(),START_TIME)
            end_day=datetime.combine(row["Dátum"].date(),END_TIME)-timedelta(minutes=dur)
            while t0<=end_day:
                times.append(t0.time()); t0+=timedelta(minutes=5)
            opts2=[tt.strftime("%H:%M") for tt in times]
            ci=opts2.index(row["Kezdés"]) if row["Kezdés"] in opts2 else 0
            ns=st.selectbox("Csúsztatás",opts2,index=ci,key=f"mv{idx}")
            if st.button("Átcsúsztat",key=f"mvbtn{idx}"):
                bookings_df.at[idx,"Kezdés"]=ns
                save_bookings_df(bookings_df,bookings_ws)
                log_action("admin","Áthelyezés",f"{d} új: {ns}")
                st.success("Átcsúsztatva"); safe_rerun()

    # Lovak hozzárendelése
    if "mod_idx" in st.session_state:
        m=st.session_state.mod_idx
        r=bookings_df.loc[m]
        st.info(f"{r['Dátum'].strftime('%Y-%m-%d')} {r['Kezdés']} – {r['Gyermek(ek) neve']}")
        cur=[h for h in str(r["Lovak"]).split(",") if h.strip() in HORSES]
        sel=st.multiselect("Lovak", HORSES, default=cur)
        note=st.text_input("Megjegyzés",value=r.get("Megjegyzés",""))
        if st.button("Mentés lovak",key="savelo"):
            bookings_df.at[m,"Lovak"]=", ".join(sel)
            bookings_df.at[m,"Megjegyzés"]=note
            save_bookings_df(bookings_df,bookings_ws)
            log_action("admin","Lovak mentve",r["Gyermek(ek) neve"])
            del st.session_state.mod_idx
            st.success("Lovak mentve"); safe_rerun()

    # Statisztikák
    with st.expander("📊 Statisztikák"):
        st.write("**Top 10 név**")
        st.dataframe(bookings_df["Gyermek(ek) neve"].value_counts().head(10))
        exploded=bookings_df["Lovak"].astype(str).str.split(",").explode().str.strip()
        st.write("**Lovak kihasználtsága**")
        st.dataframe(exploded[exploded!=""].value_counts())
        st.write("**Heti lóhasználat**")
        wu=exploded[bookings_df["Hét"]==w]
        st.bar_chart(wu.value_counts())
        st.write("**Havi lóhasználat**")
        for mm in sorted(bookings_df["Hónap"].unique()):
            st.write(f"Hónap: {mm}")
            mu=exploded[bookings_df["Hónap"]==mm]
            st.bar_chart(mu.value_counts())
        st.write("**Duplikált nevek**")
        dup=bookings_df["Gyermek(ek) neve"].value_counts()
        st.dataframe(dup[dup>1])
        st.write("**Jegyzetek**")
        st.dataframe(bookings_df[["Gyermek(ek) neve","Dátum","Kezdés","Megjegyzés"]])
