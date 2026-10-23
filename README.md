# Controle de Viagem

Aplicação web pessoal para organizar viagens, roteiro, reservas e orçamento. A interface é em português e foi projetada para uso local por você e seus acompanhantes.

> **Uso local:** por padrão, o sistema não exige login e usa armazenamento local como fallback. Para publicar na internet, configure autenticação, MySQL obrigatório e armazenamento externo conforme a seção de deploy abaixo.

## Funcionalidades

- Criar, editar, selecionar e excluir viagens com destino, período e bandeira.
- Planejar valores em reais por categorias personalizadas e receber alertas quando o consumo atingir 80% ou ultrapassar o orçamento geral ou de uma categoria.
- Registrar gastos em BRL, CLP, USD ou EUR, com cotação, pagamentos, participantes, observações e comprovantes.
- Consultar cotações históricas de CLP, USD e EUR pela API pública [Frankfurter](https://frankfurter.dev/). A consulta automática requer internet; é possível informar a cotação manualmente.
- Acompanhar valores previstos, registrados, pagos e a pagar, com filtros de gastos por categoria, período, pagamento e descrição.
- Montar o roteiro com atividades, horários, locais, custos estimados, situação e anexos; as atividades podem ser filtradas, concluídas e impressas.
- Controlar reservas de hospedagem, transporte, passeios, restaurantes e outros serviços, com fornecedor, código, período, horários de check-in/check-out, prazo de cancelamento e situação. Reservas são informativas e não são somadas aos gastos.
- Guardar documentos gerais da viagem, comprovantes de gastos e arquivos de atividades.
- Consultar um painel com resumo financeiro, próxima atividade e reservas.
- Gerar relatórios, exportar viagens e restaurar backups como novas viagens.
- Usar tema claro ou escuro e uma capa personalizada para a viagem.

As situações de atividade são `Planejada`, `Reservada`, `Realizada` e `Cancelada`. As situações de reserva são `Pendente`, `Confirmada`, `Cancelada` e `Utilizada`.

## Requisitos

- Python 3.9 ou superior.
- MySQL opcional. Se MySQL não estiver disponível, o sistema usa armazenamento JSON local.
- Gunicorn e Cloudinary são usados no deploy; suas dependências já estão em `requirements.txt`.
- Acesso à internet somente para buscar cotações automaticamente e carregar as fontes externas usadas pela interface.

As dependências Python da aplicação estão listadas em [requirements.txt](requirements.txt). Não é necessário instalar dependências separadas para executar os testes: eles usam `unittest`, incluído na biblioteca padrão do Python.

## Instalação e execução no Windows

Abra o PowerShell na pasta do projeto e execute:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py
```

Abra [http://127.0.0.1:5000](http://127.0.0.1:5000). Para usar a interface de terminal:

```powershell
.\.venv\Scripts\python.exe main.py
```

## Banco de dados e configuração

Sem configuração adicional, o sistema tenta conectar ao MySQL e usa `viagem_data.json` como fallback quando não consegue. O JSON local é ignorado pelo Git.

Para configurar o MySQL, crie primeiro o banco indicado em `DB_NAME`, copie o exemplo e preencha `.env` com as credenciais locais:

```powershell
Copy-Item .env.example .env
```

O arquivo `.env` é ignorado pelo Git e **não deve ser compartilhado**. Alternativamente, configure as variáveis `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD` e `DB_NAME` no ambiente. A conta MySQL usada pela aplicação precisa ter permissões para criar e alterar as tabelas no banco selecionado. O app cria as tabelas e aplica atualizações compatíveis do schema na inicialização.

O esquema atual está em [database/schema.sql](database/schema.sql). Para ambientes administrados manualmente, faça backup do banco e confira as instruções de migração em [database/migrations](database/migrations/) antes de aplicar qualquer script. Não execute migrações que já tenham sido aplicadas.

`TRIP_BACKUP_DIR` e `TRIP_ATTACHMENT_DIR` permitem escolher pastas para backups e anexos. Sem essas variáveis, os arquivos ficam em pastas `ControleViagemBackups` e `ControleViagemAttachments` na pasta pessoal do usuário, fora do projeto. Backups e anexos podem conter informações pessoais: armazene-os em local protegido e mantenha cópias externas seguras.

Anexos aceitos: PDF, JPG e PNG, até 10 MB por arquivo e no máximo cinco arquivos por envio. Exportações ZIP incluem os dados da viagem e seus anexos. A restauração valida os arquivos e cria novas viagens sem substituir as existentes.

## Testes

Execute todos os testes com:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## Publicação no Render com Aiven e Cloudinary

O arquivo [render.yaml](render.yaml) configura um serviço web Render com Gunicorn, health check, MySQL obrigatório, login compartilhado, cookies HTTPS e Cloudinary para anexos e capas. Ao conectar o repositório como Blueprint, configure no painel os valores secretos solicitados:

- `DB_PASSWORD`: senha do usuário MySQL do Aiven.
- `APP_LOGIN_USERNAME` e `APP_LOGIN_PASSWORD`: credenciais compartilhadas para acessar o site.
- `CLOUDINARY_API_KEY` e `CLOUDINARY_API_SECRET`: credenciais da conta Cloudinary.
- `APP_SECRET_KEY` é gerada pelo Blueprint; mantenha-a estável entre deploys.

O nome da nuvem Cloudinary e o host/porta/usuário/banco Aiven estão pré-preenchidos no Blueprint com os dados já fornecidos. O serviço exige `DB_SSL_REQUIRED=true`. Sem `DB_SSL_CA`, o MySQL Connector negocia TLS criptografado, mas não valida a identidade do servidor; para validação completa, adicione o certificado CA do Aiven como arquivo secreto no Render e configure `DB_SSL_CA` com o caminho desse arquivo. Nunca coloque senha, API secret ou chave privada no Git ou neste arquivo. Use uma senha forte e exclusiva para o login compartilhado.

O app falha ao iniciar se o MySQL ou Cloudinary obrigatórios não estiverem configurados, em vez de gravar dados no disco efêmero do Render. Os arquivos sobem para o Cloudinary; os metadados ficam no Aiven. Os arquivos usam URLs aleatórias e não são exibidos diretamente na interface, mas o Cloudinary os entrega como recursos não autenticados para quem obtiver a URL; não compartilhe esses links. Os backups diários locais são desativados no Render porque o disco do serviço não é persistente. Exporte regularmente um ZIP pelo próprio app e guarde-o fora do Render; os backups do banco também devem permanecer habilitados no Aiven.

Para migrar as viagens e anexos locais, antes de publicar exporte cada viagem pelo aplicativo local como ZIP. Depois que o site hospedado estiver configurado, entre com o login compartilhado, abra **Restaurar backup**, envie o ZIP e confirme a restauração. O app cria cópias das viagens e envia seus anexos ao Cloudinary. Não use somente o JSON se precisar preservar comprovantes e capas.

O campo `anexo.nome_armazenado` foi ampliado para guardar URLs Cloudinary. A inicialização do app aplica a alteração ao banco existente; o script correspondente está em [20261024_cloudinary_attachment_urls.sql](database/migrations/20261024_cloudinary_attachment_urls.sql). Antes de aplicar manualmente, faça backup do banco e confirme que a migração ainda não foi executada.

## Créditos das bandeiras

As bandeiras SVG locais em [static/flags](static/flags/) são distribuídas pelo FlagCDN, baseado em arquivos vetoriais do Wikimedia Commons. Consulte [Flagpedia](https://flagpedia.net) para informações sobre o projeto.
