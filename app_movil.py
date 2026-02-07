import streamlit as st
import psycopg2
import io
import os
import time
import urllib.parse
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Sorteos Milán Móvil", page_icon="🎫", layout="centered")

# --- CONEXIÓN A BASE DE DATOS ---
try:
    DB_URI = st.secrets["SUPABASE_URL"]
except:
    DB_URI = "TU_URL_DE_SUPABASE_AQUI"

@st.cache_resource
def init_connection():
    try:
        return psycopg2.connect(DB_URI, connect_timeout=10)
    except Exception as e:
        st.error(f"Error conectando a BD: {e}")
        return None

def run_query(query, params=None, fetch=True):
    conn = init_connection()
    if not conn: return None
    try:
        if conn.closed: conn = init_connection()
        with conn.cursor() as cur:
            cur.execute(query, params)
            if fetch:
                return cur.fetchall()
            else:
                conn.commit()
                return True
    except Exception as e:
        st.error(f"Error SQL: {e}")
        return None

# ============================================================================
#  1. FORMATO DE WHATSAPP (Idéntico a gestion_boletos.py / servicios.py)
# ============================================================================
def get_whatsapp_link_exacto(telefono, boleto_num, estado, cliente_nom, sorteo_nom, fecha_sorteo, cantidad_boletos=1000):
    if not telefono: return ""
    
    # Limpieza de teléfono
    tel_clean = "".join(filter(str.isdigit, str(telefono)))
    if len(tel_clean) == 10: tel_clean = "58" + tel_clean
    elif len(tel_clean) == 11 and tel_clean.startswith("0"): tel_clean = "58" + tel_clean[1:]
    
    # Formateo de Estado
    est_str = estado.upper()
    if estado == 'pagado': est_str = "PAGADO"
    elif estado == 'abonado': est_str = "ABONADO"
    elif estado == 'apartado': est_str = "APARTADO"
    
    # 🔥 CORRECCIÓN: Formato dinámico de ceros (01 vs 001)
    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
    num_str = fmt_num.format(boleto_num)
    
    texto_boleto = f"N° {num_str} ({est_str})"
    
    # Mensaje exacto de PC
    mensaje = (
        f"Hola. Saludos, somos Sorteos Milán!!, aquí te enviamos el comprobante de tu "
        f"BOLETO: {texto_boleto}, a nombre de '{cliente_nom}' para el sorteo "
        f"'{sorteo_nom}' del día '{fecha_sorteo}' . ¡Suerte!🍀"
    )
    
    return f"https://wa.me/{tel_clean}?text={urllib.parse.quote(mensaje)}"

# ============================================================================
#  2. PDF DIGITAL (Idéntico a servicios.py con corrección de ceros)
# ============================================================================
def generar_pdf_memoria(numero_boleto, datos_completos, config_db, cantidad_boletos=1000):
    buffer = io.BytesIO()
    rifa = config_db['rifa']
    empresa = config_db['empresa']
    
    # 🔥 CORRECCIÓN: Formato dinámico en el PDF
    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
    num_str = fmt_num.format(numero_boleto)
    
    # Datos
    nom_cli = datos_completos.get('cliente', '')
    cedula = datos_completos.get('cedula', '')
    tel = datos_completos.get('telefono', '')
    direcc = datos_completos.get('direccion', '')
    codigo_cli = datos_completos.get('codigo_cli', '')
    estado_fmt = datos_completos.get('estado', '').upper()
    precio = float(datos_completos.get('precio', 0))
    abonado = float(datos_completos.get('abonado', 0))
    saldo = precio - abonado
    fecha_asig = datos_completos.get('fecha_asignacion', '')

    # Altura dinámica según premios
    lista_claves = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    count_premios = sum(1 for k in lista_claves if rifa.get(k))
    total_h = 390 + max(0, (count_premios - 3) * 20)
    total_w = 390
    
    c = canvas.Canvas(buffer, pagesize=(total_w, total_h))
    m_izq, m_der = 30, total_w - 30
    centro = total_w / 2
    y = total_h - 30
    
    # LOGO
    logo_files = ["logo.jpg", "logo.png", "logo.jpeg"]
    for f in logo_files:
        if os.path.exists(f):
            try:
                c.drawImage(ImageReader(f), m_izq, y-27, width=38, height=38, preserveAspectRatio=True, mask='auto')
                break
            except: pass

    # Encabezado
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m_izq + 50, y, empresa.get('nombre', 'SORTEOS MILÁN'))
    c.setFont("Helvetica", 8)
    c.drawString(m_izq + 50, y-12, f"RIF: {empresa.get('rif', '')}")
    c.drawString(m_izq + 50, y-25, f"Tel: {empresa.get('telefono', '')}")
    
    # Número Boleto (Con el formato corregido)
    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.70, 0.55, 0.35) 
    c.drawRightString(m_der, y-5, f"BOLETO N° {num_str}")
    c.setFillColorRGB(0,0,0)
    
    # Fecha
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(m_der, y-25, f"Emitido: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    
    y -= 35; c.setStrokeColorRGB(0.70, 0.55, 0.35); c.line(m_izq, y, m_der, y)
    
    y -= 18; c.setFont("Helvetica-Bold", 15)
    
    # --- CAMBIO DE COLOR (Dorado) ---
    c.setFillColorRGB(0.70, 0.55, 0.35) 
    c.drawCentredString(centro, y, "COMPROBANTE DE SORTEO")
    c.setFillColorRGB(0, 0, 0) # Volver a negro para lo demás
    # -------------------------------
    
    y -= 8; c.line(m_izq, y, m_der, y)
    
    # Datos Sorteo
    y_start = y - 20
    col_izq_x = m_izq; col_der_x = centro + 20 
    y = y_start
    c.setFont("Helvetica-Bold", 10); c.drawString(col_izq_x, y, "SORTEO:")
    c.drawString(col_izq_x + 50, y, rifa['nombre'][:35])
    y -= 15
    c.drawString(col_izq_x, y, "FECHA:")
    c.drawString(col_izq_x + 50, y, f"{rifa.get('fecha_sorteo','')} {rifa.get('hora_sorteo','')}")
    
    # Premios
    y_prem = y_start
    c.drawString(col_der_x, y_prem, "PREMIOS:")
    y_prem -= 12; c.setFont("Helvetica", 9)
    etiquetas = ["1er:", "2do:", "3er:", "Ext:", "Ext:"]
    for i, k in enumerate(lista_claves):
        val = rifa.get(k, "")
        if val:
            lbl = etiquetas[i] if i < len(etiquetas) else f"{i+1}º:"
            c.drawString(col_der_x, y_prem, f"{lbl} {val[:30]}")
            y_prem -= 12
    
    # Cliente
    y_fin_arriba = min(y, y_prem)
    y_linea = y_fin_arriba - 10
    c.setLineWidth(1); c.setStrokeColorRGB(0, 0, 0)
    c.line(m_izq, y_linea, m_der, y_linea) 
    y = y_linea - 20
    
    c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "INFORMACIÓN DEL CLIENTE")
    y -= 15; c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Código: {codigo_cli or ''}")
    y -= 12
    c.drawString(m_izq, y, f"Nombre: {nom_cli}")
    y -= 12
    c.drawString(m_izq, y, f"Cédula: {cedula}")
    y -= 12
    c.drawString(m_izq, y, f"Teléfono: {tel}")
    y -= 12
    c.drawString(m_izq, y, f"Dirección: {direcc}")
    y -= 10
    c.line(m_izq, y, m_der, y)
    
    # Pagos
    y_final = y - 20
    x_div = total_w * 0.55
    c.line(x_div, y_final + 5, x_div, y_final - 55)
    y = y_final
    c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "INFORMACIÓN DE PAGOS")
    y -= 15; c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Precio Total: ${precio:,.2f}")
    y -= 12; c.drawString(m_izq, y, f"Total Abonado: ${abonado:,.2f}")
    y -= 12
    c.drawString(m_izq, y, f"Saldo Pendiente: ${saldo:,.2f}")
    y -= 18; c.setFont("Helvetica", 8)
    c.drawString(m_izq, y, f"Fecha registro: {str(fecha_asig)}")
    
    # Estado
    y_est = y_final
    centro_der = x_div + ((m_der - x_div) / 2)
    c.setFont("Helvetica-Bold", 10); c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(centro_der, y_est, "ESTADO:")
    c.setFont("Helvetica-Bold", 18); c.setFillColorRGB(0, 0, 0.4) 
    c.drawCentredString(centro_der, y_est - 30, estado_fmt)
    c.setFillColorRGB(0, 0, 0)
    
    # Footer
    y -= 25; c.setStrokeColorRGB(0.7, 0.7, 0.7); c.setLineWidth(0.5)
    c.line(m_izq, y, m_der, y)
    y -= 15; c.setFont("Helvetica-BoldOblique", 8)
    c.drawCentredString(centro, y, "¡GRACIAS POR PARTICIPAR EN NUESTRO SORTEO!")
    y -= 10; c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(centro, y, "Este comprobante es su garantía. Por favor, consérvelo.")
    
    c.save()
    buffer.seek(0)
    return buffer

# ============================================================================
#  2. PDF DIGITAL (APP MÓVIL - LÍNEAS DORADAS)
# ============================================================================
def generar_pdf_memoria(numero_boleto, datos_completos, config_db, cantidad_boletos=1000):
    buffer = io.BytesIO()
    rifa = config_db['rifa']
    empresa = config_db['empresa']
    
    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
    num_str = fmt_num.format(numero_boleto)
    
    # Datos
    nom_cli = datos_completos.get('cliente', '')
    cedula = datos_completos.get('cedula', '')
    tel = datos_completos.get('telefono', '')
    direcc = datos_completos.get('direccion', '')
    codigo_cli = datos_completos.get('codigo_cli', '')
    estado_fmt = datos_completos.get('estado', '').upper()
    precio = float(datos_completos.get('precio', 0))
    abonado = float(datos_completos.get('abonado', 0))
    saldo = precio - abonado
    fecha_asig = datos_completos.get('fecha_asignacion', '')

    # Altura dinámica
    lista_claves = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    count_premios = sum(1 for k in lista_claves if rifa.get(k))
    total_h = 390 + max(0, (count_premios - 3) * 20)
    total_w = 390
    
    c = canvas.Canvas(buffer, pagesize=(total_w, total_h))
    m_izq, m_der = 30, total_w - 30
    centro = total_w / 2
    y = total_h - 30
    
    # LOGO
    logo_files = ["logo.jpg", "logo.png", "logo.jpeg"]
    for f in logo_files:
        if os.path.exists(f):
            try:
                c.drawImage(ImageReader(f), m_izq, y-27, width=38, height=38, preserveAspectRatio=True, mask='auto')
                break
            except: pass

    # Encabezado
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m_izq + 50, y, empresa.get('nombre', 'SORTEOS MILÁN'))
    c.setFont("Helvetica", 8)
    c.drawString(m_izq + 50, y-12, f"RIF: {empresa.get('rif', '')}")
    c.drawString(m_izq + 50, y-25, f"Tel: {empresa.get('telefono', '')}")
    
    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.70, 0.55, 0.35) 
    c.drawRightString(m_der, y-5, f"BOLETO N° {num_str}")
    c.setFillColorRGB(0,0,0)
    
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(m_der, y-25, f"Emitido: {datetime.now().strftime('%d/%m/%Y %I:%M %p').lower()}")
    
    # --- HEADER: LÍNEAS DORADAS ---
    y -= 35
    c.setStrokeColorRGB(0.70, 0.55, 0.35)
    c.line(m_izq, y, m_der, y)
    y -= 18
    c.setFont("Helvetica-Bold", 15)
    c.setFillColorRGB(0.70, 0.55, 0.35) 
    c.drawCentredString(centro, y, "COMPROBANTE DE SORTEO")
    c.setFillColorRGB(0, 0, 0)
    y -= 8
    c.line(m_izq, y, m_der, y)
    
    # Datos Sorteo
    y_start = y - 20
    col_izq_x = m_izq
    col_der_x = centro - 20 
    
    y = y_start
    c.setFont("Helvetica-Bold", 10); c.drawString(col_izq_x, y, "SORTEO:")
    c.drawString(col_izq_x + 50, y, rifa['nombre'][:35])
    y -= 15
    c.drawString(col_izq_x, y, "FECHA:")
    c.drawString(col_izq_x + 50, y, f"{rifa.get('fecha_sorteo','')} {rifa.get('hora_sorteo','')}")
    
    # Premios
    y_prem = y_start
    c.drawString(col_der_x, y_prem, "PREMIOS:")
    y_prem -= 12; c.setFont("Helvetica", 9)
    etiquetas = ["1er:", "2do:", "3er:", "Ext:", "Ext:"]
    for i, k in enumerate(lista_claves):
        val = rifa.get(k, "")
        if val:
            lbl = etiquetas[i] if i < len(etiquetas) else f"{i+1}º:"
            c.drawString(col_der_x, y_prem, f"{lbl} {val[:30]}")
            y_prem -= 12
    
    # --- SECCIÓN CLIENTE: LÍNEAS DORADAS ---
    y_fin_arriba = min(y, y_prem)
    y_linea = y_fin_arriba - 10
    
    c.setLineWidth(1)
    c.setStrokeColorRGB(0.70, 0.55, 0.35) # 🔥 CAMBIO: Color Dorado
    c.line(m_izq, y_linea, m_der, y_linea) 
    y = y_linea - 20
    
    c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "INFORMACIÓN DEL CLIENTE")
    y -= 15; c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Código: {codigo_cli or ''}")
    y -= 12
    c.drawString(m_izq, y, f"Nombre: {nom_cli}")
    y -= 12
    c.drawString(m_izq, y, f"Cédula: {cedula}")
    y -= 12
    c.drawString(m_izq, y, f"Teléfono: {tel}")
    y -= 12
    c.drawString(m_izq, y, f"Dirección: {direcc}")
    y -= 10
    
    # Línea inferior del cliente (Hereda el dorado anterior)
    c.line(m_izq, y, m_der, y) 
    
    # --- SECCIÓN PAGOS ---
    y_final = y - 20
    x_div = total_w * 0.55
    
    # Línea Vertical (Hereda el dorado)
    c.line(x_div, y_final + 5, x_div, y_final - 55)
    
    y = y_final
    c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "INFORMACIÓN DE PAGOS")
    y -= 15; c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Precio Total: ${precio:,.2f}")
    y -= 12; c.drawString(m_izq, y, f"Total Abonado: ${abonado:,.2f}")
    y -= 12
    c.drawString(m_izq, y, f"Saldo Pendiente: ${saldo:,.2f}")
    y -= 18; c.setFont("Helvetica", 8)
    f_reg = fecha_asig if fecha_asig else datetime.now().strftime('%d/%m/%Y %I:%M %p')
    c.drawString(m_izq, y, f"Fecha de registro: {str(f_reg).lower()}")
    
    # Estado
    y_est = y_final
    centro_der = x_div + ((m_der - x_div) / 2)
    c.setFont("Helvetica-Bold", 10); c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(centro_der, y_est, "ESTADO:")
    c.setFont("Helvetica-Bold", 18); c.setFillColorRGB(0, 0, 0.4) 
    c.drawCentredString(centro_der, y_est - 30, estado_fmt)
    c.setFillColorRGB(0, 0, 0)
    
    # --- FOOTER (GRIS) ---
    y -= 25
    c.setStrokeColorRGB(0.7, 0.7, 0.7) # 🔥 EXCEPCIÓN: Volvemos a Gris
    c.setLineWidth(0.5)
    c.line(m_izq, y, m_der, y)
    
    y -= 15; c.setFont("Helvetica-BoldOblique", 8)
    c.drawCentredString(centro, y, "¡GRACIAS POR PARTICIPAR EN NUESTRO SORTEO!")
    y -= 10; c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(centro, y, "Este comprobante es su garantía. Por favor, consérvelo.")
    
    c.save()
    buffer.seek(0)
    return buffer

# ============================================================================
#  SISTEMA DE LOGIN
# ============================================================================
def check_password():
    """Retorna True si el usuario ingresó la clave correcta."""
    if st.session_state.get("password_correct", False):
        return True

    st.markdown("### 🔐 Acceso Restringido")
    pwd_input = st.text_input("Ingresa la contraseña:", type="password")
    
    if st.button("Entrar"):
        # Usa la clave de los Secrets o "admin123" por defecto si no existe
        clave_secreta = st.secrets.get("PASSWORD_APP", "admin123")
        if pwd_input == clave_secreta:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("❌ Contraseña incorrecta")
    return False

# ============================================================================
#  APP PRINCIPAL
# ============================================================================
def main():
    with st.sidebar:
        if st.button("🔒 Cerrar Sesión"):
            st.session_state["password_correct"] = False
            st.rerun()

    st.title("📱 Sorteos Milán")

    # Cargar Datos Generales
    sorteos = run_query("SELECT id, nombre, precio_boleto, fecha_sorteo, hora_sorteo, premio1, premio2, premio3, premio_extra1, premio_extra2 FROM sorteos WHERE activo = TRUE")
    config_rows = run_query("SELECT clave, valor FROM configuracion")
    
    if not sorteos: st.warning("No hay sorteos activos."); return

    empresa_config = {"nombre": "SORTEOS MILÁN", "rif": "", "telefono": ""}
    if config_rows:
        cfg = {r[0]: r[1] for r in config_rows}
        empresa_config.update({k: v for k, v in cfg.items() if k in empresa_config})

    # Selector Sorteo
    opciones_sorteo = {s[1]: s for s in sorteos}
    nom_sorteo = st.selectbox("Sorteo Activo:", list(opciones_sorteo.keys()))
    
    if not nom_sorteo: return
    s_data = opciones_sorteo[nom_sorteo]
    id_sorteo, nombre_s, precio_s, fecha_s = s_data[0], s_data[1], float(s_data[2] or 0), s_data[3]
    
    # 🔥 DETECCIÓN AUTOMÁTICA DE CANTIDAD
    cantidad_boletos = 1000
    if config_rows:
        cfg_dict = {r[0]: r[1] for r in config_rows}
        clave_cap = f"capacidad_sorteo_{id_sorteo}"
        if clave_cap in cfg_dict:
            cantidad_boletos = int(cfg_dict[clave_cap])
        else:
            max_bol = run_query("SELECT MAX(numero) FROM boletos WHERE sorteo_id=%s", (id_sorteo,))
            if max_bol and max_bol[0][0] is not None and max_bol[0][0] <= 99:
                cantidad_boletos = 100
    
    st.caption(f"⚙️ Modo: {cantidad_boletos} boletos")

    # Objeto Rifa Global
    rifa_config = {
        "nombre": nombre_s, "precio_boleto": precio_s, "fecha_sorteo": str(fecha_s), "hora_sorteo": str(s_data[4]),
        "premio1": s_data[5], "premio2": s_data[6], "premio3": s_data[7], "premio_extra1": s_data[8], "premio_extra2": s_data[9]
    }
    config_full = {'rifa': rifa_config, 'empresa': empresa_config}
    
    # CREACIÓN DE PESTAÑAS (Agregamos COBRANZA)
    tab_venta, tab_clientes, tab_cobranza = st.tabs(["🎫 VENTA", "👥 CLIENTES", "💰 COBRANZA"])

    # ---------------- PESTAÑA VENTA ----------------
    with tab_venta:
        # --- SECCIÓN 1: VISUALIZACIÓN EN VIVO ---
        st.write("### 📊 Estado del Sorteo")
        ver_ocupados = st.checkbox("Mostrar Ocupados (Amarillo)", value=True)
        img_bytes = generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, mostrar_ocupados=ver_ocupados)
        st.image(img_bytes, caption="Actualizado en tiempo real", use_container_width=True)
        nombre_archivo = "Tabla_ConOcupados.jpg" if ver_ocupados else "Tabla_Limpia.jpg"
        st.download_button("⬇️ DESCARGAR IMAGEN", img_bytes, nombre_archivo, "image/jpeg", use_container_width=True)
        
        st.divider() 

        # --- SELECTOR DE MODO ---
        modo = st.radio("🔍 Método de Búsqueda:", ["🔢 Por N° de Boleto", "👤 Por Cliente"], horizontal=True)
        st.write("") 

        # ============================================================
        #  MODO A: POR NÚMERO (Individual)
        # ============================================================
        if modo == "🔢 Por N° de Boleto":
            fmt_input = "%02d" if cantidad_boletos <= 100 else "%03d"
            c1, c2 = st.columns([2,1])
            numero = c1.number_input("Boleto N°:", min_value=0, max_value=cantidad_boletos-1, step=1, format=fmt_input)
            if c2.button("🔍 Buscar", use_container_width=True): pass
            
            boleto_info = run_query("""
                SELECT b.id, b.estado, b.precio, b.total_abonado, b.fecha_asignacion,
                       c.nombre_completo, c.telefono, c.cedula, c.direccion, c.codigo
                FROM boletos b
                LEFT JOIN clientes c ON b.cliente_id = c.id
                WHERE b.numero = %s AND b.sorteo_id = %s
            """, (numero, id_sorteo))
            
            if boleto_info:
                # --- OCUPADO ---
                b_id, estado, b_precio, b_abonado, b_fecha, c_nom, c_tel, c_ced, c_dir, c_cod = boleto_info[0]
                b_precio = float(b_precio); b_abonado = float(b_abonado)
                
                st.info(f"👤 {c_nom} | 📞 {c_tel}")
                c_est = st.columns(3)
                if estado=='pagado': c_est[0].success("PAGADO")
                elif estado=='apartado': c_est[0].warning("APARTADO")
                else: c_est[0].info("ABONADO")
                c_est[1].metric("Precio", f"${b_precio}")
                c_est[2].metric("Deuda", f"${b_precio-b_abonado}")
                
                with st.expander("🛠️ Opciones de Gestión", expanded=True):
                    # ABONOS
                    if (b_precio - b_abonado) > 0.01:
                        ma = st.number_input("Monto Abono ($)", min_value=0.0, max_value=(b_precio-b_abonado))
                        if st.button("💸 REGISTRAR ABONO", use_container_width=True):
                            nt = b_abonado + ma
                            ne = 'pagado' if (b_precio - nt) <= 0.01 else 'abonado'
                            run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE id=%s", (nt, ne, b_id), fetch=False)
                            run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) VALUES (%s, 'MOVIL', 'ABONO', %s, %s)", (id_sorteo, f"Abono {numero}", ma), fetch=False)
                            st.success("Abonado"); time.sleep(1); st.rerun()
                    
                    st.divider()
                    # ACCIONES
                    c_btn1, c_btn2, c_btn3 = st.columns(3)
                    if estado != 'apartado': 
                        if c_btn1.button("🟡 APARTAR", use_container_width=True):
                            run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE id=%s", (b_id,), fetch=False)
                            run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'REVERTIR_APARTADO', %s)", (id_sorteo, f"Marcado como apartado {numero}"), fetch=False)
                            st.rerun()
                    if estado != 'pagado':
                        if c_btn2.button("✅ PAGADO", use_container_width=True):
                            run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE id=%s", (b_precio, b_id), fetch=False)
                            run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'PAGO_COMPLETO', %s)", (id_sorteo, f"Pago total boleto {numero}"), fetch=False)
                            st.rerun()
                    if c_btn3.button("🗑️ LIBERAR", use_container_width=True):
                        run_query("DELETE FROM boletos WHERE id=%s", (b_id,), fetch=False)
                        run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'LIBERAR', %s)", (id_sorteo, f"Liberado boleto {numero}"), fetch=False)
                        st.warning("Boleto liberado."); time.sleep(1); st.rerun()

                st.divider()
                
                # --- PREPARACIÓN DEL PDF ---
                datos_pdf = {'cliente': c_nom, 'cedula': c_ced, 'telefono': c_tel, 'direccion': c_dir, 'codigo_cli': c_cod, 'estado': estado, 'precio': b_precio, 'abonado': b_abonado, 'fecha_asignacion': b_fecha}
                pdf_bytes = generar_pdf_memoria(numero, datos_pdf, config_full, cantidad_boletos)
                
                # --- NUEVA LÓGICA DE NOMBRE DE ARCHIVO ---
                fmt_file = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
                num_file = fmt_file.format(numero)
                
                partes = c_nom.strip().upper().split()
                nom_archivo = "CLIENTE"
                
                # Regla: Si tiene 2 palabras -> Las 2. Si tiene 3 o más -> 1ra y 3ra.
                if len(partes) == 2:
                    nom_archivo = f"{partes[0]} {partes[1]}"
                elif len(partes) >= 3:
                    nom_archivo = f"{partes[0]} {partes[2]}"
                elif len(partes) == 1:
                    nom_archivo = partes[0]
                
                nombre_final_pdf = f"{num_file} {nom_archivo} ({estado.upper()}).pdf"

                # --- INTERFAZ PDF Y WHATSAPP ---
                c_share1, c_share2 = st.columns(2)
                c_share1.download_button("📄 PDF", pdf_bytes, nombre_final_pdf, "application/pdf", use_container_width=True)
                
                link = get_whatsapp_link_exacto(c_tel, numero, estado, c_nom, nombre_s, str(fecha_s), cantidad_boletos)
                c_share2.link_button("📲 WhatsApp", link, use_container_width=True)

            else:
                # --- DISPONIBLE (Venta) ---
                fmt_num_show = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
                st.success(f"🟢 El boleto {fmt_num_show.format(numero)} está DISPONIBLE")
                with st.form("venta"):
                    st.write("### 📝 Asignar Boleto")
                    clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                    opc_cli = {}
                    if clientes:
                        for c in clientes:
                            codigo_display = c[2] if c[2] else "S/C"
                            etiqueta = f"{c[1]} | {codigo_display}"
                            opc_cli[etiqueta] = c[0]
                    nom_sel = st.selectbox("👤 Buscar Cliente:", options=list(opc_cli.keys()), index=None, placeholder="Escribe para buscar...")
                    c_abono, c_precio = st.columns(2)
                    abono = c_abono.number_input("Abono Inicial ($)", value=precio_s, min_value=0.0)
                    c_precio.metric("Precio Boleto", f"${precio_s}")
                    if st.form_submit_button("💾 REGISTRAR VENTA", use_container_width=True):
                        if nom_sel:
                            cid = opc_cli[nom_sel]
                            est = 'pagado' if abono >= precio_s else 'abonado'
                            if abono == 0: est = 'apartado'
                            run_query("INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion) VALUES (%s, %s, %s, %s, %s, %s, NOW())", (id_sorteo, numero, est, precio_s, cid, abono), fetch=False)
                            run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) VALUES (%s, 'MOVIL', 'VENTA', %s, %s)", (id_sorteo, f"Venta boleto {numero}", abono), fetch=False)
                            st.balloons(); st.success("✅ Venta Exitosa"); time.sleep(1); st.rerun()
                        else: st.error("⚠️ Selecciona un cliente.")

        # ============================================================
        #  MODO B: POR CLIENTE (Gestión Masiva - PDFs Sueltos)
        # ============================================================
        else:
            # 1. Buscador de Clientes
            clientes_con_boletos = run_query("""
                SELECT DISTINCT c.id, c.nombre_completo, c.telefono, c.cedula, c.direccion, c.codigo
                FROM clientes c
                JOIN boletos b ON c.id = b.cliente_id
                WHERE b.sorteo_id = %s
                ORDER BY c.nombre_completo
            """, (id_sorteo,))
            
            opciones_cliente = {}
            datos_cliente_map = {}
            if clientes_con_boletos:
                for c in clientes_con_boletos:
                    etiqueta = f"{c[1]} | {c[2]}"
                    opciones_cliente[etiqueta] = c[0]
                    datos_cliente_map[c[0]] = {'nombre': c[1], 'telefono': c[2], 'cedula': c[3], 'direccion': c[4], 'codigo': c[5]}
            
            cliente_sel = st.selectbox("👤 Buscar Cliente:", options=list(opciones_cliente.keys()), index=None, placeholder="Escribe el nombre...")
            
            if cliente_sel:
                cid = opciones_cliente[cliente_sel]
                datos_c = datos_cliente_map[cid]
                
                # 2. Cargar Boletos
                boletos_cli = run_query("""
                    SELECT numero, estado, precio, total_abonado, fecha_asignacion
                    FROM boletos 
                    WHERE sorteo_id = %s AND cliente_id = %s
                    ORDER BY numero ASC
                """, (id_sorteo, cid))
                
                if boletos_cli:
                    st.info(f"📋 Gestionando boletos de: **{datos_c['nombre']}**")
                    
                    # Preparar opciones para Multiselect
                    opc_boletos = {}
                    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
                    
                    for b in boletos_cli:
                        num, est, pre, abo, f_asig = b
                        pre = float(pre or 0); abo = float(abo or 0)
                        lbl = f"{fmt_num.format(num)} ({est.upper()})"
                        opc_boletos[lbl] = {'numero': num, 'estado': est, 'precio': pre, 'abonado': abo, 'fecha': f_asig}
                    
                    seleccion = st.multiselect(
                        "✅ Selecciona los boletos a procesar:",
                        options=list(opc_boletos.keys()),
                        default=list(opc_boletos.keys()) 
                    )
                    
                    if seleccion:
                        datos_sel = [opc_boletos[k] for k in seleccion]
                        numeros_sel = [d['numero'] for d in datos_sel]
                        
                        # --- BOTONES ACCIÓN ---
                        c_acc1, c_acc2, c_acc3 = st.columns(3)
                        if c_acc1.button("✅ PAGAR", use_container_width=True):
                            for d in datos_sel:
                                if d['estado'] != 'pagado':
                                    run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE sorteo_id=%s AND numero=%s", (d['precio'], id_sorteo, d['numero']), fetch=False)
                                    run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'PAGO_MASIVO', %s)", (id_sorteo, f"Pago boleto {d['numero']}"), fetch=False)
                            st.success("Pagados"); time.sleep(1); st.rerun()
                            
                        if c_acc2.button("🟡 APARTAR", use_container_width=True):
                            for d in datos_sel:
                                run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE sorteo_id=%s AND numero=%s", (id_sorteo, d['numero']), fetch=False)
                            st.success("Apartados"); time.sleep(1); st.rerun()

                        if c_acc3.button("🗑️ LIBERAR", type="primary", use_container_width=True):
                            for d in datos_sel:
                                run_query("DELETE FROM boletos WHERE sorteo_id=%s AND numero=%s", (id_sorteo, d['numero']), fetch=False)
                                run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'LIBERAR_MASIVO', %s)", (id_sorteo, f"Liberado boleto {d['numero']}"), fetch=False)
                            st.warning("Liberados"); time.sleep(1); st.rerun()

                        st.divider()
                        
                        # --- WHATSAPP (CON TRÉBOL ARREGLADO) ---
                        partes_msg = []
                        for d in datos_sel:
                            n_s = fmt_num.format(d['numero'])
                            e_s = "PAGADO" if d['estado']=='pagado' else ("ABONADO" if d['estado']=='abonado' else "APARTADO")
                            partes_msg.append(f"N° {n_s} ({e_s})")
                        
                        txt_boletos = ", ".join(partes_msg)
                        
                        msg_wa = (
                            f"Hola. Saludos, somos Sorteos Milán!!, aquí te enviamos los comprobantes de tus "
                            f"BOLETOS: {txt_boletos}, a nombre de '{datos_c['nombre']}' para el sorteo "
                            f"'{nombre_s}' del día '{fecha_s}' . ¡Suerte!🍀"
                        )
                        
                        col_wa, col_pdf = st.columns([1, 1])
                        
                        tel_raw = datos_c['telefono']
                        if tel_raw:
                            tel_clean = "".join(filter(str.isdigit, str(tel_raw)))
                            if len(tel_clean) == 10: tel_clean = "58" + tel_clean
                            elif len(tel_clean) == 11 and tel_clean.startswith("0"): tel_clean = "58" + tel_clean[1:]
                            
                            # 🔥 CORRECCIÓN: Usamos api.whatsapp.com para que el móvil lea bien el emoji
                            link = f"https://api.whatsapp.com/send?phone={tel_clean}&text={urllib.parse.quote(msg_wa)}"
                            col_wa.link_button("📲 Enviar WhatsApp", link, use_container_width=True)
                        else:
                            col_wa.warning("Sin teléfono")

                        # --- PDFS SUELTOS (UNO POR BOTÓN) ---
                        with col_pdf:
                            st.write("**Descargar PDFs:**")
                            for d in datos_sel:
                                info_pdf = {
                                    'cliente': datos_c['nombre'], 'cedula': datos_c['cedula'], 'telefono': datos_c['telefono'],
                                    'direccion': datos_c['direccion'], 'codigo_cli': datos_c['codigo'],
                                    'estado': d['estado'], 'precio': d['precio'], 'abonado': d['abonado'], 'fecha_asignacion': d['fecha']
                                }
                                pdf_data = generar_pdf_memoria(d['numero'], info_pdf, config_full, cantidad_boletos)
                                
                                # --- NUEVA LÓGICA DE NOMBRE DE ARCHIVO (REPLICADA) ---
                                num_f = fmt_num.format(d['numero'])
                                
                                partes = datos_c['nombre'].strip().upper().split()
                                nom_archivo = "CLIENTE"
                                
                                # Regla: 2 palabras -> 2. 3 o más -> 1ra y 3ra.
                                if len(partes) == 2:
                                    nom_archivo = f"{partes[0]} {partes[1]}"
                                elif len(partes) >= 3:
                                    nom_archivo = f"{partes[0]} {partes[2]}"
                                elif len(partes) == 1:
                                    nom_archivo = partes[0]
                                
                                n_file = f"{num_f} {nom_archivo} ({d['estado'].upper()}).pdf"
                                
                                st.download_button(
                                    f"📄 PDF {num_f}", 
                                    pdf_data, n_file, "application/pdf", 
                                    key=f"btn_down_{d['numero']}", 
                                    use_container_width=True
                                )

                    else:
                        st.info("👆 Selecciona boletos de la lista para ver acciones.")
                        
    # ---------------- PESTAÑA CLIENTES ----------------
    with tab_clientes: # <--- ¡ESTO TAMBIÉN FALTABA!
        st.header("Gestión Clientes")
        with st.expander("Nuevo Cliente"):
            with st.form("new_cli"):
                nn = st.text_input("Nombre").upper()
                nc = st.text_input("Cédula")
                nt = st.text_input("Teléfono")
                nd = st.text_input("Dirección")
                if st.form_submit_button("Guardar"):
                    if nn and nt:
                        cod = datetime.now().strftime("%H%M%S")
                        run_query("INSERT INTO clientes (codigo, nombre_completo, cedula, telefono, direccion, fecha_registro) VALUES (%s, %s, %s, %s, %s, NOW())", (cod, nn, nc, nt, nd), fetch=False)
                        st.success("Guardado"); st.rerun()
                    else: st.error("Faltan datos")
        
        # Lista y Edición
        q = st.text_input("Buscar cliente...")
        sql = "SELECT id, nombre_completo, cedula, telefono, direccion FROM clientes"
        if q: sql += f" WHERE nombre_completo ILIKE '%{q}%' OR cedula ILIKE '%{q}%'"
        sql += " ORDER BY id DESC LIMIT 15"
        res = run_query(sql)
        
        if res:
            for c in res:
                with st.container(border=True):
                    c1, c2 = st.columns([3,1])
                    c1.write(f"**{c[1]}**\n🆔 {c[2]} | 📞 {c[3]} | 📍 {c[4]}")
                    if c2.button("Editar", key=c[0]):
                        st.session_state.edit_id = c[0]
                        st.session_state.edit_vals = c
            
            if 'edit_id' in st.session_state:
                id_e = st.session_state.edit_id
                vals = st.session_state.edit_vals
                st.markdown("---")
                st.write(f"Editando: {vals[1]}")
                with st.form("edit_cli"):
                    en = st.text_input("Nombre", value=vals[1])
                    ec = st.text_input("Cédula", value=vals[2])
                    et = st.text_input("Teléfono", value=vals[3])
                    ed = st.text_input("Dirección", value=vals[4])
                    if st.form_submit_button("Guardar Cambios"):
                        run_query("UPDATE clientes SET nombre_completo=%s, cedula=%s, telefono=%s, direccion=%s WHERE id=%s", (en, ec, et, ed, id_e), fetch=False)
                        del st.session_state.edit_id
                        st.success("Actualizado"); st.rerun()

    # ---------------- PESTAÑA COBRANZA (AGRUPADA POR CLIENTE) ----------------
    with tab_cobranza:
        st.header("💸 Gestión de Cobranza")
        
        if st.button("🔄 Actualizar Lista", use_container_width=True):
            st.rerun()
            
        # 1. CONSULTA DE DEUDORES (Buscamos boletos con deuda > 0.01)
        raw_deudores = run_query("""
            SELECT c.nombre_completo, c.telefono, b.numero, b.precio, b.total_abonado
            FROM boletos b
            JOIN clientes c ON b.cliente_id = c.id
            WHERE b.sorteo_id = %s
              AND (b.precio - b.total_abonado) > 0.01 
              AND b.estado != 'disponible'
            ORDER BY c.nombre_completo
        """, (id_sorteo,))
        
        if not raw_deudores:
            st.balloons()
            st.success("✅ ¡Excelente! No hay deudas pendientes en este sorteo.")
        else:
            # 2. PROCESAMIENTO: AGRUPAR POR CLIENTE
            # Estructura: { "Nombre|Tel": { datos... } }
            grupos = {}
            
            for row in raw_deudores:
                nom, tel, num, prec, abon = row
                prec = float(prec or 0); abon = float(abon or 0)
                deuda = prec - abon
                
                # Usamos Nombre+Tel como clave única
                clave = f"{nom}|{tel}"
                
                if clave not in grupos:
                    grupos[clave] = {
                        'nombre': nom, 'tel': tel, 'numeros': [],
                        't_deuda': 0.0, 't_abono': 0.0, 't_precio': 0.0
                    }
                
                grupos[clave]['numeros'].append(num)
                grupos[clave]['t_deuda'] += deuda
                grupos[clave]['t_abono'] += abon
                grupos[clave]['t_precio'] += prec

            # 3. MOSTRAR TOTALES GLOBALES
            gran_total = sum(g['t_deuda'] for g in grupos.values())
            st.metric("Total por Cobrar (Global)", f"${gran_total:,.2f}", f"{len(grupos)} Clientes Deudores")
            st.divider()

            # 4. RENDERIZAR TARJETAS POR CLIENTE
            fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
            
            for clave, d in grupos.items():
                nom = d['nombre']
                tel = d['tel']
                lista_nums = sorted(d['numeros'])
                
                # Formatear lista de números (Ej: "05, 12, 20")
                str_numeros = ", ".join([fmt_num.format(n) for n in lista_nums])
                
                with st.container(border=True):
                    c_info, c_btn = st.columns([2, 1])
                    
                    with c_info:
                        st.markdown(f"👤 **{nom}**")
                        # Muestra qué números tiene
                        st.caption(f"🎟️ Boletos ({len(lista_nums)}): **{str_numeros}**")
                        
                        # Muestra Totales
                        st.write(f"🔴 Deuda Total: :red[**${d['t_deuda']:,.2f}**]")
                        
                        # Si tiene abonos, los mostramos
                        if d['t_abono'] > 0:
                            st.caption(f"💰 (Abonó: ${d['t_abono']:,.2f} | Total: ${d['t_precio']:,.2f})")
                        else:
                            st.caption(f"💵 Total a pagar: ${d['t_precio']:,.2f}")

                    with c_btn:
                        if tel and len(str(tel)) > 5:
                            # Preparar Link WhatsApp
                            tel_clean = "".join(filter(str.isdigit, str(tel)))
                            if len(tel_clean) == 10: tel_clean = "58" + tel_clean
                            elif len(tel_clean) == 11 and tel_clean.startswith("0"): tel_clean = "58" + tel_clean[1:]
                            
                            # Mensaje Plural o Singular
                            txt_concepto = "del boleto" if len(lista_nums) == 1 else "de los boletos"
                            
                            msg = (f"Hola {nom}, saludos de Sorteos Milán. "
                                   f"Te recordamos amablemente que tienes un saldo pendiente de ${d['t_deuda']:.2f} "
                                   f"por concepto {txt_concepto}: {str_numeros}. Agradecemos tu pago. ¡Gracias!")
                            
                            link = f"https://wa.me/{tel_clean}?text={urllib.parse.quote(msg)}"
                            st.link_button("📲 Cobrar", link, use_container_width=True)
                        else:
                            st.warning("Sin Tel")

# ============================================================================
#  PUNTO DE ENTRADA (CON LOGIN)
# ============================================================================
if __name__ == "__main__":
    if check_password():
        main()

