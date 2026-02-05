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
    y -= 18; c.setFont("Helvetica-Bold", 15); c.drawCentredString(centro, y, "COMPROBANTE DE SORTEO")
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
#  MOTOR GRÁFICO: COPIA EXACTA DE BOLETOS.PY (PC)
# ============================================================================
def generar_imagen_reporte(id_sorteo, config_completa, cantidad_boletos, mostrar_ocupados=True):
    """
    Genera una imagen de 4000x3000 píxeles IDÉNTICA al software de PC.
    Usa la lógica de boletos.py línea por línea.
    """
    
    # 1. Configuración Geométrica (Exacta de PC)
    # ---------------------------------------------------------
    base_w = 4000
    base_h = 3000
    margin_px = 80
    header_h = 450
    
    # Lógica de columnas/filas según cantidad (Igual que boletos.py)
    if cantidad_boletos <= 100:
        cols_img = 10
        rows_img = 10
        font_s_title = 80
        font_s_info = 40
        font_s_num = 60
    else:
        cols_img = 25
        rows_img = 40
        font_s_title = 90
        font_s_info = 42
        font_s_num = 35
    
    # Cálculos de grilla
    grid_pw = base_w - (2 * margin_px)
    grid_ph = base_h - (2 * margin_px) - header_h
    cell_pw = (grid_pw / cols_img) - 4  # Padding de 4px entre celdas
    cell_ph = (grid_ph / rows_img) - 4

    # 2. Lienzo y Fuentes
    # ---------------------------------------------------------
    img = Image.new('RGB', (base_w, base_h), 'white')
    draw = ImageDraw.Draw(img)
    
    # Intentamos cargar fuentes parecidas a Arial (PC)
    # En servidores Linux (Streamlit) usamos DejaVuSans como equivalente
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", font_s_title)
        font_info = ImageFont.truetype("DejaVuSans.ttf", font_s_info)
        font_num = ImageFont.truetype("DejaVuSans-Bold.ttf", font_s_num)
    except:
        # Fallback si no hay fuentes (no debería pasar en Streamlit Cloud)
        font_title = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_num = ImageFont.load_default()

    rifa = config_completa['rifa']
    empresa = config_completa['empresa']

    # 3. Dibujar Encabezado (Coordenadas de PC)
    # ---------------------------------------------------------
    
    # Título Centrado
    titulo = rifa['nombre'].upper()
    # Truco para centrar texto
    bbox = draw.textbbox((0, 0), titulo, font=font_title)
    text_w = bbox[2] - bbox[0]
    draw.text(((base_w - text_w)/2, 60), titulo, fill='#1a73e8', font=font_title)
    
    # Columna Izquierda (Info)
    iy = 180
    # Fecha Actual
    draw.text((margin_px, iy), f"📅 Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}", fill='#555', font=font_info)
    iy += 60
    # Fecha Sorteo
    texto_sorteo = f"🎲 Sorteo: {rifa.get('fecha_sorteo','')} {rifa.get('hora_sorteo','')}"
    draw.text((margin_px, iy), texto_sorteo, fill='#388E3C', font=font_info)
    iy += 60
    # Precio
    draw.text((margin_px, iy), f"💵 Costo del boleto: {rifa.get('precio_boleto',0)} $", fill='#D32F2F', font=font_info)
    
    # Columna Derecha (Premios)
    # En PC: px = base_w - margin_px - 900
    px = base_w - margin_px - 900 
    py = 180
    draw.text((px, py), "🏆 PREMIOS", fill='#D32F2F', font=font_info)
    py += 60
    
    premios = []
    keys = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    lbls = ["1er:", "2do:", "3er:", "Ext:", "Ext:"]
    for k, l in zip(keys, lbls):
        val = rifa.get(k)
        if val: premios.append(f"{l} {val}")
        
    for p in premios:
        draw.text((px, py), p, fill='black', font=font_info)
        py += 50

    # 4. Dibujar Grilla (Lógica de PC)
    # ---------------------------------------------------------
    
    # Obtener estados de la BD
    boletos_ocupados = {}
    ocupados_raw = run_query("SELECT numero, estado FROM boletos WHERE sorteo_id = %s", (id_sorteo,))
    if ocupados_raw:
        boletos_ocupados = {row[0]: row[1] for row in ocupados_raw}
        
    y_start = margin_px + header_h
    
    # Formato de números (00-99 o 000-999)
    fmt = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"

    for i in range(cantidad_boletos):
        r = i // cols_img
        c = i % cols_img
        
        # Coordenadas exactas
        x = margin_px + (c * (cell_pw + 4))
        y = y_start + (r * (cell_ph + 4))
        
        estado = boletos_ocupados.get(i, 'disponible')
        ocupado = estado != 'disponible'
        
        # --- LÓGICA DE COLORES DE REPORTES.PY ---
        bg_color = 'white'
        texto_visible = True
        
        if mostrar_ocupados:
            # IMAGEN 1: Con Ocupados (Amarillo y Texto)
            if ocupado: bg_color = '#FFFF00' # Amarillo
        else:
            # IMAGEN 2: Solo Disponibles (Ocupados en Blanco SIN texto)
            if ocupado: texto_visible = False
        
        # Dibujar Rectángulo (Borde negro ancho 3)
        draw.rectangle([x, y, x + cell_pw, y + cell_ph], fill=bg_color, outline='black', width=3)
        
        # Dibujar Número Centrado
        if texto_visible:
            txt = fmt.format(i)
            
            # Centrado matemático del texto
            bbox = draw.textbbox((0, 0), txt, font=font_num)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = x + (cell_pw - tw) / 2
            ty = y + (cell_ph - th) / 2
            
            draw.text((tx, ty), txt, fill='black', font=font_num)
            
    # 5. Guardar en Memoria
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95) # Calidad alta
    buf.seek(0)
    return buf

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
    
    # 🔥 DETECCIÓN AUTOMÁTICA DE CANTIDAD (Para saber si usar 2 o 3 dígitos)
    cantidad_boletos = 1000
    if config_rows:
        cfg_dict = {r[0]: r[1] for r in config_rows}
        clave_cap = f"capacidad_sorteo_{id_sorteo}"
        if clave_cap in cfg_dict:
            cantidad_boletos = int(cfg_dict[clave_cap])
        else:
            # Si no hay config, deducir por el boleto más alto
            max_bol = run_query("SELECT MAX(numero) FROM boletos WHERE sorteo_id=%s", (id_sorteo,))
            if max_bol and max_bol[0][0] is not None and max_bol[0][0] <= 99:
                cantidad_boletos = 100
    
    st.caption(f"⚙️ Modo: {cantidad_boletos} boletos (Formato: {'00' if cantidad_boletos<=100 else '000'})")

    # Objeto Rifa Global
    rifa_config = {
        "nombre": nombre_s, "precio_boleto": precio_s, "fecha_sorteo": str(fecha_s), "hora_sorteo": str(s_data[4]),
        "premio1": s_data[5], "premio2": s_data[6], "premio3": s_data[7], "premio_extra1": s_data[8], "premio_extra2": s_data[9]
    }
    config_full = {'rifa': rifa_config, 'empresa': empresa_config}
    
    tab_venta, tab_clientes = st.tabs(["🎫 VENTA", "👥 CLIENTES"])

    # ---------------- PESTAÑA VENTA ----------------
        # --- SECCIÓN: REPORTE VISUAL ---
        with st.expander("📷 GENERAR REPORTE VISUAL (IMAGEN)", expanded=False):
            st.info(f"Generando imagen de Alta Resolución (4000x3000px) para {cantidad_boletos} números.")
            col_rep1, col_rep2 = st.columns(2)
            
            if col_rep1.button("1. Tabla Con Ocupados (Amarillo)"):
                # True = Muestra los amarillos
                img_bytes = generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, mostrar_ocupados=True)
                st.image(img_bytes, caption="Vista Previa", use_container_width=True)
                st.download_button("⬇️ Descargar JPG", img_bytes, "01_Tabla_ConOcupados.jpg", "image/jpeg")
                
            if col_rep2.button("2. Tabla Solo Disponibles (Blanca)"):
                # False = Oculta los ocupados (deja huecos blancos)
                img_bytes = generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, mostrar_ocupados=False)
                st.image(img_bytes, caption="Vista Previa", use_container_width=True)
                st.download_button("⬇️ Descargar JPG", img_bytes, "02_Tabla_SoloDisponibles.jpg", "image/jpeg")
            
        # --- CORRECCIÓN DE FORMATO (00 o 000) ---
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
            # OCUPADO
            b_id, estado, b_precio, b_abonado, b_fecha, c_nom, c_tel, c_ced, c_dir, c_cod = boleto_info[0]
            b_precio = float(b_precio); b_abonado = float(b_abonado)
            
            st.info(f"👤 {c_nom} | 📞 {c_tel}")
            c_est = st.columns(3)
            if estado=='pagado': c_est[0].success("PAGADO")
            elif estado=='apartado': c_est[0].warning("APARTADO")
            else: c_est[0].info("ABONADO")
            c_est[1].metric("Precio", f"${b_precio}")
            c_est[2].metric("Deuda", f"${b_precio-b_abonado}")
            
            # Botones gestión
            with st.expander("🛠️ Opciones de Gestión", expanded=True):

                # --- SECCIÓN 1: ABONOS (Solo si hay deuda) ---
                if (b_precio - b_abonado) > 0.01: # Usamos 0.01 para evitar problemas de decimales
                    ma = st.number_input("Monto Abono ($)", min_value=0.0, max_value=(b_precio-b_abonado))
                    if st.button("💸 REGISTRAR ABONO", use_container_width=True):
                        nt = b_abonado + ma
                        ne = 'pagado' if (b_precio - nt) <= 0.01 else 'abonado'
                        run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE id=%s", (nt, ne, b_id), fetch=False)
                        run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) VALUES (%s, 'MOVIL', 'ABONO', %s, %s)", (id_sorteo, f"Abono {numero}", ma), fetch=False)
                        st.success("Abonado"); time.sleep(1); st.rerun()
                
                st.divider() # Línea separadora visual
                
                # --- SECCIÓN 2: CAMBIO DE ESTADO (Siempre visible) ---
                st.caption("Cambiar Estado del Boleto:")
                c_btn1, c_btn2, c_btn3 = st.columns(3)
                
                # 1. Botón APARTADO (Visible si NO es apartado, o sea en Pagado/Abonado)
                if estado != 'apartado': 
                    if c_btn1.button("🟡 APARTADO", use_container_width=True):
                        # Al apartar, reiniciamos el abono a 0
                        run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE id=%s", (b_id,), fetch=False)
                        run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'REVERTIR_APARTADO', %s)", (id_sorteo, f"Marcado como apartado {numero}"), fetch=False)
                        st.rerun()

                # 2. Botón PAGADO (Visible si NO es pagado)
                if estado != 'pagado':
                    if c_btn2.button("✅ PAGADO", use_container_width=True):
                        run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE id=%s", (b_precio, b_id), fetch=False)
                        run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'PAGO_COMPLETO', %s)", (id_sorteo, f"Pago total boleto {numero}"), fetch=False)
                        st.rerun()
                
                # 3. Botón LIBERAR (Siempre visible)
                if c_btn3.button("🗑️ LIBERAR", use_container_width=True):
                    run_query("DELETE FROM boletos WHERE id=%s", (b_id,), fetch=False)
                    run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'LIBERAR', %s)", (id_sorteo, f"Liberado boleto {numero}"), fetch=False)
                    st.warning("Boleto liberado."); time.sleep(1); st.rerun()
            
            # PDF y WhatsApp
            st.divider()
            datos_pdf = {'cliente': c_nom, 'cedula': c_ced, 'telefono': c_tel, 'direccion': c_dir, 'codigo_cli': c_cod, 'estado': estado, 'precio': b_precio, 'abonado': b_abonado, 'fecha_asignacion': b_fecha}
            
            pdf_bytes = generar_pdf_memoria(numero, datos_pdf, config_full, cantidad_boletos)
            
            # --- CONSTRUCCIÓN DEL NOMBRE DEL ARCHIVO ---
            # 1. Formato de número (01 o 001)
            fmt_file = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
            num_file = fmt_file.format(numero)
            
            # 2. Obtener Primer Nombre y Primer Apellido
            partes_nom = c_nom.strip().split()
            if len(partes_nom) >= 2:
                nom_archivo = f"{partes_nom[0]} {partes_nom[1]}"
            elif len(partes_nom) == 1:
                nom_archivo = partes_nom[0]
            else:
                nom_archivo = "Cliente"
            
            # 3. Nombre Final: XX_Juan Perez_(pagado).pdf
            nombre_final_pdf = f"{num_file}_{nom_archivo}_({estado.upper()}).pdf"

            c_share1, c_share2 = st.columns(2)
            c_share1.download_button("📄 PDF", pdf_bytes, nombre_final_pdf, "application/pdf", use_container_width=True)

            link = get_whatsapp_link_exacto(c_tel, numero, estado, c_nom, nombre_s, str(fecha_s), cantidad_boletos)
            c_share2.link_button("📲 WhatsApp", link, use_container_width=True)
            
        else:
            # --- BOLETO DISPONIBLE (ZONA DE VENTA) ---
            st.success(f"🟢 El boleto {numero} está DISPONIBLE")
            
            with st.form("venta"):
                st.write("### 📝 Asignar Boleto")
                
                # 1. Cargar Clientes CON CÓDIGO para poder buscar
                clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                
                opc_cli = {}
                if clientes:
                    for c in clientes:
                        # Formato: "JUAN PEREZ | 095123"
                        # Esto permite que si escribes el código, aparezca el cliente
                        codigo_display = c[2] if c[2] else "S/C"
                        etiqueta = f"{c[1]} | {codigo_display}"
                        opc_cli[etiqueta] = c[0]
                
                # 2. Selector Inteligente (Busca por lo que escribas)
                nom_sel = st.selectbox(
                    "👤 Buscar Cliente (Escribe Nombre o Código):", 
                    options=list(opc_cli.keys()),
                    index=None,
                    placeholder="Escribe aquí para filtrar..."
                )
                
                c_abono, c_precio = st.columns(2)
                abono = c_abono.number_input("Abono Inicial ($)", value=precio_s, min_value=0.0)
                c_precio.metric("Precio Boleto", f"${precio_s}")
                
                if st.form_submit_button("💾 Asignar boleto", use_container_width=True):
                    if nom_sel:
                        cid = opc_cli[nom_sel]
                        # Lógica de Estado
                        est = 'pagado' if abono >= precio_s else 'abonado'
                        if abono == 0: est = 'apartado'
                        
                        # Guardar
                        run_query("""
                            INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion) 
                            VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        """, (id_sorteo, numero, est, precio_s, cid, abono), fetch=False)
                        
                        # Historial
                        run_query("""
                            INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) 
                            VALUES (%s, 'MOVIL', 'VENTA', %s, %s)
                        """, (id_sorteo, f"Venta boleto {numero}", abono), fetch=False)
                        
                        st.balloons()
                        st.success("✅ ¡Boleto asignado!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("⚠️ Por favor selecciona un cliente de la lista.")

# ============================================================================
#  PUNTO DE ENTRADA (CON LOGIN)
# ============================================================================
if __name__ == "__main__":
    if check_password():
        main()
