from decimal import Decimal
from datetime import timedelta
from collections import defaultdict
import unicodedata
import uuid
from django.db import transaction, IntegrityError
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import Venda, ItemVenda, PagamentoVenda
from apps.produtos.models import Produto
from apps.produtos.services import StockService
from apps.clientes.models import Cliente
from apps.financeiro.models import ContaReceber, FluxoCaixa, PagamentoContaReceber
from apps.core.models import AuditService

class SaleService:
    @staticmethod
    def processar_venda(
        empresa,
        operador,
        sessao_caixa,
        itens_data: list,
        pagamentos_data: list,
        cliente=None,
        desconto: Decimal | float = 0.00,
        offline_uuid: str = '',
        observacao: str = '',
        recebimento_divida: dict = None
    ) -> Venda | dict:
        """
        Ponto de entrada para processamento de venda com garantia de Idempotência Semântica.
        Se um offline_uuid for enviado e já existir no banco, retorna a venda original
        sem reprocessar, sem alterar estoque, sem duplicar pagamentos ou fluxo de caixa.
        """
        # 1. Checagem prévia de Idempotência
        if offline_uuid:
            venda_existente = Venda.objects.filter(empresa=empresa, offline_uuid=offline_uuid).first()
            if venda_existente:
                return venda_existente

        try:
            # 2. Execução dentro de transação atômica isolada
            return SaleService._processar_venda_atomica(
                empresa=empresa,
                operador=operador,
                sessao_caixa=sessao_caixa,
                itens_data=itens_data,
                pagamentos_data=pagamentos_data,
                cliente=cliente,
                desconto=desconto,
                offline_uuid=offline_uuid,
                observacao=observacao,
                recebimento_divida=recebimento_divida
            )
        except IntegrityError as e:
            # 3. Tratamento seguro de colisão de concorrência:
            if offline_uuid:
                venda_existente = Venda.objects.filter(empresa=empresa, offline_uuid=offline_uuid).first()
                if venda_existente:
                    return venda_existente
            raise e

    @staticmethod
    @transaction.atomic
    def _processar_venda_atomica(
        empresa,
        operador,
        sessao_caixa,
        itens_data: list,
        pagamentos_data: list,
        cliente=None,
        desconto: Decimal | float = 0.00,
        offline_uuid: str = '',
        observacao: str = '',
        recebimento_divida: dict = None
    ) -> Venda | dict:
        """
        Processamento transacional atômico do checkout (Venda, Itens, Estoque, Pagamentos, Caixa, Dívida FIFO).
        Qualquer exceção causa Rollback Total automático no banco de dados.
        """
        tem_itens = bool(itens_data and len(itens_data) > 0)
        tem_divida = bool(recebimento_divida and isinstance(recebimento_divida, dict))

        if not tem_itens and not tem_divida:
            raise ValueError("O checkout precisa conter ao menos um item de produto ou uma operação de recebimento de dívida.")

        if not pagamentos_data:
            raise ValueError("Informe ao menos uma forma de pagamento para finalizar o checkout.")

        if sessao_caixa:
            if sessao_caixa.status != 'ABERTA':
                raise ValueError("Não é possível realizar operações em um caixa fechado.")
            from apps.caixas.services import CashService
            CashService.validar_sessao_dia_operacional(sessao_caixa)

        # ---------------------------------------------------------------------
        # 1. Validação Estrita do Recebimento de Dívida (se presente)
        # ---------------------------------------------------------------------
        valor_pago_divida = Decimal('0.00')
        valor_abatimento_divida = Decimal('0.00')
        motivo_abatimento_divida = ''
        cliente_divida = None
        contas_divida = []

        if tem_divida:
            cli_divida_id = recebimento_divida.get('cliente_id')
            if not cli_divida_id:
                raise ValueError("Cliente é obrigatório para o recebimento de dívida.")

            if not cliente or cliente.id != int(cli_divida_id):
                raise ValueError("Este checkout possui um recebimento de dívida. O cliente do checkout deve ser o mesmo cliente da dívida.")

            try:
                cliente_divida = Cliente.objects.select_for_update().get(id=cli_divida_id, empresa=empresa)
            except Cliente.DoesNotExist:
                raise ValueError(f"Cliente ID {cli_divida_id} não encontrado ou não pertence a esta empresa.")

            if not cliente_divida.ativo:
                raise ValueError(f"O cliente '{cliente_divida.nome}' está inativo.")

            # Busca todas as contas a receber pendentes com lock de concorrência
            contas_divida = list(ContaReceber.objects.select_for_update().filter(
                empresa=empresa,
                cliente=cliente_divida,
                status__in=['ABERTA', 'PARCIAL', 'PENDENTE']
            ).order_by('data_vencimento', 'id'))

            saldo_devedor_real = sum((c.saldo for c in contas_divida), Decimal('0.00'))

            valor_pago_divida = Decimal(str(recebimento_divida.get('valor_pago', '0.00'))).quantize(Decimal('0.01'))
            valor_abatimento_divida = Decimal(str(recebimento_divida.get('valor_abatimento', '0.00'))).quantize(Decimal('0.01'))
            motivo_abatimento_divida = str(recebimento_divida.get('motivo_abatimento', '')).strip()

            if valor_pago_divida < Decimal('0.00'):
                raise ValueError("O valor a pagar da dívida não pode ser negativo.")

            if valor_abatimento_divida < Decimal('0.00'):
                raise ValueError("O valor de abatimento da dívida não pode ser negativo.")

            total_liquidado_divida = (valor_pago_divida + valor_abatimento_divida).quantize(Decimal('0.01'))
            if total_liquidado_divida <= Decimal('0.00'):
                raise ValueError("O total liquidado da dívida (pagamento + abatimento) deve ser maior que zero.")

            if valor_abatimento_divida > saldo_devedor_real:
                raise ValueError(f"O abatimento (R$ {valor_abatimento_divida:.2f}) não pode ser superior à dívida total consolidada (R$ {saldo_devedor_real:.2f}).")

            if total_liquidado_divida > saldo_devedor_real:
                raise ValueError(f"O total liquidado (R$ {total_liquidado_divida:.2f}) não pode ser superior à dívida total consolidada (R$ {saldo_devedor_real:.2f}).")

        # ---------------------------------------------------------------------
        # 2. Validação de Itens, Estoque e Subtotal de Produtos
        # ---------------------------------------------------------------------
        subtotal_produtos = Decimal('0.00')
        desconto_dec = Decimal('0.00')
        total_venda_produtos = Decimal('0.00')
        itens_para_criar = []

        if tem_itens:
            for item in itens_data:
                prod_id = item.get('produto_id')
                if not prod_id:
                    raise ValueError("Identificador do produto é obrigatório para todos os itens.")

                quant = Decimal(str(item.get('quantidade', 0)))
                if quant <= Decimal('0.000'):
                    raise ValueError("A quantidade de cada produto deve ser estritamente maior que zero.")

                try:
                    produto = Produto.objects.select_for_update().get(id=prod_id, empresa=empresa, ativo=True)
                except Produto.DoesNotExist:
                    raise ValueError(f"Produto ID {prod_id} não encontrado ou inativo.")

                if produto.estoque_atual < quant:
                    raise ValueError(f"Estoque insuficiente para '{produto.nome}'. Estoque atual: {produto.estoque_atual}, Solicitado: {quant}")

                preco_venda_unit = Decimal(str(item.get('preco_venda', produto.preco_venda)))
                if preco_venda_unit <= Decimal('0.00'):
                    raise ValueError(f"Preço de venda inválido para '{produto.nome}'. O valor deve ser estritamente maior que zero.")

                subtotal_item = (quant * preco_venda_unit).quantize(Decimal('0.01'))
                subtotal_produtos += subtotal_item

                itens_para_criar.append({
                    'produto': produto,
                    'quantidade': quant,
                    'preco_custo_unitario': produto.preco_custo,
                    'preco_venda_unitario': preco_venda_unit,
                    'subtotal': subtotal_item,
                })

            desconto_dec = Decimal(str(desconto)).quantize(Decimal('0.01'))
            if desconto_dec < Decimal('0.00'):
                raise ValueError("O valor de desconto não pode ser negativo.")

            if desconto_dec > subtotal_produtos:
                raise ValueError(f"O desconto (R$ {desconto_dec:.2f}) não pode ser maior que o subtotal da venda (R$ {subtotal_produtos:.2f}).")

            total_venda_produtos = (subtotal_produtos - desconto_dec).quantize(Decimal('0.01'))

        # ---------------------------------------------------------------------
        # 3. Total Financeiro a Pagar no Checkout (Venda + Dívida)
        # ---------------------------------------------------------------------
        total_checkout = (total_venda_produtos + valor_pago_divida).quantize(Decimal('0.01'))

        # ---------------------------------------------------------------------
        # 4. Validação Estrita dos Pagamentos e Troco
        # ---------------------------------------------------------------------
        total_liquido_pago = Decimal('0.00')
        pagamentos_validados = []

        for pag in pagamentos_data:
            forma = pag.get('forma')
            if forma not in ['DINHEIRO', 'CARTAO_CREDITO', 'CARTAO_DEBITO', 'PIX', 'CREDIARIO']:
                raise ValueError(f"Forma de pagamento '{forma}' inválida.")

            val_pago = Decimal(str(pag.get('valor', 0.00))).quantize(Decimal('0.01'))
            troco_pago = Decimal(str(pag.get('troco', 0.00))).quantize(Decimal('0.01'))

            if val_pago <= Decimal('0.00'):
                raise ValueError("O valor de cada forma de pagamento deve ser maior que zero.")

            if troco_pago < Decimal('0.00'):
                raise ValueError("O troco não pode ser negativo.")

            if troco_pago > Decimal('0.00') and forma != 'DINHEIRO':
                raise ValueError("Troco só é permitido para pagamentos em Dinheiro.")

            if forma == 'DINHEIRO' and troco_pago >= val_pago and total_checkout > 0:
                raise ValueError("O troco não pode ser maior ou igual ao valor recebido em dinheiro.")

            valor_efetivo = val_pago - troco_pago
            total_liquido_pago += valor_efetivo

            pagamentos_validados.append({
                'forma': forma,
                'valor': val_pago,
                'troco': troco_pago,
                'valor_efetivo': valor_efetivo,
                'dados': pag.get('dados', {})
            })

        if abs(total_liquido_pago - total_checkout) > Decimal('0.01'):
            if total_liquido_pago < total_checkout:
                faltante = total_checkout - total_liquido_pago
                raise ValueError(f"Pagamento insuficiente. Total a pagar: R$ {total_checkout:.2f}, Total pago: R$ {total_liquido_pago:.2f}. Faltam R$ {faltante:.2f}.")
            else:
                excedente = total_liquido_pago - total_checkout
                raise ValueError(f"O total líquido pago (R$ {total_liquido_pago:.2f}) excede o total a pagar (R$ {total_checkout:.2f}) em R$ {excedente:.2f}.")

        # ---------------------------------------------------------------------
        # 5. Processamento da Nova Venda de Produtos (se houver itens)
        # ---------------------------------------------------------------------
        venda = None
        if tem_itens:
            codigo_venda = f"VD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

            venda = Venda.objects.create(
                empresa=empresa,
                sessao_caixa=sessao_caixa,
                cliente=cliente,
                operador=operador,
                codigo_venda=codigo_venda,
                subtotal=subtotal_produtos,
                desconto=desconto_dec,
                total=total_venda_produtos,
                status='CONCLUIDA',
                offline_uuid=offline_uuid,
                observacao=observacao
            )

            for item in itens_para_criar:
                ItemVenda.objects.create(
                    empresa=empresa,
                    venda=venda,
                    produto=item['produto'],
                    quantidade=item['quantidade'],
                    preco_custo_unitario=item['preco_custo_unitario'],
                    preco_venda_unitario=item['preco_venda_unitario'],
                    subtotal=item['subtotal']
                )

                StockService.remove_stock(
                    produto=item['produto'],
                    quantidade=item['quantidade'],
                    motivo=f"Venda #{venda.codigo_venda}",
                    origem_ref=venda.codigo_venda
                )

            # Rateio dos pagamentos para a Venda de Produtos
            restante_venda = total_venda_produtos
            for pag in pagamentos_validados:
                if restante_venda <= Decimal('0.00'):
                    break

                val_para_venda = min(restante_venda, pag['valor_efetivo'])
                troco_para_venda = pag['troco'] if pag['valor_efetivo'] == val_para_venda else Decimal('0.00')

                PagamentoVenda.objects.create(
                    empresa=empresa,
                    venda=venda,
                    forma_pagamento=pag['forma'],
                    valor=(val_para_venda + troco_para_venda),
                    troco=troco_para_venda,
                    dados_transacao=pag['dados']
                )

                if pag['forma'] != 'CREDIARIO':
                    FluxoCaixa.objects.create(
                        empresa=empresa,
                        tipo='ENTRADA',
                        categoria='Venda PDV',
                        descricao=f"Venda #{venda.codigo_venda} ({pag['forma']})",
                        valor=val_para_venda,
                        referencia_origem=venda.codigo_venda
                    )
                else:
                    # Crediário gera Conta a Receber e ajusta saldo devedor
                    if not cliente:
                        raise ValueError("Vendas em Crediário/Fiado exigem a seleção de um Cliente cadastrado.")

                    cliente_db = Cliente.objects.select_for_update().get(id=cliente.id, empresa=empresa)
                    if not cliente_db.ativo:
                        raise ValueError(f"O cliente '{cliente_db.nome}' está inativo.")

                    if cliente_db.limite_credito > Decimal('0.00') and (cliente_db.saldo_devedor + val_para_venda) > cliente_db.limite_credito:
                        raise ValueError(
                            f"Limite de crédito insuficiente para '{cliente_db.nome}'. "
                            f"Limite: R$ {cliente_db.limite_credito:.2f}, Saldo Devedor Atual: R$ {cliente_db.saldo_devedor:.2f}."
                        )

                    conta_rec = ContaReceber.objects.create(
                        empresa=empresa,
                        venda=venda,
                        cliente=cliente_db,
                        descricao=f"Crediário Venda #{venda.codigo_venda}",
                        valor=val_para_venda,
                        valor_original=val_para_venda,
                        valor_pago=Decimal('0.00'),
                        data_vencimento=timezone.now().date() + timezone.timedelta(days=30),
                        status='ABERTA'
                    )

                    cliente_db.saldo_devedor += val_para_venda
                    cliente_db.save()

                    AuditService.registrar(
                        empresa=empresa,
                        usuario=operador,
                        acao='CREDIARIO_CONCEDIDO',
                        entidade='ContaReceber',
                        entidade_id=conta_rec.id,
                        descricao=f"Crediário de R$ {val_para_venda:.2f} concedido ao cliente {cliente_db.nome} (Venda #{venda.codigo_venda})",
                        dados_posteriores={'conta_id': conta_rec.id, 'cliente_id': cliente_db.id, 'valor': str(val_para_venda)}
                    )

                restante_venda -= val_para_venda

            AuditService.registrar(
                empresa=empresa,
                usuario=operador,
                acao='VENDA_CRIADA',
                entidade='Venda',
                entidade_id=venda.id,
                descricao=f"Venda #{venda.codigo_venda} finalizada no valor de R$ {venda.total:.2f}",
                dados_posteriores={
                    'codigo_venda': venda.codigo_venda,
                    'total': str(venda.total),
                    'desconto': str(venda.desconto),
                    'itens_qtd': str(len(itens_data))
                }
            )

        # ---------------------------------------------------------------------
        # 6. Processamento da Baixa de Dívida / Quitação FIFO (se houver dívida)
        # ---------------------------------------------------------------------
        if tem_divida:
            restante_liquidar = (valor_pago_divida + valor_abatimento_divida).quantize(Decimal('0.01'))
            restante_pago = valor_pago_divida
            restante_abatimento = valor_abatimento_divida

            # Determina a forma de pagamento principal utilizada para a dívida
            forma_divida = 'DINHEIRO'
            for pag in reversed(pagamentos_validados):
                if pag['forma'] != 'CREDIARIO':
                    forma_divida = pag['forma']
                    break

            for conta in contas_divida:
                if restante_liquidar <= Decimal('0.00'):
                    break

                saldo_c = conta.saldo
                if saldo_c <= Decimal('0.00'):
                    continue

                liquidar_nesta = min(saldo_c, restante_liquidar)
                pago_nesta = min(restante_pago, liquidar_nesta)
                abat_nesta = min(restante_abatimento, (liquidar_nesta - pago_nesta))

                conta.valor_pago = (Decimal(str(conta.valor_pago or '0.00')) + liquidar_nesta).quantize(Decimal('0.01'))
                if conta.saldo <= Decimal('0.00'):
                    conta.status = 'QUITADA'
                    conta.data_pagamento = timezone.now().date()
                else:
                    conta.status = 'PARCIAL'
                conta.save()

                PagamentoContaReceber.objects.create(
                    empresa=empresa,
                    conta_receber=conta,
                    valor=pago_nesta,
                    troco=Decimal('0.00'),
                    valor_abatimento=abat_nesta,
                    motivo_abatimento=motivo_abatimento_divida,
                    forma_pagamento=forma_divida,
                    sessao_caixa=sessao_caixa,
                    usuario=operador,
                    observacao=f"Recebimento Dívida PDV"
                )

                if pago_nesta > Decimal('0.00'):
                    FluxoCaixa.objects.create(
                        empresa=empresa,
                        tipo='ENTRADA',
                        categoria='Recebimento Fiado',
                        descricao=f"Recebimento Dívida #{conta.id} - {cliente_divida.nome} ({forma_divida})",
                        valor=pago_nesta,
                        referencia_origem=f"REC-DIV-{conta.id}"
                    )

                restante_liquidar -= liquidar_nesta
                restante_pago -= pago_nesta
                restante_abatimento -= abat_nesta

            # Atualiza saldo devedor consolidado do cliente
            cliente_divida.saldo_devedor = max(Decimal('0.00'), cliente_divida.saldo_devedor - (valor_pago_divida + valor_abatimento_divida))
            cliente_divida.save()

            AuditService.registrar(
                empresa=empresa,
                usuario=operador,
                acao='RECEBIMENTO_DIVIDA_PDV',
                entidade='Cliente',
                entidade_id=cliente_divida.id,
                descricao=f"Recebimento de dívida PDV do cliente '{cliente_divida.nome}'. Pago: R$ {valor_pago_divida:.2f}, Abatimento: R$ {valor_abatimento_divida:.2f}",
                dados_posteriores={
                    'cliente': cliente_divida.nome,
                    'valor_pago': str(valor_pago_divida),
                    'valor_abatimento': str(valor_abatimento_divida),
                    'saldo_devedor_restante': str(cliente_divida.saldo_devedor),
                    'motivo_abatimento': motivo_abatimento_divida
                }
            )

        if venda is not None:
            return venda

        return {
            'status': 'CONCLUIDA',
            'tipo': 'RECEBIMENTO_DIVIDA',
            'cliente': cliente_divida.nome if cliente_divida else '',
            'valor_pago': float(valor_pago_divida),
            'valor_abatimento': float(valor_abatimento_divida),
            'total_liquidado': float(valor_pago_divida + valor_abatimento_divida),
            'saldo_devedor_restante': float(cliente_divida.saldo_devedor if cliente_divida else 0.0)
        }


    # =========================================================================
    # CANCELAMENTO TRANSACIONAL DE VENDA
    # =========================================================================
    @staticmethod
    def cancelar_venda(venda_id: int, empresa, usuario, motivo: str) -> Venda:
        """
        Cancela uma venda CONCLUÍDA de forma transacional e atômica.
        - Bloqueia duplo cancelamento.
        - Estorna estoque (cria MovimentacaoEstoque tipo ESTORNO).
        - Estorna impacto financeiro por forma de pagamento.
        - Reverte crediário e saldo_devedor do cliente.
        - Registra auditoria.
        - Qualquer falha causa rollback completo.
        """
        from apps.core.models import AuditService

        if not motivo or not motivo.strip():
            raise ValueError("O motivo do cancelamento é obrigatório.")

        if not usuario.pode_cancelar_venda:
            raise PermissionError("Usuário sem permissão para cancelar vendas.")

        return SaleService._cancelar_venda_atomica(venda_id, empresa, usuario, motivo.strip())

    @staticmethod
    @transaction.atomic
    def _cancelar_venda_atomica(venda_id: int, empresa, usuario, motivo: str) -> Venda:
        from apps.core.models import AuditService
        from apps.produtos.models import Produto, MovimentacaoEstoque

        # 1. Lock na venda para concorrência
        try:
            venda = Venda.objects.select_for_update().get(id=venda_id, empresa=empresa)
        except Venda.DoesNotExist:
            raise ValueError("Venda não encontrada nesta empresa.")

        # Validação de permissão específica por cargo:
        # Administrador e Gerente podem cancelar qualquer venda do tenant.
        # Operador pode cancelar SOMENTE as vendas que ele próprio realizou.
        if not (usuario.is_admin or usuario.is_gerente or usuario.is_superuser):
            if usuario.cargo == 'OPERADOR':
                if venda.operador_id != usuario.id:
                    raise PermissionError("Operador só tem permissão para cancelar suas próprias vendas.")
            else:
                raise PermissionError("Usuário sem permissão para cancelar vendas.")

        # 2. Bloquear duplo cancelamento
        if venda.status == 'CANCELADA':
            raise ValueError("Esta venda já foi cancelada anteriormente.")

        if venda.status != 'CONCLUIDA':
            raise ValueError(f"Apenas vendas CONCLUÍDAS podem ser canceladas. Status atual: {venda.status}")

        # 3. Snapshot para auditoria
        dados_anteriores = {
            'status': venda.status,
            'total': str(venda.total),
            'codigo_venda': venda.codigo_venda,
        }

        # 4. Estorno de estoque - devolver itens ao estoque
        itens = venda.itens.select_related('produto').all()
        for item in itens:
            prod = Produto.objects.select_for_update().get(id=item.produto_id)
            estoque_anterior = prod.estoque_atual
            prod.estoque_atual += item.quantidade
            estoque_posterior = prod.estoque_atual
            prod.save()

            MovimentacaoEstoque.objects.create(
                empresa=empresa,
                produto=prod,
                tipo='ESTORNO',
                quantidade=item.quantidade,
                estoque_anterior=estoque_anterior,
                estoque_posterior=estoque_posterior,
                preco_custo_unitario=item.preco_custo_unitario,
                motivo=f"Estorno Venda #{venda.codigo_venda} cancelada: {motivo}",
                usuario=usuario,
                origem_ref=f"CANC-{venda.codigo_venda}"
            )

        # 5. Estorno financeiro por forma de pagamento
        pagamentos = venda.pagamentos.all()
        for pag in pagamentos:
            valor_efetivo = pag.valor - pag.troco

            if pag.forma_pagamento == 'CREDIARIO':
                # Reverter ContaReceber e saldo_devedor do cliente
                contas = ContaReceber.objects.filter(
                    empresa=empresa, venda=venda
                ).exclude(status='CANCELADA')
                for conta in contas:
                    if conta.cliente:
                        cliente_db = Cliente.objects.select_for_update().get(
                            id=conta.cliente_id, empresa=empresa
                        )
                        # Subtrai o saldo que ainda está em aberto
                        saldo_aberto = conta.saldo
                        cliente_db.saldo_devedor = max(
                            Decimal('0.00'),
                            cliente_db.saldo_devedor - saldo_aberto
                        )
                        cliente_db.save()

                    conta.status = 'CANCELADA'
                    conta.observacoes = (
                        f"{conta.observacoes}\n"
                        f"[CANCELADA] Venda #{venda.codigo_venda} cancelada por {usuario.username}: {motivo}"
                    ).strip()
                    conta.save()
            else:
                # Registrar estorno no FluxoCaixa
                FluxoCaixa.objects.create(
                    empresa=empresa,
                    tipo='SAIDA',
                    categoria='Estorno Venda',
                    descricao=f"Estorno Venda #{venda.codigo_venda} ({pag.forma_pagamento}): {motivo}",
                    valor=valor_efetivo,
                    referencia_origem=f"CANC-{venda.codigo_venda}"
                )

        # 6. Atualizar status da venda
        venda.status = 'CANCELADA'
        venda.motivo_cancelamento = motivo
        venda.cancelado_por = usuario
        venda.data_cancelamento = timezone.now()
        venda.save()

        # 7. Registrar auditoria
        dados_posteriores = {
            'status': 'CANCELADA',
            'motivo_cancelamento': motivo,
            'cancelado_por': usuario.username,
            'data_cancelamento': str(venda.data_cancelamento),
        }

        AuditService.registrar(
            empresa=empresa,
            usuario=usuario,
            acao='VENDA_CANCELADA',
            entidade='Venda',
            entidade_id=venda.id,
            descricao=f"Cancelamento da Venda #{venda.codigo_venda} (R$ {venda.total})",
            dados_anteriores=dados_anteriores,
            dados_posteriores=dados_posteriores,
            motivo=motivo
        )

        return venda

    @staticmethod
    def normalizar_primeira_letra(nome: str) -> str:
        """
        Normaliza a primeira letra do nome do produto para agrupamento alfabético:
        - A / Á / À / Ã / Â -> A
        - E / É / Ê -> E
        - I / Í / Î -> I
        - O / Ó / Ô / Õ -> O
        - U / Ú / Ü -> U
        - Ç -> C
        - Dígitos (0-9) -> '0-9'
        - Demais caracteres especiais -> '#'
        """
        if not nome:
            return '#'
        nome_limpo = str(nome).strip()
        if not nome_limpo:
            return '#'
        primeiro_char = nome_limpo[0].upper()
        if primeiro_char == 'Ç':
            return 'C'
        decomp = unicodedata.normalize('NFD', primeiro_char)
        sem_acento = ''.join(c for c in decomp if unicodedata.category(c) != 'Mn')
        if sem_acento.isalpha():
            return sem_acento.upper()
        if sem_acento.isdigit():
            return '0-9'
        return '#'

    @staticmethod
    def obter_produtos_rapidos_agrupados(empresa) -> list:
        """
        Retorna os produtos rápidos agrupados por letra inicial:
        - Considera a totalidade dos produtos ativos da empresa (sem corte preliminar)
        - Calcula a quantidade vendida nos últimos 60 dias (apenas vendas CONCLUIDAS)
        - Produtos sem venda recebem quantidade 0 e permanecem elegíveis
        - Ordena por maior quantidade vendida nos últimos 60 dias e desempata por nome alfabético
        - Seleciona no máximo 4 produtos por letra
        - Grupos ordenados alfabeticamente: A -> Z, depois '0-9' e '#'
        """
        data_limite = timezone.now() - timedelta(days=60)

        # Agregação eficiente em uma única consulta ORM
        produtos = (
            Produto.objects.filter(empresa=empresa, ativo=True)
            .annotate(
                total_vendido_60d=Coalesce(
                    Sum(
                        'itens_venda__quantidade',
                        filter=Q(
                            itens_venda__venda__data_venda__gte=data_limite,
                            itens_venda__venda__status='CONCLUIDA'
                        )
                    ),
                    Decimal('0.000')
                )
            )
            .order_by('-total_vendido_60d', 'nome')
        )

        grupos_dict = defaultdict(list)
        for prod in produtos:
            letra = SaleService.normalizar_primeira_letra(prod.nome)
            if len(grupos_dict[letra]) < 4:
                grupos_dict[letra].append(prod)

        def chave_ordenacao(letra):
            if letra.isalpha():
                return (0, letra)
            if letra == '0-9':
                return (1, letra)
            return (2, letra)

        grupos_ordenados = [
            {'letra': letra, 'produtos': grupos_dict[letra]}
            for letra in sorted(grupos_dict.keys(), key=chave_ordenacao)
        ]
        return grupos_ordenados
