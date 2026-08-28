# Plano de implementação — ações por turma e análise financeira

## 1. Objetivo e decisões funcionais

Este documento divide a evolução da Carteira da Turma em tarefas implementáveis e ordenadas.

Regras que devem orientar todas as tarefas:

- Cada ação pertence a uma única turma e possui nome, natureza (`credit` ou `debit`), valor fixo e status ativo.
- O professor pode editar o valor de uma ação, mas a alteração só afeta movimentações futuras daquela turma. O histórico mantém o valor efetivamente aplicado na data da operação.
- Uma movimentação comum deve receber uma ação, e não um valor ou motivo digitado livremente. O backend consulta a ação e define o tipo, o valor e o motivo; o navegador nunca é a fonte desses dados.
- As turmas existentes e as novas recebem o catálogo inicial de ações. Para não bloquear a migração, o valor inicial é **1 moeda**, editável separadamente em cada turma.
- Adicionar `Fazer caligrafia` ao catálogo de recompensas e `Reposição de cartão perdido` ao catálogo de despesas.
- Débitos podem deixar o saldo abaixo de zero. Isso é necessário para cobrar a reposição de cartão mesmo sem saldo suficiente e para identificar alunos “no vermelho”.
- Reset e estorno não contam como gasto nem ganho nos indicadores. Uma movimentação desfeita também não entra nos totais.
- A análise considera, por padrão, a semana corrente no fuso `America/Maceio`, oferece mês corrente, todo o histórico e intervalo personalizado, e usa somente dados pertencentes ao superusuário autenticado.

Catálogo inicial:

| Natureza | Ação |
| --- | --- |
| Recompensa | Bom comportamento |
| Recompensa | Organizou a sala |
| Recompensa | Ajudou um colega |
| Recompensa | Terminou a atividade |
| Recompensa | Fazer caligrafia |
| Despesa | Ir ao banheiro |
| Despesa | Beber água |
| Despesa | Folha de papel |
| Despesa | Indisciplina |
| Despesa | Reposição de cartão perdido |

## 2. Ordem de execução

### TASK-01 — Criar o modelo de ações por turma

**Dependências:** nenhuma.

**Implementação:**

- Criar `ClassroomAction` com: turma, nome, natureza, valor positivo, posição de exibição, status ativo e identificador estável da ação padrão.
- Garantir unicidade do identificador dentro da turma e impedir valor zero ou negativo por validação de modelo e banco.
- Adicionar em `Movement` uma referência opcional à ação com `SET_NULL`. Manter `reason`, `amount` e `signed_amount` como fotografia histórica.
- Criar migração de schema e migração de dados que cadastre o catálogo inicial, com valor 1, em cada turma existente.
- Registrar o novo modelo no Django Admin.

**Critérios de aceite:**

- Duas turmas podem ter valores diferentes para a mesma ação.
- Editar ou remover uma ação não modifica movimentações já registradas.
- Todas as turmas existentes recebem exatamente uma cópia de cada ação inicial.

### TASK-02 — Garantir o catálogo no ciclo de vida das turmas

**Dependências:** TASK-01.

**Implementação:**

- Centralizar a criação do catálogo em um serviço idempotente, evitando duplicação caso seja executado mais de uma vez.
- Chamar o serviço ao criar uma turma pela API e ao criar turmas durante a restauração de backup.
- Na transferência de turma, manter as ações vinculadas à própria turma; nenhuma cópia deve ser criada para o novo proprietário.
- Arquivar uma turma deve apenas ocultar suas ações da operação diária, sem excluir configuração ou histórico.

**Critérios de aceite:**

- Toda turma nova está pronta para movimentações sem configuração manual obrigatória.
- Restaurar ou transferir uma turma não duplica nem perde ações.

### TASK-03 — Expor e proteger a API de configuração das ações

**Dependências:** TASK-01 e TASK-02.

**Implementação:**

- Criar `GET /api/classrooms/<classroom_id>/actions/` para listar as ações ordenadas e `POST` no mesmo recurso para atualizar os valores e o status das ações enviadas.
- Validar inteiro positivo, natureza válida e pertencimento da turma ao usuário autenticado.
- Não permitir que a API altere ações de outra turma, de outro superusuário ou de turma arquivada.
- Retornar erros em português e rejeitar a atualização inteira se qualquer item for inválido.

**Critérios de aceite:**

- Uma edição em `6º A` não muda a configuração de `6º B`.
- Tentativas de acesso cruzado retornam erro sem revelar ou alterar dados.
- Atualizações parciais ou inválidas não deixam parte do catálogo salva.

### TASK-04 — Aplicar somente valores fixos nas movimentações

**Dependências:** TASK-03.

**Implementação:**

- Alterar `POST /api/students/<student_id>/movement/` para aceitar apenas `action_id`.
- No serviço transacional, bloquear aluno e ação, confirmar que ambos pertencem à mesma turma ativa e derivar nome, natureza e valor da ação.
- Gravar a referência à ação e a fotografia histórica em `Movement`.
- Remover a regra que impede saldo negativo em débitos e estornos. Continuar exigindo valor positivo na configuração da ação.
- Desabilitar uma ação apenas para novas operações; movimentações antigas continuam legíveis e estornáveis.
- Tratar `Reposição de cartão perdido` como um débito comum: o saldo é reduzido mesmo quando fica negativo.

**Critérios de aceite:**

- Alterar `amount`, tipo ou motivo no corpo da requisição não altera o valor aplicado.
- Uma ação de outra turma ou inativa é recusada.
- A perda do cartão gera uma única movimentação de débito e pode deixar o aluno no vermelho.
- O estorno recompõe exatamente o valor histórico da operação, mesmo se o preço atual da ação mudou.

### TASK-05 — Criar a interface de configuração de preços

**Dependências:** TASK-03.

**Implementação:**

- Adicionar ao gerenciamento de turmas o comando “Configurar ações”.
- Exibir recompensas e despesas em grupos, cada ação com campo numérico e controle ativo/inativo.
- Carregar e salvar sempre pelo ID da turma, sem depender apenas do nome selecionado no filtro global.
- Mostrar confirmação de sucesso e manter os valores preenchidos quando a API retornar erro de validação.
- Adaptar o layout para celular e computador e manter toda a interface em português.

**Critérios de aceite:**

- O professor identifica claramente qual turma está configurando.
- A tela não permite enviar valor vazio, zero, negativo ou decimal.
- Reabrir a configuração mostra os dados persistidos daquela turma.

### TASK-06 — Substituir a movimentação livre pela seleção de ação

**Dependências:** TASK-04 e TASK-05.

**Implementação:**

- Remover campo de valor, botões de valores rápidos e motivo personalizado da operação rápida.
- Após selecionar um aluno, carregar as ações ativas da turma dele.
- Manter as abas “Adicionar” e “Retirar”, filtrando respectivamente recompensas e despesas.
- Exibir cada ação com seu valor antes da confirmação e enviar somente `action_id` à API.
- Incluir `Fazer caligrafia` entre recompensas e `Reposição de cartão perdido` entre despesas.
- Destacar saldos negativos na busca, na seleção do aluno e na tabela de alunos.

**Critérios de aceite:**

- Não existe caminho na interface para escolher um valor diferente do configurado.
- Trocar de aluno/turma atualiza imediatamente as ações e os preços disponíveis.
- Uma ação desativada deixa de aparecer sem afetar o histórico.

### TASK-07 — Criar o serviço e a API de análise

**Dependências:** TASK-04.

**Implementação:**

- Criar um serviço de agregação baseado em `Movement`, filtrando intervalo, proprietário e, opcionalmente, turma.
- Considerar como ganho somente créditos não desfeitos; como gasto, somente débitos não desfeitos. Excluir `reset`, `reversal` e movimentos marcados como `reversed`.
- Criar `GET /api/analytics/` com parâmetros `period=week|month|all|custom`, `start`, `end` e `classroom_id` opcional.
- Retornar:
  - totais gerais de ganhos e gastos;
  - todas as turmas ativas com seus totais, incluindo zero, permitindo identificar maior e menor gasto;
  - alunos com total ganho e gasto no período, permitindo identificar quem mais ganhou e quem mais gastou;
  - todos os alunos ativos com saldo atual negativo, independentemente do período selecionado.
- Em empates, retornar todos os líderes; ordenar empates alfabeticamente. Tratar datas do intervalo como inclusivas no fuso da aplicação.

**Critérios de aceite:**

- Estornos e resets não distorcem os totais.
- Turmas sem gastos podem aparecer como menor gasto com total zero.
- O endpoint nunca mistura dados entre proprietários.
- Intervalos inválidos retornam erro de validação em português.

### TASK-08 — Adicionar o painel visual de análise

**Dependências:** TASK-07.

**Implementação:**

- Criar uma seção “Análise financeira” com filtros de período e turma.
- Exibir cartões-resumo para total gasto, total ganho, turma que mais gastou, turma que menos gastou, aluno que mais gastou, aluno que mais ganhou e quantidade de alunos no vermelho.
- Exibir tabelas completas por turma, por aluno e de alunos no vermelho; não depender apenas dos destaques.
- Mostrar empates sem escolher arbitrariamente um único vencedor e fornecer estados de carregamento, vazio e erro.
- Atualizar o painel depois de movimentação, estorno, reset, edição de turma ou restauração.

**Critérios de aceite:**

- Os valores da tela coincidem com a API para todos os filtros.
- O painel continua legível em celular e permite localizar todos os alunos no vermelho.
- Períodos sem movimentação mostram zero e uma mensagem adequada, sem erro de JavaScript.

### TASK-09 — Evoluir backup e restauração

**Dependências:** TASK-01 a TASK-04.

**Implementação:**

- Elevar o formato do backup para a versão 3 e exportar ações por turma e a relação opcional entre movimentação e ação.
- Na restauração v3, recriar ações antes das movimentações e reconstruir as referências com IDs lógicos do arquivo.
- Manter compatibilidade com backups v2: criar o catálogo padrão e restaurar movimentos antigos sem ação, preservando motivo e valor.
- Validar todo o arquivo antes de apagar os dados atuais e executar a troca dentro de uma única transação.

**Critérios de aceite:**

- Exportar e restaurar v3 preserva valores diferentes entre turmas, ações desativadas, saldos negativos e histórico.
- Um backup v2 continua restaurável.
- Um arquivo inválido não apaga os dados existentes.

### TASK-10 — Cobertura automatizada, documentação e validação final

**Dependências:** todas as anteriores.

**Implementação:**

- Criar testes de modelo, serviços e APIs para isolamento por turma/proprietário, preço fixo, saldo negativo, perda de cartão, estorno e catálogo padrão.
- Criar testes analíticos com créditos, débitos, reset, estorno, empates, turma sem movimento, aluno inativo e intervalos de data.
- Cobrir backup v2/v3, restauração inválida, turma arquivada e transferência de propriedade.
- Atualizar o README com configuração das ações, regra de saldo negativo, painel de análise e novo formato de backup.
- Atualizar a versão dos arquivos estáticos no template para evitar cache antigo no navegador.
- Executar `python manage.py makemigrations --check`, `python manage.py check` e `python manage.py test`.

**Critérios de aceite:**

- As três verificações terminam sem erro.
- Não há regressão em cadastro, filtro, exclusão lógica, reset semanal/manual, histórico, impressão ou autenticação.

## 3. Entregas sugeridas

Para reduzir risco, as tarefas podem ser agrupadas em três entregas:

1. **Fundação e operação:** TASK-01 a TASK-06.
2. **Análise financeira:** TASK-07 e TASK-08.
3. **Compatibilidade e qualidade:** TASK-09 e TASK-10.

Cada entrega deve ser testada antes do início da seguinte. A primeira altera o contrato da API de movimentações e, portanto, backend e frontend devem ser publicados juntos.
