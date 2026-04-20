# Clínica Padre Pío — Sistema de Gestión Dental

Sistema web de gestión de citas y pacientes para una clínica dental, desarrollado con **Flask** y **SQLite**.

## Tecnologías

- Python 3 + Flask
- SQLite (base de datos local)
- Bootstrap 5 + Bootstrap Icons
- Jinja2 (templates)

## Cómo ejecutar

```bash
pip install -r requirements.txt
python app.py
```

Luego abre `http://127.0.0.1:5000` en tu navegador.

**Credenciales por defecto:**
- Usuario: `admin@clinica.com`
- Contraseña: `admin123`

## Roles del sistema

| Rol | Acceso |
|-----|--------|
| **Administrador** | Gestión completa: usuarios, servicios, horarios, reportes |
| **Recepcionista** | Registro de pacientes, agendamiento y gestión de citas |
| **Doctor** | Vista de su agenda, marcar asistencia, observaciones clínicas, historial de pacientes |
| **Cajero** | Búsqueda de citas atendidas, registro de pagos, comprobantes |

## Módulos implementados

### Pacientes
- Registro con DNI, datos personales y contacto
- Estado **activo / inactivo** (para pacientes que fallecen, se mudan, etc.)
- Filtrado por estado en la lista
- Historial de citas por paciente (visible para el doctor asignado)

### Citas
- Agendamiento con selección de doctor, servicio, fecha y hora
- Estados: `confirmada` → `atendida` → `pagada` / `cancelada` / `no_asistio`
- Reprogramación y cancelación
- Observaciones clínicas al marcar asistencia

### Doctores
- Vista de agenda diaria propia
- Página "Mi Horario" con turnos y servicios asignados
- Acceso restringido al historial de sus propios pacientes

### Cajero
- Búsqueda de citas por código o DNI
- Registro de pago con método (efectivo, tarjeta, Yape, Plin, transferencia)
- Generación de boleta / factura
- Dashboard con ingresos y pagos del día

### Administrador
- CRUD de usuarios (con roles y estado activo/inactivo)
- CRUD de servicios dentales
- Gestión de horarios por doctor
- Reportes exportables de citas y pagos
- Bitácora de auditoría de acciones

## Estructura del proyecto

```
clinica-padre-pio/
├── app.py              # Rutas y lógica principal
├── database.py         # Inicialización de BD y función audit
├── requirements.txt    # Dependencias
└── templates/
    ├── base.html
    ├── login.html
    ├── admin/
    ├── recepcionista/
    ├── doctor/
    └── cajero/
```
