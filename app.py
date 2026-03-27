import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# PRÓBA IMPORTU BIBLIOTEK
try:
    import holidays
    pl_holidays = holidays.Poland()
    HAS_HOLIDAYS = True
except ImportError:
    HAS_HOLIDAYS = False

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Audyt PV B2B 2026", layout="wide")
st.title("⚡ Analiza PV B2B: Profil Zużycia i Opłata Mocowa 2026")

st.info("""
**📌 Założenia kosztowe analizy:**
* Oszczędności energii: stała cena (Fixed Price).
* Stawki dystrybucyjne: aktualne taryfy OSD na rok 2026.
* Symulacja dobowych profili opiera się na dostarczonych danych historycznych.
""")

# --- PARAMETRY ---
STAWKA_MOCOWA_BAZOWA = 0.2194 # PLN / kWh
WSPOLNE_NETTO = 0.04346 # PLN / kWh

osd_data = {
    "PGE": {"B21": {"całodobowa": 0.06446}, "B22": {"szczyt": 0.08512, "pozaszczyt": 0.04467}, "B23": {"przedpołudnie": 0.06611, "popołudnie": 0.12438, "pozostałe": 0.02298}},
    "Tauron": {"B21": {"całodobowa": 0.07114}, "B22": {"szczyt": 0.07243, "pozaszczyt": 0.05042}, "B23": {"przedpołudnie": 0.04964, "popołudnie": 0.05610, "pozostałe": 0.03748}},
    "Enea": {"B21": {"całodobowa": 0.06820}, "B22": {"szczyt": 0.08940, "pozaszczyt": 0.04210}, "B23": {"przedpołudnie": 0.07120, "popołudnie": 0.12850, "pozostałe": 0.02050}},
    "Stoen": {"B21": {"całodobowa": 0.06150}, "B22": {"szczyt": 0.08230, "pozaszczyt": 0.03840}, "B23": {"przedpołudnie": 0.06420, "popołudnie": 0.11980, "pozostałe": 0.01820}}
}

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Konfiguracja")
data_type = st.sidebar.radio("Typ danych:", ["15-minutowe", "Godzinowe"])
osd_choice = st.sidebar.selectbox("Operator OSD", list(osd_data.keys()))
taryfa_choice = st.sidebar.selectbox("Taryfa", ["B21", "B22", "B23"])
cena_mwh = st.sidebar.number_input("Cena energii czynnej (PLN/MWh netto)", value=485.0)
moc_pv = st.sidebar.number_input("Moc PV (kWp)", value=500.0) 
uzysk = st.sidebar.number_input("Uzysk roczny (kWh/kWp)", value=1000.0)
uploaded_file = st.sidebar.file_uploader("Wgraj CSV klienta", type=['csv'])

# --- WCZYTYWANIE ---
df = None
if uploaded_file:
    try:
        raw = uploaded_file.read()
        try: decoded = raw.decode('cp1250')
        except: decoded = raw.decode('utf-8', errors='ignore')
        df_raw = pd.read_csv(io.StringIO(decoded), sep=';', decimal=',', engine='python', header=None, skiprows=1).dropna(how='all')
        if df_raw.shape[1] >= 3:
            t = pd.to_datetime(df_raw.iloc[:, 0].astype(str) + ' ' + df_raw.iloc[:, 1].astype(str), dayfirst=True, errors='coerce')
            v = pd.to_numeric(df_raw.iloc[:, 2], errors='coerce').fillna(0)
            temp = pd.DataFrame({'T': t, 'V': v}).dropna(subset=['T'])
            if data_type == "15-minutowe":
                df = temp.set_index('T')['V'].resample('1H').sum().to_frame(name='Pobór').reset_index().rename(columns={'T': 'Timestamp'})
            else:
                df = temp.rename(columns={'T': 'Timestamp', 'V': 'Pobór'}).reset_index(drop=True)
    except Exception as e: st.error(f"Błąd pliku: {e}")

if df is None:
    dates = pd.date_range("2024-07-01", periods=8760, freq="h")
    df = pd.DataFrame({"Timestamp": dates, "Pobór": np.random.uniform(1000, 3000, 8760)})

# --- LOGIKA DAT I OBLICZENIA ---
def check_holiday(dt):
    if HAS_HOLIDAYS: return dt in pl_holidays
    return (dt.month, dt.day) in [(1,1),(1,6),(5,1),(5,3),(8,15),(11,1),(11,11),(12,25),(12,26)]

df['Data_Klucz'] = df['Timestamp'].dt.date
df['Roboczy'] = (df['Timestamp'].dt.weekday < 5) & (~df['Timestamp'].apply(check_holiday))
df['Godzina'] = df['Timestamp'].dt.hour
df['Rok_Miesiac'] = df['Timestamp'].dt.to_period('M')
df['Etykieta_Miesiac'] = df['Timestamp'].dt.strftime('%Y-%m')

weights = {1:0.3, 2:0.5, 3:0.9, 4:1.2, 5:1.5, 6:1.6, 7:1.6, 8:1.4, 9:1.0, 10:0.6, 11:0.3, 12:0.2}
sin_p = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12))
df['Gen_Raw'] = sin_p * df['Timestamp'].dt.month.map(weights)
df['Generacja_PV'] = (df['Gen_Raw'] / df['Gen_Raw'].sum()) * (moc_pv * uzysk * (len(df)/8760)) if df['Gen_Raw'].sum() > 0 else 0
df['Autokonsumpcja'] = np.minimum(df['Pobór'], df['Generacja_PV'])
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Autokonsumpcja'])

# Opłata Mocowa (Zredukowany Szczyt ZAWSZE promuje zniżkę)
df['Is_Szczyt_Mocowy'] = (df['Godzina'] >= 7) & (df['Godzina'] < 22) & df['Roboczy']

def get_moc_daily_detailed(sub_df, col):
    is_roboczy = sub_df['Roboczy'].any()
    e_sz = sub_df[sub_df['Is_Szczyt_Mocowy']][col].sum() if is_roboczy else 0.0
    e_psz = sub_df[~sub_df['Is_Szczyt_Mocowy']][col].sum() if is_roboczy else sub_df[col].sum()
    e_d = sub_df[col].sum()
    
    if not is_roboczy or e_d < 0.1:
        return pd.Series({'Szczyt [kWh]': 0.0, 'PozaSzczytem [kWh]': e_d, 'L [%]': 0.0, 'Mnożnik': 0.17, 'Koszt [PLN]': 0.0})
    
    l_f = (e_sz / e_d) - 0.625
    mn = 0.17 if l_f <= 0.05 else (0.50 if l_f <= 0.10 else (0.83 if l_f <= 0.15 else 1.00))
    
    return pd.Series({'Szczyt [kWh]': e_sz, 'PozaSzczytem [kWh]': e_psz, 'L [%]': l_f * 100, 'Mnożnik': mn, 'Koszt [PLN]': e_sz * STAWKA_MOCOWA_BAZOWA * mn})

moc_po = df.groupby('Data_Klucz').apply(lambda x: get_moc_daily_detailed(x, 'Nowy_Pobór'))
moc_pre = df.groupby('Data_Klucz').apply(lambda x: get_moc_daily_detailed(x, 'Pobór'))

# Finanse
def calc_all(col):
    en = df[col].sum() * (cena_mwh / 1000)
    def get_strefa(row):
        h, rob = row['Godzina'], row['Roboczy']
        if taryfa_choice == "B21": return "całodobowa"
        if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
        if taryfa_choice == "B23":
            if not rob: return "pozostałe"
            return "przedpołudnie" if 7 <= h < 13 else ("popołudnie" if 16 <= h < 21 else "pozostałe")
        return "całodobowa"
    df['Tmp_Strefa'] = df.apply(get_strefa, axis=1)
    dys = sum(df[df['Tmp_Strefa'] == s][col].sum() * (osd_data[osd_choice][taryfa_choice][s] + WSPOLNE_NETTO) for s in osd_data[osd_choice][taryfa_choice])
    return en, dys

e_p, d_p = calc_all('Pobór')
e_n, d_n = calc_all('Nowy_Pobór')
total_m_pre, total_m_po = moc_pre['Koszt [PLN]'].sum(), moc_po['Koszt [PLN]'].sum()
z_total = (e_p + d_p + total_m_pre) - (e_n + d_n + total_m_po)

# --- PRZYGOTOWANIE DANYCH AGREGACJI (PODSUMOWANIE KATEGORII K1-K4) ---
cat_map = {0.17: 'K1 (0.17)', 0.50: 'K2 (0.50)', 0.83: 'K3 (0.83)', 1.00: 'K4 (1.00)'}
moc_pre['Mnożnik_R'] = moc_pre['Mnożnik'].round(2)
moc_po['Mnożnik_R'] = moc_po['Mnożnik'].round(2)

sum_pre = moc_pre.groupby('Mnożnik_R')[['Szczyt [kWh]', 'Koszt [PLN]']].sum()
sum_po = moc_po.groupby('Mnożnik_R')[['Szczyt [kWh]', 'Koszt [PLN]']].sum()

summary_cat_data = []
tot_vol_pre = tot_cost_pre = tot_vol_po = tot_cost_po = 0.0

for mn, cat_name in cat_map.items():
    vol_pre = sum_pre.loc[mn, 'Szczyt [kWh]'] / 1000 if mn in sum_pre.index else 0.0
    cost_pre = sum_pre.loc[mn, 'Koszt [PLN]'] if mn in sum_pre.index else 0.0
    vol_po = sum_po.loc[mn, 'Szczyt [kWh]'] / 1000 if mn in sum_po.index else 0.0
    cost_po = sum_po.loc[mn, 'Koszt [PLN]'] if mn in sum_po.index else 0.0
    
    tot_vol_pre += vol_pre
    tot_cost_pre += cost_pre
    tot_vol_po += vol_po
    tot_cost_po += cost_po
    
    summary_cat_data.append({
        "Kategoria": cat_name,
        "Wolumen PRZED [MWh]": vol_pre,
        "Koszt PRZED [PLN]": cost_pre,
        "Wolumen PO PV [MWh]": vol_po,
        "Koszt PO PV [PLN]": cost_po,
        "Zysk w grupie [PLN]": cost_pre - cost_po
    })

# Dodanie wiersza podsumowującego
summary_cat_data.append({
    "Kategoria": "SUMA (CAŁY ROK)",
    "Wolumen PRZED [MWh]": tot_vol_pre,
    "Koszt PRZED [PLN]": tot_cost_pre,
    "Wolumen PO PV [MWh]": tot_vol_po,
    "Koszt PO PV [PLN]": tot_cost_po,
    "Zysk w grupie [PLN]": tot_cost_pre - tot_cost_po
})
df_cat_summary = pd.DataFrame(summary_cat_data).set_index("Kategoria")

# Przygotowanie pełnej tabeli dobowej
detailed_daily_df = pd.DataFrame({
    'Data': moc_pre.index,
    'Szczyt PRZED [kWh]': moc_pre['Szczyt [kWh]'],
    'PozaSzcz. PRZED [kWh]': moc_pre['PozaSzczytem [kWh]'],
    'Szczyt PO PV [kWh]': moc_po['Szczyt [kWh]'],
    'PozaSzcz. PO PV [kWh]': moc_po['PozaSzczytem [kWh]'],
    'L PRZED [%]': moc_pre['L [%]'],
    'L PO PV [%]': moc_po['L [%]'],
    'Mnożnik PRZED': moc_pre['Mnożnik'],
    'Mnożnik PO PV': moc_po['Mnożnik'],
    'Koszt PRZED [PLN]': moc_pre['Koszt [PLN]'],
    'Koszt PO PV [PLN]': moc_po['Koszt [PLN]'],
    'Zysk Opłata Moc. [PLN]': moc_pre['Koszt [PLN]'] - moc_po['Koszt [PLN]']
}).set_index('Data')

# --- ZAKŁADKI (TABS) ---
tab1, tab2, tab3 = st.tabs(["📊 Podsumowanie Roczne", "📈 Analiza Miesięczna", "📅 Szczegóły Dobowe (Opłata Mocowa)"])

with tab1:
    st.subheader("⚡ Szybki Przegląd Profilu (Licznik kWh)")
    c1, c2, c3, c4 = st.columns(4)
    sz_pre, psz_pre = df[df['Is_Szczyt_Mocowy']]['Pobór'].sum(), df[~df['Is_Szczyt_Mocowy']]['Pobór'].sum()
    sz_po, psz_po = df[df['Is_Szczyt_Mocowy']]['Nowy_Pobór'].sum(), df[~df['Is_Szczyt_Mocowy']]['Nowy_Pobór'].sum()
    with c1: st.metric("Szczyt PRZED PV", f"{sz_pre/1000:,.0f} MWh")
    with c2: st.metric("Poza szczytem PRZED PV", f"{psz_pre/1000:,.0f} MWh")
    with c3: st.metric("Szczyt PO PV", f"{sz_po/1000:,.0f} MWh", delta=f"-{(sz_pre-sz_po)/1000:,.0f}")
    with c4: st.metric("Poza szczytem PO PV", f"{psz_po/1000:,.0f} MWh")

    st.markdown("---")
    st.subheader("💰 Bilans Oszczędności Rocznych (Netto)")
    main_res = pd.DataFrame({
        "Składnik": ["Energia czynna", "Dystrybucja zmienna", "Opłata mocowa", "RAZEM"],
        "PRZED PV [PLN]": [e_p, d_p, total_m_pre, e_p+d_p+total_m_pre],
        "PO PV [PLN]": [e_n, d_n, total_m_po, e_n+d_n+total_m_po],
        "ZYSK [PLN]": [e_p-e_n, d_p-d_n, total_m_pre-total_m_po, z_total]
    }).set_index("Składnik")
    st.table(main_res.style.format("{:,.2f}"))

    st.markdown("---")
    st.subheader("📝 Komentarz Eksperta")
    st.success(f"""
    * **Wpływ PV:** Fotowoltaika {moc_pv} kWp zredukowała zakup energii w szczycie o **{((sz_pre-sz_po)/sz_pre)*100:.1f}%**.
    * **Wynik finansowy:** Całkowity zysk netto z inwestycji (oszczędność kosztów) wynosi **{z_total:,.2f} PLN** rocznie.
    """)

with tab2:
    st.subheader("📈 Chronologiczny Bilans Energii [kWh]")
    m_plot = df.groupby('Rok_Miesiac').agg({'Pobór':'sum','Autokonsumpcja':'sum','Etykieta_Miesiac':'first'}).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=m_plot['Etykieta_Miesiac'], y=m_plot['Pobór'], name="Pobór Pierwotny", marker_color='#E74C3C'))
    fig.add_trace(go.Bar(x=m_plot['Etykieta_Miesiac'], y=m_plot['Autokonsumpcja'], name="Autokonsumpcja", marker_color='#2ECC71'))
    fig.update_layout(barmode='group', template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("🧐 Rozkład kategorii mocowych (Dni w miesiącu)")
    st.warning("Gdyby Twój profil poboru wyglądał tak samo w roku 2026 jak na wgranych danych historycznych, w takich kategoriach opłaty mocowej powinieneś się znaleźć. Rzeczywiste wyniki rozliczeń będą zależały od Twojego faktycznego profilu w przyszłości.")
    stats_df = moc_po.copy().reset_index()
    stats_df['Rok_Miesiac'] = pd.to_datetime(stats_df['Data_Klucz']).dt.to_period('M')
    dist = stats_df.groupby(['Rok_Miesiac', 'Mnożnik']).size().unstack(fill_value=0)
    for m in [0.17, 0.50, 0.83, 1.00]:
        if m not in dist.columns: dist[m] = 0
    dist = dist[[0.17, 0.50, 0.83, 1.00]]
    dist.index = dist.index.strftime('%Y-%m')
    st.table((dist.div(dist.sum(axis=1), axis=0) * 100).style.format("{:.1f}%"))

with tab3:
    st.subheader("📊 Podsumowanie Opłaty Mocowej w podziale na Kategorie (K1-K4)")
    
    # NOWY, PRO-KLIENCKI KOMUNIKAT:
    st.info("""
    💡 **Dlaczego w najtańszej kategorii (np. K1) może pojawić się 'minus' w rubryce Zysk?**
    To doskonała wiadomość! Ten minus oznacza po prostu **przeniesienie się większej ilości dni i ujętych w nich kWh z 'drogich stref' (np. K4) do strefy najtańszej (K1)**. 
    Fotowoltaika obcina Twoje szczyty zużycia, dlatego za energię, za którą wcześniej płaciłeś 100% opłaty mocowej, teraz płacisz tylko 17%. Sumaryczny koszt w samej grupie K1 rośnie (bo jest tam teraz więcej dni), ale Twój łączny rachunek drastycznie spada. 
    **Dlatego zawsze patrz na ostateczny zysk w zielonym wierszu SUMA (CAŁY ROK).**
    """)
    
    # Podświetlamy wiersz sumy na inny kolor, żeby nikt go nie przegapił
    st.table(df_cat_summary.style.format({
        "Wolumen PRZED [MWh]": "{:,.2f}",
        "Koszt PRZED [PLN]": "{:,.2f}",
        "Wolumen PO PV [MWh]": "{:,.2f}",
        "Koszt PO PV [PLN]": "{:,.2f}",
        "Zysk w grupie [PLN]": "{:,.2f}"
    }).apply(lambda x: ['background-color: #D7E4BC; font-weight: bold' if x.name == 'SUMA (CAŁY ROK)' else '' for i in x], axis=1))

    st.markdown("---")
    st.subheader("📅 Szczegółowy Raport Dobowy")
    st.write("Możesz przeanalizować, jak fotowoltaika zmienia relację szczytu do pozaszczytu (wskaźnik L) w danej dobie.")
    st.dataframe(detailed_daily_df.style.format({
        'Szczyt PRZED [kWh]': "{:,.0f}", 'PozaSzcz. PRZED [kWh]': "{:,.0f}",
        'Szczyt PO PV [kWh]': "{:,.0f}", 'PozaSzcz. PO PV [kWh]': "{:,.0f}",
        'L PRZED [%]': "{:.2f}%", 'L PO PV [%]': "{:.2f}%",
        'Mnożnik PRZED': "{:.2f}", 'Mnożnik PO PV': "{:.2f}",
        'Koszt PRZED [PLN]': "{:,.2f}", 'Koszt PO PV [PLN]': "{:,.2f}", 'Zysk Opłata Moc. [PLN]': "{:,.2f}"
    }), height=600, use_container_width=True)

# --- EKSPORT DO EXCELA ---
def create_excel(df_fin, df_cat_sum, df_daily):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_fin.to_excel(writer, sheet_name='Podsumowanie')
        
        # Zapis podsumowania kategorii K1-K4
        df_cat_sum.to_excel(writer, sheet_name='Raport Dobowy (Mocowa)', startrow=0, startcol=0)
        
        # Zapis szczegółów dobowych poniżej
        start_row_daily = len(df_cat_sum) + 3 
        df_daily.to_excel(writer, sheet_name='Raport Dobowy (Mocowa)', startrow=start_row_daily, startcol=0)
        
        workbook = writer.book
        ws_podsumowanie = writer.sheets['Podsumowanie']
        ws_dobowy = writer.sheets['Raport Dobowy (Mocowa)']
        
        # Formaty
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        money_fmt = workbook.add_format({'num_format': '#,##0.00 PLN', 'border': 1})
        pct_fmt = workbook.add_format({'num_format': '0.00%', 'border': 1})
        num_fmt = workbook.add_format({'num_format': '#,##0', 'border': 1})
        vol_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        sum_row_fmt = workbook.add_format({'bold': True, 'bg_color': '#E2EFDA', 'border': 1})
        
        # Formatowanie Podsumowanie
        for col_num, value in enumerate(df_fin.columns.values):
            ws_podsumowanie.write(0, col_num + 1, value, header_fmt)
        for row_num, value in enumerate(df_fin.index.values):
            ws_podsumowanie.write(row_num + 1, 0, value, header_fmt)
        ws_podsumowanie.set_column('A:A', 25)
        ws_podsumowanie.set_column('B:E', 20, money_fmt)
        
        # Formatowanie Raport Dobowy - Tabela Kategorii (Góra)
        for col_num, value in enumerate(df_cat_sum.columns.values):
            ws_dobowy.write(0, col_num + 1, value, header_fmt)
        ws_dobowy.write(0, 0, 'Kategoria', header_fmt)
        ws_dobowy.set_column('B:B', 20, vol_fmt)
        ws_dobowy.set_column('C:C', 20, money_fmt)
        ws_dobowy.set_column('D:D', 20, vol_fmt)
        ws_dobowy.set_column('E:F', 20, money_fmt)
        
        # Oznaczenie wiersza SUMA na zielono w Excelu
        for col_num in range(6):
            ws_dobowy.write(len(df_cat_sum), col_num, df_cat_sum.reset_index().iloc[-1, col_num], sum_row_fmt)

        # Formatowanie Raport Dobowy - Tabela Szczegółowa (Dół)
        for col_num, value in enumerate(df_daily.columns.values):
            ws_dobowy.write(start_row_daily, col_num + 1, value, header_fmt)
        ws_dobowy.write(start_row_daily, 0, 'Data', header_fmt)
        ws_dobowy.set_column('A:A', 15)
        ws_dobowy.set_column('F:I', 20, num_fmt) 
        ws_dobowy.set_column('J:K', 15, pct_fmt) 
        ws_dobowy.set_column('L:M', 15) 
        ws_dobowy.set_column('N:P', 20, money_fmt)

    return output.getvalue()

st.sidebar.markdown("---")
st.sidebar.download_button(
    label="📥 Pobierz pełny raport Excel",
    data=create_excel(main_res, df_cat_summary, detailed_daily_df),
    file_name=f"Raport_PV_{osd_choice}_{taryfa_choice}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
