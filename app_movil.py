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
        f"BOLETO: {texto_boleto}, a nombre de {cliente_nom} para el sorteo "
        f"'{sorteo_nom}' del día {fecha_sorteo} . ¡Suerte!🍀"
    )
    
    return f"https://wa.me/{tel_clean}?text={urllib.parse.quote(mensaje)}"

# ============================================================================
#  2. PDF DIGITAL (APP MÓVIL - MINÚSCULAS am/pm)
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

    # Encabezado Texto
    c.setFont("Helvetica-Bold", 12)
    c.drawString(m_izq + 50, y, empresa.get('nombre', 'SORTEOS MILÁN'))
    c.setFont("Helvetica", 8)
    c.drawString(m_izq + 50, y-12, f"RIF: {empresa.get('rif', '')}")
    c.drawString(m_izq + 50, y-25, f"Tel: {empresa.get('telefono', '')}")
    
    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.70, 0.55, 0.35) 
    c.drawRightString(m_der, y-5, f"BOLETO N° {num_str}")
    c.setFillColorRGB(0,0,0)
    
    # 🔥 CAMBIO 1: Fecha de emisión en minúsculas
    fecha_emision = datetime.now().strftime('%d/%m/%Y %I:%M %p').lower()
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(m_der, y-25, f"Emitido: {fecha_emision}")
    
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
    col_der_x = centro - 5 
    
    y = y_start
    c.setFont("Helvetica-Bold", 10); c.drawString(col_izq_x, y, "SORTEO:")
    c.drawString(col_izq_x + 50, y, rifa['nombre'][:35])
    y -= 15
    c.drawString(col_izq_x, y, "FECHA:")
    
    # 🔥 CAMBIO 2: Hora del sorteo en minúsculas
    hora_sorteo = str(rifa.get('hora_sorteo','')).lower()
    c.drawString(col_izq_x + 50, y, f"{rifa.get('fecha_sorteo','')} {hora_sorteo}")
    
    # Premios
    y_prem = y_start
    c.drawString(col_der_x, y_prem, "PREMIOS:")
    y_prem -= 12; c.setFont("Helvetica", 9)
    etiquetas = ["Triple A:", "Triple B:", "Triple Z:", "Especial 1:", "Especial 2:"]
    for i, k in enumerate(lista_claves):
        val = rifa.get(k, "")
        if val:
            lbl = etiquetas[i] if i < len(etiquetas) else f"{i+1}º:"
            c.drawString(col_der_x, y_prem, f"{lbl} {val[:30]}")
            y_prem -= 12
    
    # --- SECCIÓN CLIENTE ---
    y_fin_arriba = min(y, y_prem)
    y_linea = y_fin_arriba - 3
    
    c.setLineWidth(1)
    c.setStrokeColorRGB(0.70, 0.55, 0.35) 
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
    
    # --- SECCIÓN PAGOS ---
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
    
    # --- CAMBIO: FECHA NORMAL (12H) Y MINÚSCULAS ---
    f_reg_str = ""
    try:
        if fecha_asig:
            # Opción A: Si ya es un objeto de fecha (datetime)
            if hasattr(fecha_asig, 'strftime'):
                f_reg_str = fecha_asig.strftime('%d/%m/%Y %I:%M:%S %p').lower()
            # Opción B: Si es texto (string), intentamos convertirlo
            else:
                try:
                    # Limpiamos decimales si los tiene y convertimos
                    fecha_limpia = str(fecha_asig).split('.')[0] 
                    dt_obj = datetime.strptime(fecha_limpia, '%Y-%m-%d %H:%M:%S')
                    f_reg_str = dt_obj.strftime('%d/%m/%Y %I:%M:%S %p').lower()
                except:
                    # Si falla la conversión, mostramos lo que haya en minúsculas
                    f_reg_str = str(fecha_asig).lower()
        else:
            # Si no hay fecha, usamos la actual
            f_reg_str = datetime.now().strftime('%d/%m/%Y %I:%M:%S %p').lower()
    except Exception:
        f_reg_str = str(fecha_asig).lower()

    c.drawString(m_izq, y, f"Fecha de registro: {f_reg_str}")
    
    # Estado
    y_est = y_final
    centro_der = x_div + ((m_der - x_div) / 2)
    c.setFont("Helvetica-Bold", 10); c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(centro_der, y_est, "ESTADO:")
    c.setFont("Helvetica-Bold", 18); c.setFillColorRGB(0, 0, 0.4) 
    c.drawCentredString(centro_der, y_est - 30, estado_fmt)
    c.setFillColorRGB(0, 0, 0)
    
    # --- FOOTER ---
    y -= 25
    c.setStrokeColorRGB(0.7, 0.7, 0.7) 
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
#  MOTOR DE REPORTES VISUALES (COPIA EXACTA DE BOLETOS.PY)
# ============================================================================
def generar_imagen_reporte(id_sorteo, config_completa, cantidad_boletos, mostrar_ocupados=True):
    """
    Genera la imagen JPG replicando EXACTAMENTE la lógica de boletos.py.
    Cambia la resolución y tamaño de fuente según si son 100 o 1000 boletos.
    """
    
    # 1. CONFIGURACIÓN GEOMÉTRICA (Lógica idéntica a PC)
    # ---------------------------------------------------------
    if cantidad_boletos <= 100:
        # Modo 100: Lienzo más angosto y alto (2000x2500)
        cols_img = 10
        rows_img = 10
        base_w = 2000
        base_h = 2500
        font_s_title = 80
        font_s_info = 40
        font_s_num = 60
    else:
        # Modo 1000: Lienzo ancho estándar (4000x3000)
        cols_img = 25
        rows_img = 40
        base_w = 4000
        base_h = 3000
        font_s_title = 90
        font_s_info = 42
        font_s_num = 35
    
    margin_px = 80
    header_h = 450
    
    # Cálculo de celdas CON ESPACIO (Padding de 4px como en PC)
    grid_pw = base_w - (2 * margin_px)
    grid_ph = base_h - (2 * margin_px) - header_h
    cell_pw = (grid_pw / cols_img) - 4 
    cell_ph = (grid_ph / rows_img) - 4

    # 2. LIENZO Y FUENTES
    # ---------------------------------------------------------
    img = Image.new('RGB', (base_w, base_h), 'white')
    draw = ImageDraw.Draw(img)
    
    # Fuentes (DejaVu es el equivalente a Arial en Linux/Streamlit)
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", font_s_title)
        font_info = ImageFont.truetype("DejaVuSans.ttf", font_s_info)
        font_num = ImageFont.truetype("DejaVuSans-Bold.ttf", font_s_num)
    except:
        font_title = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_num = ImageFont.load_default()

    rifa = config_completa['rifa']
    
    # 3. DIBUJAR ENCABEZADO
    # ---------------------------------------------------------
    # Título Centrado
    titulo = rifa['nombre'].upper()
    bbox_t = draw.textbbox((0,0), titulo, font=font_title)
    tw_t = bbox_t[2] - bbox_t[0]
    draw.text(((base_w - tw_t)/2, 60), titulo, fill='#1a73e8', font=font_title)
    
    # Columna Izquierda (Info)
    iy = 180
    draw.text((margin_px, iy), f"📅 Fecha: {datetime.now().strftime('%d/%m/%Y')}", fill='#555', font=font_info)
    iy += 60
    # Fecha Sorteo
    txt_sorteo = f"🎲 Sorteo: {rifa.get('fecha_sorteo','')} {rifa.get('hora_sorteo','')}"
    draw.text((margin_px, iy), txt_sorteo, fill='#388E3C', font=font_info)
    iy += 60
    # Precio
    draw.text((margin_px, iy), f"💵 Precio: {rifa.get('precio_boleto',0)} $", fill='#D32F2F', font=font_info)
    
    # Columna Derecha (Premios)
    # Ubicación exacta de PC: Ancho total - margen - 900px
    px = base_w - margin_px - 900 
    py = 180
    draw.text((px, py), "🏆 PREMIOS:", fill='#D32F2F', font=font_info)
    py += 60
    
    keys = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    lbls = ["1er:", "2do:", "3er:", "Ext:", "Ext:"]
    for k, l in zip(keys, lbls):
        val = rifa.get(k)
        if val:
            draw.text((px, py), f"{l} {val}", fill='black', font=font_info)
            py += 50

    # 4. DIBUJAR GRILLA (Lógica Matemática de PC)
    # ---------------------------------------------------------
    # Obtener estados
    boletos_ocupados = {}
    ocupados_raw = run_query("SELECT numero, estado FROM boletos WHERE sorteo_id = %s", (id_sorteo,))
    if ocupados_raw: 
        boletos_ocupados = {row[0]: row[1] for row in ocupados_raw}
        
    y_start = margin_px + header_h
    fmt = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"

    for i in range(cantidad_boletos):
        r = i // cols_img
        c = i % cols_img
        
        # FÓRMULA EXACTA DE BOLETOS.PY PARA COORDENADAS
        # x = margen + (columna * (ancho_celda + espacio))
        x = margin_px + (c * (cell_pw + 4))
        y = y_start + (r * (cell_ph + 4))
        
        estado = boletos_ocupados.get(i, 'disponible')
        ocupado = estado != 'disponible'
        
        # Colores
        bg_color = 'white'
        texto_visible = True
        
        if mostrar_ocupados:
            if ocupado: bg_color = '#FFFF00' # Amarillo
        else:
            if ocupado: texto_visible = False # Borrar número (hueco blanco)
        
        # Dibujar Rectángulo
        draw.rectangle([x, y, x + cell_pw, y + cell_ph], fill=bg_color, outline='black', width=3)
        
        # Dibujar Número Centrado
        if texto_visible:
            txt = fmt.format(i)
            
            bbox_n = draw.textbbox((0,0), txt, font=font_num)
            tw_n = bbox_n[2] - bbox_n[0]
            th_n = bbox_n[3] - bbox_n[1]
            
            # Centro matemático exacto
            tx = x + (cell_pw - tw_n) / 2
            ty = y + (cell_ph - th_n) / 2
            
            draw.text((tx, ty), txt, fill='black', font=font_num)
            
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
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
    
    # --- CAMBIO: Usamos st.form para detectar la tecla ENTER ---
    with st.form("login_form"):
        pwd_input = st.text_input("Ingresa la contraseña:", type="password")
        # El botón de submit se activa con Clic o ENTER en el campo de texto
        submit_btn = st.form_submit_button("Entrar")
    
    if submit_btn:
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
        
        # 1. Generar Imagen
        img_bytes = generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, mostrar_ocupados=ver_ocupados)
        st.image(img_bytes, caption="Actualizado en tiempo real", use_container_width=True)
        
        # 2. Calcular Totales (Asignados y Dinero)
        try:
            # Hacemos la consulta
            datos_resumen = run_query("SELECT COUNT(*), SUM(precio) FROM boletos WHERE sorteo_id = %s", (id_sorteo,))
            
            # Valores por defecto
            t_asignados = 0
            t_monto = 0.0
            
            # Si hay datos, los procesamos
            if datos_resumen and datos_resumen[0]:
                fila = datos_resumen[0]
                t_asignados = fila[0] or 0          # Cantidad (Count)
                t_monto = float(fila[1] or 0.0)     # Suma Precio
            
            # 3. Mostrar Resumen (Centrado y legible)
            st.markdown(
                f"""
                <div style="text-align: center; margin-top: -10px; margin-bottom: 15px; font-size: 15px;">
                    🎟️ Asignados: <b>{t_asignados}</b> &nbsp;|&nbsp; 💰 Recaudar: <b>${t_monto:,.2f}</b>
                </div>
                """, 
                unsafe_allow_html=True
            )
        except Exception as e:
            st.error(f"Error calculando totales: {e}")

    # 4. Botón Descarga
        nombre_archivo = "Tabla_ConOcupados.jpg" if ver_ocupados else "Tabla_Limpia.jpg"
        st.download_button("⬇️ DESCARGAR IMAGEN", img_bytes, nombre_archivo, "image/jpeg", use_container_width=True)
        
        st.divider()

        modo = st.radio("📍 Selecciona opción:", ["🔢 Por N° de Boleto", "👤 Por Cliente"], horizontal=True)
        st.write("") # Espacio visual

        # ============================================================
        #  MODO A: POR NÚMERO (Botones Flexibles - Corrección de Pagos)
        # ============================================================
        if modo == "🔢 Por N° de Boleto":
            c1, c2 = st.columns([2,1])
            entrada_boletos = c1.text_input("Boleto(s) N° (Ej: 10, 25):", placeholder="Escribe números...")
            
            lista_busqueda = []
            if entrada_boletos:
                try:
                    partes = entrada_boletos.replace('-', ' ').replace('/', ' ').split(',')
                    for p in partes:
                        if p.strip().isdigit():
                            val = int(p.strip())
                            if 0 <= val < cantidad_boletos:
                                lista_busqueda.append(val)
                except: pass

            if c2.button("🔍 Buscar", use_container_width=True) or lista_busqueda:
                if not lista_busqueda:
                    st.warning("Introduce un número válido.")
                else:
                    # 1. CONSULTA
                    lista_str = ",".join(map(str, lista_busqueda))
                    placeholders = ",".join(["%s"] * len(lista_busqueda))
                    
                    query = f"""
                        SELECT b.numero, b.estado, b.precio, b.total_abonado, b.fecha_asignacion, b.id, b.cliente_id,
                               c.nombre_completo, c.telefono, c.cedula, c.direccion, c.codigo
                        FROM boletos b
                        LEFT JOIN clientes c ON b.cliente_id = c.id
                        WHERE b.sorteo_id = %s AND b.numero IN ({placeholders})
                    """
                    params = [id_sorteo] + lista_busqueda
                    resultados_ocupados = run_query(query, tuple(params))
                    mapa_resultados = {r[0]: r for r in resultados_ocupados} if resultados_ocupados else {}
                    
                    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"

                    # ---------------------------------------------------------
                    #  PANEL VISUAL
                    # ---------------------------------------------------------
                    st.write("### 🎫 Estado Actual")
                    cols_vis = st.columns(4)
                    
                    for i, num_buscado in enumerate(lista_busqueda):
                        if num_buscado in mapa_resultados:
                            dato = mapa_resultados[num_buscado]
                            estado = dato[1]
                            if estado == 'abonado': bg_color = "#1a73e8"
                            elif estado == 'apartado': bg_color = "#FFC107"
                            elif estado == 'pagado': bg_color = "#9e9e9e"
                            txt_estado = estado.upper()
                        else:
                            bg_color = "#4CAF50"; txt_estado = "DISPONIBLE"

                        html_card = f"""
                        <div style="background-color: {bg_color}; border-radius: 10px; padding: 15px; text-align: center; margin-bottom: 15px; color: white; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);">
                            <div style="font-size: 24px; font-weight: bold; line-height: 1.2;">{fmt_num.format(num_buscado)}</div>
                            <div style="font-size: 14px; text-transform: uppercase; margin-top: 5px; opacity: 0.9;">{txt_estado}</div>
                        </div>
                        """
                        with cols_vis[i % 4]: st.markdown(html_card, unsafe_allow_html=True)
                    
                    st.divider()

                    # ---------------------------------------------------------
                    #  GESTIÓN INDIVIDUAL
                    # ---------------------------------------------------------
                    if len(lista_busqueda) == 1:
                        numero = lista_busqueda[0]
                        if numero in mapa_resultados:
                            # BOLETO OCUPADO
                            row = mapa_resultados[numero]
                            b_id, estado, b_precio, b_abonado, b_fecha = row[5], row[1], float(row[2]), float(row[3]), row[4]
                            c_nom, c_tel = row[7], row[8]
                            
                            st.info(f"👤 **Cliente:** {c_nom} | 📞 {c_tel}")
                            
                            # --- BOTONES DE ACCIÓN (Lógica Flexible) ---
                            c_btn1, c_btn2, c_btn3 = st.columns(3)
                            
                            # Botón 1: Pagar (Solo si falta pagar)
                            if estado != 'pagado':
                                if c_btn1.button("✅ PAGAR TOTAL", use_container_width=True, key="btn_pag_ind"):
                                    run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE id=%s", (b_precio, b_id), fetch=False)
                                    st.rerun()

                            # Botón 2: Apartar (VISIBLE SIEMPRE, excepto si ya es apartado)
                            # Permite revertir un 'Pagado' a 'Apartado' (Deuda vuelve a 100%)
                            if estado != 'apartado':
                                if c_btn2.button("📌 APARTAR", use_container_width=True, key="btn_aprt"):
                                    # Al apartar, reseteamos el abono a 0
                                    run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE id=%s", (b_id,), fetch=False)
                                    st.success("Revertido a Apartado"); time.sleep(1); st.rerun()

                            # Botón 3: Liberar (SIEMPRE VISIBLE)
                            if c_btn3.button("🗑️ LIBERAR", type="primary", use_container_width=True, key="btn_lib_ind"):
                                run_query("DELETE FROM boletos WHERE id=%s", (b_id,), fetch=False)
                                st.warning("Liberado"); time.sleep(1); st.rerun()
                            
                            # ZONA ABONO (Solo si hay deuda y no está pagado)
                            if estado != 'pagado' and (b_precio - b_abonado) > 0.01:
                                st.divider()
                                with st.container(border=True):
                                    st.write(f"💸 **Abonar / Restante**")
                                    c_ab1, c_ab2 = st.columns([1, 1])
                                    monto_abono = c_ab1.number_input("Monto:", min_value=0.0, max_value=(b_precio-b_abonado), step=1.0, key="abono_indiv")
                                    if c_ab2.button("💾 GUARDAR", use_container_width=True, key="btn_save_abono"):
                                        if monto_abono > 0:
                                            nt = b_abonado + monto_abono
                                            ne = 'pagado' if (b_precio - nt) <= 0.01 else 'abonado'
                                            run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE id=%s", (nt, ne, b_id), fetch=False)
                                            run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) VALUES (%s, 'MOVIL', 'ABONO', %s, %s)", (id_sorteo, f"Abono {numero}", monto_abono), fetch=False)
                                            st.success("✅ Abonado"); time.sleep(1); st.rerun()

                        else:
                            # BOLETO DISPONIBLE
                            with st.form("venta_single"):
                                st.write(f"### 📝 Vender Boleto {fmt_num.format(numero)}")
                                clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                                opc_cli = {f"{c[1]} | {c[2] or 'S/C'}": c[0] for c in clientes} if clientes else {}
                                nom_sel = st.selectbox("👤 Cliente:", options=list(opc_cli.keys()), index=None)
                                
                                c_ab, c_pr = st.columns(2)
                                abono = c_ab.number_input("Abono Inicial ($)", value=0.0) 
                                c_pr.metric("Precio", f"${precio_s}")
                                
                                if st.form_submit_button("💾 ASIGNAR", use_container_width=True):
                                    if nom_sel:
                                        cid = opc_cli[nom_sel]
                                        est = 'pagado' if abono >= precio_s else 'abonado'
                                        if abono == 0: est = 'apartado'
                                        run_query("INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion) VALUES (%s, %s, %s, %s, %s, %s, NOW())", (id_sorteo, numero, est, precio_s, cid, abono), fetch=False)
                                        st.success("✅ Asignado"); time.sleep(1); st.rerun()
                                    else: st.error("⚠️ Falta cliente")
                    
                    elif len(lista_busqueda) > 1:
                        if [n for n in lista_busqueda if n in mapa_resultados]:
                            st.error("❌ Hay boletos ocupados en la lista. Búscalos individualmente.")
                        else:
                            st.info("Venta masiva disponible")

                    # ---------------------------------------------------------
                    #  C. LÓGICA DE GESTIÓN (MÚLTIPLE)
                    # ---------------------------------------------------------
                    elif len(lista_busqueda) > 1:
                        # Verificamos si alguno ya está ocupado
                        ocupados = [n for n in lista_busqueda if n in mapa_resultados]
                        
                        if ocupados:
                            st.error(f"❌ No se pueden asignar masivamente porque estos boletos ya están ocupados: {ocupados}")
                            st.info("Gestiona los boletos ocupados uno por uno o usa la búsqueda por cliente.")
                        else:
                            st.success(f"🟢 {len(lista_busqueda)} boletos disponibles. Llenar datos:")
                            
                            # --- FORMULARIO DE VENTA MASIVA ---
                            with st.form("venta_multi"):
                                st.write(f"### 📝 Asignar Boletos: {lista_busqueda}")
                                
                                # 1. Selector de Cliente
                                clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                                opc_cli = {}
                                if clientes:
                                    for c in clientes:
                                        cod_d = c[2] if c[2] else "S/C"
                                        opc_cli[f"{c[1]} | {cod_d}"] = c[0]
                                
                                nom_sel = st.selectbox("👤 Cliente:", options=list(opc_cli.keys()), index=None)
                                
                                # 2. Datos de Pago
                                st.divider()
                                c_ab, c_pr = st.columns(2)
                                abono_unit = c_ab.number_input("Abono por Boleto ($)", value=0.0, min_value=0.0, step=1.0)
                                
                                total_operacion = abono_unit * len(lista_busqueda)
                                c_pr.metric("Total a Pagar (Suma)", f"${total_operacion:,.2f}")
                                
                                # 3. Botón de Guardar
                                if st.form_submit_button("💾 ASIGNAR TODOS", use_container_width=True):
                                    if nom_sel:
                                        cid = opc_cli[nom_sel]
                                        
                                        # Determinar estado según el abono unitario vs precio unitario
                                        est = 'pagado' if abono_unit >= precio_s else 'abonado'
                                        if abono_unit == 0: est = 'apartado'
                                        
                                        # Insertar cada boleto
                                        for n_bol in lista_busqueda:
                                            run_query("""
                                                INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion) 
                                                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                                            """, (id_sorteo, n_bol, est, precio_s, cid, abono_unit), fetch=False)
                                            
                                            # Opcional: Registrar en historial (si tienes tabla historial)
                                            # run_query("INSERT INTO historial ...") 

                                        st.success("✅ Boletos asignados correctamente")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error("⚠️ Debes seleccionar un cliente.")

        # ============================================================
        #  MODO B: POR CLIENTE (Botones dinámicos según estado)
        # ============================================================
        else:
            # 1. Buscador de Clientes
            clientes_con_boletos = run_query("""
                SELECT DISTINCT c.id, c.nombre_completo, c.telefono, c.cedula, c.direccion, c.codigo
                FROM clientes c
                JOIN boletos b ON c.id = b.cliente_id
                WHERE b.sorteo_id = %s ORDER BY c.nombre_completo
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
                
                boletos_cli = run_query("""
                    SELECT numero, estado, precio, total_abonado, fecha_asignacion
                    FROM boletos WHERE sorteo_id = %s AND cliente_id = %s ORDER BY numero ASC
                """, (id_sorteo, cid))
                
                if boletos_cli:
                    st.info(f"📋 Gestionando boletos de: **{datos_c['nombre']}**")
                    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"

                    # A. PANEL VISUAL (Color Oro)
                    st.write("### 🎫 Estado Actual")
                    cols_info = st.columns(4) 
                    for i, b in enumerate(boletos_cli):
                        num, est = b[0], b[1]
                        if est == 'abonado': bg = "#1a73e8" # Azul
                        elif est == 'apartado': bg = "#FFC107" # Amarillo Oro
                        else: bg = "#9e9e9e" # Gris
                        
                        html_card = f"""<div style="background-color: {bg}; border-radius: 10px; padding: 10px; text-align: center; margin-bottom: 10px; color: white; font-weight: bold;">
                            <span style="font-size: 20px;">{fmt_num.format(num)}</span><br><span style="font-size: 10px;">{est.upper()}</span>
                        </div>"""
                        with cols_info[i % 4]: st.markdown(html_card, unsafe_allow_html=True)
                    
                    st.divider()

                    # B. PANEL DE SELECCIÓN
                    st.write("### ✅ Toca para procesar:")
                    
                    if 'seleccion_actual' not in st.session_state: st.session_state.seleccion_actual = []
                    if 'cliente_previo' not in st.session_state or st.session_state.cliente_previo != cid:
                        st.session_state.seleccion_actual = [] 
                        st.session_state.cliente_previo = cid

                    cols_sel = st.columns(5)
                    datos_boletos_map = {} 

                    for i, b in enumerate(boletos_cli):
                        num, est, pre, abo, f_asig = b
                        datos_boletos_map[num] = {'numero': num, 'estado': est, 'precio': pre, 'abonado': abo, 'fecha': f_asig}
                        
                        # Selección Libre
                        es_seleccionado = num in st.session_state.seleccion_actual
                        label_btn = f"✔ {fmt_num.format(num)}" if es_seleccionado else f"{fmt_num.format(num)}"
                        type_btn = "primary" if es_seleccionado else "secondary"
                        
                        with cols_sel[i % 5]:
                            def on_click_btn(n=num):
                                if n in st.session_state.seleccion_actual: st.session_state.seleccion_actual.remove(n)
                                else: st.session_state.seleccion_actual.append(n)

                            st.button(label_btn, key=f"btn_sel_{num}", type=type_btn, 
                                      on_click=on_click_btn, 
                                      use_container_width=True)

                    numeros_sel = sorted(st.session_state.seleccion_actual)
                    datos_sel = [datos_boletos_map[n] for n in numeros_sel]

                    st.divider()

                    # C. ZONA ABONO (Si hay 1 seleccionado y tiene deuda)
                    if len(numeros_sel) == 1:
                        dato_unico = datos_sel[0]
                        deuda = dato_unico['precio'] - dato_unico['abonado']
                        if deuda > 0.01: # Solo mostrar si hay deuda
                            with st.container(border=True):
                                st.write(f"💸 **Abonar: {fmt_num.format(dato_unico['numero'])}** (Deuda: ${deuda:.2f})")
                                c1, c2 = st.columns([2,1])
                                m = c1.number_input("Monto:", 0.0, deuda, step=1.0, label_visibility="collapsed")
                                if c2.button("GUARDAR", use_container_width=True) and m > 0:
                                    nt = dato_unico['abonado'] + m
                                    ne = 'pagado' if (dato_unico['precio'] - nt) <= 0.01 else 'abonado'
                                    run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE sorteo_id=%s AND numero=%s", (nt, ne, id_sorteo, dato_unico['numero']), fetch=False)
                                    st.session_state.seleccion_actual = []; st.rerun()

                    # D. BOTONES DE ACCIÓN (Desaparecen si no son necesarios)
                    if numeros_sel:
                        c_acc1, c_acc2, c_acc3 = st.columns(3)
                        
                        # Lógica de Visibilidad
                        # Mostrar PAGAR si al menos UNO NO está pagado
                        show_pagar = any(d['estado'] != 'pagado' for d in datos_sel)
                        
                        # Mostrar APARTAR si al menos UNO NO está apartado (Permite revertir pagados)
                        show_apartar = any(d['estado'] != 'apartado' for d in datos_sel)
                        
                        # 1. PAGAR
                        if show_pagar:
                            if c_acc1.button("✅ PAGAR", use_container_width=True):
                                for d in datos_sel:
                                    run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE sorteo_id=%s AND numero=%s", (d['precio'], id_sorteo, d['numero']), fetch=False)
                                st.session_state.seleccion_actual = []; st.success("Pagado"); time.sleep(1); st.rerun()
                        
                        # 2. APARTAR
                        if show_apartar:
                            if c_acc2.button("📌 APARTAR", use_container_width=True):
                                for d in datos_sel:
                                    run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE sorteo_id=%s AND numero=%s", (id_sorteo, d['numero']), fetch=False)
                                st.session_state.seleccion_actual = []; st.success("Apartado"); time.sleep(1); st.rerun()

                        # 3. LIBERAR (Siempre visible si hay selección)
                        if c_acc3.button("🗑️ LIBERAR", type="primary", use_container_width=True):
                            for d in datos_sel:
                                run_query("DELETE FROM boletos WHERE sorteo_id=%s AND numero=%s", (id_sorteo, d['numero']), fetch=False)
                            st.session_state.seleccion_actual = []; st.warning("Liberados"); time.sleep(1); st.rerun()
                    
                    st.divider()
                    
                    # E. WHATSAPP Y PDF
                    col_wa, col_pdf = st.columns([1, 1])
                    if numeros_sel:
                        partes_msg = [f"N° {fmt_num.format(d['numero'])} ({d['estado'].upper()})" for d in datos_sel]
                        txt_boletos = ", ".join(partes_msg)
                        msg_wa = f"Hola. Boletos: {txt_boletos}. Sorteo {nombre_s}."
                        
                        tel_clean = "".join(filter(str.isdigit, str(datos_c['telefono'] or "")))
                        link_wa = f"https://api.whatsapp.com/send?phone=58{tel_clean}&text={urllib.parse.quote(msg_wa)}" if len(tel_clean) >= 10 else ""
                        
                        col_wa.link_button("📲 WhatsApp", link_wa if link_wa else "#", disabled=(not link_wa), use_container_width=True)
                        
                        with col_pdf:
                            st.write("**Descargar PDFs:**")
                            for d in datos_sel:
                                info_pdf = {'cliente': datos_c['nombre'], 'cedula': datos_c['cedula'], 'telefono': datos_c['telefono'], 'direccion': datos_c['direccion'], 'codigo_cli': datos_c['codigo'], 'estado': d['estado'], 'precio': d['precio'], 'abonado': d['abonado'], 'fecha_asignacion': d['fecha']}
                                pdf_data = generar_pdf_memoria(d['numero'], info_pdf, config_full, cantidad_boletos)
                                st.download_button(f"📄 {fmt_num.format(d['numero'])}", pdf_data, f"boleto_{d['numero']}.pdf", "application/pdf", key=f"d_{d['numero']}", use_container_width=True)
                    else:
                        col_wa.button("📲 WhatsApp", disabled=True, use_container_width=True)
                        col_pdf.info("Selecciona para ver PDFs")
                        
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

