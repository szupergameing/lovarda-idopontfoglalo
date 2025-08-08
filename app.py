from datetime import datetime, date, time, timedelta
import uuid
import os
import pandas as pd
import streamlit as st
import gspread
import altair as alt
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from supabase import create_client, Client

# ---- PERMANENS DARK MODE ----
st.markdown("""
    <style>
      .stApp, body, .css-18e3th9 { background-color: #121212 !important; color: #e0e0e0 !important; }
      .stButton>button, .stSelectbox>div>div, .stTextInput>div>div>input,
      .stDateInput>div>div>div>input {
        background-color: #1e1e1e !important; color: #e0e0e0 !important; border: 1px solid #333 !important;
      }
      .css-1d391kg.sidebar-content { background-color: #181818 !important; }
      .stDataFrame, .stBarChart, .stLineChart, .stAreaChart { background-color: #121212 !important; }
      ::-webkit-scrollbar { width: 8px; }
      ::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
      ::-webkit-scrollbar-track { background: #121212; }
    </style>
""", unsafe_allow_html=True)

# ---- Google Sheets config & constants ----
GOOGLE_SHEET_ID     = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7FVRzz7TTGRKrSCy6Uo"
GOOGLE_JSON         = "mystic-fountain-300911-9b2c042063fa.json"
ADMIN_PW            = "almakaki"
START_TIME          = time(9,0)
END_TIME            = time(20,30)
DEFAULT_BREAK_MIN   = 10
DEFAULT_LUNCH_START = time(12,0)
DEFAULT_LUNCH_DUR   = 45  # perc

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

@st.cache_resource
def get_supabase_client() -> Client | None:
    if SUPABASE_URL and SUPABASE_KEY:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None

@st.cache_resource
def get_gspread_client():
    return gspread.service_account(filename=GOOGLE_JSON)

# ---- DataFrame betöltők ----
@st.cache_data(ttl=60)
def load_bookings_df():
    ws = get_gspread_client().open_by_key(GOOGLE_SHEET_ID).worksheet("Foglalások")
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if "Dátum" in df.columns:
        df["Dátum"] = pd.to_datetime(df["Dátum"]).dt.date
    return df

@st.cache_data(ttl=60)
def load_users_df():
    sb = get_supabase_client()
    if sb is not None:
        res = sb.table("users").select("*").execute()
        data = res.data or []
        df = pd.DataFrame(data)
        if df.empty:
            df = pd.DataFrame(columns=["username","password"])
        return df
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    for name in ("Felhasználók","Felhasznalok"):
        try:
            ws = sh.worksheet(name)
            break
        except gspread.exceptions.WorksheetNotFound:
            ws = None
    if ws is None:
        ws = sh.add_worksheet("Felhasználók", rows=100, cols=2)
        ws.append_row(["username","password"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    return df

@st.cache_data(ttl=60)
def load_blocked_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet("TiltottNapok")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("TiltottNapok", rows=100, cols=1)
        ws.append_row(["Dátum"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if "Dátum" in df.columns:
        df["Dátum"] = pd.to_datetime(df["Dátum"]).dt.date
    return df

@st.cache_data(ttl=300)
def load_settings_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet("Beallitasok")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("Beallitasok", rows=10, cols=2)
        ws.append_rows([
            ["lunch_start","12:00"],
            ["lunch_dur","45"],
            ["break_min","10"]
        ])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    df.columns = ["Key","Value"]
    return df

@st.cache_data(ttl=60)
def load_lunch_overrides_df():
    sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sh.worksheet("EbédSzunet")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet("EbédSzunet", rows=100, cols=3)
        ws.append_row(["Dátum","Kezdes","HosszPerc"])
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all").fillna("")
    if not df.empty:
        df["Dátum"]     = pd.to_datetime(df["Dátum"]).dt.date
        df["Kezdes"]    = pd.to_datetime(df["Kezdes"]).dt.time
        df["HosszPerc"] = df["HosszPerc"].astype(int)
    return df

# ---- Mentő- és mentőfüggvények ----
def save_df_to_sheet(df: pd.DataFrame, sheet_name: str):
    ws = get_gspread_client().open_by_key(GOOGLE_SHEET_ID).worksheet(sheet_name)
    ws.clear()
    set_with_dataframe(ws, df, include_index=False)

def save_settings_df(df: pd.DataFrame):
    save_df_to_sheet(df, "Beallitasok")

def save_user(username: str, password: str):
    sb = get_supabase_client()
    if sb is not None:
        sb.table("users").insert({"username": username, "password": password}).execute()
    else:
        dfu = load_users_df()
        dfu = pd.concat([dfu, pd.DataFrame([{"username": username, "password": password}])], ignore_index=True)
        save_df_to_sheet(dfu, "Felhasználók")

def log_action(user: str, action: str, details: str = ""):
    try:
        sh = get_gspread_client().open_by_key(GOOGLE_SHEET_ID)
        try:
            ws = sh.worksheet("Naplo")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet("Naplo", rows=1000, cols=4)
            ws.append_row(["Idő", "Felhasználó", "Művelet", "Részletek"])
        ws.append_row([datetime.now().isoformat(), user, action, details])
    except Exception:
        pass

def safe_rerun():
    try: st.experimental_rerun()
    except: pass

# ---- ICS generátor ----
def generate_ics(df: pd.DataFrame):
    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//Lovarda Foglaló//EN"]
    for _,r in df.iterrows():
        dtstart = datetime.combine(r["Dátum"], datetime.strptime(r["Kezdés"],"%H:%M").time())
        dtend   = dtstart + timedelta(minutes=int(r["Időtartam (perc)"]))
        uid     = uuid.uuid4()
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
            f"DTSTART:{dtstart:%Y%m%dT%H%M%S}",
            f"DTEND:{dtend:%Y%m%dT%H%M%S}",
            f"SUMMARY:Lovarda foglalás ({r['Gyermek(ek) neve']})",
            "END:VEVENT"
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

# ---- Session init: globális beállítások fallback-kel ----
raw = load_settings_df().set_index("Key")["Value"].to_dict()
lunch_start_str = raw.get("lunch_start", DEFAULT_LUNCH_START.strftime("%H:%M"))
lunch_dur_str   = raw.get("lunch_dur",   str(DEFAULT_LUNCH_DUR))
break_min_str   = raw.get("break_min",   str(DEFAULT_BREAK_MIN))

if "lunch_start" not in st.session_state:
    st.session_state["lunch_start"] = datetime.strptime(lunch_start_str,"%H:%M").time()
if "lunch_dur" not in st.session_state:
    st.session_state["lunch_dur"]   = int(lunch_dur_str)
if "break_min" not in st.session_state:
    st.session_state["break_min"]   = int(break_min_str)
for k in ("role","auth","user"):
    if k not in st.session_state:
        st.session_state[k] = None

st.title("🐴 Lovarda Időpontfoglaló")

# ---- Szerepkiválasztás ----
if st.session_state.role is None:
    st.write("**Válassz szerepet:**")
    c1,c2 = st.columns(2)
    if c1.button("Lovas"):
        st.session_state.role="rider"; safe_rerun()
    if c2.button("Admin"):
        st.session_state.role="admin"; safe_rerun()
    st.stop()

# ---- Auth ----
if not st.session_state.auth:
    if st.session_state.role=="rider":
        dfu = load_users_df()
        st.subheader("Lovas bejelentkezés")
        uname = st.text_input("Felhasználónév")
        pwd   = st.text_input("Jelszó", type="password")
        if st.button("Bejelentkezés lovasként"):
            if ((dfu["username"]==uname)&(dfu["password"]==pwd)).any():
                st.session_state.auth=True
                st.session_state.user=uname
                safe_rerun()
            else:
                st.error("Hibás belépés.")
    else:
        st.subheader("Admin bejelentkezés")
        pwd = st.text_input("Jelszó", type="password")
        if st.button("Bejelentkezés adminként"):
            if pwd==ADMIN_PW:
                st.session_state.auth=True; safe_rerun()
            else:
                st.error("Hibás jelszó.")
    st.stop()

# ---- Dátum és tiltott napok ----
sel_date = st.date_input("Dátum kiválasztása")
wd, mo   = sel_date.weekday(), sel_date.month
if mo==7 and wd not in (0,1):
    st.warning("Júliusban csak hétfő–kedd foglalható."); st.stop()
elif mo==8 and wd==0:
    st.warning("Augusztusban csak kedd–vasárnap foglalható."); st.stop()
blocked    = load_blocked_df()
if st.session_state.role=="rider" and sel_date in blocked["Dátum"].tolist():
    st.warning("❌ Ezen a napon nem lehet foglalni."); st.stop()

bookings_df   = load_bookings_df()
lunch_over_df = load_lunch_overrides_df()

# ---- Slot generálás ----
def get_free_slots(duration):
    slots = []
    cur   = datetime.combine(sel_date, START_TIME)
    odf   = lunch_over_df[lunch_over_df["Dátum"]==sel_date]
    if not odf.empty:
        ls = odf.iloc[0]["Kezdes"]; ld = int(odf.iloc[0]["HosszPerc"])
    else:
        ls = st.session_state["lunch_start"]; ld = st.session_state["lunch_dur"]
    lunch_end = (datetime.combine(sel_date, ls) + timedelta(minutes=ld)).time()
    break_min = st.session_state["break_min"]
    today     = bookings_df[bookings_df["Dátum"]==sel_date]
    last_start= (datetime.combine(sel_date, END_TIME) - timedelta(minutes=duration)).time()

    while cur.time() <= last_start:
        if ls <= cur.time() < lunch_end:
            cur += timedelta(minutes=ld)
            continue
        stime = cur.time()
        end_dt= cur + timedelta(minutes=duration)
        etime = end_dt.time()
        conflict=False
        for _,r in today.iterrows():
            bs = datetime.combine(sel_date, datetime.strptime(r["Kezdés"], "%H:%M").time())
            be = bs + timedelta(minutes=int(r["Időtartam (perc)"]))
            if cur < be and bs < end_dt:
                conflict=True; break
        if not conflict:
            slots.append((stime, etime))
        cur += timedelta(minutes=duration + break_min)
    return slots

# ---- Rider nézet ----
if st.session_state.role=="rider":
    st.subheader(f"Üdv, {st.session_state.user}!")
    names = st.text_input("Gyermek(ek) neve(i), vesszővel elválasztva", value=st.session_state.user)
    dur   = st.selectbox("Időtartam (perc)", [30,60,90])
    free  = get_free_slots(dur)
    if not free:
        st.info("Nincs szabad időpont.")
    else:
        for i,(s,e) in enumerate(free):
            c1,c2 = st.columns([1,1])
            label = f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
            # sima Foglalás
            if c1.button(f"Foglal {label}", key=f"bk{i}"):
                new = {
                    "Dátum":sel_date, "Gyermek(ek) neve":names,
                    "Lovak":"", "Kezdés":s.strftime("%H:%M"),
                    "Időtartam (perc)":dur,"Fő":1,
                    "Ismétlődik":False, "RepeatGroupID":"", "Megjegyzés":""
                }
                bookings_df = pd.concat([bookings_df, pd.DataFrame([new])], ignore_index=True)
                save_df_to_sheet(bookings_df, "Foglalások")
                log_action(st.session_state.user, "foglalás", f"{sel_date} {label}")
                st.success("Foglalás sikeres!"); safe_rerun()

            # Örökítés gomb: heti ismétlés a következő évre
            if c2.button(f"Örökítés {label}", key=f"orok{i}"):
                future = pd.date_range(
                    start=sel_date + timedelta(weeks=1),
                    end=sel_date + timedelta(days=365),
                    freq='7D'
                ).date
                conflicts = [d for d in future
                             if ((bookings_df["Dátum"]==d)&
                                 (bookings_df["Kezdés"]==s.strftime("%H:%M"))).any()]
                if conflicts:
                    st.warning(f"Ütközés: már foglalt napok: {', '.join(map(str,conflicts))}")
                new_entries = []
                for d in future:
                    if d not in conflicts:
                        new_entries.append({
                            "Dátum": d,
                            "Gyermek(ek) neve": names,
                            "Lovak":"",
                            "Kezdés": s.strftime("%H:%M"),
                            "Időtartam (perc)": dur,
                            "Fő": 1,
                            "Ismétlődik": True,
                            "RepeatGroupID": f"orok{i}",
                            "Megjegyzés": "örökítés"
                        })
                if new_entries:
                    bookings_df = pd.concat([bookings_df, pd.DataFrame(new_entries)], ignore_index=True)
                    save_df_to_sheet(bookings_df, "Foglalások")
                    log_action(st.session_state.user, "örökítés", f"{sel_date} {label}")
                    st.success("Örökítés lefuttatva az elkövetkező évre!"); safe_rerun()

    # saját foglalások ICS
    mask = (
        bookings_df["Gyermek(ek) neve"]
        .fillna("")
        .astype(str)
        .str.contains(st.session_state.user, case=False, na=False)
    )
    my_df = bookings_df[mask]
    if not my_df.empty:
        ics = generate_ics(my_df)
        st.download_button("ICS export (saját)", data=ics,
                           file_name="sajat_foglalasok.ics", mime="text/calendar")
    st.stop()

# ---- Admin nézet ----
st.subheader("🛠️ Admin felület")
menu = st.radio("Menü", ["Foglalások","Felhasználók","Statisztika","Beállítások","Naptár"])

if menu=="Foglalások":
    st.markdown("### Heti foglalások")
    wn  = sel_date.isocalendar()[1]
    wdf = bookings_df[bookings_df["Dátum"].apply(lambda d:d.isocalendar()[1])==wn]
    if wdf.empty:
        st.info("Nincs foglalás ezen a héten.")
    else:
        for idx,r in wdf.iterrows():
            st.write(f"**{r['Dátum']} {r['Kezdés']}** – {r['Gyermek(ek) neve']} ({r['Időtartam (perc)']}p)")
            c1,c2,c3 = st.columns([1,1,1])
            # egyedi sor törlése
            if c1.button("❌ Törlés", key=f"del{idx}"):
                bookings_df = bookings_df.drop(idx)
                save_df_to_sheet(bookings_df,"Foglalások")
                log_action("admin","foglalás törlése", f"{r['Dátum']} {r['Kezdés']}")
                safe_rerun()
            # áthelyezés
            if st.session_state.get("edit_idx")!=idx:
                if c2.button("↻ Áthelyez", key=f"mv{idx}"):
                    st.session_state["edit_idx"]=idx
                    st.session_state["new_time"]=datetime.strptime(r["Kezdés"],"%H:%M").time()
                    safe_rerun()
            else:
                nt = c2.time_input("Új kezdés", value=st.session_state["new_time"], key=f"time{idx}")
                if c2.button("Mentés", key=f"save{idx}"):
                    bookings_df.at[idx,"Kezdés"]=nt.strftime("%H:%M")
                    save_df_to_sheet(bookings_df,"Foglalások")
                    log_action("admin","foglalás módosítása", f"{r['Dátum']} {r['Kezdés']}->{nt.strftime('%H:%M')}")
                    del st.session_state["edit_idx"]
                    safe_rerun()
            # Stop ismétlés, ha RepeatGroupID van
            rg = r.get("RepeatGroupID","")
            if rg:
                if c3.button("↺ Stop ismétlés", key=f"stop{idx}"):
                    bookings_df = bookings_df[~(
                        (bookings_df["RepeatGroupID"]==rg) &
                        (bookings_df["Dátum"]>=sel_date)
                    )]
                    save_df_to_sheet(bookings_df,"Foglalások")
                    log_action("admin","ismétlés leállítása", rg)
                    st.success("Ismétlés leállítva innen!"); safe_rerun()
    # teljes ICS export
    ics_all = generate_ics(bookings_df)
    st.download_button("ICS export (összes)", data=ics_all,
                       file_name="osszes_foglalas.ics", mime="text/calendar")

elif menu=="Felhasználók":
    dfu = load_users_df()
    st.dataframe(dfu)
    nu  = st.text_input("Új felhasználó")
    npw = st.text_input("Új jelszó", type="password")
    if st.button("Regisztrálás"):
        save_user(nu, npw)
        log_action("admin", "felhasználó regisztrálása", nu)
        st.success("Felhasználó hozzáadva!"); safe_rerun()

elif menu=="Statisztika":
    st.write("📊 Foglalások napi bontásban")
    st.bar_chart(bookings_df["Dátum"].value_counts())

elif menu=="Beállítások":
    st.header("⚙️ Globális & napi ebédszünet & átnyergelési idő")

    # 1) Mai foglalások idővonalként
    df_ = bookings_df[bookings_df["Dátum"]==sel_date].copy()
    if not df_.empty:
        df_["start"] = pd.to_datetime(df_["Dátum"].astype(str)+" "+df_["Kezdés"])
        df_["end"]   = df_["start"] + pd.to_timedelta(df_["Időtartam (perc)"],unit="m")

    # 2) napi override vagy globális
    odf = lunch_over_df[lunch_over_df["Dátum"]==sel_date]
    if not odf.empty:
        base_ls, base_ld = odf.iloc[0]["Kezdes"], odf.iloc[0]["HosszPerc"]
    else:
        base_ls, base_ld = st.session_state["lunch_start"], st.session_state["lunch_dur"]

    # 3) éles slider + input
    ov_ls_dt = st.slider(
        "Napi ebédszünet kezdete",
        min_value=datetime.combine(sel_date,START_TIME),
        max_value=datetime.combine(sel_date,END_TIME),
        value=datetime.combine(sel_date,base_ls),
        format="HH:mm"
    )
    ov_ls = ov_ls_dt.time()
    ov_ld = st.number_input(
        "Napi ebédszünet hossza (perc)",
        min_value=0, max_value=180,
        value=int(base_ld), step=5
    )

    # 4) idővonal kirajzolása
    lunch_bar = pd.DataFrame([{
        "type":"Ebédszünet",
        "start":datetime.combine(sel_date,ov_ls),
        "end":  datetime.combine(sel_date,ov_ls)+timedelta(minutes=int(ov_ld))
    }])
    timeline = pd.concat([df_.assign(type="Foglalás"), lunch_bar], ignore_index=True)
    chart = (
        alt.Chart(timeline)
           .mark_bar(size=20)
           .encode(x='start:T', x2='end:T', y=alt.value(0),
                   color='type:N', tooltip=['type','start:T','end:T'])
           .properties(height=80)
    )
    st.altair_chart(chart, use_container_width=True)
    st.markdown("---")

    # 5) mentés gombok
    col1,col2 = st.columns(2)
    with col1:
        if st.button("Mentés — Napi override"):
            new_ov = lunch_over_df[lunch_over_df["Dátum"]!=sel_date]
            new_ov = pd.concat([new_ov,
                pd.DataFrame([{"Dátum":sel_date,"Kezdes":ov_ls,"HosszPerc":int(ov_ld)}])
            ], ignore_index=True)
            save_df_to_sheet(new_ov,"EbédSzunet")
            log_action("admin","napi ebédszünet mentése", str(sel_date))
            st.success("Napi ebédszünet mentve."); safe_rerun()
    with col2:
        br = st.number_input(
            "Átnyergelési idő (perc)",
            min_value=0, max_value=60,
            value=st.session_state["break_min"], step=1
        )
        if st.button("Mentés — Átnyergelési idő"):
            st.session_state["break_min"]=int(br)
            df = load_settings_df()
            df.loc[df["Key"]=="break_min","Value"]=str(int(br))
            save_settings_df(df)
            log_action("admin","átnyergelési idő mentése", str(br))
            st.success("Átnyergelési idő mentve."); safe_rerun()

    # 6) globális ebédszünet beállítása
    st.markdown("### Globális ebédszünet")
    g1,g2 = st.columns(2)
    with g1:
        glob_ls = st.time_input("Alap ebédszünet kezdete", value=st.session_state["lunch_start"])
    with g2:
        glob_ld = st.number_input(
            "Alap ebédszünet hossza (perc)",
            min_value=0, max_value=180,
            value=st.session_state["lunch_dur"], step=5
        )
    if st.button("Mentés — Globális ebédszünet"):
        st.session_state["lunch_start"]=glob_ls
        st.session_state["lunch_dur"]=glob_ld
        df = load_settings_df()
        df.loc[df["Key"]=="lunch_start","Value"]=glob_ls.strftime("%H:%M")
        df.loc[df["Key"]=="lunch_dur",    "Value"]=str(int(glob_ld))
        save_settings_df(df)
        log_action("admin","globális ebédszünet mentése", f"{glob_ls}-{glob_ld}")
        st.success("Globális ebédszünet mentve."); safe_rerun()

elif menu=="Naptár":
    st.header("📅 Tiltott napok kezelése")
    bd = blocked
    st.write("Tiltott napok:", bd["Dátum"].tolist())
    c1,c2 = st.columns(2)
    with c1: sb = st.date_input("Kezdés", value=date.today())
    with c2: eb = st.date_input("Vége",   value=date.today())
    if st.button("Tiltás mentése"):
        if eb<sb:
            st.error("Vége nem lehet korábbi.")
        else:
            rng = pd.date_range(sb, eb).date
            new_df = pd.DataFrame({"Dátum":rng})
            merged = pd.concat([bd,new_df],ignore_index=True)\
                       .drop_duplicates(subset=["Dátum"])\
                       .sort_values("Dátum")
            save_df_to_sheet(merged,"TiltottNapok")
            log_action("admin","nap tiltása", f"{sb}-{eb}")
            safe_rerun()

# ---- Kijelentkezés ----
if st.button("Kijelentkezés"):
    st.session_state.clear()
    safe_rerun()
