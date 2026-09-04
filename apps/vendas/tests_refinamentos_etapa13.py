from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.financeiro.models import ContaReceber, FluxoCaixa
from apps.vendas.services import SaleService
from apps.caixas.services import CashService
from apps.financeiro.services import FinancialService
from apps.relatorios.services import ReportService
from apps.core.operational_day import (
    get_operational_date, get_operational_today, get_operational_datetime_range
)


class OperationalDayRefinementTests(TestCase):
    """Testes rigorosos para a virada operacional às 02:00 da manhã."""

    def test_operational_date_cutoff_before_and_after_02am(self):
        # 1. 01:59:00 do dia 10/05/2026 -> Pertence ao dia operacional 09/05/2026
        dt_1 = datetime(2026, 5, 10, 1, 59, 0)
        self.assertEqual(get_operational_date(dt_1), date(2026, 5, 9))

        # 2. 01:59:59 do dia 10/05/2026 -> Pertence ao dia operacional 09/05/2026
        dt_2 = datetime(2026, 5, 10, 1, 59, 59, 999999)
        self.assertEqual(get_operational_date(dt_2), date(2026, 5, 9))

        # 3. 02:00:00 do dia 10/05/2026 -> Inicia o dia operacional 10/05/2026
        dt_3 = datetime(2026, 5, 10, 2, 0, 0)
        self.assertEqual(get_operational_date(dt_3), date(2026, 5, 10))

        # 4. 02:00:01 do dia 10/05/2026 -> Pertence ao dia operacional 10/05/2026
        dt_4 = datetime(2026, 5, 10, 2, 0, 1)
        self.assertEqual(get_operational_date(dt_4), date(2026, 5, 10))

        # 5. 15:30:00 do dia 10/05/2026 -> Pertence ao dia operacional 10/05/2026
        dt_5 = datetime(2026, 5, 10, 15, 30, 0)
        self.assertEqual(get_operational_date(dt_5), date(2026, 5, 10))

    def test_operational_datetime_range(self):
        d_ini = date(2026, 6, 1)
        d_fim = date(2026, 6, 1)
        start_dt, end_dt = get_operational_datetime_range(d_ini, d_fim)

        # Início no dia 01/06 às 02:00:00
        self.assertEqual(start_dt.date(), date(2026, 6, 1))
        self.assertEqual(start_dt.time(), time(2, 0, 0))

        # Fim no dia 02/06 às 01:59:59
        self.assertEqual(end_dt.date(), date(2026, 6, 2))
        self.assertEqual(end_dt.hour, 1)
        self.assertEqual(end_dt.minute, 59)
        self.assertEqual(end_dt.second, 59)

    def test_report_service_groups_sales_by_operational_day(self):
        empresa = Empresa.objects.create(razao_social="Empresa Teste", nome_fantasia="Empresa Teste", cnpj="12345678000100")
        operador = Usuario.objects.create_user(username="op1", empresa=empresa, cargo='OPERADOR')
        caixa = Caixa.objects.create(empresa=empresa, nome="Caixa 1", codigo_identificador="CX01")
        sessao = CashService.abrir_caixa(caixa, operador, Decimal('100.00'))
        produto = Produto.objects.create(empresa=empresa, nome="Prod A", preco_custo=Decimal('5.00'), preco_venda=Decimal('10.00'), estoque_atual=Decimal('100.00'))

        # Venda 1: Feita em 10/05/2026 às 01:30 (pertence ao dia operacional 09/05/2026)
        venda_1 = SaleService.processar_venda(
            empresa=empresa,
            operador=operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': produto.id, 'quantidade': 1, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 10.00, 'troco': 0.00}],
            offline_uuid='UUID-V1'
        )
        tz = timezone.get_current_timezone() if timezone.is_aware(timezone.now()) else None
        dt_v1 = datetime(2026, 5, 10, 1, 30, 0)
        if tz:
            dt_v1 = timezone.make_aware(dt_v1, tz)
        Venda.objects.filter(id=venda_1.id).update(data_venda=dt_v1)

        # Venda 2: Feita em 10/05/2026 às 14:00 (pertence ao dia operacional 10/05/2026)
        venda_2 = SaleService.processar_venda(
            empresa=empresa,
            operador=operador,
            sessao_caixa=sessao,
            itens_data=[{'produto_id': produto.id, 'quantidade': 2, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 20.00, 'troco': 0.00}],
            offline_uuid='UUID-V2'
        )
        dt_v2 = datetime(2026, 5, 10, 14, 0, 0)
        if tz:
            dt_v2 = timezone.make_aware(dt_v2, tz)
        Venda.objects.filter(id=venda_2.id).update(data_venda=dt_v2)

        # Relatório do dia operacional 09/05/2026 (das 09/05 02:00 até 10/05 01:59:59)
        start_09, end_09 = get_operational_datetime_range(date(2026, 5, 9), date(2026, 5, 9))
        rep_09 = ReportService.get_vendas_report(empresa, start_09, end_09)
        self.assertEqual(rep_09['qtd_vendas'], 1)
        self.assertEqual(rep_09['faturamento_liquido'], Decimal('10.00'))

        # Relatório do dia operacional 10/05/2026 (das 10/05 02:00 até 11/05 01:59:59)
        start_10, end_10 = get_operational_datetime_range(date(2026, 5, 10), date(2026, 5, 10))
        rep_10 = ReportService.get_vendas_report(empresa, start_10, end_10)
        self.assertEqual(rep_10['qtd_vendas'], 1)
        self.assertEqual(rep_10['faturamento_liquido'], Decimal('20.00'))


class MultiPaymentAndDebtRefinementTests(TestCase):
    """Testes para Múltiplas Formas de Pagamento e Recebimento de Dívidas."""

    def setUp(self):
        self.empresa = Empresa.objects.create(razao_social="Empresa Refino", nome_fantasia="Empresa Refino", cnpj="98765432000199")
        self.operador = Usuario.objects.create_user(username="operador_refino", empresa=self.empresa, cargo='OPERADOR')
        self.caixa = Caixa.objects.create(empresa=self.empresa, nome="Caixa Principal 01", codigo_identificador="CX01")
        self.sessao = CashService.abrir_caixa(self.caixa, self.operador, Decimal('200.00'))
        self.produto = Produto.objects.create(
            empresa=self.empresa,
            nome="Notebook Top",
            preco_custo=Decimal('100.00'),
            preco_venda=Decimal('150.00'),
            estoque_atual=Decimal('10.00')
        )
        self.cliente = Cliente.objects.create(
            empresa=self.empresa,
            nome="Carlos Silva",
            limite_credito=Decimal('500.00'),
            saldo_devedor=Decimal('0.00')
        )

    def test_multi_payment_sale_processes_all_distinct_methods(self):
        # Venda de 2 unidades = R$ 300,00
        # Pagamento: Dinheiro 100 + PIX 100 + Crédito 100
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto.id, 'quantidade': 2, 'preco_venda': 150.00}],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 0.00},
                {'forma': 'PIX', 'valor': 100.00, 'troco': 0.00},
                {'forma': 'CARTAO_CREDITO', 'valor': 100.00, 'troco': 0.00}
            ],
            cliente=self.cliente,
            offline_uuid='UUID-MULTI-PAY-1'
        )

        self.assertEqual(venda.total, Decimal('300.00'))
        pags = list(venda.pagamentos.all().order_by('id'))
        self.assertEqual(len(pags), 3)

        self.assertEqual(pags[0].forma_pagamento, 'DINHEIRO')
        self.assertEqual(pags[0].valor, Decimal('100.00'))

        self.assertEqual(pags[1].forma_pagamento, 'PIX')
        self.assertEqual(pags[1].valor, Decimal('100.00'))

        self.assertEqual(pags[2].forma_pagamento, 'CARTAO_CREDITO')
        self.assertEqual(pags[2].valor, Decimal('100.00'))

        # Caixa Físico: Apenas a parte em DINHEIRO afeta a gaveta física (saldo inicial 200 + 100 = 300)
        self.assertEqual(self.sessao.total_vendas_dinheiro, Decimal('100.00'))
        self.assertEqual(self.sessao.total_vendas_pix, Decimal('100.00'))
        self.assertEqual(self.sessao.total_vendas_credito, Decimal('100.00'))
        self.assertEqual(self.sessao.saldo_esperado, Decimal('300.00'))

    def test_multi_payment_with_cash_and_troco(self):
        # Venda de R$ 150,00
        # Pagamento: PIX 50 + Dinheiro 120 (com 20 de troco -> efetivo 100) = Total 150
        venda = SaleService.processar_venda(
            empresa=self.empresa,
            operador=self.operador,
            sessao_caixa=self.sessao,
            itens_data=[{'produto_id': self.produto.id, 'quantidade': 1, 'preco_venda': 150.00}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': 50.00, 'troco': 0.00},
                {'forma': 'DINHEIRO', 'valor': 120.00, 'troco': 20.00}
            ],
            offline_uuid='UUID-MULTI-TROCO-1'
        )

        self.assertEqual(venda.total, Decimal('150.00'))
        # Gaveta: 200 inicial + 100 líquido em dinheiro = 300
        self.assertEqual(self.sessao.total_vendas_dinheiro, Decimal('100.00'))
        self.assertEqual(self.sessao.saldo_esperado, Decimal('300.00'))

    def test_debt_receipt_partial_and_full_without_creating_sale(self):
        # 1. Cria uma conta a receber prévia para o cliente
        conta = ContaReceber.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            descricao="Fiado Mercearia",
            valor_original=Decimal('200.00'),
            valor=Decimal('200.00'),
            data_vencimento=date.today() + timedelta(days=15),
            status='PENDENTE'
        )
        self.cliente.saldo_devedor = Decimal('200.00')
        self.cliente.save()

        vendas_antes = Venda.objects.count()

        # 2. Recebimento parcial de R$ 50,00 via PIX (não deve aumentar gaveta física)
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('50.00'),
            forma_pagamento='PIX',
            sessao_caixa=self.sessao,
            usuario=self.operador
        )

        conta.refresh_from_db()
        self.cliente.refresh_from_db()
        self.assertEqual(conta.valor_pago, Decimal('50.00'))
        self.assertEqual(conta.saldo, Decimal('150.00'))
        self.assertEqual(conta.status, 'PARCIAL')
        self.assertEqual(self.cliente.saldo_devedor, Decimal('150.00'))
        self.assertEqual(self.sessao.saldo_esperado, Decimal('200.00'))  # PIX não alterou gaveta física

        # 3. Quitação restante de R$ 150,00 em DINHEIRO (deve aumentar gaveta física)
        FinancialService.receber_pagamento_conta(
            conta=conta,
            valor_pago=Decimal('150.00'),
            forma_pagamento='DINHEIRO',
            sessao_caixa=self.sessao,
            usuario=self.operador
        )

        conta.refresh_from_db()
        self.cliente.refresh_from_db()
        self.assertEqual(conta.saldo, Decimal('0.00'))
        self.assertEqual(conta.status, 'QUITADA')
        self.assertEqual(self.cliente.saldo_devedor, Decimal('0.00'))
        # Gaveta física aumentou em 150 via SUPRIMENTO de quitação
        self.assertEqual(self.sessao.saldo_esperado, Decimal('350.00'))

        # Garantir que nenhuma Venda espúria foi criada
        self.assertEqual(Venda.objects.count(), vendas_antes)
