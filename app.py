# app.py
# Teljes, egyesített Lovarda Időpontfoglaló alkalmazás
# Csak admin regisztrálhat felhasználókat, vendégek csak belépni tudnak

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

# ---- Google Sheets beállítások ----
GOOGLE_SHEET_ID = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7FVRzz7TTGRKrSCy6Uo"
GOOGLE_JSON    = "mystic-fountain-300911-9b2c042063fa.json"

def get_gsheet():
    """Szolgáltató fiókos hitelesítés és Spreadsheet objektum."""
    gc = gspread.service_account(filename=GOOGLE_JSON)
    return gc.open_by_key(GOOGLE_SHEET_ID)

# --- Felhasználók kezelés ---
def get_users_df():
    sh = get_gsheet()
    ws = sh.worksheet("Felhasznalok")
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    return df, ws

def save_users_df(df, ws):
    set_with_dataframe(ws, df, include_index=False)

# --- Foglalások kezelés ---
def get_bookings_df():
    sh = get_gsheet()
    ws = sh.worksheet("Foglalások")
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    # Ha üres, legalább a fejléc legyen meg
    if df.empty or "Dátum" not in df.columns:
        df = pd.DataFrame(columns=[
            "Dátum","Gyermek(ek) neve","Lovak","Kezdés",
            "Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"
        ])
    return df, ws

def save_bookings_df(df, ws):
    set_with_dataframe(ws, df, include_index=False)

# --- Aktivítás-naplózás ---
def log_action(actor, action, details=""):
    sh = get_gsheet()
    # ha nincs Aktivitas munkalap, létrehozzuk
    try:
        ws = sh.worksheet("Aktivitas")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Aktivitas", rows=1000, cols=4)
        ws.append_row(["Idő","Ki","Akció","Részletek"])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([ts, actor, action, details])

# ---- Alapbeállítások ----
ADMIN_PASSWORD = "almakaki"
START_TIME  = time(9,0)
END_TIME    = time(20,30)
DEFAULT_BREAK_MINUTES = 10
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = time(12,0)
LUNCH_WINDOW_END   = time(14,0)
MAX_CHILDREN_PER_SLOT = 7
HORSES = ["Eni","Vera","Lord","Pinty","Szerencse lovag","Herceg"]

# ---- Streamlit session state init ----
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None
if "break_minutes" not in st.session_state:
    st.session_state.break_minutes = DEFAULT_BREAK_MINUTES

# ---- Oldalsáv: Admin belépés és felhasználó-kezelés ----
st.sidebar.title("🔐 Admin panel")
if not st.session_state.authenticated:
    pw = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Bejelentkezés"):
        if pw == ADMIN_PASSWORD:
            st.session_state.authenticated = True
            st.session_state.user = "admin"
            st.sidebar.success("Admin belépve")
            st.experimental_rerun()
        else:
            st.sidebar.error("Hibás jelszó")
    st.stop()
else:
    # Admin felületen: új felhasználó létrehozása
    st.sidebar.subheader("Új felhasználó regisztrálása")
    new_uname = st.sidebar.text_input("Felhasználónév")
    new_pw    = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Regisztrálás"):
        users_df, users_ws = get_users_df()
        if not new_uname or not new_pw:
            st.sidebar.error("Adj meg mindkét mezőt!")
        elif new_uname in users_df["username"].values:
            st.sidebar.error("Ez a név már létezik.")
        else:
            users_df = pd.concat([users_df,
                pd.DataFrame([{"username":new_uname,"password":new_pw}])
            ], ignore_index=True)
            save_users_df(users_df, users_ws)
            log_action("admin","Felhasználó regisztrálva",new_uname)
            st.sidebar.success(f"{new_uname} regisztrálva!")

    # Break beállítása
    st.sidebar.markdown("---")
    st.sidebar.subheader("Szünet (perc)")
    st.session_state.break_minutes = st.sidebar.number_input(
        "", min_value=0, max_value=60,
        value=st.session_state.break_minutes
    )

# ---- Alapoldal ----
st.title("🐴 Lovarda Időpontfoglaló")

# ---- Dátumválasztó és korlátozások ----
selected_date = st.date_input("📅 Dátum")
weekday = selected_date.weekday()
month   = selected_date.month

invalid = False; warn_msg = ""
if month == 7 and weekday not in (0,1):
    invalid = True; warn_msg = "Júliusban csak hétfőn és kedden lehet foglalni."
elif month == 8:
    if selected_date < date(selected_date.year,8,5):
        invalid = True; warn_msg = "Augusztus 1–4. között nem lehet foglalni."
    elif weekday == 0:
        invalid = True; warn_msg = "Augusztusban hétfőn nem lehet foglalni."

if invalid and not st.session_state.authenticated:
    st.warning(warn_msg)
    st.stop()

# ---- Betöltjük a foglalásokat ----
bookings_df, bookings_ws = get_bookings_df()

# ---- Segédfüggvények ----
def slot_overlapping(start_time, end_time, on_date, df):
    """True, ha ütközés van a meglévő foglalásokkal."""
    s_dt = datetime.combine(on_date, start_time)
    e_dt = datetime.combine(on_date, end_time)
    today = on_date.strftime("%Y-%m-%d")
    for _, r in df[df["Dátum"]==today].iterrows():
        b_start = datetime.combine(on_date, datetime.strptime(r["Kezdés"],"%H:%M").time())
        b_end = b_start + timedelta(minutes=int(r["Időtartam (perc)"]))
        if s_dt < b_end and b_start < e_dt:
            return True
    return False

def get_free_slots(duration, on_date, df):
    """Visszaadja az összes szabad slotot megadott hosszra."""
    slots = []
    cur = datetime.combine(on_date, START_TIME)
    lunch_done = False
    day_bookings = df[df["Dátum"]==on_date.strftime("%Y-%m-%d")]
    br = st.session_state.break_minutes
    while cur.time() <= (datetime.combine(on_date,END_TIME)-timedelta(minutes=duration)).time():
        # ebédszünet
        if not lunch_done and LUNCH_WINDOW_START <= cur.time() < LUNCH_WINDOW_END:
            cur += LUNCH_BREAK_DURATION
            lunch_done = True
            continue
        s = cur.time()
        e = (cur + timedelta(minutes=duration)).time()
        if not slot_overlapping(s, e, on_date, df):
            slots.append((s,e))
        cur += timedelta(minutes=duration+br)
    return slots

def has_duplicate_name(df, name, on_date, start, end):
    """Ellenőrzi, ha ugyanazzal a névvel ütköző foglalás van."""
    today = on_date.strftime("%Y-%m-%d")
    for _, r in df[df["Dátum"]==today].iterrows():
        if r["Gyermek(ek) neve"]==name:
            r_s = datetime.combine(on_date, datetime.strptime(r["Kezdés"],"%H:%M").time())
            r_e = r_s + timedelta(minutes=int(r["Időtartam (perc)"]))
            if start < r_e and r_s < end:
                return True
    return False

# ---- Vendég felület (nem-admin) ----
if not st.session_state.authenticated:
    st.subheader("➕ Új foglalás")
    dur = st.selectbox("Időtartam (perc)", [30,60,90], index=0)
    free = get_free_slots(dur, selected_date, bookings_df)
    opts = [f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')}" for s in free]
    with st.form("frm"):
        name   = st.text_input("Gyermek(ek) neve")
        cnt    = st.number_input("Fő", 1, MAX_CHILDREN_PER_SLOT, 1)
        note   = st.text_input("Megjegyzés")
        slot   = st.selectbox("Időpont", opts if opts else ["Nincs időpont"])
        repeat = st.checkbox("Heti ismétlődés")
        if st.form_submit_button("Foglalás"):
            if slot=="Nincs időpont":
                st.error("Nincs elérhető időpont.")
            else:
                idx = opts.index(slot)
                s,e = free[idx]
                s_dt = datetime.combine(selected_date, s)
                e_dt = datetime.combine(selected_date, e)
                if has_duplicate_name(bookings_df, name, selected_date, s_dt, e_dt):
                    st.warning("Ugyanazzal a névvel ütköző foglalás!")
                else:
                    # létrehozás
                    rg = str(uuid.uuid4()) if repeat else ""
                    dates = [selected_date]
                    if repeat:
                        # csak augusztus hónapjára
                        nxt = selected_date + timedelta(weeks=1)
                        while nxt.month == selected_date.month:
                            dates.append(nxt)
                            nxt += timedelta(weeks=1)
                    rows = []
                    for d in dates:
                        rows.append({
                            "Dátum": d.strftime("%Y-%m-%d"),
                            "Gyermek(ek) neve": name,
                            "Lovak": "",
                            "Kezdés": s.strftime("%H:%M"),
                            "Időtartam (perc)": dur,
                            "Fő": cnt,
                            "Ismétlődik": repeat,
                            "RepeatGroupID": rg,
                            "Megjegyzés": note
                        })
                    bookings_df = pd.concat([bookings_df, pd.DataFrame(rows)], ignore_index=True)
                    save_bookings_df(bookings_df, bookings_ws)
                    log_action(name, "Foglalás", f"{selected_date} {slot}")
                    st.success("Foglalás rögzítve!")
                    st.experimental_rerun()
    st.subheader("📆 Elérhető időpontok")
    if opts:
        for s,e in free:
            st.write(f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}")
    else:
        st.info("Nincsenek szabad időpontok.")

    st.stop()

# ---- Admin felület ----
st.subheader("🛠️ Admin felület")

# átalakítjuk dátumokat és hozzáadunk heti, havi mezőt
bookings_df["Dátum"] = pd.to_datetime(bookings_df["Dátum"])
bookings_df["Hét"] = bookings_df["Dátum"].dt.isocalendar().week
bookings_df["Hónap"] = bookings_df["Dátum"].dt.month

# heti nézet kiválasztás
year = selected_date.year
weeks = sorted(bookings_df["Hét"].unique())
week_labels = []
for w in weeks:
    try:
        tue = date.fromisocalendar(year, w, 2)
        sun = date.fromisocalendar(year, w, 7)
        week_labels.append(f"{tue} – {sun}")
    except:
        week_labels.append(str(w))
sel_label = st.selectbox("Válassz hetet", week_labels, index=len(week_labels)-1)
sel_week = weeks[week_labels.index(sel_label)]
week_df = bookings_df[bookings_df["Hét"]==sel_week].sort_values(["Dátum","Kezdés"])

if week_df.empty:
    st.info("Nincs foglalás ezen a héten.")
else:
    st.write(f"Foglalások: {sel_label}")
    for idx, r in week_df.iterrows():
        d = r["Dátum"].strftime("%Y-%m-%d")
        st.markdown(f"**{d} {r['Kezdés']}** – {r['Gyermek(ek) neve']} – {r['Időtartam (perc)']}p – {r['Fő']} fő")
        c1,c2,c3 = st.columns([1,1,2])
        with c1:
            if st.button("❌ Törlés", key=f"del_{idx}"):
                bookings_df = bookings_df.drop(idx)
                save_bookings_df(bookings_df, bookings_ws)
                log_action("admin","Törlés",f"{d} {r['Gyermek(ek) neve']}")
                st.success("Törölve")
                st.experimental_rerun()
        with c2:
            if st.button("🦄 Lovak", key=f"horses_{idx}"):
                st.session_state.mod_idx = idx
        with c3:
            # idő áthelyezése
            dur = int(r["Időtartam (perc)"])
            times = []
            t = datetime.combine(r["Dátum"].date(), START_TIME)
            end_day = datetime.combine(r["Dátum"].date(), END_TIME) - timedelta(minutes=dur)
            while t <= end_day:
                times.append(t.time())
                t += timedelta(minutes=5)
            opts2 = [tt.strftime("%H:%M") for tt in times]
            cur_idx = opts2.index(r["Kezdés"]) if r["Kezdés"] in opts2 else 0
            new_start = st.selectbox("Csúsztatás", opts2, index=cur_idx, key=f"move_{idx}")
            if st.button("Átcsúsztat", key=f"mvbtn_{idx}"):
                bookings_df.at[idx, "Kezdés"] = new_start
                save_bookings_df(bookings_df, bookings_ws)
                log_action("admin","Áthelyezés",f"{d} új kezdés: {new_start}")
                st.success("Áthelyezve")
                st.experimental_rerun()

    # lovak hozzárendelés
    if "mod_idx" in st.session_state:
        m = st.session_state.mod_idx
        row = bookings_df.loc[m]
        st.info(f"{row['Dátum'].strftime('%Y-%m-%d')} {row['Kezdés']} – {row['Gyermek(ek) neve']}")
        cur = [h for h in str(row["Lovak"]).split(",") if h.strip() in HORSES]
        sel = st.multiselect("Lovak", HORSES, default=cur)
        note = st.text_input("Megjegyzés", value=row.get("Megjegyzés",""))
        if st.button("Mentés lovak", key="save_horses"):
            bookings_df.at[m, "Lovak"] = ", ".join(sel)
            bookings_df.at[m, "Megjegyzés"] = note
            save_bookings_df(bookings_df, bookings_ws)
            log_action("admin","Lovak mentve", row["Gyermek(ek) neve"])
            del st.session_state.mod_idx
            st.success("Lovak mentve")
            st.experimental_rerun()

    # statisztika
    with st.expander("📊 Statisztikák"):
        # Top10 nevek
        st.write("**Top 10 név**")
        st.dataframe(bookings_df["Gyermek(ek) neve"].value_counts().head(10))
        # Lókihasználtság
        exploded = bookings_df["Lovak"].astype(str).str.split(",").explode().str.strip()
        st.write("**Lovak kihasználtsága**")
        st.dataframe(exploded[exploded!="" ].value_counts())
        # Heti stat
        st.write("**Heti lóhasználat**")
        week_use = exploded[bookings_df["Hét"]==sel_week]
        st.bar_chart(week_use.value_counts())
        # Havi stat
        st.write("**Havi lóhasználat**")
        for m in sorted(bookings_df["Hónap"].unique()):
            st.write(f"Hónap: {m}")
            month_use = exploded[bookings_df["Hónap"]==m]
            st.bar_chart(month_use.value_counts())
        # Duplikált nevek
        dup = bookings_df["Gyermek(ek) neve"].value_counts()
        st.write("**Duplikált nevek**")
        st.dataframe(dup[dup>1])
        # Jegyzetek
        st.write("**Jegyzetek**")
        st.dataframe(bookings_df[["Gyermek(ek) neve","Dátum","Kezdés","Megjegyzés"]])
