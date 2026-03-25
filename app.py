import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- USTAWIENIA STRONY ---
st.set_page_config(page_title="Kalkulator PV dla B21/B22/B23", layout="wide")
st.title("⚡ Zaawansowany Kalkulator Opłacalności PV")

# --- PANEL BOCZNY (DANE WEJŚCIOWE) ---
st.sidebar.header("Parametry Inwestycji")
osd = st.sidebar.selectbox("Wybierz OSD", ["PGE", "Tauron", "Enea", "Energa", "Stoen"])
taryfa = st.sidebar.selectbox("Wybierz Taryfę", ["B21", "B22", "B23"])

cena_czynna = st.sidebar.number_input("Cena energii czynnej (PLN/MWh)", value=485.0)
moc_pv = st.sidebar.number_input("Moc instalacji PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk z 1 kWp (kWh)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj profil poboru 8760h (CSV)", type=['csv'])

# --- MOCKUP DANYCH (Jeśli ktoś nie wgra pliku, aplikacja i tak zadziała demonstracyjnie) ---
if uploaded_file is None:
    st.info("👈 Wgraj plik z profilem godzinowym, aby uzyskać dokładne wyniki. Obecnie wyświetlam dane demonstracyjne.")
    # Generowanie sztucznych 8760 godzin dla pokazu
    dates = pd.date_range(start="2025-01-01", periods=8760, freq="H")
    pobor_mock = np.random.uniform(10, 50, 8760) # Stały pobór miedzy 10 a 50 kW
    generacja_mock = np.zeros(8760)
    # Sztuczna produkcja słońca w dzień (godziny 8-16)
    generacja_mock[[(d.hour >= 8 and d.hour <= 16) for d in dates]] = np.random.uniform(0, 0.8 * moc_pv, sum([(d.hour >= 8 and d.hour <= 16) for d in dates]))
    
    df = pd.DataFrame({"Data": dates, "Pobor_kWh": pobor_mock, "Generacja_PV_kWh": generacja_mock})
else:
    # Tu później dodamy parsowanie wgranego przez Ciebie pliku
    df = pd.read_csv(uploaded_file)
    st.success("Plik wgrany poprawnie!")

# --- OBLICZENIA (SILNIK) ---
df['Bilans'] = df['Pobor_kWh'] - df['Generacja_PV_kWh']
df['Pobor_z_sieci_po_PV'] = df['Bilans'].apply(lambda x: x if x > 0 else 0)
df['Oddane_do_sieci'] = df['Bilans'].apply(lambda x: abs(x) if x < 0 else 0)

# Godziny Opłaty Mocowej (Dni robocze 7:00 - 21:59)
df['Godzina_Mocowa'] = df['Data'].apply(lambda x: 1 if x.weekday() < 5 and 7 <= x.hour <= 21 else 0)

# Statystyki przed PV
zuzycie_przed_szczyt = df[df['Godzina_Mocowa'] == 1]['Pobor_kWh'].sum()
zuzycie_przed_pozaszczyt = df[df['Godzina_Mocowa'] == 0]['Pobor_kWh'].sum()
calkowite_zuzycie_przed = zuzycie_przed_szczyt + zuzycie_przed_pozaszczyt

# Statystyki po PV
zuzycie_po_szczyt = df[df['Godzina_Mocowa'] == 1]['Pobor_z_sieci_po_PV'].sum()
zuzycie_po_pozaszczyt = df[df['Godzina_Mocowa'] == 0]['Pobor_z_sieci_po_PV'].sum()
calkowite_zuzycie_po = zuzycie_po_szczyt + zuzycie_po_pozaszczyt

# --- MODUŁ OPŁATY MOCOWEJ (K1 - K4) ---
# K1: Różnica < 5%, K2: 5-10%, K3: 10-15%, K4: >15%
def sprawdz_k(pozaszczyt, szczyt):
    if szczyt == 0: return "Brak (100% płaski)"
    wspolczynnik = pozaszczyt / (szczyt + pozaszczyt)
    if wspolczynnik < 0.05: return "Brak Ulgi (Standard)"
    elif wspolczynnik < 0.10: return "K1 (17% ulgi)"
    elif wspolczynnik < 0.15: return "K2 (50% ulgi)"
    else: return "K3 / K4 (83% ulgi lub brak opłaty)"

profil_przed_k = sprawdz_k(zuzycie_przed_pozaszczyt, zuzycie_przed_szczyt)
profil_po_k = sprawdz_k(zuzycie_po_pozaszczyt, zuzycie_po_szczyt)

# --- WYŚWIETLANIE WYNIKÓW (DASHBOARD) ---
st.subheader(f"Wstępna Analiza dla: {osd} | Taryfa {taryfa} | Instalacja {moc_pv} kWp")

col1, col2, col3 = st.columns(3)
col1.metric("Pobór z sieci PRZED PV", f"{calkowite_zuzycie_przed/1000:.1f} MWh")
col2.metric("Pobór z sieci PO PV", f"{calkowite_zuzycie_po/1000:.1f} MWh", f"-{(calkowite_zuzycie_przed-calkowite_zuzycie_po)/1000:.1f} MWh")
col3.metric("Autokonsumpcja", f"{(calkowite_zuzycie_przed-calkowite_zuzycie_po)/(df['Generacja_PV_kWh'].sum())*100:.1f} %")

st.markdown("---")
st.subheader("💡 Analiza Opłaty Mocowej")
col4, col5 = st.columns(2)
col4.metric("Kwalifikacja mocowa PRZED PV", profil_przed_k)
col5.metric("Kwalifikacja mocowa PO PV", profil_po_k)

# --- WYKRES PROFILU DOBOWEGO ---
st.subheader("Średni Profil Dobowy Poboru")
df['Godzina'] = df['Data'].dt.hour
sredni_profil = df.groupby('Godzina')[['Pobor_kWh', 'Pobor_z_sieci_po_PV']].mean().reset_index()

fig = go.Figure()
fig.add_trace(go.Bar(x=sredni_profil['Godzina'], y=sredni_profil['Pobor_kWh'], name='Przed PV', marker_color='lightgray'))
fig.add_trace(go.Bar(x=sredni_profil['Godzina'], y=sredni_profil['Pobor_z_sieci_po_PV'], name='Po PV', marker_color='#1f77b4'))
fig.update_layout(barmode='overlay', xaxis_title="Godzina", yaxis_title="Średni pobór (kWh)")
fig.update_traces(opacity=0.75)
st.plotly_chart(fig, use_container_width=True)

st.markdown("*Uwaga: To pierwsza faza demonstracyjna! W kolejnych krokach podepniemy tu cenniki OSD wgrywane z pliku cenniki_osd.csv*")
