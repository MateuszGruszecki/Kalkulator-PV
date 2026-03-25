import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Analiza PV B2B: Bilans i Opłata Mocowa (Dobowa)")

# --- BAZA OSD ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_STAWKA = 0.2194 # 219,40 zł/MWh netto

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 1.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 1.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia")
data_type = st.sidebar.radio("Tryb danych:", ["15-minutowe", "Godzinowe"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=500.0) 
uzysk = st.sidebar.number_input("Uzysk roczny (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj dane klienta (CSV)", type=['csv'])

# --- WCZYTYWANIE DANYCH ---
df = None
if uploaded_file:
    try:
        raw = uploaded_file.read()
        try: decoded = raw.decode('cp1250')
        except: decoded = raw.decode('utf-8', errors='ignore')
        df_raw = pd.read_csv(io.StringIO(decoded), sep=';', decimal=',', engine='python', header=None, skiprows=1)
        
        if data_type == "15-minutowe":
            temp = pd.DataFrame({'T': pd.to_datetime(df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str), dayfirst=True, errors='coerce'), 'V': pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)})
            df = temp.dropna().set_index('T')['V'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'T': 'Timestamp'})
        else:
            df = pd.DataFrame({'Timestamp': pd.to_datetime(df_raw.iloc[:, 0], dayfirst=True, errors='coerce'), 'Pobór': pd.to_numeric(df_raw.iloc[:, 1], errors='coerce').fillna(0)}).dropna()
        if len(df) > 0: st.success(f"Wczytano {len(df)} h danych.")
    except Exception as e: st.error(f"Błąd pliku: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(100, 300, 8760)})

# --- OBLICZENIA BILANSU ---
df['Data'] = df['Timestamp'].dt.date
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5
df['Miesiąc_Num'] = df['Timestamp'].dt.month
df['Miesiąc'] = df['Timestamp'].dt.strftime('%m - %b')

# Generacja PV (uproszczona sezonowość)
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
weights = {1: 0.3, 2: 0.5, 3: 0.9, 4: 1.2, 5: 1.5, 6: 1.6, 7: 1.6, 8: 1.4, 9: 1.0, 10: 0.6, 11: 0.3, 12: 0.2}
df['Waga'] = df['Timestamp'].dt.month.map(weights)
df['Gen_Raw'] = sin_p * df['Waga']
total_gen_raw = df['Gen_Raw'].sum()
df['Generacja_PV'] = (df['Gen_Raw'] / total_gen_raw) * (moc_pv * uzysk * (len(df)/8760)) if total_gen_raw > 0 else 0

df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Autokonsumpcja'])
df['Eksport'] = np.maximum(0, df['Generacja_PV'] - df['Pobór'])

# --- OPŁATA MOCOWA (LOGIKA DOBOWA) ---
df['Is_Szczyt_Mocowy'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def calculate_daily_mocowa_safe(sub_df, col_name):
    szczyt = float(sub_df[sub_df['Is_Szczyt_Mocowy']][col_name].sum())
    poza_szczyt = float(sub_df[~sub_df['Is_Szczyt_Mocowy']][col_name].sum())
    total = szczyt + poza_szczyt
    
    # Bezpiecznik: jeśli total jest 0 (np. słońce pokryło wszystko lub budynek zamknięty)
    if total < 0.0001:
        return pd.Series([0.0, 0.17], index=['Koszt', 'Mnożnik'])
    
    delta = (szczyt - poza_szczyt) / total
    
    if delta < 0.05: mn = 0.17
    elif delta < 0.10: mn = 0.50
    elif delta < 0.15: mn = 0.83
    else: mn = 1.0
    
    return pd.Series([szczyt * OPLATA_MOCOWA_STAWKA * mn, mn], index=['Koszt', 'Mnożnik'])

# Grupowanie dobowe
mocowa_po = df.groupby('Data').apply(lambda x: calculate_daily_mocowa_safe(x, 'Nowy_Pobór'))
mocowa_pre = df.groupby('Data').apply(lambda x: calculate_daily_mocowa_safe(x, 'Pobór'))

total_mocowa_po = mocowa_po['Koszt'].sum()
total_mocowa_przed = mocowa_pre['Koszt'].sum()

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

def calc_base(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    return en, dys

e_p, d_p = calc_base('Pobór')
e_n, d_n = calc_base('Nowy_Pobór')

# --- WYŚWIETLANIE ---
st.header(f"📊 Analiza Miesięczna i Dobowa: {osd_choice} {taryfa_choice}")

m_df = df.groupby(['Miesiąc_Num', 'Miesiąc'])[['Pobór', 'Autokonsumpcja', 'Nowy_Pobór', 'Eksport']].sum().reset_index()
fig = go.Figure()
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Pobór'], name="Pobór Pierwotny", marker_color='#E74C3C'))
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Autokonsumpcja'], name="Autokonsumpcja", marker_color='#2ECC71'))
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Nowy_Pobór'], name="Zakup po PV", marker_color='#3498DB'))
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Eksport'], name="Nadwyżka (Eksport)", marker_color='#F1C40F', opacity=0.4))
fig.update_layout(barmode='group', template="plotly_white", title="Energia w skali miesiąca [kWh]")
st.plotly_chart(fig, use_container_width=True)

st.subheader("💰 Bilans Oszczędności Rocznych (Netto)")
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja zmienna", "Opłata mocowa (DOBOWA)", "RAZEM"],
    "PRZED PV [PLN]": [e_p, d_p, total_mocowa_przed, e_p+d_p+total_mocowa_przed],
    "PO PV [PLN]": [e_n, d_n, total_mocowa_po, e_n+d_n+total_mocowa_po],
    "ZYSK [PLN]": [e_p-e_n, d_p-d_n, total_mocowa_przed-total_mocowa_po, (e_p+d_p+total_mocowa_przed)-(e_n+d_n+total_mocowa_po)]
}).set_index("Składnik").style.format("{:,.2f}"))

# Analiza K1-K4
st.markdown("---")
st.subheader("🧐 Rozkład kategorii mocowych (Dni w miesiącu)")
st.write("Dzięki PV 500 kWp, w słoneczne dni klient „zeruje” szczyt, wchodząc w kategorię K1 (ulga 83%).")

# Przygotowanie tabeli udziałów kategorii
mocowa_po['Miesiąc'] = pd.to_datetime(mocowa_po.index).month
dist_table = mocowa_po.groupby(['Miesiąc', 'Mnożnik']).size().unstack().fillna(0)
# Zamiana na procenty
dist_table_pct = dist_table.div(dist_table.sum(axis=1), axis=0) * 100
st.table(dist_table_pct.style.format("{:.1f}%"))
