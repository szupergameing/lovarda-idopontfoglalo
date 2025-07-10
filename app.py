import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import uuid
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe

# ---- Google Sheets setup ----
GOOGLE_SHEET_ID = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7FVRzz7TTGRKrSCy6Uo"
GOOGLE_JSON = "mystic-fountain-300911-9b2c042063fa.json"

def get_gsheet_df():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.sheet1
    df = get_as_dataframe(ws, evaluate_formulas=True).dropna(how="all")
    if not df.empty and "Dátum" in df.columns:
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
    ws = sh.get_worksheet(1)  # users sheet
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

# ---- Configuration ----
START_TIME = time(9,0)
END_TIME = time(20,30)
BREAK_MIN = 10
LUNCH_START = time(12,0)
LUNCH_END = time(14,0)
LUNCH_DUR = timedelta(minutes=45)
HORSES = ["Eni","Vera","Lord","Pinty","Szerencse lovag","Herceg"]
ADMIN_PW = "almakaki"

# ---- Session state init ----
for var in ["role","auth","user"]:
    if var not in st.session_state:
        st.session_state[var] = None

# ---- Global dark theme ----
st.markdown(
    "<style>body{background:#181818;color:#f5f5f5;}\n" +
    ".stButton>button{color:#000;} .stSelectbox>div>div{color:#000;} .stTextInput>div>div>input{background:#fff;color:#000;}</style>",
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
        st.experimental_rerun()
    if c2.button("Admin"):
        st.session_state.role = "admin"
        st.experimental_rerun()
    st.stop()

# ---- Authentication ----nif not st.session_state.auth:
    users_df, users_ws = get_users_df()
    if st.session_state.role == "rider":
        st.subheader("Lovas bejelentkezés")
        uname = st.text_input("Felhasználónév", key="uname")
        pwd = st.text_input("Jelszó", type="password", key="upwd")
        if st.button("Bejelentkezés"):
            if ((users_df['username']==uname)&(users_df['password']==pwd)).any():
                st.session_state.auth = True
                st.session_state.user = uname
                st.experimental_rerun()
            else:
                st.error("Hibás felhasználónév vagy jelszó.")
    else:
        st.subheader("Admin bejelentkezés")
        pwd = st.text_input("Jelszó", type="password", key="apwd")
        if st.button("Bejelentkezés"):
            if pwd==ADMIN_PW:
                st.session_state.auth = True
                st.experimental_rerun()
            else:
                st.error("Hibás admin jelszó.")
    st.stop()

# ---- Date picker & restrictions ----
sel_date = st.date_input("Dátum kiválasztása")
wd, mo = sel_date.weekday(), sel_date.month
if mo==7 and wd not in [0,1]: st.warning("Júliusban csak hétfő, kedd")
elif mo==8 and (sel_date<date(2025,8,5) or wd==0): st.warning("Augusztus tiltott nap")

# ---- Load bookings ----
df, ws = get_gsheet_df()

# ---- Slot helpers ----ndef overlaps(s,e,bookings):
    sdt=datetime.combine(sel_date,s)
    edt=datetime.combine(sel_date,e)
    for _,r in bookings.iterrows():
        bs=datetime.combine(sel_date,datetime.strptime(r['Kezdés'],'%H:%M').time())
        be=bs+timedelta(minutes=int(r['Időtartam (perc)']))
        if sdt<be and bs<edt: return True
    return False


def free_slots(dur):
    slots=[]; cur=datetime.combine(sel_date,START_TIME); lunch=False
    today=df[df['Dátum']==sel_date]
    while cur.time()<=(datetime.combine(sel_date,END_TIME)-timedelta(minutes=dur)).time():
        if not lunch and LUNCH_START<=cur.time()<LUNCH_END:
            cur+=LUNCH_DUR; lunch=True; continue
        nxt=cur+timedelta(minutes=dur)
        if not overlaps(cur.time(),nxt.time(),today):
            slots.append((cur.time(),nxt.time()))
        cur+=timedelta(minutes=dur+BREAK_MIN)
    return slots

# ---- Rider view ----nif st.session_state.role=='rider':
    st.subheader(f"Üdv, {st.session_state.user}!")
    dur=st.selectbox("Időtartam (perc)",[30,60,90])
    slots=free_slots(dur)
    for s,e in slots:
        if st.button(f"Foglalok {s.strftime('%H:%M')}-{e.strftime('%H:%M')}"):
            new={{'Dátum':sel_date,'Gyermek(ek) neve':st.session_state.user,'Lovak':'',
                  'Kezdés':s.strftime('%H:%M'),'Időtartam (perc)':dur,'Fő':1,
                  'Ismétlődik':False,'RepeatGroupID':'','Megjegyzés':''}}
            df2=pd.concat([df,pd.DataFrame([new])],ignore_index=True)
            save_df(df2,ws)
            st.success("Foglalás sikeres!")

# ---- Admin view ----nelif st.session_state.role=='admin':
    st.subheader("Admin felület")
    menu=st.radio("Menü",['Foglalások','Lovak','Statisztika','Felhasználók'])

    if menu=='Foglalások':
        week=df['Dátum'].dt.isocalendar().week.unique()[0]
        wk=df[df['Dátum'].dt.isocalendar().week==week]
        for idx,row in wk.iterrows():
            st.write(row['Dátum'],row['Kezdés'],row['Gyermek(ek) neve'])
            c1,c2=st.columns(2)
            if c1.button('Törlés',key=f'd{idx}'):
                df.drop(idx,inplace=True); save_df(df,ws); st.experimental_rerun()
            if c2.button('Csúsztat',key=f'm{idx}'):
                new=st.time_input('Új kezdés',value=datetime.strptime(row['Kezdés'],'%H:%M').time())
                df.at[idx,'Kezdés']=new.strftime('%H:%M'); save_df(df,ws); st.experimental_rerun()

    if menu=='Lovak':
        st.write("Lovak hozzárendelése TBD")

    if menu=='Statisztika':
        st.write(df['Gyermek(ek) neve'].value_counts())

    if menu=='Felhasználók':
        users, uw=get_users_df()
        st.dataframe(users)
        nu=st.text_input('Új user')
        npw=st.text_input('Új jelszó')
        if st.button('Hozzáadás'):
            users2=pd.concat([users,pd.DataFrame([{'username':nu,'password':npw}])],ignore_index=True)
            save_users(users2,uw); st.experimental_rerun()

    if st.button('Kijelentkezés'):
        for var in ['role','auth','user']: st.session_state[var]=None
        st.experimental_rerun()
