import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD 2026 (NETTO PLN/kWh) ---
WSPOLNE_NETTO = 0.04346 

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

# Opłata mocowa Netto 2026: 219.40 zł/MWh
OPLATA_MOCOWA_NETTO = 0.2194 

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja (Kwoty Netto)")
cena_mwh_netto = st.sidebar.number_input("Stała cena energii czynnej (PLN/MWh)", value=485.0)
cena_en_kwh = cena_mwh_netto / 1000

osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])

st.sidebar.markdown("### Edycja Opłat Dystrybucyjnych")
final_rates = {}
base_osd = osd_data[osd_choice][taryfa_choice]

for strefa, stawka in base_osd.items():
    final_rates[strefa] = st.sidebar.number_input(
        f"Dystrybucja {strefa} (zł/kWh)", 
        value=float(stawka + WSPOLNE_NETTO), 
        format="%.5f"
    )

st.sidebar.markdown("---")
st.sidebar.header("☀️ System PV")
moc_pv = st.sidebar.number_input("Moc instalacji (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp/rok)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil godzinowy lub 15-minutowy (CSV)", type=['csv'])

# --- „PANCERNY” MECHANIZM WCZYTYWANIA DANYCH ---
df = None
if uploaded_file is not None:
    try:
        raw_bytes = uploaded_file.read()
        decoded_str = None
        
        # Próba kodowań (UTF-8, potem polski Excel CP1250)
        for enc in ['utf-8', 'cp1250', 'utf-8-sig', 'iso-8859-2']:
            try:
                decoded_str = raw_bytes.decode(enc)
                break
            except: continue
            
        if decoded_str:
            # Automatyczne wykrywanie separatora (, lub ;)
            df_raw = pd.read_csv(io.StringIO(decoded_str), sep=None, engine='python')
            
            # Wybieramy kolumnę z wartościami (zazwyczaj 3. kolumna na Twoim screenie)
            # Jeśli plik ma co najmniej 3 kolumny, bierzemy indeks 2 (trzecia kolumna)
            if df_raw.shape[1] >= 3:
                val_col = df_raw.columns[2]
            else:
                val_col = df_raw.columns[-1]
            
            # Konwersja tekstu na liczby (naprawa przecinków)
            data_series = df_raw[val_col].astype(str).str.replace(',', '.').str.extract(r'(\d+\.?\d*)')[0].astype(float)
            
            # Agregacja 15 min -> 1h (jeśli wierszy jest > 10 000)
            if len(data_series) > 10000:
                hourly_pobor = data_series.groupby(data_series.index // 4).sum()
                df = pd.DataFrame({"Pobór": hourly_pobor})
                st.success(f"Wykryto dane 15-minutowe. Zagregowano do {len(df)} godzin.")
            else:
                df = pd.DataFrame({"Pobór": data_series})
                st.success(f"Wczytano {len(df)} godzin danych.")
                
            df = df.head(8760).reset_index(drop=True)
        else:
            st.error("Nie udało się rozpoznać kodowania pliku.")
    except Exception as e:
        st.error(f"Błąd krytyczny przy wczytywaniu: {e}")

# Dane testowe jeśli brak pliku
if df is None:
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    pobor = np.where((dates.weekday < 5) & (dates.hour >= 8) & (dates.hour < 16), 60, 20)
    df = pd.DataFrame({"Pobór": pobor})

# --- OBLICZENIA ---
df['Godzina'] = np.arange(len(df)) % 24
df['Roboczy'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday < 5
profil_slonca = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Generacja_PV'] = (profil_slonca / profil_slonca.sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

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

def calc_all(col):
    en_cost = df[col].sum() * cena_en_kwh
    dist_cost = sum(df[df['Strefa'] == s][col].sum() * final_rates[s] for s in final_rates)
    sz_m = df[df['Godzina_Mocowa']][col].sum()
    pz_m = df[~df['Godzina_Mocowa']][col].sum()
    calkowite = sz_m + pz_m
    delta = (sz_m - pz_m) / calkowite if calkowite > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.5 if delta < 0.10 else (0.83 if delta < 0.15 else 1.0))
    moc_cost = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en_cost, dist_cost, moc_cost, mn, sz_m

e_przed, d_przed, m_przed, mn_przed, sz_m_przed = calc_all('Pobór')
e_po, d_po, m_po, mn_po, sz_m_po = calc_all('Nowy_Pobór')

# --- WYŚWIETLANIE ---
st.header(f"📊 Raport Kosztów: {osd_choice} {taryfa_choice} - Netto 2026")

res_data = {
    "Kategoria kosztów": ["Energia Czynna", "Dystrybucja Zmienna", "Opłata Mocowa", "ŁĄCZNIE"],
    "PRZED PV [PLN]": [e_przed, d_przed, m_przed, e_przed+d_przed+m_przed],
    "PO PV [PLN]": [e_po, d_po, m_po, e_po+d_po+m_po],
    "ZYSK ROCZNY [PLN]": [e_przed-e_po, d_przed-d_po, m_przed-m_po, (e_przed+d_przed+m_przed)-(e_po+d_po+m_po)]
}
st.table(pd.DataFrame(res_data).set_index("Kategoria kosztów").style.format("{:,.2f}"))

# Sekcja Mocowa K1-K4
st.markdown("---")
st.subheader("⚡ Dokładne zestawienie opłaty mocowej wg kategorii (K1-K4)")
col_m1, col_m2 = st.columns(2)

def generate_moc_table(sz_val, active_mn):
    names = ["Kategoria K1 (17%)", "Kategoria K2 (50%)", "Kategoria K3 (83%)", "Kategoria K4 (100%)"]
    multipliers = [0.17, 0.50, 0.83, 1.00]
    costs = [sz_val * OPLATA_MOCOWA_NETTO * m for m in multipliers]
    df_m = pd.DataFrame({"Kategoria": names, "Stawka [zł/kWh]": [OPLATA_MOCOWA_NETTO * m for m in multipliers], "Roczny Koszt [PLN]": costs})
    def highlight(row):
        return ['background-color: #d1f2d1' if active_mn == multipliers[row.name] else '' for _ in row]
    return df_m.style.apply(highlight, axis=1).format({"Stawka [zł/kWh]": "{:.4f}", "Roczny Koszt [PLN]": "{:,.2f}"})

with col_m1:
    st.write(f"**PRZED PV** (Mocowy: {sz_m_przed/1000:,.2f} MWh)")
    st.table(generate_moc_table(sz_m_przed, mn_przed))
with col_m2:
    st.write(f"**PO PV** (Mocowy: {sz_m_po/1000:,.2f} MWh)")
    st.table(generate_moc_table(sz_m_po, mn_po))

# Wykresy
st.markdown("---")
avg_df = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg_df.index, y=avg_df['Pobór'], name="Pobór przed PV", line=dict(color='#E74C3C')))
fig.add_trace(go.Scatter(x=avg_df.index, y=avg_df['Nowy_Pobór'], name="Pobór po PV", fill='tozeroy', line=dict(color='#2ECC71')))
fig.add_trace(go.Bar(x=avg_df.index, y=avg_df['Generacja_PV'], name="Generacja PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni Profil Dobowy (kWh)", xaxis_title="Godzina", template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
