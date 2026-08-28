# Prompt para o Codex

Analise este projeto Django chamado **Carteira da Turma**.

Objetivo: manter uma aplicação escolar simples, sem login e sem autenticação, hospedada no PythonAnywhere, usando Django, templates, JavaScript puro e SQLite.

Regras principais:

1. Não adicionar React, Vue, Next.js, banco externo, Redis, Celery ou Docker sem necessidade explícita.
2. Manter um único app Django chamado `wallet`.
3. Preservar a configuração de deploy descrita no README e em `pythonanywhere_wsgi.py.example`.
4. Usar SQLite com armazenamento persistente no PythonAnywhere.
5. Preservar backup manual em JSON, cópia automática no `localStorage` e restauração quando o servidor estiver vazio.
6. O reset semanal deve ocorrer na primeira abertura de cada nova semana, usando o fuso `America/Maceio`.
7. Toda alteração de saldo deve ser atômica e não pode deixar saldo negativo.
8. Não criar login para professor ou alunos.
9. Interface em português, responsiva para celular e computador.
10. Antes de concluir mudanças, execute:

```bash
python manage.py check
python manage.py test
```

Agora revise o projeto, corrija erros encontrados e preserve a simplicidade da arquitetura.
