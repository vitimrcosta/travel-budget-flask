# Guia de uso do Rota

Este guia explica, passo a passo, como usar o Rota para controlar viagens: do primeiro acesso até o relatório final. Para instalação e publicação, veja o [README](README.md).

## Sumário

1. [Primeiro acesso](#1-primeiro-acesso)
2. [Instalar no celular](#2-instalar-no-celular)
3. [Navegação](#3-navegação)
4. [Cadastrar uma viagem](#4-cadastrar-uma-viagem)
5. [Planejar o orçamento por categoria](#5-planejar-o-orçamento-por-categoria)
6. [Registrar gastos](#6-registrar-gastos)
7. [Entender o painel](#7-entender-o-painel)
8. [Roteiro](#8-roteiro)
9. [Reservas](#9-reservas)
10. [Pessoas da viagem](#10-pessoas-da-viagem)
11. [Documentos e anexos](#11-documentos-e-anexos)
12. [Relatório e impressão](#12-relatório-e-impressão)
13. [Backup e restauração](#13-backup-e-restauração)
14. [Tema claro e escuro](#14-tema-claro-e-escuro)
15. [Dicas e solução de problemas](#15-dicas-e-solução-de-problemas)

---

## 1. Primeiro acesso

1. Abra o endereço do sistema no navegador.
2. Se o login estiver ativado, informe o **usuário** e a **senha** compartilhados (os mesmos para todas as pessoas que usam o sistema).
3. O login fica salvo por **90 dias** no aparelho. Se o navegador limpar os dados do site, será preciso entrar de novo.
4. Para sair, use o botão de sair no menu.

> No plano gratuito do Render, o site "dorme" depois de um tempo sem uso. O primeiro acesso pode demorar alguns segundos. O banco gratuito do Aiven também pode ser desligado por inatividade; se aparecer erro, tente de novo depois de alguns instantes.

## 2. Instalar no celular

O Rota funciona como aplicativo (PWA):

- **Android (Chrome):** abra o site, toque nos três pontinhos e escolha **Instalar app** ou **Adicionar à tela inicial**.
- **iPhone (Safari):** toque em **Compartilhar** e depois em **Adicionar à Tela de Início**.

O app abre em tela cheia, com ícone próprio. Depois de uma atualização do sistema, feche o app por completo e abra de novo para carregar a versão nova.

## 3. Navegação

**No celular**, há um menu na parte de baixo com:

| Item | O que abre |
| --- | --- |
| **Início** | Painel da viagem |
| **Gastos** | Lista de gastos |
| **Roteiro** | Atividades planejadas |
| **Reservas** | Hospedagem, transporte, passeios etc. |
| **Mais** | Pessoas, documentos, relatório, nova viagem e restaurar backup |

O botão **+** flutuante registra um gasto rapidamente. Ele some nos formulários para não atrapalhar.

Na barra do topo, o **seletor de viagem** permite trocar de viagem ou criar uma nova.

**No computador**, a navegação fica numa barra lateral com a lista de viagens e os atalhos equivalentes.

## 4. Cadastrar uma viagem

1. Toque em **Nova viagem** (ou no **+** ao lado de "Suas viagens").
2. Preencha:
   - **Destino**: nome da cidade ou viagem.
   - **País**: escolha na lista; a bandeira aparece ao lado do destino.
   - **Data de ida** e **Data de volta**.
3. Salve. A viagem fica selecionada automaticamente.

Para mudar esses dados depois, abra o painel, toque em **⋯** e escolha **Editar viagem**.

**Foto de capa:** no painel, toque em **Alterar foto** sobre a capa, escolha uma imagem JPG ou PNG e salve.

**Excluir viagem:** fica dentro do menu **⋯** do painel, de propósito, por ser uma ação que apaga tudo da viagem. Há uma confirmação antes. Exporte um backup antes se tiver dúvida.

## 5. Planejar o orçamento por categoria

O planejamento define quanto você pretende gastar em cada categoria (Alimentação, Hospedagem, Transporte etc.).

1. No painel, em **Planejamento por categoria**, toque em **Editar valores**.
2. Digite o valor **previsto** de cada categoria. O campo aceita vírgula ou ponto e limpa o `0,00` ao tocar.
3. Toque em **Salvar planejamento**.

**Adicionar categoria:** na mesma tela, digite o nome em "Categorias desta viagem" e toque em adicionar. Os valores que você já digitou são mantidos.

**Editar uma categoria:** no painel, toque na categoria (na tabela ou na lista do celular). Abre uma tela só dela, onde você muda o **nome** e o **valor previsto**. Se renomear, os gastos dessa categoria acompanham o novo nome. Nessa tela também há **Excluir categoria**.

**Finalizar ou reabrir uma categoria:** na edição da categoria, escolha **Finalizada** ou **Em andamento** em Situação e salve. Uma categoria finalizada continua no painel, identificada pelo selo. A marcação não altera os cálculos nem bloqueia gastos: ao selecioná-la em um gasto, aparece um aviso e o lançamento pode ser salvo normalmente. Se ultrapassar o previsto, o saldo ficará negativo como de costume.

**Remover categoria:** só é possível se ela **não tiver gastos**. Com gastos, o botão fica desativado e aparece o motivo.

O **Total previsto** é a soma de todas as categorias e funciona como o orçamento geral da viagem.

## 6. Registrar gastos

1. Toque em **Adicionar gasto** (painel), em **Gastos > Novo gasto** ou no botão **+**.
2. Preencha:

| Campo | Para que serve |
| --- | --- |
| **Data** | Dia em que o gasto aconteceu |
| **Categoria** | Define de qual planejamento o valor será abatido |
| **Descrição** | Ex.: "Jantar no restaurante" |
| **Moeda** | BRL, CLP, USD ou EUR |
| **Valor original** | Valor na moeda escolhida |
| **Cotação** | Para moedas estrangeiras, é buscada automaticamente (histórica da data). Se estiver sem internet, informe manualmente |
| **Pago** | Já vem como **Pago**. Se marcar pendente, o gasto entra em "A pagar" |
| **Forma de pagamento** | Dinheiro, Pix, cartão etc. Obrigatória para gasto pago |
| **Pessoa / Valor pago** | Opcional: divide quanto cada pessoa pagou e de que forma |
| **Observação** | Anotações livres |
| **Comprovantes** | Fotos ou PDFs (veja [Documentos e anexos](#11-documentos-e-anexos)) |

3. Toque em **Salvar**. No celular, a barra **Cancelar / Salvar** fica fixa acima do menu.

Os valores são sempre convertidos e controlados em **reais (BRL)**.

**Lista de gastos:** mostra cartões com ícone da categoria, descrição, data e valor. Use o botão **Filtros** para filtrar por categoria, período, situação de pagamento ou texto da descrição. Toque em um gasto para editar. Na tela de edição há o botão **Excluir gasto** no fim da página (com confirmação). O mesmo vale para **Excluir atividade** e **Excluir reserva**.

**Seletores no celular:** as listas (como a de categoria) abrem em um painel inferior com ícones, no estilo do app.

## 7. Entender o painel

O painel (**Início**) reúne tudo da viagem:

- **Capa e resumo:** destino, bandeira e datas.
- **Saldo do planejamento:** quanto ainda resta do orçamento geral. Positivo é o que sobra; negativo é o que excedeu. A barra mostra a % do orçamento utilizado.
  - Aviso amarelo a partir de **80%**.
  - Aviso vermelho quando **ultrapassa 100%**.
- **Total previsto** e **Gasto registrado**.
- **Total pago** e **A pagar**: aparecem só quando existem gastos pendentes.
- **Resultado do planejamento:** considera apenas categorias que já têm pelo menos um gasto.
  - Mostra em quantas categorias **sobrou** e em quantas **estourou**, e o saldo líquido.
  - Com a viagem em andamento, o valor aparece como "Folga atual" (ainda não é economia).
  - Depois da data de volta, passa a ser "Economizado no total".
- **Planejamento por categoria:** previsto, gasto, pago e **Ainda disponível** de cada categoria, com alerta quando passa de 80% ou estoura.
- **Gastos recentes**, **próxima atividade** e **reservas**.

O menu **⋯** do painel tem: Pessoas, Documentos da viagem, Reservas, Exportar backup ZIP, Ver relatório, Editar viagem e Excluir viagem.

## 8. Roteiro

O roteiro organiza o que será feito em cada dia.

1. Abra **Roteiro** e toque em **Nova atividade**.
2. Preencha **Nome**, **Data**, **Horário** (opcional), **Local** (opcional), **Custo estimado** (opcional) e **Situação**.
3. Anexe ingressos ou confirmações (JPG, PNG ou PDF).

**Situações:** `Planejada`, `Reservada`, `Realizada` e `Cancelada`. É possível marcar uma atividade como concluída direto na lista.

O **custo estimado** serve só de referência: ele **não** entra nos gastos. Para registrar o gasto real, use a tela de gastos.

Use os filtros para ver por data ou situação. O botão **Imprimir roteiro** gera uma versão limpa para imprimir ou salvar em PDF.

## 9. Reservas

Controle de hospedagem, transporte, passeios, restaurantes e outros serviços.

1. Abra **Reservas** e toque em **Nova reserva**.
2. Campos principais:
   - **Tipo** e **Fornecedor**.
   - **Check-in** e **Check-out** (data e horário).
   - **Código de confirmação**.
   - **Situação:** `Pendente`, `Confirmada`, `Cancelada` ou `Utilizada`.
   - **Local ou endereço**.
   - **Prazo para cancelamento gratuito**.
   - **Observações** e anexos.

Reservas são **informativas**: não são somadas aos gastos. Registre o pagamento correspondente na tela de gastos.

## 10. Pessoas da viagem

Em **⋯ > Pessoas** (ou **Mais > Pessoas** no celular), cadastre quem está na viagem. Essas pessoas aparecem no gasto para indicar **quem pagou** e com qual forma de pagamento. Pessoas associadas a pagamentos registrados não podem ser removidas.

## 11. Documentos e anexos

- **Documentos da viagem:** arquivos gerais (passagens, seguros, passaporte etc.), em **⋯ > Documentos da viagem**.
- **Comprovantes de gastos** e **arquivos de atividades e reservas:** anexados nos próprios formulários.

Regras dos anexos: formatos **PDF, JPG ou PNG**, até **10 MB por arquivo** e no máximo **5 por envio**. Os arquivos ficam guardados no Cloudinary e só podem ser abertos por quem está logado. Para abrir, toque no nome do arquivo; para apagar, use o botão de excluir ao lado.

## 12. Relatório e impressão

Em **⋯ > Ver relatório** há um resumo completo da viagem: totais, saldo do planejamento, categorias, gastos, atividades e reservas. Use a impressão do navegador para salvar em PDF ou imprimir.

## 13. Backup e restauração

- **Exportar:** em **⋯ > Exportar backup ZIP**. Baixa um arquivo com a viagem completa e os anexos.
- **Restaurar:** em **Restaurar backup** (barra do topo no computador, menu **Mais** no celular). Envie o ZIP; ele volta como uma **nova viagem**, sem sobrescrever as existentes.

Boa prática: exporte um backup ao fim de cada viagem e antes de mudanças grandes. O servidor gratuito do Render não guarda backups locais de forma permanente.

## 14. Tema claro e escuro

Use o botão de tema (lua/sol) na barra do topo. A escolha fica salva no aparelho. As cores principais são mantidas nos dois temas.

## 15. Dicas e solução de problemas

| Situação | O que fazer |
| --- | --- |
| Pediu login de novo | Os dados do site podem ter sido limpos pelo navegador. Entre novamente; a sessão dura 90 dias |
| "Erro interno" ao salvar | O banco gratuito pode estar acordando. Aguarde um momento e tente novamente |
| Cotação não carregou | Sem internet ou fora do ar. Informe a cotação manualmente |
| Não consigo remover uma categoria | Ela tem gastos. Edite ou exclua os gastos antes |
| Tela antiga depois de atualizar | Feche o app completamente e abra de novo |
| Anexo não abre | Confirme que está logado e tente novamente; envie de novo se persistir |
| Verificar se o sistema está no ar | Acesse `/status` ou `/healthz` no endereço do site |

Para dúvidas de instalação, variáveis de ambiente e publicação, consulte o [README](README.md).
