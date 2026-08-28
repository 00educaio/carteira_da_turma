# Carteira da Turma — Django + SQLite

Aplicação simples para administrar moedas dos alunos, com acesso isolado por superusuário.

## Recursos

- Cadastro individual e em massa.
- Administração separada por turma, com alunos, histórico, impressão e reset filtrados.
- Cada turma pertence a um superusuário; dados, backups, restaurações e resets não se misturam.
- Criação, renomeação, arquivamento, reativação e transferência de turmas.
- Código exclusivo para cada cartão.
- Crédito e débito por aluno.
- Bloqueio de saldo negativo.
- Histórico e estorno.
- Reset semanal automático na primeira abertura de uma nova semana.
- Reset manual.
- Impressão dos cartões.
- Backup e restauração em JSON.
- Ping a cada 8 minutos enquanto a página estiver aberta.

## Rodar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abra `http://127.0.0.1:8000`.

O comando `createsuperuser` solicita o usuário e a senha da primeira conta. Use
essas credenciais na tela de login. A carteira aceita apenas superusuários. Novas
contas e a transferência de uma turma para outro proprietário podem ser gerenciadas
em `/admin/`.

No desenvolvimento, `DEBUG` fica ativo por padrão. Em produção, defina
`DEBUG=False`, uma `SECRET_KEY` própria e `ALLOWED_HOSTS` com o domínio real.

## Deploy no PythonAnywhere

No console Bash do PythonAnywhere, após clonar ou enviar o projeto:

```bash
cd ~/carteira-da-turma-django
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

Na aba **Web**:

1. Crie um app com configuração manual e escolha a mesma versão de Python da virtualenv.
2. Informe `/home/SEU_USUARIO/carteira-da-turma-django/.venv` em **Virtualenv**.
3. Abra o arquivo WSGI indicado pelo painel e adapte o conteúdo de
   `pythonanywhere_wsgi.py.example`, substituindo `SEU_USUARIO` e a chave secreta.
4. Em **Static files**, mapeie `/static/` para
   `/home/SEU_USUARIO/carteira-da-turma-django/staticfiles`.
5. Ative **Force HTTPS** e clique em **Reload**.

O SQLite do PythonAnywhere é persistente. Antes de atualizar uma instalação já em
uso, baixe um backup pela aplicação e depois execute `migrate` e `collectstatic`
novamente. Não envie a chave secreta real para o repositório.

## Deploy gratuito no Render

1. Crie um repositório no GitHub e envie esta pasta.
2. No Render, escolha **New > Blueprint**.
3. Conecte o repositório.
4. O Render lerá o `render.yaml`.
5. Confirme o serviço gratuito e aguarde o deploy.

Também é possível criar um Web Service manualmente:

- Runtime: `Python 3`
- Build Command: `./build.sh`
- Start Command: `./start.sh`
- Health Check Path: `/health/`

## Limitação assumida

O Render gratuito usa armazenamento efêmero. O SQLite pode ser apagado quando o serviço entra em repouso, reinicia ou recebe novo deploy.

Para reduzir o impacto:

1. Enquanto a página estiver aberta, ela chama `/health/` a cada 8 minutos.
2. Use **Baixar backup** para guardar um arquivo manual ao final da aula.
3. Guarde o JSON fora do Render e use **Restaurar backup** quando necessário.

## Formato para cadastro em massa

```text
Ana Silva; 6º A; 1024
Bruno Lima; 6º A
Carla Souza; 6º B; 2098
```

O código é gerado automaticamente quando não for informado.
