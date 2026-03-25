import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA ---
st.set_page_config(page_title="Kalkulator PV B2B - Naprawa Ostateczna", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- STAŁE (Netto 2026) ---
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
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=50.0)
uzysk = st.sidebar.number_input("Uzysk (kWh/kWp)", value=1000.0)

uploaded_file = st.sidebar.file_uploader("Wgraj Twój plik CSV (15- min.csv)", type=['csv'])

# --- LOGIKA WCZYTYWANIA (NAPRAWA BŁĘDU KODOWANIA I DŁUGOŚCI) ---
main_df = None

if uploaded_file:
    try:
        # 1. Wymuszone kodowanie polskiego Excela (cp1250) rozwiązuje błąd '0xb3'
        raw_bytes = uploaded_file.read()
        df_raw = pd.read_csv(io.BytesIO(raw_bytes), sep=';', encoding='cp1250', decimal=',', engine='python')
        
        # 2. Wybieramy kolumny (Data, Godzina, Wartość) - ignorujemy puste kolumny Excela
        # Na Twoim screenie wartość jest w 3. kolumnie (indeks 2)
        df_raw = df_raw.iloc[:, [0, 1, 2]]
        df_raw.columns = ['Data', 'Czas', 'Wartość']
        
        # 3. Konwersja czasu i agregacja 15-min -> 1h
        df_raw['Timestamp'] = pd.to_datetime(df_raw['Data'] + ' ' + df_raw['Czas'], dayfirst=True, errors='coerce')
        df_raw = df_raw.dropna(subset=['Timestamp'])
        
        # Sumujemy wartości w ramach pełnych godzin
        df_hourly = df_raw.set_index('Timestamp')['Wartość'].resample('1H').sum().reset_index()
        df_hourly.columns = ['Data_Czas', 'Pobór']
        
        # 4. Tworzymy główny DataFrame (Długość zależna OD PLIKU, nie od 8760)
        main_df = df_hourly.copy()
        st.success(f"Pomyślnie wczytano dane. Zakres: {main_df['Data_Czas'].min()} do {main_df['Data_Czas'].max()}")

    except Exception as e:
        st.error(f"Błąd pliku: {e}. Sprawdź czy plik ma kolumny: Data, Czas, Wartość.")

# Dane demonstracyjne jeśli brak pliku
if main_df is None:
    dates = pd.date_range("2026-01-01", periods=8760, freq="h")
    main_df = pd.DataFrame({"Data_Czas": dates, "Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA (DYNAMICZNE DOPASOWANIE) ---
# Teraz wszystkie tablice mają tę samą długość (len(main_df))
main_df['Godzina'] = main_df['Data_Czas'].dt.hour
main_df['Roboczy'] = main_df['Data_Czas'].dt.weekday < 5

# Profil PV dopasowany do długości wczytanych danych
sin_profile = np.maximum(0, np.sin((main_df['Godzina'] - 6) * np.pi / 12))
# Skalowanie produkcji do okresu w pliku (proporcjonalnie)
produkcja_okresowa = (moc_pv * uzysk) * (len(main_df) / 8760)
main_df['Generacja_PV'] = (sin_profile / sin_profile.sum()) * produkcja_okresowa if sin_profile.sum() > 0 else 0
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

# Kalkulacja kosztów
def run_calc(col):
    en = main_df[col].sum() * (cena_mwh / 1000)
    dys = sum(main_df[main_df['Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    
    sz_m = main_df[main_df['Godzina_Mocowa']][col].sum()
    pz_m = main_df[~main_df['Godzina_Mocowa']][col].sum()
    delta = (sz_m - pz_m) / (sz_m + pz_m) if (sz_m + pz_m) > 0 else 0
    mn = 0.17 if delta < 0.05 else (0.50 if delta < 0.10 else (0.83 if delta < 0.15 else 1.00))
    moc = sz_m * OPLATA_MOCOWA_NETTO * mn
    return en, dys, moc, mn, sz_m

e_p, d_p, m_p, mn_p, sz_p = run_calc('Pobór')
e_n, d_n, m_n, mn_n, sz_n = run_calc('Nowy_Pobór')

# --- PREZENTACJA ---
st.header(f"💰 Wyniki Analizy (Netto)")

# Tabela główna
st.table(pd.DataFrame({
    "Składnik": ["Energia czynna", "Dystrybucja", "Opłata mocowa", "SUMA"],
    "PRZED PV": [e_p, d_p, m_p, e_p+d_p+m_p],
    "PO PV": [e_n, d_n, m_n, e_n+d_n+m_n],
    "ZYSK": [e_p-e_n, d_p-d_n, m_p-m_n, (e_p+d_p+m_p)-(e_n+d_n+m_n)]
}).set_index("Składnik").style.format("{:,.2f}"))

# Analiza Mocowa K1-K4
st.markdown("---")
st.subheader("⚡ Porównanie Kategorii Opłaty Mocowej")
cl, cr = st.columns(2)
def draw_moc(sz, active_mn):
    mns = [0.17, 0.50, 0.83, 1.00]
    m_df = pd.DataFrame({"Kategoria": ["K1 (17%)", "K2 (50%)", "K3 (83%)", "K4 (100%)"], "Koszt [PLN]": [sz * OPLATA_MOCOWA_NETTO * m for m in mns]})
    return m_df.style.apply(lambda x: ['background-color: #d1f2d1' if active_mn == mns[x.name] else '' for _ in x], axis=1).format({"Koszt [PLN]": "{:,.2f}"})

cl.write(f"**PRZED PV**")
cl.table(draw_moc(sz_p, mn_p))
cr.write(f"**PO PV**")
cr.table(draw_moc(sz_n, mn_n))

# Wykres profilu
st.markdown("---")
avg_p = main_df.groupby('Godzina')[['Pobór', 'Nowy_Pobór', 'Generacja_PV']].mean()
fig = go.Figure()
fig.add_trace(go.Scatter(x=avg_p.index, y=avg_p['Pobór'], name="Pobór przed", line=dict(color='red')))
fig.add_trace(go.Scatter(x=avg_p.index, y=avg_p['Nowy_Pobór'], name="Pobór po", fill='tozeroy', line=dict(color='green')))
fig.add_trace(go.Bar(x=avg_p.index, y=avg_p['Generacja_PV'], name="PV", opacity=0.3, marker_color='orange'))
fig.update_layout(title="Średni profil dobowy (kWh)", template="plotly_white", xaxis=dict(dtick=1))
st.plotly_chart(fig, use_container_width=True)
