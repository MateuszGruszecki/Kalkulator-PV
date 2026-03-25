import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Naprawa ZeroDivision", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD (Netto 2026) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 1.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia")
data_type = st.sidebar.radio("Typ wczytywanych danych:", ["15-minutowe (np. licznikowe)", "Godzinowe (profil 1h)"])

osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV", type=['csv'])

# --- SYSTEM WCZYTYWANIA I AGREGACJI ---
df = None

if uploaded_file is not None:
    try:
        raw_bytes = uploaded_file.read()
        try:
            decoded_text = raw_bytes.decode('cp1250')
        except:
            decoded_text = raw_bytes.decode('utf-8', errors='ignore')
            
        df_raw = pd.read_csv(io.StringIO(decoded_text), sep=';', decimal=',', engine='python', header=None, skiprows=1)
        
        if data_type == "15-minutowe (np. licznikowe)":
            temp_df = pd.DataFrame({
                'DT_STR': df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str),
                'Val': pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            })
            temp_df['TS'] = pd.to_datetime(temp_df['DT_STR'], dayfirst=True, errors='coerce')
            temp_df = temp_df.dropna(subset=['TS']).set_index('TS')
            df = temp_df['Val'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'TS': 'Timestamp'})
            
        else:
            val_idx = 1 if df_raw.shape[1] >= 2 else 0
            df = pd.DataFrame({
                'Timestamp': pd.to_datetime(df_raw.iloc[:, 0], dayfirst=True, errors='coerce'),
                'Pobór': pd.to_numeric(df_raw.iloc[:, val_idx], errors='coerce').fillna(0)
            }).dropna(subset=['Timestamp'])

        if len(df) == 0:
            st.error("Błąd: Plik po przetworzeniu jest pusty. Sprawdź format daty.")
            df = None
        else:
            st.success(f"Pomyślnie wczytano dane. Liczba godzin: {len(df)}")
    except Exception as e:
        st.error(f"Błąd pliku: {e}")

# Demo jeśli brak pliku lub błąd
if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA (Zabezpieczone przed dzieleniem przez zero) ---
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5

# Słońce
sin_profile = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
sin_sum = sin_profile.sum()
period_prod = (moc_pv * uzysk) * (len(df) / 8760)

if sin_sum > 0:
    df['Generacja_PV'] = (sin_profile / sin_sum) * period_prod
else:
    df['Generacja_PV'] = 0

df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# Strefy
def get_strefa(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        if 7 <= h < 13: return "przedpołudnie"
        if 16 <= h < 21: return "popołudnie"
        return "pozostałe"
    return "całodobowa"

df['Strefa'] = df.apply(get_strefa, axis=1)
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def safe_calc(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    
    total_mocowa = sz_m + pz_m
    if total_mocowa > 0:
        delta = (sz_m - pz_m) / total_mocowa
        mn = 0.17 if delta < 0.05 else (0.50 if delta < 0.10 else (0.83 if delta < 0.15 else 1.00))
    else:
        delta, mn = 0, 0
        
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = safe_calc('Pobór')
e_n, d_n, m_n, mn_n, sz_n = safe_calc('Nowy_Pobór')

# --- WYNIKI ---
st.header(f"💰 Wyniki Analizy: {osd_choice} {taryfa_choice}")

st.table(pd.DataFrame({
    "Kategoria": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "RAZEM"],
    "PRZED PV": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Kategoria").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("⚡ Podział Opłaty Mocowej (K1-K4)")
cl, cr = st.columns(2)

def draw_moc_table(sz, mn_active):
    mns = [0.17, 0.50, 0.83, 1.00]
    m_df = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return m_df.style.apply(lambda x: ['background-color: #d1f2d1' if mn_active == mns[x.name] else '' for _ in x], axis=1).format({"Koszt": "{:,.2f}"})

cl.write("**PRZED PV**")
cl.table(draw_moc_table(sz_p, mn_p))
cr.write("**PO PV**")
cr.table(draw_moc_table(sz_n, mn_n))

st.markdown("---")
avg = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean().reindex(range(24)).fillna(0)
fig = go.Figure()
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Pobór'], name="Przed PV", line=dict(color='red')))
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Nowy_Pobór'], name="Po PV", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", template="plotly_white", xaxis=dict(dtick=1, title="Godzina"))
st.plotly_chart(fig, use_container_width=True)
