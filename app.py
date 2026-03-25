import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Naprawa Ostateczna", layout="wide")
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

uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV", type=['csv'])

# --- LOGIKA WCZYTYWANIA I AGREGACJI ---
main_df = None

if uploaded_file is not None:
    try:
        # 1. Odczyt surowy z polskim kodowaniem
        raw = uploaded_file.read()
        try:
            decoded = raw.decode('cp1250')
        except:
            decoded = raw.decode('utf-8', errors='ignore')
            
        # 2. Czytanie bez nagłówka (skiprows=1), separacja średnikiem, przecinek jako dziesiętny
        df_raw = pd.read_csv(io.StringIO(decoded), sep=';', decimal=',', engine='python', header=None, skiprows=1)
        
        # 3. Wybieramy: Kolumna 0 (Data), Kolumna 1 (Czas), Kolumna 2 (Wartość)
        # Tworzymy listę wartości kWh
        vals_15min = pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0).values
        
        # 4. Agregacja 15 min -> 1h (tylko pełne godziny)
        num_full_hours = len(vals_15min) // 4
        vals_hourly = [np.sum(vals_15min[i*4 : (i+1)*4]) for i in range(num_full_hours)]
        
        # 5. Budujemy Daty (tylko tyle ile mamy pełnych godzin)
        try:
            start_date_str = str(df_raw.iloc[0, 0])
            start_dt = pd.to_datetime(start_date_str, dayfirst=True)
        except:
            start_dt = pd.Timestamp("2026-01-01")
            
        main_df = pd.DataFrame({
            "Timestamp": pd.date_range(start=start_dt, periods=num_full_hours, freq='H'),
            "Pobór": vals_hourly
        })
        
        st.success(f"Pomyślnie wczytano {len(main_df)} pełnych godzin danych.")
        
    except Exception as e:
        st.error(f"Błąd krytyczny pliku: {e}")

# Jeśli brak pliku - używamy demo
if main_df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    main_df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA (Synchronizacja tablic) ---
main_df['Godzina'] = main_df['Timestamp'].dt.hour
main_df['Roboczy'] = main_df['Timestamp'].dt.weekday < 5

# Generacja PV (sinusoida)
sin_curve = np.maximum(0, np.sin((main_df['Godzina'] - 6) * np.pi / 12))
# Skalowanie produkcji do długości wczytanych danych
total_pv_prod = (moc_pv * uzysk) * (len(main_df) / 8760)
main_df['Generacja_PV'] = (sin_curve / sin_curve.sum() * total_pv_prod) if sin_curve.sum() > 0 else 0
main_df['Nowy_Pobór'] = np.maximum(0, main_df['Pobór'] - main_df['Generacja_PV'])

# Strefy
def get_strefa(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozostałe"
        return "przedpołudnie" if 7 <= h < 13 else ("popołudnie" if 16 <= h < 21 else "pozostałe")
    return "całodobowa"

main_df['Strefa'] = main_df.apply(get_strefa, axis=1)
main_df['Godzina_Mocowa'] = (main_df['Godzina'] >= 7) & (main_df['Godzina'] < 22) & main_df['Roboczy']

# Finanse
def calculate(col):
    en_cost = main_df[col].sum() * (cena_mwh / 1000)
    dist_cost = sum(main_df[main_df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    
    sz_m = main_df[main_df['Godzina_Mocowa']][col].sum()
    pz_m = main_df[~main_df['Godzina_Mocowa']][col].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.50 if delta < 0.10 else (0.83 if delta < 0.15 else 1.00))
    moc_cost = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en_cost, dist_cost, moc_cost, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = calculate('Pobór')
e_n, d_n, m_n, mn_n, sz_n = calculate('Nowy_Pobór')

# --- WYŚWIETLANIE ---
st.header(f"💰 Wyniki Analizy: {osd_choice} {taryfa_choice} (Netto 2026)")

# Tabela główna
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV [PLN]": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV [PLN]": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK [PLN]": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Składnik").style.format("{:,.2f}"))

# Sekcja opłaty mocowej
st.markdown("---")
st.subheader("⚡ Podział Opłaty Mocowej (K1-K4)")
cl, cr = st.columns(2)
def gen_moc_table(sz, mn_act):
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({
        "Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"],
        "Roczny Koszt [PLN]": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]
    })
    return df_m.style.apply(lambda x: ['background-color: #d1f2d1' if mn_act == mns[x.name] else '' for _ in x], axis=1).format("{:,.2f}")

cl.write(f"**PRZED PV** (Mocowy: {sz_p/1000:,.2f} MWh)")
cl.table(gen_moc_table(sz_p, mn_p))
cr.write(f"**PO PV** (Mocowy: {sz_n/1000:,.2f} MWh)")
cr.table(gen_moc_table(sz_n, mn_n))

# Wykres profilu
st.markdown("---")
avg = main_df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean().reindex(range(24)).fillna(0)
fig = go.Figure()
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Pobór'], name="Przed PV", line=dict(color='red')))
fig.add_trace(go.Scatter(x=list(range(24)), y=avg['Nowy_Pobór'], name="Po PV", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=list(range(24)), y=avg['Generacja_PV'], name="Produkcja PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", xaxis=dict(dtick=1, title="Godzina"), template="plotly_white")
st.plotly_chart(fig, use_container_width=True)
