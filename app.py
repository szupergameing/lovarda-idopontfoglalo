import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from datetime import datetime

# ---- Google Sheets setup ----
GOOGLE_SHEET_ID = "1xGeEqZ0Y-o7XEIR0mOBvgvTk7FVRzz7TTGRKrSCy6Uo"
GOOGLE_JSON = "/etc/secrets/mystic-fountain-300911-9b2c042063fa.json"

def get_gsheet():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    return sh

def get_users_df():
    sh = get_gsheet()
    ws = sh.worksheet('Felhasznalok')
    df = get_as_dataframe(ws, evaluate_formulas=True)
    df = df.dropna(how="all")
    df = df.fillna("")
    return df, ws

def save_users_df(df, ws):
    set_with_dataframe(ws, df, include_index=False)

def get_foglalasok_df():
    sh = get_gsheet()
    ws = sh.worksheet('Munkalap1')
    df = get_as_dataframe(ws, evaluate_formulas=True)
    df = df.dropna(how="all")
    df = df.fillna("")
    return df, ws

def save_foglalasok_df(df, ws):
    set_with_dataframe(ws, df, include_index=False)

ADMIN_PW = "almakaki"

if "user_mode" not in st.session_state:
    st.session_state.user_mode = None
if "user" not in st.session_state:
    st.session_state.user = None

st.title("🐴 Lovarda Időpontfoglaló")

if st.session_state.user_mode is None:
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Felhasználó"):
            st.session_state.user_mode = "user"
    with col2:
        if st.button("Admin"):
            st.session_state.user_mode = "admin"
    st.stop()

# ---- ADMIN LOGIN ----
if st.session_state.user_mode == "admin":
    st.subheader("Admin belépés")
    admin_pw = st.text_input("Admin jelszó", type="password")
    if st.button("Belépés"):
        if admin_pw == ADMIN_PW:
            st.session_state.user = "admin"
            st.success("Sikeres admin belépés!")
        else:
            st.error("Hibás admin jelszó!")
    if st.session_state.user != "admin":
        st.stop()

# ---- USER LOGIN/REG ----
if st.session_state.user_mode == "user" and not st.session_state.user:
    st.subheader("Felhasználói belépés")
    users_df, users_ws = get_users_df()
    tab1, tab2 = st.tabs(["Bejelentkezés", "Regisztráció"])

    with tab1:
        uname = st.text_input("Felhasználónév")
        pw = st.text_input("Jelszó", type="password")
        if st.button("Bejelentkezés"):
            if uname in users_df["username"].values:
                i = users_df.index[users_df["username"] == uname][0]
                if users_df.at[i, "password"] == pw:
                    st.session_state.user = uname
                    st.success("Sikeres belépés!")
                else:
                    st.error("Hibás jelszó!")
            else:
                st.error("Nincs ilyen felhasználó!")
    with tab2:
        new_uname = st.text_input("Új felhasználónév")
        new_pw = st.text_input("Új jelszó", type="password")
        if st.button("Regisztráció"):
            if new_uname in users_df["username"].values:
                st.error("Ez a felhasználónév már foglalt.")
            elif not new_uname or not new_pw:
                st.error("Adj meg felhasználónevet ÉS jelszót!")
            else:
                users_df = pd.concat([users_df, pd.DataFrame([{"username": new_uname, "password": new_pw}])], ignore_index=True)
                save_users_df(users_df, users_ws)
                st.success("Sikeres regisztráció!")
                st.session_state.user = new_uname
    if not st.session_state.user:
        st.stop()

# ---- Akció-naplózás ----
def log_action(action, who, extra=""):
    sh = get_gsheet()
    try:
        ws = sh.worksheet('Aktivitas')
    except Exception:
        ws = sh.add_worksheet(title='Aktivitas', rows=1000, cols=5)
        ws.append_row(["Idő", "Ki", "Akció", "Részletek"])
    ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), who, action, extra])

st.success(f"Szia, {st.session_state.user}!")

# Foglalási sheet kezelése
df, ws = get_foglalasok_df()
if df.empty or "Dátum" not in df.columns:
    df = pd.DataFrame(columns=["Dátum", "Gyermek(ek) neve", "Lovak", "Kezdés", "Időtartam (perc)", "Fő", "Ismétlődik", "RepeatGroupID", "Megjegyzés"])

st.header("Új foglalás hozzáadása")
datum = st.date_input("Dátum")
nev = st.text_input("Gyermek(ek) neve")
ido = st.text_input("Kezdés (pl. 09:00)")
ido_min = st.number_input("Időtartam (perc)", value=30)
if st.button("Foglalás rögzítése"):
    df = pd.concat([
        df,
        pd.DataFrame([{
            "Dátum": datum.strftime("%Y-%m-%d"),
            "Gyermek(ek) neve": nev,
            "Lovak": "",
            "Kezdés": ido,
            "Időtartam (perc)": ido_min,
            "Fő": 1,
            "Ismétlődik": False,
            "RepeatGroupID": "",
            "Megjegyzés": ""
        }])
    ], ignore_index=True)
    save_foglalasok_df(df, ws)
    log_action("Új foglalás", st.session_state.user, f"{datum} {nev} {ido}")
    st.success("Foglalás rögzítve!")

st.header("Foglalások")
for i, row in df.iterrows():
    st.write(f"{row['Dátum']} {row['Kezdés']} - {row['Gyermek(ek) neve']} [{row['Fő']} fő]")
    if st.session_state.user == "admin" or st.session_state.user == row['Gyermek(ek) neve']:
        if st.button(f"Törlés_{i}", key=f"del_{i}"):
            log_action("Törlés", st.session_state.user, f"{row['Dátum']} {row['Gyermek(ek) neve']}")
            df = df.drop(i)
            save_foglalasok_df(df, ws)
            st.success("Törölve!")
            st.experimental_rerun()
