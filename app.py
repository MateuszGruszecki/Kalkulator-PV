import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- STAŁE ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Parametry")
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV", type=['csv'])

# --- PANCERNY LOADER ---
df = None
if uploaded_file is not None:
    try:
        # 1. Czytamy bajty i dekodujemy polskim formatem Excela
        raw = uploaded_file.read()
        try:
            text = raw.decode('cp1250')
        except:
            text = raw.decode('utf-8-sig', errors='ignore')
            
        # 2. Czytamy CSV ignorując nazwy kolumn (skiprows=1), używamy pozycji
        # sep=None wykryje ; oraz ,
        df_raw = pd.read_csv(io.StringIO(text), sep=None, engine='python', decimal=',', header=None, skiprows=1)
        
        # 3. Twoja struktura: 0: Data, 1: Czas, 2: Wartość
        vals = pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0).values
        
        # 4. Agregacja 15 min -> 1h (paczki po 4 wiersze)
        num_hours = len(vals) // 4
        hourly_values = [np.sum(vals[i*4 : (i+1)*4]) for i in range(num_hours)]
        
        # 5. Tworzymy oś czasu na podstawie pierwszej daty z pliku
        try:
            start_date = pd.to_datetime(df_raw.iloc[0, 0], dayfirst=True)
        except:
            start_date = pd.Timestamp("2026-01-01")
            
        df = pd.DataFrame({
            "Timestamp": pd.date_range(start=start_date, periods=num_hours, freq='H'),
            "Pobór": hourly_values
        })
        st.success(f"Pomyślnie wczytano {len(df)} godzin danych.")
    except Exception as e:
        st.error(f"Błąd krytyczny pliku: {e}")

# Dane testowe
if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA (Wszystko w jednym DF, by uniknąć błędów długości) ---
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5

# Generacja PV (sinusoida)
sin_curve = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
# Skalujemy słońce do okresu w pliku
total_pv_prod = (moc_pv * uzysk) * (len(df) / 8760)
df['Generacja_PV'] = (sin_curve / sin_curve.sum()) * total_pv_prod if sin_curve.sum() > 0 else 0
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# Strefy
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

def kalkuluj(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    calk = sz_m + pz_m
    delta = (sz_m - pz_m) / calk if calk > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.50 if delta < 0.10 else (0.83 if delta < 0.15 else 1.00))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = kalkuluj('Pobór')
e_n, d_n, m_n, mn_n, sz_n = kalkuluj('Nowy_Pobór')

# --- WYNIKI ---
st.header(f"💰 Wyniki Analizy: {osd_choice} {taryfa_choice} (Netto)")

# Tabela
st.table(pd.DataFrame({
    "Kategoria": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Kategoria").style.format("{:,.2f}"))

# Analiza Mocowa
st.markdown("---")
st.subheader("⚡ Opłata Mocowa K1-K4")
cl, cr = st.columns(2)
def tab_moc(sz, mn_act):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_act == mns[x.name] else '' for _ in x], axis=1).format({"Koszt": "{:,.2f}"})

cl.write("**PRZED PV**")
cl.table(tab_moc(sz_p, mn_p))
cr.write("**PO PV**")
cr.table(tab_moc(sz_n, mn_n))

# Wykres
st.markdown("---")
avg = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean().reset_index()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg['Godzina'], y=avg['Pobór'], name="Przed", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg['Godzina'], y=avg['Nowy_Pobór'], name="Po", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg['Godzina'], y=avg['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", template="plotly_white", xaxis=dict(dtick=1))
st.plotly_chart(fig, use_container_width=True)
