import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Pełny Bilans", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- STAŁE (Ceny Netto 2026) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia")
data_type = st.sidebar.radio("Typ danych:", ["15-minutowe (np. licznikowe)", "Godzinowe (profil 1h)"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV", type=['csv'])

# --- WCZYTYWANIE DANYCH ---
df = None
if uploaded_file:
    try:
        raw = uploaded_file.read()
        try: decoded = raw.decode('cp1250')
        except: decoded = raw.decode('utf-8', errors='ignore')
        df_raw = pd.read_csv(io.StringIO(decoded), sep=None, decimal=',', engine='python', header=None, skiprows=1)
        
        if data_type == "15-minutowe (np. licznikowe)":
            temp = pd.DataFrame({'T': pd.to_datetime(df_raw.iloc[:, 0] + ' ' + df_raw.iloc[:, 1], dayfirst=True, errors='coerce'), 'V': pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)})
            df = temp.dropna().set_index('T')['V'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'T': 'Timestamp'})
        else:
            df = pd.DataFrame({'Timestamp': pd.to_datetime(df_raw.iloc[:, 0], dayfirst=True), 'Pobór': pd.to_numeric(df_raw.iloc[:, 1], errors='coerce').fillna(0)}).dropna()
    except Exception as e: st.error(f"Błąd pliku: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA BILANSU ---
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5

# Generacja PV
sin_profile = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
sin_sum = sin_profile.sum()
if sin_sum > 0:
    df['Generacja_PV'] = (sin_profile / sin_sum) * (moc_pv * uzysk)
else:
    df['Generacja_PV'] = 0

# KLUCZOWE WSKAŹNIKI:
df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Eksport'] = np.maximum(0, df['Generacja_PV'] - df['Pobór'])
df['Nowy_Pobór'] = df['Pobór'] - df['Autokonsumpcja']

# Sumy roczne
total_pobor = df['Pobór'].sum()
total_pv = df['Generacja_PV'].sum()
total_auto = df['Autokonsumpcja'].sum()
total_eksport = df['Eksport'].sum()
auto_ratio = (total_auto / total_pv * 100) if total_pv > 0 else 0

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

def calc(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    total_m = sz_m + pz_m
    delta = (sz_m - pz_m) / total_m if total_m > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.5 if delta < 0.1 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = calc('Pobór')
e_n, d_n, m_n, mn_n, sz_n = calc('Nowy_Pobór')

# --- PREZENTACJA ---
st.header(f"📊 Bilans Energetyczny i Finansowy: {osd_choice} {taryfa_choice}")

# Kafelki z autokonsumpcją
c1, c2, c3, c4 = st.columns(4)
c1.metric("Produkcja PV", f"{total_pv/1000:,.1f} MWh")
c2.metric("Autokonsumpcja", f"{total_auto/1000:,.1f} MWh", f"{auto_ratio:.1f}%")
c3.metric("Eksport do sieci", f"{total_eksport/1000:,.1f} MWh")
c4.metric("Zredukowany pobór", f"{(total_pobor-total_auto)/1000:,.1f} MWh")

if auto_ratio < 20:
    st.warning(f"⚠️ Bardzo niska autokonsumpcja ({auto_ratio:.1f}%). System jest mocno przewymiarowany względem bieżącego zużycia.")

# Tabela Finansowa
st.subheader("💰 Oszczędności na rachunku (Netto)")
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, e_n+d_n+m_n],
    "OSZCZĘDNOŚĆ [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Składnik").style.format("{:,.2f}"))

# Analiza Mocowa K1-K4
st.markdown("---")
st.subheader("⚡ Opłata Mocowa i Kategorie")
col_m1, col_m2 = st.columns(2)
def draw_m(sz, mn_a):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_a == mns[x.name] else '' for _ in x], axis=1).format({"Koszt": "{:,.2f}"})

col_m1.write(f"**PRZED PV** (Mocowy: {sz_p/1000:,.2f} MWh)")
col_m1.table(draw_m(sz_p, mn_p))
col_m2.write(f"**PO PV** (Mocowy: {sz_n/1000:,.2f} MWh)")
col_m2.table(draw_m(sz_n, mn_n))

# Wykres profilu
st.markdown("---")
avg = df.groupby('Godzina')[['Pobór', 'Autokonsumpcja', 'Generacja_PV', 'Eksport']].mean().reindex(range(24)).fillna(0)
fig = go.Figure()
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Pobór'], name="Pobór z sieci (oryginalny)", line=dict(color='red', width=3)))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Autokonsumpcja'], name="Autokonsumpcja (zysk bezpośredni)", marker_color='green'))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Eksport'], name="Eksport (nadprodukcja)", marker_color='rgba(255, 165, 0, 0.4)'))
fig.update_layout(title="Średniodobowy bilans energii (kWh)", barmode='stack', template="plotly_white", xaxis=dict(dtick=1, title="Godzina"))
st.plotly_chart(fig, use_container_width=True)
