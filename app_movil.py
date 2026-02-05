import streamlit as st
import psycopg2
import io
import os
import time
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Venta Móvil - Pro", page_icon="🎫", layout="centered")

# --- CONEXIÓN A BASE DE DATOS ---
try:
    DB_URI = st.secrets["SUPABASE_URL"]
except:
    # PEGA TU URL DE SUPABASE AQUÍ PARA PRUEBAS LOCALES
    DB_URI = "TU_URL_DE_SUPABASE_AQUI"

@st.cache_resource
def init_connection():
    try:
        return psycopg2.connect(DB_URI, connect_timeout=10)
    except Exception as e:
        st.error(f"Error conectando a BD: {e}")
        return None

def run_query(query, params=None):
    conn = init_connection()
    if not conn: return None
    try:
        if conn.closed: conn = init_connection()
        with conn.cursor() as cur:
            cur.execute(query, params)
            if query.strip().upper().startswith("SELECT"):
                return cur.fetchall()
            else:
                conn.commit()
                return True
    except Exception as e:
        st.error(f"Error SQL: {e}")
        return None

# ============================================================================
#  MOTOR DE PDF EXACTO (Copiado y adaptado de tu servicios.py)
# ============================================================================
def generar_pdf_exacto_memoria(numero_boleto, datos_completos, config_db):
    """
    Genera el PDF idéntico al de escritorio usando la misma lógica de coordenadas y fuentes.
    """
    buffer = io.BytesIO()

    # 1. PREPARAR DATOS (Simulando la estructura de tu PC)
    # config_db trae la data cruda, la convertimos al diccionario que espera tu código antiguo
    rifa = config_db['rifa']
    empresa = config_db['empresa']
    
    config = {
        'rifa_actual': rifa,
        'empresa': empresa
    }
    
    # Datos del boleto
    num_str = f"{numero_boleto:03d}" # Asumimos 3 dígitos por defecto
    nom_cli = datos_completos.get('cliente', '')
    cedula = datos_completos.get('cedula', '')
    tel = datos_completos.get('telefono', '')
    direcc = datos_completos.get('direccion', '')
    codigo_cli = datos_completos.get('codigo_cli', '')
    estado_fmt = datos_completos.get('estado', '').upper()
    precio = float(datos_completos.get('precio', 0))
    abonado = float(datos_completos.get('abonado', 0))
    saldo = precio - abonado
    fecha_asig = datos_completos.get('fecha_asignacion', datetime.now().strftime('%Y-%m-%d'))

    # 2. CÁLCULO DE ALTURA (Lógica exacta de servicios.py)
    lista_claves_premios = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    count_premios = 0
    for k in lista_claves_premios:
        if rifa.get(k): count_premios += 1
    
    altura_minima = 390
    altura_extra = max(0, (count_premios - 3) * 20) 
    total_h = altura_minima + altura_extra
    total_w = 390
    
    c = canvas.Canvas(buffer, pagesize=(total_w, total_h))
    m_izq, m_der = 30, total_w - 30
    centro = total_w / 2
    y = total_h - 30
    
    # 3. DIBUJO EXACTO (Pixel perfect)
    
    # Logo: Buscamos un archivo local en la carpeta del script
    # IMPORTANTE: Debes subir tu logo.png a la misma carpeta
    logo_candidates = ["logo.png", "logo.jpg", "logo.jpeg"]
    logo_path = None
    for cand in logo_candidates:
        if os.path.exists(cand):
            logo_path = cand
            break
            
    if logo_path:
        try:
            c.drawImage(ImageReader(logo_path), m_izq, y-27, width=38, height=38, preserveAspectRatio=True, mask='auto')
        except: pass
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m_izq + 50, y, empresa.get('nombre', 'SORTEOS'))
    c.setFont("Helvetica", 8)
    c.drawString(m_izq + 50, y-12, f"RIF: {empresa.get('rif', '')}")
    c.drawString(m_izq + 50, y-25, f"Tel: {empresa.get('telefono', '')}")
    
    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.70, 0.55, 0.35) # Dorado
    c.drawRightString(m_der, y-5, f"BOLETO N° {num_str}")
    c.setFillColorRGB(0,0,0)
    
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(m_der, y-25, f"Emitido: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    
    y -= 35
    c.setStrokeColorRGB(0.70, 0.55, 0.35)
    c.line(m_izq, y, m_der, y)
    y -= 18
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(centro, y, "COMPROBANTE DE SORTEO")
    y -= 8
    c.line(m_izq, y, m_der, y)
    
    # SECCIÓN 2: DATOS
    y_start = y - 20
    col_izq_x = m_izq
    col_der_x = centro + 20 
    
    y = y_start
    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_izq_x, y, "SORTEO:")
    c.drawString(col_izq_x + 50, y, rifa['nombre'][:35])
    y -= 15
    c.drawString(col_izq_x, y, "FECHA:")
    fs = rifa.get('fecha_sorteo', '')
    hs = rifa.get('hora_sorteo', '')
    c.drawString(col_izq_x + 50, y, f"{fs} {hs}")
    
    y_prem = y_start
    c.drawString(col_der_x, y_prem, "PREMIOS:")
    y_prem -= 12
    c.setFont("Helvetica", 9)
    etiquetas = ["1er:", "2do:", "3er:", "Ext:", "Ext:"]
    hay_premio = False
    for i, k in enumerate(lista_claves_premios):
        val = rifa.get(k, "")
        if val:
            lbl = etiquetas[i] if i < len(etiquetas) else f"{i+1}º:"
            c.drawString(col_der_x, y_prem, f"{lbl} {val[:35]}")
            y_prem -= 12
            hay_premio = True
    
    # SECCIÓN 3: CLIENTE
    y_fin_arriba = min(y, y_prem)
    y_linea = y_fin_arriba - 10
    c.setLineWidth(1)
    c.setStrokeColorRGB(0, 0, 0) # Negro para lineas divisorias
    c.line(m_izq, y_linea, m_der, y_linea) 
    y = y_linea - 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(m_izq, y, "INFORMACIÓN DEL CLIENTE")
    y -= 15
    c.setFont("Helvetica", 9)
    gap = 12
    c.drawString(m_izq, y, f"Código: {codigo_cli or ''}")
    y -= gap
    c.drawString(m_izq, y, f"Nombre: {nom_cli or ''}")
    y -= gap
    c.drawString(m_izq, y, f"Cédula: {cedula or ''}")
    y -= gap
    c.drawString(m_izq, y, f"Teléfono: {tel or ''}")
    y -= gap
    c.drawString(m_izq, y, f"Dirección: {direcc or ''}")
    y -= 10
    c.line(m_izq, y, m_der, y)

    # SECCIÓN 4: PAGOS
    y_final = y - 20
    x_div = total_w * 0.55
    c.line(x_div, y_final + 5, x_div, y_final - 55)
    y = y_final
    c.setFont("Helvetica-Bold", 10)
    c.drawString(m_izq, y, "INFORMACIÓN DE PAGOS")
    y -= 15
    c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Precio Total: ${precio:,.2f}")
    y -= 12
    c.drawString(m_izq, y, f"Total Abonado: ${abonado:,.2f}")
    y -= 12
    c.drawString(m_izq, y, f"Saldo Pendiente: ${saldo:,.2f}")
    y -= 18
    c.setFont("Helvetica", 8)
    
    c.drawString(m_izq, y, f"Fecha registro: {str(fecha_asig)}")
    
    # ESTADO (GRANDE Y DE COLOR)
    y_est = y_final
    centro_der = x_div + ((m_der - x_div) / 2)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(centro_der, y_est, "ESTADO:")
    c.setFont("Helvetica-Bold", 18) 
    c.setFillColorRGB(0, 0, 0.4) # Azul Oscuro
    c.drawCentredString(centro_der, y_est - 30, estado_fmt)
    c.setFillColorRGB(0, 0, 0)

    # FOOTER
    y -= 25 
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setLineWidth(0.5)
    c.line(m_izq, y, m_der, y)
    y -= 15 
    c.setFont("Helvetica-BoldOblique", 8)
    c.drawCentredString(centro, y, "¡GRACIAS POR PARTICIPAR EN NUESTRO SORTEO!")
    y -= 10
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(centro, y, "Este comprobante es su garantía. Por favor, consérvelo.")

    c.save()
    buffer.seek(0)
    return buffer

# --- INTERFAZ GRÁFICA ---
def main():
    st.title("📱 Sorteos - Venta Rápida")

    # 1. CARGAR CONFIGURACIÓN GLOBAL (EMPRESA + SORTEO)
    sorteos = run_query("SELECT id, nombre, precio_boleto, fecha_sorteo, hora_sorteo, premio1, premio2, premio3, premio_extra1, premio_extra2 FROM sorteos WHERE activo = TRUE")
    config_rows = run_query("SELECT clave, valor FROM configuracion")
    
    if not sorteos:
        st.warning("No hay sorteos activos.")
        return

    # Construir diccionario de configuración de empresa
    empresa_config = {"nombre": "SORTEOS MILÁN", "rif": "", "telefono": ""}
    if config_rows:
        cfg_dict = {r[0]: r[1] for r in config_rows}
        empresa_config['nombre'] = cfg_dict.get('nombre_empresa', 'SORTEOS MILÁN')
        empresa_config['rif'] = cfg_dict.get('rif', '')
        empresa_config['telefono'] = cfg_dict.get('telefono', '')

    # Selector de Sorteo
    opciones_sorteo = {s[1]: s for s in sorteos}
    nom_sorteo = st.selectbox("Selecciona Sorteo:", list(opciones_sorteo.keys()))
    
    if nom_sorteo:
        s_data = opciones_sorteo[nom_sorteo]
        id_sorteo = s_data[0]
        
        # Construir objeto 'rifa' para el PDF
        rifa_config = {
            "nombre": s_data[1], "precio_boleto": float(s_data[2] or 0),
            "fecha_sorteo": str(s_data[3]), "hora_sorteo": str(s_data[4]),
            "premio1": s_data[5], "premio2": s_data[6], "premio3": s_data[7],
            "premio_extra1": s_data[8], "premio_extra2": s_data[9]
        }
        
        # 2. BUSCAR BOLETO
        col1, col2 = st.columns([2, 1])
        with col1:
            numero = st.number_input("Número de Boleto:", min_value=0, max_value=9999, step=1, value=0)
        with col2:
            st.write("##")
            btn_buscar = st.button("🔍 Buscar")
            
        boleto_info = run_query("""
            SELECT b.id, b.estado, b.precio, b.total_abonado, b.fecha_asignacion,
                   c.nombre_completo, c.telefono, c.cedula, c.direccion, c.codigo
            FROM boletos b
            LEFT JOIN clientes c ON b.cliente_id = c.id
            WHERE b.numero = %s AND b.sorteo_id = %s
        """, (numero, id_sorteo))
        
        if boleto_info:
            b_id, estado, b_precio, b_abonado, b_fecha, c_nom, c_tel, c_ced, c_dir, c_cod = boleto_info[0]
            
            # --- MOSTRAR ESTADO ---
            colors = {'disponible': 'green', 'apartado': 'orange', 'pagado': 'blue', 'abonado': 'violet'}
            st.markdown(f":{colors.get(estado, 'grey')}[**ESTADO: {estado.upper()}**]")

            if estado == 'disponible':
                with st.expander("🛒 VENDER AHORA", expanded=True):
                    with st.form("venta"):
                        c_n = st.text_input("Nombre"); c_t = st.text_input("Teléfono"); c_c = st.text_input("Cédula")
                        abono = st.number_input("Abono ($)", value=float(rifa_config['precio_boleto']))
                        if st.form_submit_button("VENDER"):
                             # (Aquí iría la lógica de INSERT cliente/boleto idéntica a la respuesta anterior)
                             # ... Lógica de venta ...
                             st.success("Venta Simulada (Pega la lógica de INSERT aquí)")
            else:
                # --- GENERAR PDF IDÉNTICO ---
                datos_para_pdf = {
                    'cliente': c_nom, 'cedula': c_ced, 'telefono': c_tel,
                    'direccion': c_dir, 'codigo_cli': c_cod,
                    'estado': estado, 'precio': b_precio, 'abonado': b_abonado,
                    'fecha_asignacion': b_fecha
                }
                
                # Pasamos la configuración completa (Empresa + Rifa)
                config_full = {'rifa': rifa_config, 'empresa': empresa_config}
                
                pdf_bytes = generar_pdf_exacto_memoria(numero, datos_para_pdf, config_full)
                
                st.download_button(
                    label="📄 DESCARGAR PDF (OFICIAL)",
                    data=pdf_bytes,
                    file_name=f"Boleto_{numero}_Original.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        else:
            st.info("Boleto libre (No inicializado en BD).")

if __name__ == "__main__":
    main()