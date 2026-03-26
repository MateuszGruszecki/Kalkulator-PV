import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# PRÓBA IMPORTU HOLIDAYS (BEZPIECZNIK)
try:
    import holidays
    pl_holidays = holidays.Poland()
    HAS_HOLIDAYS = True
except ImportError:
    HAS_HOLIDAYS = False

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kalkulator PV B2B - Chronologia", layout="wide")
st.title("⚡ Analiza PV B2B: Raport Chronologiczny (2024-2026)")

# --- PARAMETRY ---
STAWKA_MOCOWA_BAZOWA = 0.2194 
WSPOLNE_NETTO = 0.04346 

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia")
data_type = st.sidebar.radio("Typ danych:", ["15-minutowe", "Godzinowe"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=500.0) 
uzysk = st.sidebar.number_input("Uzysk roczny (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj CSV klienta", type=['csv'])

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
        if len(df) > 0: st.success(f"Zakres danych: {df['Timestamp'].min().date()} do {df['Timestamp'].max().date()}")
    except Exception as e: st.error(f"Błąd pliku: {e}")

if df is None:
    dates = pd.date_range("2024-07-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(1000, 3000, 8760)})

# --- LOGIKA DAT I CHRONOLOGII ---
def check_holiday(dt):
    if HAS_HOLIDAYS: return dt in pl_holidays
    h_manual = [(1,1),(1,6),(5,1),(5,3),(8,15),(11,1),(11,11),(12,25),(12,26)]
    return (dt.month, dt.day) in h_manual

df['Data_Klucz'] = df['Timestamp'].dt.date
df['Roboczy'] = (df['Timestamp'].dt.weekday < 5) & (~df['Timestamp'].apply(check_holiday))
df['Godzina'] = df['Timestamp'].dt.hour
df['Rok_Miesiac'] = df['Timestamp'].dt.to_period('M')
df['Etykieta_Miesiac'] = df['Timestamp'].dt.strftime('%Y-%m')

# --- PV ---
weights = {1:0.3, 2:0.5, 3:0.9, 4:1.2, 5:1.5, 6:1.6, 7:1.6, 8:1.4, 9:1.0, 10:0.6, 11:0.3, 12:0.2}
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Gen_Raw'] = sin_p * df['Timestamp'].dt.month.map(weights)
total_gen_raw = df['Gen_Raw'].sum()
df['Generacja_PV'] = (df['Gen_Raw'] / total_gen_raw) * (moc_pv * uzysk * (len(df)/8760)) if total_gen_raw > 0 else 0

df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Autokonsumpcja'])

# --- OPŁATA MOCOWA (METODOLOGIA 2026) ---
df['Is_Szczyt'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def get_moc_daily(sub_df, col):
    if not sub_df['Roboczy'].any(): return pd.Series({'Koszt': 0.0, 'Mnożnik': 0.17, 'L': 0.0})
    e_sz = sub_df[sub_df['Is_Szczyt']][col].sum()
    e_d = sub_df[col].sum()
    if e_d < 0.1: return pd.Series({'Koszt': 0.0, 'Mnożnik': 0.17, 'L': 0.0})
    l_f = (e_sz / e_d) - 0.625
    if l_f <= 0.05: mn = 0.17
    elif l_f <= 0.10: mn = 0.50
    elif l_f <= 0.15: mn = 0.83
    else: mn = 1.00
    return pd.Series({'Koszt': e_sz * STAWKA_MOCOWA_BAZOWA * mn, 'Mnożnik': mn, 'L': l_f})

moc_po = df.groupby('Data_Klucz').apply(lambda x: get_moc_daily(x, 'Nowy_Pobór'))
moc_pre = df.groupby('Data_Klucz').apply(lambda x: get_moc_daily(x, 'Pobór'))

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

def calc_main(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    return en, dys

e_pre, d_pre = calc_main('Pobór')
e_po, d_po = calc_main('Nowy_Pobór')
total_m_pre = moc_pre['Koszt'].sum()
total_m_po = moc_po['Koszt'].sum()

# --- WYNIKI ---
st.subheader(f"💰 Bilans za okres: {df['Timestamp'].min().date()} — {df['Timestamp'].max().date()}")
z_en, z_dys, z_moc = e_pre-e_po, d_pre-d_po, total_m_pre-total_m_po
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja zmienna", "Opłata mocowa", "RAZEM"],
    "PRZED PV [PLN]": [e_pre, d_pre, total_m_pre, e_pre+d_pre+total_m_pre],
    "PO PV [PLN]": [e_po, d_po, total_m_po, e_po+d_po+total_m_po],
    "ZYSK [PLN]": [z_en, z_dys, z_moc, z_en+z_dys+z_moc]
}).set_index("Składnik").style.format("{:,.2f}"))

# WYKRES CHRONOLOGICZNY (LIP 2024 -> LIP 2025)
st.markdown("---")
m_plot = df.groupby('Rok_Miesiac').agg({
    'Pobór': 'sum',
    'Autokonsumpcja': 'sum',
    'Nowy_Pobór': 'sum',
    'Etykieta_Miesiac': 'first'
}).reset_index()

fig = go.Figure()
fig.add_trace(go.Bar(x=m_plot['Etykieta_Miesiac'], y=m_plot['Pobór'], name="Pobór Pierwotny", marker_color='#E74C3C'))
fig.add_trace(go.Bar(x=m_plot['Etykieta_Miesiac'], y=m_plot['Autokonsumpcja'], name="Autokonsumpcja", marker_color='#2ECC71'))
fig.add_trace(go.Bar(x=m_plot['Etykieta_Miesiac'], y=m_plot['Nowy_Pobór'], name="Zakup z sieci", marker_color='#3498DB'))
fig.update_layout(barmode='group', template="plotly_white", title="Chronologiczny Bilans Energii", xaxis_title="Miesiąc (Chronologicznie)")
st.plotly_chart(fig, use_container_width=True)

# TABELA KATEGORII
st.markdown("---")
st.subheader("🧐 Rozkład kategorii mocowych (Dni w miesiącu)")
stats_df = moc_po.copy().reset_index()
stats_df['Rok_Miesiac'] = pd.to_datetime(stats_df['Data_Klucz']).dt.to_period('M')
dist = stats_df.groupby(['Rok_Miesiac', 'Mnożnik']).size().unstack(fill_value=0)
for m in [0.17, 0.50, 0.83, 1.00]:
    if m not in dist.columns: dist[m] = 0
dist = dist[[0.17, 0.50, 0.83, 1.00]]
dist.index = dist.index.strftime('%Y-%m')
st.table((dist.div(dist.sum(axis=1), axis=0) * 100).style.format("{:.1f}%"))

# KOMENTARZ
st.markdown("---")
st.subheader("📝 Komentarz Eksperta")
st.info(f"Dzięki analizie chronologicznej widzimy, że instalacja PV {moc_pv} kWp najmocniej wspiera zakład w okresie letnim, gdzie współczynnik L wynosi średnio {moc_po['L'].mean()*100:.2f}%. Chroni to klienta przed wysokimi kosztami mocy przez cały badany okres.")
