import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD 2026 (WARTOŚCI NETTO PLN/kWh) ---
WSPOLNE_NETTO = 0.04346 # Jakościowa + OZE + Kogen (Netto 2026)
OPLATA_MOCOWA_NETTO = 0.2194 # 219,40 zł/MWh netto

osd_data = {
    "PGE": {
        "B21": {"całodobowa": 0.06446}, # Dane netto
        "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467},
        "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}
    },
    "Tauron": {
        "B21": {"całodobowa": 0.07114}, # Dane netto
        "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042},
        "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}
    },
    "Enea": {
        "B21": {"całodobowa": 0.06820},
        "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210},
        "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}
    },
    "Stoen": {
        "B21": {"całodobowa": 0.06150},
        "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840},
        "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}
    }
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja (Netto)")
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil klienta (CSV)", type=['csv'])

# --- PANCERNY MECHANIZM WCZYTYWANIA CSV ---
df = None
if uploaded_file is not None:
    try:
        raw_bytes = uploaded_file.read()
        # Próba odczytu w różnych kodowaniach (rozwiązuje błąd UnicodeDecodeError)
        for enc in ['cp1250', 'utf-8-sig', 'utf-8']:
            try:
                decoded = raw_bytes.decode(enc)
                # sep=None automatycznie wykrywa średnik vs przecinek
                df_raw = pd.read_csv(io.StringIO(decoded), sep=None, engine='python', decimal=',')
                break
            except: continue
        
        # Standaryzacja kolumn na podstawie image_98d8a3.png (Data, Godzina, Wartość)
        if df_raw.shape[1] >= 3:
            # Tworzymy pełną datę z dwóch pierwszych kolumn
            df_raw['Timestamp'] = pd.to_datetime(df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str), dayfirst=True)
            # Trzecia kolumna to zużycie
            df_raw['Val'] = pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            
            # Agregacja danych 15-minutowych do pełnych godzin
            df_hourly = df_raw.set_index('Timestamp')['Val'].resample('1H').sum().reset_index()
            df = pd.DataFrame({
                "Data_Czas": df_hourly['Timestamp'],
                "Pobór": df_hourly['Val']
            })
            st.success(f"Pomyślnie przetworzono dane 15-minutowe na {len(df)} godzin.")
        else:
            st.error("Plik ma nieprawidłową strukturę kolumn.")
            
        df = df.head(8760).reset_index(drop=True)
    except Exception as e:
        st.error(f"Nie udało się wczytać pliku: {e}")

# Jeśli brak pliku, używamy profilu testowego
if df is None:
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Data_Czas": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA ---
df['Godzina'] = df['Data_Czas'].dt.hour
df['Roboczy'] = df['Data_Czas'].dt.weekday < 5
df['Generacja_PV'] = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
df['Generacja_PV'] = (df['Generacja_PV'] / df['Generacja_PV'].sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# Logika stref
def przypisz_strefe(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        if 7 <= h < 13: return "przedpołudnie"
        if 16 <= h < 21: return "popołudnie"
        return "pozostałe"
    return "całodobowa"

df['Strefa'] = df.apply(przypisz_strefe, axis=1)
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def kalkuluj(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.5 if delta < 0.10 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = kalkuluj('Pobór')
e_n, d_n, m_n, mn_n, sz_n = kalkuluj('Nowy_Pobór')

# --- PREZENTACJA ---
st.header(f"📉 Raport Kosztów: {osd_choice} {taryfa_choice} (Netto 2026)")
st.table(pd.DataFrame({
    "Kategoria": ["Energia Czynna", "Dystrybucja", "Opłata Mocowa", "SUMA"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Kategoria").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("⚡ Szczegółowa Analiza Opłaty Mocowej (K1-K4)")
c1, c2 = st.columns(2)
def tab_moc(sz, mn_a):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt [PLN]": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_a == mns[x.name] else '' for _ in x], axis=1).format({"Koszt [PLN]": "{:,.2f}"})

with c1:
    st.write(f"**PRZED PV** (Pobór mocowy: {sz_p/1000:,.2f} MWh)")
    st.table(tab_moc(sz_p, mn_p))
with c2:
    st.write(f"**PO PV** (Pobór mocowy: {sz_n/1000:,.2f} MWh)")
    st.table(tab_moc(sz_n, mn_n))

# Wykres
avg = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg.index, y=avg['Pobór'], name="Przed", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg.index, y=avg['Nowy_Pobór'], name="Po", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg.index, y=avg['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", xaxis_title="Godzina", template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
