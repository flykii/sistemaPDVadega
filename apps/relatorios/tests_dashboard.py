from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.clientes.models import Cliente
from apps.financeiro.models import ContaPagar, ContaReceber, CategoriaDespesa
from apps.financeiro.services import FinancialService
from apps.relatorios.services import ReportService

class DashboardGerencialTestCase(TestCase):
    def setUp(self):
        # 1. Empresas
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Gerencial Alpha LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="11122233000199"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Gerencial Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="44455566000199"
        )

        # 2. Usuários
        self.operador_1 = Usuario.objects.create_user(
            username="gestor1",
            first_name="Roberto",
            last_name="Gerente",
            email="gestor1@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='GERENTE'
        )

        # 3. Caixas
        self.caixa_1 = Caixa.objects.create(empresa=self.empresa_a, nome="Caixa Principal", codigo_identificador="CX-01")
        self.sessao_1 = CashService.abrir_caixa(self.caixa_1, self.operador_1, Decimal('150.00'))

        # 4. Produtos e Categorias
        self.cat_destilados = Categoria.objects.create(empresa=self.empresa_a, nome="Destilados")
        self.p_whisky = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78999901",
            nome="Whisky 12 Anos",
            categoria=self.cat_destilados,
            preco_custo=Decimal('80.00'),
            preco_venda=Decimal('150.00'),
            estoque_atual=Decimal('20.000'),
            estoque_minimo=Decimal('5.000'),
            controle_estoque=True
        )
        self.p_vodka_baixo = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78999902",
            nome="Vodka Premium",
            categoria=self.cat_destilados,
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('2.000'), # Baixo
            estoque_minimo=Decimal('5.000'),
            controle_estoque=True
        )
        self.p_gin_zerado = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="78999903",
            nome="Gin London Dry",
            categoria=self.cat_destilados,
            preco_custo=Decimal('50.00'),
            preco_venda=Decimal('100.00'),
            estoque_atual=Decimal('0.000'), # Zerado
            estoque_minimo=Decimal('4.000'),
            controle_estoque=True
        )

        # 5. Cliente
        self.cliente_marcos = Cliente.objects.create(
            empresa=self.empresa_a,
            nome="Marcos Rocha",
            limite_credito=Decimal('1000.00'),
            saldo_devedor=Decimal('0.00')
        )

        self.client = Client()
        self.client.force_login(self.operador_1)

    # 1. Dashboard sem vendas
    def test_1_dashboard_sem_vendas(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['vendas_atual']['qtd_vendas'], 0)
        self.assertEqual(resp.context['vendas_atual']['faturamento_liquido'], Decimal('0.00'))
        self.assertEqual(resp.context['vendas_atual']['ticket_medio'], Decimal('0.00'))

    # 2. Dashboard com vendas e comparação de períodos
    def test_2_dashboard_com_vendas_e_comparacao(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            cliente=self.cliente_marcos,
            itens_data=[{'produto_id': self.p_whisky.id, 'quantidade': 1, 'preco_venda': 150.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 150.00, 'troco': 0.00}]
        )
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['vendas_atual']['qtd_vendas'], 1)
        self.assertEqual(resp.context['vendas_atual']['faturamento_liquido'], Decimal('150.00'))
        self.assertEqual(resp.context['vendas_atual']['lucro_bruto'], Decimal('70.00')) # 150 - 80

    # 3. Cálculo de Faturamento Líquido = Bruto - Descontos
    def test_3_calculo_faturamento_liquido(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_whisky.id, 'quantidade': 2, 'preco_venda': 150.00}], # 300.00
            pagamentos_data=[{'forma': 'PIX', 'valor': 270.00, 'troco': 0.00}],
            desconto=Decimal('30.00')
        )
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.context['vendas_atual']['faturamento_bruto'], Decimal('300.00'))
        self.assertEqual(resp.context['vendas_atual']['descontos_total'], Decimal('30.00'))
        self.assertEqual(resp.context['vendas_atual']['faturamento_liquido'], Decimal('270.00'))

    # 4. Formas de Pagamento e 5. Dinheiro com Troco
    def test_4_e_5_formas_pagamento_dinheiro_troco(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_whisky.id, 'quantidade': 1, 'preco_venda': 150.00}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': 200.00, 'troco': 50.00}]
        )
        resp = self.client.get(reverse('dashboard'))
        formas = resp.context['formas_data']['formas']
        dinheiro_forma = next(f for f in formas if f['forma_codigo'] == 'DINHEIRO')
        self.assertEqual(dinheiro_forma['valor'], Decimal('150.00')) # Líquido: 200 - 50
        self.assertEqual(dinheiro_forma['troco'], Decimal('50.00'))

    # 6. Pagamento Dividido
    def test_6_pagamento_dividido(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_whisky.id, 'quantidade': 1, 'preco_venda': 150.00}],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': 50.00, 'troco': 0.00},
                {'forma': 'PIX', 'valor': 100.00, 'troco': 0.00}
            ]
        )
        resp = self.client.get(reverse('dashboard'))
        formas = resp.context['formas_data']['formas']
        f_dinheiro = next(f for f in formas if f['forma_codigo'] == 'DINHEIRO')
        f_pix = next(f for f in formas if f['forma_codigo'] == 'PIX')
        self.assertEqual(f_dinheiro['valor'], Decimal('50.00'))
        self.assertEqual(f_pix['valor'], Decimal('100.00'))

    # 7. Estoque Zerado e Baixo
    def test_7_estoque_zerado_e_baixo(self):
        resp = self.client.get(reverse('dashboard'))
        estoque = resp.context['estoque_data']
        self.assertEqual(estoque['qtd_zerados'], 1)
        self.assertEqual(estoque['qtd_baixo'], 1)
        self.assertEqual(len(estoque['produtos_criticos']), 2)

    # 8. Valor Patrimonial do Estoque
    def test_8_valor_patrimonial_estoque(self):
        resp = self.client.get(reverse('dashboard'))
        estoque = resp.context['estoque_data']
        # p_whisky: 20 * 80 = 1600; p_vodka: 2 * 30 = 60; p_gin: 0 * 50 = 0 -> Total custo 1660.00
        self.assertEqual(estoque['valor_total_custo'], Decimal('1660.00'))
        # p_whisky: 20 * 150 = 3000; p_vodka: 2 * 60 = 120 -> Total venda 3120.00
        self.assertEqual(estoque['valor_total_venda'], Decimal('3120.00'))

    # 9. Lucro Real utilizando custo histórico no momento da venda
    def test_9_lucro_custo_momento(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            itens_data=[{'produto_id': self.p_whisky.id, 'quantidade': 1, 'preco_venda': 150.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 150.00, 'troco': 0.00}]
        )
        # Altera o preço de custo atual do produto para 120.00
        self.p_whisky.preco_custo = Decimal('120.00')
        self.p_whisky.save()

        resp = self.client.get(reverse('dashboard'))
        # O lucro deve continuar sendo 150 - 80 = 70.00 (custo histórico do item)
        self.assertEqual(resp.context['vendas_atual']['lucro_bruto'], Decimal('70.00'))

    # 10. Despesas no Dashboard
    def test_10_despesas_dashboard(self):
        cat = CategoriaDespesa.objects.create(empresa=self.empresa_a, nome="Manutenção")
        FinancialService.cadastrar_despesa_avulsa(
            empresa=self.empresa_a,
            descricao="Troca de Lâmpadas",
            valor=Decimal('75.00'),
            categoria=cat,
            data_vencimento=timezone.localdate(),
            pago_imediatamente=True,
            forma_pagamento='PIX',
            usuario=self.operador_1
        )
        resp = self.client.get(reverse('dashboard'))
        desp = resp.context['despesas_data']
        self.assertEqual(desp['total_despesas'], Decimal('75.00'))
        self.assertEqual(desp['total_pagas'], Decimal('75.00'))

    # 11. Caixas Abertos no Dashboard
    def test_11_caixas_abertos(self):
        resp = self.client.get(reverse('dashboard'))
        abertos = resp.context['caixas_abertos']
        self.assertEqual(abertos.count(), 1)
        self.assertEqual(abertos.first().saldo_esperado, Decimal('150.00'))

    # 12. Diferença de Fechamento de Caixa
    def test_12_diferenca_fechamento_caixa(self):
        # Fecha a sessão 1 com sobra de 10.00 (esperado 150.00, contado 160.00)
        CashService.fechar_caixa(self.sessao_1, Decimal('160.00'), "Fechamento com sobra")
        resp = self.client.get(reverse('dashboard'))
        fechadas = resp.context['ultimas_sessoes_fechadas']
        self.assertEqual(len(fechadas), 1)
        self.assertEqual(fechadas[0]['diferenca'], Decimal('10.00'))
        self.assertIn('SOBRA', fechadas[0]['status_diferenca'])

    # 13. Crediário e Clientes Devedores
    def test_13_crediario_dashboard(self):
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_1,
            sessao_caixa=self.sessao_1,
            cliente=self.cliente_marcos,
            itens_data=[{'produto_id': self.p_whisky.id, 'quantidade': 1, 'preco_venda': 150.00}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': 150.00, 'troco': 0.00}]
        )
        resp = self.client.get(reverse('dashboard'))
        cred = resp.context['crediario_data']
        self.assertEqual(cred['total_aberto'], Decimal('150.00'))
        self.assertEqual(cred['qtd_devedores'], 1)
        self.assertEqual(cred['top_devedores'][0]['cliente'].nome, "Marcos Rocha")

    # 14. Filtros de Período
    def test_14_filtros_periodo_dashboard(self):
        resp_hoje = self.client.get(reverse('dashboard') + '?periodo=hoje')
        self.assertEqual(resp_hoje.status_code, 200)
        self.assertEqual(resp_hoje.context['p_info']['periodo'], 'hoje')

        resp_30d = self.client.get(reverse('dashboard') + '?periodo=30dias')
        self.assertEqual(resp_30d.status_code, 200)
        self.assertEqual(resp_30d.context['p_info']['periodo'], '30dias')

    # 15. Isolamento Multi-tenant
    def test_15_isolamento_multi_tenant(self):
        # Cria produto e caixa na Empresa B
        caixa_b = Caixa.objects.create(empresa=self.empresa_b, nome="Caixa B", codigo_identificador="CX-B")
        resp = self.client.get(reverse('dashboard'))
        for cx in resp.context['caixas_abertos']:
            self.assertEqual(cx.empresa_id, self.empresa_a.id)

    # 16. Permissões de Acesso
    def test_16_permissoes_acesso(self):
        client_anonimo = Client()
        resp = client_anonimo.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 302)
