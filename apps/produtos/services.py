from decimal import Decimal
from django.db import transaction
from .models import Produto, MovimentacaoEstoque

class StockService:
    @staticmethod
    @transaction.atomic
    def add_stock(produto: Produto, quantidade: Decimal | float, motivo: str, preco_custo: Decimal | float = None, origem_ref: str = '', usuario=None) -> MovimentacaoEstoque:
        quant = Decimal(str(quantidade)).quantize(Decimal('0.001'))
        if quant <= Decimal('0.000'):
            raise ValueError("A quantidade de entrada no estoque deve ser estritamente maior que zero.")

        # Bloqueio transacional de linha
        prod = Produto.objects.select_for_update().get(id=produto.id)
        estoque_anterior = prod.estoque_atual
        prod.estoque_atual += quant
        estoque_posterior = prod.estoque_atual

        if preco_custo is not None:
            custo = Decimal(str(preco_custo)).quantize(Decimal('0.01'))
            if custo > Decimal('0.00'):
                prod.preco_custo = custo

        prod.save()

        mov = MovimentacaoEstoque.objects.create(
            empresa=prod.empresa,
            produto=prod,
            tipo='ENTRADA',
            quantidade=quant,
            estoque_anterior=estoque_anterior,
            estoque_posterior=estoque_posterior,
            preco_custo_unitario=prod.preco_custo,
            motivo=motivo,
            usuario=usuario,
            origem_ref=origem_ref
        )
        return mov

    @staticmethod
    @transaction.atomic
    def remove_stock(produto: Produto, quantidade: Decimal | float, motivo: str, origem_ref: str = '', usuario=None) -> MovimentacaoEstoque:
        quant = Decimal(str(quantidade)).quantize(Decimal('0.001'))
        if quant <= Decimal('0.000'):
            raise ValueError("A quantidade de saída do estoque deve ser estritamente maior que zero.")

        # Bloqueio transacional de linha
        prod = Produto.objects.select_for_update().get(id=produto.id)
        
        if prod.controle_estoque and prod.estoque_atual < quant:
            raise ValueError(f"Estoque insuficiente para '{prod.nome}'. Estoque atual: {prod.estoque_atual}, Solicitado: {quant}")

        estoque_anterior = prod.estoque_atual
        prod.estoque_atual -= quant
        estoque_posterior = prod.estoque_atual
        prod.save()

        mov = MovimentacaoEstoque.objects.create(
            empresa=prod.empresa,
            produto=prod,
            tipo='SAIDA',
            quantidade=quant,
            estoque_anterior=estoque_anterior,
            estoque_posterior=estoque_posterior,
            preco_custo_unitario=prod.preco_custo,
            motivo=motivo,
            usuario=usuario,
            origem_ref=origem_ref
        )
        return mov

    @staticmethod
    @transaction.atomic
    def adjust_stock(produto: Produto, novo_estoque: Decimal | float, motivo: str, usuario=None, origem_ref: str = '') -> MovimentacaoEstoque:
        quant_nova = Decimal(str(novo_estoque)).quantize(Decimal('0.001'))
        if quant_nova < Decimal('0.000'):
            raise ValueError("O novo saldo de estoque não pode ser negativo.")

        # Bloqueio transacional de linha
        prod = Produto.objects.select_for_update().get(id=produto.id)
        estoque_anterior = prod.estoque_atual
        delta = quant_nova - estoque_anterior
        
        prod.estoque_atual = quant_nova
        estoque_posterior = prod.estoque_atual
        prod.save()

        mov = MovimentacaoEstoque.objects.create(
            empresa=prod.empresa,
            produto=prod,
            tipo='AJUSTE',
            quantidade=abs(delta),
            estoque_anterior=estoque_anterior,
            estoque_posterior=estoque_posterior,
            preco_custo_unitario=prod.preco_custo,
            motivo=motivo or f"Ajuste Manual ({'+' if delta >= 0 else ''}{delta})",
            usuario=usuario,
            origem_ref=origem_ref
        )
        return mov
