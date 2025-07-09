import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import os
import uuid
from ics import Calendar, Event
import io

# ========== KONSTANSOK ==========

START_TIME = time(9, 0)
END_TIME = time(20, 30)
BREAK_MINUTES = 10
MAX_CHILDREN_PER_SLOT = 7
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = time(12, 0)
LUNCH_WINDOW_END = time(14, 0)
HORSES = ["Eni", "Vera", "Lord", "Pinty", "Szerencse lovag", "Herceg"]
FILE_NAME = "heti_foglalasok.xlsx"
ADMIN_PASSWORD = "almakaki"

# ========== SESSION, STYLES, NYELV, DARK MODE ==========

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "lang" not in st.session_state:
    st.session_state["lang"] = "HU"
if "darkmode" not in st.session_state:
    st.session_state["darkmode"] = False

st.set_page_config(page_title="Lovarda Foglalás", layout="centered")

# Topbar: nyelv + darkmode
c1, c2 = st.columns([2, 1])
with c1:
    lang = st.radio("Nyelv / Language", ["HU", "EN"], index=0, horizontal=True)
    st.session_state["lang"] = lang
with c2:
    st.session_state["darkmode"] = st.toggle("🌙 Dark mode", value=st.session_state["darkmode"])

# CSS sötét módhoz (csak vizuális, nem minden elemnél tökéletes, de elég jó!)
if st.session_state["darkmode"]:
    st.markdown("""
        <style>
        body, .stApp { background: #17181c !important; color: #f1f1f1 !important; }
        .stButton>button, .stTextInput>div>input { background: #232328; color: #f1f1f1; }
        .stNumberInput input { color: #f1f1f1 !important; background: #232328 !important; }
        </style>
        """, unsafe_allow_html=True)

_ = lambda hu, en: hu if st.session_state["lang"] == "HU" else en

# ========== ADMIN AUTH ==========

st.sidebar.title(_("🔐 Admin belépés", "🔐 Admin login"))
if not st.session_state["authenticated"]:
    pwd = st.sidebar.text_input(_("Jelszó", "Password"), type="password")
    if st.sidebar.button(_("Bejelentkezés", "Login")):
        if pwd == ADMIN_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.sidebar.error(_("❌ Hibás jelszó.", "❌ Wrong password."))
else:
    st.sidebar.success(_("✅ Admin módban", "✅ Admin mode"))
    if st.sidebar.button(_("Kijelentkezés", "Logout")):
        st.session_state["authenticated"] = False
        st.rerun()
    BREAK_MINUTES = st.sidebar.number_input(
        _("Szünet (perc)", "Break (minutes)"), min_value=0, max_value=60, value=BREAK_MINUTES
    )

# ========== CÍM, NAP VÁLASZTÓ, NYÁRI LIMITÁLÁSOK ==========

st.title(_("🐴 Lovarda Időpontfoglaló", "🐴 Horseback Booking"))
selected_date = st.date_input(_("📅 Válaszd ki a napot", "📅 Pick a date"))
weekday = selected_date.weekday()
month = selected_date.month

invalid = False
msg = ""
if month == 7 and weekday not in [0, 1]:
    invalid = True
    msg = _("❌ Júliusban csak hétfőn és kedden lehet foglalni.", "❌ July: only Mondays and Tuesdays are available.")
elif month == 8:
    if selected_date < date(2025, 8, 5):
        invalid = True
        msg = _("❌ Augusztus 1–4. között nem lehet foglalni.", "❌ August 1–4: No bookings allowed.")
    elif weekday == 0:
        invalid = True
        msg = _("❌ Augusztusban hétfőn nem lehet foglalni.", "❌ Mondays in August: No bookings allowed.")

if invalid and not st.session_state["authenticated"]:
    st.warning(msg)
    st.stop()

# ========== FOGLALÁSOK BETÖLTÉSE ==========

if os.path.exists(FILE_NAME):
    df = pd.read_excel(FILE_NAME)
else:
    df = pd.DataFrame(columns=[
        "Dátum", "Gyermek(ek) neve", "Lovak",
        "Kezdés", "Időtartam (perc)", "Fő",
        "Ismétlődik", "RepeatGroupID"
    ])
if "RepeatGroupID" not in df.columns:
    df["RepeatGroupID"] = ""

# ========== FÜGGVÉNYEK ==========

def slot_overlapping(start_time, end_time, on_date, bookings_df):
    """Ellenőrzi az átfedést (bármely kezdő-vég idővel, minden foglalásra)."""
    if isinstance(start_time, time):
        start_dt = datetime.combine(on_date, start_time)
    else:
        start_dt = start_time
    if isinstance(end_time, time):
        end_dt = datetime.combine(on_date, end_time)
    else:
        end_dt = end_time
    for _, row in bookings_df.iterrows():
        b_start = datetime.combine(
            on_date,
            datetime.strptime(row["Kezdés"], "%H:%M").time()
        )
        b_end = b_start + timedelta(minutes=int(row["Időtartam (perc)"]))
        if start_dt < b_end and b_start < end_dt:
            return True
    return False

def get_free_slots_exclusive(duration, on_date, bookings_df):
    """Üres idősávok listája a kiválasztott napra és időtartamra."""
    slots = []
    current = datetime.combine(on_date, START_TIME)
    lunch_done = False
    today = on_date.strftime("%Y-%m-%d")
    day_bookings = bookings_df[bookings_df["Dátum"] == today]
    while current.time() <= (datetime.combine(on_date, END_TIME) - timedelta(minutes=duration)).time():
        if (not lunch_done and LUNCH_WINDOW_START <= current.time() < LUNCH_WINDOW_END):
            current += LUNCH_BREAK_DURATION
            lunch_done = True
            continue
        slot_start = current
        slot_end = current + timedelta(minutes=duration)
        if not slot_overlapping(slot_start, slot_end, on_date, day_bookings):
            slots.append((slot_start.time(), slot_end.time(), duration))
        current += timedelta(minutes=duration + BREAK_MINUTES)
    return slots

def make_ics(nev, dates, start, ido):
    """ICS naptár generálás (több dátumra is)."""
    cal = Calendar()
    for d in dates:
        event = Event()
        event.name = f"Lovis foglalás – {nev}"
        event.begin = datetime.combine(d, start)
        event.duration = timedelta(minutes=ido)
        cal.events.add(event)
    ics_buf = io.BytesIO()
    ics_buf.write(str(cal).encode())
    ics_buf.seek(0)
    return ics_buf

# ========== VENDÉG FELÜLET (FOGLALÁS) ==========

if not st.session_state["authenticated"]:
    st.subheader(_("➕ Foglalás", "➕ Booking"))
    # élő szűrés: időtartam váltásra frissülő slot lista!
    ido = st.selectbox(_("Időtartam", "Duration"), [30, 60, 90], key="user_dur")
    szlots = get_free_slots_exclusive(ido, selected_date, df)
    opts = [
        f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')} ({s[2]}p)"
        for s in szlots
    ]
    # Lenyitható: foglalható időpontok mindig az aktuális ido-ra
    with st.expander(_("📆 Elérhető időpontok", "📆 Available slots")):
        if szlots:
            for s in szlots:
                st.write(f"{s[0].strftime('%H:%M')} – {s[1].strftime('%H:%M')} ({s[2]}p)")
        else:
            st.info(_("Nincs szabad időpont ma.", "No available slots today."))
    with st.form("foglalas_form"):
        nev = st.text_input(_("Gyermek(ek) neve", "Name(s)"))
        letszam = st.number_input(_("Fő", "Persons"), 1, MAX_CHILDREN_PER_SLOT, 1)
        v = st.selectbox(_("Időpont", "Slot"), opts if opts else ["Nincs időpont"], key="slotpick")
        ism = st.checkbox(_("Heti ismétlődés aug.", "Repeat weekly in August"))
        if st.form_submit_button(_("Mentés", "Book")) and v != "Nincs időpont":
            idx = opts.index(v)
            start, end, _ = szlots[idx]
            if slot_overlapping(start, end, selected_date, df[df["Dátum"] == selected_date.strftime("%Y-%m-%d")]):
                st.error(_("Erre az időpontra már van foglalás!", "Slot already booked!"))
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
                        "Időtartam (perc)": ido,
                        "Fő": letszam,
                        "Ismétlődik": ism,
                        "RepeatGroupID": rg
                    })
                df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
                df.to_excel(FILE_NAME, index=False)
                st.success(_("Foglalás elmentve!", "Booking saved!"))
                # ICS LETÖLTÉS
                ics_buf = make_ics(nev, dates, start, ido)
                st.download_button("Letöltés naptárhoz (ICS)", ics_buf, "booking.ics", "text/calendar")
                st.rerun()

# ========== ADMIN FELÜLET ==========

if st.session_state["authenticated"]:
    df["Dátum"] = pd.to_datetime(df["Dátum"])
    df["Hét"] = df["Dátum"].dt.isocalendar().week
    YEAR = selected_date.year
    weeks = sorted(df["Hét"].unique())
    week_ranges = []
    for w in weeks:
        tue = date.fromisocalendar(YEAR, w, 2)
        sun = date.fromisocalendar(YEAR, w, 7)
        month_name = tue.strftime("%B")
        label = f"{tue.strftime('%Y.%m.%d')} – {sun.strftime('%Y.%m.%d')} ({month_name})"
        week_ranges.append((w, label))
    labels = [lbl for _, lbl in week_ranges]
    sel_label = st.selectbox(
        _("🔍 Válassz hetet (kedd–vasárnap)", "🔍 Pick week (Tue–Sun)"), labels,
        index=len(labels)-1 if labels else 0
    )
    sel_week = [w for w, lbl in week_ranges if lbl == sel_label][0]
    week_df = (
        df[df["Hét"] == sel_week]
        .sort_values(by=["Dátum", "Kezdés"])
        .reset_index(drop=True)
    )
    st.write(_("Foglalások:", "Bookings:"), sel_label)
    for idx, row in week_df.iterrows():
        d = row["Dátum"].strftime("%Y-%m-%d")
        st.markdown(
            f"**{d} {row['Kezdés']}** – {row['Gyermek(ek) neve']} – "
            f"{row['Időtartam (perc)']}p – {row['Fő']} fő – "
            f"Lovak: {row['Lovak'] or 'nincs'}"
        )
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            if st.button("❌ Törlés", key=f"del_{idx}"):
                df = df.drop(idx)
                df.to_excel(FILE_NAME, index=False)
                st.success(_("Törölve!", "Deleted!"))
                st.rerun()
        with c2:
            if st.button("🐴 Lovak", key=f"lo_{idx}"):
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
            new_start = st.selectbox(
                _("Új kezdés", "New start"), opts2, index=current_index,
                key=f"cs_select_{idx}"
            )
            if st.button(_("Csúsztat", "Move"), key=f"cs_button_{idx}"):
                df.at[idx, "Kezdés"] = new_start
                df.to_excel(FILE_NAME, index=False)
                st.success(_("Átcsúsztatva!", "Moved!"))
                st.rerun()

    if "mod" in st.session_state:
        m = st.session_state["mod"]
        row = df.loc[m]
        st.info(
            f"{row['Dátum'].strftime('%Y-%m-%d')} {row['Kezdés']} – {row['Gyermek(ek) neve']}"
        )
        cur = [h for h in str(row["Lovak"]).split(",") if h.strip() in HORSES]
        nh = st.multiselect("Lovak", HORSES, default=cur)
        if st.button(_("Mentés lovak", "Save horses"), key="mentlov"):
            df.at[m, "Lovak"] = ", ".join(nh)
            df.to_excel(FILE_NAME, index=False)
            del st.session_state["mod"]
            st.success(_("Lovak mentve!", "Saved!"))
            st.rerun()

    if st.button(_("📁 Exportálás Excel-be", "📁 Export Excel")):
        fn = f"foglalasok_{sel_label.split()[0]}.xlsx"
        week_df.to_excel(fn, index=False)
        st.success(_("Exportálva:", "Exported:") + f" {fn}")

    with st.expander(_("📊 Statisztikák", "📊 Stats"), expanded=False):
        st.bar_chart(week_df.groupby("Dátum")["Fő"].sum())
        st.write("**Top 10 név:**" if st.session_state["lang"]=="HU" else "**Top 10 name:**")
        st.dataframe(df["Gyermek(ek) neve"].value_counts().head(10))
        st.write("**Lovak kihasználtsága:**" if st.session_state["lang"]=="HU" else "**Horse usage:**")
        lo_list = (
            df["Lovak"]
            .fillna("")
            .astype(str)
            .str.split(",")
            .explode()
            .str.strip()
        )
        st.dataframe(lo_list[lo_list!=""].value_counts())

# ========== EXTRA: FEJLESZTÉSI ÖTLETEK (INFO BOX) ==========

with st.expander("🚀 Tipp! Mit lehet még fejleszteni? / Ideas to improve"):
    st.markdown("""
- Drag&drop idővonal adminnak: jelenleg natívan NEM támogatja a Streamlit! Lehet próbálkozni JS/Timeline komponenssel.
- WebSocket (real-time multi-admin): külön backenddel (FastAPI + socket.io) vagy [Streamlit Websocket](https://github.com/streamlit/streamlit-websocket) bridge.
- E-mail/SMS értesítés automatikusan foglalás után.
- Google Calendar, PDF export.
- Felhasználói regisztráció/profil.
- Lovas képek feltöltése.
- ...stb.
""")
