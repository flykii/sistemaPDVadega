from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.clientes.models import Cliente
from apps.financeiro.models import ContaPagar, ContaReceber, CategoriaDespesa
from apps.financeiro.services import FinancialService
from apps.relatorios.services import ReportService

class RelatoriosGerenciaisTestCase(TestCase):
    def setUp(self):
        # Empresas
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Alpha LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="11222333000100"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="44555666000100"
        )

        # Operadores
        self.operador_1 = Usuario.objects.create_user(
            username="operador1",
            first_name="Carlos",
            last_name="Silva",
            email="op1@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )
        self.operador_2 = Usuario.objects.create_user(
            username="operador2",
            first_name="Ana",
            last_name="Souza",
            email="op2@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )

        # Caixas e Sessões
        self.caixa_1 = Caixa.objects.create(empresa=self.empresa_a, nome="Caixa Balcão", codigo_identificador="CX-01")
        self.caixa_2 = Caixa.objects.create(empresa=self.empresa_a, nome="Caixa Drive", codigo_identificador="CX-02")
        self.sessao_1 = CashService.abrir_caixa(self.caixa_1, self.operador_1, Decimal('200.00'))
        self.sessao_2 = CashService.abrir_caixa(self.caixa_2, self.operador_2, Decimal('300.00'))

        # Categorias
        self.cat_vinhos = Categoria.objects.create(empresa=self.empresa_a, nome="Vinhos Finos")
        self.cat_cervejas = Categoria.objects.create(empresa=self.empresa_a, nome="Cervejas Especiais")

        # Produtos
        self.p_vinho = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="789001",
            nome="Vinho Malbec Reserva",
            categoria=self.cat_vinhos,
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('50.000'),
            estoque_minimo=Decimal('10.000'),
            controle_estoque=True
        )
        self.p_cerveja = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="789002",
            nome="Cerveja IPA Artesanal",
            categoria=self.cat_cervejas,
            preco_custo=Decimal('8.00'),
            preco_venda=Decimal('16.00'),
            estoque_atual=Decimal('20.000'),
            estoque_minimo=Decimal('10.000'),
            controle_estoque=True
        )
        self.p_baixo = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="789004",
            nome="Espumante Brut",
            categoria=self.cat_vinhos,
            preco_custo=Decimal('40.00'),
            preco_venda=Decimal('80.00'),
            estoque_atual=Decimal('2.000'), # Estoque baixo (< 5)
            estoque_minimo=Decimal('5.000'),
            controle_estoque=True
        )
        self.p_zerado = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="789003",
            nome="Licor de Cacau",
            categoria=self.cat_vinhos,
            preco_custo=Decimal('25.00'),
            preco_venda=Decimal('50.00'),
            estoque_atual=Decimal('0.000'), # Estoque zerado
            estoque_minimo=Decimal('5.000'),
            controle_estoque=True
        )

        # Clientes
        self.cliente_joao = Cliente.objects.create(
            empresa=self.empresa_a,
            nome="João Cliente",
            limite_credito=Decimal('500.00'),
            saldo_devedor=Decimal('0.00')
        )

        # Client de Testes HTTP
        self.client = Client()
        self.client.force_login(self.operador_1)

    # 1. Relatório de Vendas (Faturamento Líquido, Bruto, Descontos, Ticket Médio)
    def test_1_relatorio_vendas(self):
        # Venda 1: 1 Vinho (60.00) com 5.00 de desconto = Total 55.00
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            cliente=self.cliente_joao,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 60.00, 'troco': 5.00}],
            desconto=Decimal('5.00')
        )
        # Venda 2: 2 Cervejas (32.00) = Total 32.00
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_2,
            sessao_caixa=self.sessao_2,
            itens_data=[{'produto_id': self.p_cerveja.id, 'quantidade': 2, 'preco_venda': 16.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 32.00, 'troco': 0.00}]
        )

        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])

        self.assertEqual(rep['qtd_vendas'], 2)
        self.assertEqual(rep['faturamento_bruto'], Decimal('92.00')) # 60 + 32
        self.assertEqual(rep['descontos_total'], Decimal('5.00'))
        self.assertEqual(rep['faturamento_liquido'], Decimal('87.00')) # 55 + 32
        self.assertEqual(rep['ticket_medio'], Decimal('43.50'))

    # 2. Filtro Hoje e 3. Filtro Mês Atual e 4. Filtro Personalizado
    def test_2_3_4_filtros_periodo(self):
        hoje = timezone.localdate()
        p_hoje = ReportService.parse_periodo('hoje')
        self.assertEqual(p_hoje['data_inicio'], hoje)
        self.assertEqual(p_hoje['data_fim'], hoje)

        p_mes = ReportService.parse_periodo('mes_atual')
        self.assertEqual(p_mes['data_inicio'].day, 1)

        p_cust = ReportService.parse_periodo('personalizado', '2026-08-01', '2026-08-15')
        self.assertEqual(p_cust['data_inicio'], date(2026, 8, 1))
        self.assertEqual(p_cust['data_fim'], date(2026, 8, 15))

    # 5. Exclusão de Vendas Canceladas
    def test_5_exclusao_vendas_canceladas(self):
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
        )
        venda.status = 'CANCELADA'
        venda.save()

        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(rep['qtd_vendas'], 0)
        self.assertEqual(rep['faturamento_liquido'], Decimal('0.00'))

    # 6. Forma de Pagamento Dinheiro com Abatimento de Troco
    def test_6_forma_pagamento_dinheiro_com_troco(self):
        # Venda 77.30, cliente entregou 100.00 em dinheiro, troco 22.70
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 77.30}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 100.00, 'troco': 22.70}]
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_formas_pagamento_report(self.empresa_a, p['start_datetime'], p['end_datetime'])

        forma_dinheiro = next(f for f in rep['formas'] if f['forma_codigo'] == 'DINHEIRO')
        self.assertEqual(forma_dinheiro['valor'], Decimal('77.30')) # Efetivo: 100 - 22.70
        self.assertEqual(forma_dinheiro['troco'], Decimal('22.70'))
        self.assertEqual(forma_dinheiro['bruto'], Decimal('100.00'))

    # 7. Pagamento Dividido e 8. Preservação do Caixa Físico
    def test_7_e_8_pagamento_dividido(self):
        # Venda de 100.00 paga com 40.00 em Dinheiro e 60.00 em PIX
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': 40.00, 'troco': 0.00},
                {'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}
            ]
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_formas_pagamento_report(self.empresa_a, p['start_datetime'], p['end_datetime'])

        f_dinheiro = next(f for f in rep['formas'] if f['forma_codigo'] == 'DINHEIRO')
        f_pix = next(f for f in rep['formas'] if f['forma_codigo'] == 'PIX')

        self.assertEqual(f_dinheiro['valor'], Decimal('40.00'))
        self.assertEqual(f_pix['valor'], Decimal('60.00'))
        self.assertEqual(rep['total_geral'], Decimal('100.00'))

    # 9. Ranking por Quantidade, 10. Por Faturamento e 11. Por Lucro
    def test_9_10_11_ranking_produtos(self):
        # Venda 1: 5 Cervejas (80.00 fat, custo 40.00, lucro 40.00)
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_cerveja.id, 'quantidade': 5, 'preco_venda': 16.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 80.00, 'troco': 0.00}]
        )
        # Venda 2: 2 Vinhos (120.00 fat, custo 60.00, lucro 60.00)
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 2, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 120.00, 'troco': 0.00}]
        )

        p = ReportService.parse_periodo('hoje')
        # Ranking por Quantidade -> Cerveja (5) deve ser 1º
        rep_qtd = ReportService.get_produtos_ranking(self.empresa_a, p['start_datetime'], p['end_datetime'], sort_by='qtd')
        self.assertEqual(rep_qtd['produtos'][0]['nome'], "Cerveja IPA Artesanal")

        # Ranking por Faturamento -> Vinho (120.00) deve ser 1º
        rep_fat = ReportService.get_produtos_ranking(self.empresa_a, p['start_datetime'], p['end_datetime'], sort_by='faturamento')
        self.assertEqual(rep_fat['produtos'][0]['nome'], "Vinho Malbec Reserva")

        # Ranking por Lucro -> Vinho (60.00) deve ser 1º
        rep_lucro = ReportService.get_produtos_ranking(self.empresa_a, p['start_datetime'], p['end_datetime'], sort_by='lucro')
        self.assertEqual(rep_lucro['produtos'][0]['nome'], "Vinho Malbec Reserva")
        self.assertEqual(rep_lucro['produtos'][0]['lucro_bruto'], Decimal('60.00'))

    # 12. Margem % e Divisão por Zero
    def test_12_margem_lucro_e_divisao_zero(self):
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_produtos_ranking(self.empresa_a, p['start_datetime'], p['end_datetime'])
        # Quando não há vendas, não estoura divisão por zero
        self.assertEqual(len(rep['produtos']), 0)
        self.assertEqual(rep['total_faturamento'], Decimal('0.00'))

    # 13. Vendas por Categoria
    def test_13_vendas_por_categoria(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[
                {'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00},
                {'produto_id': self.p_cerveja.id, 'quantidade': 2, 'preco_venda': 16.00}
            ],
            pagamentos_data=[{'forma': 'PIX', 'valor': 92.00, 'troco': 0.00}]
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_por_categoria(self.empresa_a, p['start_datetime'], p['end_datetime'])

        cat_vinho = next(c for c in rep['categorias'] if c['nome'] == "Vinhos Finos")
        cat_cerveja = next(c for c in rep['categorias'] if c['nome'] == "Cervejas Especiais")

        self.assertEqual(cat_vinho['faturamento'], Decimal('60.00'))
        self.assertEqual(cat_cerveja['faturamento'], Decimal('32.00'))
        self.assertEqual(rep['total_faturamento'], Decimal('92.00'))

    # 14. Vendas por Operador
    def test_14_vendas_por_operador(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
        )
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_2,
            sessao_caixa=self.sessao_2,
            itens_data=[{'produto_id': self.p_cerveja.id, 'quantidade': 1, 'preco_venda': 16.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 16.00, 'troco': 0.00}]
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_por_operador(self.empresa_a, p['start_datetime'], p['end_datetime'])

        op1 = next(o for o in rep if o['id'] == self.operador_1.id)
        op2 = next(o for o in rep if o['id'] == self.operador_2.id)

        self.assertEqual(op1['faturamento'], Decimal('60.00'))
        self.assertEqual(op2['faturamento'], Decimal('16.00'))

    # 15. Vendas por Caixa
    def test_15_vendas_por_caixa(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 60.00, 'troco': 0.00}]
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_por_caixa(self.empresa_a, p['start_datetime'], p['end_datetime'])

        cx1 = next(c for c in rep if c['caixa'].id == self.caixa_1.id)
        self.assertEqual(cx1['faturamento'], Decimal('60.00'))
        self.assertEqual(cx1['dinheiro'], Decimal('60.00'))

    # 16. Estoque Baixo e 17. Estoque Zerado
    def test_16_e_17_relatorio_estoque(self):
        rep = ReportService.get_estoque_report(self.empresa_a)
        self.assertEqual(rep['total_produtos_ativos'], 4)
        self.assertEqual(rep['qtd_zerados'], 1)
        self.assertEqual(rep['qtd_baixo'], 1)
        self.assertEqual(rep['qtd_normais'], 2)

    # 18. Movimentações de Estoque
    def test_18_movimentacoes_estoque(self):
        MovimentacaoEstoque.objects.create(
            empresa=self.empresa_a,
            produto=self.p_vinho,
            tipo='ENTRADA',
            quantidade=Decimal('10.000'),
            estoque_anterior=Decimal('40.000'),
            estoque_posterior=Decimal('50.000'),
            motivo='Compra NF 1234',
            usuario=self.operador_1
        )
        p = ReportService.parse_periodo('hoje')
        movs = ReportService.get_movimentacoes_estoque_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(movs.count(), 1)
        self.assertEqual(movs.first().motivo, 'Compra NF 1234')

    # 19. Relatório de Despesas
    def test_19_relatorio_despesas(self):
        cat = CategoriaDespesa.objects.create(empresa=self.empresa_a, nome="Limpeza")
        hoje = timezone.localdate()
        FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Sabão e Álcool",
            valor=Decimal('50.00'),
            categoria=cat,
            data_vencimento=hoje,
            pago_imediatamente=True,
            forma_pagamento='PIX',
            usuario=self.operador_1
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_despesas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(rep['total_despesas'], Decimal('50.00'))
        self.assertEqual(rep['total_pagas'], Decimal('50.00'))

    # 20. Relatório de Crediário
    def test_20_relatorio_crediario(self):
        # Venda fiada de 100.00
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            cliente=self.cliente_joao,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 100.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 100.00, 'troco': 0.00}]
        )
        rep = ReportService.get_crediario_report(self.empresa_a)
        self.assertEqual(rep['total_vendido_fiado'], Decimal('100.00'))
        self.assertEqual(rep['total_aberto'], Decimal('100.00'))
        self.assertEqual(rep['qtd_devedores'], 1)

    # 21. Isolamento Multi-tenant
    def test_21_isolamento_multi_tenant(self):
        p_b = Produto.objects.create(
            empresa=self.empresa_b,
            codigo_barras="999001",
            nome="Produto Beta",
            preco_custo=Decimal('10.00'),
            preco_venda=Decimal('20.00'),
            estoque_atual=Decimal('5.000')
        )
        rep_a = ReportService.get_estoque_report(self.empresa_a)
        self.assertNotIn(p_b, rep_a['produtos'])

    # 22. Permissões e Autenticação
    def test_22_permissoes_acesso(self):
        client_anon = Client()
        resp = client_anon.get(reverse('relatorios_hub'))
        self.assertEqual(resp.status_code, 302) # Redireciona para login

    # 23. Exportação CSV de Vendas
    def test_23_exportacao_csv_vendas(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
        )
        resp = self.client.get(reverse('exportar_relatorio_csv', args=['vendas']))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8-sig')
        self.assertIn('60,00', resp.content.decode('utf-8-sig'))

    # 24. Exportação CSV de Produtos
    def test_24_exportacao_csv_produtos(self):
        resp = self.client.get(reverse('exportar_relatorio_csv', args=['produtos']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Produto', resp.content.decode('utf-8-sig'))

    # 25. Período Sem Dados
    def test_25_periodo_sem_dados(self):
        p_antigo = ReportService.parse_periodo('personalizado', '2020-01-01', '2020-01-02')
        rep = ReportService.get_vendas_report(self.empresa_a, p_antigo['start_datetime'], p_antigo['end_datetime'])
        self.assertEqual(rep['qtd_vendas'], 0)
        self.assertEqual(rep['faturamento_liquido'], Decimal('0.00'))
        self.assertEqual(rep['ticket_medio'], Decimal('0.00'))

    # 26. Divisão por Zero em Vendas
    def test_26_divisao_por_zero_vendas(self):
        p_antigo = ReportService.parse_periodo('personalizado', '2020-01-01', '2020-01-02')
        rep = ReportService.get_vendas_report(self.empresa_a, p_antigo['start_datetime'], p_antigo['end_datetime'])
        self.assertEqual(rep['margem_lucro_pct'], 0.0)

    # 27. Consistência Faturamento Líquido = Bruto - Descontos
    def test_27_consistencia_faturamento(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 2, 'preco_venda': 60.00}], # 120.00
            pagamentos_data=[{'forma': 'PIX', 'valor': 110.00, 'troco': 0.00}],
            desconto=Decimal('10.00')
        )
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(rep['faturamento_bruto'] - rep['descontos_total'], rep['faturamento_liquido'])

    # 28. Evolução de Vendas Diárias
    def test_28_evolucao_vendas_diarias(self):
        p = ReportService.parse_periodo('7dias')
        rep = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(len(rep['vendas_por_dia']), 7)

    # 29. Exportação CSV Estoque
    def test_29_exportacao_csv_estoque(self):
        resp = self.client.get(reverse('exportar_relatorio_csv', args=['estoque']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Vinho Malbec Reserva', resp.content.decode('utf-8-sig'))

    # 30. Consistência Banco vs Relatório
    def test_30_consistencia_banco_vs_relatorio(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_vinho.id, 'quantidade': 1, 'preco_venda': 60.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
        )
        total_banco = sum((v.total for v in Venda.objects.filter(empresa=self.empresa_a, status='CONCLUIDA')), Decimal('0.00'))
        p = ReportService.parse_periodo('hoje')
        rep = ReportService.get_vendas_report(self.empresa_a, p['start_datetime'], p['end_datetime'])
        self.assertEqual(rep['faturamento_liquido'], total_banco)
