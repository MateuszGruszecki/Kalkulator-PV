import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kalkulator PV B2B - Metodologia 2026", layout="wide")
st.title("⚡ Analiza PV B2B: Opłata Mocowa wg Metodologii 2026")

# --- PARAMETRY USTAWOWE 2026 ---
STAWKA_MOCOWA_BAZOWA = 0.2194 # 219,40 zł/MWh netto
WSPOLNE_NETTO = 0.04346 # Kogeneracyjna, OZE, Jakościowa (Netto 2026)

# Grupy i mnożniki
MOC_GROUPS = {
    "K1": {"limit": 0.05, "mn": 0.17, "desc": "Różnica < 5%"},
    "K2": {"limit": 0.10, "mn": 0.50, "desc": "Różnica 5-10%"},
    "K3": {"limit": 0.15, "mn": 0.83, "desc": "Różnica 10-15%"},
    "K4": {"limit": 1.00, "mn": 1.00, "desc": "Różnica > 15%"}
}

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia Symulacji")
data_type = st.sidebar.radio("Typ danych wejściowych:", ["15-minutowe", "Godzinowe"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=500.0) 
uzysk = st.sidebar.number_input("Uzysk roczny (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj CSV klienta (Data;Czas;Wartość)", type=['csv'])

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
        else:
            df = pd.DataFrame({'Timestamp': pd.to_datetime(df_raw.iloc[:, 0], dayfirst=True, errors='coerce'), 'Pobór': pd.to_numeric(df_raw.iloc[:, 1], errors='coerce').fillna(0)}).dropna(subset=['Timestamp'])
        if len(df) > 0: st.success(f"Dane wczytane poprawnie ({len(df)} h).")
    except Exception as e: st.error(f"Błąd: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(500, 1500, 8760)})

# --- LOGIKA KALENDARZA 2026 ---
def is_polish_holiday(dt):
    holidays = [
        (1, 1), (1, 6), # Nowy Rok, Trzech Króli
        (4, 5), (4, 6), # Wielkanoc 2026
        (5, 1), (5, 3), # Majówka
        (5, 24),        # Zielone Świątki
        (6, 4),         # Boże Ciało
        (8, 15),        # Wniebowzięcie
        (11, 1), (11, 11), # Wszystkich Świętych, Niepodległości
        (25, 12), (26, 12) # Boże Narodzenie
    ]
    return (dt.month, dt.day) in holidays

df['Is_Holiday'] = df['Timestamp'].apply(is_polish_holiday)
df['Roboczy'] = (df['Timestamp'].dt.weekday < 5) & (~df['Is_Holiday'])
df['Godzina'] = df['Timestamp'].dt.hour
df['Data'] = df['Timestamp'].dt.date

# --- SYMULACJA PV ---
weights = {1: 0.3, 2: 0.5, 3: 0.9, 4: 1.2, 5: 1.5, 6: 1.6, 7: 1.6, 8: 1.4, 9: 1.0, 10: 0.6, 11: 0.3, 12: 0.2}
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Gen_Raw'] = sin_p * df['Timestamp'].dt.month.map(weights)
total_gen_raw = df['Gen_Raw'].sum()
df['Generacja_PV'] = (df['Gen_Raw'] / total_gen_raw) * (moc_pv * uzysk * (len(df)/8760)) if total_gen_raw > 0 else 0

df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Autokonsumpcja'])
df['Eksport'] = np.maximum(0, df['Generacja_PV'] - df['Pobór'])

# --- ANALIZA MOCOWA DOBOWA ---
df['Is_Peak'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def get_daily_mocowa_cost(sub_df, col):
    if not sub_df['Roboczy'].any(): return 0.0, 0.17 # Weekendy/Święta = brak opłaty, domyślnie K1
    
    e_peak = sub_df[sub_df['Is_Peak']][col].sum()
    e_off = sub_df[~sub_df['Is_Peak']][col].sum()
    
    p_peak = e_peak / 15
    p_off = e_off / 9
    
    if p_off < 0.001: delta = 100.0 # Brak poboru w nocy = K4
    else: delta = ((p_peak / p_off) - 1) * 100
    
    if delta < 5: mn = 0.17
    elif delta < 10: mn = 0.50
    elif delta < 15: mn = 0.83
    else: mn = 1.00
    
    return e_peak * STAWKA_MOCOWA_BAZOWA * mn, mn

mocowa_stats_po = df.groupby('Data').apply(lambda x: pd.Series(get_daily_mocowa_cost(x, 'Nowy_Pobór')))
mocowa_stats_pre = df.groupby('Data').apply(lambda x: pd.Series(get_daily_mocowa_cost(x, 'Pobór')))

total_m_po = mocowa_stats_po[0].sum()
total_m_pre = mocowa_stats_pre[0].sum()

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

def calc_base_costs(col):
    e_cost = df[col].sum() * (cena_mwh / 1000)
    d_cost = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    return e_cost, d_cost

e_pre, d_pre = calc_base_costs('Pobór')
e_po, d_po = calc_base_costs('Nowy_Pobór')

# --- WYNIKI ---
st.subheader("💰 Podsumowanie Oszczędności Rocznych (Netto 2026)")
res_df = pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja zmienna", "Opłata mocowa (DOBOWA)", "SUMA"],
    "PRZED PV [PLN]": [e_pre, d_pre, total_m_pre, e_pre+d_pre+total_m_pre],
    "PO PV [PLN]": [e_po, d_po, total_m_po, e_po+d_po+total_m_po],
    "ZYSK [PLN]": [e_pre-e_po, d_pre-d_po, total_m_pre-total_m_po, (e_pre+d_pre+total_m_pre)-(e_po+d_po+total_m_po)]
}).set_index("Składnik")
st.table(res_df.style.format("{:,.2f}"))

st.markdown("---")
st.subheader("🧐 Rozkład Kategorii Mocowych (Udział dni w miesiącu)")
st.caption("Poniższa tabela pokazuje, przez ile dni w danym miesiącu instalacja PV „zbiła” profil klienta do konkretnej grupy (K1=0.17, K4=1.00).")

mocowa_stats_po['Month'] = pd.to_datetime(mocowa_stats_po.index).month
dist = mocowa_stats_po.groupby(['Month', 1]).size().unstack().fillna(0)
dist.columns = [f"K{list(MOC_GROUPS.keys())[i]} ({m})" for i, m in enumerate([0.17,
