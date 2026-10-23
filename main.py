from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from currency_rates import ExchangeRateError, SUPPORTED_CURRENCIES, get_historical_rate
from db_service import storage_manager

PAYMENT_METHODS = ("Pix", "Cartão", "Dinheiro")
ORCAMENTO_ALERTA_PERCENTUAL = 80.0

selected_trip_id = None
CANCELLED = object()


def load_data():
    return {"viagens": storage_manager.list_viagens()}


def save_data(dados):
    storage_manager.save_data(dados)


def prompt_text(mensagem):
    try:
        if "voltar" not in mensagem.lower():
            mensagem = f"{mensagem} [digite 'voltar' para retornar/cancelar]"
        valor = input(mensagem).strip()
    except EOFError:
        return None
    if valor.lower() == "voltar":
        return None
    return valor


def prompt_required_text(mensagem, nome_campo):
    while True:
        valor = prompt_text(mensagem)
        if valor is None:
            return None
        if valor:
            return valor
        print(f"Campo obrigatório: {nome_campo}.")


def prompt_float(mensagem):
    while True:
        valor = prompt_text(mensagem)
        if valor is None:
            return None
        if valor == "":
            return 0.0

        try:
            numero = float(valor.replace(",", "."))
            if numero < 0:
                print("O valor não pode ser negativo.")
                continue
            return numero
        except ValueError:
            print("Valor inválido. Digite um número, por exemplo: 150.00")


def prompt_date(mensagem, nome_campo):
    while True:
        valor = prompt_required_text(mensagem, nome_campo)
        if valor is None:
            return None
        try:
            datetime.strptime(valor, "%d/%m/%Y")
            return valor
        except ValueError:
            print("Data inválida. Use o formato DD/MM/AAAA.")


def prompt_date_optional(mensagem, valor_atual):
    while True:
        valor = prompt_text(mensagem)
        if valor is None:
            return None
        if not valor:
            return valor_atual
        try:
            datetime.strptime(valor, "%d/%m/%Y")
            return valor
        except ValueError:
            print("Data inválida. Use o formato DD/MM/AAAA.")


def prompt_float_optional(mensagem, valor_atual):
    while True:
        valor = prompt_text(mensagem)
        if valor is None:
            return None
        if not valor:
            return float(valor_atual)
        try:
            numero = float(valor.replace(",", "."))
            if numero < 0:
                print("O valor não pode ser negativo.")
                continue
            return numero
        except ValueError:
            print("Valor inválido. Digite um número, por exemplo: 150.00")


def prompt_optional_float(mensagem):
    while True:
        valor = prompt_text(mensagem)
        if valor is None:
            return CANCELLED
        if valor == "":
            return None
        try:
            numero = float(valor.replace(",", "."))
            if numero < 0:
                print("O valor não pode ser negativo.")
                continue
            return numero
        except ValueError:
            print("Valor inválido. Digite um número, por exemplo: 150.00")


def data_esta_no_periodo(data, viagem):
    data_atividade = datetime.strptime(data, "%d/%m/%Y").date()
    data_ida = datetime.strptime(viagem["data_ida"], "%d/%m/%Y").date()
    data_volta = datetime.strptime(viagem["data_volta"], "%d/%m/%Y").date()
    return data_ida <= data_atividade <= data_volta


def prompt_activity_date(viagem, mensagem="Data da atividade (DD/MM/AAAA): "):
    while True:
        data = prompt_date(mensagem, "data da atividade")
        if data is None:
            return None
        if data_esta_no_periodo(data, viagem):
            return data
        print(
            "A data da atividade deve ficar entre "
            f"{viagem['data_ida']} e {viagem['data_volta']}."
        )


def obter_viagem_atual():
    global selected_trip_id
    viagens = storage_manager.list_viagens()
    if not viagens:
        return None
    if selected_trip_id is not None:
        viagem = storage_manager.get_viagem(selected_trip_id)
        if viagem is not None:
            return viagem
    selected_trip_id = max(viagens, key=lambda item: int(item["id"]))["id"]
    return storage_manager.get_viagem(selected_trip_id)


def salvar_viagem(viagem):
    global selected_trip_id
    storage_manager.save_viagem(viagem)
    selected_trip_id = viagem.get("id", selected_trip_id)


def listar_viagens():
    viagens = storage_manager.list_viagens()
    if not viagens:
        print("Nenhuma viagem cadastrada.")
        return []
    print("\n=== VIAGENS CADASTRADAS ===")
    for viagem in viagens:
        print(
            f"{viagem['id']}. {viagem['destino']} "
            f"({viagem['data_ida']} até {viagem['data_volta']})"
        )
    return viagens


def selecionar_viagem(forcar=False):
    global selected_trip_id
    viagens = listar_viagens()
    if not viagens:
        return None
    if not forcar and selected_trip_id is not None:
        selecionada = storage_manager.get_viagem(selected_trip_id)
        if selecionada is not None:
            return selecionada
    if len(viagens) == 1:
        selected_trip_id = viagens[0]["id"]
        return storage_manager.get_viagem(selected_trip_id)

    while True:
        escolha = prompt_text("ID da viagem (ou 'voltar' para o menu): ")
        if escolha is None:
            return None
        try:
            viagem_id = int(escolha)
        except ValueError:
            print("Digite um ID válido.")
            continue
        viagem = storage_manager.get_viagem(viagem_id)
        if viagem:
            selected_trip_id = viagem_id
            print(f"Viagem selecionada: {viagem['destino']}.")
            return viagem
        print("ID de viagem não encontrado.")


def cadastrar_viagem():
    global selected_trip_id
    if selected_trip_id is not None:
        viagem_selecionada = storage_manager.get_viagem(selected_trip_id)
        if viagem_selecionada is not None:
            print(
                f"A viagem '{viagem_selecionada['destino']}' está selecionada. "
                "Desselecione-a antes de cadastrar outra."
            )
            return
        selected_trip_id = None

    destino = prompt_required_text("Destino (ou 'voltar' para o menu): ", "destino")
    if destino is None:
        print("Cadastro cancelado.")
        return
    data_ida = prompt_date("Data de ida (DD/MM/AAAA): ", "data de ida")
    if data_ida is None:
        print("Cadastro cancelado.")
        return
    data_volta = prompt_date("Data de volta (DD/MM/AAAA): ", "data de volta")
    if data_volta is None:
        print("Cadastro cancelado.")
        return
    if datetime.strptime(data_volta, "%d/%m/%Y") < datetime.strptime(data_ida, "%d/%m/%Y"):
        print("A data de volta não pode ser anterior à data de ida.")
        return
    viagem = {
        "destino": destino,
        "data_ida": data_ida,
        "data_volta": data_volta,
        "orcamento_total": 0.0,
        "gastos": [],
        "atividades": [],
            "planejamento": [],
    }
    salvar_viagem(viagem)
    print("Viagem cadastrada e selecionada com sucesso!")


def editar_dados_viagem():
    viagem = selecionar_viagem()
    if not viagem:
        return

    destino = prompt_text(f"Destino [{viagem['destino']}] (Enter mantém): ")
    if destino is None:
        print("Edição cancelada.")
        return
    data_ida = prompt_date_optional(
        f"Data de ida [{viagem['data_ida']}] (Enter mantém): ", viagem["data_ida"]
    )
    if data_ida is None:
        print("Edição cancelada.")
        return
    data_volta = prompt_date_optional(
        f"Data de volta [{viagem['data_volta']}] (Enter mantém): ", viagem["data_volta"]
    )
    if data_volta is None:
        print("Edição cancelada.")
        return
    ida = datetime.strptime(data_ida, "%d/%m/%Y").date()
    volta = datetime.strptime(data_volta, "%d/%m/%Y").date()
    if volta < ida:
        print("A data de volta não pode ser anterior à data de ida. Edição cancelada.")
        return

    periodo_alterado = (data_ida, data_volta) != (viagem["data_ida"], viagem["data_volta"])
    if periodo_alterado:
        viagem_atualizada = {**viagem, "data_ida": data_ida, "data_volta": data_volta}
        atividades_fora_periodo = [
            atividade["nome"]
            for atividade in viagem.get("atividades", [])
            if not data_esta_no_periodo(atividade["data"], viagem_atualizada)
        ]
        if atividades_fora_periodo:
            nomes = ", ".join(atividades_fora_periodo)
            print(
                "As novas datas deixariam atividades fora do período: "
                f"{nomes}. Edição cancelada."
            )
            return

    viagem["destino"] = destino or viagem["destino"]
    viagem["data_ida"] = data_ida
    viagem["data_volta"] = data_volta
    salvar_viagem(viagem)
    print("Dados da viagem atualizados com sucesso!")


def coletar_dados_gasto(categorias=None):
    data_gasto = prompt_date("Data do gasto (DD/MM/AAAA): ", "data do gasto")
    if data_gasto is None:
        return None
    categorias = categorias or []
    if not categorias:
        print("Cadastre uma categoria no planejamento antes de adicionar gastos.")
        return None
    while True:
        categoria = prompt_required_text(
            f"Categoria ({', '.join(categorias)}): ", "categoria"
        )
        if categoria is None:
            return None
        if categoria in categorias:
            break
        print("Selecione uma categoria cadastrada no planejamento da viagem.")
    descricao = prompt_required_text("Descrição: ", "descrição")
    if descricao is None:
        return None

    while True:
        moeda_informada = prompt_required_text(
            f"Moeda ({'/'.join(SUPPORTED_CURRENCIES)}): ", "moeda"
        )
        if moeda_informada is None:
            return None
        moeda = moeda_informada.upper()
        if moeda in SUPPORTED_CURRENCIES:
            break
        print(f"A moeda deve ser uma destas: {', '.join(SUPPORTED_CURRENCIES)}.")

    valor_original = prompt_float("Valor original da nota: ")
    if valor_original is None or valor_original <= 0:
        print("O valor original deve ser maior que zero.")
        return None
    cotacao = 1.0
    if moeda != "BRL":
        requested_date = datetime.strptime(data_gasto, "%d/%m/%Y").date()
        try:
            quote = get_historical_rate(moeda, requested_date)
            cotacao = float(quote["rate"])
            effective_date = datetime.strptime(quote["date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            print(f"Cotação histórica {moeda} para BRL ({effective_date}): {cotacao:.8f}")
        except ExchangeRateError as error:
            print(f"Não foi possível buscar a cotação automaticamente: {error}")
            cotacao = prompt_float(f"Cotação manual {moeda} para BRL (reais por 1 {moeda}): ")
        if cotacao is None or cotacao <= 0:
            print("A cotação deve ser maior que zero.")
            return None

    while True:
        pago_informado = prompt_required_text("Pago? (s/n): ", "status de pagamento")
        if pago_informado is None:
            return None
        pago_resposta = pago_informado.lower()
        if pago_resposta in {"s", "sim", "n", "não", "nao"}:
            break
        print("Informe s para pago ou n para pendente.")
    pago = pago_resposta in {"s", "sim"}
    forma_pagamento = None
    if pago:
        forma_pagamento = prompt_required_text(
            "Forma de pagamento (Pix/Cartão/Dinheiro): ", "forma de pagamento"
        )
        if forma_pagamento is None or forma_pagamento not in PAYMENT_METHODS:
            print("Forma de pagamento inválida.")
            return None
    else:
        forma_pagamento = prompt_text("Forma prevista (opcional): ")
        if forma_pagamento is None:
            return None

    observacao = prompt_text("Observação (opcional): ")
    if observacao is None:
        return None

    return {
        "data_gasto": data_gasto,
        "categoria": categoria,
        "descricao": descricao,
        "moeda": moeda,
        "valor_original": valor_original,
        "cotacao": cotacao,
        "valor_em_brl": float((Decimal(str(valor_original)) * Decimal(str(cotacao))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "forma_pagamento": forma_pagamento or None,
        "pago": pago,
        "observacao": observacao,
    }


def adicionar_gasto():
    viagem = selecionar_viagem()
    if not viagem:
        return
    categorias = [item["categoria"] for item in viagem.get("planejamento", [])]
    gasto = coletar_dados_gasto(categorias)
    if gasto is None:
        print("Cadastro cancelado.")
        return
    viagem.setdefault("gastos", []).append(gasto)
    salvar_viagem(viagem)
    print("Gasto adicionado com sucesso!")


def adicionar_atividade():
    viagem = selecionar_viagem()
    if not viagem:
        return

    nome = prompt_required_text("Nome da atividade (ou 'voltar' para o menu): ", "nome")
    if nome is None:
        print("Cadastro cancelado.")
        return
    data = prompt_activity_date(viagem)
    if data is None:
        print("Cadastro cancelado.")
        return
    custo_estimado = prompt_optional_float("Custo estimado (opcional; Enter pula): ")
    if custo_estimado is CANCELLED:
        print("Cadastro cancelado.")
        return

    viagem.setdefault("atividades", []).append({
        "nome": nome,
        "data": data,
        "custo_estimado": custo_estimado,
    })
    salvar_viagem(viagem)
    print("Atividade adicionada com sucesso!")


def valor_em_reais(gasto):
    valor_original = Decimal(str(gasto.get("valor_original", 0)))
    cotacao = Decimal("1") if gasto.get("moeda", "BRL") == "BRL" else Decimal(str(gasto.get("cotacao", 0)))
    return (valor_original * cotacao).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def valores_pagamento_gasto(gasto):
    total = valor_em_reais(gasto)
    payments = gasto.get("pagamentos")
    if payments:
        paid = sum(
            (Decimal(str(payment.get("valor_brl", 0))) for payment in payments),
            Decimal("0.00"),
        )
        paid = min(max(paid, Decimal("0.00")), total)
    else:
        paid = total if gasto.get("pago", False) else Decimal("0.00")
    return paid, total - paid


def nivel_alerta_orcamento(percentual_usado):
    if percentual_usado is None:
        return None
    if percentual_usado > 100:
        return "excedido"
    if percentual_usado >= ORCAMENTO_ALERTA_PERCENTUAL:
        return "atencao"
    return None


def calcular_totais(viagem):
    planejamento = {
        item["categoria"]: Decimal(str(item.get("valor_previsto", 0)))
        for item in viagem.get("planejamento", [])
    }
    gastos_por_categoria = {}
    pagos_por_categoria = {}
    abertos_por_categoria = {}
    total_gasto = Decimal("0.00")
    total_pago = Decimal("0.00")
    total_em_aberto = Decimal("0.00")

    categorias = list(planejamento.keys())
    for categoria in (*planejamento.keys(), *(gasto["categoria"] for gasto in viagem.get("gastos", []))):
        if categoria not in categorias:
            categorias.append(categoria)

    for gasto in viagem.get("gastos", []):
        categoria = gasto["categoria"]
        convertido = valor_em_reais(gasto)
        pago, em_aberto = valores_pagamento_gasto(gasto)
        gastos_por_categoria[categoria] = gastos_por_categoria.get(categoria, Decimal("0.00")) + convertido
        total_gasto += convertido
        pagos_por_categoria[categoria] = pagos_por_categoria.get(categoria, Decimal("0.00")) + pago
        abertos_por_categoria[categoria] = abertos_por_categoria.get(categoria, Decimal("0.00")) + em_aberto
        total_pago += pago
        total_em_aberto += em_aberto

    linhas = []
    for categoria in categorias:
        previsto = planejamento.get(categoria, Decimal("0.00"))
        gasto = gastos_por_categoria.get(categoria, Decimal("0.00"))
        percentual_usado = float(gasto * 100 / previsto) if previsto > 0 else None
        linhas.append({
            "categoria": categoria,
            "previsto": float(previsto),
            "gasto": float(gasto),
            "pago": float(pagos_por_categoria.get(categoria, Decimal("0.00"))),
            "em_aberto": float(abertos_por_categoria.get(categoria, Decimal("0.00"))),
            "falta": float(previsto - gasto),
            "percentual_usado": percentual_usado,
            "progresso": round(min(100.0, max(0.0, percentual_usado or 0.0)), 1),
            "alerta_orcamento": nivel_alerta_orcamento(percentual_usado),
        })

    total_previsto = sum(planejamento.values(), Decimal("0.00"))
    total_faltante = total_previsto - total_gasto
    percentual_orcamento_usado = (
        float(total_gasto * 100 / total_previsto) if total_previsto > 0 else None
    )
    percentual_pago = float(total_pago * 100 / total_previsto) if total_previsto else 0.0
    estimativa_atividades = sum(
        (Decimal(str(activity.get("custo_estimado") or 0)) for activity in viagem.get("atividades", [])),
        Decimal("0.00"),
    )
    return {
        "categorias": linhas,
        "total_previsto": float(total_previsto),
        "total_gasto": float(total_gasto),
        "total_pago": float(total_pago),
        "total_em_aberto": float(total_em_aberto),
        "total_faltante": float(total_faltante),
        "percentual_orcamento_usado": percentual_orcamento_usado,
        "alerta_orcamento": nivel_alerta_orcamento(percentual_orcamento_usado),
        "percentual_pago": percentual_pago,
        "estimativa_atividades": float(estimativa_atividades),
    }


def escolher_item(viagem, collection, titulo, resumo_item):
    itens = viagem.get(collection, [])
    if not itens:
        print(f"Nenhum registro em {titulo.lower()}.")
        return None

    print(f"\n=== {titulo} ===")
    for indice, item in enumerate(itens, start=1):
        print(f"{indice}. {resumo_item(item)}")
    escolha = prompt_text("Número do item (ou 'voltar' para o menu): ")
    if escolha is None:
        return None
    try:
        indice = int(escolha) - 1
    except ValueError:
        print("Número inválido.")
        return None
    if indice < 0 or indice >= len(itens):
        print("Número fora da lista.")
        return None
    return indice


def editar_gasto():
    viagem = selecionar_viagem()
    if not viagem:
        return
    indice = escolher_item(
        viagem,
        "gastos",
        "GASTOS DA VIAGEM",
        lambda gasto: f"{gasto['descricao']} ({gasto['categoria']})",
    )
    if indice is None:
        return

    gasto = dict(viagem["gastos"][indice])
    categorias = [item["categoria"] for item in viagem.get("planejamento", [])]
    novos_dados = coletar_dados_gasto(categorias)
    if novos_dados is None:
        print("Edição cancelada.")
        return

    gasto.update(novos_dados)
    viagem["gastos"][indice] = gasto
    salvar_viagem(viagem)
    print("Gasto atualizado com sucesso!")


def editar_atividade():
    viagem = selecionar_viagem()
    if not viagem:
        return
    indice = escolher_item(
        viagem,
        "atividades",
        "ATIVIDADES DA VIAGEM",
        lambda atividade: f"{atividade['nome']} ({atividade['data']})",
    )
    if indice is None:
        return

    atividade = dict(viagem["atividades"][indice])
    nome = prompt_required_text("Nome (ou 'voltar' para cancelar): ", "nome")
    if nome is None:
        print("Edição cancelada.")
        return
    data = prompt_activity_date(viagem, "Data (DD/MM/AAAA): ")
    if data is None:
        print("Edição cancelada.")
        return
    custo = prompt_optional_float("Custo estimado (opcional; Enter pula): ")
    if custo is CANCELLED:
        print("Edição cancelada.")
        return

    atividade.update({"nome": nome, "data": data, "custo_estimado": custo})
    viagem["atividades"][indice] = atividade
    salvar_viagem(viagem)
    print("Atividade atualizada com sucesso!")


def remover_item(collection, titulo, resumo_item):
    viagem = selecionar_viagem()
    if not viagem:
        return
    indice = escolher_item(viagem, collection, titulo, resumo_item)
    if indice is None:
        return
    resposta = prompt_text("Confirma a exclusão? (s/n): ")
    if resposta is None or resposta.lower() not in {"s", "sim"}:
        print("Exclusão cancelada.")
        return
    viagem[collection].pop(indice)
    salvar_viagem(viagem)
    print("Registro removido com sucesso!")


def gerenciar_registros():
    while True:
        print("\n=== GERENCIAR REGISTROS ===")
        print("1. Editar gasto")
        print("2. Remover gasto")
        print("3. Editar atividade")
        print("4. Remover atividade")
        print("0. Voltar ao menu principal")
        opcao = prompt_text("Escolha uma opção: ")
        if opcao is None or opcao == "0":
            return
        if opcao == "1":
            editar_gasto()
        elif opcao == "2":
            remover_item("gastos", "GASTOS DA VIAGEM", lambda gasto: gasto["descricao"])
        elif opcao == "3":
            editar_atividade()
        elif opcao == "4":
            remover_item("atividades", "ATIVIDADES DA VIAGEM", lambda atividade: atividade["nome"])
        else:
            print("Opção inválida.")


def excluir_viagem():
    global selected_trip_id
    viagem = selecionar_viagem()
    if not viagem:
        return
    resposta = prompt_text(
        f"Excluir a viagem '{viagem['destino']}' e seus registros? (s/n): "
    )
    if resposta is None or resposta.lower() not in {"s", "sim"}:
        print("Exclusão cancelada.")
        return
    storage_manager.delete_viagem(viagem["id"])
    selected_trip_id = None
    print("Viagem e registros associados removidos.")


def desselecionar_viagem():
    global selected_trip_id
    if selected_trip_id is None:
        print("Nenhuma viagem está selecionada.")
        return
    selected_trip_id = None
    print("Viagem desselecionada. Agora você pode cadastrar outra viagem.")


def ver_resumo():
    viagem = selecionar_viagem()
    if not viagem:
        print("Nenhuma viagem cadastrada.")
        return

    resumo = calcular_totais(viagem)

    print("\n=== RESUMO DA VIAGEM ===")
    print(f"Destino: {viagem['destino']}")
    print(f"Data de ida: {viagem['data_ida']}")
    print(f"Data de volta: {viagem['data_volta']}")
    print(f"Total previsto: R$ {resumo['total_previsto']:.2f}")
    print(f"Gasto registrado: R$ {resumo['total_gasto']:.2f}")
    print(f"Total pago: R$ {resumo['total_pago']:.2f}")
    print(f"A pagar: R$ {resumo['total_em_aberto']:.2f}")
    print(f"Saldo do planejamento: R$ {resumo['total_faltante']:.2f}")
    print("Saldo positivo é valor restante; saldo negativo indica excedente.")
    print(f"Percentual já pago: {resumo['percentual_pago']:.1f}%")
    print(f"Estimativas de atividades (fora do resumo): R$ {resumo['estimativa_atividades']:.2f}")
    print("\nPlanejamento por categoria:")
    for linha in resumo["categorias"]:
        print(
            f"- {linha['categoria']}: Previsto R$ {linha['previsto']:.2f} | "
            f"Gasto R$ {linha['gasto']:.2f} | Pago R$ {linha['pago']:.2f} | "
            f"A pagar R$ {linha['em_aberto']:.2f} | Saldo R$ {linha['falta']:.2f}"
        )


def editar_planejamento():
    viagem = selecionar_viagem()
    if not viagem:
        return

    atuais = {
        item["categoria"]: float(item.get("valor_previsto", 0.0))
        for item in viagem.get("planejamento", [])
    }
    planejamento = []
    for categoria in atuais:
        previsto = prompt_float_optional(
            f"{categoria} (previsto R$ {atuais.get(categoria, 0.0):.2f}; Enter mantém): ",
            atuais.get(categoria, 0.0),
        )
        if previsto is None:
            print("Edição do planejamento cancelada.")
            return
        planejamento.append({"categoria": categoria, "valor_previsto": previsto})

    categorias_existentes = {categoria.casefold() for categoria in atuais}
    while True:
        categoria = prompt_text("Nova categoria (Enter conclui): ")
        if categoria is None:
            print("Edição do planejamento cancelada.")
            return
        if not categoria:
            break
        if categoria.casefold() in categorias_existentes:
            print("Essa categoria já existe.")
            continue
        previsto = prompt_float(f"Previsto para {categoria} em BRL: ")
        if previsto is None:
            print("Edição do planejamento cancelada.")
            return
        planejamento.append({"categoria": categoria, "valor_previsto": previsto})
        categorias_existentes.add(categoria.casefold())

    viagem["planejamento"] = planejamento
    salvar_viagem(viagem)
    print("Planejamento por categoria salvo.")


def gerar_relatorio():
    viagem = selecionar_viagem()
    if not viagem:
        print("Nenhuma viagem cadastrada para gerar relatório.")
        return

    resumo = calcular_totais(viagem)

    print("\n" + "=" * 48)
    print("RELATÓRIO DA VIAGEM".center(48))
    print("=" * 48)
    print(f"Destino: {viagem['destino']}")
    print(f"Período: {viagem['data_ida']} até {viagem['data_volta']}")
    print(f"Total previsto: R$ {resumo['total_previsto']:.2f}")
    print(f"Gasto registrado: R$ {resumo['total_gasto']:.2f}")
    print(f"Total pago: R$ {resumo['total_pago']:.2f}")
    print(f"A pagar: R$ {resumo['total_em_aberto']:.2f}")
    print(f"Saldo do planejamento: R$ {resumo['total_faltante']:.2f}")
    print("Saldo positivo é valor restante; saldo negativo indica excedente.")
    print(f"Percentual já pago: {resumo['percentual_pago']:.1f}%")
    print(f"Estimativas de atividades (fora do resumo): R$ {resumo['estimativa_atividades']:.2f}")
    print("=" * 48)

    print("\nGastos:")
    if viagem.get("gastos"):
        for gasto in viagem["gastos"]:
            print(
                f"- {gasto['data_gasto']} {gasto['categoria']} {gasto['descricao']}: "
                f"{gasto['valor_original']:.2f} {gasto['moeda']} = "
                f"R$ {valor_em_reais(gasto):.2f} | {'Pago' if gasto['pago'] else 'Pendente'}"
            )
    else:
        print("Nenhum gasto registrado.")

    print("\nAtividades:")
    if viagem.get("atividades"):
        for atividade in viagem["atividades"]:
            custo_estimado = atividade.get("custo_estimado")
            custo_label = (
                f"Custo estimado R$ {float(custo_estimado):.2f}"
                if custo_estimado is not None
                else "Custo não estimado"
            )
            print(
                f"- {atividade['nome']} ({atividade['data']}): {custo_label}"
            )
    else:
        print("Nenhuma atividade registrada.")


def exibir_menu():
    global selected_trip_id
    print("\n" + "=" * 40)
    print("CONTROLE DE VIAGEM".center(40))
    print("=" * 40)
    if selected_trip_id is not None:
        viagem = storage_manager.get_viagem(selected_trip_id)
        if viagem:
            print(f"Viagem selecionada: {viagem['destino']}")
            print("-" * 40)
            print("9. Desselecionar viagem")
        else:
            selected_trip_id = None
    if selected_trip_id is None:
        print("1. Cadastrar viagem")
    print("2. Adicionar gasto")
    print("3. Adicionar atividade")
    print("4. Ver resumo")
    print("5. Gerar relatório")
    print("6. Editar/remover gastos e atividades")
    print("7. Listar/selecionar viagem")
    print("8. Excluir viagem")
    print("10. Editar dados da viagem")
    print("11. Planejar orçamento por categoria")
    print("0. Sair")
    print("=" * 40)


def main():
    while True:
        exibir_menu()
        try:
            opcao = input("Escolha uma opção: ").strip()
        except EOFError:
            print("\nEntrada encerrada. Encerrando programa.")
            break
        except KeyboardInterrupt:
            print("\nPrograma encerrado pelo usuário.")
            break

        if storage_manager.mysql_error is not None:
            print(f"Aviso: banco MySQL indisponível ({storage_manager.mysql_error}). Usando arquivo JSON como fallback.")
            storage_manager.mysql_error = None

        if opcao == "":
            print("Opção vazia. Digite uma opção válida.")
            continue

        if opcao == "1":
            cadastrar_viagem()
        elif opcao == "2":
            adicionar_gasto()
        elif opcao == "3":
            adicionar_atividade()
        elif opcao == "4":
            ver_resumo()
        elif opcao == "5":
            gerar_relatorio()
        elif opcao == "6":
            gerenciar_registros()
        elif opcao == "7":
            selecionar_viagem(forcar=True)
        elif opcao == "8":
            excluir_viagem()
        elif opcao == "9" and selected_trip_id is not None:
            desselecionar_viagem()
        elif opcao == "10":
            editar_dados_viagem()
        elif opcao == "11":
            editar_planejamento()
        elif opcao == "0":
            print("Programa encerrado.")
            break
        else:
            print("Opção inválida. Tente novamente.")


if __name__ == "__main__":
    main()
