import streamlit as st
import psycopg2
import io
import os
import time
import math
import urllib.parse
import pandas as pd
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
        conn.rollback() 
        st.error(f"Error SQL: {e}")
        return None
    
# ============================================================================
#  HELPER: REGISTRO DE HISTORIAL
# ============================================================================
def log_movimiento(sorteo_id, accion, detalle, monto):
    sql = """
        INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto, fecha_hora)
        VALUES (%s, 'MOVIL', %s, %s, %s, NOW())
    """
    run_query(sql, (sorteo_id, accion, detalle, monto), fetch=False)
    
# ============================================================================
#  CONTROL DE INACTIVIDAD (10 MINUTOS)
# ============================================================================
def verificar_inactividad():
    TIMEOUT_SEGUNDOS = 600 
    now = time.time()
    if 'ultima_actividad' in st.session_state:
        tiempo_transcurrido = now - st.session_state['ultima_actividad']
        if tiempo_transcurrido > TIMEOUT_SEGUNDOS:
            st.warning("⚠️ Sesión cerrada por inactividad (10 min).")
            st.session_state["password_correct"] = False
            del st.session_state['ultima_actividad']
            time.sleep(2)
            st.rerun()
            return False
    st.session_state['ultima_actividad'] = now
    return True

# ============================================================================
#  FUNCIONES DE APOYO Y WHATSAPP (Móvil)
# ============================================================================
def formato_fecha_inteligente(fecha_str):
    """Convierte una fecha DD/MM/YYYY a Hoy, Mañana o 'del sábado'"""
    if not fecha_str or "Pendiente" in fecha_str or "Sin" in fecha_str:
        return f"del día {fecha_str}"
    try:
        if "/" in fecha_str:
            d_obj = datetime.strptime(fecha_str, "%d/%m/%Y").date()
        else:
            d_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        
        hoy = datetime.now().date()
        delta = (d_obj - hoy).days
        
        if delta == 0: return "de hoy"
        elif delta == 1: return "de Mañana"
        else:
            dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            return f"del {dias[d_obj.weekday()]}"
    except:
        return f"del día {fecha_str}"

def get_whatsapp_link_exacto(telefono, boleto_num, estado, cliente_nom, sorteo_nom, fecha_sorteo, hora_sorteo, cantidad_boletos=1000):
    if not telefono: return ""
    tel_clean = "".join(filter(str.isdigit, str(telefono)))
    if len(tel_clean) == 10: tel_clean = "58" + tel_clean
    elif len(tel_clean) == 11 and tel_clean.startswith("0"): tel_clean = "58" + tel_clean[1:]
    
    est_str = estado.upper()
    if estado == 'pagado': est_str = "PAGADO"
    elif estado == 'abonado': est_str = "ABONADO"
    elif estado == 'apartado': est_str = "APARTADO"
    
    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
    num_str = fmt_num.format(boleto_num)
    texto_boleto = f"N° {num_str} ({est_str})"
    
    # Aplicar fecha inteligente
    txt_fecha = formato_fecha_inteligente(fecha_sorteo)
    
    # Se añade el strip() para evitar el error de los asteriscos
    mensaje = (
        f"Hola. Saludos, somos Sorteos Milán!!, aquí te enviamos el comprobante de tu "
        f"BOLETO: {texto_boleto}, a nombre de {cliente_nom.strip()} para el sorteo "
        f"'{sorteo_nom}' {txt_fecha} a las {hora_sorteo}. ¡Suerte!🍀"
    )
    return f"https://wa.me/{tel_clean}?text={urllib.parse.quote(mensaje)}"

# ============================================================================
#  CALCULADORA DE TARIFAS
# ============================================================================
def calcular_total_pagar_escala(cantidad_boletos, config_rifa):
    tarifas = []
    if config_rifa.get('cant_p1') and config_rifa.get('prec_p1') and int(config_rifa['cant_p1']) > 0:
        c = int(config_rifa['cant_p1'])
        tarifas.append((c, float(config_rifa['prec_p1']) / c))
    if config_rifa.get('cant_p2') and config_rifa.get('prec_p2') and int(config_rifa['cant_p2']) > 0:
        c = int(config_rifa['cant_p2'])
        tarifas.append((c, float(config_rifa['prec_p2']) / c))
    if config_rifa.get('cant_p3') and config_rifa.get('prec_p3') and int(config_rifa['cant_p3']) > 0:
        c = int(config_rifa['cant_p3'])
        tarifas.append((c, float(config_rifa['prec_p3']) / c))
        
    if not tarifas:
        precio_base = float(config_rifa.get('precio_boleto') or 0)
        return cantidad_boletos * precio_base

    tarifas.sort(key=lambda x: x[0], reverse=True)
    precio_unitario_aplicado = None
    
    for cant_minima, precio_unit_promo in tarifas:
        if cantidad_boletos >= cant_minima:
            precio_unitario_aplicado = precio_unit_promo
            break
            
    if precio_unitario_aplicado is None:
        precio_unitario_aplicado = tarifas[-1][1]
        
    return cantidad_boletos * precio_unitario_aplicado

# ============================================================================
#  PDF DIGITAL (APP MÓVIL)
# ============================================================================
def generar_pdf_memoria(numero_boleto, datos_completos, config_db, cantidad_boletos=1000):
    buffer = io.BytesIO()
    rifa = config_db['rifa']
    empresa = config_db['empresa']
    
    fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
    num_str = fmt_num.format(numero_boleto)
    
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

    lista_claves = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    count_premios = sum(1 for k in lista_claves if rifa.get(k))
    total_h = 440 + max(0, (count_premios - 3) * 20)
    total_w = 390
    
    c = canvas.Canvas(buffer, pagesize=(total_w, total_h))
    m_izq, m_der = 30, total_w - 30
    centro = total_w / 2
    y = total_h - 30
    
    logo_files = ["logo.jpg", "logo.png", "logo.jpeg"]
    for f in logo_files:
        if os.path.exists(f):
            try:
                c.drawImage(ImageReader(f), m_izq, y-27, width=38, height=38, preserveAspectRatio=True, mask='auto')
                break
            except: pass

    c.setFont("Helvetica-Bold", 12)
    c.drawString(m_izq + 50, y, empresa.get('nombre', 'SORTEOS MILÁN'))
    c.setFont("Helvetica", 8)
    c.drawString(m_izq + 50, y-12, f"RIF: {empresa.get('rif', '')}")
    c.drawString(m_izq + 50, y-25, f"Tel: {empresa.get('telefono', '')}")
    
    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.70, 0.55, 0.35) 
    c.drawRightString(m_der, y-5, f"BOLETO N° {num_str}")
    c.setFillColorRGB(0,0,0)
    
    fecha_emision = datetime.now().strftime('%d/%m/%Y %I:%M %p').lower()
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(m_der, y-25, f"Emitido: {fecha_emision}")
    
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
    
    y_start = y - 25
    col_izq_x = m_izq
    col_der_x = centro - 10 
    
    y = y_start
    c.setFont("Helvetica-Bold", 10); c.drawString(col_izq_x, y, "SORTEO:")
    c.drawString(col_izq_x + 50, y, rifa['nombre'][:35])
    y -= 15
    c.drawString(col_izq_x, y, "FECHA:")
    
    hora_sorteo = str(rifa.get('hora_sorteo','')).lower()
    c.drawString(col_izq_x + 50, y, f"{rifa.get('fecha_sorteo','')} {hora_sorteo}")
    
    # 🔥 NUEVO: DIBUJAR TARIFAS EN PDF MÓVIL
    y -= 25
    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_izq_x, y, "TARIFAS:")
    y -= 12
    c.setFont("Helvetica", 9)
    if rifa.get('cant_p1') and rifa.get('prec_p1'):
        c.drawString(col_izq_x, y, f"• {rifa['cant_p1']} x ${float(rifa['prec_p1']):,.2f}")
        y -= 12
    if rifa.get('cant_p2') and rifa.get('prec_p2'):
        c.drawString(col_izq_x, y, f"• {rifa['cant_p2']} x ${float(rifa['prec_p2']):,.2f}")
        y -= 12
    if rifa.get('cant_p3') and rifa.get('prec_p3'):
        c.drawString(col_izq_x, y, f"• {rifa['cant_p3']} x ${float(rifa['prec_p3']):,.2f}")
    
    y_prem = y_start
    c.setFont("Helvetica-Bold", 10)
    c.drawString(col_der_x, y_prem, "PREMIOS:")
    y_prem -= 12; c.setFont("Helvetica", 9)
    etiquetas = ["Triple A:", "Triple B:", "Triple Z:", "Especial 1:", "Especial 2:"]
    for i, k in enumerate(lista_claves):
        val = rifa.get(k, "")
        if val:
            lbl = etiquetas[i] if i < len(etiquetas) else f"{i+1}º:"
            c.drawString(col_der_x, y_prem, f"{lbl} {val[:30]}")
            y_prem -= 12
    
    y_fin_arriba = min(y, y_prem)
    y_linea = y_fin_arriba - 20 # 🔥 Separación de la línea dorada
    
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
    
    f_reg_str = ""
    try:
        if fecha_asig:
            if hasattr(fecha_asig, 'strftime'):
                f_reg_str = fecha_asig.strftime('%d/%m/%Y %I:%M:%S %p').lower()
            else:
                try:
                    fecha_limpia = str(fecha_asig).split('.')[0] 
                    dt_obj = datetime.strptime(fecha_limpia, '%Y-%m-%d %H:%M:%S')
                    f_reg_str = dt_obj.strftime('%d/%m/%Y %I:%M:%S %p').lower()
                except:
                    f_reg_str = str(fecha_asig).lower()
        else:
            f_reg_str = datetime.now().strftime('%d/%m/%Y %I:%M:%S %p').lower()
    except Exception:
        f_reg_str = str(fecha_asig).lower()

    c.drawString(m_izq, y, f"Fecha de registro: {f_reg_str}")
    
    y_est = y_final
    centro_der = x_div + ((m_der - x_div) / 2)
    c.setFont("Helvetica-Bold", 10); c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(centro_der, y_est, "ESTADO:")
    c.setFont("Helvetica-Bold", 18); c.setFillColorRGB(0, 0, 0.4) 
    c.drawCentredString(centro_der, y_est - 30, estado_fmt)
    c.setFillColorRGB(0, 0, 0)
    
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
#  MOTOR DE REPORTES VISUALES (ACTUALIZADO A LÓGICA DE PC)
# ============================================================================
def generar_imagen_reporte(id_sorteo, config_completa, cantidad_boletos, tipo_img=1):
    """
    tipo_img: 1=Con Ocupados(Amarillo), 2=Solo Disponibles(Blancos), 3=Compacta(Agrupados)
    """
    if cantidad_boletos <= 100:
        cols_img = 10; rows_img = 10
        base_w = 2000; base_h = 2500
        font_s_title = 80; font_s_info = 40; font_s_num = 60
    else:
        cols_img = 20; rows_img = 50 
        base_w = 2700; base_h = 4800 # Formato 9:16 exacto
        font_s_title = 100; font_s_info = 50; font_s_num = 45
    
    margin_px = 80
    header_h = 450
    grid_pw = base_w - (2 * margin_px)
    grid_ph = base_h - (2 * margin_px) - header_h
    cell_pw = (grid_pw / cols_img) - 4 
    cell_ph = (grid_ph / rows_img) - 4

    boletos_ocupados = {}
    ocupados_raw = run_query("SELECT numero, estado FROM boletos WHERE sorteo_id = %s", (id_sorteo,))
    if ocupados_raw: 
        boletos_ocupados = {row[0]: row[1] for row in ocupados_raw}

    if cantidad_boletos >= 1000 and tipo_img == 3:
        lista_mostrar = [i for i in range(cantidad_boletos) if boletos_ocupados.get(i, 'disponible') == 'disponible']
        if not lista_mostrar: lista_mostrar = [0] 
        
        filas_necesarias = math.ceil(len(lista_mostrar) / cols_img)
        alto_grid_nuevo = filas_necesarias * (cell_ph + 4)
        alto_calculado = int(margin_px * 2 + header_h + alto_grid_nuevo)
        
        lienzo_h = max(2500, alto_calculado)
        lienzo_w = base_w
    else:
        lista_mostrar = list(range(cantidad_boletos))
        lienzo_w = base_w
        lienzo_h = base_h

    img = Image.new('RGB', (lienzo_w, lienzo_h), 'white')
    draw = ImageDraw.Draw(img)
    
    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", font_s_title)
        font_info = ImageFont.truetype("DejaVuSans.ttf", font_s_info)
        font_num = ImageFont.truetype("DejaVuSans-Bold.ttf", font_s_num)
    except:
        font_title = ImageFont.load_default()
        font_info = ImageFont.load_default()
        font_num = ImageFont.load_default()

    rifa = config_completa['rifa']
    
    titulo = rifa['nombre'].upper()
    bbox_t = draw.textbbox((0,0), titulo, font=font_title)
    tw_t = bbox_t[2] - bbox_t[0]
    draw.text(((lienzo_w - tw_t)/2, 60), titulo, fill='#1a73e8', font=font_title)
    
    iy = 180
    draw.text((margin_px, iy), f"📅 Fecha: {datetime.now().strftime('%d/%m/%Y')}", fill='#555', font=font_info)
    iy += 60
    txt_sorteo = f"🎲 Sorteo: {rifa.get('fecha_sorteo','')} {rifa.get('hora_sorteo','')}"
    draw.text((margin_px, iy), txt_sorteo, fill='#388E3C', font=font_info)
    iy += 65
    draw.text((margin_px, iy), "💰 PRECIOS:", fill='#D32F2F', font=font_info)
    iy += 55
    if rifa.get('cant_p1') and rifa.get('prec_p1'):
        draw.text((margin_px + 30, iy), f"• {rifa['cant_p1']} x ${float(rifa['prec_p1']):,.2f}", fill='black', font=font_info)
        iy += 50
    if rifa.get('cant_p2') and rifa.get('prec_p2'):
        draw.text((margin_px + 30, iy), f"• {rifa['cant_p2']} x ${float(rifa['prec_p2']):,.2f}", fill='black', font=font_info)
        iy += 50
    if rifa.get('cant_p3') and rifa.get('prec_p3'):
        draw.text((margin_px + 30, iy), f"• {rifa['cant_p3']} x ${float(rifa['prec_p3']):,.2f}", fill='black', font=font_info)
        iy += 50
    
    # AJUSTE HACIA EL CENTRO IGUAL A PC
    if lienzo_w >= 2700:
        px = lienzo_w - margin_px - 1350
    else:
        px = lienzo_w - margin_px - 1180
        
    py = 180
    draw.text((px, py), "🏆 PREMIOS:", fill='#D32F2F', font=font_info)
    py += 60
    
    keys = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    lbls = ["🥇 1er:", "🥈 2do:", "🥉 3er:", "🎁 Extra 1:", "🎁 Extra 2:"]
    for k, l in zip(keys, lbls):
        val = rifa.get(k)
        if val and val.strip():
            draw.text((px, py), f"{l} {val}", fill='black', font=font_info)
            py += 50

    y_start = margin_px + header_h
    fmt = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"

    for idx, num_real in enumerate(lista_mostrar):
        r = idx // cols_img
        c = idx % cols_img
        
        x = margin_px + (c * (cell_pw + 4))
        y = y_start + (r * (cell_ph + 4))
        
        estado = boletos_ocupados.get(num_real, 'disponible')
        ocupado = estado != 'disponible'
        
        bg_color = 'white'
        texto_visible = True
        
        if tipo_img == 1:
            if ocupado: bg_color = '#FFFF00' 
        elif tipo_img == 2:
            if ocupado: texto_visible = False 
        elif tipo_img == 3:
            pass 
        
        draw.rectangle([x, y, x + cell_pw, y + cell_ph], fill=bg_color, outline='black', width=3)
        
        if texto_visible:
            txt = fmt.format(num_real)
            bbox_n = draw.textbbox((0,0), txt, font=font_num)
            tw_n = bbox_n[2] - bbox_n[0]
            th_n = bbox_n[3] - bbox_n[1]
            tx = x + (cell_pw - tw_n) / 2
            ty = y + (cell_ph - th_n) / 2
            draw.text((tx, ty), txt, fill='black', font=font_num)
            
    buf = io.BytesIO()
    calidad = 95 if cantidad_boletos <= 100 else 90
    img.save(buf, format="JPEG", quality=calidad)
    buf.seek(0)
    return buf

# ============================================================================
#  SISTEMA DE LOGIN
# ============================================================================
def check_password():
    if st.session_state.get("password_correct", False):
        return True

    st.markdown("### 🔐 Acceso Restringido")
    with st.form("login_form"):
        pwd_input = st.text_input("Ingresa la contraseña:", type="password")
        submit_btn = st.form_submit_button("Entrar")
    
    if submit_btn:
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

    sorteos = run_query("SELECT id, nombre, precio_boleto, fecha_sorteo, hora_sorteo, premio1, premio2, premio3, premio_extra1, premio_extra2, cant_promo1, precio_promo1, cant_promo2, precio_promo2, cant_promo3, precio_promo3 FROM sorteos WHERE activo = TRUE")
    config_rows = run_query("SELECT clave, valor FROM configuracion")
    
    if not sorteos: st.warning("No hay sorteos activos."); return

    empresa_config = {"nombre": "SORTEOS MILÁN", "rif": "", "telefono": ""}
    if config_rows:
        cfg = {r[0]: r[1] for r in config_rows}
        empresa_config.update({k: v for k, v in cfg.items() if k in empresa_config})

    # SELECTOR DE SORTEOS ACTIVOS
    opciones_sorteo = {s[1]: s for s in sorteos}
    nom_sorteo = st.selectbox("Sorteo Activo:", list(opciones_sorteo.keys()))
    
    if not nom_sorteo: return
    s_data = opciones_sorteo[nom_sorteo]
    id_sorteo, nombre_s, precio_s, fecha_raw, hora_raw = s_data[0], s_data[1], float(s_data[2] or 0), s_data[3], s_data[4]
    
    try:
        fecha_s = fecha_raw.strftime('%d/%m/%Y')
    except:
        try:
            f_obj = datetime.strptime(str(fecha_raw), '%Y-%m-%d')
            fecha_s = f_obj.strftime('%d/%m/%Y')
        except:
            fecha_s = str(fecha_raw)

    try:
        h_obj = datetime.strptime(str(hora_raw), '%H:%M:%S')
        hora_s = h_obj.strftime('%I:%M %p').lower() 
    except:
        hora_s = str(hora_raw).lower()
    
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
    
    st.caption(f"⚙️ Modo detectado: {cantidad_boletos} boletos")

    rifa_config = {
        "nombre": nombre_s, "precio_boleto": precio_s, "fecha_sorteo": str(fecha_s), "hora_sorteo": str(hora_s),
        "premio1": s_data[5], "premio2": s_data[6], "premio3": s_data[7], "premio_extra1": s_data[8], "premio_extra2": s_data[9],
        "cant_p1": s_data[10], "prec_p1": s_data[11],
        "cant_p2": s_data[12], "prec_p2": s_data[13],
        "cant_p3": s_data[14], "prec_p3": s_data[15]
    }
    config_full = {'rifa': rifa_config, 'empresa': empresa_config}
    
    tab_venta, tab_clientes, tab_cobranza = st.tabs(["🎫 VENTA", "👥 CLIENTES", "💰 COBRANZA"])

    # ---------------- PESTAÑA VENTA ----------------
    with tab_venta:
        st.write("### 📊 Estado del Sorteo")
        
        # 1. PREVISUALIZACIÓN EN VIVO (ARRIBA)
        ver_ocupados = st.checkbox("Mostrar Ocupados (Amarillo)", value=True)
        
        tipo_vista = 1 if ver_ocupados else 2
        img_bytes = generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, tipo_img=tipo_vista)
        st.image(img_bytes, caption="Actualizado en tiempo real", use_container_width=True)
        
        # 2. Calcular Totales (Asignados y Dinero)
        try:
            datos_resumen = run_query("SELECT COUNT(*), SUM(precio) FROM boletos WHERE sorteo_id = %s", (id_sorteo,))
            t_asignados = 0
            t_monto = 0.0
            if datos_resumen and datos_resumen[0]:
                fila = datos_resumen[0]
                t_asignados = fila[0] or 0         
                t_monto = float(fila[1] or 0.0)    
            
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

        # 3. BOTONES DE DESCARGA (DEBAJO DE LA IMAGEN)
        st.write("📥 **Descargar Tablas:**")
        if cantidad_boletos <= 100:
            c_d1, c_d2 = st.columns(2)
            c_d1.download_button("⬇️ Con Ocupados", generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, 1), "01_Tabla_ConOcupados.jpg", "image/jpeg", use_container_width=True)
            c_d2.download_button("⬇️ Solo Disponibles", generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, 2), "02_Tabla_SoloDisponibles.jpg", "image/jpeg", use_container_width=True)
        else:
            c_d1, c_d2, c_d3 = st.columns(3)
            c_d1.download_button("⬇️ Ocupados", generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, 1), "01_Tabla_ConOcupados.jpg", "image/jpeg", use_container_width=True)
            c_d2.download_button("⬇️ Limpia", generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, 2), "02_Tabla_SoloDisponibles.jpg", "image/jpeg", use_container_width=True)
            c_d3.download_button("⬇️ Agrupada", generar_imagen_reporte(id_sorteo, config_full, cantidad_boletos, 3), "03_Tabla_Compacta.jpg", "image/jpeg", use_container_width=True)
        
        st.divider()

        # ------------------------------------------------------------------
        #  SELECTOR DE MODO Y DEFINICIÓN DE FORMATO
        # ------------------------------------------------------------------
        modo = st.radio("📍 Selecciona opción:", ["🔢 Por N° de Boleto", "👤 Por Cliente"], horizontal=True)
        st.write("") 
        
        fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"

        if modo == "🔢 Por N° de Boleto":
            c1, c2 = st.columns([2,1])
            entrada_boletos = c1.text_input("Boleto(s) N° (Ej: 01, 25):", placeholder="Escribe números...")
            
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

                    if len(lista_busqueda) == 1:
                        numero = lista_busqueda[0]
                        str_num = fmt_num.format(numero)

                        if numero in mapa_resultados:
                            row = mapa_resultados[numero]
                            b_id, estado, b_precio, b_abonado, b_fecha = row[5], row[1], float(row[2]), float(row[3]), row[4]
                            c_nom, c_tel, c_ced, c_dir, c_cod = row[7], row[8], row[9], row[10], row[11]
                            
                            st.info(f"👤 **Cliente:** {c_nom} | 📞 {c_tel}")
                            
                            c_btn1, c_btn2, c_btn3 = st.columns(3)
                            
                            if estado != 'pagado':
                                if c_btn1.button("✅ PAGAR TOTAL", use_container_width=True, key="btn_pag_ind"):
                                    run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE id=%s", (b_precio, b_id), fetch=False)
                                    log_movimiento(id_sorteo, 'PAGO_COMPLETO', f"Boleto {str_num} - {c_nom}", b_precio)
                                    st.rerun()

                            if estado != 'apartado':
                                if c_btn2.button("📌 APARTAR", use_container_width=True, key="btn_aprt"):
                                    run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE id=%s", (b_id,), fetch=False)
                                    log_movimiento(id_sorteo, 'REVERTIR_APARTADO', f"Boleto {str_num} - {c_nom}", 0)
                                    st.success("Revertido a Apartado"); time.sleep(1); st.rerun()

                            if c_btn3.button("🗑️ LIBERAR", type="primary", use_container_width=True, key="btn_lib_ind"):
                                run_query("DELETE FROM boletos WHERE id=%s", (b_id,), fetch=False)
                                log_movimiento(id_sorteo, 'LIBERACION', f"Boleto {str_num} - {c_nom}", 0)
                                st.warning("Liberado"); time.sleep(1); st.rerun()
                            
                            if estado != 'pagado' and (b_precio - b_abonado) > 0.01:
                                st.divider()
                                with st.container(border=True):
                                    st.write(f"💸 **Abonar al N° {str_num}**")
                                    c_ab1, c_ab2 = st.columns([1, 1])
                                    monto_abono = c_ab1.number_input("Monto:", min_value=0.0, max_value=(b_precio-b_abonado), step=1.0, key="abono_indiv")
                                    if c_ab2.button("💾 GUARDAR", use_container_width=True, key="btn_save_abono"):
                                        if monto_abono > 0:
                                            nt = b_abonado + monto_abono
                                            ne = 'pagado' if (b_precio - nt) <= 0.01 else 'abonado'
                                            run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE id=%s", (nt, ne, b_id), fetch=False)
                                            log_movimiento(id_sorteo, 'ABONO', f"Boleto {str_num} - {c_nom}", monto_abono)
                                            st.success("✅ Abonado"); time.sleep(1); st.rerun()
                            
                            st.divider()

                            col_pdf, col_wa = st.columns([1, 1])
                            
                            partes_nom = c_nom.strip().upper().split()
                            if len(partes_nom) >= 3: nom_archivo = f"{partes_nom[0]}_{partes_nom[2]}"
                            elif len(partes_nom) == 2: nom_archivo = f"{partes_nom[0]}_{partes_nom[1]}"
                            else: nom_archivo = partes_nom[0]
                            
                            n_file = f"{str_num} {nom_archivo} ({estado.upper()}).pdf"

                            info_pdf = {'cliente': c_nom, 'cedula': c_ced, 'telefono': c_tel, 'direccion': c_dir, 'codigo_cli': c_cod, 'estado': estado, 'precio': b_precio, 'abonado': b_abonado, 'fecha_asignacion': b_fecha}
                            pdf_data = generar_pdf_memoria(numero, info_pdf, config_full, cantidad_boletos)
                            
                            with col_pdf:
                                st.download_button(f"📄 PDF", pdf_data, n_file, "application/pdf", use_container_width=True)

                            link_wa = get_whatsapp_link_exacto(c_tel, numero, estado, c_nom, nombre_s, str(fecha_s), str(hora_s), cantidad_boletos)
                            
                            with col_wa:
                                if link_wa:
                                    st.link_button("📲 WhatsApp", link_wa, use_container_width=True)
                                else:
                                    st.warning("Sin teléfono")

                        else:
                            with st.form("venta_single"):
                                st.write(f"### 📝 Vender Boleto {str_num}")
                                
                                # 🔥 Calcula precio unitario con la promo
                                precio_a_cobrar = calcular_total_pagar_escala(1, rifa_config)
                                
                                clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                                opc_cli = {f"{c[1]} | {c[2] or 'S/C'}": c[0] for c in clientes} if clientes else {}
                                nom_sel = st.selectbox("👤 Cliente:", options=list(opc_cli.keys()), index=None)
                                
                                c_ab, c_pr = st.columns(2)
                                abono = c_ab.number_input("Abono Inicial ($)", value=0.0) 
                                c_pr.metric("Precio Unitario", f"${precio_a_cobrar:,.2f}")
                                
                                if st.form_submit_button("💾 ASIGNAR", use_container_width=True):
                                    if nom_sel:
                                        cid = opc_cli[nom_sel]
                                        est = 'pagado' if abono >= precio_a_cobrar else 'abonado'
                                        if abono == 0: est = 'apartado'
                                        run_query("INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion) VALUES (%s, %s, %s, %s, %s, %s, NOW())", (id_sorteo, numero, est, precio_a_cobrar, cid, abono), fetch=False)
                                        log_movimiento(id_sorteo, 'ASIGNACION', f"Boleto {str_num} - {nom_sel}", abono)
                                        st.success("✅ Asignado"); time.sleep(1); st.rerun()
                                    else: st.error("⚠️ Falta cliente")
                    
                    elif len(lista_busqueda) > 1:
                        ocupados = [n for n in lista_busqueda if n in mapa_resultados]
                        if ocupados:
                            ocup_fmt = [fmt_num.format(n) for n in ocupados]
                            st.error(f"❌ Ocupados: {ocup_fmt}")
                            st.info("Gestiona los boletos ocupados uno por uno.")
                        else:
                            lista_fmt = [fmt_num.format(n) for n in lista_busqueda]
                            st.success(f"🟢 {len(lista_busqueda)} boletos disponibles.")
                            
                            with st.form("venta_multi"):
                                st.write(f"### 📝 Asignar {len(lista_busqueda)} boletos")
                                
                                # 🔥 Calcula precio del paquete y unitario
                                cantidad_venta = len(lista_busqueda)
                                total_paquete = calcular_total_pagar_escala(cantidad_venta, rifa_config)
                                precio_unitario = total_paquete / cantidad_venta if cantidad_venta > 0 else 0
                                
                                clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                                opc_cli = {f"{c[1]} | {c[2] or 'S/C'}": c[0] for c in clientes} if clientes else {}
                                nom_sel = st.selectbox("👤 Cliente:", options=list(opc_cli.keys()), index=None)
                                
                                st.divider()
                                c_ab, c_pr = st.columns(2)
                                # Ahora pedimos el abono total, es más fácil para el usuario
                                abono_total = c_ab.number_input("Abono TOTAL ($)", value=0.0, min_value=0.0, max_value=float(total_paquete), step=1.0)
                                c_pr.metric("Total a Pagar (Promo)", f"${total_paquete:,.2f}")
                                
                                if st.form_submit_button("💾 ASIGNAR TODOS", use_container_width=True):
                                    if nom_sel:
                                        cid = opc_cli[nom_sel]
                                        abono_unitario = abono_total / cantidad_venta if cantidad_venta > 0 else 0
                                        est = 'pagado' if abono_total >= total_paquete else 'abonado'
                                        if abono_total == 0: est = 'apartado'
                                        
                                        for n_bol in lista_busqueda:
                                            run_query("INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion) VALUES (%s, %s, %s, %s, %s, %s, NOW())", (id_sorteo, n_bol, est, precio_unitario, cid, abono_unitario), fetch=False)
                                        
                                        log_movimiento(id_sorteo, 'ASIGNACION_MASIVA', f"{cantidad_venta} Boletos - {nom_sel}", abono_total)
                                        st.success("✅ Asignados"); time.sleep(1); st.rerun()
                                    else: st.error("⚠️ Selecciona un cliente.")

        else:
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
                    
                    datos_cliente_map[c[0]] = {
                        'nombre': c[1], 
                        'telefono': c[2],
                        'cedula': c[3],
                        'direccion': c[4],
                        'codigo': c[5]
                    }
            
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

                    st.write("### 🎫 Estado Actual")
                    cols_info = st.columns(4) 
                    for i, b in enumerate(boletos_cli):
                        num, est = b[0], b[1]
                        
                        if est == 'abonado': bg = "#1a73e8"
                        elif est == 'apartado': bg = "#FFC107"
                        else: bg = "#9e9e9e"
                        
                        html_card = f"""
                        <div style="background-color: {bg}; border-radius: 10px; padding: 15px; text-align: center; margin-bottom: 15px; color: white; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);">
                            <div style="font-size: 24px; font-weight: bold; line-height: 1.2;">{fmt_num.format(num)}</div>
                            <div style="font-size: 14px; text-transform: uppercase; margin-top: 5px; opacity: 0.9;">{est.upper()}</div>
                        </div>
                        """
                        with cols_info[i % 4]: st.markdown(html_card, unsafe_allow_html=True)
                    
                    st.divider()

                    st.write("### ✅ Toca para procesar:")
                    
                    if 'seleccion_actual' not in st.session_state: st.session_state.seleccion_actual = []
                    if 'cliente_previo' not in st.session_state or st.session_state.cliente_previo != cid:
                        st.session_state.seleccion_actual = [] 
                        st.session_state.cliente_previo = cid

                    todos_nums = [b[0] for b in boletos_cli]
                    c_todos, c_nada = st.columns(2)
                    if c_todos.button("✅ Marcar Todos", use_container_width=True, key="btn_all"):
                        st.session_state.seleccion_actual = list(todos_nums)
                        st.rerun()
                        
                    if c_nada.button("🗑️ Desmarcar Todo", use_container_width=True, key="btn_none"):
                        st.session_state.seleccion_actual = []
                        st.rerun()

                    # --- NUEVO: SELECCIÓN RÁPIDA POR NÚMEROS ---
                    st.caption("✏️ **Selección rápida por N°:**")
                    c_inp, c_sel = st.columns([3, 1])
                    # Agregamos key=f"quick_{cid}" para que se limpie sola al cambiar de cliente
                    nums_escritos = c_inp.text_input("Ej: 01, 03, 05", label_visibility="collapsed", key=f"quick_{cid}")
                    
                    if c_sel.button("Aplicar", use_container_width=True):
                        if nums_escritos:
                            # Reemplazamos comas y guiones por espacios para separar fácil
                            texto_limpio = nums_escritos.replace(',', ' ').replace('-', ' ')
                            nuevos_sel = []
                            for p in texto_limpio.split():
                                if p.strip().isdigit():
                                    val = int(p.strip())
                                    # Si el número pertenece a este cliente, lo seleccionamos
                                    if val in todos_nums:
                                        nuevos_sel.append(val)
                            
                            # Actualizamos la selección con los números encontrados
                            st.session_state.seleccion_actual = nuevos_sel
                            st.rerun()
                    # -------------------------------------------

                    cols_sel = st.columns(5)
                    datos_boletos_map = {} 

                    for i, b in enumerate(boletos_cli):
                        num, est, pre, abo, f_asig = b
                        datos_boletos_map[num] = {'numero': num, 'estado': est, 'precio': pre, 'abonado': abo, 'fecha': f_asig}
                        
                        es_seleccionado = num in st.session_state.seleccion_actual
                        str_btn = fmt_num.format(num)
                        label_btn = f"✔ {str_btn}" if es_seleccionado else f"{str_btn}"
                        type_btn = "primary" if es_seleccionado else "secondary"
                        
                        with cols_sel[i % 5]:
                            def on_click_btn(n=num):
                                if n in st.session_state.seleccion_actual: st.session_state.seleccion_actual.remove(n)
                                else: st.session_state.seleccion_actual.append(n)

                            st.button(label_btn, key=f"btn_sel_{num}", type=type_btn, on_click=on_click_btn, use_container_width=True)

                    numeros_sel = sorted(st.session_state.seleccion_actual)
                    datos_sel = [datos_boletos_map[n] for n in numeros_sel]

                    st.divider()

                    if len(numeros_sel) == 1:
                        dato_unico = datos_sel[0]
                        deuda = dato_unico['precio'] - dato_unico['abonado']
                        if deuda > 0.01: 
                            with st.container(border=True):
                                st.write(f"💸 **Abonar: {fmt_num.format(dato_unico['numero'])}** (Deuda: ${deuda:.2f})")
                                c1, c2 = st.columns([2,1])
                                m = c1.number_input("Monto:", 0.0, deuda, step=1.0, label_visibility="collapsed")
                                if c2.button("GUARDAR", use_container_width=True) and m > 0:
                                    nt = dato_unico['abonado'] + m
                                    ne = 'pagado' if (dato_unico['precio'] - nt) <= 0.01 else 'abonado'
                                    run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE sorteo_id=%s AND numero=%s", (nt, ne, id_sorteo, dato_unico['numero']), fetch=False)
                                    log_movimiento(id_sorteo, 'ABONO', f"Boleto {fmt_num.format(dato_unico['numero'])} - {datos_c['nombre']}", m)
                                    st.session_state.seleccion_actual = []; st.rerun()

                    if numeros_sel:
                        c_acc1, c_acc2, c_acc3 = st.columns(3)
                        show_pagar = any(d['estado'] != 'pagado' for d in datos_sel)
                        show_apartar = any(d['estado'] != 'apartado' for d in datos_sel)
                        
                        if show_pagar:
                            if c_acc1.button("✅ PAGAR", use_container_width=True):
                                for d in datos_sel:
                                    run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE sorteo_id=%s AND numero=%s", (d['precio'], id_sorteo, d['numero']), fetch=False)
                                    log_movimiento(id_sorteo, 'PAGO_COMPLETO', f"Boleto {fmt_num.format(d['numero'])} - {datos_c['nombre']}", d['precio'])
                                st.session_state.seleccion_actual = []; st.success("Pagado"); time.sleep(1); st.rerun()
                        
                        if show_apartar:
                            if c_acc2.button("📌 APARTAR", use_container_width=True):
                                for d in datos_sel:
                                    run_query("UPDATE boletos SET estado='apartado', total_abonado=0 WHERE sorteo_id=%s AND numero=%s", (id_sorteo, d['numero']), fetch=False)
                                    log_movimiento(id_sorteo, 'REVERTIR_APARTADO', f"Boleto {fmt_num.format(d['numero'])} - {datos_c['nombre']}", 0)
                                st.session_state.seleccion_actual = []; st.success("Apartado"); time.sleep(1); st.rerun()

                        if c_acc3.button("🗑️ LIBERAR", type="primary", use_container_width=True):
                            for d in datos_sel:
                                run_query("DELETE FROM boletos WHERE sorteo_id=%s AND numero=%s", (id_sorteo, d['numero']), fetch=False)
                                log_movimiento(id_sorteo, 'LIBERACION', f"Boleto {fmt_num.format(d['numero'])} - {datos_c['nombre']}", 0)
                            st.session_state.seleccion_actual = []; st.warning("Liberados"); time.sleep(1); st.rerun()
                    
                    st.divider()
                    
                    col_pdf, col_wa = st.columns([1, 1])
                    
                    if numeros_sel:
                        partes_nom = datos_c['nombre'].strip().upper().split()
                        if len(partes_nom) >= 3: nom_archivo_cli = f"{partes_nom[0]}_{partes_nom[2]}"
                        elif len(partes_nom) == 2: nom_archivo_cli = f"{partes_nom[0]}_{partes_nom[1]}"
                        else: nom_archivo_cli = partes_nom[0] if partes_nom else "CLIENTE"

                        partes_msg = [f"N° {fmt_num.format(d['numero'])} ({d['estado'].upper()})" for d in datos_sel]
                        txt_boletos = ", ".join(partes_msg)
                        tipo_txt = "los comprobantes de tus BOLETOS" if len(numeros_sel) > 1 else "el comprobante de tu BOLETO"
                        
                        msg_wa = (
                            f"Hola. Saludos, somos Sorteos Milán!!, aquí te enviamos {tipo_txt}: "
                            f"{txt_boletos}, a nombre de {datos_c['nombre']} para el sorteo "
                            f"'{nombre_s}' del día {fecha_s} a las {hora_s}. ¡Suerte!🍀"
                        )

                        with col_pdf:
                            st.write("**Descargar PDFs:**")
                            for d in datos_sel:
                                info_pdf = {
                                    'cliente': datos_c['nombre'], 'cedula': datos_c['cedula'], 
                                    'telefono': datos_c['telefono'], 'direccion': datos_c['direccion'], 
                                    'codigo_cli': datos_c['codigo'], 'estado': d['estado'], 
                                    'precio': d['precio'], 'abonado': d['abonado'], 
                                    'fecha_asignacion': d['fecha']
                                }
                                pdf_data = generar_pdf_memoria(d['numero'], info_pdf, config_full, cantidad_boletos)
                                n_file = f"{fmt_num.format(d['numero'])} {nom_archivo_cli} ({d['estado'].upper()}).pdf"
                                st.download_button(f"📄 {fmt_num.format(d['numero'])}", pdf_data, n_file, "application/pdf", key=f"d_{d['numero']}", use_container_width=True)

                        with col_wa:
                            st.write("**Enviar:**")
                            tel_raw = datos_c['telefono']
                            tel_clean = "".join(filter(str.isdigit, str(tel_raw or "")))
                            
                            if len(tel_clean) == 10: tel_final = "58" + tel_clean
                            elif len(tel_clean) == 11 and tel_clean.startswith("0"): tel_final = "58" + tel_clean[1:]
                            else: tel_final = tel_clean
                            
                            if len(tel_final) >= 7:
                                link_wa = f"https://wa.me/{tel_final}?text={urllib.parse.quote(msg_wa)}"
                                st.link_button("📲 WhatsApp", link_wa, use_container_width=True)
                            else:
                                st.warning(f"Tel Inválido: {tel_raw}")
                    else:
                        col_pdf.info("Selecciona para ver PDFs")
                        col_wa.button("📲 WhatsApp", disabled=True, use_container_width=True)
                        
    # ---------------- PESTAÑA CLIENTES ----------------
    with tab_clientes:
        st.header("Gestión Clientes")
        
        if 'edit_id' in st.session_state:
            id_e = st.session_state.edit_id
            vals = st.session_state.edit_vals 
            
            st.info(f"✏️ Editando a: **{vals[1]}**")
            
            with st.form("edit_cli_form"):
                en = st.text_input("Nombre", value=vals[1]).upper()
                
                ced_parts = vals[2].split('-') if vals[2] and '-' in vals[2] else ["V", vals[2]]
                pre_tipo = ced_parts[0] if ced_parts[0] in ["V", "E"] else "V"
                pre_num = ced_parts[1] if len(ced_parts) > 1 else vals[2]
                
                c_tipo, c_ced = st.columns([1, 3])
                tipo_doc = c_tipo.selectbox("Tipo", ["V", "E"], index=["V", "E"].index(pre_tipo))
                ced_num = c_ced.text_input("Cédula", value=pre_num)
                
                et = st.text_input("Teléfono", value=vals[3])
                ed = st.text_input("Dirección", value=vals[4])
                
                c_guardar, c_cancelar = st.columns(2)
                
                if c_guardar.form_submit_button("💾 Guardar Cambios", use_container_width=True):
                    cedula_final = f"{tipo_doc}-{ced_num}"
                    run_query("UPDATE clientes SET nombre_completo=%s, cedula=%s, telefono=%s, direccion=%s WHERE id=%s", 
                             (en, cedula_final, et, ed, id_e), fetch=False)
                    del st.session_state.edit_id
                    del st.session_state.edit_vals
                    st.success("✅ Cliente Actualizado")
                    time.sleep(1)
                    st.rerun()
                    
                if c_cancelar.form_submit_button("❌ Cancelar Edición", use_container_width=True):
                    del st.session_state.edit_id
                    del st.session_state.edit_vals
                    st.rerun()
            
            st.divider()
            
        else:
            with st.expander("➕ Nuevo Cliente", expanded=False):
                with st.form("new_cli"):
                    st.write("📝 **Datos del Cliente**")
                    nn = st.text_input("Nombre Completo").upper()
                    
                    c_tipo, c_ced = st.columns([1, 3])
                    tipo_doc = c_tipo.selectbox("Tipo", ["V", "E"], label_visibility="collapsed")
                    ced_num = c_ced.text_input("Cédula", placeholder="Ej: 12345678", label_visibility="collapsed")
                    
                    nt = st.text_input("Teléfono")
                    nd = st.text_input("Dirección")
                    
                    if st.form_submit_button("💾 Guardar Cliente", use_container_width=True):
                        if nn and ced_num and nt:
                            cedula_final = f"{tipo_doc}-{ced_num}"
                            
                            codigos_existentes = set()
                            rows = run_query("SELECT codigo FROM clientes")
                            if rows:
                                for r in rows:
                                    try: codigos_existentes.add(int(r[0]))
                                    except: pass
                            
                            nuevo_codigo = 1
                            while nuevo_codigo in codigos_existentes:
                                nuevo_codigo += 1
                            cod_final = f"{nuevo_codigo:06d}"
                            
                            run_query("""
                                INSERT INTO clientes (codigo, nombre_completo, cedula, telefono, direccion, fecha_registro) 
                                VALUES (%s, %s, %s, %s, %s, NOW())
                            """, (cod_final, nn, cedula_final, nt, nd), fetch=False)
                            
                            st.success(f"✅ Registrado: {cod_final}")
                            time.sleep(1.5)
                            st.rerun()
                        else:
                            st.error("⚠️ Faltan datos")

        st.write("### 📋 Lista de Clientes")
        q = st.text_input("🔍 Buscar cliente (Nombre o Cédula)...", key="search_cli")
        sql = "SELECT id, nombre_completo, cedula, telefono, direccion, codigo FROM clientes"
        
        if q: 
            sql += " WHERE nombre_completo ILIKE %s OR cedula ILIKE %s"
            sql += " ORDER BY id DESC LIMIT 15"
            res = run_query(sql, (f"%{q}%", f"%{q}%"))
        else:
            sql += " ORDER BY id DESC LIMIT 15"
            res = run_query(sql)
        
        if res:
            for c in res:
                with st.container(border=True):
                    c1, c2 = st.columns([3,1])
                    with c1:
                        st.markdown(f"<b>{c[1]}</b>", unsafe_allow_html=True)
                        st.caption(f"🆔 {c[2]} | 🔑 Cód: {c[5]}")
                        st.caption(f"📞 {c[3]} | 📍 {c[4]}")
                    with c2:
                        if st.button("✏️", key=f"edit_{c[0]}", use_container_width=True):
                            st.session_state.edit_id = c[0]
                            st.session_state.edit_vals = c
                            st.rerun()

# ---------------- PESTAÑA COBRANZA ----------------
    with tab_cobranza:
        st.header("📊 Gestión de Cobranza")
        
        if st.button("🔄 Actualizar Datos", use_container_width=True):
            st.rerun()

        st.write("---")
        
        sql_estado = """
            SELECT 
                b.numero as "Número", 
                c.nombre_completo as "Cliente", 
                c.telefono as "Teléfono", 
                c.cedula as "Cédula",
                UPPER(b.estado) as "Estado", 
                b.precio as "Precio ($)", 
                b.total_abonado as "Abonado ($)", 
                (b.precio - b.total_abonado) as "Saldo Pendiente ($)",
                b.fecha_asignacion as "Fecha Asignación"
            FROM boletos b
            JOIN clientes c ON b.cliente_id = c.id
            WHERE b.sorteo_id = %s
            ORDER BY b.numero ASC
        """
        rows_estado = run_query(sql_estado, (id_sorteo,))

        sql_hist = """
            SELECT 
                fecha_hora,
                usuario, 
                accion, 
                detalle, 
                monto
            FROM historial 
            WHERE sorteo_id = %s 
            ORDER BY id ASC
        """
        rows_hist = run_query(sql_hist, (id_sorteo,))

        buffer = io.BytesIO()
        hay_datos = False
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            
            if rows_estado:
                df_estado = pd.DataFrame(rows_estado, columns=["Número", "Cliente", "Teléfono", "Cédula", "Estado", "Precio ($)", "Abonado ($)", "Saldo Pendiente ($)", "Fecha Asignación"])
                try: df_estado["Fecha Asignación"] = pd.to_datetime(df_estado["Fecha Asignación"]).dt.strftime('%d/%m/%Y')
                except: pass
                
                df_estado.to_excel(writer, index=False, sheet_name='Estado General')
                hay_datos = True
            else:
                pd.DataFrame(columns=["Mensaje"]).to_excel(writer, sheet_name='Estado General', index=False)

            if rows_hist:
                df_hist = pd.DataFrame(rows_hist, columns=["FechaRaw", "Usuario", "Acción", "Detalle", "MontoRaw"])
                df_hist.insert(0, "Nro. Transacción", range(1, len(df_hist) + 1))
                
                try:
                    df_hist["FechaRaw"] = pd.to_datetime(df_hist["FechaRaw"]) - pd.Timedelta(hours=4)
                    df_hist["Fecha"] = df_hist["FechaRaw"].dt.strftime('%d/%m/%Y')
                    df_hist["Hora"] = df_hist["FechaRaw"].dt.strftime('%I:%M %p') 
                except:
                    df_hist["Fecha"] = df_hist["FechaRaw"].astype(str)
                    df_hist["Hora"] = ""

                def separar_detalle(texto):
                    boleto = texto
                    cliente = ""
                    if " - " in str(texto):
                        partes = str(texto).split(" - ", 1)
                        boleto = partes[0].strip() 
                        resto = partes[1].strip()  
                        if " | " in resto:
                            cliente = resto.split(" | ")[0].strip()
                        else:
                            cliente = resto
                    return pd.Series([boleto, cliente])

                df_hist[["Boletos", "Cliente"]] = df_hist["Detalle"].apply(separar_detalle)
                df_hist["Monto ($)"] = df_hist["MontoRaw"].apply(lambda x: "{:.2f}".format(float(x) if x else 0.0))
                
                cols_finales = ["Nro. Transacción", "Fecha", "Hora", "Usuario", "Acción", "Boletos", "Cliente", "Monto ($)"]
                df_export = df_hist[cols_finales]
                
                df_export.to_excel(writer, index=False, sheet_name='Historial Movimientos')
                
                worksheet = writer.sheets['Historial Movimientos']
                worksheet.set_column('A:A', 10) 
                worksheet.set_column('B:C', 12) 
                worksheet.set_column('F:F', 15) 
                worksheet.set_column('G:G', 40) 
                
                hay_datos = True
        
        if hay_datos:
            st.download_button(
                label="📥 DESCARGAR REPORTE COMPLETO (Excel)",
                data=buffer,
                file_name=f"Reporte_Total_{nombre_s}.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True,
                type="primary"
            )
        else:
            st.info("No hay información para generar reporte.")

        st.divider()
            
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
            st.success("✅ ¡Cero Deudas! Todos están al día.")
        else:
            grupos = {}
            for row in raw_deudores:
                nom, tel, num, prec, abon = row
                prec = float(prec or 0); abon = float(abon or 0)
                deuda = prec - abon
                clave = f"{nom}|{tel}"
                if clave not in grupos:
                    grupos[clave] = {'nombre': nom, 'tel': tel, 'numeros': [], 't_deuda': 0.0}
                grupos[clave]['numeros'].append(num)
                grupos[clave]['t_deuda'] += deuda

            gran_total = sum(g['t_deuda'] for g in grupos.values())
            st.metric("Total por Cobrar", f"${gran_total:,.2f}", f"{len(grupos)} Clientes con deuda")
            
            st.write("---")

            fmt_num = "{:02d}" if cantidad_boletos <= 100 else "{:03d}"
            
            for clave, d in grupos.items():
                nom = d['nombre']
                tel = d['tel']
                lista_nums = sorted(d['numeros'])
                str_numeros = ", ".join([fmt_num.format(n) for n in lista_nums])
                
                with st.container(border=True):
                    c_info, c_btn = st.columns([2, 1])
                    with c_info:
                        # Se agrega .strip() para evitar error de los asteriscos **
                        st.markdown(f"👤 **{nom.strip()}**")
                        st.caption(f"🎟️ Boletos: **{str_numeros}**")
                        st.write(f"🔴 Deuda: :red[**${d['t_deuda']:,.2f}**]")
                    with c_btn:
                        if tel and len(str(tel)) > 5:
                            tel_clean = "".join(filter(str.isdigit, str(tel)))
                            if len(tel_clean) == 10: tel_clean = "58" + tel_clean
                            elif len(tel_clean) == 11 and tel_clean.startswith("0"): tel_clean = "58" + tel_clean[1:]
                            
                            txt_concepto = "de tus boletos" if len(lista_nums) > 1 else "de tu boleto"
                            
                            # Generamos la fecha inteligente
                            txt_fecha = formato_fecha_inteligente(fecha_s)
                            
                            # MENSAJE DE COBRANZA INTELIGENTE
                            msg = (f"Hola {nom.strip()}, saludos de Sorteos Milán. "
                                   f"Te recordamos amablemente que tienes un saldo pendiente de ${d['t_deuda']:.2f} "
                                   f"{txt_concepto}: {str_numeros}, para el sorteo {txt_fecha} a las {hora_s}. "
                                   f"Agradecemos tu pago. ¡Gracias! 🍀")
                            
                            link = f"https://wa.me/{tel_clean}?text={urllib.parse.quote(msg)}"
                            
                            st.link_button("📲 Cobrar", link, use_container_width=True)
                            
# ============================================================================
#  PUNTO DE ENTRADA (CON LOGIN Y TIMEOUT)
# ============================================================================
if __name__ == "__main__":
    if check_password():
        if verificar_inactividad():
            main()

