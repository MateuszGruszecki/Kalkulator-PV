import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Analiza Miesięczna", layout="wide")
st.title("⚡ Analiza Miesięczna PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD (Netto 2026) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 1.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 1.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia")
data_type = st.sidebar.radio("Tryb danych w pliku:", ["15-minutowe", "Godzinowe"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
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
            temp = pd.DataFrame({
                'T': pd.to_datetime(df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str), dayfirst=True, errors='coerce'),
                'V': pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            }).dropna()
            df = temp.set_index('T')['V'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'T': 'Timestamp'})
        else:
            df = pd.DataFrame({'Timestamp': pd.to_datetime(df_raw.iloc[:, 0], dayfirst=True, errors='coerce'), 'Pobór': pd.to_numeric(df_raw.iloc[:, 1], errors='coerce').fillna(0)}).dropna()
        
        if len(df) > 0:
            st.success(f"Wczytano {len(df)} godzin danych.")
    except Exception as e: st.error(f"Problem z plikiem: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(50, 150, 8760)})

# --- OBLICZENIA BILANSU ---
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5
df['Miesiąc'] = df['Timestamp'].dt.strftime('%m - %B')

# Profil produkcji z wagami sezonowymi
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
monthly_weights = {1: 0.3, 2: 0.5, 3: 0.9, 4: 1.2, 5: 1.5, 6: 1.6, 7: 1.6, 8: 1.4, 9: 1.0, 10: 0.6, 11: 0.3, 12: 0.2}
df['Waga_Mies'] = df['Timestamp'].dt.month.map(monthly_weights)
df['Gen_Raw'] = sin_p * df['Waga_Mies']

# BEZPIECZNIK DZIELENIA PRZEZ ZERO
gen_sum = df['Gen_Raw'].sum()
if gen_sum > 0:
    df['Generacja_PV'] = (df['Gen_Raw'] / gen_sum) * (moc_pv * uzysk * (len(df)/8760))
else:
    df['Generacja_PV'] = 0

df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Autokonsumpcja'])
df['Eksport'] = np.maximum(0, df['Generacja_PV'] - df['Pobór'])

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
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def calc_cost(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    total_m = sz_m + pz_m
    delta = (sz_m - pz_m) / total_m if total_m > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.5 if delta < 0.1 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = calc_cost('Pobór')
e_n, d_n, m_n, mn_n, sz_n = calc_cost('Nowy_Pobór')

# --- PREZENTACJA ---
st.header(f"📈 Analiza Bilansu Miesięcznego: {osd_choice} {taryfa_choice}")

# Agregacja miesięczna
m_df = df.groupby('Miesiąc')[['Pobór', 'Generacja_PV', 'Autokonsumpcja', 'Nowy_Pobór', 'Eksport']].sum().reset_index()

# Wykres Miesięczny
fig = go.Figure()
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Pobór'], name="Pobór Pierwotny", marker_color='#E74C3C'))
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Autokonsumpcja'], name="Autokonsumpcja (zysk)", marker_color='#2ECC71'))
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Nowy_Pobór'], name="Zakup z sieci (Po PV)", marker_color='#3498DB'))
fig.add_trace(go.Bar(x=m_df['Miesiąc'], y=m_df['Eksport'], name="Nadwyżka (Eksport)", marker_color='#F1C40F', opacity=0.6))

fig.update_layout(title="Miesięczne zestawienie energii [kWh]", barmode='group', template="plotly_white", legend=dict(orientation="h", y=1.1))
st.plotly_chart(fig, use_container_width=True)

# Tabela Miesięczna z % pokrycia
st.subheader("📋 Dane szczegółowe za każdy miesiąc")
m_disp = m_df.copy()
m_disp['Stopień Pokrycia (%)'] = (m_disp['Autokonsumpcja'] / m_disp['Pobór'] * 100).fillna(0)
st.table(m_disp.set_index('Miesiąc').style.format("{:,.0f}").format({"Stopień Pokrycia (%)": "{:.1f}%"}))

# Sekcja Finansowa
st.markdown("---")
st.subheader("💰 Oszczędności Roczne (Netto)")
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Składnik").style.format("{:,.2f}"))

# Tabele K1-K4 (Czyste)
col1, col2 = st.columns(2)
def gen_tab(sz, mn_act):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt [PLN]": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return df_m.style.apply(lambda x: ['font-weight: bold; border: 1px solid #ccc' if mn_act == mns[x.name] else '' for _ in x], axis=1).format({"Koszt [PLN]": "{:,.2f}"})

with col1:
    st.write(f"**Mocowa PRZED PV** ({sz_p/1000:,.1f} MWh)")
    st.table(gen_tab(sz_p, mn_p))
with col2:
    st.write(f"**Mocowa PO PV** ({sz_n/1000:,.1f} MWh)")
    st.table(gen_tab(sz_n, mn_n))
