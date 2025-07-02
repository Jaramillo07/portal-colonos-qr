import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import qrcode
from PIL import Image
import requests
import io
import os
import json
from datetime import datetime, time, date, timedelta
import logging
import hashlib
import hmac
import base64

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración global
CONFIG = {
    'SHEET_NAME': 'ControlAccesoQR',
    'CACHE_FILE': 'cache_colonos.csv',
    'HORARIO_INICIO': time(6, 0),  # 6:00 AM
    'HORARIO_FIN': time(23, 0),    # 11:00 PM
    'SESSION_DURATION_DAYS': 30,    # Sesión válida por 30 días
    'SECRET_KEY': 'PORTONDELOSGIRASOLES2025'
}

def get_mexico_date():
    """Obtiene la fecha actual en zona horaria de México (UTC-6)"""
    try:
        utc_now = datetime.utcnow()
        mexico_now = utc_now - timedelta(hours=6)
        return mexico_now.date()
    except Exception as e:
        logger.error(f"Error obteniendo fecha México: {e}")
        return date.today()

def get_google_credentials():
    """Obtiene las credenciales de Google desde Streamlit secrets o archivo local"""
    try:
        if hasattr(st, 'secrets') and 'google_sheets' in st.secrets:
            credentials_dict = dict(st.secrets['google_sheets'])
            return credentials_dict
        else:
            with open('credenciales_girasoles.json', 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error obteniendo credenciales: {e}")
        return None

# ============== SISTEMA DE SESIÓN AUTOMÁTICO PARA PWA ==============

def create_session_token(colono_name: str, colono_code: str) -> str:
    """Crea un token de sesión seguro"""
    try:
        expiry = datetime.now() + timedelta(days=CONFIG['SESSION_DURATION_DAYS'])
        expiry_str = expiry.strftime('%Y%m%d%H%M%S')
        
        token_data = f"{colono_name}|{colono_code}|{expiry_str}"
        signature = hmac.new(
            CONFIG['SECRET_KEY'].encode(),
            token_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        full_token = f"{token_data}|{signature}"
        token_bytes = base64.b64encode(full_token.encode()).decode()
        
        logger.info(f"Token creado para {colono_name}")
        return token_bytes
        
    except Exception as e:
        logger.error(f"Error creando token: {e}")
        return ""

def validate_session_token(token: str) -> tuple:
    """Valida un token de sesión"""
    try:
        if not token:
            return False, "", ""
        
        try:
            full_token = base64.b64decode(token).decode()
        except:
            return False, "", ""
        
        parts = full_token.split('|')
        if len(parts) != 4:
            return False, "", ""
        
        colono_name, colono_code, expiry_str, signature = parts
        
        token_data = f"{colono_name}|{colono_code}|{expiry_str}"
        expected_signature = hmac.new(
            CONFIG['SECRET_KEY'].encode(),
            token_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return False, "", ""
        
        try:
            expiry = datetime.strptime(expiry_str, '%Y%m%d%H%M%S')
            if datetime.now() > expiry:
                return False, "", ""
        except:
            return False, "", ""
        
        return True, colono_name, colono_code
        
    except Exception as e:
        logger.error(f"Error validando token: {e}")
        return False, "", ""

def auto_save_session(colono_name: str, colono_code: str):
    """Guarda automáticamente la sesión usando localStorage"""
    try:
        # Guardar en session_state
        st.session_state.authenticated = True
        st.session_state.colono_name = colono_name
        st.session_state.colono_code = colono_code
        st.session_state.login_time = datetime.now().isoformat()
        
        # Crear token
        token = create_session_token(colono_name, colono_code)
        
        if token:
            # JavaScript para guardar automáticamente en localStorage
            save_js = f"""
            <script>
            (function() {{
                try {{
                    // Guardar token en localStorage
                    localStorage.setItem('portal_colonos_token', '{token}');
                    localStorage.setItem('portal_colonos_user', '{colono_name}');
                    localStorage.setItem('portal_colonos_saved', 'true');
                    
                    // Marcar como guardado exitosamente
                    window.sessionSaved = true;
                    
                    console.log('✅ Sesión guardada automáticamente');
                }} catch(e) {{
                    console.error('Error guardando sesión:', e);
                    window.sessionSaved = false;
                }}
            }})();
            </script>
            """
            
            # Ejecutar JavaScript invisiblemente
            st.components.v1.html(save_js, height=0)
            
            logger.info(f"Sesión auto-guardada para {colono_name}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error auto-guardando sesión: {e}")
        return False

def auto_load_session():
    """Carga automáticamente la sesión desde localStorage"""
    try:
        # Si ya está autenticado, no hacer nada
        if st.session_state.get('authenticated', False):
            return True
        
        # JavaScript para cargar automáticamente desde localStorage
        load_js = """
        <script>
        (function() {
            try {
                const token = localStorage.getItem('portal_colonos_token');
                const user = localStorage.getItem('portal_colonos_user');
                
                if (token && user) {
                    // Enviar datos al componente padre usando postMessage
                    const message = {
                        type: 'auto_login',
                        token: token,
                        user: user
                    };
                    
                    // Enviar mensaje al padre
                    window.parent.postMessage(message, '*');
                    
                    console.log('🔄 Intentando auto-login para:', user);
                } else {
                    console.log('❌ No hay sesión guardada');
                }
            } catch(e) {
                console.error('Error cargando sesión:', e);
            }
        })();
        
        // Escuchar mensajes del iframe
        window.addEventListener('message', function(event) {
            if (event.data && event.data.type === 'auto_login') {
                // Aquí Streamlit recibiría los datos, pero necesitamos otro método
                console.log('Datos de auto-login recibidos');
            }
        });
        </script>
        """
        
        # Ejecutar JavaScript
        st.components.v1.html(load_js, height=0)
        
        # Como JavaScript no puede comunicarse directamente con Streamlit,
        # usamos un enfoque diferente: verificar en cada carga de página
        if 'check_auto_login' not in st.session_state:
            st.session_state.check_auto_login = True
            st.rerun()  # Recargar para activar el check
            
        return False
        
    except Exception as e:
        logger.error(f"Error auto-cargando sesión: {e}")
        return False

def clear_auto_session():
    """Limpia automáticamente la sesión"""
    try:
        # Limpiar session_state
        keys_to_clear = ['authenticated', 'colono_name', 'colono_code', 'qr_generated', 'qr_data', 
                        'peatonal_registered', 'peatonal_data', 'login_time', 'check_auto_login']
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        
        # JavaScript para limpiar localStorage
        clear_js = """
        <script>
        (function() {
            try {
                localStorage.removeItem('portal_colonos_token');
                localStorage.removeItem('portal_colonos_user');
                localStorage.removeItem('portal_colonos_saved');
                console.log('🗑️ Sesión limpiada automáticamente');
            } catch(e) {
                console.error('Error limpiando sesión:', e);
            }
        })();
        </script>
        """
        
        st.components.v1.html(clear_js, height=0)
        logger.info("Sesión auto-limpiada")
        
    except Exception as e:
        logger.error(f"Error limpiando sesión: {e}")

class GoogleSheetsManager:
    """Maneja la conexión y operaciones con Google Sheets"""
    
    def __init__(self, sheet_name: str):
        self.sheet_name = sheet_name
        self.client = None
        self.sheet = None
        self.connect()
    
    def connect(self) -> bool:
        """Conecta a Google Sheets"""
        try:
            credentials_dict = get_google_credentials()
            if not credentials_dict:
                raise Exception("No se pudieron obtener las credenciales")
            
            scope = ['https://spreadsheets.google.com/feeds',
                    'https://www.googleapis.com/auth/drive']
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(
                credentials_dict, scope)
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open(self.sheet_name).sheet1
            logger.info("Conectado a Google Sheets exitosamente")
            return True
        except Exception as e:
            logger.error(f"Error conectando a Google Sheets: {e}")
            return False
    
    def get_colonos_data(self) -> pd.DataFrame:
        """Obtiene datos de colonos desde Google Sheets"""
        try:
            if not self.sheet:
                raise Exception("No hay conexión a Google Sheets")
            
            records = self.sheet.get_all_records()
            df = pd.DataFrame(records)
            
            if not df.empty and 'tipo' in df.columns:
                colonos_df = df[df['tipo'].isin(['fijo', 'colono'])]
                required_cols = ['codigo_qr', 'tipo', 'colono', 'fecha_inicio', 'fecha_fin']
                for col in required_cols:
                    if col not in colonos_df.columns:
                        colonos_df[col] = ''
                return colonos_df[required_cols]
            else:
                return pd.DataFrame(columns=['codigo_qr', 'tipo', 'colono', 'fecha_inicio', 'fecha_fin'])
                
        except Exception as e:
            logger.error(f"Error obteniendo datos de colonos: {e}")
            return pd.DataFrame(columns=['codigo_qr', 'tipo', 'colono', 'fecha_inicio', 'fecha_fin'])
    
    def add_visita_qr(self, codigo_qr: str, colono: str, fecha_inicio: str, fecha_fin: str) -> bool:
        """Agrega un QR de visita temporal a Google Sheets"""
        try:
            if not self.sheet:
                raise Exception("No hay conexión a Google Sheets")
            
            self.sheet.append_row([codigo_qr, "visita", colono, fecha_inicio, fecha_fin])
            logger.info(f"QR visita {codigo_qr} agregado exitosamente para {colono}")
            return True
        except Exception as e:
            logger.error(f"Error agregando QR visita: {e}")
            return False
    
    def add_peatonal_visitor(self, nombre_visitante: str, colono: str, fecha_inicio: str, fecha_fin: str) -> bool:
        """Agrega un visitante peatonal a Google Sheets"""
        try:
            if not self.sheet:
                raise Exception("No hay conexión a Google Sheets")
            
            self.sheet.append_row([nombre_visitante, "peatonal", colono, fecha_inicio, fecha_fin])
            logger.info(f"Visitante peatonal {nombre_visitante} agregado exitosamente para {colono}")
            return True
        except Exception as e:
            logger.error(f"Error agregando visitante peatonal: {e}")
            return False

class CacheManager:
    """Maneja el cache local de códigos QR"""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
    
    def save_cache(self, df: pd.DataFrame) -> bool:
        """Guarda los datos en cache local"""
        try:
            df.to_csv(self.cache_file, index=False)
            logger.info(f"Cache guardado en {self.cache_file}")
            return True
        except Exception as e:
            logger.error(f"Error guardando cache: {e}")
            return False
    
    def load_cache(self) -> pd.DataFrame:
        """Carga los datos desde cache local"""
        try:
            if os.path.exists(self.cache_file):
                df = pd.read_csv(self.cache_file)
                logger.info(f"Cache cargado desde {self.cache_file}")
                return df
            else:
                logger.warning(f"Archivo de cache {self.cache_file} no existe")
                return pd.DataFrame(columns=['codigo_qr', 'tipo', 'colono', 'fecha_inicio', 'fecha_fin'])
        except Exception as e:
            logger.error(f"Error cargando cache: {e}")
            return pd.DataFrame(columns=['codigo_qr', 'tipo', 'colono', 'fecha_inicio', 'fecha_fin'])

class QRGenerator:
    """Genera códigos QR y imágenes"""
    
    @staticmethod
    def generate_qr_code(data: str):
        """Genera un código QR como imagen PIL"""
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            from PIL import Image
            if not isinstance(img, Image.Image):
                img = img.convert('RGB')
            
            logger.info(f"QR generado exitosamente para: {data}")
            return img
                
        except Exception as e:
            logger.error(f"Error generando QR: {e}")
            return None
    
    @staticmethod
    def qr_to_bytes(img):
        """Convierte imagen QR a bytes para descarga"""
        try:
            if img is None:
                logger.error("Imagen QR es None")
                return None
            
            from PIL import Image
            
            if not isinstance(img, Image.Image):
                logger.error(f"Objeto no es PIL Image: {type(img)}")
                return None
                
            buf = io.BytesIO()
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            img.save(buf, format='PNG')
            
            buf.seek(0)
            img_bytes = buf.getvalue()
            buf.close()
            
            logger.info(f"QR convertido a bytes exitosamente: {len(img_bytes)} bytes")
            return img_bytes
            
        except Exception as e:
            logger.error(f"Error convirtiendo QR a bytes: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

class AuthManager:
    """Maneja la autenticación de colonos"""
    
    def __init__(self, sheets_manager: GoogleSheetsManager, cache_manager: CacheManager):
        self.sheets_manager = sheets_manager
        self.cache_manager = cache_manager
        self.colonos_data = pd.DataFrame()
        self.update_colonos_data()
    
    def update_colonos_data(self) -> bool:
        """Actualiza los datos de colonos desde Sheets o cache"""
        try:
            df = self.sheets_manager.get_colonos_data()
            
            if not df.empty:
                self.colonos_data = df
                self.cache_manager.save_cache(df)
                logger.info("Datos de colonos actualizados desde Google Sheets")
                return True
            else:
                df = self.cache_manager.load_cache()
                if not df.empty:
                    self.colonos_data = df
                    logger.info("Datos de colonos cargados desde cache local")
                    return True
                else:
                    logger.error("No se pudieron cargar datos de colonos")
                    return False
                    
        except Exception as e:
            logger.error(f"Error actualizando datos de colonos: {e}")
            df = self.cache_manager.load_cache()
            if not df.empty:
                self.colonos_data = df
                return True
            return False
    
    def authenticate_colono(self, nombre_colono: str, codigo_qr: str) -> tuple:
        """Autentica un colono con su nombre y código QR"""
        try:
            if self.colonos_data.empty:
                return False, "No hay datos de colonos cargados"
            
            nombre_lower = nombre_colono.lower().strip()
            colono_match = self.colonos_data[
                self.colonos_data['colono'].str.lower().str.strip() == nombre_lower
            ]
            
            if colono_match.empty:
                return False, f"Colono '{nombre_colono}' no encontrado"
            
            colono_row = colono_match.iloc[0]
            codigo_esperado = str(colono_row['codigo_qr']).strip()
            codigo_ingresado = codigo_qr.strip()
            
            if codigo_esperado.lower() == codigo_ingresado.lower():
                return True, f"Bienvenido {colono_row['colono']}"
            else:
                return False, "Código QR incorrecto"
                
        except Exception as e:
            logger.error(f"Error en autenticación: {e}")
            return False, f"Error de autenticación: {str(e)}"
    
    def get_colono_code(self, nombre_colono: str) -> str:
        """Obtiene el código QR de un colono autenticado"""
        try:
            nombre_lower = nombre_colono.lower().strip()
            colono_match = self.colonos_data[
                self.colonos_data['colono'].str.lower().str.strip() == nombre_lower
            ]
            
            if not colono_match.empty:
                return str(colono_match.iloc[0]['codigo_qr']).strip()
            return ""
        except Exception as e:
            logger.error(f"Error obteniendo código del colono: {e}")
            return ""

def check_authenticated():
    """Verifica si el usuario está autenticado automáticamente"""
    # Primero verificar si ya está en session_state
    if st.session_state.get('authenticated', False):
        # Verificar que la sesión no haya expirado
        login_time = st.session_state.get('login_time')
        if login_time:
            try:
                login_datetime = datetime.fromisoformat(login_time)
                if datetime.now() - login_datetime < timedelta(days=30):
                    return True
                else:
                    # Sesión expirada
                    st.session_state.authenticated = False
            except:
                pass
    
    # Si no está autenticado, intentar auto-login
    auto_load_session()
    
    return st.session_state.get('authenticated', False)

def get_current_colono():
    """Obtiene el nombre del colono autenticado"""
    return st.session_state.get('colono_name', '')

def get_current_colono_code():
    """Obtiene el código QR del colono autenticado"""
    return st.session_state.get('colono_code', '')

@st.cache_resource
def get_managers():
    sheets_manager = GoogleSheetsManager(CONFIG['SHEET_NAME'])
    cache_manager = CacheManager(CONFIG['CACHE_FILE'])
    auth_manager = AuthManager(sheets_manager, cache_manager)
    return sheets_manager, cache_manager, auth_manager

def login_form():
    """Formulario de login COMPLETAMENTE AUTOMÁTICO"""
    st.title("🏠 Portal Colonos - Generador QR Visitas")
    st.success("✅ Sesión automática de 30 días - ¡Sin complicaciones!")
    st.markdown("---")
    
    sheets_manager, cache_manager, auth_manager = get_managers()
    
    with st.container():
        st.subheader("🔐 Iniciar Sesión")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nombre_colono = st.text_input(
                "👤 Nombre del Colono:",
                placeholder="Ej: Jesus Jaramillo",
                key="login_nombre"
            )
        
        with col2:
            codigo_qr = st.text_input(
                "🔑 Password:",
                type="password",
                placeholder="Ej: jaramillo203",
                key="login_codigo"
            )
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            login_btn = st.button("🔑 Iniciar Sesión", type="primary", use_container_width=True)
        
        if login_btn:
            if not nombre_colono or not codigo_qr:
                st.error("❌ Por favor complete todos los campos")
            else:
                with st.spinner("Verificando credenciales..."):
                    auth_manager.update_colonos_data()
                    
                    success, message = auth_manager.authenticate_colono(nombre_colono, codigo_qr)
                    
                    if success:
                        colono_code = auth_manager.get_colono_code(nombre_colono)
                        
                        # GUARDADO AUTOMÁTICO
                        session_saved = auto_save_session(nombre_colono, colono_code)
                        
                        st.success(f"✅ {message}")
                        st.success("🔄 Sesión guardada automáticamente por 30 días")
                        st.info("📱 La próxima vez se abrirá directamente sin login")
                        
                        import time
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
        
        st.markdown("---")
        with st.expander("ℹ️ Información de Acceso"):
            st.write("""
            **Para acceder necesitas:**
            - 👤 **Usuario**: Tu nombre completo como aparece en el registro
            - 🔑 **Password**: Tu código QR personal (mismo que usas en el acceso físico)
            
            **¡Completamente automático!**
            - ✅ **Una vez que te loggees**, la app recordará tus datos
            - 🔄 **30 días sin volver a loggearte** 
            - 📱 **Funciona en apps del menú de inicio**
            - 🚪 **Solo usa "Cerrar Sesión" si quieres terminar manualmente**
            
            **Si tienes problemas:**
            - Verifica que tu nombre esté escrito exactamente como en el registro
            - Asegúrate de usar tu código QR personal correcto
            - Contacta a administración si persisten los problemas
            """)

def vehicular_qr_generator():
    """Generador de QR para visitantes vehiculares"""
    sheets_manager, cache_manager, auth_manager = get_managers()
    
    st.subheader("🚗 Generar QR para Visita Vehicular")
    st.info("💡 Para visitantes que ingresan con vehículo y necesitan QR")
    
    with st.form("qr_generator_form", clear_on_submit=True):
        st.markdown("**📝 Datos de la Visita:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nombre_visita = st.text_input(
                "👤 Nombre del Visitante:",
                placeholder="Ej: Juan",
                key="vehicle_visitor_name"
            )
        
        with col2:
            apellido_visita = st.text_input(
                "👤 Apellido del Visitante:",
                placeholder="Ej: Pérez",
                key="vehicle_visitor_lastname"
            )
        
        st.info("ℹ️ Debe llenar al menos el nombre o apellido del visitante")
        
        st.markdown("**📅 Horario de Visita:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            hoy = get_mexico_date()
            fecha_visita = st.date_input(
                "📅 Fecha de la visita:",
                value=hoy,
                min_value=hoy,
                max_value=hoy + timedelta(days=60),
                help="Selecciona la fecha de la visita vehicular",
                key="vehicle_visit_date"
            )
        
        with col2:
            st.markdown("⏰ **Horario disponible: 6:00 AM - 11:00 PM**")
            st.info("📅 Puedes programar hasta 60 días adelante")
            hoy_debug = get_mexico_date()
            st.caption(f"🗓️ Hoy es: {hoy_debug.strftime('%d/%m/%Y')} (México)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            hora_inicio_str = st.selectbox(
                "🕕 Hora de inicio:",
                options=[
                    "06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
                    "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
                    "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"
                ],
                index=12,
                key="vehicle_start_time"
            )
            hora_inicio = time(int(hora_inicio_str.split(':')[0]), int(hora_inicio_str.split(':')[1]))
        
        with col2:
            hora_fin_str = st.selectbox(
                "🕙 Hora de fin:",
                options=[
                    "07:00", "08:00", "09:00", "10:00", "11:00", "12:00",
                    "13:00", "14:00", "15:00", "16:00", "17:00", "18:00",
                    "19:00", "20:00", "21:00", "22:00", "23:00"
                ],
                index=16,
                key="vehicle_end_time"
            )
            hora_fin = time(int(hora_fin_str.split(':')[0]), int(hora_fin_str.split(':')[1]))
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            generate_btn = st.form_submit_button("🎫 Generar QR Vehicular", type="primary", use_container_width=True)
        
        if generate_btn:
            errors = []
            
            if not nombre_visita.strip() and not apellido_visita.strip():
                errors.append("Debe ingresar al menos el nombre o apellido del visitante")
            
            if hora_inicio < CONFIG['HORARIO_INICIO'] or hora_inicio > CONFIG['HORARIO_FIN']:
                errors.append(f"La hora de inicio debe estar entre {CONFIG['HORARIO_INICIO'].strftime('%H:%M')} y {CONFIG['HORARIO_FIN'].strftime('%H:%M')}")
            
            if hora_fin < CONFIG['HORARIO_INICIO'] or hora_fin > CONFIG['HORARIO_FIN']:
                errors.append(f"La hora de fin debe estar entre {CONFIG['HORARIO_INICIO'].strftime('%H:%M')} y {CONFIG['HORARIO_FIN'].strftime('%H:%M')}")
            
            if hora_fin <= hora_inicio:
                errors.append("La hora de fin debe ser posterior a la hora de inicio")
            
            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                with st.spinner("Generando QR vehicular..."):
                    try:
                        nombre_completo = f"{nombre_visita.strip()}{apellido_visita.strip()}".lower().replace(" ", "")
                        
                        colono_code = get_current_colono_code()
                        qr_code = f"QR{nombre_completo}{colono_code}"
                        
                        fecha_inicio_completa = datetime.combine(fecha_visita, hora_inicio)
                        fecha_fin_completa = datetime.combine(fecha_visita, hora_fin)
                        
                        fecha_inicio_str = fecha_inicio_completa.strftime('%Y-%m-%d %H:%M:%S')
                        fecha_fin_str = fecha_fin_completa.strftime('%Y-%m-%d %H:%M:%S')
                        
                        success = sheets_manager.add_visita_qr(
                            qr_code,
                            get_current_colono(),
                            fecha_inicio_str,
                            fecha_fin_str
                        )
                        
                        if success:
                            st.session_state.qr_generated = True
                            st.session_state.qr_data = {
                                'codigo': qr_code,
                                'visitante': f"{nombre_visita} {apellido_visita}",
                                'colono': get_current_colono(),
                                'fecha': fecha_visita.strftime('%d/%m/%Y'),
                                'horario': f"{hora_inicio.strftime('%H:%M')} - {hora_fin.strftime('%H:%M')}",
                                'nombre_archivo': f"QR_vehicular_{nombre_completo}_{fecha_visita.strftime('%Y%m%d')}_{hora_inicio.strftime('%H%M')}.png",
                                'tipo': 'vehicular'
                            }
                            st.success("✅ QR vehicular generado exitosamente")
                            
                        else:
                            st.error("❌ Error al guardar QR en el sistema")
                    
                    except Exception as e:
                        st.error(f"❌ Error generando QR: {str(e)}")
                        logger.error(f"Error en generación de QR vehicular: {e}")

def peatonal_registration():
    """Registro de visitantes peatonales"""
    sheets_manager, cache_manager, auth_manager = get_managers()
    
    st.subheader("🚶 Registrar Visitante Peatonal")
    st.info("💡 Para visitantes que ingresan a pie (sin vehículo) - No requiere QR")
    
    tipo_visitante = st.radio(
        "🔘 Tipo de visitante:",
        ["👤 Visitante único (un día)", "🔄 Visitante recurrente (varios días)"],
        key="tipo_visitante_peatonal"
    )
    
    es_recurrente = "recurrente" in tipo_visitante
    
    with st.form("peatonal_registration_form", clear_on_submit=True):
        st.markdown("**📝 Datos del Visitante:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nombre_visitante = st.text_input(
                "👤 Nombre del Visitante:",
                placeholder="Ej: María González" if not es_recurrente else "Ej: María González (Limpieza)",
                key="peatonal_visitor_name"
            )
        
        with col2:
            if es_recurrente:
                tipo_servicio = st.selectbox(
                    "🔧 Tipo de servicio:",
                    ["Limpieza", "Jardinería", "Mantenimiento", "Seguridad", "Delivery", "Otro"],
                    key="peatonal_service_type"
                )
                telefono_visitante = ""
            else:
                telefono_visitante = st.text_input(
                    "📱 Teléfono (opcional):",
                    placeholder="Ej: 477-123-4567",
                    key="peatonal_visitor_phone"
                )
                tipo_servicio = ""
        
        st.markdown("**📅 Horario Autorizado:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            hoy = get_mexico_date()
            fecha_visita = st.date_input(
                "📅 Fecha de la visita:",
                value=hoy,
                min_value=hoy,
                max_value=hoy + timedelta(days=30),
                help="Selecciona la fecha de la visita peatonal",
                key="peatonal_visit_date"
            )
        
        with col2:
            st.markdown("⏰ **Horario disponible: 6:00 AM - 11:00 PM**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if es_recurrente:
                hora_inicio_str = st.selectbox(
                    "🕕 Hora de inicio diaria:",
                    options=[
                        "06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
                        "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
                        "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"
                    ],
                    index=2,
                    key="peatonal_recurrent_start_time"
                )
            else:
                hora_inicio_str = st.selectbox(
                    "🕕 Hora de inicio:",
                    options=[
                        "06:00", "07:00", "08:00", "09:00", "10:00", "11:00",
                        "12:00", "13:00", "14:00", "15:00", "16:00", "17:00",
                        "18:00", "19:00", "20:00", "21:00", "22:00", "23:00"
                    ],
                    index=3,
                    key="peatonal_start_time"
                )
            hora_inicio = time(int(hora_inicio_str.split(':')[0]), int(hora_inicio_str.split(':')[1]))
        
        with col2:
            if es_recurrente:
                hora_fin_str = st.selectbox(
                    "🕙 Hora de fin diaria:",
                    options=[
                        "07:00", "08:00", "09:00", "10:00", "11:00", "12:00",
                        "13:00", "14:00", "15:00", "16:00", "17:00", "18:00",
                        "19:00", "20:00", "21:00", "22:00", "23:00"
                    ],
                    index=10,
                    key="peatonal_recurrent_end_time"
                )
            else:
                hora_fin_str = st.selectbox(
                    "🕙 Hora de fin:",
                    options=[
                        "07:00", "08:00", "09:00", "10:00", "11:00", "12:00",
                        "13:00", "14:00", "15:00", "16:00", "17:00", "18:00",
                        "19:00", "20:00", "21:00", "22:00", "23:00"
                    ],
                    index=11,
                    key="peatonal_end_time"
                )
            hora_fin = time(int(hora_fin_str.split(':')[0]), int(hora_fin_str.split(':')[1]))
        
        if es_recurrente:
            observaciones = st.text_area(
                "📝 Descripción del servicio:",
                placeholder="Ej: Limpieza general de la casa, viene lunes, miércoles y viernes",
                key="peatonal_recurrent_observations",
                max_chars=200
            )
        else:
            observaciones = st.text_area(
                "📝 Observaciones (opcional):",
                placeholder="Ej: Viene a recoger documentos, visita familiar, etc.",
                key="peatonal_observations",
                max_chars=200
            )
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if es_recurrente:
                register_btn = st.form_submit_button("🔄 Registrar Visitante Recurrente", type="primary", use_container_width=True)
            else:
                register_btn = st.form_submit_button("👥 Registrar Visitante Peatonal", type="primary", use_container_width=True)
        
        if register_btn:
            errors = []
            
            if not nombre_visitante.strip():
                errors.append("Debe ingresar el nombre del visitante")
            
            if hora_inicio < CONFIG['HORARIO_INICIO'] or hora_inicio > CONFIG['HORARIO_FIN']:
                errors.append(f"La hora de inicio debe estar entre {CONFIG['HORARIO_INICIO'].strftime('%H:%M')} y {CONFIG['HORARIO_FIN'].strftime('%H:%M')}")
            
            if hora_fin < CONFIG['HORARIO_INICIO'] or hora_fin > CONFIG['HORARIO_FIN']:
                errors.append(f"La hora de fin debe estar entre {CONFIG['HORARIO_INICIO'].strftime('%H:%M')} y {CONFIG['HORARIO_FIN'].strftime('%H:%M')}")
            
            if hora_fin <= hora_inicio:
                errors.append("La hora de fin debe ser posterior a la hora de inicio")
            
            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                with st.spinner("Registrando visitante peatonal..."):
                    try:
                        fecha_inicio_completa = datetime.combine(fecha_visita, hora_inicio)
                        fecha_fin_completa = datetime.combine(fecha_visita, hora_fin)
                        
                        fecha_inicio_str = fecha_inicio_completa.strftime('%Y-%m-%d %H:%M:%S')
                        fecha_fin_str = fecha_fin_completa.strftime('%Y-%m-%d %H:%M:%S')
                        
                        nombre_completo = nombre_visitante.strip()
                        if es_recurrente:
                            nombre_completo += f" ({tipo_servicio})"
                        else:
                            if telefono_visitante.strip():
                                nombre_completo += f" ({telefono_visitante.strip()})"
                        
                        if observaciones.strip():
                            nombre_completo += f" - {observaciones.strip()}"
                        
                        success = sheets_manager.add_peatonal_visitor(
                            nombre_completo,
                            get_current_colono(),
                            fecha_inicio_str,
                            fecha_fin_str
                        )
                        
                        if success:
                            st.session_state.peatonal_registered = True
                            st.session_state.peatonal_data = {
                                'visitante': nombre_visitante,
                                'colono': get_current_colono(),
                                'fecha': fecha_visita.strftime('%d/%m/%Y'),
                                'horario': f"{hora_inicio.strftime('%H:%M')} - {hora_fin.strftime('%H:%M')}",
                                'observaciones': observaciones,
                                'es_recurrente': es_recurrente
                            }
                            
                            if es_recurrente:
                                st.session_state.peatonal_data['tipo_servicio'] = tipo_servicio
                            else:
                                st.session_state.peatonal_data['telefono'] = telefono_visitante
                            
                            st.success("✅ Visitante peatonal registrado exitosamente")
                        else:
                            st.error("❌ Error al registrar visitante en el sistema")
                            
                    except Exception as e:
                        st.error(f"❌ Error registrando visitante: {str(e)}")
                        logger.error(f"Error en registro peatonal: {e}")

def main_app():
    """Aplicación principal para colonos autenticados"""
    sheets_manager, cache_manager, auth_manager = get_managers()
    
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    
    with col1:
        st.title("🏠 Portal Colonos")
        st.markdown(f"**Bienvenido:** {get_current_colono()}")
        st.caption("🔒 Sesión automática activa (30 días)")
    
    with col2:
        if st.button("🔄 Actualizar Datos", key="refresh_data"):
            auth_manager.update_colonos_data()
            st.success("Datos actualizados")
    
    with col3:
        # Mostrar días restantes
        login_time = st.session_state.get('login_time')
        if login_time:
            try:
                login_datetime = datetime.fromisoformat(login_time)
                days_remaining = 30 - (datetime.now() - login_datetime).days
                if days_remaining > 0:
                    st.caption(f"⏰ Quedan: {days_remaining} días")
                else:
                    st.caption("⏰ Sesión activa")
            except:
                st.caption("⏰ Sesión activa")
    
    with col4:
        if st.button("🚪 Cerrar Sesión", key="logout"):
            clear_auto_session()
            st.success("🔓 Sesión cerrada exitosamente")
            import time
            time.sleep(1)
            st.rerun()
    
    st.markdown("---")
    
    tab1, tab2 = st.tabs(["🚗 Visitantes Vehiculares", "🚶 Visitantes Peatonales"])
    
    with tab1:
        vehicular_qr_generator()
        
        if st.session_state.get('qr_generated', False):
            qr_data = st.session_state.qr_data
            
            if qr_data.get('tipo') == 'vehicular':
                st.markdown("---")
                st.subheader("🎫 QR Vehicular Generado")
                
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.markdown("**📋 Información del QR:**")
                    st.write(f"**Código QR:** `{qr_data['codigo']}`")
                    st.write(f"**Visitante:** {qr_data['visitante']}")
                    st.write(f"**Colono:** {qr_data['colono']}")
                    st.write(f"**Fecha:** {qr_data['fecha']}")
                    st.write(f"**Horario:** {qr_data['horario']}")
                
                with col2:
                    try:
                        qr_img = QRGenerator.generate_qr_code(qr_data['codigo'])
                        
                        if qr_img:
                            st.image(qr_img, caption=f"QR: {qr_data['codigo']}", width=200)
                            
                            qr_bytes = QRGenerator.qr_to_bytes(qr_img)
                            if qr_bytes:
                                st.download_button(
                                    label="📥 Descargar QR",
                                    data=qr_bytes,
                                    file_name=qr_data['nombre_archivo'],
                                    mime="image/png",
                                    type="primary",
                                    use_container_width=True,
                                    key="download_qr_btn"
                                )
                            else:
                                st.error("Error preparando descarga")
                                st.markdown("**📋 Código QR:**")
                                st.code(qr_data['codigo'])
                        else:
                            st.error("Error generando imagen QR")
                            st.markdown("**📋 Código QR:**")
                            st.code(qr_data['codigo'])
                    except Exception as e:
                        st.error(f"Error con imagen QR: {str(e)}")
                        st.markdown("**📋 Código QR (texto):**")
                        st.code(qr_data['codigo'])
                        st.info("💡 Copie este código y use un generador QR online")
                
                st.markdown("---")
                st.info("""
                📋 **Instrucciones para tu visitante vehicular:**
                1. 📱 Descarga la imagen QR y compártela con tu visitante
                2. 🚗 El visitante debe presentar el QR en la entrada vehicular
                3. ✅ El acceso será válido solo en el horario especificado
                4. ⏰ El QR expirará automáticamente después de la hora de fin
                """)
                
                if st.button("➕ Generar Otro QR Vehicular", key="new_vehicle_qr_btn"):
                    st.session_state.qr_generated = False
                    st.rerun()
    
    with tab2:
        peatonal_registration()
        
        if st.session_state.get('peatonal_registered', False):
            peatonal_data = st.session_state.peatonal_data
            
            st.markdown("---")
            st.subheader("✅ Visitante Peatonal Registrado")
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("**📋 Información del Registro:**")
                st.write(f"**Visitante:** {peatonal_data['visitante']}")
                if peatonal_data.get('telefono'):
                    st.write(f"**Teléfono:** {peatonal_data['telefono']}")
                if peatonal_data.get('tipo_servicio'):
                    st.write(f"**Servicio:** {peatonal_data['tipo_servicio']}")
                st.write(f"**Autorizado por:** {peatonal_data['colono']}")
                st.write(f"**Fecha:** {peatonal_data['fecha']}")
                st.write(f"**Horario:** {peatonal_data['horario']}")
                if peatonal_data.get('observaciones'):
                    st.write(f"**Observaciones:** {peatonal_data['observaciones']}")
            
            with col2:
                st.markdown("**🚶 Acceso Peatonal**")
                if peatonal_data.get('es_recurrente'):
                    st.success("""
                    ✅ **Visitante recurrente autorizado**
                    
                    🔄 Puede venir cualquier día del período
                    🗣️ Se identifica con el guardia cada vez
                    📝 Cada visita se registra por separado
                    """)
                else:
                    st.info("""
                    ✅ **El visitante ya está autorizado**
                    
                    No necesita QR, solo debe:
                    1. 🚶 Llegar a la entrada peatonal
                    2. 🗣️ Identificarse con el guardia
                    3. ✅ El guardia confirmará su autorización
                    4. 🚪 Acceso permitido en horario indicado
                    """)
            
            st.markdown("---")
            st.success("📋 **¡Registro completado exitosamente!** Tu visitante peatonal ya aparece en el sistema del guardia.")
            
            if st.button("👥 Registrar Otro Visitante Peatonal", key="new_peatonal_btn"):
                st.session_state.peatonal_registered = False
                st.rerun()

def main():
    """Función principal COMPLETAMENTE AUTOMÁTICA"""
    st.set_page_config(
        page_title="Portal Colonos - QR Visitas",
        page_icon="🏠",
        layout="wide"
    )
    
    st.markdown("""
    <style>
    .main-header {
        text-align: center;
        padding: 1rem;
        background: linear-gradient(90deg, #4CAF50, #45a049);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .info-box {
        background: #f0f8ff;
        padding: 1rem;
        border-radius: 5px;
        border-left: 4px solid #4CAF50;
    }
    </style>
    """, unsafe_allow_html=True)
    
    if not check_authenticated():
        login_form()
    else:
        main_app()
    
    st.markdown("---")
    st.markdown(
        "<div style='text-align: center; color: #666;'>"
        "🏠 Portal Colonos - Sistema de Visitantes (Vehiculares y Peatonales)<br>"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        "</div>",
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
