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

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración global
CONFIG = {
    'SHEET_NAME': 'ControlAccesoQR',
    'CACHE_FILE': 'cache_colonos.csv',
    'HORARIO_INICIO': time(6, 0),
    'HORARIO_FIN': time(23, 0),
}

def get_mexico_date():
    try:
        utc_now = datetime.utcnow()
        mexico_now = utc_now - timedelta(hours=6)
        return mexico_now.date()
    except Exception as e:
        logger.error(f"Error obteniendo fecha México: {e}")
        return date.today()

def get_google_credentials():
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

class GoogleSheetsManager:
    """Maneja la conexión y operaciones con Google Sheets (2 hojas: Colonos + Visitas)"""

    SHEET_COLONOS = "Colonos"
    SHEET_VISITAS  = "Visitas"

    def __init__(self, sheet_name: str):
        self.sheet_name    = sheet_name
        self.client        = None
        self.sheet_colonos = None  # codigo_qr | link | colono | estatus
        self.sheet_visitas  = None  # codigo_qr | colono | fecha_inicio | fecha_fin
        self.connect()

    def connect(self) -> bool:
        try:
            credentials_dict = get_google_credentials()
            if not credentials_dict:
                raise Exception("No se pudieron obtener las credenciales")

            scope = ['https://spreadsheets.google.com/feeds',
                     'https://www.googleapis.com/auth/drive']

            creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
            self.client    = gspread.authorize(creds)
            spreadsheet    = self.client.open(self.sheet_name)
            self.sheet_colonos = spreadsheet.worksheet(self.SHEET_COLONOS)
            self.sheet_visitas  = spreadsheet.worksheet(self.SHEET_VISITAS)
            logger.info(f"Conectado a Sheets: '{self.SHEET_COLONOS}' y '{self.SHEET_VISITAS}'")
            return True
        except Exception as e:
            logger.error(f"Error conectando a Google Sheets: {e}")
            return False

    def get_colonos_data(self) -> pd.DataFrame:
        """Lee hoja Colonos, devuelve solo colonos activos con codigo_qr | colono | estatus"""
        try:
            if not self.sheet_colonos:
                raise Exception("No hay conexión a hoja Colonos")

            records = self.sheet_colonos.get_all_records()
            df = pd.DataFrame(records)

            if df.empty:
                return pd.DataFrame(columns=['codigo_qr', 'colono', 'estatus'])

            df.columns = [c.lower().strip() for c in df.columns]
            df = df.fillna('')
            df['codigo_qr'] = df.get('codigo_qr', pd.Series(dtype=str)).astype(str).str.strip()
            df['colono']    = df.get('colono',    pd.Series(dtype=str)).astype(str).str.strip()
            df['estatus']   = df.get('estatus',   pd.Series(dtype=str)).astype(str).str.strip().str.lower()

            # Solo colonos activos
            df = df[df['estatus'] == 'activo']
            logger.info(f"Colonos activos cargados: {len(df)}")
            return df[['codigo_qr', 'colono', 'estatus']]

        except Exception as e:
            logger.error(f"Error obteniendo datos de colonos: {e}")
            return pd.DataFrame(columns=['codigo_qr', 'colono', 'estatus'])

    def add_visita_qr(self, codigo_qr: str, colono: str, fecha_inicio: str, fecha_fin: str) -> bool:
        """Agrega visita vehicular en hoja Visitas: codigo_qr | colono | fecha_inicio | fecha_fin"""
        try:
            if not self.sheet_visitas:
                raise Exception("No hay conexión a hoja Visitas")
            self.sheet_visitas.append_row([codigo_qr, colono, fecha_inicio, fecha_fin])
            logger.info(f"Visita QR agregada: {codigo_qr} para {colono}")
            return True
        except Exception as e:
            logger.error(f"Error agregando visita QR: {e}")
            return False

    def add_peatonal_visitor(self, nombre_visitante: str, colono: str, fecha_inicio: str, fecha_fin: str) -> bool:
        """Agrega visitante peatonal en hoja Visitas: nombre | colono | fecha_inicio | fecha_fin"""
        try:
            if not self.sheet_visitas:
                raise Exception("No hay conexión a hoja Visitas")
            self.sheet_visitas.append_row([nombre_visitante, colono, fecha_inicio, fecha_fin])
            logger.info(f"Peatonal agregado: {nombre_visitante} para {colono}")
            return True
        except Exception as e:
            logger.error(f"Error agregando visitante peatonal: {e}")
            return False


class CacheManager:
    def __init__(self, cache_file: str):
        self.cache_file = cache_file

    def save_cache(self, df: pd.DataFrame) -> bool:
        try:
            df.to_csv(self.cache_file, index=False)
            logger.info(f"Cache guardado en {self.cache_file}")
            return True
        except Exception as e:
            logger.error(f"Error guardando cache: {e}")
            return False

    def load_cache(self) -> pd.DataFrame:
        try:
            if os.path.exists(self.cache_file):
                df = pd.read_csv(self.cache_file)
                logger.info(f"Cache cargado desde {self.cache_file}")
                return df
            else:
                return pd.DataFrame(columns=['codigo_qr', 'colono', 'estatus'])
        except Exception as e:
            logger.error(f"Error cargando cache: {e}")
            return pd.DataFrame(columns=['codigo_qr', 'colono', 'estatus'])


class QRGenerator:
    @staticmethod
    def generate_qr_code(data: str):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=12,
                border=4,
            )
            qr.add_data(data)
            try:
                qr.make(fit=False)
            except:
                qr.version = None
                qr.make(fit=True)

            img = qr.make_image(fill_color="#000000", back_color="#FFFFFF", image_factory=None)

            from PIL import Image
            if not isinstance(img, Image.Image):
                img = img.convert('RGB')

            target_size = 400
            current_size = img.size[0]
            if current_size < target_size:
                scale_factor = target_size // current_size
                if scale_factor > 1:
                    new_size = (current_size * scale_factor, current_size * scale_factor)
                    img = img.resize(new_size, Image.NEAREST)

            logger.info(f"QR generado (v{qr.version}): {data[:30]}...")
            return img
        except Exception as e:
            logger.error(f"Error generando QR: {e}")
            return None

    @staticmethod
    def generate_simple_qr(data: str):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            if len(data) > 20:
                data = data[:20]
            qr.add_data(data)
            qr.make(fit=False)
            img = qr.make_image(fill_color="black", back_color="white")
            from PIL import Image
            if not isinstance(img, Image.Image):
                img = img.convert('RGB')
            return img
        except Exception as e:
            logger.error(f"Error generando QR simple: {e}")
            return None

    @staticmethod
    def qr_to_bytes(img):
        try:
            if img is None:
                return None
            from PIL import Image
            if not isinstance(img, Image.Image):
                return None
            buf = io.BytesIO()
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(buf, format='PNG', optimize=False, compress_level=0)
            buf.seek(0)
            img_bytes = buf.getvalue()
            buf.close()
            return img_bytes
        except Exception as e:
            logger.error(f"Error convirtiendo QR: {e}")
            return None

    @staticmethod
    def generate_test_qr(test_data: str = "TEST123"):
        return QRGenerator.generate_simple_qr(test_data)


class AuthManager:
    def __init__(self, sheets_manager: GoogleSheetsManager, cache_manager: CacheManager):
        self.sheets_manager = sheets_manager
        self.cache_manager  = cache_manager
        self.colonos_data   = pd.DataFrame()
        self.update_colonos_data()

    def update_colonos_data(self) -> bool:
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
        try:
            if self.colonos_data.empty:
                return False, "No hay datos de colonos cargados"

            nombre_lower  = nombre_colono.lower().strip()
            colono_match  = self.colonos_data[
                self.colonos_data['colono'].str.lower().str.strip() == nombre_lower
            ]

            if colono_match.empty:
                return False, f"Colono '{nombre_colono}' no encontrado"

            colono_row       = colono_match.iloc[0]
            codigo_esperado  = str(colono_row['codigo_qr']).strip()
            codigo_ingresado = codigo_qr.strip()

            if codigo_esperado.lower() == codigo_ingresado.lower():
                return True, f"Bienvenido {colono_row['colono']}"
            else:
                return False, "Código QR incorrecto"

        except Exception as e:
            logger.error(f"Error en autenticación: {e}")
            return False, f"Error de autenticación: {str(e)}"

    def get_colono_code(self, nombre_colono: str) -> str:
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
    return st.session_state.get('authenticated', False)

def get_current_colono():
    return st.session_state.get('colono_name', '')

def get_current_colono_code():
    return st.session_state.get('colono_code', '')

@st.cache_resource
def get_managers():
    sheets_manager = GoogleSheetsManager(CONFIG['SHEET_NAME'])
    cache_manager  = CacheManager(CONFIG['CACHE_FILE'])
    auth_manager   = AuthManager(sheets_manager, cache_manager)
    return sheets_manager, cache_manager, auth_manager


def login_form():
    st.title("🏠 Portal Colonos - Generador QR Visitas")
    st.markdown("---")

    sheets_manager, cache_manager, auth_manager = get_managers()

    with st.container():
        st.subheader("🔐 Iniciar Sesión")

        col1, col2 = st.columns(2)
        with col1:
            nombre_colono = st.text_input("👤 Nombre del Colono:", placeholder="Ej: Jesus Jaramillo", key="login_nombre")
        with col2:
            codigo_qr = st.text_input("🔑 Password:", type="password", placeholder="Ej: jaramillo203", key="login_codigo")

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
                        st.session_state.authenticated = True
                        st.session_state.colono_name   = nombre_colono
                        st.session_state.colono_code   = colono_code
                        st.success(f"✅ {message}")
                        import time; time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")

        st.markdown("---")
        with st.expander("ℹ️ Información de Acceso"):
            st.write("""
            **Para acceder necesitas:**
            - 👤 **Usuario**: Tu nombre completo como aparece en el registro
            - 🔑 **Password**: Tu código QR personal (mismo que usas en el acceso físico)
            """)


def vehicular_qr_generator():
    sheets_manager, cache_manager, auth_manager = get_managers()

    st.subheader("🚗 Generar QR para Visita Vehicular")
    st.info("💡 Para visitantes que ingresan con vehículo y necesitan QR")

    with st.form("qr_generator_form", clear_on_submit=True):
        st.markdown("**📝 Datos de la Visita:**")

        col1, col2 = st.columns(2)
        with col1:
            nombre_visita = st.text_input("👤 Nombre del Visitante:", placeholder="Ej: Juan", key="vehicle_visitor_name")
        with col2:
            apellido_visita = st.text_input("👤 Apellido del Visitante:", placeholder="Ej: Pérez", key="vehicle_visitor_lastname")

        st.info("ℹ️ Debe llenar al menos el nombre o apellido del visitante")
        st.markdown("**📅 Horario de Visita:**")

        col1, col2 = st.columns(2)
        with col1:
            hoy = get_mexico_date()
            fecha_visita = st.date_input("📅 Fecha de la visita:", value=hoy, min_value=hoy,
                                          max_value=hoy + timedelta(days=60), key="vehicle_visit_date")
        with col2:
            st.markdown("⏰ **Horario disponible: 6:00 AM - 11:00 PM**")
            st.info("📅 Puedes programar hasta 60 días adelante")

        opciones_inicio = ["06:00","07:00","08:00","09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00","21:00","22:00","23:00"]
        opciones_fin    = ["07:00","08:00","09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00","21:00","22:00","23:00"]

        col1, col2 = st.columns(2)
        with col1:
            hora_inicio_str = st.selectbox("🕕 Hora de inicio:", opciones_inicio, index=12, key="vehicle_start_time")
            hora_inicio = time(int(hora_inicio_str.split(':')[0]), 0)
        with col2:
            hora_fin_str = st.selectbox("🕙 Hora de fin:", opciones_fin, index=16, key="vehicle_end_time")
            hora_fin = time(int(hora_fin_str.split(':')[0]), 0)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            generate_btn = st.form_submit_button("🎫 Generar QR Vehicular", type="primary", use_container_width=True)

        if generate_btn:
            errors = []
            if not nombre_visita.strip() and not apellido_visita.strip():
                errors.append("Debe ingresar al menos el nombre o apellido del visitante")
            if hora_fin <= hora_inicio:
                errors.append("La hora de fin debe ser posterior a la hora de inicio")

            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                with st.spinner("Generando QR vehicular..."):
                    try:
                        nombre_completo = f"{nombre_visita.strip()}{apellido_visita.strip()}".lower().replace(" ", "")
                        colono_code     = get_current_colono_code()
                        qr_code         = f"QR{nombre_completo}{colono_code}"

                        fecha_inicio_completa = datetime.combine(fecha_visita, hora_inicio)
                        fecha_fin_completa    = datetime.combine(fecha_visita, hora_fin)
                        fecha_inicio_str      = fecha_inicio_completa.strftime('%Y-%m-%d %H:%M:%S')
                        fecha_fin_str         = fecha_fin_completa.strftime('%Y-%m-%d %H:%M:%S')

                        success = sheets_manager.add_visita_qr(qr_code, get_current_colono(), fecha_inicio_str, fecha_fin_str)

                        if success:
                            st.session_state.qr_generated = True
                            st.session_state.qr_data = {
                                'codigo': qr_code,
                                'visitante': f"{nombre_visita} {apellido_visita}",
                                'colono': get_current_colono(),
                                'fecha': fecha_visita.strftime('%d/%m/%Y'),
                                'horario': f"{hora_inicio.strftime('%H:%M')} - {hora_fin.strftime('%H:%M')}",
                                'nombre_archivo': f"QR_vehicular_{nombre_completo}_{fecha_visita.strftime('%Y%m%d')}.png",
                                'tipo': 'vehicular'
                            }
                            st.success("✅ QR vehicular generado exitosamente")
                        else:
                            st.error("❌ Error al guardar QR en el sistema")
                    except Exception as e:
                        st.error(f"❌ Error generando QR: {str(e)}")


def peatonal_registration():
    sheets_manager, cache_manager, auth_manager = get_managers()

    st.subheader("🚶 Registrar Visitante Peatonal")
    st.info("💡 Para visitantes que ingresan a pie (sin vehículo) - No requiere QR")

    tipo_visitante = st.radio("🔘 Tipo de visitante:",
                               ["👤 Visitante único (un día)", "🔄 Visitante recurrente (varios días)"],
                               key="tipo_visitante_peatonal")
    es_recurrente = "recurrente" in tipo_visitante

    with st.form("peatonal_registration_form", clear_on_submit=True):
        st.markdown("**📝 Datos del Visitante:**")

        col1, col2 = st.columns(2)
        with col1:
            nombre_visitante = st.text_input("👤 Nombre del Visitante:", key="peatonal_visitor_name")
        with col2:
            if es_recurrente:
                tipo_servicio      = st.selectbox("🔧 Tipo de servicio:", ["Limpieza","Jardinería","Mantenimiento","Seguridad","Delivery","Otro"], key="peatonal_service_type")
                telefono_visitante = ""
            else:
                telefono_visitante = st.text_input("📱 Teléfono (opcional):", key="peatonal_visitor_phone")
                tipo_servicio      = ""

        st.markdown("**📅 Horario Autorizado:**")
        col1, col2 = st.columns(2)
        with col1:
            hoy = get_mexico_date()
            fecha_visita = st.date_input("📅 Fecha de la visita:", value=hoy, min_value=hoy,
                                          max_value=hoy + timedelta(days=30), key="peatonal_visit_date")
        with col2:
            st.markdown("⏰ **Horario disponible: 6:00 AM - 11:00 PM**")

        opciones_inicio = ["06:00","07:00","08:00","09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00","21:00","22:00","23:00"]
        opciones_fin    = ["07:00","08:00","09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00","21:00","22:00","23:00"]

        col1, col2 = st.columns(2)
        with col1:
            hora_inicio_str = st.selectbox("🕕 Hora de inicio:", opciones_inicio, index=2, key="peatonal_start_time")
            hora_inicio = time(int(hora_inicio_str.split(':')[0]), 0)
        with col2:
            hora_fin_str = st.selectbox("🕙 Hora de fin:", opciones_fin, index=10, key="peatonal_end_time")
            hora_fin = time(int(hora_fin_str.split(':')[0]), 0)

        observaciones = st.text_area("📝 Observaciones (opcional):", key="peatonal_observations", max_chars=200)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            label_btn = "🔄 Registrar Visitante Recurrente" if es_recurrente else "👥 Registrar Visitante Peatonal"
            register_btn = st.form_submit_button(label_btn, type="primary", use_container_width=True)

        if register_btn:
            errors = []
            if not nombre_visitante.strip():
                errors.append("Debe ingresar el nombre del visitante")
            if hora_fin <= hora_inicio:
                errors.append("La hora de fin debe ser posterior a la hora de inicio")

            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                with st.spinner("Registrando visitante peatonal..."):
                    try:
                        fecha_inicio_completa = datetime.combine(fecha_visita, hora_inicio)
                        fecha_fin_completa    = datetime.combine(fecha_visita, hora_fin)
                        fecha_inicio_str      = fecha_inicio_completa.strftime('%Y-%m-%d %H:%M:%S')
                        fecha_fin_str         = fecha_fin_completa.strftime('%Y-%m-%d %H:%M:%S')

                        nombre_completo = nombre_visitante.strip()
                        if es_recurrente:
                            nombre_completo += f" ({tipo_servicio})"
                        elif telefono_visitante.strip():
                            nombre_completo += f" ({telefono_visitante.strip()})"
                        if observaciones.strip():
                            nombre_completo += f" - {observaciones.strip()}"

                        success = sheets_manager.add_peatonal_visitor(
                            nombre_completo, get_current_colono(), fecha_inicio_str, fecha_fin_str)

                        if success:
                            st.session_state.peatonal_registered = True
                            st.session_state.peatonal_data = {
                                'visitante': nombre_visitante,
                                'colono': get_current_colono(),
                                'fecha': fecha_visita.strftime('%d/%m/%Y'),
                                'horario': f"{hora_inicio.strftime('%H:%M')} - {hora_fin.strftime('%H:%M')}",
                                'observaciones': observaciones,
                                'es_recurrente': es_recurrente,
                                'tipo_servicio': tipo_servicio,
                                'telefono': telefono_visitante,
                            }
                            st.success("✅ Visitante peatonal registrado exitosamente")
                        else:
                            st.error("❌ Error al registrar visitante en el sistema")
                    except Exception as e:
                        st.error(f"❌ Error registrando visitante: {str(e)}")


def main_app():
    sheets_manager, cache_manager, auth_manager = get_managers()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.title("🏠 Portal Colonos")
        st.markdown(f"**Bienvenido:** {get_current_colono()}")
    with col2:
        if st.button("🔄 Actualizar Datos", key="refresh_data"):
            auth_manager.update_colonos_data()
            st.success("Datos actualizados")
    with col3:
        if st.button("🚪 Cerrar Sesión", key="logout"):
            for key in ['authenticated','colono_name','colono_code','qr_generated','qr_data','peatonal_registered','peatonal_data']:
                if key in st.session_state:
                    del st.session_state[key]
            st.success("🔓 Sesión cerrada")
            import time; time.sleep(1)
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
                            st.image(qr_img, caption=f"QR: {qr_data['codigo']}", width=350)
                            qr_bytes = QRGenerator.qr_to_bytes(qr_img)
                            if qr_bytes:
                                st.download_button("📥 Descargar QR", data=qr_bytes,
                                                   file_name=qr_data['nombre_archivo'],
                                                   mime="image/png", type="primary",
                                                   use_container_width=True, key="download_qr_btn")
                        else:
                            st.code(qr_data['codigo'])
                    except Exception as e:
                        st.code(qr_data['codigo'])

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
                st.write(f"**Visitante:** {peatonal_data['visitante']}")
                if peatonal_data.get('telefono'):
                    st.write(f"**Teléfono:** {peatonal_data['telefono']}")
                if peatonal_data.get('tipo_servicio'):
                    st.write(f"**Servicio:** {peatonal_data['tipo_servicio']}")
                st.write(f"**Autorizado por:** {peatonal_data['colono']}")
                st.write(f"**Fecha:** {peatonal_data['fecha']}")
                st.write(f"**Horario:** {peatonal_data['horario']}")
            with col2:
                st.info("✅ El visitante ya aparece en el sistema del guardia.")

            if st.button("👥 Registrar Otro Visitante Peatonal", key="new_peatonal_btn"):
                st.session_state.peatonal_registered = False
                st.rerun()


def main():
    st.set_page_config(page_title="Portal Colonos - QR Visitas", page_icon="🏠", layout="wide")

    if not check_authenticated():
        login_form()
    else:
        main_app()

    st.markdown("---")
    st.markdown(
        "<div style='text-align:center;color:#666;'>"
        "🏠 Portal Colonos - Sistema de Visitantes<br>"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        "</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
