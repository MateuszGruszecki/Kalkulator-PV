import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from fpdf import FPDF

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Stała Cena", layout="wide")
st.title("⚡ Profesjonalny Kalkulator PV dla Biznesu (B21, B22, B23)")

# --- BAZA CENNIKÓW OSD (DOMYŚLNE NA 2026 R.) ---
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
OPLATA_MOCOWA_2026 = 0.2194  # 219,40 zł/MWh netto

# --- PANEL BOCZNY ---
st.sidebar.header("🛡️ Parametry Kontraktu")
cena_mwh_netto = st.sidebar.number_input("Stała cena energii czynnej (PLN/MWh netto)", value=485.0, step=10.0)
cena_kwh_netto = cena_mwh_netto / 1000

st.sidebar.markdown("---")
st.sidebar.header("🚛 Dystrybucja i OSD")
osd_choice = st.sidebar.selectbox("Wybierz Operatora", list(osd_tariffs_b.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])

# Pobieranie stawek dystrybucyjnych z bazy z możliwością edycji
stawki_dyst_input = {}
domyslne_stawki = osd_tariffs_b[osd_choice][taryfa_choice]
for strefa, stawka in domyslne_stawki.items():
    stawki_dyst_input[strefa] = st.sidebar.number_input(f"Dystrybucja: {strefa} (PLN/kWh)", value=stawka, format="%.4f")

st.sidebar.markdown("---")
st.sidebar.header("☀️ Instalacja PV")
moc_pv = st.sidebar.number_input("Moc instalacji (kWp)", value=50.0)
uzysk_kwh_kwp = st.sidebar.number_input("Uzysk (kWh/kWp/rok)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil godzinowy (CSV)", type=['csv'])

# --- LOGIKA OBLICZEŃ ---
if uploaded_file is None:
    st.warning("Używam profilu demonstracyjnego. Wgraj plik CSV, aby zobaczyć realne wyniki.")
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    # Symulacja profilu firmy (większy pobór w dzień)
    pobor = np.where((dates.hour >= 8) & (dates.hour < 16), np.random.uniform(40, 60, 8760), np.random.uniform(10, 20, 8760))
    df = pd.DataFrame({"Data": dates, "Pobór": pobor})
else:
    df = pd.read_csv(uploaded_file)
    df.columns = ["Data", "Pobór"]
    df["Pobór"] = pd.to_numeric(df["Pobór"], errors='coerce').fillna(0)

# 1. Symulacja Generacji PV
# Tworzymy teoretyczny profil (dzwon Gaussa w ciągu dnia)
df['Godzina'] = np.arange(len(df)) % 24
df['Dzień_Roku'] = np.arange(len(df)) // 24
profil_dzienny = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
# Skalowanie do całkowitej rocznej produkcji
calkowita_produkcja = moc_pv * uzysk_kwh_kwp
df['Generacja_PV'] = (profil_dzienny / profil_dzienny.sum()) * calkowita_produkcja

# 2. Nowy Bilans
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# 3. Przypisanie Stref Dystrybucyjnych (Logika czasowa)
df['Dzień_Tygodnia'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday
df['Roboczy'] = df['Dzień_Tygodnia'] < 5

def przypisz_strefe(row):
    h = row['Godzina']
    rob = row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22":
        return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        if 7 <= h < 13: return "przedpołudnie"
        if 16 <= h < 21: return "popołudnie"
        return "pozostałe"
    return "całodobowa"

df['Strefa'] = df.apply(przypisz_strefe, axis=1)

# 4. Opłata Mocowa (Godziny 7-22 w dni robocze)
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

# Obliczanie kosztów
def oblicz_koszty(kolumna_poboru):
    energia = df[kolumna_poboru].sum() * cena_kwh_netto
    dystrybucja = sum(df[df['Strefa'] == s][kolumna_poboru].sum() * stawki_dyst_input[s] for s in stawki_dyst_input)
    
    # Mocowa (Kwalifikacja)
    szczyt_m = df[df['Godzina_Mocowa']][kolumna_poboru].sum()
    poza_m = df[~df['Godzina_Mocowa']][kolumna_poboru].sum()
    calkowite = szczyt_m + poza_m
    delta = (szczyt_m - poza_m) / calkowite if calkowite > 0 else 0
    
    if delta < 0.05: mnoznik = 0.17
    elif delta < 0.10: mnoznik = 0.50
    elif delta < 0.15: mnoznik = 0.83
    else: mnoznik = 1.00
    
    mocowa = szczyt_m * OPLATA_MOCOWA_2026 * mnoznik
    return energia, dystrybucja, mocowa

e_przed, d_przed, m_przed = oblicz_koszty('Pobór')
e_po, d_po, m_po = oblicz_koszty('Nowy_Pobór')

oszcz_en = e_przed - e_po
oszcz_dyst = d_przed - d_po
oszcz_moc = m_przed - m_po
suma_zysk = oszcz_en + oszcz_dyst + oszcz_moc

# --- WIZUALIZACJA ---
c1, c2, c3 = st.columns(3)
c1.metric("Zysk na Energii Czynnej", f"{oszcz_en:,.0f} PLN".replace(',', ' '))
c2.metric("Zysk na Dystrybucji", f"{oszcz_dyst:,.0f} PLN".replace(',', ' '))
c3.metric("Zysk na Opłacie Mocowej", f"{oszcz_moc:,.0f} PLN".replace(',', ' '))

st.subheader(f"💰 Całkowita roczna oszczędność: {suma_zysk:,.2f} PLN Netto")

# Wykres profilu (średni dzień)
st.markdown("---")
profil_wykres = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=profil_wykres.index, y=profil_wykres['Pobór'], name="Pobór Pierwotny", line=dict(color='red')))
fig.add_trace(go.Scatter(x=profil_wykres.index, y=profil_wykres['Nowy_Pobór'], name="Pobór po PV", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=profil_wykres.index, y=profil_wykres['Generacja_PV'], name="Generacja PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średniodobowy efekt instalacji PV", xaxis_title="Godzina", yaxis_title="Energia [kWh]")
st.plotly_chart(fig, use_container_width=True)

# --- PDF GENERATOR (SKRÓCONY) ---
def eksport_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(200, 10, "Raport Oszczędności PV (B2B)", ln=True, align='C')
    pdf.set_font("Arial", "", 12)
    pdf.ln(10)
    pdf.cell(200, 8, f"Cena energii czynnej: {cena_mwh_netto} PLN/MWh", ln=True)
    pdf.cell(200, 8, f"Moc instalacji: {moc_pv} kWp", ln=True)
    pdf.cell(200, 8, f"Taryfa: {taryfa_choice} ({osd_choice})", ln=True)
    pdf.ln(10)
    pdf.cell(200, 10, f"ROCZNY ZYSK SUMARYCZNY: {suma_zysk:,.2f} PLN Netto", ln=True)
    
    # Naprawa błędu Streamlit bytes
    pdf_out = pdf.output()
    return bytes(pdf_out) if not isinstance(pdf_out, str) else pdf_out.encode('latin-1')

st.download_button("📥 Pobierz uproszczony Raport PDF", data=eksport_pdf(), file_name="raport_pv.pdf")
