import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
import requests
from fpdf import FPDF
import io

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV dla B21/B22/B23", layout="wide")
st.title("⚡ Kalkulator Opłacalności PV dla Biznesu")

# --- BAZA CENNIKÓW OSD (NETTO PLN na 2026 r.) ---
osd_tariffs_b = {
    "PGE": {
        "oplata_stala_kW": 18.50,
        "B21": {"calodobowa": 0.245},
        "B22": {"szczyt": 0.310, "pozaszczyt": 0.140},
        "B23": {"przedpoludnie": 0.250, "popoludnie": 0.380, "pozostale": 0.110}
    },
    "Tauron": {
        "oplata_stala_kW": 17.20,
        "B21": {"calodobowa": 0.225},
        "B22": {"szczyt": 0.290, "pozaszczyt": 0.125},
        "B23": {"przedpoludnie": 0.230, "popoludnie": 0.350, "pozostale": 0.095}
    },
    "Energa": {
        "oplata_stala_kW": 19.10,
        "B21": {"calodobowa": 0.255},
        "B22": {"szczyt": 0.320, "pozaszczyt": 0.150},
        "B23": {"przedpoludnie": 0.260, "popoludnie": 0.400, "pozostale": 0.120}
    },
    "Enea": {
        "oplata_stala_kW": 16.90,
        "B21": {"calodobowa": 0.215},
        "B22": {"szczyt": 0.280, "pozaszczyt": 0.120},
        "B23": {"przedpoludnie": 0.220, "popoludnie": 0.340, "pozostale": 0.090}
    },
    "Stoen": {
        "oplata_stala_kW": 17.50,
        "B21": {"calodobowa": 0.205},
        "B22": {"szczyt": 0.270, "pozaszczyt": 0.115},
        "B23": {"przedpoludnie": 0.210, "popoludnie": 0.330, "pozostale": 0.085}
    }
}
OPLATA_MOCOWA_BAZA = 0.1412 # 141,20 zł/MWh netto za kWh w godzinach 7-22 robocze

# --- PANEL BOCZNY (DANE WEJŚCIOWE) ---
st.sidebar.header("Parametry Inwestycji")
osd = st.sidebar.selectbox("Wybierz OSD", list(osd_tariffs_b.keys()))
taryfa = st.sidebar.selectbox("Wybierz Taryfę", ["B21", "B22", "B23"])

cena_czynna = st.sidebar.number_input("Cena zakupu energii czynnej (PLN/MWh netto)", value=485.0)
moc_umowna = st.sidebar.number_input("Moc umowna firmy (kW)", value=50, step=1)
moc_pv = st.sidebar.number_input("Moc instalacji PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Zakładany uzysk z 1 kWp (kWh)", value=1000.0)

st.sidebar.markdown("---")
uploaded_file = st.sidebar.file_uploader("Wgraj swój profil poboru (CSV)", type=['csv'])

# --- GŁÓWNA LOGIKA (WCZYTYWANIE DANYCH) ---
if uploaded_file is None:
    st.info("👈 Wgraj plik ze swoim poborem (8760 godzin), aby przeliczyć realne dane. Obecnie używam profilu testowego.")
    dates = pd.date_range(start="2025-01-01", periods=8760, freq="h")
    # Profil testowy: wyższe zużycie w dzień, żeby symulować biznes
    pobor = np.where((dates.hour >= 7) & (dates.hour < 17), np.random.uniform(30, 80, 8760), np.random.uniform(5, 20, 8760))
    df = pd.DataFrame({"Data": dates, "Zużycie (kWh)": pobor})
else:
    try:
        df = pd.read_csv(uploaded_file)
        if 'Zużycie (kWh)' not in df.columns:
            kolumny_numeryczne = df.select_dtypes(include=np.number).columns
            if len(kolumny_numeryczne) > 0:
                df.rename(columns={kolumny_numeryczne[0]: 'Zużycie (kWh)'}, inplace=True)
        df['Zużycie (kWh)'] = pd.to_numeric(df['Zużycie (kWh)'], errors='coerce').fillna(0)
        st.success("Plik przetworzony poprawnie!")
    except Exception as e:
        st.error(f"Błąd odczytu pliku: {e}")
        st.stop()

godziny_w_roku = 8760
df = df.iloc[:min(len(df), godziny_w_roku)].copy()
df = df.reset_index(drop=True)

# --- SYMULACJA GENERACJI PV ---
profil_slonca = np.zeros(len(df))
for i in range(len(df)):
    godzina_dnia = i % 24
    if 6 <= godzina_dnia <= 18:
        profil_slonca[i] = np.sin((godzina_dnia - 6) * np.pi / 12)

suma_profilu = np.sum(profil_slonca)
mnoznik = (uzysk * moc_pv) / suma_profilu if suma_profilu > 0 else 0
df['Generacja_PV_kWh'] = profil_slonca * mnoznik

# --- BILANS ENERGETYCZNY ---
df['Bilans'] = df['Zużycie (kWh)'] - df['Generacja_PV_kWh']
df['Pobor_z_sieci_po_PV'] = df['Bilans'].apply(lambda x: x if x > 0 else 0)

# --- PRZYPISANIE STREF CZASOWYCH I MOCOWYCH ---
df['Dzien_tygodnia'] = (np.arange(len(df)) // 24) % 7
df['Godzina_dnia'] = np.arange(len(df)) % 24
# Opłata mocowa: Dni robocze (0-4), godziny 7:00 - 21:59
df['Godzina_Mocowa'] = np.where((df['Dzien_tygodnia'] < 5) & (df['Godzina_dnia'] >= 7) & (df['Godzina_dnia'] < 22), 1, 0)

# Strefy Dystrybucyjne
if taryfa == "B22":
    df['Strefa_Dyst'] = np.where((df['Dzien_tygodnia'] < 5) & (df['Godzina_dnia'] >= 6) & (df['Godzina_dnia'] < 21), 'szczyt', 'pozaszczyt')
elif taryfa == "B23":
    warunek_przed = (df['Dzien_tygodnia'] < 5) & (df['Godzina_dnia'] >= 7) & (df['Godzina_dnia'] < 13)
    warunek_popol = (df['Dzien_tygodnia'] < 5) & (df['Godzina_dnia'] >= 16) & (df['Godzina_dnia'] < 21)
    df['Strefa_Dyst'] = np.select([warunek_przed, warunek_popol], ['przedpoludnie', 'popoludnie'], default='pozostale')
else:
    df['Strefa_Dyst'] = 'calodobowa'

# --- LOGIKA OPŁATY MOCOWEJ (KWALIFIKACJA K1-K4) ---
def kwalifikacja_k(szczyt_mocowy, pozaszczyt_mocowy):
    calkowite = szczyt_mocowy + pozaszczyt_mocowy
    if calkowite == 0: return "K1 (17%)", 0.17
    delta = (szczyt_mocowy - pozaszczyt_mocowy) / calkowite
    
    if delta < 0.05: return "K1 (17%)", 0.17
    elif delta < 0.10: return "K2 (50%)", 0.50
    elif delta < 0.15: return "K3 (83%)", 0.83
    else: return "K4 (100%)", 1.00

szczyt_przed = df[df['Godzina_Mocowa'] == 1]['Zużycie (kWh)'].sum()
pozaszczyt_przed = df[df['Godzina_Mocowa'] == 0]['Zużycie (kWh)'].sum()
szczyt_po = df[df['Godzina_Mocowa'] == 1]['Pobor_z_sieci_po_PV'].sum()
pozaszczyt_po = df[df['Godzina_Mocowa'] == 0]['Pobor_z_sieci_po_PV'].sum()

kat_przed_nazwa, mnoznik_przed = kwalifikacja_k(szczyt_przed, pozaszczyt_przed)
kat_po_nazwa, mnoznik_po = kwalifikacja_k(szczyt_po, pozaszczyt_po)

koszt_mocowy_przed = szczyt_przed * OPLATA_MOCOWA_BAZA * mnoznik_przed
koszt_mocowy_po = szczyt_po * OPLATA_MOCOWA_BAZA * mnoznik_po

# --- OBLICZENIA DYSTRYBUCJI I ENERGII ---
koszt_energii_przed = df['Zużycie (kWh)'].sum() * (cena_czynna / 1000)
koszt_energii_po = df['Pobor_z_sieci_po_PV'].sum() * (cena_czynna / 1000)

koszt_dyst_zmiennej_przed = 0
koszt_dyst_zmiennej_po = 0
cennik_dyst = osd_tariffs_b[osd][taryfa]

for strefa in df['Strefa_Dyst'].unique():
    stawka = cennik_dyst.get(strefa, 0)
    koszt_dyst_zmiennej_przed += df[df['Strefa_Dyst'] == strefa]['Zużycie (kWh)'].sum() * stawka
    koszt_dyst_zmiennej_po += df[df['Strefa_Dyst'] == strefa]['Pobor_z_sieci_po_PV'].sum() * stawka

zysk_roczny = (koszt_energii_przed + koszt_dyst_zmiennej_przed + koszt_mocowy_przed) - (koszt_energii_po + koszt_dyst_zmiennej_po + koszt_mocowy_po)

# --- WYŚWIETLANIE WYNIKÓW ---
st.subheader(f"📊 Wyniki dla OSD: {osd} | Taryfa: {taryfa}")
col1, col2, col3 = st.columns(3)
col1.metric("Roczne zużycie z sieci PRZED", f"{df['Zużycie (kWh)'].sum()/1000:,.1f} MWh".replace(',', ' '))
col2.metric("Roczne zużycie z sieci PO PV", f"{df['Pobor_z_sieci_po_PV'].sum()/1000:,.1f} MWh".replace(',', ' '))
col3.metric("ŁĄCZNE OSZCZĘDNOŚCI (Netto)", f"{zysk_roczny:,.0f} PLN".replace(',', ' '))

st.markdown("---")
st.subheader("💡 Wpływ PV na Opłatę Mocową (Kwalifikacja K1-K4)")
c1, c2, c3 = st.columns(3)
c1.metric("Kwalifikacja PRZED PV", kat_przed_nazwa, f"Koszt: {koszt_mocowy_przed:,.0f} PLN".replace(',', ' '), delta_color="off")
c2.metric("Kwalifikacja PO PV", kat_po_nazwa, f"Koszt: {koszt_mocowy_po:,.0f} PLN".replace(',', ' '), delta_color="off")
c3.metric("Zysk z samej opłaty mocowej", f"{(koszt_mocowy_przed - koszt_mocowy_po):,.0f} PLN".replace(',', ' '))

st.info("Fotowoltaika ścina zużycie w godzinach dziennych (7:00-21:59). Dzięki temu współczynnik zużycia w szczycie do całości maleje, co pozwala przeskoczyć do tańszej grupy ryczałtowej opłaty mocowej.")

# --- WYKRESY ---
st.subheader("Średni Profil Dobowy Poboru")
sredni_profil = df.groupby('Godzina_dnia')[['Zużycie (kWh)', 'Pobor_z_sieci_po_PV']].mean().reset_index()

fig = go.Figure()
fig.add_trace(go.Bar(x=sredni_profil['Godzina_dnia'], y=sredni_profil['Zużycie (kWh)'], name='Pobór bez PV', marker_color='lightgray'))
fig.add_trace(go.Bar(x=sredni_profil['Godzina_dnia'], y=sredni_profil['Pobor_z_sieci_po_PV'], name='Pobór po instalacji PV', marker_color='#1f77b4'))
fig.update_layout(barmode='overlay', xaxis_title="Godzina dnia", yaxis_title="Średni pobór [kWh]", showlegend=True)
fig.update_traces(opacity=0.75)
st.plotly_chart(fig, use_container_width=True)

# --- GENERATOR RAPORTÓW PDF ---
st.markdown("---")
st.subheader("📄 Generowanie Raportu PDF")

def pobierz_czcionke():
    # Zmieniamy nazwę pliku, żeby zignorować stary, zepsuty pobrany plik
    font_path = "Czcionka_PL.ttf" 
    
    if not os.path.exists(font_path):
        # Używamy prawidłowego linku RAW (bezpośrednio do pliku binarnego)
        url = "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/ttf/DejaVuSans.ttf"
        r = requests.get(url, allow_redirects=True)
        open(font_path, 'wb').write(r.content)
        
    return font_path

def stworz_raport_pdf():
    font_path = pobierz_czcionke()
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.set_font("DejaVu", "", 12)
    
    # Nagłówek
    pdf.set_font("DejaVu", "", 18)
    pdf.cell(200, 10, txt="Raport Oplacalnosci Instalacji PV (B2B)", ln=True, align='C')
    pdf.ln(10)
    
    # Sekcja 1
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="1. Parametry Inwestycji", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 8, txt=f"Operator OSD: {osd}", ln=True)
    pdf.cell(200, 8, txt=f"Taryfa: {taryfa}", ln=True)
    pdf.cell(200, 8, txt=f"Moc instalacji PV: {moc_pv} kWp", ln=True)
    pdf.cell(200, 8, txt=f"Moc umowna firmy: {moc_umowna} kW", ln=True)
    pdf.ln(5)
    
    # Sekcja 2
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="2. Bilans Energetyczny (Roczny)", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 8, txt=f"Pobor z sieci PRZED instalacja: {df['Zużycie (kWh)'].sum()/1000:,.1f} MWh".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Pobor z sieci PO instalacji PV: {df['Pobor_z_sieci_po_PV'].sum()/1000:,.1f} MWh".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Calkowita generacja z PV: {df['Generacja_PV_kWh'].sum()/1000:,.1f} MWh".replace(',', ' '), ln=True)
    pdf.ln(5)
    
    # Sekcja 3
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="3. Wplyw na Oplate Mocowa (Kwalifikacja)", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 8, txt=f"Kwalifikacja PRZED PV: {kat_przed_nazwa} (Koszt: {koszt_mocowy_przed:,.2f} PLN)".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Kwalifikacja PO PV: {kat_po_nazwa} (Koszt: {koszt_mocowy_po:,.2f} PLN)".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Oszczednosc na samej oplacie mocowej: {(koszt_mocowy_przed - koszt_mocowy_po):,.2f} PLN".replace(',', ' '), ln=True)
    pdf.ln(5)
    
    # Sekcja 4
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="4. Podsumowanie Finansowe", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.multi_cell(0, 8, txt="Poniższa kwota uwzględnia oszczędności na energii czynnej, zmiennych opłatach dystrybucyjnych oraz redukcji opłaty mocowej wynikającej ze zmiany profilu poboru w godzinach szczytowych.")
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt=f"SZACOWANY ZYSK ROCZNY NETTO: {zysk_roczny:,.2f} PLN".replace(',', ' '), ln=True)
    
    # Generowanie pliku do zmiennej w pamięci
    return pdf.output(dest='S').encode('latin-1')

st.info("Kliknij poniżej, aby wygenerować dokument podsumowujący obliczenia w formie PDF.")
pdf_bytes = stworz_raport_pdf()

st.download_button(
    label="📥 Pobierz Raport PDF",
    data=pdf_bytes,
    file_name="Raport_Oplacalnosci_PV.pdf",
    mime="application/pdf"
)
