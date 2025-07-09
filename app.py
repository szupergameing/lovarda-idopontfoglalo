import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import uuid

# Alapbeállítások
START_TIME = datetime.strptime("09:00", "%H:%M").time()
END_TIME   = datetime.strptime("20:30", "%H:%M").time()
BREAK_MINUTES = 10
MAX_CHILDREN_PER_SLOT = 7
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = datetime.strptime("12:00", "%H:%M").time()
LUNCH_WINDOW_END   = datetime.strptime("14:00", "%H:%M").time()
HORSES = ["Eni", "Vera", "Lord", "Pinty", "Szerencse lovag", "Herceg"]
FILE_NAME      = "heti_foglalasok.xlsx"
ADMIN_PASSWORD = "almakaki"

st.set_page_config(page_title="Lovarda Foglalás", layout="centered")

# --- Admin authentikáció ---
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
    # Admin override a pihenőidőre
    BREAK_MINUTES = st.sidebar.number_input(
        "Szünet (perc)", min_value=0, max_value=60, value=BREAK_MINUTES
    )

st.title("🐴 Lovarda Időpontfoglaló")

# --- Dátumválasztó és korlátozások ---
selected_date = st.date_input("📅 Válaszd ki a napot")
weekday = selected_date.weekday()
month   = selected_date.month

invalid = False; msg = ""
if month == 7 and weekday not in [0,1]:
    invalid = True; msg = "❌ Júliusban csak hétfőn és kedden lehet foglalni."
elif month == 8:
    if selected_date < datetime(2025,8,5).date():
        invalid = True; msg = "❌ Augusztus 1–4. között nem lehet foglalni."
    elif weekday == 0:
        invalid = True; msg = "❌ Augusztusban hétfőn nem lehet foglalni."

if invalid and not st.session_state["authenticated"]:
    st.warning(msg); st.stop()

# --- Foglalások betöltése ---
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

# --- Segédfüggvények ---
def slot_overlapping(start_time, end_time, date, bookings_df):
    for _, row in bookings_df.iterrows():
        b_start = datetime.combine(date, datetime.strptime(row["Kezdés"], "%H:%M").time())
        b_end   = b_start + timedelta(minutes=int(row["Időtartam (perc)"]))
        if (start_time < b_end and b_start < end_time):
            return True
    return False

def get_free_slots_exclusive(duration, date, bookings_df):
    slots = []
    current = datetime.combine(date, START_TIME)
    lunch_done = False
    today = date.strftime("%Y-%m-%d")
    day_bookings = bookings_df[bookings_df["Dátum"] == today]

    while current.time() <= (datetime.combine(date, END_TIME) - timedelta(minutes=duration)).time():
        if not lunch_done and LUNCH_WINDOW_START <= current.time() < LUNCH_WINDOW_END:
            current += LUNCH_BREAK_DURATION
            lunch_done = True
            continue

        slot_start = current
        slot_end   = current + timedelta(minutes=duration)

        if not slot_overlapping(slot_start, slot_end, date, day_bookings):
            slots.append((slot_start.time(), slot_end.time(), duration))

        current += timedelta(minutes=duration + BREAK_MINUTES)

    return slots

# --- Vendég-felület ---
if not st.session_state["authenticated"]:
    st.subheader("➕ Foglalás")
    with st.form("foglalas_form"):
        nev    = st.text_input("Gyermek(ek) neve")
        letszam= st.number_input("Fő", 1, MAX_CHILDREN_PER_SLOT, 1)
        ido    = st.selectbox("Időtartam", [30, 60, 90])
        szlots = get_free_slots_exclusive(ido, selected_date, df)
        opts   = [f"{s[0].strftime('%H:%M')}-{s[1].strftime('%H:%M')} ({s[2]}p)" for s in szlots]
        v      = st.selectbox("Időpont", opts if opts else ["Nincs időpont"])
        ism    = st.checkbox("Heti ismétlődés aug.")
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

    st.subheader("📆 Elérhető időpontok")
    if szlots:
        for s in szlots:
            st.write(f"{s[0].strftime('%H:%M')} – {s[1].strftime('%H:%M')} ({s[2]}p)")
    else:
        st.info("Nincs szabad időpont ma.")

# --- Admin-felület ---
if st.session_state["authenticated"]:
    st.subheader("🛠️ Admin felület")

    df["Dátum"] = pd.to_datetime(df["Dátum"])
    df["Hét"]   = df["Dátum"].dt.isocalendar().week
    weeks      = sorted(df["Hét"].unique())
    sel_week   = st.selectbox("Válassz hetet", weeks, index=len(weeks)-1 if weeks else 0)

    # Itt rendezzük időrendbe:
    week_df = (
        df[df["Hét"] == sel_week]
        .sort_values(by=["Dátum", "Kezdés"])
        .reset_index(drop=True)
    )

    st.write(f"Foglalások ({sel_week}. hét):")
    for idx, row in week_df.iterrows():
        d = row["Dátum"].strftime("%Y-%m-%d")
        st.markdown(
            f"**{d} {row['Kezdés']}** – {row['Gyermek(ek) neve']} – "
            f"{row['Időtartam (perc)']}p – {row['Fő']} fő – "
            f"Lovak: {row['Lovak'] or 'nincs'}"
        )
        c1, c2, c3 = st.columns([1,1,2])
        # Törlés
        with c1:
            if st.button("❌ Törlés", key=f"del_{idx}"):
                df = df.drop(idx)
                df.to_excel(FILE_NAME, index=False)
                st.success("Törölve!")
                st.rerun()
        # Lovak
        with c2:
            if st.button("🐴 Lovak", key=f"lo_{idx}"):
                st.session_state["mod"] = idx
        # Csúsztatás admin override-ként
        with c3:
            duration = int(row["Időtartam (perc)"])
            # 5 perces lépések
            times = []
            t = datetime.combine(row["Dátum"].date(), START_TIME)
            end_of_day = datetime.combine(row["Dátum"].date(), END_TIME) - timedelta(minutes=duration)
            while t <= end_of_day:
                times.append(t.time()); t += timedelta(minutes=5)
            opts2 = [tt.strftime("%H:%M") for tt in times]
            current_index = opts2.index(row["Kezdés"]) if row["Kezdés"] in opts2 else 0

            select_key = f"cs_select_{idx}"
            button_key = f"cs_button_{idx}"

            new_start = st.selectbox("Új kezdés", opts2,
                                     index=current_index, key=select_key)
            if st.button("Csúsztat", key=button_key):
                df.at[idx, "Kezdés"] = new_start
                df.to_excel(FILE_NAME, index=False)
                st.success("Átcsúsztatva admin joggal!")
                st.rerun()

    # Lovak hozzárendelése
    if "mod" in st.session_state:
        m   = st.session_state["mod"]
        row = df.loc[m]
        st.info(f"{row['Dátum'].strftime('%Y-%m-%d')} {row['Kezdés']} – {row['Gyermek(ek) neve']}")
        cur = [h for h in str(row["Lovak"]).split(",") if h.strip() in HORSES]
        nh  = st.multiselect("Lovak", HORSES, default=cur)
        if st.button("Mentés lovak", key="mentlov"):
            df.at[m, "Lovak"] = ", ".join(nh)
            df.to_excel(FILE_NAME, index=False)
            del st.session_state["mod"]
            st.success("Lovak mentve!")
            st.rerun()

    # Excel export
    if st.button("📁 Exportálás Excel-be"):
        fn = f"foglalasok_{sel_week}.xlsx"
        week_df.to_excel(fn, index=False)
        st.success(f"Exportálva: {fn}")

    # Statisztikák
    with st.expander("📊 Statisztikák", expanded=False):
        st.bar_chart(week_df.groupby("Dátum")["Fő"].sum())
        st.write("**Top 10 név:**")
        st.dataframe(df["Gyermek(ek) neve"].value_counts().head(10))
        st.write("**Lovak kihasználtsága:**")
        lo_list = df["Lovak"].fillna("").astype(str).str.split(",").explode().str.strip()
        st.dataframe(lo_list[lo_list!=""].value_counts())
