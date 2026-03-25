import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Analiza Kosztów i Profili PV", layout="wide")
st.title("📉 Kompleksowa Analiza Opłacalności PV dla Biznesu")

# --- BAZA CENNIKÓW (2026) ---
osd_tariffs_b = {
    "PGE": {
        "B21": {"całodobowa": 0.2450},
        "B22": {"szczyt": 0.3100, "pozaszczyt": 0.1400},
        "B23": {"przedpołudnie": 0.2500, "popołudnie": 0.3800, "pozostałe": 0.1100}
    },
    "Tauron": {
        "B21": {"całodobowa": 0.2250},
        "B22": {"szczyt": 0.2900, "pozaszczyt": 0.1250},
        "B23": {"przedpołudnie": 0.2300, "popołudnie": 0.3500, "pozostałe": 0.0950}
    },
    "Energa": {
        "B21": {"całodobowa": 0.2550},
        "B22": {"szczyt": 0.3200, "pozaszczyt": 0.1500},
        "B23": {"przedpołudnie": 0.2600, "popołudnie": 0.400, "pozostałe": 0.1200}
    },
    "Enea": {
        "B21": {"całodobowa": 0.2150},
        "B22": {"szczyt": 0.2800, "pozaszczyt": 0.1200},
        "B23": {"przedpołudnie": 0.2200, "popołudnie": 0.3400, "pozostałe": 0.0900}
    }
}
OPLATA_MOCOWA_2026 = 0.2194 

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja")
cena_mwh_netto = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
cena_kwh_netto = cena_mwh_netto / 1000

osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_tariffs_b.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])

stawki_dyst = {}
for strefa, stawka in osd_tariffs_b[osd_choice][taryfa_choice].items():
    stawki_dyst[strefa] = st.sidebar.number_input(f"Dystrybucja {strefa} (zł/kWh)", value=stawka, format="%.4f")

moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil CSV", type=['csv'])

# --- LOGIKA OBLICZEŃ ---
if uploaded_file is None:
    st.info("💡 Używam profilu demonstracyjnego. Wgraj CSV dla realnych danych.")
    dates = pd.date_range(start="2026-01-01", periods=8760, freq="h")
    pobor = np.where((dates.hour >= 8) & (dates.hour < 17), np.random.uniform(40, 70, 8760), np.random.uniform(10, 25, 8760))
    df = pd.DataFrame({"Data": dates, "Pobór": pobor})
else:
    df = pd.read_csv(uploaded_file)
    df.columns = ["Data", "Pobór"]
    df["Pobór"] = pd.to_numeric(df["Pobór"], errors='coerce').fillna(0)

# Symulacja PV i Bilans
df['Godzina'] = np.arange(len(df)) % 24
df['Roboczy'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday < 5

profil_dzienny = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
df['Generacja_PV'] = (profil_dzienny / profil_dzienny.sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# Strefy i Mocowa
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

def kalkulacja(col):
    en = df[col].sum() * cena_kwh_netto
    dys = sum(df[df['Strefa'] == s][col].sum() * stawki_dyst[s] for s in stawki_dyst)
    sz_m, pz_m = df[df['Godzina_Mocowa']][col].sum(), df[~df['Godzina_Mocowa']][col].sum()
    calkowite = sz_m + pz_m
    delta = (sz_m - pz_m) / calkowite if calkowite > 0 else 0
    mnoznik = 0.17 if delta < 0.05 else (0.5 if delta < 0.10 else (0.83 if delta < 0.15 else 1.0))
    moc = sz_m * OPLATA_MOCOWA_2026 * mnoznik
    return en, dys, moc, delta, mnoznik

e_przed, d_przed, m_przed, delta_przed, mn_przed = kalkulacja('Pobór')
e_po, d_po, m_po, delta_po, mn_po = kalkulacja('Nowy_Pobór')

# --- PREZENTACJA: SEKCOJA FINANSOWA ---
st.header("💰 Analiza Finansowa (Netto)")

col_a, col_b = st.columns([2, 1])

with col_a:
    st.subheader("📋 Zestawienie Roczne")
    data_compare = {
        "Kategoria": ["Energia Czynna", "Dystrybucja (Zmienna)", "Opłata Mocowa", "RAZEM"],
        "PRZED PV [PLN]": [f"{e_przed:,.2f}", f"{d_przed:,.2f}", f"{m_przed:,.2f}", f"{e_przed+d_przed+m_przed:,.2f}"],
        "PO PV [PLN]": [f"{e_po:,.2f}", f"{d_po:,.2f}", f"{m_po:,.2f}", f"{e_po+d_po+m_po:,.2f}"],
        "ZYSK [PLN]": [f"{e_przed-e_po:,.2f}", f"{d_przed-d_po:,.2f}", f"{m_przed-m_po:,.2f}", f"{(e_przed+d_przed+m_przed)-(e_po+d_po+m_po):,.2f}"]
    }
    st.table(pd.DataFrame(data_compare))

with col_b:
    st.subheader("📊 Struktura Kosztów")
    categories = ["Energia", "Dystrybucja", "Mocowa"]
    fig_costs = go.Figure(data=[
        go.Bar(name='Przed', x=categories, y=[e_przed, d_przed, m_przed], marker_color='#E74C3C'),
        go.Bar(name='Po', x=categories, y=[e_po, d_po, m_po], marker_color='#2ECC71')
    ])
    fig_costs.update_layout(barmode='group', height=300, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig_costs, use_container_width=True)

# --- PREZENTACJA: PROFIL ENERGETYCZNY ---
st.markdown("---")
st.header("☀️ Charakterystyka Energetyczna")

# Wykres profilu (średni dzień)
sredni_dzien = df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()

fig_prof = go.Figure()
fig_prof.add_trace(go.Scatter(x=sredni_dzien.index, y=sredni_dzien['Pobór'], name="Pobór Pierwotny", line=dict(color='#E74C3C', width=2)))
fig_prof.add_trace(go.Scatter(x=sredni_dzien.index, y=sredni_dzien['Nowy_Pobór'], name="Pobór po PV", fill='tozeroy', line=dict(color='#2ECC71', width=2)))
fig_prof.add_trace(go.Bar(x=sredni_dzien.index, y=sredni_dzien['Generacja_PV'], name="Generacja PV", opacity=0.4, marker_color='orange'))

fig_prof.update_layout(
    title="Średniodobowy profil przepływu energii",
    xaxis_title="Godzina",
    yaxis_title="Moc / Energia [kWh]",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    template="plotly_white"
)
st.plotly_chart(fig_prof, use_container_width=True)

# Dodatkowe info o mocowej
st.info(f"""
**Analiza Opłaty Mocowej (2026):**
* Współczynnik Δ przed PV: **{delta_przed:.3f}** (Mnożnik: {mn_przed})
* Współczynnik Δ po PV: **{delta_po:.3f}** (Mnożnik: {mn_po})
* PV obniżyło pobór w godzinach szczytowych o **{df['Pobór'].sum() - df['Nowy_Pobór'].sum():,.1f} kWh**.
""")
