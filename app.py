from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import hashlib
import sqlite3
from datetime import datetime, date
from database import get_db, init_db, audit
from functools import wraps
import uuid

app = Flask(__name__)
app.secret_key = 'padre-pio-clinica-2025-secret'


# ─── Helpers ────────────────────────────────────────────────────────────────

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'usuario_id' not in session:
                flash('Debes iniciar sesión.', 'warning')
                return redirect(url_for('login'))
            if roles and session.get('rol') not in roles:
                flash('No tienes permiso para acceder a esta sección.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def gen_codigo():
    return 'C-' + str(uuid.uuid4())[:8].upper()


def validar_telefono(tel):
    """Retorna True si el teléfono es vacío/None o tiene solo dígitos y máximo 9."""
    if not tel:
        return True
    digits = tel.strip()
    return digits.isdigit() and len(digits) <= 9


# ─── Auth ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        dni = request.form.get('dni', '').strip()
        pw = request.form.get('contrasena', '')
        db = get_db()
        user = db.execute('SELECT * FROM usuarios WHERE dni=? AND estado="activo"', (dni,)).fetchone()
        if user and user['contrasena'] == hash_pw(pw):
            session['usuario_id'] = user['id']
            session['nombre'] = user['nombres'] + ' ' + user['apellidos']
            session['rol'] = user['rol']
            audit(user['id'], 'LOGIN', 'Inicio de sesión exitoso', request.remote_addr)
            db.close()
            return redirect(url_for('dashboard'))
        audit(None, 'LOGIN_FALLIDO', f'DNI: {dni}', request.remote_addr)
        db.close()
        flash('DNI o contraseña incorrectos.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    audit(session.get('usuario_id'), 'LOGOUT', '', request.remote_addr)
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required()
def dashboard():
    rol = session['rol']
    db = get_db()
    ctx = {}
    if rol == 'administrador':
        ctx['total_usuarios'] = db.execute("SELECT COUNT(*) FROM usuarios WHERE estado='activo'").fetchone()[0]
        ctx['total_servicios'] = db.execute("SELECT COUNT(*) FROM servicios WHERE estado='activo'").fetchone()[0]
        ctx['citas_hoy'] = db.execute("SELECT COUNT(*) FROM citas WHERE fecha=? AND estado!='cancelada'", (date.today().isoformat(),)).fetchone()[0]
        ctx['ingresos_hoy'] = db.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE date(fecha)=?", (date.today().isoformat(),)).fetchone()[0]
    elif rol == 'recepcionista':
        ctx['citas_hoy'] = db.execute("SELECT COUNT(*) FROM citas WHERE fecha=? AND estado='confirmada'", (date.today().isoformat(),)).fetchone()[0]
        ctx['total_pacientes'] = db.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
        ctx['citas_pendientes'] = db.execute("SELECT COUNT(*) FROM citas WHERE estado='confirmada'").fetchone()[0]
    elif rol == 'doctor':
        ctx['mis_citas_hoy'] = db.execute("SELECT COUNT(*) FROM citas WHERE doctor_id=? AND fecha=? AND estado='confirmada'", (session['usuario_id'], date.today().isoformat())).fetchone()[0]
        ctx['total_atendidas'] = db.execute("SELECT COUNT(*) FROM citas WHERE doctor_id=? AND estado='atendida'", (session['usuario_id'],)).fetchone()[0]
    elif rol == 'cajero':
        ctx['pendientes_pago'] = db.execute("SELECT COUNT(*) FROM citas WHERE estado IN ('confirmada','atendida')").fetchone()[0]
        ctx['pagos_hoy'] = db.execute("SELECT COUNT(*) FROM pagos WHERE date(fecha)=?", (date.today().isoformat(),)).fetchone()[0]
        ctx['ingresos_hoy'] = db.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE date(fecha)=?", (date.today().isoformat(),)).fetchone()[0]
        ctx['fecha_hoy'] = date.today().isoformat()
    db.close()
    return render_template('dashboard.html', **ctx)


# ─── ADMIN: Usuarios ─────────────────────────────────────────────────────────

@app.route('/admin/usuarios')
@login_required(['administrador'])
def admin_usuarios():
    db = get_db()
    usuarios = db.execute("SELECT * FROM usuarios ORDER BY fecha_creacion DESC").fetchall()
    db.close()
    return render_template('admin/usuarios.html', usuarios=usuarios)


@app.route('/admin/usuarios/crear', methods=['GET', 'POST'])
@login_required(['administrador'])
def admin_crear_usuario():
    db = get_db()
    servicios = db.execute("SELECT * FROM servicios WHERE estado='activo'").fetchall()
    if request.method == 'POST':
        f = request.form
        try:
            if not validar_telefono(f.get('telefono')):
                flash('El teléfono debe tener solo dígitos y máximo 9 caracteres.', 'danger')
                db.close()
                return render_template('admin/crear_usuario.html', servicios=servicios)
            pw = hash_pw(f['contrasena'])
            cur = db.execute('''INSERT INTO usuarios (dni,nombres,apellidos,correo,telefono,rol,contrasena,especialidad)
                                VALUES (?,?,?,?,?,?,?,?)''',
                             (f['dni'], f['nombres'], f['apellidos'], f['correo'],
                              f.get('telefono'), f['rol'], pw, f.get('especialidad')))
            uid = cur.lastrowid
            if f['rol'] == 'doctor':
                for sid in request.form.getlist('servicios'):
                    db.execute('INSERT OR IGNORE INTO doctor_servicio VALUES (?,?)', (uid, sid))
            db.commit()
            audit(session['usuario_id'], 'CREAR_USUARIO', f"DNI: {f['dni']}", request.remote_addr)
            flash('Usuario creado correctamente.', 'success')
            return redirect(url_for('admin_usuarios'))
        except sqlite3.IntegrityError as e:
            flash('Error: DNI o correo ya registrado.', 'danger')
    db.close()
    return render_template('admin/crear_usuario.html', servicios=servicios)


@app.route('/admin/usuarios/<int:uid>/editar', methods=['GET', 'POST'])
@login_required(['administrador'])
def admin_editar_usuario(uid):
    db = get_db()
    user = db.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone()
    servicios = db.execute("SELECT * FROM servicios WHERE estado='activo'").fetchall()
    seleccionados = [r['servicio_id'] for r in db.execute("SELECT servicio_id FROM doctor_servicio WHERE doctor_id=?", (uid,)).fetchall()]
    if request.method == 'POST':
        f = request.form
        if not validar_telefono(f.get('telefono')):
            flash('El teléfono debe tener solo dígitos y máximo 9 caracteres.', 'danger')
            db.close()
            return render_template('admin/editar_usuario.html', user=user, servicios=servicios, seleccionados=seleccionados)
        db.execute('''UPDATE usuarios SET nombres=?,apellidos=?,correo=?,telefono=?,rol=?,especialidad=?,estado=?
                      WHERE id=?''',
                   (f['nombres'], f['apellidos'], f['correo'], f.get('telefono'),
                    f['rol'], f.get('especialidad'), f['estado'], uid))
        if f.get('nueva_contrasena'):
            db.execute('UPDATE usuarios SET contrasena=? WHERE id=?', (hash_pw(f['nueva_contrasena']), uid))
        db.execute('DELETE FROM doctor_servicio WHERE doctor_id=?', (uid,))
        if f['rol'] == 'doctor':
            for sid in request.form.getlist('servicios'):
                db.execute('INSERT OR IGNORE INTO doctor_servicio VALUES (?,?)', (uid, sid))
        db.commit()
        audit(session['usuario_id'], 'EDITAR_USUARIO', f"ID: {uid}", request.remote_addr)
        flash('Usuario actualizado.', 'success')
        return redirect(url_for('admin_usuarios'))
    db.close()
    return render_template('admin/editar_usuario.html', user=user, servicios=servicios, seleccionados=seleccionados)


@app.route('/admin/usuarios/<int:uid>/eliminar', methods=['POST'])
@login_required(['administrador'])
def admin_eliminar_usuario(uid):
    db = get_db()
    db.execute("UPDATE usuarios SET estado='inactivo' WHERE id=?", (uid,))
    db.commit()
    audit(session['usuario_id'], 'ELIMINAR_USUARIO', f"ID: {uid}", request.remote_addr)
    db.close()
    flash('Usuario desactivado.', 'warning')
    return redirect(url_for('admin_usuarios'))


# ─── ADMIN: Servicios ─────────────────────────────────────────────────────────

@app.route('/admin/servicios')
@login_required(['administrador'])
def admin_servicios():
    db = get_db()
    servicios = db.execute("SELECT * FROM servicios ORDER BY nombre").fetchall()
    db.close()
    return render_template('admin/servicios.html', servicios=servicios)


@app.route('/admin/servicios/crear', methods=['POST'])
@login_required(['administrador'])
def admin_crear_servicio():
    f = request.form
    db = get_db()
    try:
        db.execute('INSERT INTO servicios (nombre,descripcion,duracion,buffer_limpieza,costo) VALUES (?,?,?,?,?)',
                   (f['nombre'], f.get('descripcion'), int(f['duracion']), int(f.get('buffer', 0)), float(f['costo'])))
        db.commit()
        audit(session['usuario_id'], 'CREAR_SERVICIO', f['nombre'], request.remote_addr)
        flash('Servicio registrado correctamente.', 'success')
    except sqlite3.IntegrityError:
        flash('Servicio duplicado.', 'danger')
    db.close()
    return redirect(url_for('admin_servicios'))


@app.route('/admin/servicios/<int:sid>/editar', methods=['POST'])
@login_required(['administrador'])
def admin_editar_servicio(sid):
    f = request.form
    db = get_db()
    db.execute('UPDATE servicios SET nombre=?,descripcion=?,duracion=?,buffer_limpieza=?,costo=?,estado=? WHERE id=?',
               (f['nombre'], f.get('descripcion'), int(f['duracion']), int(f.get('buffer', 0)), float(f['costo']), f['estado'], sid))
    db.commit()
    audit(session['usuario_id'], 'EDITAR_SERVICIO', f"ID: {sid}", request.remote_addr)
    db.close()
    flash('Servicio actualizado.', 'success')
    return redirect(url_for('admin_servicios'))


@app.route('/admin/servicios/<int:sid>/eliminar', methods=['POST'])
@login_required(['administrador'])
def admin_eliminar_servicio(sid):
    db = get_db()
    en_uso = db.execute("SELECT COUNT(*) FROM citas WHERE servicio_id=? AND estado='confirmada'", (sid,)).fetchone()[0]
    if en_uso:
        flash('No se puede eliminar: el servicio tiene citas activas.', 'danger')
    else:
        db.execute("UPDATE servicios SET estado='inactivo' WHERE id=?", (sid,))
        db.commit()
        audit(session['usuario_id'], 'ELIMINAR_SERVICIO', f"ID: {sid}", request.remote_addr)
        flash('Servicio desactivado.', 'warning')
    db.close()
    return redirect(url_for('admin_servicios'))


# ─── ADMIN: Horarios ──────────────────────────────────────────────────────────

@app.route('/admin/horarios')
@login_required(['administrador'])
def admin_horarios():
    db = get_db()
    doctores = db.execute("SELECT * FROM usuarios WHERE rol='doctor' AND estado='activo'").fetchall()
    db.close()
    return render_template('admin/horarios.html', doctores=doctores)


@app.route('/admin/horarios/<int:did>')
@login_required(['administrador'])
def admin_horarios_doctor(did):
    db = get_db()
    doctor = db.execute("SELECT * FROM usuarios WHERE id=?", (did,)).fetchone()
    horarios = db.execute("SELECT * FROM horarios WHERE doctor_id=? ORDER BY dia,hora_inicio", (did,)).fetchall()
    db.close()
    return jsonify({'doctor': dict(doctor), 'horarios': [dict(h) for h in horarios]})


@app.route('/admin/horarios/crear', methods=['POST'])
@login_required(['administrador'])
def admin_crear_horario():
    f = request.form
    db = get_db()
    solapado = db.execute('''SELECT id FROM horarios WHERE doctor_id=? AND dia=?
        AND NOT (hora_fin <= ? OR hora_inicio >= ?)''',
        (f['doctor_id'], f['dia'], f['hora_inicio'], f['hora_fin'])).fetchone()
    if solapado:
        flash('El horario se superpone con uno existente.', 'danger')
    elif f['hora_fin'] <= f['hora_inicio']:
        flash('La hora de fin debe ser mayor a la hora de inicio.', 'danger')
    else:
        db.execute('INSERT INTO horarios (doctor_id,dia,hora_inicio,hora_fin) VALUES (?,?,?,?)',
                   (f['doctor_id'], f['dia'], f['hora_inicio'], f['hora_fin']))
        db.commit()
        audit(session['usuario_id'], 'CREAR_HORARIO', f"Doctor ID: {f['doctor_id']}", request.remote_addr)
        flash('Horario creado correctamente.', 'success')
    db.close()
    return redirect(url_for('admin_horarios'))


@app.route('/admin/horarios/<int:hid>/eliminar', methods=['POST'])
@login_required(['administrador'])
def admin_eliminar_horario(hid):
    db = get_db()
    db.execute("DELETE FROM horarios WHERE id=?", (hid,))
    db.commit()
    audit(session['usuario_id'], 'ELIMINAR_HORARIO', f"ID: {hid}", request.remote_addr)
    db.close()
    flash('Horario eliminado.', 'warning')
    return redirect(url_for('admin_horarios'))


# ─── ADMIN: Reportes ─────────────────────────────────────────────────────────

@app.route('/admin/reportes', methods=['GET', 'POST'])
@login_required(['administrador'])
def admin_reportes():
    if request.method == 'POST' and request.form.get('accion') == 'verificar':
        pw = request.form.get('contrasena')
        db = get_db()
        admin = db.execute("SELECT contrasena FROM usuarios WHERE id=?", (session['usuario_id'],)).fetchone()
        db.close()
        if admin and admin['contrasena'] == hash_pw(pw):
            session['reportes_auth'] = True
            return redirect(url_for('admin_reportes'))
        flash('Contraseña incorrecta.', 'danger')
        return render_template('admin/reportes.html', auth=False)

    if not session.get('reportes_auth'):
        return render_template('admin/reportes.html', auth=False)

    db = get_db()
    tipo = request.args.get('tipo', 'citas')
    desde = request.args.get('desde', date.today().replace(day=1).isoformat())
    hasta = request.args.get('hasta', date.today().isoformat())

    datos = []
    totales = {}
    if tipo == 'citas':
        datos = db.execute('''SELECT c.codigo, p.nombres||' '||p.apellidos AS paciente,
            u.nombres||' '||u.apellidos AS doctor, s.nombre AS servicio,
            c.fecha, c.hora, c.estado, c.monto
            FROM citas c
            JOIN pacientes p ON c.paciente_id=p.id
            JOIN usuarios u ON c.doctor_id=u.id
            JOIN servicios s ON c.servicio_id=s.id
            WHERE c.fecha BETWEEN ? AND ?
            ORDER BY c.fecha DESC''', (desde, hasta)).fetchall()
        totales['total'] = len(datos)
    elif tipo == 'pagos':
        datos = db.execute('''SELECT pg.fecha, c.codigo, p.nombres||' '||p.apellidos AS paciente,
            pg.monto, pg.metodo_pago, pg.comprobante_tipo,
            u.nombres||' '||u.apellidos AS cajero
            FROM pagos pg
            JOIN citas c ON pg.cita_id=c.id
            JOIN pacientes p ON c.paciente_id=p.id
            JOIN usuarios u ON pg.cajero_id=u.id
            WHERE date(pg.fecha) BETWEEN ? AND ?
            ORDER BY pg.fecha DESC''', (desde, hasta)).fetchall()
        totales['total'] = sum(r['monto'] for r in datos)
    elif tipo == 'auditoria':
        datos = db.execute('''SELECT a.fecha, u.nombres||' '||u.apellidos AS usuario,
            a.accion, a.detalle, a.ip
            FROM auditoria a
            LEFT JOIN usuarios u ON a.usuario_id=u.id
            WHERE date(a.fecha) BETWEEN ? AND ?
            ORDER BY a.fecha DESC LIMIT 500''', (desde, hasta)).fetchall()

    db.close()
    return render_template('admin/reportes.html', auth=True, datos=datos, tipo=tipo,
                           desde=desde, hasta=hasta, totales=totales)


@app.route('/admin/reportes/logout')
@login_required(['administrador'])
def admin_reportes_logout():
    session.pop('reportes_auth', None)
    return redirect(url_for('admin_reportes'))


# ─── RECEPCIONISTA: Pacientes ─────────────────────────────────────────────────

@app.route('/pacientes')
@login_required(['recepcionista', 'administrador'])
def pacientes():
    db = get_db()
    q = request.args.get('q', '').strip()
    filtro = request.args.get('filtro', 'activo')
    conditions = []
    params = []
    if q:
        conditions.append("(dni LIKE ? OR nombres LIKE ? OR apellidos LIKE ?)")
        params += [f'%{q}%', f'%{q}%', f'%{q}%']
    if filtro in ('activo', 'inactivo'):
        conditions.append("estado = ?")
        params.append(filtro)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = db.execute(f"SELECT * FROM pacientes {where} ORDER BY fecha_registro DESC", params).fetchall()
    db.close()
    return render_template('recepcionista/pacientes.html', pacientes=rows, q=q, filtro=filtro)


@app.route('/pacientes/crear', methods=['GET', 'POST'])
@login_required(['recepcionista', 'administrador'])
def crear_paciente():
    if request.method == 'POST':
        f = request.form
        db = get_db()
        if not validar_telefono(f.get('telefono')):
            flash('El teléfono debe tener solo dígitos y máximo 9 caracteres.', 'danger')
            db.close()
            return render_template('recepcionista/crear_paciente.html')
        try:
            db.execute('''INSERT INTO pacientes (dni,nombres,apellidos,telefono,correo,direccion,fecha_nacimiento,sexo)
                          VALUES (?,?,?,?,?,?,?,?)''',
                       (f['dni'], f['nombres'], f['apellidos'], f.get('telefono'),
                        f.get('correo'), f.get('direccion'), f.get('fecha_nacimiento'), f.get('sexo')))
            db.commit()
            audit(session['usuario_id'], 'REGISTRAR_PACIENTE', f"DNI: {f['dni']}", request.remote_addr)
            flash('Paciente registrado correctamente.', 'success')
            db.close()
            return redirect(url_for('pacientes'))
        except sqlite3.IntegrityError:
            flash('El paciente ya está registrado con ese DNI.', 'danger')
            db.close()
    return render_template('recepcionista/crear_paciente.html')


@app.route('/pacientes/<int:pid>/editar', methods=['GET', 'POST'])
@login_required(['recepcionista', 'administrador'])
def editar_paciente(pid):
    db = get_db()
    paciente = db.execute("SELECT * FROM pacientes WHERE id=?", (pid,)).fetchone()
    if request.method == 'POST':
        f = request.form
        if not validar_telefono(f.get('telefono')):
            flash('El teléfono debe tener solo dígitos y máximo 9 caracteres.', 'danger')
            db.close()
            return render_template('recepcionista/editar_paciente.html', paciente=paciente)
        db.execute('''UPDATE pacientes SET telefono=?,correo=?,direccion=?,fecha_nacimiento=?,sexo=?
                      WHERE id=?''',
                   (f.get('telefono'), f.get('correo'), f.get('direccion'),
                    f.get('fecha_nacimiento'), f.get('sexo'), pid))
        db.commit()
        audit(session['usuario_id'], 'ACTUALIZAR_PACIENTE', f"ID: {pid}", request.remote_addr)
        flash('Datos actualizados correctamente.', 'success')
        db.close()
        return redirect(url_for('pacientes'))
    db.close()
    return render_template('recepcionista/editar_paciente.html', paciente=paciente)


@app.route('/pacientes/<int:pid>/estado', methods=['POST'])
@login_required(['recepcionista', 'administrador'])
def cambiar_estado_paciente(pid):
    db = get_db()
    paciente = db.execute("SELECT * FROM pacientes WHERE id=?", (pid,)).fetchone()
    if paciente:
        nuevo = 'inactivo' if paciente['estado'] == 'activo' else 'activo'
        db.execute("UPDATE pacientes SET estado=? WHERE id=?", (nuevo, pid))
        db.commit()
        audit(session['usuario_id'], 'CAMBIAR_ESTADO_PACIENTE', f"ID: {pid} → {nuevo}", request.remote_addr)
        flash(f"Paciente marcado como {nuevo}.", 'info')
    db.close()
    return redirect(url_for('pacientes', filtro=request.args.get('filtro', 'activo'), q=request.args.get('q', '')))


@app.route('/pacientes/<int:pid>/eliminar', methods=['POST'])
@login_required(['recepcionista', 'administrador'])
def eliminar_paciente(pid):
    db = get_db()
    citas_activas = db.execute("SELECT COUNT(*) FROM citas WHERE paciente_id=? AND estado='confirmada'", (pid,)).fetchone()[0]
    if citas_activas:
        flash('No se puede eliminar: el paciente tiene citas activas.', 'danger')
    else:
        db.execute("DELETE FROM pacientes WHERE id=?", (pid,))
        db.commit()
        audit(session['usuario_id'], 'ELIMINAR_PACIENTE', f"ID: {pid}", request.remote_addr)
        flash('Paciente eliminado.', 'warning')
    db.close()
    return redirect(url_for('pacientes'))


# ─── RECEPCIONISTA: Citas ─────────────────────────────────────────────────────

@app.route('/citas')
@login_required(['recepcionista', 'administrador', 'cajero'])
def citas():
    db = get_db()
    q = request.args.get('q', '').strip()
    estado = request.args.get('estado', '')
    fecha = request.args.get('fecha', date.today().isoformat())
    sql = '''SELECT c.*, p.nombres||' '||p.apellidos AS paciente, p.dni AS paciente_dni,
             u.nombres||' '||u.apellidos AS doctor, s.nombre AS servicio
             FROM citas c
             JOIN pacientes p ON c.paciente_id=p.id
             JOIN usuarios u ON c.doctor_id=u.id
             JOIN servicios s ON c.servicio_id=s.id
             WHERE 1=1'''
    params = []
    if q:
        sql += " AND (c.codigo LIKE ? OR p.dni LIKE ? OR p.nombres LIKE ?)"
        params += [f'%{q}%', f'%{q}%', f'%{q}%']
    if estado:
        sql += " AND c.estado=?"
        params.append(estado)
    if fecha:
        sql += " AND c.fecha=?"
        params.append(fecha)
    sql += " ORDER BY c.fecha DESC, c.hora ASC"
    rows = db.execute(sql, params).fetchall()
    db.close()
    return render_template('recepcionista/citas.html', citas=rows, q=q, estado=estado, fecha=fecha)


@app.route('/citas/crear', methods=['GET', 'POST'])
@login_required(['recepcionista', 'administrador'])
def crear_cita():
    db = get_db()
    servicios = db.execute("SELECT * FROM servicios WHERE estado='activo' ORDER BY nombre").fetchall()
    if request.method == 'POST':
        f = request.form
        codigo = gen_codigo()
        try:
            db.execute('''INSERT INTO citas (codigo,paciente_id,doctor_id,servicio_id,fecha,hora,monto,observaciones,creado_por)
                          VALUES (?,?,?,?,?,?,?,?,?)''',
                       (codigo, f['paciente_id'], f['doctor_id'], f['servicio_id'],
                        f['fecha'], f['hora'], float(f['monto']), f.get('observaciones'), session['usuario_id']))
            db.commit()
            audit(session['usuario_id'], 'CREAR_CITA', f"Código: {codigo}", request.remote_addr)
            flash(f'Cita creada exitosamente. Código: {codigo}', 'success')
            db.close()
            return redirect(url_for('citas'))
        except Exception as e:
            flash(f'Error al crear cita: {e}', 'danger')
    db.close()
    return render_template('recepcionista/crear_cita.html', servicios=servicios, now=date.today().isoformat())


@app.route('/citas/<int:cid>/cancelar', methods=['POST'])
@login_required(['recepcionista', 'administrador'])
def cancelar_cita(cid):
    db = get_db()
    db.execute("UPDATE citas SET estado='cancelada' WHERE id=? AND estado='confirmada'", (cid,))
    db.commit()
    audit(session['usuario_id'], 'CANCELAR_CITA', f"ID: {cid}", request.remote_addr)
    db.close()
    flash('Cita cancelada.', 'warning')
    return redirect(url_for('citas'))


@app.route('/citas/<int:cid>/reprogramar', methods=['GET', 'POST'])
@login_required(['recepcionista', 'administrador'])
def reprogramar_cita(cid):
    db = get_db()
    cita = db.execute('''SELECT c.*, u.nombres||' '||u.apellidos AS doctor, s.nombre AS servicio,
                         p.nombres||' '||p.apellidos AS paciente
                         FROM citas c JOIN usuarios u ON c.doctor_id=u.id
                         JOIN servicios s ON c.servicio_id=s.id
                         JOIN pacientes p ON c.paciente_id=p.id
                         WHERE c.id=?''', (cid,)).fetchone()
    if request.method == 'POST':
        f = request.form
        db.execute("UPDATE citas SET fecha=?,hora=? WHERE id=?", (f['fecha'], f['hora'], cid))
        db.commit()
        audit(session['usuario_id'], 'REPROGRAMAR_CITA', f"ID: {cid}", request.remote_addr)
        flash('Cita reprogramada correctamente.', 'success')
        db.close()
        return redirect(url_for('citas'))
    db.close()
    db.close()
    return render_template('recepcionista/reprogramar_cita.html', cita=cita, now=date.today().isoformat())


# ─── RECEPCIONISTA: Horarios consulta ────────────────────────────────────────

@app.route('/horarios')
@login_required(['recepcionista', 'administrador'])
def consultar_horarios():
    db = get_db()
    servicios = db.execute("SELECT * FROM servicios WHERE estado='activo' ORDER BY nombre").fetchall()
    db.close()
    return render_template('recepcionista/horarios.html', servicios=servicios)


# ─── API helpers ──────────────────────────────────────────────────────────────

@app.route('/api/paciente/<dni>')
@login_required()
def api_paciente(dni):
    db = get_db()
    p = db.execute("SELECT * FROM pacientes WHERE dni=?", (dni,)).fetchone()
    db.close()
    if p:
        return jsonify({'ok': True, 'paciente': dict(p)})
    return jsonify({'ok': False})


@app.route('/api/doctores/<int:sid>')
@login_required()
def api_doctores_servicio(sid):
    db = get_db()
    docs = db.execute('''SELECT u.id, u.nombres||' '||u.apellidos AS nombre, u.especialidad
                         FROM usuarios u
                         JOIN doctor_servicio ds ON u.id=ds.doctor_id
                         WHERE ds.servicio_id=? AND u.estado='activo' ''', (sid,)).fetchall()
    db.close()
    return jsonify([dict(d) for d in docs])


@app.route('/api/horarios/<int:did>')
@login_required()
def api_horarios_doctor(did):
    db = get_db()
    horarios = db.execute("SELECT * FROM horarios WHERE doctor_id=? ORDER BY dia,hora_inicio", (did,)).fetchall()
    citas_ocupadas = db.execute("SELECT fecha, hora FROM citas WHERE doctor_id=? AND estado='confirmada'", (did,)).fetchall()
    db.close()
    ocupadas = [{'fecha': r['fecha'], 'hora': r['hora']} for r in citas_ocupadas]
    return jsonify({'horarios': [dict(h) for h in horarios], 'ocupadas': ocupadas})


@app.route('/api/servicio/<int:sid>/costo')
@login_required()
def api_costo_servicio(sid):
    db = get_db()
    s = db.execute("SELECT costo FROM servicios WHERE id=?", (sid,)).fetchone()
    db.close()
    return jsonify({'costo': s['costo'] if s else 0})


# ─── DOCTOR: Citas ────────────────────────────────────────────────────────────

@app.route('/doctor/citas')
@login_required(['doctor'])
def doctor_citas():
    db = get_db()
    fecha = request.args.get('fecha', date.today().isoformat())
    estado = request.args.get('estado', '')
    sql = '''SELECT c.*, p.nombres||' '||p.apellidos AS paciente,
             p.dni AS paciente_dni, p.telefono, s.nombre AS servicio
             FROM citas c
             JOIN pacientes p ON c.paciente_id=p.id
             JOIN servicios s ON c.servicio_id=s.id
             WHERE c.doctor_id=?'''
    params = [session['usuario_id']]
    if fecha:
        sql += " AND c.fecha=?"
        params.append(fecha)
    if estado:
        sql += " AND c.estado=?"
        params.append(estado)
    sql += " ORDER BY c.hora ASC"
    citas = db.execute(sql, params).fetchall()
    db.close()
    return render_template('doctor/citas.html', citas=citas, fecha=fecha, estado=estado)


@app.route('/doctor/citas/<int:cid>/asistencia', methods=['POST'])
@login_required(['doctor'])
def doctor_asistencia(cid):
    nuevo_estado = request.form.get('estado')
    if nuevo_estado not in ('atendida', 'no_asistio'):
        flash('Estado inválido.', 'danger')
        return redirect(url_for('doctor_citas'))
    observaciones = request.form.get('observaciones', '').strip() or None
    db = get_db()
    if observaciones:
        db.execute("UPDATE citas SET estado=?, observaciones=? WHERE id=? AND doctor_id=?",
                   (nuevo_estado, observaciones, cid, session['usuario_id']))
    else:
        db.execute("UPDATE citas SET estado=? WHERE id=? AND doctor_id=?",
                   (nuevo_estado, cid, session['usuario_id']))
    db.commit()
    audit(session['usuario_id'], 'MARCAR_ASISTENCIA', f"Cita ID: {cid} → {nuevo_estado}", request.remote_addr)
    db.close()
    flash('Asistencia registrada.', 'success')
    return redirect(url_for('doctor_citas'))


@app.route('/doctor/mi-horario')
@login_required(['doctor'])
def doctor_mi_horario():
    db = get_db()
    horarios = db.execute(
        "SELECT * FROM horarios WHERE doctor_id=? ORDER BY dia,hora_inicio",
        (session['usuario_id'],)
    ).fetchall()
    servicios = db.execute(
        '''SELECT s.nombre FROM servicios s
           JOIN doctor_servicio ds ON s.id=ds.servicio_id
           WHERE ds.doctor_id=? AND s.estado='activo' ''',
        (session['usuario_id'],)
    ).fetchall()
    db.close()
    dias_orden = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
    return render_template('doctor/mi_horario.html', horarios=horarios,
                           servicios=servicios, dias_orden=dias_orden)


@app.route('/doctor/pacientes/<int:pid>')
@login_required(['doctor'])
def doctor_historial_paciente(pid):
    db = get_db()
    # Verifica que el doctor tenga al menos una cita con este paciente
    permiso = db.execute(
        "SELECT id FROM citas WHERE doctor_id=? AND paciente_id=? LIMIT 1",
        (session['usuario_id'], pid)
    ).fetchone()
    if not permiso:
        db.close()
        flash('No tienes acceso al historial de este paciente.', 'danger')
        return redirect(url_for('doctor_citas'))
    paciente = db.execute("SELECT * FROM pacientes WHERE id=?", (pid,)).fetchone()
    citas = db.execute(
        '''SELECT c.*, s.nombre AS servicio, c.observaciones
           FROM citas c
           JOIN servicios s ON c.servicio_id=s.id
           WHERE c.paciente_id=? AND c.doctor_id=?
           ORDER BY c.fecha DESC, c.hora DESC''',
        (pid, session['usuario_id'])
    ).fetchall()
    db.close()
    return render_template('doctor/historial_paciente.html', paciente=paciente, citas=citas)


# ─── CAJERO: Pagos ────────────────────────────────────────────────────────────

@app.route('/cajero/pago', methods=['GET', 'POST'])
@login_required(['cajero', 'administrador'])
def cajero_pago():
    cita = None
    q = request.args.get('q', '').strip()
    db = get_db()
    if q:
        cita = db.execute('''SELECT c.*, p.nombres||' '||p.apellidos AS paciente,
                             p.correo, u.nombres||' '||u.apellidos AS doctor, s.nombre AS servicio
                             FROM citas c
                             JOIN pacientes p ON c.paciente_id=p.id
                             JOIN usuarios u ON c.doctor_id=u.id
                             JOIN servicios s ON c.servicio_id=s.id
                             WHERE (c.codigo=? OR p.dni=?) AND c.estado IN ('confirmada','atendida')
                             LIMIT 1''', (q, q)).fetchone()
        if not cita:
            flash('No se encontró cita pendiente de pago con ese código/DNI.', 'warning')

    if request.method == 'POST':
        f = request.form
        cita_id = f['cita_id']
        monto = float(f['monto'])
        metodo = f['metodo_pago']
        cambio = float(f.get('cambio', 0))
        num_op = f.get('numero_operacion', '')
        comp = f.get('comprobante_tipo', 'boleta')
        db.execute('''INSERT INTO pagos (cita_id,cajero_id,monto,metodo_pago,numero_operacion,cambio,comprobante_tipo)
                      VALUES (?,?,?,?,?,?,?)''',
                   (cita_id, session['usuario_id'], monto, metodo, num_op, cambio, comp))
        db.execute("UPDATE citas SET estado='pagada' WHERE id=?", (cita_id,))
        db.commit()
        audit(session['usuario_id'], 'REGISTRAR_PAGO', f"Cita ID: {cita_id} | S/{monto}", request.remote_addr)
        cita_info = db.execute('''SELECT c.*, p.nombres||' '||p.apellidos AS paciente,
                                  p.correo, u.nombres||' '||u.apellidos AS doctor, s.nombre AS servicio
                                  FROM citas c JOIN pacientes p ON c.paciente_id=p.id
                                  JOIN usuarios u ON c.doctor_id=u.id
                                  JOIN servicios s ON c.servicio_id=s.id
                                  WHERE c.id=?''', (cita_id,)).fetchone()
        db.close()
        flash('Pago registrado exitosamente.', 'success')
        return render_template('cajero/comprobante.html', cita=cita_info, monto=monto,
                               metodo=metodo, cambio=cambio, comp=comp, num_op=num_op,
                               fecha_pago=datetime.now().strftime('%d/%m/%Y %H:%M'))
    db.close()
    return render_template('cajero/pago.html', cita=cita, q=q)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
