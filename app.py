from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
import datetime
import re
from sqlalchemy import func, text

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///logs.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'mysecret' # Change this to a random secret key
db = SQLAlchemy(app)
admin = Admin(app, name='Property Website')

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<Employee {self.name}>'

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(100), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f'<Log {self.employee_id}>'

class Call(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    employee = db.relationship(
        'Employee',
        backref=db.backref('calls', lazy=True, cascade='all, delete-orphan')
    )
    person_name = db.Column(db.String(100), nullable=False)
    person_number = db.Column(db.String(20), nullable=False)
    answered = db.Column(db.Boolean, default=False, nullable=False)
    outcome = db.Column(db.Text, nullable=True)
    property_value = db.Column(db.String(100), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f'<Call {self.person_name}>'


class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Setting {self.key}>'

admin.add_view(ModelView(Employee, db.session))
admin.add_view(ModelView(Log, db.session))
admin.add_view(ModelView(Call, db.session))

def _ensure_schema_updates():
    with app.app_context():
        db.create_all()
        existing_columns = db.session.execute(text("PRAGMA table_info(call)"))
        has_property_value = any(row[1] == 'property_value' for row in existing_columns)
        if not has_property_value:
            db.session.execute(text("ALTER TABLE call ADD COLUMN property_value TEXT"))
            db.session.commit()


_ensure_schema_updates()


_CURRENCY_STRIPPER = re.compile(r'[^0-9,.-]')


def _parse_property_value(raw_value):
    if not raw_value:
        return 0.0
    cleaned = _CURRENCY_STRIPPER.sub('', raw_value)
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(',', '')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _format_currency(amount):
    if amount is None:
        return 'R 0'
    return f"R {amount:,.0f}"


def get_setting_value(key, default=''):
    setting = Setting.query.filter_by(key=key).first()
    return setting.value if setting else default


def set_setting_value(key, value):
    setting = Setting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()

# ... existing code ...
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        employee_name = request.form['employee_name'].strip()
        password = request.form['password'].strip()

        if employee_name.lower() == 'admin':
            if password == '2025':
                session.clear()
                session['logged_in'] = True
                session['is_admin'] = True
                flash('Welcome, Admin')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid Admin Credentials')
                return redirect(url_for('login'))

        employee = Employee.query.filter_by(name=employee_name).first()
        if employee and employee.password == password:
            session['logged_in'] = True
            session['employee_id'] = employee.id
            session['is_admin'] = False
            new_log = Log(employee_id=employee.id)
            db.session.add(new_log)
            db.session.commit()
            flash('You were successfully logged in')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid Credentials')
    login_message = get_setting_value('login_message', 'Please log in to continue.')
    return render_template('login.html', login_message=login_message)

from flask import jsonify
# ... existing code ...
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    is_admin = session.get('is_admin')
    employee_id = session.get('employee_id')

    if is_admin:
        employee_id = session.get('impersonated_employee_id')
        if not employee_id:
            flash('Select an employee to view from the admin dashboard.')
            return redirect(url_for('admin_dashboard'))
    elif not employee_id:
        flash('Please log in again.')
        return redirect(url_for('login'))

    employee = Employee.query.get_or_404(employee_id)

    if request.method == 'POST':
        person_name = request.form['person_name']
        person_number = request.form['person_number']
        answered = request.form.get('answered') == 'yes'
        outcome = request.form['outcome']
        property_value = request.form.get('property_value', '').strip()

        new_call = Call(
            person_name=person_name,
            person_number=person_number,
            answered=answered,
            outcome=outcome,
            property_value=property_value or None,
            employee_id=employee_id
        )
        db.session.add(new_call)
        db.session.commit()
        flash('Call logged successfully!')
        return redirect(url_for('dashboard'))
    
    date_filter = request.args.get('date')
    if date_filter:
        try:
            date_obj = datetime.datetime.strptime(date_filter, '%Y-%m-%d').date()
            calls = Call.query.filter(
                Call.employee_id == employee_id,
                func.date(Call.timestamp) == date_obj
            ).order_by(Call.timestamp.desc()).all()
        except ValueError:
            calls = [] # Or handle the error appropriately
    else:
        calls = Call.query.filter_by(employee_id=employee_id).order_by(Call.timestamp.desc()).all()

    # Get dates with calls for the calendar
    dates_with_calls = db.session.query(func.date(Call.timestamp)).filter_by(employee_id=employee_id).distinct().all()
    call_dates = [d[0].strftime('%Y-%m-%d') if hasattr(d[0], 'strftime') else str(d[0]) for d in dates_with_calls if d[0]]

    return render_template(
        'dashboard.html',
        calls=calls,
        call_dates=call_dates,
        is_admin=is_admin,
        viewing_employee=employee if is_admin else None
    )

def _require_admin():
    if not session.get('logged_in') or not session.get('is_admin'):
        flash('Admin access required')
        return False
    return True


@app.route('/admin/dashboard')
def admin_dashboard():
    if not _require_admin():
        return redirect(url_for('login'))

    employees = Employee.query.order_by(Employee.name).all()
    month_param = request.args.get('month')
    today = datetime.date.today()
    if month_param:
        try:
            month_start = datetime.datetime.strptime(month_param, '%Y-%m').date().replace(day=1)
        except ValueError:
            month_start = datetime.date(today.year, today.month, 1)
    else:
        month_start = datetime.date(today.year, today.month, 1)

    month_end = (month_start + datetime.timedelta(days=32)).replace(day=1)
    prev_month_start = (month_start - datetime.timedelta(days=1)).replace(day=1)
    next_month_start = month_end
    prev_month_param = prev_month_start.strftime('%Y-%m')
    next_month_param = next_month_start.strftime('%Y-%m')

    total_calls = Call.query.count()
    yes_count = Call.query.filter(Call.answered.is_(True)).count()
    no_count = total_calls - yes_count

    month_calls_query = Call.query.filter(Call.timestamp >= month_start, Call.timestamp < month_end)
    month_total_calls = month_calls_query.count()
    month_yes = month_calls_query.filter(Call.answered.is_(True)).count()
    month_no = month_total_calls - month_yes

    call_totals = dict(db.session.query(Call.employee_id, func.count(Call.id)).group_by(Call.employee_id).all())
    yes_totals = dict(
        db.session.query(Call.employee_id, func.count(Call.id))
        .filter(Call.answered.is_(True))
        .group_by(Call.employee_id)
        .all()
    )

    month_totals = dict(
        db.session.query(Call.employee_id, func.count(Call.id))
        .filter(Call.timestamp >= month_start, Call.timestamp < month_end)
        .group_by(Call.employee_id)
        .all()
    )

    month_value_totals = {}
    for emp_id, raw_value in (
        month_calls_query
        .filter(Call.answered.is_(True))
        .with_entities(Call.employee_id, Call.property_value)
        .all()
    ):
        amount = _parse_property_value(raw_value)
        if amount:
            month_value_totals[emp_id] = month_value_totals.get(emp_id, 0.0) + amount

    month_total_value = sum(month_value_totals.values())

    employee_rows = []
    chart_labels = []
    chart_values = []
    value_chart_labels = []
    value_chart_values = []
    for emp in employees:
        total_emp = call_totals.get(emp.id, 0)
        yes_emp = yes_totals.get(emp.id, 0)
        last_call = Call.query.filter_by(employee_id=emp.id).order_by(Call.timestamp.desc()).first()
        employee_rows.append({
            'id': emp.id,
            'name': emp.name,
            'total_calls': total_emp,
            'answered_yes': yes_emp,
            'answered_no': max(total_emp - yes_emp, 0),
            'last_call': last_call.timestamp.strftime('%Y-%m-%d %H:%M') if last_call else 'No calls yet'
        })

        monthly_val = month_totals.get(emp.id, 0)
        if monthly_val:
            chart_labels.append(emp.name)
            chart_values.append(monthly_val)

        value_amount = month_value_totals.get(emp.id, 0.0)
        if value_amount:
            value_chart_labels.append(emp.name)
            value_chart_values.append(round(value_amount, 2))

    return render_template(
        'admin_dashboard.html',
        employees=employee_rows,
        total_calls=total_calls,
        yes_count=yes_count,
        no_count=no_count,
        total_employees=len(employees),
        month_label=month_start.strftime('%B %Y'),
        month_yes=month_yes,
        month_no=month_no,
        month_total_calls=month_total_calls,
        month_total_value=month_total_value,
        month_total_value_display=_format_currency(month_total_value),
        monthly_agent_chart={'labels': chart_labels, 'values': chart_values},
        monthly_value_chart={'labels': value_chart_labels, 'values': value_chart_values},
        prev_month_param=prev_month_param,
        next_month_param=next_month_param
    )


@app.route('/admin/users')
def admin_users():
    if not _require_admin():
        return redirect(url_for('login'))

    employees = Employee.query.order_by(Employee.name).all()

    call_totals = dict(
        db.session.query(Call.employee_id, func.count(Call.id)).group_by(Call.employee_id).all()
    )

    last_log_map = {}
    log_rows = (
        db.session.query(Log.employee_id, func.max(Log.timestamp))
        .group_by(Log.employee_id)
        .all()
    )
    for emp_id, last_ts in log_rows:
        try:
            last_log_map[int(emp_id)] = last_ts
        except (TypeError, ValueError):
            continue

    employee_rows = []
    for emp in employees:
        employee_rows.append({
            'id': emp.id,
            'name': emp.name,
            'call_total': call_totals.get(emp.id, 0),
            'last_login': last_log_map.get(emp.id)
        })

    return render_template('admin_users.html', employees=employee_rows)


@app.route('/admin/users/add', methods=['GET', 'POST'])
def admin_add_user():
    if not _require_admin():
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        password = request.form['password'].strip()

        if not name or not password:
            flash('Name and password are required to add a user.')
        elif Employee.query.filter(func.lower(Employee.name) == name.lower()).first():
            flash('An employee with that name already exists.')
        else:
            db.session.add(Employee(name=name, password=password))
            db.session.commit()
            flash(f'Employee "{name}" added successfully.')
            return redirect(url_for('admin_users'))

    return render_template('admin_add_user.html')


@app.route('/admin/users/<int:employee_id>/delete', methods=['POST'])
def admin_delete_user(employee_id):
    if not _require_admin():
        return redirect(url_for('login'))

    employee = Employee.query.get_or_404(employee_id)

    Call.query.filter_by(employee_id=employee.id).delete(synchronize_session=False)
    Log.query.filter_by(employee_id=str(employee.id)).delete(synchronize_session=False)

    if session.get('impersonated_employee_id') == employee.id:
        session.pop('impersonated_employee_id', None)

    db.session.delete(employee)
    db.session.commit()
    flash(f'Employee "{employee.name}" deleted.')
    return redirect(url_for('admin_users'))


@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    if not _require_admin():
        return redirect(url_for('login'))

    current_message = get_setting_value('login_message', 'Please log in to continue.')

    if request.method == 'POST':
        login_message = request.form.get('login_message', '').strip()
        set_setting_value('login_message', login_message or 'Please log in to continue.')
        flash('General settings updated.')
        return redirect(url_for('admin_settings'))

    return render_template('admin_settings.html', login_message=current_message)


@app.route('/admin/dashboard/employee/<int:employee_id>')
def admin_employee_dashboard(employee_id):
    if not _require_admin():
        return redirect(url_for('login'))

    employee = Employee.query.get_or_404(employee_id)
    calls = Call.query.filter_by(employee_id=employee_id).order_by(Call.timestamp.desc()).all()
    yes_count = sum(1 for call in calls if call.answered)
    no_count = len(calls) - yes_count

    return render_template(
        'admin_employee.html',
        employee=employee,
        calls=calls,
        yes_count=yes_count,
        no_count=no_count,
        total_calls=len(calls)
    )


@app.route('/admin/impersonate/<int:employee_id>')
def admin_impersonate(employee_id):
    if not _require_admin():
        return redirect(url_for('login'))

    employee = Employee.query.get_or_404(employee_id)
    session['impersonated_employee_id'] = employee.id
    flash(f'Viewing dashboard as {employee.name}')
    return redirect(url_for('dashboard'))


@app.route('/admin/stop-impersonation')
def admin_stop_impersonation():
    if session.get('is_admin'):
        session.pop('impersonated_employee_id', None)
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('employee_id', None)
    session.pop('is_admin', None)
    session.pop('impersonated_employee_id', None)
    flash('You were logged out')
    return redirect(url_for('login'))


@app.route('/logs')
def logs():
    all_logs = Log.query.all()
    return render_template('logs.html', logs=all_logs)

if __name__ == '__main__':
    app.run(debug=True)
