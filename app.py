import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os

# Alapbeállítások
START_TIME = datetime.strptime("09:00", "%H:%M").time()
END_TIME = datetime.strptime("20:30", "%H:%M").time()
BREAK_MINUTES = 10
MAX_CHILDREN_PER_SLOT = 7
LUNCH_BREAK_DURATION = timedelta(minutes=45)
LUNCH_WINDOW_START = datetime.strptime("12:00", "%H:%M").time()
LUNCH_WINDOW_END = datetime.strptime("14:00", "%H:%M").time()
HORSES = ["Eni", "Vera", "Lord", "Pinty", "Szerencse lovag", "Herceg"]
FILE_NAME = "heti_foglalasok.xlsx"
ADMIN_PASSWORD = "almakaki"

st.set_page_config(page_title="Lovarda Foglalás", layout="centered")

# Admin bejelentkezés
st.sidebar.title("🔐 Admin belépés")
password = st.sidebar.text_input("Jelszó", type="password")
is_admin = password == ADMIN_PASSWORD

st.title("🐴 Lovarda Időpontfoglaló")

selected_date = st.date_input("🗕️ Válaszd ki a napot")
weekday = selected_date.weekday()
month = selected_date.month

invalid = False
msg = ""

if month == 7:
    if weekday not in [0, 1]:
        invalid = True
        msg = "❌ Júliusban csak hétfőn és kedden lehet foglalni."
elif month == 8:
    if selected_date < datetime(2025, 8, 5).date():
        invalid = True
        msg = "❌ Augusztus 1–4. között nem lehet foglalni."
    elif weekday == 0:
        invalid = True
        msg = "❌ Augusztusban hétfőn nem lehet foglalni."

if invalid:
    st.warning(msg)
    st.stop()

# Foglalások betöltése
if os.path.exists(FILE_NAME):
    df = pd.read_excel(FILE_NAME)
else:
    df = pd.DataFrame()

required_columns = ["Dátum", "Gyermek(ek) neve", "Lovak", "Kezdés", "Időtartam (perc)", "Fő", "Ismétlődik"]
for col in required_columns:
    if col not in df.columns:
        df[col] = 0 if col == "Fő" else False if col == "Ismétlődik" else ""

def generate_time_slots(duration_filter):
    slots = []
    current = datetime.combine(datetime.today(), START_TIME)
    lunch_inserted = False

    while current.time() <= (datetime.combine(datetime.today(), END_TIME) - timedelta(minutes=duration_filter)).time():
        if not lunch_inserted and LUNCH_WINDOW_START <= current.time() < LUNCH_WINDOW_END:
            current += LUNCH_BREAK_DURATION
            lunch_inserted = True
            continue

        end_time = current + timedelta(minutes=duration_filter)
        slot_key = current.strftime("%H:%M")
        slot_bookings = df[(df["Dátum"] == selected_date.strftime("%Y-%m-%d")) & (df["Kezdés"] == slot_key)]
        total_booked = slot_bookings["Fő"].sum() if not slot_bookings.empty else 0

        if total_booked < MAX_CHILDREN_PER_SLOT:
            slots.append((f"{duration_filter} perc", current.time(), end_time.time()))

        current += timedelta(minutes=duration_filter + BREAK_MINUTES)

    return slots

if not is_admin:
    st.subheader("➕ Foglalás")
    with st.form("foglalas_form"):
        names = st.text_input("Gyermek(ek) neve (vesszővel elválasztva)")
        num_children = st.number_input("Hány főre foglal?", min_value=1, max_value=MAX_CHILDREN_PER_SLOT, step=1)
        duration_choice_label = st.selectbox("Időtartam kiválasztása", ["30 perc", "60 perc", "Terep (90 perc)"])
        duration_choice = int(duration_choice_label.split()[0])
        repeat = st.checkbox("Ismétlődjön minden héten augusztusban")
        valid_slots = generate_time_slots(duration_choice)
        slot_labels = []
        for label, start, end in valid_slots:
            slot_key = start.strftime("%H:%M")
            current_booked = df[(df["Dátum"] == selected_date.strftime("%Y-%m-%d")) & (df["Kezdés"] == slot_key)]["Fő"].sum()
            if current_booked + num_children <= MAX_CHILDREN_PER_SLOT:
                slot_labels.append(f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')} ({label})")

        chosen_slot = st.selectbox("Időpont kiválasztása", slot_labels)
        submitted = st.form_submit_button("Foglalás mentése")

        if submitted:
            idx = slot_labels.index(chosen_slot)
            label, start, end = valid_slots[idx]
            slot_key = start.strftime("%H:%M")
            current_booked = df[(df["Dátum"] == selected_date.strftime("%Y-%m-%d")) & (df["Kezdés"] == slot_key)]["Fő"].sum()
            if current_booked + num_children > MAX_CHILDREN_PER_SLOT:
                st.error("Ehhez az időponthoz már nincs elég hely!")
            else:
                dates_to_add = [selected_date]
                if repeat and selected_date.month == 8:
                    next_date = selected_date + timedelta(weeks=1)
                    while next_date.month == 8:
                        dates_to_add.append(next_date)
                        next_date += timedelta(weeks=1)
                for d in dates_to_add:
                    new_entry = {
                        "Dátum": d.strftime("%Y-%m-%d"),
                        "Gyermek(ek) neve": names,
                        "Lovak": "",
                        "Kezdés": start.strftime("%H:%M"),
                        "Időtartam (perc)": duration_choice,
                        "Fő": num_children,
                        "Ismétlődik": repeat
                    }
                    df = pd.concat([df, pd.DataFrame([new_entry])], ignore_index=True)
                df.to_excel(FILE_NAME, index=False)
                st.success("Foglalás mentve!")

    st.subheader("📆 Elérhető időpontok")
    display_slots = generate_time_slots(duration_choice)
    filtered_slots = []
    for label, start, end in display_slots:
        slot_key = start.strftime("%H:%M")
        total_booked = df[(df["Dátum"] == selected_date.strftime("%Y-%m-%d")) & (df["Kezdés"] == slot_key)]["Fő"].sum()
        if total_booked < MAX_CHILDREN_PER_SLOT:
            filtered_slots.append((label, start, end))

    if filtered_slots:
        next_time = filtered_slots[0][1]
        st.info(f"🔜 Legközelebbi időpont: {next_time.strftime('%H:%M')}")
        for label, start, end in filtered_slots:
            st.write(f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')} ({label})")
    else:
        st.info("Nincs elérhető időpont ezen a napon.")

else:
    st.subheader("🛠️ Admin felület")
    st.write(f"Foglalások száma: {len(df)}")

    if st.button("📅 Exportálás Excel-be"):
        weekly_file = f"foglalasok_{selected_date.strftime('%Y-%m-%d')}.xlsx"
        df.to_excel(weekly_file, index=False)
        st.success(f"Exportálva: {weekly_file}")

    st.subheader("📆 Heti kiválasztás")
    unique_weeks = df["Dátum"].dropna().apply(lambda x: pd.to_datetime(x).isocalendar()[1]).unique()
    selected_week = st.selectbox("Válassz hetet (ISO hét szám)", sorted(unique_weeks))
    df["Week"] = df["Dátum"].apply(lambda x: pd.to_datetime(x).isocalendar()[1])
    weekly_df = df[df["Week"] == selected_week].copy()

    if not weekly_df.empty:
        summary = weekly_df.groupby(["Dátum", "Kezdés"]).agg({
            "Gyermek(ek) neve": lambda x: ", ".join(str(i) for i in x if pd.notna(i)),
            "Lovak": lambda x: ", ".join(str(i) for i in x if pd.notna(i)),
            "Fő": "sum"
        }).reset_index()
        st.dataframe(summary)

        # Oktatói terheltség kimutatás
        st.subheader("📊 Oktatói terheltség")
        load = weekly_df.groupby("Dátum")["Fő"].sum().reset_index(name="Összes fő")
        st.bar_chart(load.set_index("Dátum"))

    else:
        st.info("Nincs foglalás erre a hétre.")

    st.subheader("🧾 Foglalások kezelése")
    for idx, row in df.iterrows():
        st.write(f"{row['Dátum']} – {row['Gyermek(ek) neve']} – {row['Kezdés']} – {row['Időtartam (perc)']} perc – {row['Fő']} fő")
        if st.button(f"❌ Törlés [{idx}]"):
            df = df.drop(idx).reset_index(drop=True)
            df.to_excel(FILE_NAME, index=False)
            st.success("Foglalás törölve!")
            st.experimental_rerun()

    if st.checkbox("📁 Teljes adatbázis megtekintése"):
        st.dataframe(df)
