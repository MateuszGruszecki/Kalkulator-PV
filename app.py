import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV dla B21/B22/B23", layout="wide")
st.title("⚡ Kalkulator Opłacalności PV")

# --- WCZYTANIE BAZY CENNIKÓW ---
@st.cache_data
def load_tariffs():
    try:
        return pd.read_csv("cenniki_osd.csv")
    except FileNotFoundError:
        st.warning("Nie znaleziono pliku cenniki_osd.csv w repozytorium! Używam pustej bazy.")
        return pd.DataFrame()

df_tariffs = load_tariffs()

# --- PANEL BOCZNY (DANE WEJŚCIOWE) ---
st.sidebar.header("Parametry Inwestycji")
osd = st.sidebar.selectbox("Wybierz OSD", ["PGE", "Tauron", "Enea", "Energa", "Stoen"])
taryfa = st.sidebar.selectbox("Wybierz Taryfę", ["B21", "B22", "B23"])

cena_czynna = st.sidebar.number_input("Cena zakupu energii (PLN/MWh)", value=485.0)
moc_pv = st.sidebar.number_input("Moc instalacji PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Zakładany uzysk z 1 kWp (kWh)", value=1000.0)

st.sidebar.markdown("---")
uploaded_file = st.sidebar.file_uploader("Wgraj swój profil poboru (CSV)", type=['csv'])

# --- GŁÓWNA LOGIKA ---
if uploaded_file is None:
    st.info("👈 Wgraj plik ze swoim poborem, aby przeliczyć realne dane.")
    dates = pd.date_range(start="2025-01-01", periods=8760, freq="h")
    pobor = np.random.uniform(10, 50, 8760)
    df = pd.DataFrame({"Data": dates, "Zużycie (kWh)": pobor})
else:
    try:
        df = pd.read_csv(uploaded_file)
        
        # Inteligentne szukanie kolumny ze zużyciem
        if 'Zużycie (kWh)' not in df.columns:
            kolumny_numeryczne = df.select_dtypes(include=np.number).columns
            if len(kolumny_numeryczne) > 0:
                df.rename(columns={kolumny_numeryczne[0]: 'Zużycie (kWh)'}, inplace=True)
        
        # BARDZO WAŻNE: Czyszczenie danych z Excela (puste wiersze = błąd)
        df['Zużycie (kWh)'] = pd.to_numeric(df['Zużycie (kWh)'], errors='coerce').fillna(0)
        st.success("Plik przetworzony poprawnie!")
    except Exception as e:
        st.error(f"Błąd odczytu pliku: {e}")
        st.stop()

# Upewniamy się, że mamy max 8760 godzin i twardo resetujemy indeks (usuwa to błędy z pustymi wierszami)
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
# Zabezpieczenie przed dzieleniem przez zero
if suma_profilu > 0:
    mnoznik = (uzysk * moc_pv) / suma_profilu
else:
    mnoznik = 0
    
df['Generacja_PV_kWh'] = profil_slonca * mnoznik

# --- OBLICZENIA ENERGETYCZNE ---
df['Bilans'] = df['Zużycie (kWh)'] - df['Generacja_PV_kWh']
df['Pobor_z_sieci_po_PV'] = df['Bilans'].apply(lambda x: x if x > 0 else 0)

# --- BEZPIECZNE PRZYPISANIE GODZIN (Całkowicie odporne na błędy CSV) ---
df['Dzien_tygodnia'] = (np.arange(len(df)) // 24) % 7
df['Godzina_dnia'] = np.arange(len(df)) % 24
df['Godzina_Mocowa'] = np.where((df['Dzien_tygodnia'] < 5) & (df['Godzina_dnia'] >= 7) & (df['Godzina_dnia'] < 22), 1, 0)

# --- STATYSTYKI ---
zuzycie_przed = df['Zużycie (kWh)'].sum()
zuzycie_po = df['Pobor_z_sieci_po_PV'].sum()
oszczednosc_mwh = (zuzycie_przed - zuzycie_po) / 1000
oszczednosc_energia_czynna_pln = oszczednosc_mwh * cena_czynna

# Opłata Mocowa
szczyt_przed = df[df['Godzina_Mocowa'] == 1]['Zużycie (kWh)'].sum()
pozaszczyt_przed = df[df['Godzina_Mocowa'] == 0]['Zużycie (kWh)'].sum()
szczyt_po = df[df['Godzina_Mocowa'] == 1]['Pobor_z_sieci_po_PV'].sum()
pozaszczyt_po = df[df['Godzina_Mocowa'] == 0]['Pobor_z_sieci_po_PV'].sum()

def kwalifikacja_k(szczyt, pozaszczyt):
    if szczyt == 0: return "Brak"
    wsp = pozaszczyt / (szczyt + pozaszczyt)
    if wsp < 0.05: return "Brak Ulgi"
    elif wsp < 0.10: return "K1"
    elif wsp < 0.15: return "K2"
    else: return "K3/K4"

# --- WYŚWIETLANIE ---
col1, col2, col3 = st.columns(3)
col1.metric("Pobór z sieci PRZED", f"{zuzycie_przed/1000:,.1f} MWh".replace(',', ' '))
col2.metric("Pobór z sieci PO", f"{zuzycie_po/1000:,.1f} MWh".replace(',', ' '))
col3.metric("Oszczędność (Czynna)", f"{oszczednosc_energia_czynna_pln:,.0f} PLN".replace(',', ' '))

st.markdown("---")
st.subheader("💡 Wpływ PV na Opłatę Mocową")
c1, c2, c3 = st.columns(3)
c1.metric("Kwalifikacja PRZED PV", kwalifikacja_k(szczyt_przed, pozaszczyt_przed))
c2.metric("Kwalifikacja PO PV", kwalifikacja_k(szczyt_po, pozaszczyt_po))
c3.info("Często po instalacji PV klient 'wskakuje' do lepszej grupy ryczałtowej, ponieważ PV ścina zużycie w godzinach mocowych (dziennych).")

# --- WYKRES ---
st.subheader("Średni Profil Dobowy Poboru")
sredni_profil = df.groupby('Godzina_dnia')[['Zużycie (kWh)', 'Pobor_z_sieci_po_PV']].mean().reset_index()

fig = go.Figure()
fig.add_trace(go.Bar(x=sredni_profil['Godzina_dnia'], y=sredni_profil['Zużycie (kWh)'], name='Przed PV', marker_color='lightgray'))
fig.add_trace(go.Bar(x=sredni_profil['Godzina_dnia'], y=sredni_profil['Pobor_z_sieci_po_PV'], name='Po PV', marker_color='#1f77b4'))
fig.update_layout(barmode='overlay', xaxis_title="Godzina dnia", yaxis_title="Średni pobór (kWh)", showlegend=True)
fig.update_traces(opacity=0.75)
st.plotly_chart(fig, use_container_width=True)
