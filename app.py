import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- USTAWIENIA ---
st.set_page_config(page_title="Kalkulator PV B2B - Final Fix", layout="wide")
st.title("⚡ Profesjonalna Analiza PV dla Biznesu (Netto 2026)")

# --- BAZA OSD 2026 (NETTO) ---
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

uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV klienta", type=['csv'])

# --- PANCERNY CZYTNIK PLIKU ---
df = None
if uploaded_file is not None:
    try:
        # 1. Pobieramy surowe bajty
        raw_bytes = uploaded_file.getvalue()
        
        # 2. Próbujemy dekodować polskim formatem Excela (Windows-1250)
        try:
            decoded_text = raw_bytes.decode('cp1250')
        except:
            decoded_text = raw_bytes.decode('utf-8', errors='ignore')
            
        # 3. Czytamy CSV (sep=None wykryje średnik, decimal=',' naprawi przecinki)
        df_raw = pd.read_csv(io.StringIO(decoded_text), sep=None, engine='python', decimal=',')
        
        # 4. Znajdujemy kolumnę z wartościami (zazwyczaj ostatnia lub trzecia)
        val_col = df_raw.columns[2] if len(df_raw.columns) >= 3 else df_raw.columns[-1]
        raw_values = pd.to_numeric(df_raw[val_col], errors='coerce').fillna(0)
        
        # 5. Agregacja 15-minutówek do godzin (jeśli wierszy > 10k)
        if len(raw_values) > 10000:
            hourly_values = raw_values.groupby(np.arange(len(raw_values)) // 4).sum()
            df = pd.DataFrame({"Pobór": hourly_values})
            st.success(f"Pomyślnie przetworzono dane 15-minutowe na {len(df)} godzin.")
        else:
            df = pd.DataFrame({"Pobór": raw_values})
            st.success("Wczytano dane godzinowe.")
            
        df = df.head(8760).reset_index(drop=True)
    except Exception as e:
        st.error(f"Krytyczny błąd odczytu: {e}")

# Jeśli brak pliku - dane testowe
if df is None:
    df = pd.DataFrame({"Pobór": np.random.uniform(20, 60, 8760)})

# --- OBLICZENIA ---
df['Godzina'] = np.arange(len(df)) % 24
df['Roboczy'] = pd.to_datetime(np.arange(len(df)), unit='h', origin='2026-01-01').weekday < 5
df['Generacja_PV'] = np.maximum(0, np.sin((df['Godzina'] - 6) * np.pi / 12)) 
df['Generacja_PV'] = (df['Generacja_PV'] / df['Generacja_PV'].sum()) * (moc_pv * uzysk)
df['Nowy_Pobór'] = np.maximum(0, df['Pobór'] - df['Generacja_PV'])

# Strefy
def get_strefa(row):
    h, rob = row['Godzina'], row['Roboczy']
    if taryfa_choice == "B21": return "całodobowa"
    if taryfa_choice == "B22": return "szczyt" if (6 <= h < 21) and rob else "pozaszczyt"
    if taryfa_choice == "B23":
        if not rob: return "pozosta
