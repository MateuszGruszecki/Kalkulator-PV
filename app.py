import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV B2B - Komplet OSD 2026", layout="wide")
st.title("⚡ Profesjonalny Kalkulator PV dla Biznesu (Netto 2026)")

# --- BAZA DANYCH OSD 2026 (WARTOŚCI NETTO PLN/kWh) ---
# Opłaty wspólne krajowe Netto 2026: Jakościowa (40.79/1.23=33.16) + OZE (7.30) + Kogen (3.00) = 43.46 PLN/MWh
WSPOLNE_NETTO = 0.04346 

osd_data = {
    "PGE": {
        "B21": {"całodobowa": 0.06446}, # 79.29 / 1.23
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

# Opłata mocowa Netto 2026 zgodnie z Twoją wytyczną
OPLATA_MOCOWA_NETTO = 0.2194 

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Kontrakt i Ceny (Netto)")
cena_mwh_netto = st.sidebar.number_input("Stała cena energii czynnej (PLN/MWh)", value=485.0)
cena_en_kwh = cena_mwh_netto / 1000

osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])

st.sidebar.markdown("### Edycja Opłat Dystrybucyjnych")
# Łączenie stawki sieciowej ze wspólnymi (Jakościowa, OZE, Kogen)
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

uploaded_file = st.sidebar.file_uploader("Wgraj profil godzinowy (CSV)", type=['csv'])

# --- LOGIKA OBLICZEŃ ---
if uploaded_file is None:
    st.info("💡 Używam profilu demonstracyjnego. Wgraj plik CSV klienta, aby przeliczyć realne dane.")
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    pobor = np.where((dates.weekday < 5) & (dates.hour >= 8) & (dates.hour < 16), 65, 20)
    df = pd.DataFrame({"Data": dates, "Pobór": pobor})
else:
    df = pd.read_csv(uploaded_file)
    df.columns = ["Data", "Pobór"]
    df["Pobór"] = pd.to_numeric(df["Pobór"], errors='coerce').fillna(0)

# 1. Produkcja PV
df['Godzina'] = np.arange(len(df)) % 24
df['Roboczy'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday < 5
profil_slonca = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Generacja_PV'] = (profil_slonca / profil_slonca.sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# 2. Przypisanie stref taryfowych
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

# 3. Kalkulacja
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
st.header(f"📉 Raport Kosztów: {osd_choice} ({taryfa_choice}) - Netto 2026")

# Tabela główna
res_data = {
    "Kategoria kosztów": ["Energia Czynna", "Dystrybucja Zmienna", "Opłata Mocowa", "ŁĄCZNIE"],
    "PRZED PV [PLN]": [e_przed, d_przed, m_przed, e_przed+d_przed+m_przed],
    "PO PV [PLN]": [e_po, d_po, m_po, e_po+d_po+m_po],
    "OSZCZĘDNOŚĆ [PLN]": [e_przed-e_po, d_przed-d_po, m_przed-m_po, (e_przed+d_przed+m_przed)-(e_po+d_po+m_po)]
}
st.table(pd.DataFrame(res_data).set_index("Kategoria kosztów").style.format("{:,.2f}"))

# Analiza mocowa
st.markdown("---")
st.subheader("⚡ Szczegółowa Analiza Opłaty Mocowej (K1-K4)")
col_m1, col_m2 = st.columns(2)

def draw_moc_table(sz_val, current_mn):
    kats = ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"]
    mns = [0.17, 0.50, 0.83, 1.00]
    df_m = pd.DataFrame({
        "Kategoria": kats,
        "Koszt Roczny [PLN]": [sz_val * OPLATA_MOCOWA_NETTO * m for m in mns]
    })
    # Podświetlenie aktualnej stawki
    def highlight(row):
        return ['background-color: #d1f2d1' if current_mn == mns[row.name] else '' for _ in row]
    return df_m.style.apply(highlight, axis=1).format({"Koszt Roczny [PLN]": "{:,.2f}"})

with col_m1:
    st.write(f"**PRZED PV** (Pobór mocowy: {sz_m_przed/1000:,.2f} MWh)")
    st.table(draw_moc_table(sz_m_przed, mn_przed))

with col_m2:
    st.write(f"**PO PV** (Pobór mocowy: {sz_m_po/1000:,.2f} MWh)")
    st.table(draw_moc_table(sz_m_po, mn_po))

# Wykresy
st.markdown("---")
c1, c2 = st.columns([1, 2])

with c1:
    st.subheader("📊 Struktura kosztów")
    fig_costs = go.Figure(data=[
        go.Bar(name='Przed', x=["Energia", "Dystr.", "Mocowa"], y=[e_przed, d_przed, m_przed], marker_color='#E74C3C'),
        go.Bar(name='Po', x=["Energia", "Dystr.", "Mocowa"], y=[e_po, d_po, m_po], marker_color='#2ECC71')
    ])
    fig_costs.update_layout(barmode='group', template="plotly_white", height=400)
    st.plotly_chart(fig_costs, use_container_width=True)

with c2:
    st.subheader("☀️ Średni profil dobowy")
    avg_df = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
    fig_prof = go.Figure()
    fig_prof.add_trace(go.Scatter(x=avg_df.index, y=avg_df['Pobór'], name="Pobór przed", line=dict(color='#E74C3C', width=2)))
    fig_prof.add_trace(go.Scatter(x=avg_df.index, y=avg_df['Nowy_Pobór'], name="Pobór po", fill='tozeroy', line=dict(color='#2ECC71', width=2)))
    fig_prof.add_trace(go.Bar(x=avg_df.index, y=avg_df['Generacja_PV'], name="Produkcja PV", opacity=0.3, marker_color='orange'))
    fig_prof.update_layout(template="plotly_white", height=400, xaxis_title="Godzina", yaxis_title="kWh")
    st.plotly_chart(fig_prof, use_container_width=True)
