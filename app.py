import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import uuid
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe

try:
    from ics import Calendar, Event
    ICS_OK = True
except ImportError:
    ICS_OK = False

# ---- Google Sheets setup ----
GOOGLE_SHEET_ID = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7FVRzz7TTGRKrSCy6Uo"
GOOGLE_JSON = "mystic-fountain-300911-9b2c042063fa.json"

def get_gsheet_df():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.sheet1
    df = get_as_dataframe(ws, evaluate_formulas=True)
    df = df.dropna(how="all")
    if not df.empty and "Dátum" in df.columns:
        df["Dátum"] = df["Dátum"].astype(str)
    else:
        df = pd.DataFrame(columns=[
            "Dátum","Gyermek(ek) neve","Lovak","Kezdés",
            "Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"
        ])
    return df, ws


def save_gsheet_df(df, ws):
    keep = ["Dátum","Gyermek(ek) neve","Lovak","Kezdés",
            "Időtartam (perc)","Fő","Ismétlődik","RepeatGroupID","Megjegyzés"]
    ws.clear()
    set_with_dataframe(ws, df[keep], include_index=False)

# ---- Config ----
START_TIME = time(9, 0)
END_TIME = time(20, 30)
DEFAULT_BREAK_MINUTES = 10
MAX_CHILDREN_PER_SLOT = 7
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = time(12, 0)
LUNCH_WINDOW_END = time(14, 0)
HORSES = ["Eni", "Vera", "Lord", "Pinty", "Szerencse lovag", "Herceg"]
ADMIN_PASSWORD = "almakaki"

# ---- Labels ----
LABELS = {
    "HU": {
        "title": "🐴 Lovarda Időpontfoglaló",
        "reserve": "➕ Foglalás",
        "name": "Gyermek(ek) neve",
        "count": "Fő",
        "duration": "Időtartam",
        "slot": "Időpont",
        "repeat": "Heti ismétlődés aug.",
        "save": "Mentés",
        "no_slots": "Nincs szabad időpont ma.",
        "available_slots": "📆 Elérhető időpontok",
        "admin_panel": "🛠️ Admin felület",
        "delete": "❌ Törlés",
        "horses": "🐴 Lovak",
        "move": "Csúsztat",
        "move_done": "Átcsúsztatva admin joggal!",
        "logout": "Kijelentkezés",
        "login": "Bejelentkezés",
        "incorrect_pw": "❌ Hibás jelszó.",
        "already_booked": "Erre az időpontra már van foglalás!",
        "duplicate_name": "⚠️ Ugyanazzal a névvel már van foglalás egymást követő időpontban!",
        "select_week": "🔍 Válassz hetet",
        "note": "Megjegyzés",
        "stats": "📊 Statisztikák",
        "top10": "**Top 10 név:**",
        "horse_usage": "**Lovak kihasználtsága:**",
        "stat_weekly": "Heti lóhasználat",
        "stat_monthly": "Havi lóhasználat"
    }
}

# ---- Session init ----
if "break_minutes" not in st.session_state:
    st.session_state["break_minutes"] = DEFAULT_BREAK_MINUTES
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# ---- Language & Darkmode ----
col_lang, col_dark = st.columns([2,1])
with col_lang:
    lang = st.selectbox("🌐 Nyelv", ["HU"], key="lang")
with col_dark:
    dark = st.toggle("🌙 Dark mode", key="dark")
labels = LABELS[lang]
if dark:
    st.markdown(
        "<style>body, .stApp{background:#181818; color:#f5f5f5;} .stButton>button{color:#000;}</style>",
        unsafe_allow_html=True
    )
st.title(labels["title"])

# ---- Admin auth ----
st.sidebar.title("🔐 Admin belépés")
if not st.session_state["authenticated"]:
    pwd = st.sidebar.text_input(labels["login"], type="password")
    if st.sidebar.button(labels["login"]):
        if pwd == ADMIN_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.sidebar.error(labels["incorrect_pw"])
else:
    st.sidebar.success("✅ Admin")
    if st.sidebar.button(labels["logout"]):
        st.session_state["authenticated"] = False
        st.rerun()
    st.session_state["break_minutes"] = st.sidebar.number_input(
        "Szünet (perc)", 0, 60, st.session_state["break_minutes"]
    )

# ---- Date picker & restrictions ----
selected_date = st.date_input(labels["slot"])
wd = selected_date.weekday()
mo = selected_date.month
invalid = False; msg=""
if mo==7 and wd not in [0,1]: invalid=True; msg="Júliusban csak H-Cs"
elif mo==8:
    if selected_date<date(2025,8,5): invalid=True; msg="Aug 1-4 tiltva"
    elif wd==0: invalid=True; msg="Augusztusban H nem"
if invalid and not st.session_state["authenticated"]:
    st.warning(msg); st.stop()

# ---- Load bookings ----
df, ws = get_gsheet_df()
for c in ["RepeatGroupID","Megjegyzés"]:
    if c not in df.columns: df[c] = ""

# ---- Helpers ----
def slot_overlapping(start,end,on_date,bookings):
    s_dt = datetime.combine(on_date,start) if isinstance(start,time) else start
    e_dt = datetime.combine(on_date,end) if isinstance(end,time) else end
    for _,r in bookings.iterrows():
        b_s = datetime.combine(on_date,datetime.strptime(r["Kezdés"],"%H:%M").time())
        b_e = b_s + timedelta(minutes=int(r["Időtartam (perc)"]))
        if s_dt < b_e and b_s < e_dt:
            return True
    return False

def get_free_slots(duration,on_date,bookings):
    slots=[]
    cur = datetime.combine(on_date,START_TIME)
    lunch=False
    today = on_date.strftime("%Y-%m-%d")
    day = bookings[bookings["Dátum"]==today]
    br = st.session_state["break_minutes"]
    while cur.time() <= (datetime.combine(on_date,END_TIME)-timedelta(minutes=duration)).time():
        if not lunch and LUNCH_WINDOW_START<=cur.time()<LUNCH_WINDOW_END:
            cur+=LUNCH_BREAK_DURATION; lunch=True; continue
        st_end=cur+timedelta(minutes=duration)
        if not slot_overlapping(cur.time(),st_end.time(),on_date,day):
            slots.append((cur.time(),st_end.time(),duration))
        cur+=timedelta(minutes=duration+br)
    return slots

def has_duplicate_name(bookings,name,on_date,s,e):
    rows=bookings[bookings["Dátum"]==on_date.strftime("%Y-%m-%d")]
    for _,r in rows.iterrows():
        if r["Gyermek(ek) neve"]==name:
            rs=datetime.combine(on_date,datetime.strptime(r["Kezdés"],"%H:%M").time())
            re_=rs+timedelta(minutes=int(r["Időtartam (perc)"]))
            if e==rs or s==re_ or (s<re_ and rs<e): return True
    return False

# ---- Guest view ----
if not st.session_state["authenticated"]:
    st.subheader(labels["reserve"])
    dur = st.selectbox(labels["duration"],[30,60,90],key="dur_guest")
    st.info("Ha admin módosított, kattints: 🔄 Frissít")
    if st.button("🔄 Frissít"): st.experimental_rerun()
    # reload before computing
    df_refresh,_=get_gsheet_df()
    slots=get_free_slots(dur,selected_date,df_refresh)
    opts=[f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')} ({s[2]}p)" for s in slots]
    with st.form("form_guest"):
        name=st.text_input(labels["name"])
        cnt =st.number_input(labels["count"],1,MAX_CHILDREN_PER_SLOT,1)
        note=st.text_input(labels["note"])
        choice=st.selectbox(labels["slot"],opts if opts else [labels["no_slots"]])
        rep=st.checkbox(labels["repeat"])
        if st.form_submit_button(labels["save"]) and opts:
            idx=opts.index(choice)
            s,e,_=slots[idx]
            s_dt=datetime.combine(selected_date,s)
            e_dt=datetime.combine(selected_date,e)
            df_cur,_=get_gsheet_df()
            if has_duplicate_name(df_cur,name,selected_date,s_dt,e_dt):
                st.warning(labels["duplicate_name"])
            elif slot_overlapping(s,e,selected_date,df_cur[df_cur["Dátum"]==selected_date.strftime("%Y-%m-%d")]):
                st.error(labels["already_booked"])
            else:
                rg=str(uuid.uuid4()) if rep else ""
                dates=[selected_date]
                if rep:
                    nd=selected_date+timedelta(weeks=1)
                    while nd.month==8:
                        dates.append(nd); nd+=timedelta(weeks=1)
                rows=[{"Dátum":d.strftime("%Y-%m-%d"),"Gyermek(ek) neve":name,
                       "Lovak":"","Kezdés":s.strftime("%H:%M"),
                       "Időtartam (perc)":dur,"Fő":cnt,
                       "Ismétlődik":rep,"RepeatGroupID":rg,
                       "Megjegyzés":note} for d in dates]
                df_new=pd.concat([df_cur,pd.DataFrame(rows)],ignore_index=True)
                save_gsheet_df(df_new,ws)
                st.success(labels["save"])
                st.experimental_rerun()
    st.subheader(labels["available_slots"])
    if not slots: st.info(labels["no_slots"])
    else:
        for s in slots:
            st.write(f"{s[0].strftime('%H:%M')} – {s[1].strftime('%H:%M')} ({s[2]}p)")

# ---- Admin view ----
else:
    st.subheader(labels["admin_panel"])
    # menu on right
    main_col, menu_col = st.columns([4,1])
    with menu_col:
        section = st.radio("Menü", ["Foglalások","Lovak","Statisztika"], index=0)
    # reload bookings
    df_admin,_ = get_gsheet_df()
    df_admin["Dátum"] = pd.to_datetime(df_admin["Dátum"])
    df_admin["Hét"] = df_admin["Dátum"].dt.isocalendar().week
    df_admin["Hónap"] = df_admin["Dátum"].dt.month
    # week select
    weeks = sorted(df_admin["Hét"].unique())
    labels_week=[]
    for w in weeks:
        try:
            tue=date.fromisocalendar(selected_date.year,w,2)
            sun=date.fromisocalendar(selected_date.year,w,7)
            labels_week.append((w,f"{tue.strftime('%Y.%m.%d')} – {sun.strftime('%Y.%m.%d')}"))
        except: pass
    if labels_week:
        sel_lbl = main_col.selectbox(labels["select_week"], [lbl for _,lbl in labels_week])
        sel_w = [w for w,lbl in labels_week if lbl==sel_lbl][0]
        week_df = df_admin[df_admin["Hét"]==sel_w].sort_values(by=["Dátum","Kezdés"])
    else:
        week_df=pd.DataFrame()
    # Foglalások
    if section=="Foglalások":
        if week_df.empty:
            main_col.warning("Nincs foglalás ezen a héten.")
        else:
            main_col.write(f"Foglalások: {sel_lbl}")
            for idx,row in week_df.iterrows():
                d=row["Dátum"].strftime("%Y-%m-%d")
                main_col.markdown(
                    f"**{d} {row['Kezdés']}** – {row['Gyermek(ek) neve']} – "
                    f"{row['Időtartam (perc)']}p – {row['Fő']} fő" , unsafe_allow_html=True)
                c1,c2=main_col.columns([1,1])
                with c1:
                    if st.button(labels["delete"],key=f"del{idx}"):
                        df_admin.drop(idx,inplace=True)
                        save_gsheet_df(df_admin,ws)
                        st.success(labels["delete"])
                        st.experimental_rerun()
                with c2:
                    if st.button(labels["move"],key=f"mv{idx}"):
                        st.session_state['move_idx']=idx
    # Lovak
    elif section=="Lovak":
        if 'move_idx' in st.session_state:
            m=st.session_state['move_idx']
        else:
            main_col.info("Válassz egy foglalást a 'Foglalások' menüben.")
            st.stop()
        row=df_admin.loc[m]
        main_col.info(f"{row['Dátum'].strftime('%Y-%m-%d')} {row['Kezdés']} – {row['Gyermek(ek) neve']}")
        cur=[h for h in str(row['Lovak']).split(',') if h.strip() in HORSES]
        sel=main_col.multiselect(labels['horses'],HORSES, default=cur)
        note_val=main_col.text_input(labels['note'],value=row['Megjegyzés'])
        if main_col.button(labels['save']):
            df_admin.at[m,'Lovak']=','.join(sel)
            df_admin.at[m,'Megjegyzés']=note_val
            save_gsheet_df(df_admin,ws)
            st.success(labels['save'])
            del st.session_state['move_idx']
            st.experimental_rerun()
    # Statisztika
    elif section=="Statisztika":
        if week_df.empty:
            main_col.info("Nincs statisztika.")
        else:
            main_col.write(labels['top10'])
            main_col.dataframe(df_admin['Gyermek(ek) neve'].value_counts().head(10))
            main_col.write(labels['horse_usage'])
            expl = df_admin['Lovak'].astype(str).apply(lambda x: x.split(',') if x else []).explode().str.strip()
            main_col.dataframe(expl[expl!=''].value_counts())
            main_col.write("**"+labels['stat_weekly']+"**")
            weekly=expl[week_df.index].value_counts()
            main_col.bar_chart(weekly)
            main_col.write("**"+labels['stat_monthly']+"**")
            for m in sorted(df_admin['Hónap'].unique()):
                monthly=expl[df_admin[df_admin['Hónap']==m].index].value_counts()
                main_col.write(f"Hónap: {m}")
                main_col.bar_chart(monthly)
                
    # Pályák mozgatása
    if 'move_idx' in st.session_state and section=='Foglalások':
        idx=st.session_state['move_idx']
        row=df_admin.loc[idx]
        duration=int(row['Időtartam (perc)'])
        times=[]
        t0=datetime.combine(row['Dátum'].date(),START_TIME)
        endd=datetime.combine(row['Dátum'].date(),END_TIME)-timedelta(minutes=duration)
        while t0<=endd:
            times.append(t0.time())
            t0+=timedelta(minutes=5)
        opts2=[tt.strftime('%H:%M') for tt in times]
        new=main_col.selectbox(labels['move'],opts2,key=f"mvsel{idx}")
        if main_col.button(labels['save'],key=f"mvsave{idx}"):
            df_admin.at[idx,'Kezdés']=new
            save_gsheet_df(df_admin,ws)
            st.success(labels['move_done'])
            del st.session_state['move_idx']
            st.experimental_rerun()
