import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import os
import uuid

# --- Nemzetközi szótár ---
LANGS = {
    "hu": {
        "lang": "🇭🇺 Magyar",
        "delete": "❌ Törlés",
        "edit_horses": "🐴 Lovak",
        "save_horses": "Lovak mentése",
        "shift": "Csúsztat",
        "shifted": "Átcsúsztatva!",
        "horses_saved": "Lovak mentve!",
        "dragdrop_title": "🕑 Drag & Drop idővonal (demo)",
        "help": "Foglalásokat *drag & drop* módon szerkeszteni csak bővítménnyel lehet (pl. [streamlit-timeline](https://github.com/tylerjrichards/streamlit-timeline)) – itt most csak szemléltető listát látsz.",
        "export": "📁 Exportálás Excel-be",
        "exported": "Exportálva:",
        "stats": "📊 Statisztikák",
        "top10": "**Top 10 név:**",
        "horse_usage": "**Lovak kihasználtsága:**",
        "ics_dl": "ICS naptár export",
        "ics_ready": "ICS naptár letöltés kész!",
        "theme": "🌙 Dark mód",
        "select_lang": "Nyelv: ",
    },
    "en": {
        "lang": "🇬🇧 English",
        "delete": "❌ Delete",
        "edit_horses": "🐴 Horses",
        "save_horses": "Save horses",
        "shift": "Shift",
        "shifted": "Shifted!",
        "horses_saved": "Horses saved!",
        "dragdrop_title": "🕑 Drag & Drop timeline (demo)",
        "help": "*Drag & drop* editing only with plugins (see [streamlit-timeline](https://github.com/tylerjrichards/streamlit-timeline)). This is a static preview.",
        "export": "📁 Export to Excel",
        "exported": "Exported:",
        "stats": "📊 Statistics",
        "top10": "**Top 10 names:**",
        "horse_usage": "**Horse utilization:**",
        "ics_dl": "ICS calendar export",
        "ics_ready": "ICS download ready!",
        "theme": "🌙 Dark mode",
        "select_lang": "Language: ",
    }
}

def _(txt):
    lang = st.session_state.get("lang", "hu")
    return LANGS[lang].get(txt, txt)

# --- Nyelvválasztó + dark mód kapcsoló ---
st.sidebar.write("---")
col1, col2 = st.sidebar.columns([1,1])
if "lang" not in st.session_state:
    st.session_state["lang"] = "hu"
with col1:
    st.session_state["lang"] = st.selectbox(
        _( "select_lang"), [k for k in LANGS], format_func=lambda k: LANGS[k]["lang"], key="LANG")
with col2:
    dark = st.checkbox(_( "theme"), value=False)
    if dark:
        st.markdown("""<style>body, .stApp {background:#17191c;color:#eee;} .stButton>button{background:#444;color:#fff;}</style>""", unsafe_allow_html=True)

# --- Alapbeállítások ---
START_TIME = time(9, 0)
END_TIME   = time(20, 30)
BREAK_MINUTES = 10
MAX_CHILDREN_PER_SLOT = 7
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = time(12, 0)
LUNCH_WINDOW_END   = time(14, 0)
HORSES = ["Eni", "Vera", "Lord", "Pinty", "Szerencse lovag", "Herceg"]
FILE_NAME      = "heti_foglalasok.xlsx"
ADMIN_PASSWORD = "almakaki"

st.set_page_config(page_title="Lovarda Foglalás", layout="centered")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

st.sidebar.title("🔐 Admin belépés")
if not st.session_state["authenticated"]:
    pwd = st.sidebar.text_input("Jelszó", type="password")
    if st.sidebar.button("Bejelentkezés"):
        if pwd == ADMIN_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.sidebar.error("❌ Hibás jelszó.")
else:
    st.sidebar.success("✅ Admin módban")
    if st.sidebar.button("Kijelentkezés"):
        st.session_state["authenticated"] = False
        st.rerun()
    BREAK_MINUTES = st.sidebar.number_input(
        "Szünet (perc)", min_value=0, max_value=60, value=BREAK_MINUTES
    )

st.title("🐴 Lovarda Időpontfoglaló")

selected_date = st.date_input("📅 Válaszd ki a napot")
weekday = selected_date.weekday()
month   = selected_date.month

invalid = False; msg = ""
if month == 7 and weekday not in [0,1]:
    invalid = True; msg = "❌ Júliusban csak hétfőn és kedden lehet foglalni."
elif month == 8:
    if selected_date < date(2025,8,5):
        invalid = True; msg = "❌ Augusztus 1–4. között nem lehet foglalni."
    elif weekday == 0:
        invalid = True; msg = "❌ Augusztusban hétfőn nem lehet foglalni."

if invalid and not st.session_state["authenticated"]:
    st.warning(msg)
    st.stop()

if os.path.exists(FILE_NAME):
    df = pd.read_excel(FILE_NAME)
else:
    df = pd.DataFrame(columns=[
        "Dátum","Gyermek(ek) neve","Lovak",
        "Kezdés","Időtartam (perc)","Fő",
        "Ismétlődik","RepeatGroupID"
    ])
if "RepeatGroupID" not in df.columns:
    df["RepeatGroupID"] = ""

def slot_overlapping(start_time, end_time, on_date, bookings_df):
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
    slots = []
    current = datetime.combine(on_date, START_TIME)
    lunch_done = False
    today = on_date.strftime("%Y-%m-%d")
    day_bookings = bookings_df[bookings_df["Dátum"] == today]

    while current.time() <= (datetime.combine(on_date, END_TIME)
                             - timedelta(minutes=duration)).time():
        if (not lunch_done and 
            LUNCH_WINDOW_START <= current.time() < LUNCH_WINDOW_END):
            current += LUNCH_BREAK_DURATION
            lunch_done = True
            continue

        slot_start = current
        slot_end = current + timedelta(minutes=duration)

        if not slot_overlapping(slot_start, slot_end, on_date, day_bookings):
            slots.append((slot_start.time(), slot_end.time(), duration))

        current += timedelta(minutes=duration + BREAK_MINUTES)

    return slots

# --- Vendég-felület ---
if not st.session_state["authenticated"]:
    st.subheader("➕ Foglalás")

    # Élő foglalható időpontok a kiválasztott időtartamhoz
    ido = st.selectbox("Időtartam", [30, 60, 90], key="foglalas_idotartam")
    szlots  = get_free_slots_exclusive(ido, selected_date, df)
    st.markdown("**Elérhető időpontok:**")
    if szlots:
        st.info(", ".join([
            f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')} ({s[2]}p)"
            for s in szlots
        ]))
    else:
        st.warning("Nincs szabad időpont ma ezzel az időtartammal.")

    with st.form("foglalas_form"):
        nev     = st.text_input("Gyermek(ek) neve")
        letszam = st.number_input("Fő", 1, MAX_CHILDREN_PER_SLOT, 1)
        opts    = [
            f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')} ({s[2]}p)"
            for s in szlots
        ]
        v       = st.selectbox("Időpont", opts if opts else ["Nincs időpont"], key="ido_opts")
        ism     = st.checkbox("Heti ismétlődés aug.")
        if st.form_submit_button("Mentés") and v != "Nincs időpont":
            idx = opts.index(v)
            start, end, _ = szlots[idx]
            if slot_overlapping(start, end, selected_date,
                                df[df["Dátum"] == selected_date.strftime("%Y-%m-%d")]):
                st.error("Erre az időpontra már van foglalás!")
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
                st.success("Foglalás elmentve!")

    # ICS letöltés generálása (ics string)
    def make_ics(df, for_date):
        from ics import Calendar, Event
        c = Calendar()
        for _, row in df[df["Dátum"]==for_date.strftime("%Y-%m-%d")].iterrows():
            e = Event()
            stime = datetime.combine(for_date, datetime.strptime(row["Kezdés"], "%H:%M").time())
            e.name = row["Gyermek(ek) neve"]
            e.begin = stime
            e.duration = {"minutes": int(row["Időtartam (perc)"])}
            e.description = f"Ló: {row['Lovak']}"
            c.events.add(e)
        return str(c)
    if st.button(_( "ics_dl")):
        try:
            import ics
            ics_txt = make_ics(df, selected_date)
            st.download_button("Letöltés .ics", ics_txt, file_name=f"lovarda_{selected_date}.ics")
            st.success(_( "ics_ready"))
        except ImportError:
            st.error("Az ics csomagot pip install ics -el tedd fel!")

# --- Admin-felület ---
if st.session_state["authenticated"]:
    df["Dátum"] = pd.to_datetime(df["Dátum"])
    df["Hét"]   = df["Dátum"].dt.isocalendar().week

    YEAR = selected_date.year
    weeks = sorted(df["Hét"].unique())
    week_ranges = []
    for w in weeks:
        tue = date.fromisocalendar(YEAR, w, 2)
        sun = date.fromisocalendar(YEAR, w, 7)
        month_name = tue.strftime("%B")
        label = (
            f"{tue.strftime('%Y.%m.%d')} – {sun.strftime('%Y.%m.%d')} ({month_name})"
        )
        week_ranges.append((w, label))

    labels = [lbl for _, lbl in week_ranges]
    sel_label = st.selectbox(
        "🔍 Válassz hetet (kedd–vasárnap)", labels,
        index=len(labels)-1 if labels else 0
    )
    sel_week = [w for w, lbl in week_ranges if lbl == sel_label][0]

    week_df = (
        df[df["Hét"] == sel_week]
        .sort_values(by=["Dátum", "Kezdés"])
        .reset_index(drop=True)
    )

    st.write(f"Foglalások: {sel_label}")
    for idx, row in week_df.iterrows():
        d = row["Dátum"].strftime("%Y-%m-%d")
        st.markdown(
            f"**{d} {row['Kezdés']}** – {row['Gyermek(ek) neve']} – "
            f"{row['Időtartam (perc)']}p – {row['Fő']} fő – "
            f"Lovak: {row['Lovak'] or 'nincs'}"
        )
        c1, c2, c3 = st.columns([1,1,2])
        with c1:
            if st.button(_( "delete"), key=f"del_{idx}"):
                df = df.drop(idx)
                df.to_excel(FILE_NAME, index=False)
                st.success("Törölve!")
                st.rerun()
        with c2:
            if st.button(_( "edit_horses"), key=f"lo_{idx}"):
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
                "Új kezdés", opts2, index=current_index,
                key=f"cs_select_{idx}"
            )
            if st.button(_( "shift"), key=f"cs_button_{idx}"):
                df.at[idx, "Kezdés"] = new_start
                df.to_excel(FILE_NAME, index=False)
                st.success(_( "shifted"))
                st.rerun()

    # --- Lovak hozzárendelése ---
    if "mod" in st.session_state:
        m   = st.session_state["mod"]
        row = df.loc[m]
        st.info(f"{row['Dátum'].strftime('%Y-%m-%d')} {row['Kezdés']} – {row['Gyermek(ek) neve']}")
        cur = [h for h in str(row["Lovak"]).split(",") if h.strip() in HORSES]
        nh  = st.multiselect(_( "edit_horses"), HORSES, default=cur)
        if st.button(_( "save_horses"), key="mentlov"):
            df.at[m, "Lovak"] = ", ".join(nh)
            df.to_excel(FILE_NAME, index=False)
            del st.session_state["mod"]
            st.success(_( "horses_saved"))
            st.rerun()

    # --- Idővonalas Drag & Drop Szerkesztés ---
    with st.expander(_( "dragdrop_title"), expanded=False):
        st.markdown("**DEMO timeline (drag & drop):** Sorrendbe rendezett foglalások – szerkesztéshez válassz ki egyet a listából fent!")
        for idx, row in week_df.iterrows():
            st.progress((idx + 1) / len(week_df))
            st.write(
                f"{row['Dátum'].strftime('%a %H:%M')} - {row['Gyermek(ek) neve']} "
                f"({row['Kezdés']} - {int(row['Időtartam (perc)'])+int(row['Kezdés'][:2])*60} perc)"
            )
        st.info(_( "help"))

    # --- Excel export ---
    if st.button(_( "export")):
        fn = f"foglalasok_{sel_label.split()[0]}.xlsx"
        week_df.to_excel(fn, index=False)
        st.success(f"{_( 'exported')} {fn}")

    # --- Statisztikák ---
    with st.expander(_( "stats"), expanded=False):
        st.bar_chart(week_df.groupby("Dátum")["Fő"].sum())
        st.write(_( "top10"))
        st.dataframe(df["Gyermek(ek) neve"].value_counts().head(10))
        st.write(_( "horse_usage"))
        lo_list = (
            df["Lovak"]
            .fillna("")
            .astype(str)
            .str.split(",")
            .explode()
            .str.strip()
        )
        st.dataframe(lo_list[lo_list!=""].value_counts())
