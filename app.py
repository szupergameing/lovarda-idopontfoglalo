import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe

# ---- Google Sheets setup ----
GOOGLE_SHEET_ID = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7TTGRKrSCy6Uo"
GOOGLE_JSON = "mystic-fountain-300911-9b2c042063fa.json"

# ---- Helper functions ----
def get_gsheet_df():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    try:
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("Nem található a megadott Google Sheet. Kérlek ellenőrizd a SHEET_ID-t és oszd meg a táblázatot a service account e-mail címével.")
        st.stop()
    ws = sh.sheet1
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all")
    if "Dátum" in df.columns:
        df["Dátum"] = pd.to_datetime(df["Dátum"]).dt.date
    else:
        df = pd.DataFrame(columns=[
            "Dátum","Gyermek(ek) neve","Lovak","Kezdés",
            "Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"
        ])
    return df, ws

def get_users_df():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.get_worksheet(1)
    users = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all")
    return users, ws

def save_df(df, ws):
    cols = ["Dátum","Gyermek(ek) neve","Lovak","Kezdés",
            "Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"]
    ws.clear()
    set_with_dataframe(ws, df[cols], include_index=False)

def save_users(users_df, ws):
    ws.clear()
    set_with_dataframe(ws, users_df, include_index=False)

# ---- Config ----
START_TIME = time(9, 0)
END_TIME = time(20, 30)
BREAK_MIN = 10
LUNCH_START = time(12, 0)
LUNCH_END = time(14, 0)
LUNCH_DUR = timedelta(minutes=45)
MAX_CHILDREN = 7
HORSES = ["Eni","Vera","Lord","Pinty","Szerencse lovag","Herceg"]
ADMIN_PW = "almakaki"

# ---- Session init ----
for key in ["role","auth","user"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ---- Dark theme ----
st.markdown(
    "<style>body{background:#181818;color:#f5f5f5;}" +
    ".stButton>button{color:#000;} .stSelectbox>div>div{color:#000;}" +
    ".stTextInput>div>div>input{background:#fff;color:#000;}" +
    "</style>",
    unsafe_allow_html=True
)

# ---- Title ----
st.title("🐴 Lovarda Időpontfoglaló")

# ---- Role selection ----
if st.session_state.role is None:
    st.write("**Válassz szerepet:**")
    c1, c2 = st.columns(2)
    if c1.button("Lovas"):
        st.session_state.role = "rider"
        st.rerun()
    if c2.button("Admin"):
        st.session_state.role = "admin"
        st.rerun()
    st.stop()

# ---- Authentication ----
if not st.session_state.auth:
    if st.session_state.role == "rider":
        users_df, users_ws = get_users_df()
        st.subheader("Lovas bejelentkezés")
        uname = st.text_input("Felhasználónév")
        pwd = st.text_input("Jelszó", type="password")
        if st.button("Bejelentkezés lovasként"):
            if ((users_df['username'] == uname) & (users_df['password'] == pwd)).any():
                st.session_state.auth = True
                st.session_state.user = uname
                st.rerun()
            else:
                st.error("Hibás felhasználónév vagy jelszó.")
    else:
        st.subheader("Admin bejelentkezés")
        pwd = st.text_input("Jelszó", type="password")
        if st.button("Bejelentkezés adminként"):
            if pwd == ADMIN_PW:
                st.session_state.auth = True
                st.rerun()
            else:
                st.error("Hibás admin jelszó.")
    st.stop()

# ---- Date ----
sel_date = st.date_input("Dátum kiválasztása")
wd, mo = sel_date.weekday(), sel_date.month
if mo == 7 and wd not in [0,1]:
    st.warning("Júliusban csak hétfő és kedd foglalható.")
elif mo == 8:
    if sel_date < date(2025,8,5):
        st.warning("Augusztus 1–4 között nem foglalható.")
    elif wd == 0:
        st.warning("Augusztusban hétfő nem foglalható.")

# ---- Load bookings ----
df, ws = get_gsheet_df()

# ---- Helpers ----
def overlaps(s, e, bookings):
    sdt = datetime.combine(sel_date, s)
    edt = datetime.combine(sel_date, e)
    for _, r in bookings.iterrows():
        bs = datetime.combine(sel_date, datetime.strptime(r['Kezdés'], '%H:%M').time())
        be = bs + timedelta(minutes=int(r['Időtartam (perc)']))
        if sdt < be and bs < edt:
            return True
    return False

def get_free_slots(duration):
    slots = []
    cur = datetime.combine(sel_date, START_TIME)
    lunch = False
    today = df[df['Dátum'] == sel_date]
    while cur.time() <= (datetime.combine(sel_date, END_TIME) - timedelta(minutes=duration)).time():
        if not lunch and LUNCH_START <= cur.time() < LUNCH_END:
            cur += LUNCH_DUR; lunch = True; continue
        nxt = cur + timedelta(minutes=duration)
        if not overlaps(cur.time(), nxt.time(), today):
            slots.append((cur.time(), nxt.time()))
        cur += timedelta(minutes=duration + BREAK_MIN)
    return slots

# ---- Views ----
if st.session_state.role == 'rider':
    st.subheader(f"Üdv, {st.session_state.user}!")
    dur = st.selectbox("Időtartam (perc)", [30,60,90])
    slots = get_free_slots(dur)
    if not slots:
        st.info("Nincsenek szabad időpontok.")
    for s, e in slots:
        if st.button(f"Foglal {s.strftime('%H:%M')}-{e.strftime('%H:%M')}"):
            new = {'Dátum': sel_date, 'Gyermek(ek) neve': st.session_state.user,
                   'Lovak':'','Kezdés':s.strftime('%H:%M'),'Időtartam (perc)':dur,
                   'Fő':1,'Ismétlődik':False,'RepeatGroupID':'','Megjegyzés':''}
            df2 = pd.concat([df, pd.DataFrame([new])], ignore_index=True)
            save_df(df2, ws)
            st.success("Foglalás sikeres!")

elif st.session_state.role == 'admin':
    st.subheader("Admin felület")
    menu = st.radio("Menü", ['Foglalások','Lovak','Statisztika','Felhasználók'])
    if menu == 'Foglalások':
        week = df['Dátum'].apply(lambda d:d.isocalendar()[1]).max()
        wk = df[df['Dátum'].apply(lambda d:d.isocalendar()[1])==week]
        if wk.empty: st.info("Nincsenek foglalások ezen a héten.")
        for idx,row in wk.iterrows():
            st.write(f"{row['Dátum']} {row['Kezdés']} – {row['Gyermek(ek) neve']}")
            c1,c2=st.columns(2)
            if c1.button('Törlés',key=f'd{idx}'):
                df2=df.drop(idx); save_df(df2,ws); st.rerun()
            if c2.button('Csúsztat',key=f'm{idx}'):
                nt=st.time_input('Új kezdés',value=datetime.strptime(row['Kezdés'],'%H:%M').time())
                df.at[idx,'Kezdés']=nt.strftime('%H:%M'); save_df(df,ws); st.rerun()
    elif menu=='Lovak': st.write("Lovak funkció..." )
    elif menu=='Statisztika':
        st.write(df['Gyermek(ek) neve'].value_counts())
    else:
        users,uw=get_users_df(); st.dataframe(users)
        nu=st.text_input('Új user'); npw=st.text_input('Új pwd',type='password')
        if st.button('Hozzáad'): users2=pd.concat([users,pd.DataFrame([{'username':nu,'password':npw}])],ignore_index=True); save_users(users2,uw); st.rerun()
    if st.button('Kijelentkezés'): st.session_state.clear(); st.rerun()
