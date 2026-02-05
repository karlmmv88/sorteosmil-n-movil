import streamlit as st
import psycopg2
import io
import os
import time
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

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
#  FUNCIONES AUXILIARES
# ============================================================================
def generar_pdf_memoria(numero_boleto, datos_completos, config_db):
    buffer = io.BytesIO()
    rifa = config_db['rifa']
    empresa = config_db['empresa']
    
    # Datos
    num_str = f"{numero_boleto:03d}"
    nom_cli = datos_completos.get('cliente', '')
    cedula = datos_completos.get('cedula', '')
    tel = datos_completos.get('telefono', '')
    estado_fmt = datos_completos.get('estado', '').upper()
    precio = float(datos_completos.get('precio', 0))
    abonado = float(datos_completos.get('abonado', 0))
    saldo = precio - abonado
    fecha_asig = datos_completos.get('fecha_asignacion', '')

    # Calculo Altura
    lista_claves = ["premio1", "premio2", "premio3", "premio_extra1", "premio_extra2"]
    count_premios = sum(1 for k in lista_claves if rifa.get(k))
    total_h = 390 + max(0, (count_premios - 3) * 20)
    total_w = 390
    
    c = canvas.Canvas(buffer, pagesize=(total_w, total_h))
    m_izq, m_der = 30, total_w - 30
    centro = total_w / 2
    y = total_h - 30
    
    # 1. LOGO (Búsqueda inteligente)
    logo_files = ["logo.jpg", "logo.png", "logo.jpeg", "logo_empresa.jpg"]
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
    c.setFillColorRGB(0.70, 0.55, 0.35) # Dorado
    c.drawRightString(m_der, y-5, f"BOLETO N° {num_str}")
    c.setFillColorRGB(0,0,0)
    
    y -= 35; c.setStrokeColorRGB(0.70, 0.55, 0.35); c.line(m_izq, y, m_der, y)
    y -= 18; c.setFont("Helvetica-Bold", 15); c.drawCentredString(centro, y, "COMPROBANTE DIGITAL")
    y -= 8; c.line(m_izq, y, m_der, y)
    
    # Datos Sorteo
    y -= 20
    c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "SORTEO:")
    c.drawString(m_izq + 50, y, rifa['nombre'][:35])
    y -= 15
    c.drawString(m_izq, y, "FECHA:")
    c.drawString(m_izq + 50, y, f"{rifa.get('fecha_sorteo','')} {rifa.get('hora_sorteo','')}")
    
    # Premios
    y_prem = y + 15; col_der_x = centro + 20
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
    y = min(y, y_prem) - 20
    c.line(m_izq, y, m_der, y); y -= 20
    c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "CLIENTE:")
    y -= 15; c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Nombre: {nom_cli}")
    y -= 12; c.drawString(m_izq, y, f"Cédula: {cedula} - Tel: {tel}")
    
    # Pagos
    y -= 25; c.setFont("Helvetica-Bold", 10); c.drawString(m_izq, y, "PAGOS:")
    y -= 15; c.setFont("Helvetica", 9)
    c.drawString(m_izq, y, f"Precio: ${precio:,.2f}  |  Abonado: ${abonado:,.2f}")
    y -= 15
    if saldo <= 0:
        c.setFillColorRGB(0, 0.5, 0); c.setFont("Helvetica-Bold", 10)
        c.drawString(m_izq, y, "SALDO: PAGADO")
    else:
        c.setFillColorRGB(0.8, 0, 0); c.setFont("Helvetica-Bold", 10)
        c.drawString(m_izq, y, f"RESTA: ${saldo:,.2f}")
    
    # Estado Grande
    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(col_der_x + 40, y + 25, estado_fmt)
    
    # Footer
    c.setFont("Helvetica", 7); c.setFillColorRGB(0.5,0.5,0.5)
    c.drawCentredString(centro, 15, "Generado desde App Móvil - Sorteos Milán")
    
    c.save()
    buffer.seek(0)
    return buffer

def get_whatsapp_link(telefono, mensaje):
    if not telefono: return ""
    tel_clean = "".join(filter(str.isdigit, str(telefono)))
    if not tel_clean.startswith("58"): tel_clean = "58" + tel_clean
    return f"https://wa.me/{tel_clean}?text={mensaje.replace(' ', '%20')}"

# ============================================================================
#  INTERFAZ PRINCIPAL
# ============================================================================
def main():
    st.title("📱 Sorteos Milán")

    # 1. CARGAR CONFIGURACIÓN
    sorteos = run_query("SELECT id, nombre, precio_boleto, fecha_sorteo, hora_sorteo, premio1, premio2, premio3, premio_extra1, premio_extra2 FROM sorteos WHERE activo = TRUE")
    config_rows = run_query("SELECT clave, valor FROM configuracion")
    
    if not sorteos:
        st.warning("No hay sorteos activos."); return

    # Config Empresa
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
    
    # Config Rifa para PDF
    rifa_config = {
        "nombre": nombre_s, "fecha_sorteo": str(fecha_s), "hora_sorteo": str(s_data[4]),
        "premio1": s_data[5], "premio2": s_data[6], "premio3": s_data[7], "premio_extra1": s_data[8], "premio_extra2": s_data[9]
    }
    
    # --- PESTAÑAS ---
    tab_venta, tab_clientes = st.tabs(["🎫 VENTA Y GESTIÓN", "👥 CLIENTES"])

    # ========================================================================
    #  PESTAÑA 1: VENTA Y GESTIÓN DE BOLETOS
    # ========================================================================
    with tab_venta:
        col1, col2 = st.columns([2, 1])
        numero = col1.number_input("Número de Boleto:", min_value=0, max_value=9999, step=1)
        
        if col2.button("🔍 Buscar", use_container_width=True):
            pass # Solo recarga

        # Buscar Info Boleto
        boleto_info = run_query("""
            SELECT b.id, b.estado, b.precio, b.total_abonado, b.fecha_asignacion,
                   c.nombre_completo, c.telefono, c.cedula, c.direccion, c.codigo, c.id
            FROM boletos b
            LEFT JOIN clientes c ON b.cliente_id = c.id
            WHERE b.numero = %s AND b.sorteo_id = %s
        """, (numero, id_sorteo))

        if boleto_info:
            # --- BOLETO OCUPADO ---
            b_id, estado, b_precio, b_abonado, b_fecha, c_nom, c_tel, c_ced, c_dir, c_cod, c_id = boleto_info[0]
            b_precio = float(b_precio); b_abonado = float(b_abonado)
            deuda = b_precio - b_abonado

            # Tarjeta de Info
            st.info(f"👤 **{c_nom}** | 📞 {c_tel}")
            
            # Estado Visual
            cols_est = st.columns(3)
            if estado == 'pagado':
                cols_est[0].success("✅ PAGADO")
            elif estado == 'apartado':
                cols_est[0].warning("🟡 APARTADO")
            else:
                cols_est[0].info("🔵 ABONADO")
            
            cols_est[1].metric("Precio", f"${b_precio:.2f}")
            cols_est[2].metric("Deuda", f"${deuda:.2f}", delta_color="inverse")

            # --- ACCIONES ---
            with st.expander("🛠️ Opciones de Gestión", expanded=True):
                
                # 1. ABONAR
                if deuda > 0:
                    c_abo1, c_abo2 = st.columns([2,1])
                    monto_abono = c_abo1.number_input("Monto a Abonar ($)", min_value=0.0, max_value=deuda, value=deuda)
                    if c_abo2.button("💸 Abonar"):
                        nuevo_total = b_abonado + monto_abono
                        nuevo_est = 'pagado' if (b_precio - nuevo_total) <= 0.01 else 'abonado'
                        run_query("UPDATE boletos SET total_abonado=%s, estado=%s WHERE id=%s", (nuevo_total, nuevo_est, b_id), fetch=False)
                        run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) VALUES (%s, 'MOVIL', 'ABONO', %s, %s)", (id_sorteo, f"Abono boleto {numero}", monto_abono), fetch=False)
                        st.success("Abono registrado!"); time.sleep(1); st.rerun()

                # 2. BOTONES RÁPIDOS
                c_btn1, c_btn2 = st.columns(2)
                if estado != 'pagado' and c_btn1.button("✅ MARCAR PAGADO"):
                    run_query("UPDATE boletos SET estado='pagado', total_abonado=%s WHERE id=%s", (b_precio, b_id), fetch=False)
                    run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'PAGO_COMPLETO', %s)", (id_sorteo, f"Pago total boleto {numero}"), fetch=False)
                    st.rerun()
                
                if c_btn2.button("🗑️ LIBERAR (BORRAR)"):
                    run_query("DELETE FROM boletos WHERE id=%s", (b_id,), fetch=False)
                    run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle) VALUES (%s, 'MOVIL', 'LIBERAR', %s)", (id_sorteo, f"Liberado boleto {numero}"), fetch=False)
                    st.warning("Boleto liberado."); time.sleep(1); st.rerun()

            # --- COMPARTIR ---
            st.divider()
            
            # Generar PDF en Memoria
            datos_pdf = {'cliente': c_nom, 'cedula': c_ced, 'telefono': c_tel, 'estado': estado, 'precio': b_precio, 'abonado': b_abonado}
            config_full = {'rifa': rifa_config, 'empresa': empresa_config}
            pdf_bytes = generar_pdf_memoria(numero, datos_pdf, config_full)
            
            c_share1, c_share2 = st.columns(2)
            
            c_share1.download_button(
                label="📄 Descargar PDF",
                data=pdf_bytes,
                file_name=f"Boleto_{numero}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            
            link_wa = get_whatsapp_link(c_tel, f"Hola {c_nom}, aquí tienes tu boleto N° {numero} para el sorteo {nombre_s}. Estado: {estado.upper()}.")
            c_share2.link_button("📲 Enviar WhatsApp", link_wa, use_container_width=True)

        else:
            # --- BOLETO DISPONIBLE ---
            st.success(f"El boleto {numero} está DISPONIBLE")
            
            with st.form("form_asignar"):
                st.write("### Asignar Cliente")
                
                # Cargar Clientes para Selectbox
                clientes = run_query("SELECT id, nombre_completo, codigo FROM clientes ORDER BY nombre_completo")
                opciones_cli = {f"{c[1]} ({c[2]})": c[0] for c in clientes} if clientes else {}
                
                cli_selec = st.selectbox("Seleccionar Cliente Existente:", list(opciones_cli.keys()), index=None, placeholder="Escribe para buscar...")
                
                st.write("---")
                abono_ini = st.number_input("Abono Inicial ($)", value=precio_s, min_value=0.0)
                
                if st.form_submit_button("💾 ASIGNAR BOLETO"):
                    if not cli_selec:
                        st.error("Debes seleccionar un cliente (o crea uno en la pestaña Clientes).")
                    else:
                        cli_id = opciones_cli[cli_selec]
                        est_final = 'pagado' if abono_ini >= precio_s else 'abonado'
                        if abono_ini == 0: est_final = 'apartado'
                        
                        run_query("""
                            INSERT INTO boletos (sorteo_id, numero, estado, precio, cliente_id, total_abonado, fecha_asignacion)
                            VALUES (%s, %s, %s, %s, %s, %s, NOW())
                        """, (id_sorteo, numero, est_final, precio_s, cli_id, abono_ini), fetch=False)
                        
                        # Historial (Importante para sincronización PC)
                        run_query("INSERT INTO historial (sorteo_id, usuario, accion, detalle, monto) VALUES (%s, 'MOVIL', 'VENTA', %s, %s)", (id_sorteo, f"Venta boleto {numero}", abono_ini), fetch=False)
                        
                        st.success("¡Venta Registrada!"); time.sleep(1); st.rerun()

    # ========================================================================
    #  PESTAÑA 2: GESTIÓN DE CLIENTES
    # ========================================================================
    with tab_clientes:
        st.header("👥 Base de Datos de Clientes")
        
        with st.expander("➕ REGISTRAR NUEVO CLIENTE", expanded=False):
            with st.form("nuevo_cliente"):
                nc_nom = st.text_input("Nombre Completo").upper()
                c1, c2 = st.columns(2)
                nc_ced = c1.text_input("Cédula (V-123456)")
                nc_tel = c2.text_input("Teléfono (04XX...)")
                nc_dir = st.text_input("Dirección (Opcional)")
                
                if st.form_submit_button("Guardar Cliente"):
                    if not nc_nom or not nc_tel:
                        st.error("Nombre y Teléfono obligatorios")
                    else:
                        # Generar Codigo
                        cod = datetime.now().strftime("%H%M%S")
                        run_query("""
                            INSERT INTO clientes (codigo, nombre_completo, cedula, telefono, direccion, fecha_registro)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                        """, (cod, nc_nom, nc_ced, nc_tel, nc_dir), fetch=False)
                        st.success(f"Cliente {nc_nom} guardado."); time.sleep(1); st.rerun()

        # LISTA Y BÚSQUEDA
        busq_cli = st.text_input("🔍 Buscar Cliente (Nombre o Cédula):")
        
        query_cli = "SELECT id, nombre_completo, cedula, telefono FROM clientes"
        params_cli = None
        if busq_cli:
            query_cli += " WHERE nombre_completo ILIKE %s OR cedula ILIKE %s"
            params_cli = (f"%{busq_cli}%", f"%{busq_cli}%")
        query_cli += " ORDER BY id DESC LIMIT 50"
        
        res_cli = run_query(query_cli, params_cli)
        
        if res_cli:
            for c in res_cli:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"**{c[1]}**")
                    c1.text(f"🆔 {c[2]} | 📞 {c[3]}")
                    
                    if c2.button("Editar", key=f"edit_{c[0]}"):
                        st.session_state['edit_cli'] = c[0]
                        st.session_state['edit_nom'] = c[1]
                        st.session_state['edit_tel'] = c[3]
                        
            # MODAL EDITAR (Simulado)
            if 'edit_cli' in st.session_state:
                st.write("---")
                st.write(f"✏️ Editando ID: {st.session_state['edit_cli']}")
                new_n = st.text_input("Editar Nombre", value=st.session_state['edit_nom'])
                new_t = st.text_input("Editar Tel", value=st.session_state['edit_tel'])
                if st.button("Guardar Cambios"):
                    run_query("UPDATE clientes SET nombre_completo=%s, telefono=%s WHERE id=%s", 
                              (new_n, new_t, st.session_state['edit_cli']), fetch=False)
                    del st.session_state['edit_cli']
                    st.success("Editado."); st.rerun()
        else:
            st.info("No se encontraron clientes.")

if __name__ == "__main__":
    main()
