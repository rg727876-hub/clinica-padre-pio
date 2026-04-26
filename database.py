import sqlite3
from datetime import datetime
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'clinica.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dni TEXT UNIQUE NOT NULL,
            nombres TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            correo TEXT UNIQUE NOT NULL,
            telefono TEXT,
            rol TEXT NOT NULL CHECK(rol IN ('administrador','recepcionista','doctor','cajero')),
            contrasena TEXT NOT NULL,
            especialidad TEXT,
            estado TEXT DEFAULT 'activo' CHECK(estado IN ('activo','inactivo')),
            fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS servicios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            descripcion TEXT,
            duracion INTEGER NOT NULL,
            buffer_limpieza INTEGER DEFAULT 0,
            costo REAL NOT NULL,
            estado TEXT DEFAULT 'activo' CHECK(estado IN ('activo','inactivo'))
        );

        CREATE TABLE IF NOT EXISTS doctor_servicio (
            doctor_id INTEGER NOT NULL,
            servicio_id INTEGER NOT NULL,
            PRIMARY KEY (doctor_id, servicio_id),
            FOREIGN KEY (doctor_id) REFERENCES usuarios(id),
            FOREIGN KEY (servicio_id) REFERENCES servicios(id)
        );

        CREATE TABLE IF NOT EXISTS horarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            dia TEXT NOT NULL CHECK(dia IN ('Lunes','Martes','Miércoles','Jueves','Viernes','Sábado')),
            hora_inicio TEXT NOT NULL,
            hora_fin TEXT NOT NULL,
            FOREIGN KEY (doctor_id) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dni TEXT UNIQUE NOT NULL,
            nombres TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            telefono TEXT,
            correo TEXT,
            direccion TEXT,
            fecha_nacimiento TEXT,
            sexo TEXT CHECK(sexo IN ('M','F')),
            estado TEXT DEFAULT 'activo' CHECK(estado IN ('activo','inactivo')),
            fecha_registro TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS citas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            paciente_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            servicio_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            hora TEXT NOT NULL,
            estado TEXT DEFAULT 'confirmada' CHECK(estado IN ('confirmada','atendida','cancelada','no_asistio','pagada')),
            monto REAL NOT NULL,
            observaciones TEXT,
            creado_por INTEGER,
            fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (doctor_id) REFERENCES usuarios(id),
            FOREIGN KEY (servicio_id) REFERENCES servicios(id)
        );

        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cita_id INTEGER NOT NULL,
            cajero_id INTEGER NOT NULL,
            monto REAL NOT NULL,
            metodo_pago TEXT NOT NULL CHECK(metodo_pago IN ('efectivo','tarjeta','yape','plin','transferencia')),
            numero_operacion TEXT,
            cambio REAL DEFAULT 0,
            comprobante_tipo TEXT DEFAULT 'boleta' CHECK(comprobante_tipo IN ('boleta','factura')),
            fecha TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cita_id) REFERENCES citas(id),
            FOREIGN KEY (cajero_id) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            accion TEXT NOT NULL,
            detalle TEXT,
            fecha TEXT DEFAULT CURRENT_TIMESTAMP,
            ip TEXT
        );

        CREATE TABLE IF NOT EXISTS historia_clinica (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER UNIQUE NOT NULL,
            motivo_consulta TEXT,
            enfermedad_inicio TEXT,
            enfermedad_evolucion TEXT,
            enfermedad_estado_actual TEXT,
            antec_sistemicos TEXT,
            antec_estomatologico TEXT,
            antec_farmacologicos TEXT,
            antec_otros TEXT,
            antec_familiares TEXT,
            creado_por INTEGER,
            fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
            actualizado_por INTEGER,
            fecha_actualizacion TEXT,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (creado_por) REFERENCES usuarios(id),
            FOREIGN KEY (actualizado_por) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS consulta_clinica (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            cita_id INTEGER UNIQUE,
            doctor_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            vitales_pa TEXT,
            vitales_pulso TEXT,
            vitales_fr TEXT,
            vitales_temperatura TEXT,
            vitales_otros TEXT,
            extra_oral_zona TEXT,
            extra_oral_otros TEXT,
            intra_oral_zona TEXT,
            intra_oral_otros TEXT,
            diagnostico_presuntivo TEXT,
            examenes_complementarios TEXT,
            diagnostico_cie10 TEXT,
            plan_tratamiento TEXT,
            tratamiento TEXT,
            pronostico TEXT,
            control_evolucion TEXT,
            alta_paciente TEXT,
            fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TEXT,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (cita_id) REFERENCES citas(id),
            FOREIGN KEY (doctor_id) REFERENCES usuarios(id)
        );
    ''')

    # Migración: columnas nuevas en pacientes
    for col_def in [
        'estado_civil TEXT',
        'ocupacion TEXT',
        'contacto_emergencia TEXT',
    ]:
        try:
            c.execute(f"ALTER TABLE pacientes ADD COLUMN {col_def}")
        except Exception:
            pass

    # Crear administrador por defecto
    admin_pass = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute('''INSERT OR IGNORE INTO usuarios (dni,nombres,apellidos,correo,rol,contrasena)
                 VALUES ('00000000','Admin','Sistema','admin@clinica.com','administrador',?)''', (admin_pass,))

    # Servicios de ejemplo
    servicios = [
        ('Limpieza dental', 'Profilaxis y limpieza profesional', 45, 10, 80.0),
        ('Extracción simple', 'Extracción de piezas dentales', 30, 15, 120.0),
        ('Endodoncia', 'Tratamiento de conductos', 90, 15, 350.0),
        ('Blanqueamiento', 'Blanqueamiento dental profesional', 60, 10, 200.0),
        ('Ortodoncia', 'Colocación y control de brackets', 45, 10, 150.0),
        ('Radiografía', 'Radiografía dental periapical', 15, 5, 40.0),
    ]
    c.executemany('''INSERT OR IGNORE INTO servicios (nombre,descripcion,duracion,buffer_limpieza,costo)
                     VALUES (?,?,?,?,?)''', servicios)

    conn.commit()
    conn.close()


def audit(usuario_id, accion, detalle='', ip=''):
    conn = get_db()
    conn.execute('INSERT INTO auditoria (usuario_id,accion,detalle,ip) VALUES (?,?,?,?)',
                 (usuario_id, accion, detalle, ip))
    conn.commit()
    conn.close()
