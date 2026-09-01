# Carteira da Turma — Django + SQLite

Aplicação simples para administrar moedas dos alunos, com acesso isolado por superusuário.

## Recursos

- Cadastro individual e em massa.
- Administração separada por turma, com alunos, histórico, impressão e reset filtrados.
- Cada turma pertence a um superusuário; dados, backups, restaurações e resets não se misturam.
- Criação, renomeação, arquivamento, reativação e transferência de turmas.
- Código exclusivo para cada cartão.
- Catálogo de recompensas e despesas configurável separadamente por turma.
- Movimentações com valores fixos definidos pelo professor, sem valor livre no navegador.
- Crédito e débito por aluno, incluindo cobrança com saldo negativo.
- Histórico e estorno.
- Reset semanal automático na primeira abertura de uma nova semana.
- Reset manual.
- Painel de análise financeira por semana, mês, histórico ou intervalo personalizado.
- Impressão dos cartões com QR Code que abre o aluno diretamente na operação rápida.
- Backup e restauração transacional em JSON, com compatibilidade v2 e v3.

## Ações e saldos

Cada turma recebe automaticamente um catálogo inicial de recompensas e despesas.
Em **Gerenciar turmas → Configurar ações**, o professor pode alterar o valor e
ativar ou desativar cada opção. A mudança vale somente para movimentações futuras;
o histórico preserva o nome e o valor efetivamente aplicados.

A operação rápida aceita apenas uma ação ativa da turma do aluno. Débitos podem
deixar o saldo negativo, inclusive a ação **Reposição de cartão perdido**. Saldos
no vermelho são destacados na interface. Um estorno sempre usa o valor histórico
da movimentação, mesmo que o preço atual da ação seja diferente.

## Análise financeira

A seção **Análise financeira** apresenta totais de ganhos e gastos por turma e
por aluno, destaques com suporte a empates e a relação de alunos ativos com saldo
negativo. Os filtros disponíveis são semana atual, mês atual, todo o histórico e
intervalo personalizado, com opção de limitar a uma turma.

Resets, estornos e movimentações desfeitas não entram nos totais. Os intervalos
de data são inclusivos e seguem o fuso `America/Maceio`.

## Backup e restauração

O backup atual usa o formato **v3** e inclui turmas, ações e seus valores, status,
alunos, saldos negativos, histórico, vínculo opcional entre movimentação e ação e
configurações da conta. Alunos e turmas arquivados também são preservados.

A restauração valida o arquivo inteiro antes de substituir qualquer dado e executa
a troca em uma única transação. Se houver erro, os dados atuais permanecem intactos.
Backups **v2** continuam aceitos: cada turma recebe o catálogo padrão e as
movimentações antigas são restauradas sem vínculo de ação, preservando motivo e
valor históricos.

Além do download manual, o navegador mantém uma cópia automática no `localStorage`,
se houver espaço disponível. Na primeira abertura, se o servidor estiver sem turmas
e alunos, essa cópia é enviada à mesma restauração validada automaticamente. A cópia
é separada por superusuário no navegador.

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

## Formato para cadastro em massa

```text
Ana Silva; 6º A; 1024
Bruno Lima; 6º A
Carla Souza; 6º B; 2098
```

O código é gerado automaticamente quando não for informado.
