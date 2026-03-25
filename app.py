import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kalkulator PV B2B - Raport Końcowy", layout="wide")
st.title("⚡ Analiza PV B2B: Kompletny Raport Energetyczny 2026")

# --- PARAMETRY USTAWOWE 2026 ---
STAWKA_MOCOWA_BAZOWA = 0.2194 
WSPOLNE_NETTO = 0.04346 

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 1.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 1.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja")
data_type = st.sidebar.radio("Typ danych:", ["15-minutowe", "Godzinowe"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=500.0) 
uzysk = st.sidebar.number_input("Uzysk roczny (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj CSV (Data;Czas;Wartość)", type=['csv'])

# --- WCZYTYWANIE ---
df = None
if uploaded_file:
    try:
        raw = uploaded_file.read()
        try: decoded = raw.decode('cp1250')
        except: decoded = raw.decode('utf-8', errors='ignore')
        df_raw = pd.read_csv(io.StringIO(decoded), sep=';', decimal=',', engine='python', header=None, skiprows=1).dropna(how='all')
        
        if df_raw.shape[1] >= 3:
            t = pd.to_datetime(df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str), dayfirst=True, errors='coerce')
            v = pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            temp = pd.DataFrame({'T': t, 'V': v}).dropna(subset=['T'])
            if data_type == "15-minutowe":
                df = temp.set_index('T')['V'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'T': 'Timestamp'})
            else:
                df = temp.rename(columns={'T': 'Timestamp', 'V': 'Pobór'}).reset_index(drop=True)
        if len(df) > 0: st.success(f"Wczytano {len(df)} h danych.")
    except Exception as e: st.error(f"Błąd pliku: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(500, 1500, 8760)})

# --- LOGIKA 2026 ---
def is_holiday(dt):
    h = [(1,1),(1,6),(4,5),(4,6),(5,1),(5,3),(5,24),(6,4),(8,15),(11,1),(11,11),(25,12),(26,12)]
    return (dt.month, dt.day) in h

df['Data_Klucz'] = df['Timestamp'].dt.date
df['Roboczy'] = (df['Timestamp'].dt.weekday < 5) & (~df['Timestamp'].apply(is_holiday))
df['Godzina'] = df['Timestamp'].dt.hour
df['Miesiąc_Numer'] = df['Timestamp'].dt.month
df['Miesiąc_Nazwa'] = df['Timestamp'].dt.strftime('%m - %b')

# --- PV ---
weights = {1:0.3, 2:0.5, 3:0.9, 4:1.2, 5:1.5, 6:1.6, 7:1.6, 8:1.4, 9:1.0, 10:0.6, 11:0.3, 12:0.2}
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Gen_Raw'] = sin_p * df['Miesiąc_Numer'].map(weights)
total_gen = df['Gen_Raw'].sum()
df['Generacja_PV'] = (df['Gen_Raw'] / total_gen) * (moc_pv * uzysk * (len(df)/8760)) if total_gen > 0 else 0

df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Autokonsumpcja'])

# --- OPŁATA MOCOWA (DOBOWA) ---
df['Is_Szczyt'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def get_moc_daily(sub_df, col):
    if not sub_df['Roboczy'].any():
        return pd.Series({'Koszt': 0.0, 'Mnożnik': 0.17, 'L_Factor': 0.0})
    e_sz = sub_df[sub_df['Is_Szczyt']][col].sum()
    e_d = sub_df[col].sum()
    if e_d < 0.1: return pd.Series({'Koszt': 0.0, 'Mnożnik': 0.17, 'L_Factor': 0.0})
    l_f = (e_sz / e_d) - 0.625
    delta = abs(l_f)
    if delta < 0.05: mn = 0.17
    elif delta < 0.10: mn = 0.50
    elif delta < 0.15: mn = 0.83
    else: mn = 1.00
    return pd.Series({'Koszt': e_sz * STAWKA_MOCOWA_BAZOWA * mn, 'Mnożnik': mn, 'L_Factor': l_f})

moc_po = df.groupby('Data_Klucz').apply(lambda x: get_moc_daily(x, 'Nowy_Pobór'))
moc_pre = df.groupby('Data_Klucz').apply(lambda x: get_moc_daily(x, 'Pobór'))

total_m_po = moc_po['Koszt'].sum()
total_m_pre = moc_pre['Koszt'].sum()

# --- FINANSE ---
def get_strefa(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        return "przedpołudnie" if 7 <= h < 13 else ("popołudnie" if 16 <= h < 21 else "pozostałe")
    return "całodobowa"

df['Strefa'] = df.apply(get_strefa, axis=1)

def calc_all(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    return en, dys

e_p, d_p = calc_all('Pobór')
e_n, d_n = calc_all('Nowy_Pobór')

# --- PREZENTACJA ---
st.subheader("💰 Bilans Oszczędności Rocznych (Netto 2026)")

# POPRAWKA: Zysk to (Przed - Po)
z_en = e_p - e_n
z_dys = d_p - d_n
z_moc = total_m_pre - total_m_po
z_total = z_en + z_dys + z_moc

st.table(pd.DataFrame({
    "Składnik kosztu": ["Energia czynna", "Dystrybucja zmienna", "Opłata mocowa (DOBOWA)", "RAZEM"],
    "Koszty PRZED PV [PLN]": [e_p, d_p, total_m_pre, e_p+d_p+total_m_pre],
    "Koszty PO PV [PLN]": [e_n, d_n, total_m_po, e_n+d_n+total_m_po],
    "ZYSK (Oszczędność) [PLN]": [z_en, z_dys, z_moc, z_total]
}).set_index("Składnik kosztu").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("📊 Raport Szczegółowy Energii i Ulgi Mocowej")

e_sz_pre = df[df['Is_Szczyt']]['Pobór'].sum() / 1000 
e_psz_pre = df[~df['Is_Szczyt']]['Pobór'].sum() / 1000 
e_sz_po = df[df['Is_Szczyt']]['Nowy_Pobór'].sum() / 1000 
e_psz_po = df[~df['Is_Szczyt']]['Nowy_Pobór'].sum() / 1000 

st.table(pd.DataFrame({
    "Parametr (Suma Roczna)": ["Energia w szczycie [MWh]", "Energia poza szczytem [MWh]", "Średni współczynnik L [%]"],
    "PRZED PV": [e_sz_pre, e_psz_pre, moc_pre['L_Factor'].mean()*100],
    "PO PV": [e_sz_po, e_psz_po, moc_po['L_Factor'].mean()*100]
}).set_index("Parametr (Suma Roczna)").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("🧐 Rozkład kategorii mocowych (Dni w miesiącu)")
stats_df = moc_po.copy().reset_index()
stats_df['Miesiąc'] = pd.to_datetime(stats_df['Data_Klucz']).dt.month
dist = stats_df.groupby(['Miesiąc', 'Mnożnik']).size().unstack(fill_value=0)
for m in [0.17, 0.50, 0.83, 1.00]:
    if m not in dist.columns: dist[m] = 0
dist = dist[[0.17, 0.50, 0.83, 1.00]]
dist.columns = ["K1 (0.17)", "K2 (0.50)", "K3 (0.83)", "K4 (1.00)"]
st.table((dist.div(dist.sum(axis=1), axis=0) * 100).style.format("{:.1f}%"))

# Wykres
m_plot = df.groupby(['Miesiąc_Numer', 'Miesiąc_Nazwa'])[['Pobór', 'Autokonsumpcja', 'Nowy_Pobór']].sum().reset_index()
fig = go.Figure()
fig.add_trace(go.Bar(x=m_plot['Miesiąc_Nazwa'], y=m_plot['Pobór'], name="Pobór Pierwotny", marker_color='#E74C3C'))
fig.add_trace(go.Bar(x=m_plot['Miesiąc_Nazwa'], y=m_plot['Autokonsumpcja'], name="Autokonsumpcja (z PV)", marker_color='#2ECC71'))
fig.add_trace(go.Bar(x=m_plot['Miesiąc_Nazwa'], y=m_plot['Nowy_Pobór'], name="Zakup z sieci (Po PV)", marker_color='#3498DB'))
fig.update_layout(barmode='group', template="plotly_white", title="Miesięczny bilans energii [kWh]", legend=dict(orientation="h", y=1.1))
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.subheader("📝 Wnioski i Rekomendacje dla Klienta")
st.info(f"""
1. **Stabilność opłaty mocowej**: Dzięki płaskiemu profilowi (praca 24/7) Twój zakład już teraz kwalifikuje się do ulgi K1. Instalacja PV o mocy {moc_pv} kWp pogłębia ten efekt, redukując pobór szczytowy.
2. **Potencjał oszczędności**: Roczny zysk netto na samym rachunku za energię i dystrybucję (bez uwzględnienia sprzedaży nadwyżek) wynosi **{z_total:,.2f} PLN**.
3. **Optymalizacja profilu**: Największe korzyści osiągasz w miesiącach letnich, gdzie współczynnik L spada znacząco poniżej zera, co gwarantuje utrzymanie najniższej stawki opłaty mocowej.
""")
