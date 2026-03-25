import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Analiza Kosztów PV", layout="wide")
st.title("📉 Porównanie Kosztów Energii: Przed i Po PV")

# --- BAZA CENNIKÓW (2026) ---
osd_tariffs_b = {
    "PGE": {
        "B21": {"całodobowa": 0.2450},
        "B22": {"szczyt": 0.3100, "pozaszczyt": 0.1400},
        "B23": {"przedpołudnie": 0.2500, "popołudnie": 0.3800, "pozostałe": 0.1100}
    },
    "Tauron": {
        "B21": {"całodobowa": 0.2250},
        "B22": {"szczyt": 0.2900, "pozaszczyt": 0.1250},
        "B23": {"przedpołudnie": 0.2300, "popołudnie": 0.3500, "pozostałe": 0.0950}
    },
    "Energa": {
        "B21": {"całodobowa": 0.2550},
        "B22": {"szczyt": 0.3200, "pozaszczyt": 0.1500},
        "B23": {"przedpołudnie": 0.2600, "popołudnie": 0.400, "pozostałe": 0.1200}
    },
    "Enea": {
        "B21": {"całodobowa": 0.2150},
        "B22": {"szczyt": 0.2800, "pozaszczyt": 0.1200},
        "B23": {"przedpołudnie": 0.2200, "popołudnie": 0.3400, "pozostałe": 0.0900}
    }
}
OPLATA_MOCOWA_2026 = 0.2194 

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja")
cena_mwh_netto = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
cena_kwh_netto = cena_mwh_netto / 1000

osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_tariffs_b.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])

stawki_dyst = {}
for strefa, stawka in osd_tariffs_b[osd_choice][taryfa_choice].items():
    stawki_dyst[strefa] = st.sidebar.number_input(f"Dystrybucja {strefa} (zł/kWh)", value=stawka, format="%.4f")

moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil CSV", type=['csv'])

# --- LOGIKA ---
if uploaded_file is None:
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    pobor = np.where((dates.hour >= 8) & (dates.hour < 16), np.random.uniform(40, 60, 8760), np.random.uniform(10, 20, 8760))
    df = pd.DataFrame({"Data": dates, "Pobór": pobor})
else:
    df = pd.read_csv(uploaded_file)
    df.columns = ["Data", "Pobór"]
    df["Pobór"] = pd.to_numeric(df["Pobór"], errors='coerce').fillna(0)

# Symulacja PV i Bilans
df['Godzina'] = np.arange(len(df)) % 24
df['Dzień_Roku'] = np.arange(len(df)) // 24
df['Roboczy'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday < 5

profil_dzienny = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
df['Generacja_PV'] = (profil_dzienny / profil_dzienny.sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# Strefy i Mocowa
def get_strefa(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        return "przedpołudnie" if 7 <= h < 13 else ("popołudnie" if 16 <= h < 21 else "pozostałe")
    return "całodobowa"

df['Strefa'] = df.apply(get_strefa, axis=1)
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def kalkulacja(col):
    en = df[col].sum() * cena_kwh_netto
    dys = sum(df[df['Strefa'] == s][col].sum() * stawki_dyst[s] for s in stawki_dyst)
    sz_m, pz_m = df[df['Godzina_Mocowa']][col].sum(), df[~df['Godzina_Mocowa']][col].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mnoznik = 0.17 if delta < 0.05 else (0.5 if delta < 0.10 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_2026 * mnoznik
    return round(en, 2), round(dys, 2), round(moc, 2)

e_przed, d_przed, m_przed = kalkulacja('Pobór')
e_po, d_po, m_po = kalkulacja('Nowy_Pobór')

# --- PREZENTACJA DANYCH ---

# 1. Tabela Porównawcza
st.subheader("📋 Porównanie Rocznych Kosztów (Netto)")
data_compare = {
    "Kategoria kosztów": ["Energia Czynna", "Dystrybucja (Zmienna)", "Opłata Mocowa", "SUMA"],
    "PRZED PV [PLN]": [f"{e_przed:,.2f}", f"{d_przed:,.2f}", f"{m_przed:,.2f}", f"{e_przed+d_przed+m_przed:,.2f}"],
    "PO PV [PLN]": [f"{e_po:,.2f}", f"{d_po:,.2f}", f"{m_po:,.2f}", f"{e_po+d_po+m_po:,.2f}"],
    "OSZCZĘDNOŚĆ [PLN]": [f"{e_przed-e_po:,.2f}", f"{d_przed-d_po:,.2f}", f"{m_przed-m_po:,.2f}", f"{(e_przed+d_przed+m_przed)-(e_po+d_po+m_po):,.2f}"]
}
st.table(pd.DataFrame(data_compare))

# 2. Wykres Słupkowy Porównawczy
st.subheader("📊 Struktura Kosztów: Przed vs Po")
categories = ["Energia Czynna", "Dystrybucja", "Opłata Mocowa"]
fig_costs = go.Figure(data=[
    go.Bar(name='Przed PV', x=categories, y=[e_przed, d_przed, m_przed], marker_color='#E74C3C'),
    go.Bar(name='Po PV', x=categories, y=[e_po, d_po, m_po], marker_color='#2ECC71')
])
fig_costs.update_layout(barmode='group', yaxis_title="Koszt w PLN", template="plotly_white")
st.plotly_chart(fig_costs, use_container_width=True)

# 3. Podsumowanie procentowe
zysk_proc = ((e_przed+d_przed+m_przed)-(e_po+d_po+m_po)) / (e_przed+d_przed+m_przed) * 100
st.info(f"💡 Instalacja PV obniża całkowite koszty energii Twojego klienta o ok. **{zysk_proc:.1f}%** rocznie.")
