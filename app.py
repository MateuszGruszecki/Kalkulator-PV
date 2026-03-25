import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- STAŁE (Netto 2026) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194 # 219,40 zł/MWh netto

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

uploaded_file = st.sidebar.file_uploader("Wgraj Twój plik CSV (15- min.csv)", type=['csv'])

# --- LOGIKA WCZYTYWANIA I SYNCHRONIZACJI ---
main_df = None

if uploaded_file:
    try:
        # 1. Wczytanie z kodowaniem polskiego Excela
        raw = uploaded_file.read()
        df_raw = pd.read_csv(io.BytesIO(raw), sep=';', encoding='cp1250', decimal=',', engine='python')
        
        # 2. Wybieramy kolumny po pozycji: 0 (Data), 1 (Czas), 2 (Wartość)
        dane = pd.DataFrame({
            'TS': pd.to_datetime(df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str), dayfirst=True, errors='coerce'),
            'Val': pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
        }).dropna(subset=['TS'])

        # 3. Agregacja 15 min -> 1h (Resample gwarantuje ciągłość czasu)
        main_df = dane.set_index('TS')['Val'].resample('1H').sum().reset_index()
        main_df.columns = ['Timestamp', 'Pobór']
        
        st.success(f"Pomyślnie wczytano dane: {len(main_df)} godzin.")
    except Exception as e:
        st.error(f"Nie udało się odczytać pliku: {e}")

# Dane testowe (awaryjne)
if main_df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    main_df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA (Gwarantowana zgodność długości) ---
main_df['Godzina'] = main_df['Timestamp'].dt.hour
main_df['Roboczy'] = main_df['Timestamp'].dt.weekday < 5

# Produkcja PV (Dopasowana DOKŁADNIE do długości wczytanego pliku)
sin_curve = np.maximum(0, np.sin((main_df['Godzina'] - 6) * np.pi / 12))
# Produkcja roczna skalowana do długości danych w pliku
total_prod_for_period = (moc_pv * uzysk) * (len(main_df) / 8760)
main_df['Generacja_PV'] = (sin_curve / sin_curve.sum() * total_prod_for_period) if sin_curve.sum() > 0 else 0
main_df['Nowy_Pobór'] = np.maximum(0, main_df['Pobór'] - main_df['Generacja_PV'])

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

main_df['Strefa'] = main_df.apply(get_strefa, axis=1)
main_df['Godzina_Mocowa'] = (main_df['Godzina'] >= 7) & (main_df['Godzina'] < 22) & main_df['Roboczy']

# Kalkulacja
def calc(col):
    en = main_df[col].sum() * (cena_mwh / 1000)
    dys = sum(main_df[main_df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = main_df[main_df['Godzina_Mocowa']][col].sum()
    pz_m = main_df[~main_df['Godzina_Mocowa']][col].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.50 if delta < 0.10 else (0.83 if delta < 0.15 else 1.00))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = calc('Pobór')
e_n, d_n, m_n, mn_n, sz_n = calc('Nowy_Pobór')

# --- PREZENTACJA ---
st.header(f"💰 Analiza Wyników (Netto)")

st.table(pd.DataFrame({
    "Kategoria": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Kategoria").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("⚡ Opłata Mocowa K1-K4")
cl, cr = st.columns(2)
def draw_m(sz, mn_a):
    mns = [0.17, 0.50, 0.83, 1.00]
    m_df = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return m_df.style.apply(lambda x: ['background-color: #d1f2d1' if mn_a == mns[x.name] else '' for _ in x], axis=1).format({"Koszt": "{:,.2f}"})

cl.write("**PRZED PV**")
cl.table(draw_m(sz_p, mn_p))
cr.write("**PO PV**")
cr.table(draw_m(sz_n, mn_n))

st.markdown("---")
# Wykres profilu - Agregacja do 24 punktów (Gwarantuje stałą długość)
avg = main_df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean().reindex(range(24)).fillna(0)
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg.index, y=avg['Pobór'], name="Przed PV", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg.index, y=avg['Nowy_Pobór'], name="Po PV", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg.index, y=avg['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", xaxis=dict(dtick=1, title="Godzina"), template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
