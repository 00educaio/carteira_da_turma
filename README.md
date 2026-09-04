# Class Wallet — Django + SQLite

A simple application for managing student coins, with data isolated by superuser.

## Features

- Add students individually or in bulk.
- Separate classroom management for students, history, printing, and filtered resets.
- Create, rename, archive, reactivate, and transfer classrooms.
- Unique code and printable QR card for every student.
- Configurable rewards and expenses for each classroom.
- Credits and expenses with fixed values, including negative balances.
- Transaction history and reversals.
- Automatic weekly allowance of 15 coins every Monday at 7:00 a.m.
- Manual balance reset.
- Coin analytics by week, month, all history, or a custom date range.
- Transactional JSON backup and restore, compatible with v2 and v3 files.

## Actions and balances

Every classroom automatically receives the default rewards and expenses, including
**Play Video Game**. In **Manage classrooms → Configure actions**, the teacher can
change each value and enable or disable each option. Changes apply only to future
transactions; history keeps the action name and value that were originally used.

Expenses may make a balance negative. A reversal always uses the historical
transaction value, even when the current action value has changed.

## Weekly coins

The command below awards 15 coins to every active student in an active classroom.
It is idempotent: running it again in the same weekly window will not award coins
twice. The weekly window starts Monday at 7:00 a.m. in `America/Maceio`.

```bash
.venv/bin/python manage.py award_weekly_coins
```

Schedule it for Monday at 7:00 a.m. on the server. For example, with cron:

```cron
CRON_TZ=America/Maceio
0 7 * * 1 cd /path/to/carteira-da-turma-django && .venv/bin/python manage.py award_weekly_coins
```

The web app also checks the allowance window when it is opened. This provides an
idempotent fallback if one scheduled run is missed.

## Coin analytics

The **Coin analytics** section displays earned and spent coin totals by classroom
and student, leaders (including ties), and active students with negative balances.
Resets, reversals, and undone transactions are excluded. Date ranges are inclusive
and follow the `America/Maceio` time zone.

## Backup and restore

The current backup format is **v3** and includes classrooms, configurable actions,
students, negative balances, transaction history, and account settings. Archived
students and classrooms are preserved. The restore process validates the entire
file and replaces data in a single transaction. Older **v2** backups are supported.

The browser also keeps an automatic local backup when local storage is available.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000` and sign in with a superuser account.

In development, `DEBUG` is enabled by default. In production, set `DEBUG=False`,
provide a unique `SECRET_KEY`, and configure `ALLOWED_HOSTS` with the real domain.

## Deploy on PythonAnywhere

After cloning or uploading the project, run:

```bash
cd ~/carteira-da-turma-django
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

Configure the virtual environment, WSGI file, `/static/` mapping, HTTPS, and reload
the web app. Add `manage.py award_weekly_coins` as a scheduled task for Mondays at
7:00 a.m. Maceió time (10:00 UTC).

Before updating an existing installation, download a backup. Then run `migrate`
and `collectstatic` again. Never commit a real secret key.

## Bulk student format

```text
Ana Silva; Grade 6A; 1024
Bruno Lima; Grade 6A
Carla Souza; Grade 6B; 2098
```

The code is generated automatically when omitted.
