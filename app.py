import os
import requests
from fpdf import FPDF
import io

# --- GENERATOR RAPORTÓW PDF ---
st.markdown("---")
st.subheader("📄 Generowanie Raportu")

def pobierz_czcionke():
    """Pobiera czcionkę TTF z polskimi znakami, jeśli jej nie ma w folderze."""
    font_path = "DejaVuSans.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
        r = requests.get(url, allow_redirects=True)
        open(font_path, 'wb').write(r.content)
    return font_path

def stworz_raport_pdf():
    # Pobranie czcionki
    font_path = pobierz_czcionke()
    
    # Inicjalizacja PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.set_font("DejaVu", "", 12)
    
    # Nagłówek
    pdf.set_font("DejaVu", "", 18)
    pdf.cell(200, 10, txt="Raport Opłacalności Instalacji Fotowoltaicznej (B2B)", ln=True, align='C')
    pdf.ln(10)
    
    # Sekcja: Parametry Wejściowe
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="1. Parametry Inwestycji", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 8, txt=f"Operator OSD: {osd}", ln=True)
    pdf.cell(200, 8, txt=f"Taryfa: {taryfa}", ln=True)
    pdf.cell(200, 8, txt=f"Moc instalacji PV: {moc_pv} kWp", ln=True)
    pdf.cell(200, 8, txt=f"Moc umowna firmy: {moc_umowna} kW", ln=True)
    pdf.ln(5)
    
    # Sekcja: Bilans Energetyczny
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="2. Bilans Energetyczny (Roczny)", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 8, txt=f"Pobór z sieci PRZED instalacją: {df['Zużycie (kWh)'].sum()/1000:,.1f} MWh".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Pobór z sieci PO instalacji PV: {df['Pobor_z_sieci_po_PV'].sum()/1000:,.1f} MWh".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Całkowita generacja z PV: {df['Generacja_PV_kWh'].sum()/1000:,.1f} MWh".replace(',', ' '), ln=True)
    pdf.ln(5)
    
    # Sekcja: Opłata Mocowa
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="3. Wpływ na Opłatę Mocową i Kwalifikację (K1-K4)", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.cell(200, 8, txt=f"Kwalifikacja PRZED PV: {kat_przed_nazwa} (Koszt: {koszt_mocowy_przed:,.2f} PLN)".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Kwalifikacja PO PV: {kat_po_nazwa} (Koszt: {koszt_mocowy_po:,.2f} PLN)".replace(',', ' '), ln=True)
    pdf.cell(200, 8, txt=f"Oszczędność na samej opłacie mocowej: {(koszt_mocowy_przed - koszt_mocowy_po):,.2f} PLN".replace(',', ' '), ln=True)
    pdf.ln(5)
    
    # Sekcja: Podsumowanie Finansowe
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt="4. Podsumowanie Finansowe (Wartości Netto)", ln=True)
    pdf.set_font("DejaVu", "", 12)
    pdf.multi_cell(0, 8, txt="Poniższa kwota uwzględnia oszczędności na energii czynnej, zmiennych opłatach dystrybucyjnych oraz redukcji opłaty mocowej wynikającej ze zmiany profilu poboru w godzinach szczytowych.")
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 14)
    pdf.cell(200, 10, txt=f"SZACOWANY ZYSK ROCZNY: {zysk_roczny:,.2f} PLN".replace(',', ' '), ln=True)
    
    # Zapis do obiektu w pamięci (zamiast na dysk)
    return pdf.output(dest='S').encode('latin-1')

# --- PRZYCISK POBIERANIA ---
# Tworzymy PDF w locie tylko gdy użytkownik kliknie przycisk
st.info("Pobierz szczegółowy raport w formacie PDF ze wszystkimi wyliczeniami dla klienta.")
pdf_bytes = stworz_raport_pdf()

st.download_button(
    label="📥 Pobierz Raport PDF",
    data=pdf_bytes,
    file_name="Raport_Oplacalnosci_PV.pdf",
    mime="application/pdf"
)
