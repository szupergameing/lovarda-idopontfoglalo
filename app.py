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
GOOGLE_JSON = "/etc/secrets/mystic-fountain-300911-9b2c042063fa.json"


def get_gsheet_df():
    gc = gspread.service_account(filename=GOOGLE_JSON)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    ws = sh.sheet1
    df = get_as_dataframe(ws, evaluate_formulas=True)
    df = df.dropna(how="all")  # üres sorok törlése
    if not df.empty and "Dátum" in df.columns:
        df["Dátum"] = df["Dátum"].astype(str)
    else:
        df = pd.DataFrame(columns=[
            "Dátum", "Gyermek(ek) neve", "Lovak", "Kezdés",
            "Időtartam (perc)", "Fő", "Ismétlődik", "RepeatGroupID", "Megjegyzés"
        ])
    return df, ws

def save_gsheet_df(df, ws):
    keep = ["Dátum", "Gyermek(ek) neve", "Lovak", "Kezdés", "Időtartam (perc)", "Fő", "Ismétlődik", "RepeatGroupID", "Megjegyzés"]
    set_with_dataframe(ws, df[keep], include_index=False)

# ---- Alapbeállítások ----
START_TIME = time(9, 0)
END_TIME   = time(20, 30)
DEFAULT_BREAK_MINUTES = 10
MAX_CHILDREN_PER_SLOT = 7
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = time(12, 0)
LUNCH_WINDOW_END   = time(14, 0)
HORSES = ["Eni", "Vera", "Lord", "Pinty", "Szerencse lovag", "Herceg"]
ADMIN_PASSWORD = "almakaki"

# ---- Nyelvi szótárak ----
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
        "export": "📁 Exportálás Excel-be",
        "ics_dl": "📅 Letöltés naptár (.ics)",
        "logout": "Kijelentkezés",
        "login": "Bejelentkezés",
        "incorrect_pw": "❌ Hibás jelszó.",
        "stats": "📊 Statisztikák",
        "lovak_saved": "Lovak mentve!",
        "saved": "Foglalás elmentve!",
        "deleted": "Törölve!",
        "no_ics": "Az .ics exporthoz telepítsd az 'ics' csomagot!",
        "exported": "Exportálva: ",
        "warn_july": "❌ Júliusban csak hétfőn és kedden lehet foglalni.",
        "warn_aug": "❌ Augusztus 1–4. között nem lehet foglalni.",
        "warn_aug2": "❌ Augusztusban hétfőn nem lehet foglalni.",
        "already_booked": "Erre az időpontra már van foglalás!",
        "top10": "**Top 10 név:**",
        "horse_usage": "**Lovak kihasználtsága:**",
        "select_week": "🔍 Válassz hetet (kedd–vasárnap)",
        "note": "Megjegyzés",
        "duplicate_name": "⚠️ Ugyanazzal a névvel már van foglalás egymást követő időpontban!",
        "stat_weekly": "Heti lóhasználat",
        "stat_monthly": "Havi lóhasználat"
    }
}

# ---- Session state: break_minutes ----
if "break_minutes" not in st.session_state:
    st.session_state["break_minutes"] = DEFAULT_BREAK_MINUTES

# ---- Nyelv és Dark Mode választó, oldal tetején! ----
col1, col2 = st.columns([2, 1])
with col1:
    lang = st.selectbox("🌐 Language / Nyelv", ["HU"], key="lang_select")
with col2:
    dark = st.toggle("🌙 Sötét mód / Dark mode", key="darkmode_toggle")
labels = LABELS[lang]

if dark:
    st.markdown(
        """
        <style>
        body, .stApp {background-color: #181818 !important; color: #f5f5f5 !important;}
        .stButton>button, .stSelectbox>div>div {color:#000;}
        .stCheckbox>label {color: #f5f5f5 !important;}
        </style>
        """,
        unsafe_allow_html=True
    )

st.title(labels["title"])

# ---- Admin autentikáció ----
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

st.sidebar.title("🔐 Admin belépés")
if not st.session_state["authenticated"]:
    pwd = st.sidebar.text_input("Jelszó", type="password")
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
        "Szünet (perc)", min_value=0, max_value=60, value=st.session_state["break_minutes"]
    )

# ---- Dátumválasztó és korlátozások ----
selected_date = st.date_input("📅 " + labels["slot"])
weekday = selected_date.weekday()
month   = selected_date.month

invalid = False; msg = ""
if month == 7 and weekday not in [0,1]:
    invalid = True; msg = labels["warn_july"]
elif month == 8:
    if selected_date < date(2025,8,5):
        invalid = True; msg = labels["warn_aug"]
    elif weekday == 0:
        invalid = True; msg = labels["warn_aug2"]

if invalid and not st.session_state["authenticated"]:
    st.warning(msg)
    st.stop()

# ---- Foglalások betöltése ----
df, ws = get_gsheet_df()
for col in ["RepeatGroupID", "Megjegyzés"]:
    if col not in df.columns:
        df[col] = ""

# ---- Segédfüggvények ----
def slot_overlapping(start_time, end_time, on_date, bookings_df, ignore_idx=None, allow_admin=False):
    if isinstance(start_time, time):
        start_dt = datetime.combine(on_date, start_time)
    else:
        start_dt = start_time
    if isinstance(end_time, time):
        end_dt = datetime.combine(on_date, end_time)
    else:
        end_dt = end_time
    for idx, row in bookings_df.iterrows():
        if ignore_idx is not None and idx == ignore_idx and allow_admin:
            continue
        b_start = datetime.combine(
            on_date,
            datetime.strptime(row["Kezdés"], "%H:%M").time()
        )
        b_end = b_start + timedelta(minutes=int(row["Időtartam (perc)"]))
        if start_dt < b_end and b_start < end_dt:
            return True
    return False

def get_free_slots_exclusive(duration, on_date, bookings_df):
    slots = []
    current = datetime.combine(on_date, START_TIME)
    lunch_done = False
    today = on_date.strftime("%Y-%m-%d")
    day_bookings = bookings_df[bookings_df["Dátum"] == today]
    break_minutes = st.session_state.get("break_minutes", DEFAULT_BREAK_MINUTES)
    while current.time() <= (datetime.combine(on_date, END_TIME)
                             - timedelta(minutes=duration)).time():
        if (not lunch_done and
            LUNCH_WINDOW_START <= current.time() < LUNCH_WINDOW_END):
            current += LUNCH_BREAK_DURATION
            lunch_done = True
            continue
        slot_start = current
        slot_end = current + timedelta(minutes=duration)
        overlap = False
        for _, row in day_bookings.iterrows():
            b_start = datetime.combine(on_date, datetime.strptime(row["Kezdés"], "%H:%M").time())
            b_end = b_start + timedelta(minutes=int(row["Időtartam (perc)"]))
            if slot_start < b_end and b_start < slot_end:
                overlap = True
                break
        if not overlap:
            slots.append((slot_start.time(), slot_end.time(), duration))
        current += timedelta(minutes=duration + break_minutes)
    return slots

def has_duplicate_name(df, name, selected_date, start, end):
    rows = df[df["Dátum"] == selected_date.strftime("%Y-%m-%d")]
    for _, row in rows.iterrows():
        if row["Gyermek(ek) neve"] == name:
            r_start = datetime.combine(selected_date, datetime.strptime(row["Kezdés"], "%H:%M").time())
            r_end = r_start + timedelta(minutes=int(row["Időtartam (perc)"]))
            if (r_end == start or r_start == end or (start < r_end and r_start < end)):
                return True
    return False

# ---- Vendég-felület ----
if not st.session_state["authenticated"]:
    st.subheader(labels["reserve"])
    slot_duration = st.selectbox(labels["duration"], [30, 60, 90], key="ido_select_guest")
    szlots  = get_free_slots_exclusive(slot_duration, selected_date, df)
    opts    = [
        f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')} ({s[2]}p)"
        for s in szlots
    ]
    with st.form("foglalas_form"):
        nev     = st.text_input(labels["name"])
        letszam = st.number_input(labels["count"], 1, MAX_CHILDREN_PER_SLOT, 1)
        megj    = st.text_input(labels["note"])
        v       = st.selectbox(labels["slot"], opts if opts else ["Nincs időpont"], key="ido_opcio_guest")
        ism     = st.checkbox(labels["repeat"])
        if st.form_submit_button(labels["save"]) and v != "Nincs időpont":
            idx = opts.index(v)
            start, end, _ = szlots[idx]
            start_dt = datetime.combine(selected_date, start)
            end_dt = datetime.combine(selected_date, end)
            if has_duplicate_name(df, nev, selected_date, start_dt, end_dt):
                st.warning(labels["duplicate_name"])
            if slot_overlapping(start, end, selected_date, df[df["Dátum"] == selected_date.strftime("%Y-%m-%d")]):
                st.error(labels["already_booked"])
            else:
                rg = str(uuid.uuid4()) if ism else ""
                dates = [selected_date]
                if ism:
                    nd = selected_date + timedelta(weeks=1)
                    while nd.month == 8:
                        dates.append(nd)
                        nd += timedelta(weeks=1)
                rows = []
                for d in dates:
                    rows.append({
                        "Dátum": d.strftime("%Y-%m-%d"),
                        "Gyermek(ek) neve": nev,
                        "Lovak": "",
                        "Kezdés": start.strftime("%H:%M"),
                        "Időtartam (perc)": slot_duration,
                        "Fő": letszam,
                        "Ismétlődik": ism,
                        "RepeatGroupID": rg,
                        "Megjegyzés": megj
                    })
                df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
                save_gsheet_df(df, ws)
                st.success(labels["saved"])
                st.rerun()
    st.subheader(labels["available_slots"])
    if szlots:
        for s in szlots:
            st.write(f"{s[0].strftime('%H:%M')} – {s[1].strftime('%H:%M')} ({s[2]}p)")
    else:
        st.info(labels["no_slots"])

# ---- Admin-felület ----
if st.session_state["authenticated"]:
    st.subheader(labels["admin_panel"])
    df["Dátum"] = pd.to_datetime(df["Dátum"])
    df["Hét"] = df["Dátum"].dt.isocalendar().week
    df["Hónap"] = df["Dátum"].dt.month

    year = selected_date.year
    weeks = sorted(df["Hét"].unique())
    week_ranges = []
    for w in weeks:
        try:
            tue = date.fromisocalendar(year, w, 2)
            sun = date.fromisocalendar(year, w, 7)
            month_name = tue.strftime("%B")
            label = f"{tue.strftime('%Y.%m.%d')} – {sun.strftime('%Y.%m.%d')} ({month_name})"
            week_ranges.append((w, label))
        except Exception:
            continue
    if not week_ranges:
        st.info("Nincs foglalás, ezért nincs heti nézet.")
        sel_week = None
        week_df = pd.DataFrame()
        week_labels = []
        sel_label = None
    else:
        week_labels = [lbl for _, lbl in week_ranges]
        sel_label = st.selectbox(labels["select_week"], week_labels, index=len(week_labels)-1)
        week_idx_list = [w for w, lbl in week_ranges if lbl == sel_label]
        sel_week = week_idx_list[0] if week_idx_list else weeks[0]
        week_df = (
            df[df["Hét"] == sel_week]
            .sort_values(by=["Dátum", "Kezdés"])
            .reset_index(drop=True)
        )

    if not week_ranges or week_df.empty:
        st.warning("Nincs foglalás ezen a héten.")
    else:
        st.write(f"Foglalások: {sel_label}")
        for idx, row in week_df.iterrows():
            d = row["Dátum"].strftime("%Y-%m-%d")
            st.markdown(
                f"**{d} {row['Kezdés']}** – {row['Gyermek(ek) neve']} – "
                f"{row['Időtartam (perc)']}p – {row['Fő']} fő – "
                f"Lovak: {row['Lovak'] or 'nincs'}<br>"
                f"<i>{labels['note']}: {row['Megjegyzés']}</i>",
                unsafe_allow_html=True
            )
            c1, c2, c3 = st.columns([1,1,2])
            with c1:
                if st.button(labels["delete"], key=f"del_{idx}"):
                    df = df.drop(idx)
                    save_gsheet_df(df, ws)
                    st.success(labels["deleted"])
                    st.rerun()
            with c2:
                if st.button(labels["horses"], key=f"lo_{idx}"):
                    st.session_state["mod"] = idx
            with c3:
                duration = int(row["Időtartam (perc)"])
                times = []
                t = datetime.combine(row["Dátum"].date(), START_TIME)
                end_of_day = datetime.combine(row["Dátum"].date(), END_TIME) - timedelta(minutes=duration)
                while t <= end_of_day:
                    times.append(t.time())
                    t += timedelta(minutes=5)
                opts2 = [tt.strftime("%H:%M") for tt in times]
                current_index = opts2.index(row["Kezdés"]) if row["Kezdés"] in opts2 else 0
                new_start = st.selectbox(labels["move"], opts2, index=current_index, key=f"cs_select_{idx}")
                if st.button(labels["move"], key=f"cs_button_{idx}"):
                    df.at[idx, "Kezdés"] = new_start
                    save_gsheet_df(df, ws)
                    st.success(labels["move_done"])
                    st.rerun()

        # Lovak hozzárendelése, szerkesztés
        if "mod" in st.session_state:
            m   = st.session_state["mod"]
            row = df.loc[m]
            st.info(f"{row['Dátum'].strftime('%Y-%m-%d')} {row['Kezdés']} – {row['Gyermek(ek) neve']}")
            cur = [h for h in str(row["Lovak"]).split(",") if h.strip() in HORSES]
            nh  = st.multiselect("Lovak", HORSES, default=cur)
            megj = st.text_input(labels["note"], value=row.get("Megjegyzés",""))
            if st.button(labels["save"], key="mentlov"):
                df.at[m, "Lovak"] = ", ".join(nh)
                df.at[m, "Megjegyzés"] = megj
                save_gsheet_df(df, ws)
                del st.session_state["mod"]
                st.success(labels["lovak_saved"])
                st.rerun()

        # STATISZTIKA (heti/havi lóhasználat, top10 név, duplikált nevek listája, jegyzetek)
        with st.expander(labels["stats"], expanded=False):
            if not week_df.empty and "Dátum" in week_df.columns:
                st.bar_chart(week_df.groupby("Dátum")["Fő"].sum())
                st.write(labels["top10"])
                st.dataframe(df["Gyermek(ek) neve"].value_counts().head(10))
                st.write(labels["horse_usage"])
                lovak = df["Lovak"].astype(str).fillna("").apply(lambda x: x.split(",") if x else []).explode().str.strip()
                st.dataframe(lovak[lovak!=""].value_counts())
                # Heti stat
                st.write("**"+labels["stat_weekly"]+"**")
                usage_week = df[df["Hét"]==sel_week]["Lovak"].astype(str).fillna("").apply(lambda x: x.split(",") if x else []).explode().str.strip().value_counts()
                st.bar_chart(usage_week)
                # Havi stat
                st.write("**"+labels["stat_monthly"]+"**")
                for m in sorted(df["Hónap"].unique()):
                    usage_month = df[df["Hónap"]==m]["Lovak"].astype(str).fillna("").apply(lambda x: x.split(",") if x else []).explode().str.strip().value_counts()
                    st.write(f"Hónap: {m}")
                    st.bar_chart(usage_month)
                # Duplikált nevek keresése
                dupl_nevek = df["Gyermek(ek) neve"].value_counts()
                st.write("**Duplikált nevek:**")
                st.dataframe(dupl_nevek[dupl_nevek > 1])
                st.write("**Foglalások jegyzetei:**")
                st.dataframe(df[["Gyermek(ek) neve", "Dátum", "Kezdés", "Megjegyzés"]])
            else:
                st.info("Nincs statisztika ehhez a héthez.")
