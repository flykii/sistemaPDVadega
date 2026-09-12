from decimal import Decimal
from datetime import date, timedelta
from django.db import transaction
from django.utils import timezone
from .models import Compra, ItemCompra, RecebimentoCompra, ItemRecebimentoCompra
from apps.produtos.models import Produto
from apps.produtos.services import StockService
from apps.financeiro.models import ContaPagar
from apps.core.models import AuditService

class PurchaseService:
    @staticmethod
    @transaction.atomic
    def criar_pedido_compra(
        empresa,
        fornecedor,
        numero_nota: str,
        itens_data: list,
        data_vencimento = None,
        observacoes: str = '',
        usuario = None
    ) -> Compra:
        """
        MOMENTO 1: Cria o Pedido de Compra com status 'PENDENTE'.
        - Registra os itens e quantidades pedidas com quantidade_recebida = 0.
        - Gera a Conta a Pagar com a data de vencimento informada.
        - NÃO altera o estoque atual dos produtos.
        - NÃO gera movimentação de estoque.
        - NÃO altera o preço de custo do produto.
        """
        if not itens_data:
            raise ValueError("Uma compra precisa ter ao menos um item.")

        dt_venc = data_vencimento
        if not dt_venc:
            prazo_dias = fornecedor.dias_prazo_calculados if fornecedor else 0
            dt_venc = timezone.now().date() + timedelta(days=prazo_dias)
        elif isinstance(dt_venc, str):
            try:
                dt_venc = date.fromisoformat(dt_venc.strip())
            except ValueError:
                prazo_dias = fornecedor.dias_prazo_calculados if fornecedor else 0
                dt_venc = timezone.now().date() + timedelta(days=prazo_dias)

        compra = Compra.objects.create(
            empresa=empresa,
            fornecedor=fornecedor,
            numero_nota=numero_nota.strip(),
            status='PENDENTE',
            observacoes=observacoes.strip()
        )

        total_compra = Decimal('0.00')

        for item in itens_data:
            prod_id = item['produto_id']
            quant = Decimal(str(item['quantidade'])).quantize(Decimal('0.001'))
            custo_unit = Decimal(str(item['preco_custo_unitario'])).quantize(Decimal('0.01'))

            if quant <= Decimal('0.000'):
                raise ValueError("A quantidade de cada item na compra deve ser maior que zero.")

            if custo_unit < Decimal('0.00'):
                raise ValueError("O custo unitário não pode ser negativo.")

            try:
                produto = Produto.objects.select_for_update().get(id=prod_id, empresa=empresa)
            except Produto.DoesNotExist:
                raise ValueError(f"Produto ID {prod_id} não encontrado nesta empresa.")

            subtotal_item = (quant * custo_unit).quantize(Decimal('0.01'))
            total_compra += subtotal_item

            ItemCompra.objects.create(
                empresa=empresa,
                compra=compra,
                produto=produto,
                quantidade=quant,
                quantidade_recebida=Decimal('0.000'),
                preco_custo_unitario=custo_unit,
                subtotal=subtotal_item
            )

        compra.total = total_compra
        compra.save()

        # Gera Conta a Pagar automaticamente no Financeiro com vencimento real
        fornec_desc = fornecedor.nome_fantasia if fornecedor else 'Fornecedor Avulso'
        ContaPagar.objects.create(
            empresa=empresa,
            compra=compra,
            fornecedor=fornecedor,
            descricao=f"Compra NF #{numero_nota or compra.id} - {fornec_desc}",
            valor=total_compra,
            valor_original=total_compra,
            valor_pago=Decimal('0.00'),
            data_competencia=timezone.now().date(),
            data_vencimento=dt_venc,
            status='ABERTA',
            usuario=usuario,
            observacoes=f"Gerado automaticamente pelo Pedido de Compra #{compra.id}."
        )

        AuditService.registrar(
            empresa=empresa,
            usuario=usuario,
            acao='PEDIDO_COMPRA_CRIADO',
            entidade='Compra',
            entidade_id=compra.id,
            descricao=f"Pedido de Compra #{compra.id} criado com {len(itens_data)} itens. Total: R$ {total_compra:.2f}. Vencimento: {dt_venc.strftime('%d/%m/%Y')}",
            dados_posteriores={
                'compra_id': compra.id,
                'total': str(total_compra),
                'status': compra.status,
                'data_vencimento': str(dt_venc)
            }
        )

        return compra

    @staticmethod
    def processar_compra(empresa, fornecedor, numero_nota: str, itens_data: list, data_vencimento = None, observacoes: str = '', usuario = None) -> Compra:
        """Alias para compatibilidade retroativa."""
        return PurchaseService.criar_pedido_compra(
            empresa=empresa,
            fornecedor=fornecedor,
            numero_nota=numero_nota,
            itens_data=itens_data,
            data_vencimento=data_vencimento,
            observacoes=observacoes,
            usuario=usuario
        )

    @staticmethod
    @transaction.atomic
    def registrar_recebimento(
        compra: Compra,
        itens_recebidos: list,
        encerrar_compra: bool = False,
        observacao: str = '',
        usuario = None
    ) -> RecebimentoCompra:
        """
        MOMENTO 2: Recebimento e Conferência Física da Mercadoria.
        - Dá entrada no estoque estritamente para as quantidades informadas no recebimento.
        - Atualiza a quantidade_recebida em cada ItemCompra.
        - Atualiza o preco_custo do produto e fornecedor principal.
        - Registra histórico detalhado da remessa em RecebimentoCompra.
        - Atualiza o status da Compra para 'PARCIAL' ou 'CONCLUIDA'.
        """
        compra_db = Compra.objects.select_for_update().get(id=compra.id)

        if compra_db.status == 'CANCELADA':
            raise ValueError("Não é possível receber mercadorias de uma compra cancelada.")

        if compra_db.status == 'CONCLUIDA':
            raise ValueError("Esta compra já se encontra concluída / encerrada.")

        if not itens_recebidos:
            raise ValueError("Informe ao menos um item com quantidade recebida maior que zero.")

        # Valida se há pelo menos um item com quantidade > 0
        tem_quantidade = False
        for item_data in itens_recebidos:
            q_rec = Decimal(str(item_data.get('quantidade_recebida', 0))).quantize(Decimal('0.001'))
            if q_rec > Decimal('0.000'):
                tem_quantidade = True
                break

        if not tem_quantidade:
            raise ValueError("Ao menos um produto deve ter quantidade recebida maior que zero.")

        recebimento = RecebimentoCompra.objects.create(
            empresa=compra_db.empresa,
            compra=compra_db,
            usuario=usuario,
            data_recebimento=timezone.now(),
            observacao=observacao.strip()
        )

        for item_data in itens_recebidos:
            item_id = item_data['item_compra_id']
            q_rec = Decimal(str(item_data.get('quantidade_recebida', 0))).quantize(Decimal('0.001'))

            if q_rec <= Decimal('0.000'):
                continue

            try:
                item_db = ItemCompra.objects.select_for_update().get(id=item_id, compra=compra_db)
            except ItemCompra.DoesNotExist:
                raise ValueError(f"Item #{item_id} não pertence à Compra #{compra_db.id}.")

            produto_db = Produto.objects.select_for_update().get(id=item_db.produto_id)

            custo_praticado = item_data.get('preco_custo')
            if custo_praticado is not None and str(custo_praticado).strip() != '':
                custo_unit = Decimal(str(custo_praticado)).quantize(Decimal('0.01'))
            else:
                custo_unit = item_db.preco_custo_unitario

            # Atualiza o item de compra
            item_db.quantidade_recebida += q_rec
            item_db.save()

            # Cria o registro do item desta remessa
            ItemRecebimentoCompra.objects.create(
                empresa=compra_db.empresa,
                recebimento=recebimento,
                item_compra=item_db,
                produto=produto_db,
                quantidade_recebida=q_rec,
                preco_custo=custo_unit
            )

            # Entrada física no estoque com rastreabilidade
            motivo_log = f"Recebimento Compra #{compra_db.id}"
            if compra_db.numero_nota:
                motivo_log += f" (NF {compra_db.numero_nota})"
            
            StockService.add_stock(
                produto=produto_db,
                quantidade=q_rec,
                motivo=motivo_log,
                preco_custo=custo_unit,
                origem_ref=f"Compra #{compra_db.id} (Rec #{recebimento.id})",
                usuario=usuario
            )

            # Vincula fornecedor principal se ainda não tiver
            if compra_db.fornecedor and not produto_db.fornecedor_principal_id:
                Produto.objects.filter(id=produto_db.id, fornecedor_principal__isnull=True).update(fornecedor_principal=compra_db.fornecedor)

        # Atualiza status da compra
        compra_db.refresh_from_db()
        if encerrar_compra or compra_db.is_totalmente_recebida:
            compra_db.status = 'CONCLUIDA'
        else:
            compra_db.status = 'PARCIAL'
        compra_db.save()

        AuditService.registrar(
            empresa=compra_db.empresa,
            usuario=usuario,
            acao='MERCADORIA_RECEBIDA',
            entidade='Compra',
            entidade_id=compra_db.id,
            descricao=f"Recebimento #{recebimento.id} registrado para a Compra #{compra_db.id}. Status atual da compra: {compra_db.get_status_display()}.",
            dados_posteriores={
                'recebimento_id': recebimento.id,
                'status_compra': compra_db.status,
                'total_recebido': str(compra_db.total_itens_recebidos),
                'total_pendente': str(compra_db.total_itens_pendentes),
                'encerrada_manualmente': encerrar_compra
            }
        )

        return recebimento

    @staticmethod
    @transaction.atomic
    def cancelar_compra(compra: Compra, usuario = None, motivo: str = '') -> Compra:
        """
        Cancela uma compra:
        - Se ainda não houve recebimentos: cancela compra e conta a pagar sem mexer em estoque.
        - Se já houve recebimento parcial/total: estorna do estoque a quantidade já recebida.
        - Bloqueia cancelamento se a Conta a Pagar já estiver quitada ou amortizada.
        """
        compra_db = Compra.objects.select_for_update().get(id=compra.id)

        if compra_db.status == 'CANCELADA':
            raise ValueError("Esta compra já se encontra cancelada.")

        # Verifica se alguma conta a pagar vinculada já possui pagamentos
        contas_pagas = ContaPagar.objects.filter(compra=compra_db).filter(
            status__in=['PAGA', 'PAGO']
        ).exists() or ContaPagar.objects.filter(compra=compra_db, valor_pago__gt=Decimal('0.00')).exists()

        if contas_pagas:
            raise ValueError("Não é possível cancelar uma compra cuja conta a pagar já foi quitada ou amortizada. Cancele ou estorne o pagamento primeiro no financeiro.")

        # Estorna estoque para cada item que teve quantidade recebida
        for item in compra_db.itens.all():
            if item.quantidade_recebida > Decimal('0.000'):
                StockService.remove_stock(
                    produto=item.produto,
                    quantidade=item.quantidade_recebida,
                    motivo=f"Estorno por Cancelamento da Compra #{compra_db.id}",
                    origem_ref=f"Cancelamento Compra #{compra_db.id}",
                    usuario=usuario
                )

        # Cancela as contas a pagar vinculadas
        ContaPagar.objects.filter(compra=compra_db, valor_pago=Decimal('0.00')).update(status='CANCELADA')

        compra_db.status = 'CANCELADA'
        if motivo:
            compra_db.observacoes = f"{compra_db.observacoes}\n[Cancelamento em {timezone.now().strftime('%d/%m/%Y %H:%M')} por {usuario.username if usuario else 'Sistema'}]: {motivo}".strip()
        compra_db.save()

        AuditService.registrar(
            empresa=compra_db.empresa,
            usuario=usuario,
            acao='COMPRA_CANCELADA',
            entidade='Compra',
            entidade_id=compra_db.id,
            descricao=f"Compra #{compra_db.id} cancelada. Motivo: {motivo}",
            motivo=motivo,
            dados_posteriores={'status': 'CANCELADA'}
        )

        return compra_db
