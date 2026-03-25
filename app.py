import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - ROI & Bilans", layout="wide")
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
st.sidebar.header("⚙️ Konfiguracja")
data_type = st.sidebar.radio("Tryb pliku:", ["15-minutowy", "Godzinowy"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)

st.sidebar.markdown("---")
st.sidebar.header("☀️ System Fotowoltaiczny")
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk roczny (kWh/kWp)", value=1000.0)
koszt_kwp = st.sidebar.number_input("Koszt instalacji (PLN netto / kWp)", value=3200.0)
cena_sprzedazy = st.sidebar.number_input("Cena sprzedaży nadwyżek (PLN/MWh)", value=350.0)

uploaded_file = st.sidebar.file_uploader("Wgraj dane klienta (CSV)", type=['csv'])

# --- WCZYTYWANIE I NAPRAWA KOLUMN ---
df = None
if uploaded_file:
    try:
        raw = uploaded_file.read()
        try: decoded = raw.decode('cp1250')
        except: decoded = raw.decode('utf-8', errors='ignore')
        df_raw = pd.read_csv(io.StringIO(decoded), sep=';', decimal=',', engine='python', header=None, skiprows=1)
        
        if data_type == "15-minutowy":
            temp = pd.DataFrame({
                'T': pd.to_datetime(df_raw.iloc[:, 0] + ' ' + df_raw.iloc[:, 1], dayfirst=True, errors='coerce'),
                'V': pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            }).dropna()
            df = temp.set_index('T')['V'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'T': 'Timestamp'})
        else:
            df = pd.DataFrame({'Timestamp': pd.to_datetime(df_raw.iloc[:, 0], dayfirst=True), 'Pobór': pd.to_numeric(df_raw.iloc[:, 1], errors='coerce').fillna(0)}).dropna()
        
        if len(df) > 0:
            st.success(f"Wczytano {len(df)} godzin danych.")
    except Exception as e: st.error(f"Problem z plikiem: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(50, 150, 8760)})

# --- OBLICZENIA BILANSU (Zawsze tworzymy te kolumny!) ---
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5

# Symulacja produkcji
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
sin_sum = sin_p.sum()
df['Generacja_PV'] = (sin_p / sin_sum * (moc_pv * uzysk * (len(df)/8760))) if sin_sum > 0 else 0

# Rozliczenie Autokonsumpcji
df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Eksport'] = np.maximum(0, df['Generacja_PV'] - df['Pobór'])
df['Nowy_Pobór'] = df['Pobór'] - df['Autokonsumpcja']

# Statystyki
total_pobor = df['Pobór'].sum()
total_pv = df['Generacja_PV'].sum()
total_auto = df['Autokonsumpcja'].sum()
total_eks = df['Eksport'].sum()
auto_proc = (total_auto / total_pv * 100) if total_pv > 0 else 0

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

zysk_rachunek = (e_p + d_p + m_p) - (e_n + d_n + m_n)
przychody_eksport = total_eks * (cena_sprzedazy / 1000)
laczny_zysk = zysk_rachunek + przychody_eksport
koszt_caly = moc_pv * koszt_kwp
roi = koszt_caly / laczny_zysk if laczny_zysk > 0 else 0

# --- WYNIKI ---
st.header("📊 Raport Energetyczno-Finansowy")

# Wskaźniki
k1, k2, k3, k4 = st.columns(4)
k1.metric("Autokonsumpcja", f"{auto_proc:.1f}%")
k2.metric("Oszczędność rachunku", f"{zysk_rachunek:,.2f} zł")
k3.metric("Przychód z eksportu", f"{przychody_eksport:,.2f} zł")
k4.metric("Czas zwrotu (ROI)", f"{roi:.1f} lat")

if auto_proc < 15:
    st.error(f"⚠️ Uwaga: System jest bardzo przewymiarowany. Klient zużywa tylko {auto_proc:.1f}% energii na miejscu. Rozważ mniejszą moc lub magazyn energii.")

# Tabela
st.subheader("💰 Szczegóły Oszczędności (Netto)")
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "Zysk z Eksportu", "SUMA KORZYŚCI"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, 0, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, przychody_eksport * -1, (e_n+d_n+m_n) - przychody_eksport],
    "KORZYŚĆ [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, przychody_eksport, laczny_zysk]
}).set_index("Składnik").style.format("{:,.2f}"))

# Wykres
st.markdown("---")
avg = df.groupby('Godzina')[['Pobór', 'Autokonsumpcja', 'Generacja_PV', 'Eksport']].mean().reindex(range(24)).fillna(0)
fig = go.Figure()
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Pobór'], name="Oryginalny Pobór", line=dict(color='red', width=2)))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Autokonsumpcja'], name="Autokonsumpcja", marker_color='green'))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Eksport'], name="Eksport (Nadprodukcja)", marker_color='rgba(255, 165, 0, 0.4)'))
fig.update_layout(title="Średni profil dobowy (kWh) - Bilans", barmode='stack', template="plotly_white", xaxis=dict(dtick=1))
st.plotly_chart(fig, use_container_width=True)
