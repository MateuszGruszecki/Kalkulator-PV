import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD 2026 (NETTO PLN/kWh) ---
WSPOLNE_NETTO = 0.04346 
OPLATA_MOCOWA_NETTO = 0.2194

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
st.sidebar.header("⚙️ Konfiguracja")
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil klienta (CSV)", type=['csv'])

# --- PANCERNY LOADER DANYCH ---
df = None
if uploaded_file is not None:
    try:
        # Odczytujemy surowe bajty
        raw_bytes = uploaded_file.read()
        
        # Pętla po kodowaniach (rozwiązuje problem UnicodeDecodeError)
        decoded_str = None
        for enc in ['cp1250', 'utf-8-sig', 'utf-8', 'iso-8859-2']:
            try:
                decoded_str = raw_bytes.decode(enc)
                break
            except: continue
            
        if decoded_str:
            # Automatyczne wykrywanie separatora (, lub ;)
            df_raw = pd.read_csv(io.StringIO(decoded_str), sep=None, engine='python')
            
            # Naprawa liczb i wybór kolumny wartości (zakładamy 3. kolumnę wg Twojego screena)
            val_col = df_raw.columns[2] if df_raw.shape[1] >= 3 else df_raw.columns[-1]
            
            # Zamiana przecinków na kropki i konwersja na liczby
            df_raw[val_col] = df_raw[val_col].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
            
            # Jeśli dane są 15-minutowe (dużo wierszy), sumujemy do godzin
            if len(df_raw) > 10000:
                hourly_data = df_raw[val_col].groupby(df_raw.index // 4).sum()
                df = pd.DataFrame({"Pobór": hourly_data})
                st.success(f"Zagregowano dane 15-minutowe do {len(df)} godzin.")
            else:
                df = pd.DataFrame({"Pobór": df_raw[val_col]})
                st.success(f"Wczytano {len(df)} godzin danych.")
                
            df = df.head(8760).reset_index(drop=True)
    except Exception as e:
        st.error(f"Błąd krytyczny przy wczytywaniu: {e}")

# Dane testowe (jeśli brak pliku)
if df is None:
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    df = pd.DataFrame({"Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA ---
df['Godzina'] = np.arange(len(df)) % 24
df['Roboczy'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday < 5
profil_slonca = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Generacja_PV'] = (profil_slonca / profil_slonca.sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

def przypisz_strefe(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        return "przedpołudnie" if 7 <= h < 13 else ("popołudnie" if 16 <= h < 21 else "pozostałe")
    return "całodobowa"

df['Strefa'] = df.apply(przypisz_strefe, axis=1)
df['Godzina_Mocowa'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def kalkuluj(col):
    en = df[col].sum() * (cena_mwh / 1000)
    dys = sum(df[df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    calk = sz_m + pz_m
    delta = (sz_m - pz_m) / calk if calk > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.5 if delta < 0.10 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = kalkuluj('Pobór')
e_n, d_n, m_n, mn_n, sz_n = kalkuluj('Nowy_Pobór')

# --- PREZENTACJA WYNIKÓW ---
st.header(f"📊 Raport Kosztów: {osd_choice} {taryfa_choice} (Netto 2026)")
st.table(pd.DataFrame({
    "Kategoria": ["Energia Czynna", "Dystrybucja", "Opłata Mocowa", "SUMA"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Kategoria").style.format("{:,.2f}"))

st.markdown("---")
st.subheader("⚡ Szczegółowe zestawienie opłaty mocowej (K1-K4)")
c1, c2 = st.columns(2)
def tabela_moc(sz, mn_a):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_a == mns[x.name] else '' for _ in x], axis=1).format({"Koszt": "{:,.2f}"})

with c1:
    st.write(f"**PRZED PV** (Pobór mocowy: {sz_p/1000:,.2f} MWh)")
    st.table(tabela_moc(sz_p, mn_p))
with c2:
    st.write(f"**PO PV** (Pobór mocowy: {sz_n/1000:,.2f} MWh)")
    st.table(tabela_moc(sz_n, mn_n))

# Wykres
avg = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg.index, y=avg['Pobór'], name="Przed", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg.index, y=avg['Nowy_Pobór'], name="Po", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg.index, y=avg['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", xaxis_title="Godzina", template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
