import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Analiza Strefowa", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD 2026 (NETTO PLN/kWh) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja")
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV (Data, Godzina, Zużycie)", type=['csv'])

# --- „INTELIGENTNY” LOADER DANYCH ---
df = None
if uploaded_file is not None:
    try:
        # Odczyt z automatycznym wykrywaniem separatora i obsługą polskich znaków
        content = uploaded_file.read()
        for enc in ['cp1250', 'utf-8-sig', 'utf-8', 'iso-8859-2']:
            try:
                df_raw = pd.read_csv(io.BytesIO(content), sep=None, engine='python', encoding=enc, decimal=',')
                break
            except: continue
        
        # Przetwarzanie kolumn (Zakładamy układ: Data | Godzina | Wartość)
        df_raw.columns = ['Data', 'Godzina', 'Wartość']
        
        # Konwersja daty i czasu
        df_raw['Timestamp'] = pd.to_datetime(df_raw['Data'] + ' ' + df_raw['Godzina'], dayfirst=True, errors='coerce')
        df_raw['Wartość'] = pd.to_numeric(df_raw['Wartość'], errors='coerce').fillna(0)
        
        # Agregacja do pełnych godzin (Resample sumuje 15-minutówki w jedną godzinę)
        df_hourly = df_raw.set_index('Timestamp')['Wartość'].resample('1H').sum().reset_index()
        df_hourly.columns = ['Data_Czas', 'Pobór']
        
        # Wyciąganie cech czasowych dla taryf
        df_hourly['Godzina'] = df_hourly['Data_Czas'].dt.hour
        df_hourly['Dzień_Tyg'] = df_hourly['Data_Czas'].dt.weekday # 0-4 to dni robocze
        df_hourly['Roboczy'] = df_hourly['Dzień_Tyg'] < 5
        
        df = df_hourly.head(8760).copy()
        st.success(f"Pomyślnie przetworzono profil klienta ({len(df)} godzin).")
    except Exception as e:
        st.error(f"Błąd formatu pliku: {e}. Upewnij się, że masz kolumny: Data, Godzina, Wartość.")

# Dane testowe (awaryjne)
if df is None:
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Data_Czas": dates, "Pobór": np.random.uniform(20, 60, 8760)})
    df['Godzina'] = df['Data_Czas'].dt.hour
    df['Roboczy'] = df['Data_Czas'].dt.weekday < 5

# --- SYMULACJA PV ---
# Generacja PV (uproszczony model dzwonowy)
df['Generacja_PV'] = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
df['Generacja_PV'] = (df['Generacja_PV'] / df['Generacja_PV'].sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# --- PRZYPISANIE STREF TARYFOWYCH ---
def przypisz_strefe(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        if 7 <= h < 13: return "przedpołudnie"
        if 16 <= h < 21: return "popołudnie"
        return "pozostałe"
    return "całodobowa"

df['Strefa'] = df.apply(przypisz_strefe, axis=1)
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

# --- KALKULACJA FINANSOWA ---
def oblicz(col_name):
    cena_kwh = cena_mwh / 1000
    en = df[col_name].sum() * cena_kwh
    dys = sum(df[df['Strefa'] == s][col_name].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    
    sz_m = df[df['Godzina_Mocowa']][col_name].sum()
    pz_m = df[~df['Godzina_Mocowa']][col_name].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.5 if delta < 0.10 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_przed, d_przed, m_przed, mn_przed, sz_m_przed = oblicz('Pobór')
e_po, d_po, m_po, mn_po, sz_m_po = oblicz('Nowy_Pobór')

# --- PREZENTACJA WYNIKÓW ---
st.header(f"📉 Analiza Kosztów: {osd_choice} {taryfa_choice}")
st.table(pd.DataFrame({
    "Kategoria": ["Energia Czynna", "Dystrybucja", "Opłata Mocowa", "SUMA"],
    "PRZED PV [PLN]": [e_przed, d_przed, m_przed, e_przed+d_przed+m_przed],
    "PO PV [PLN]": [e_po, d_po, m_po, e_po+d_po+m_po],
    "ZYSK [PLN]": [e_przed-e_po, d_przed-d_po, m_przed-m_po, (e_przed+d_przed+m_przed)-(e_po+d_po+m_po)]
}).set_index("Kategoria").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("⚡ Porównanie Kategorii Opłaty Mocowej")
c1, c2 = st.columns(2)
def tabela_moc(sz_m, mn_akt):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({
        "Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"],
        "Koszt Roczny": [sz_m * OPLATA_MOCOWA_NETTO * m for m in mns]
    })
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_akt == mns[x.name] else '' for _ in x], axis=1).format({"Koszt Roczny": "{:,.2f}"})

with c1:
    st.write("**PRZED PV**")
    st.table(tabela_moc(sz_m_przed, mn_przed))
with c2:
    st.write("**PO PV**")
    st.table(tabela_moc(sz_m_po, mn_po))

st.markdown("---")
# Wykres profilu
avg_profile = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg_profile.index, y=avg_profile['Pobór'], name="Pobór przed", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg_profile.index, y=avg_profile['Nowy_Pobór'], name="Pobór po", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg_profile.index, y=avg_profile['Generacja_PV'], name="Generacja PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", xaxis_title="Godzina", template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
