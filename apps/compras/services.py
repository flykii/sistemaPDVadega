from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Compra, ItemCompra
from apps.produtos.models import Produto
from apps.produtos.services import StockService
from apps.financeiro.models import ContaPagar

class PurchaseService:
    @staticmethod
    @transaction.atomic
    def processar_compra(empresa, fornecedor, numero_nota: str, itens_data: list, observacoes: str = '', usuario=None) -> Compra:
        if not itens_data:
            raise ValueError("Uma compra precisa ter ao menos um item.")

        compra = Compra.objects.create(
            empresa=empresa,
            fornecedor=fornecedor,
            numero_nota=numero_nota.strip(),
            status='CONCLUIDA',
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
                preco_custo_unitario=custo_unit,
                subtotal=subtotal_item
            )

            # Dá entrada rastreada no estoque e atualiza preço de custo
            StockService.add_stock(
                produto=produto,
                quantidade=quant,
                motivo=f"Entrada Compra NF #{numero_nota or compra.id}",
                preco_custo=custo_unit,
                origem_ref=f"Compra #{compra.id}",
                usuario=usuario
            )

            # Atualiza fornecedor principal do produto se ainda não tiver
            if fornecedor and not produto.fornecedor_principal_id:
                Produto.objects.filter(id=produto.id, fornecedor_principal__isnull=True).update(fornecedor_principal=fornecedor)

        compra.total = total_compra
        compra.save()

        # Gera Conta a Pagar automaticamente no Financeiro
        ContaPagar.objects.create(
            empresa=empresa,
            compra=compra,
            fornecedor=fornecedor,
            descricao=f"Compra NF #{numero_nota or compra.id}",
            valor=total_compra,
            data_vencimento=timezone.now().date() + timezone.timedelta(days=30),
            status='PENDENTE'
        )

        return compra
