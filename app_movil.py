# ---------------------------------------------------------
                    #  A. PANEL INFORMATIVO (TARJETAS RELLENAS GRANDES)
                    # ---------------------------------------------------------
                    st.write("### 🎫 Estado Actual")
                    cols_info = st.columns(3) # 3 por fila para que sean grandes
                    
                    for i, b in enumerate(boletos_cli):
                        num, est, pre, abo, f_asig = b
                        
                        # Definir colores de FONDO
                        bg_color = "#9e9e9e" # Gris (Pagado/Default)
                        if est == 'abonado': bg_color = "#1a73e8" # Azul
                        elif est == 'apartado': bg_color = "#ff9800" # Naranja
                        elif est == 'pagado': bg_color = "#9e9e9e" # Gris
                        
                        # Renderizar tarjeta RELLENA con HTML/CSS
                        html_card = f"""
                        <div style="
                            background-color: {bg_color};
                            border-radius: 10px;
                            padding: 15px;
                            text-align: center;
                            margin-bottom: 15px;
                            color: white;
                            box-shadow: 2px 2px 5px rgba(0,0,0,0.2);
                        ">
                            <div style="font-size: 24px; font-weight: bold; line-height: 1.2;">
                                {fmt_num.format(num)}
                            </div>
                            <div style="font-size: 14px; text-transform: uppercase; margin-top: 5px; opacity: 0.9;">
                                {est}
                            </div>
                        </div>
                        """
                        with cols_info[i % 3]:
                            st.markdown(html_card, unsafe_allow_html=True)
                    
                    st.divider()
