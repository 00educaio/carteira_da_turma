# Codex Project Prompt

Review this Django project named **Class Wallet**.

Goal: maintain a simple classroom coin-management application hosted on
PythonAnywhere, using Django, server-rendered templates, vanilla JavaScript, and
SQLite.

Main rules:

1. Do not add React, Vue, Next.js, an external database, Redis, Celery, or Docker unless explicitly required.
2. Keep a single Django app named `wallet`.
3. Preserve the deployment setup described in `README.md` and `pythonanywhere_wsgi.py.example`.
4. Use SQLite with persistent storage on PythonAnywhere.
5. Preserve manual JSON backups, the automatic `localStorage` copy, and restoration when the server is empty.
6. Award every active student 15 coins each Monday at 7:00 a.m. in `America/Maceio`; never award the same weekly allowance twice.
7. Every balance change must be atomic. Expenses are allowed to make balances negative.
8. Keep superuser authentication and data isolation between classroom owners.
9. Keep the interface in English and responsive on mobile and desktop.
10. Before completing changes, run:

```bash
python manage.py check
python manage.py test
```

Review the project, fix any issues found, and preserve its simple architecture.
