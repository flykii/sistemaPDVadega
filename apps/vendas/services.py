from decimal import Decimal
import uuid
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Venda, ItemVenda, PagamentoVenda
from apps.produtos.models import Produto
from apps.produtos.services import StockService
from apps.financeiro.models import ContaReceber, FluxoCaixa
from apps.clientes.models import Cliente
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
        observacao: str = ''
    ) -> Venda:
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
                observacao=observacao
            )
        except IntegrityError as e:
            # 3. Tratamento seguro de colisão de concorrência:
            # Se a colisão ocorreu pelo constraint de offline_uuid, a transação interna já fez rollback completo.
            # Consultamos fora do bloco quebrado e retornamos a venda vencedora.
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
        observacao: str = ''
    ) -> Venda:
        """
        Processamento transacional atômico da venda (Venda, Itens, Estoque, Pagamentos, Caixa).
        Qualquer exceção causa Rollback Total automático no banco de dados.
        """
        if not itens_data:
            raise ValueError("Uma venda precisa ter ao menos um item.")

        if not pagamentos_data:
            raise ValueError("Informe ao menos uma forma de pagamento para a venda.")

        if sessao_caixa and sessao_caixa.status != 'ABERTA':
            raise ValueError("Não é possível realizar vendas em um caixa fechado.")

        # 1. Validação de itens, quantidade e estoque com lock de linha (select_for_update)
        subtotal = Decimal('0.00')
        itens_para_criar = []

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
            if preco_venda_unit < Decimal('0.00'):
                raise ValueError(f"Preço de venda inválido para '{produto.nome}'.")

            subtotal_item = (quant * preco_venda_unit).quantize(Decimal('0.01'))
            subtotal += subtotal_item

            itens_para_criar.append({
                'produto': produto,
                'quantidade': quant,
                'preco_custo_unitario': produto.preco_custo,
                'preco_venda_unitario': preco_venda_unit,
                'subtotal': subtotal_item,
            })

        # 2. Validação estrita de desconto e total da venda
        desconto_dec = Decimal(str(desconto)).quantize(Decimal('0.01'))
        if desconto_dec < Decimal('0.00'):
            raise ValueError("O valor de desconto não pode ser negativo.")

        if desconto_dec > subtotal:
            raise ValueError(f"O desconto (R$ {desconto_dec:.2f}) não pode ser maior que o subtotal da venda (R$ {subtotal:.2f}).")

        total_venda = (subtotal - desconto_dec).quantize(Decimal('0.01'))

        # 3. Validação estrita de pagamentos e troco
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

            if forma == 'DINHEIRO' and troco_pago >= val_pago and total_venda > 0:
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

        # Validação do total pago vs total da venda
        if total_liquido_pago < total_venda:
            faltante = total_venda - total_liquido_pago
            raise ValueError(f"Pagamento insuficiente. Total da venda: R$ {total_venda:.2f}, Total pago: R$ {total_liquido_pago:.2f}. Faltam R$ {faltante:.2f}.")

        if total_liquido_pago > total_venda:
            excedente = total_liquido_pago - total_venda
            raise ValueError(f"O total líquido pago (R$ {total_liquido_pago:.2f}) excede o total da venda (R$ {total_venda:.2f}) em R$ {excedente:.2f}.")

        # 4. Criação da Venda
        codigo_venda = f"VD-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        venda = Venda.objects.create(
            empresa=empresa,
            sessao_caixa=sessao_caixa,
            cliente=cliente,
            operador=operador,
            codigo_venda=codigo_venda,
            subtotal=subtotal,
            desconto=desconto_dec,
            total=total_venda,
            status='CONCLUIDA',
            offline_uuid=offline_uuid,
            observacao=observacao
        )

        # 5. Cria Itens e Atualiza Estoque com MovimentacaoEstoque
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

            # Baixa no estoque rastreada
            StockService.remove_stock(
                produto=item['produto'],
                quantidade=item['quantidade'],
                motivo=f"Venda #{venda.codigo_venda}",
                origem_ref=venda.codigo_venda
            )

        # 6. Registra Pagamentos
        for pag in pagamentos_validados:
            forma = pag['forma']
            val_pago = pag['valor']
            troco_pago = pag['troco']
            valor_efetivo = pag['valor_efetivo']

            PagamentoVenda.objects.create(
                empresa=empresa,
                venda=venda,
                forma_pagamento=forma,
                valor=val_pago,
                troco=troco_pago,
                dados_transacao=pag['dados']
            )

            # Lançamento no Fluxo de Caixa se não for fiado
            if forma != 'CREDIARIO':
                FluxoCaixa.objects.create(
                    empresa=empresa,
                    tipo='ENTRADA',
                    categoria='Venda PDV',
                    descricao=f"Venda #{venda.codigo_venda} ({forma})",
                    valor=valor_efetivo,
                    referencia_origem=venda.codigo_venda
                )
            else:
                # Se for CREDIARIO / Fiado, gera Conta a Receber e ajusta saldo do cliente
                if not cliente:
                    raise ValueError("Vendas em Crediário/Fiado exigem a seleção de um Cliente cadastrado.")
                
                # Bloqueio transacional de concorrência do Cliente
                cliente_db = Cliente.objects.select_for_update().get(id=cliente.id, empresa=empresa)

                if not cliente_db.ativo:
                    raise ValueError(f"O cliente '{cliente_db.nome}' está inativo e não pode realizar compras no crediário.")

                disponivel = cliente_db.credito_disponivel
                if cliente_db.limite_credito > Decimal('0.00') and (cliente_db.saldo_devedor + valor_efetivo) > cliente_db.limite_credito:
                    raise ValueError(
                        f"Limite de crédito insuficiente para '{cliente_db.nome}'. "
                        f"Limite: R$ {cliente_db.limite_credito:.2f}, Saldo Devedor Atual: R$ {cliente_db.saldo_devedor:.2f}, Crédito Disponível: R$ {disponivel:.2f}."
                    )

                conta_rec = ContaReceber.objects.create(
                    empresa=empresa,
                    venda=venda,
                    cliente=cliente_db,
                    descricao=f"Crediário Venda #{venda.codigo_venda}",
                    valor=valor_efetivo,
                    valor_original=valor_efetivo,
                    valor_pago=Decimal('0.00'),
                    data_vencimento=timezone.now().date() + timezone.timedelta(days=30),
                    status='ABERTA'
                )

                cliente_db.saldo_devedor += valor_efetivo
                cliente_db.save()

                # Auditoria de Crediário Concedido
                AuditService.registrar(
                    empresa=empresa,
                    usuario=operador,
                    acao='CREDIARIO_CONCEDIDO',
                    entidade='ContaReceber',
                    entidade_id=conta_rec.id,
                    descricao=f"Crediário de R$ {valor_efetivo:.2f} concedido para '{cliente_db.nome}' na venda #{venda.codigo_venda}",
                    dados_posteriores={
                        'cliente': cliente_db.nome,
                        'valor': str(valor_efetivo),
                        'saldo_devedor_atual': str(cliente_db.saldo_devedor),
                        'limite_credito': str(cliente_db.limite_credito)
                    }
                )

        # Auditoria da Venda Criada
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

        return venda


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
