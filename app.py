import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Autokonsumpcja", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD (Netto 2026) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194 # 219,40 zł/MWh netto

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
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

# --- OBLICZENIA BILANSU ---
df['Godzina'] = df['Timestamp'].dt.hour
df['Roboczy'] = df['Timestamp'].dt.weekday < 5

# Generacja PV
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
sin_sum = sin_p.sum()
df['Generacja_PV'] = (sin_p / sin_sum * (moc_pv * uzysk * (len(df)/8760))) if sin_sum > 0 else 0

# Rozliczenie Autokonsumpcji i Nadwyżek
df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nadwyżka_PV'] = np.maximum(0, df['Generacja_PV'] - df['Pobór'])
df['Nowy_Pobór'] = df['Pobór'] - df['Autokonsumpcja']

# Statystyki energii
total_pv = df['Generacja_PV'].sum()
total_auto = df['Autokonsumpcja'].sum()
total_nadwyzka = df['Nadwyżka_PV'].sum()
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

# --- WYŚWIETLANIE WYNIKÓW ---
st.header(f"📊 Bilans Energii i Oszczędności: {osd_choice} {taryfa_choice}")

# Wskaźniki autokonsumpcji
c1, c2, c3 = st.columns(3)
c1.metric("Produkcja PV", f"{total_pv/1000:,.1f} MWh")
c2.metric("Autokonsumpcja", f"{total_auto/1000:,.1f} MWh", f"{auto_ratio:.1f}%")
c3.metric("Nadwyżki (Eksport)", f"{total_nadwyzka/1000:,.1f} MWh")

# Główna tabela kosztów
st.subheader("💰 Oszczędności na rachunku (Netto)")
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja zmienna", "Opłata mocowa", "RAZEM"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, e_n+d_n+m_n],
    "OSZCZĘDNOŚĆ [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Składnik").style.format("{:,.2f}"))

# Przywrócona tabela kategorii mocowych (K1-K4)
st.markdown("---")
st.subheader("⚡ Dokładne zestawienie opłaty mocowej wg kategorii (K1-K4)")
col_m1, col_m2 = st.columns(2)

def gen_moc_table(sz, mn_act):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({
        "Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"],
        "Stawka [zł/kWh]": [OPLATA_MOCOWA_NETTO * m for m in mns],
        "Roczny Koszt [PLN]": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]
    })
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_act == mns[x.name] else '' for _ in x], axis=1).format({"Stawka [zł/kWh]": "{:.4f}", "Roczny Koszt [PLN]": "{:,.2f}"})

with col_m1:
    st.write(f"**PRZED PV** (Pobór w godz. mocowych: {sz_p/1000:,.2f} MWh)")
    st.table(gen_moc_table(sz_p, mn_p))

with col_m2:
    st.write(f"**PO PV** (Pobór w godz. mocowych: {sz_n/1000:,.2f} MWh)")
    st.table(gen_moc_table(sz_n, mn_n))

# Wykres profilu dobowego
st.markdown("---")
avg = df.groupby('Godzina')[['Pobór', 'Autokonsumpcja', 'Generacja_PV', 'Nadwyżka_PV']].mean().reindex(range(24)).fillna(0)
fig = go.Figure()
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Pobór'], name="Pobór przed PV", line=dict(color='red', width=2)))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Autokonsumpcja'], name="Autokonsumpcja (zysk)", marker_color='green'))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Nadwyżka_PV'], name="Nadwyżka (eksport)", marker_color='rgba(255, 165, 0, 0.4)'))
fig.update_layout(title="Średni profil dobowy (kWh) - Bilans energii", barmode='stack', template="plotly_white", xaxis=dict(dtick=1))
st.plotly_chart(fig, use_container_width=True)
