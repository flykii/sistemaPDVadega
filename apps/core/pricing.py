from decimal import Decimal, ROUND_HALF_UP

def calculate_sale_price(cost_price: Decimal | float, margin_percent: Decimal | float) -> Decimal:
    """
    Calcula o preço de venda com base na margem bruta desejada sobre o preço de venda.
    Fórmula do usuário: Preço de Venda = Custo / (1 - (Margem / 100))
    Exemplo: Custo = 2.00, Margem = 30% -> 2.00 / (1 - 0.30) = 2.00 / 0.70 = 2.8571... -> 2.85 (ou arredondado)
    """
    cost = Decimal(str(cost_price))
    margin = Decimal(str(margin_percent))
    
    if margin >= Decimal('100'):
        raise ValueError("A margem de lucro não pode ser igual ou superior a 100%.")
    if margin <= Decimal('0'):
        return cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    factor = Decimal('1') - (margin / Decimal('100'))
    sale_price = cost / factor
    return sale_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def calculate_margin_percent(cost_price: Decimal | float, sale_price: Decimal | float) -> Decimal:
    """
    Calcula a margem percentual com base no preço de custo e no preço de venda.
    Margem % = ((Preço Venda - Custo) / Preço Venda) * 100
    Exemplo: Venda = 2.85, Custo = 2.00 -> Lucro = 0.85 -> (0.85 / 2.85) * 100 = 29.82% (~30%)
    """
    cost = Decimal(str(cost_price))
    sale = Decimal(str(sale_price))
    
    if sale <= Decimal('0'):
        return Decimal('0.00')

    margin = ((sale - cost) / sale) * Decimal('100')
    return margin.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def calculate_profit_amount(cost_price: Decimal | float, sale_price: Decimal | float) -> Decimal:
    """
    Calcula o lucro bruto em moeda (Lucro Real).
    Lucro Real = Preço de Venda - Preço de Custo
    Exemplo: 2.85 - 2.00 = 0.85
    """
    cost = Decimal(str(cost_price))
    sale = Decimal(str(sale_price))
    return (sale - cost).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
