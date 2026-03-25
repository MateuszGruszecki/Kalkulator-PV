import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Finalny Importer", layout="wide")
st.title("⚡ Profesjonalny Kalkulator PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD (Netto 2026) ---
# Składniki wspólne netto (Jakościowa + OZE + Kogen) ok. 0.04153 zł/kWh
WSPOLNE_NETTO = 0.04153 
OPLATA_MOCOWA_NETTO = 0.2194 # 219.40 zł/MWh netto

osd_data = {
    "PGE": {
        "B21": {"całodobowa": 0.06446}, 
        "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467},
        "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}
    },
    "Tauron": {
        "B21": {"całodobowa": 0.07114}, 
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
st.sidebar.header("🛡️ Parametry Analizy")
osd_choice = st.sidebar.selectbox("Wybierz Operatora", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])

st.sidebar.markdown("---")
cena_mwh = st.sidebar.number_input("Stała cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil klienta (CSV)", type=['csv'])

# --- LOGIKA WCZYTYWANIA I AGREGACJI ---
df = None
if uploaded_file:
    try:
        raw_bytes = uploaded_file.read()
        # Próba odczytu z wymuszonym kodowaniem polskiego Excela
        df_raw = pd.read_csv(io.BytesIO(raw_bytes), sep=';', encoding='cp1250', decimal=',', engine='python')
        
        # Wybieramy kolumny po pozycji (0: Data, 1: Czas, 2: kWh), aby uniknąć błędnych nazw nagłówków
        # W Twoim pliku 15-min.csv są 3 kolumny
        if df_raw.shape[1] >= 3:
            data_col = df_raw.iloc[:, 0].astype(str)
            time_col = df_raw.iloc[:, 1].astype(str)
            val_col = pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            
            # Przetwarzamy daty
            ts = pd.to_datetime(data_col + ' ' + time_col, dayfirst=True, errors='coerce')
            
            # Agregacja 15-min -> 1h (suma)
            df_hourly = val_col.groupby(np.arange(len(val_col)) // 4).sum().to_frame(name='Pobór')
            df_hourly['Data_Czas'] = ts.iloc[::4].reset_index(drop=True)
            
            # Cechy czasowe
            df_hourly['Godzina'] = df_hourly['Data_Czas'].dt.hour
            df_hourly['Roboczy'] = df_hourly['Data_Czas'].dt.weekday < 5
            
            df = df_hourly.dropna().head(8760).reset_index(drop=True)
            st.success(f"Wczytano {len(df)} godzin danych z profilu 15-minutowego.")
        else:
            st.error("Nieprawidłowy układ kolumn w pliku CSV.")
    except Exception as e:
        st.error(f"Błąd podczas analizy pliku: {e}")

if df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({
        "Data_Czas": dates,
        "Pobór": np.where((dates.hour >= 8) & (dates.hour <= 17), 50.0, 15.0),
        "Godzina": dates.hour, "Roboczy": dates.weekday < 5
    })

# --- OBLICZENIA PV ---
profil_pv = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
df['Generacja_PV'] = (profil_pv / profil_pv.sum()) * (moc_pv * uzysk)
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

# Kalkulator
def calculate_all(col):
    energia = df[col].sum() * (cena_mwh / 1000)
    dystrybucja = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.50 if delta < 0.10 else (0.83 if delta < 0.15 else 1.00))
    mocowa = sz_m * OPLATA_MOCOWA_NETTO * mn
    return energia, dystrybucja, mocowa, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = calculate_all('Pobór')
e_n, d_n, m_n, mn_n, sz_n = calculate_all('Nowy_Pobór')

# --- PREZENTACJA ---
st.header(f"💰 Wyniki: {osd_choice} {taryfa_choice} (Netto)")

# Wyniki główne
res_df = pd.DataFrame({
    "Składnik kosztu": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
})
st.table(res_df.set_index("Składnik kosztu").style.format("{:,.2f}"))

# Analiza Mocowa K1-K4
st.markdown("---")
st.subheader("⚡ Szczegóły Opłaty Mocowej")
cl, cr = st.columns(2)
def gen_tab_moc(sz, mn_act):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt [PLN]": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_act == mns[x.name] else '' for _ in x], axis=1).format({"Koszt [PLN]": "{:,.2f}"})

cl.write(f"**PRZED PV** (Mocowy: {sz_p/1000:,.2f} MWh)")
cl.table(gen_tab_moc(sz_p, mn_p))
cr.write(f"**PO PV** (Mocowy: {sz_n/1000:,.2f} MWh)")
cr.table(gen_tab_moc(sz_n, mn_n))

# Wykres
st.markdown("---")
avg_p = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg_p.index, y=avg_p['Pobór'], name="Przed PV", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg_p.index, y=avg_p['Nowy_Pobór'], name="Po PV", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg_p.index, y=avg_p['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
