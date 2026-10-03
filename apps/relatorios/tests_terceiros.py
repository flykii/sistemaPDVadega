from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.empresas.models import Empresa
from apps.clientes.models import Fornecedor, Cliente
from apps.produtos.models import Produto, MovimentacaoEstoque
from apps.produtos.services import StockService
from apps.caixas.models import Caixa, SessaoCaixa
from apps.vendas.models import Venda, ItemVenda
from apps.vendas.services import SaleService
from apps.relatorios.services import ReportService

Usuario = get_user_model()


class ProdutosTerceirosTestCase(TestCase):
    def setUp(self):
        # 1. Criação das Empresas para teste de Isolamento Multiempresa
        self.empresa_a = Empresa.objects.create(
            razao_social="Empresa Matriz A LTDA",
            nome_fantasia="Adega Matriz",
            cnpj="11111111000111"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Empresa Filial B LTDA",
            nome_fantasia="Adega Filial B",
            cnpj="22222222000122"
        )

        # 2. Usuários
        self.user_a = Usuario.objects.create_user(
            username="admin_a",
            password="password123",
            empresa=self.empresa_a,
            cargo="ADMIN"
        )
        self.user_b = Usuario.objects.create_user(
            username="admin_b",
            password="password123",
            empresa=self.empresa_b,
            cargo="ADMIN"
        )

        # 3. Fornecedores / Terceiros
        self.terceiro_1 = Fornecedor.objects.create(
            empresa=self.empresa_a,
            razao_social="Distribuidora de Canetas Bobbie Goods",
            nome_fantasia="Bobbie Goods Oficial",
            cnpj="33333333000133"
        )
        self.terceiro_2 = Fornecedor.objects.create(
            empresa=self.empresa_a,
            razao_social="Eletrônicos e Acessórios Inova",
            nome_fantasia="Inova Acessórios",
            cnpj="44444444000144"
        )
        self.terceiro_b = Fornecedor.objects.create(
            empresa=self.empresa_b,
            razao_social="Terceiro Empresa B",
            nome_fantasia="Terceiro B",
            cnpj="55555555000155"
        )

        # 4. Caixas e Sessões
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa 01",
            codigo_identificador="CX01",
            status='ABERTO',
            ativo=True
        )
        self.sessao_a = SessaoCaixa.objects.create(
            empresa=self.empresa_a,
            caixa=self.caixa_a,
            operador=self.user_a,
            saldo_inicial=Decimal('100.00'),
            status='ABERTA'
        )

        self.client_a = Client()
        self.client_a.force_login(self.user_a)

    def test_1_cadastro_produto_terceiro(self):
        """1. Valida o cadastro de produto de terceiro."""
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Bobbie Goods + 6 Canetas",
            codigo_barras="7890001112223",
            sku="BG-001",
            fornecedor_principal=self.terceiro_1,
            is_produto_terceiro=True,
            preco_venda=Decimal('25.00'),
            percentual_repasse=Decimal('70.00'),
            estoque_atual=Decimal('3.000'),
            ativo=True
        )
        # O nome deve ser gravado em CAIXA ALTA
        self.assertEqual(prod.nome, "BOBBIE GOODS + 6 CANETAS")
        self.assertTrue(prod.is_produto_terceiro)
        self.assertEqual(prod.percentual_repasse, Decimal('70.00'))
        self.assertEqual(prod.fornecedor_principal, self.terceiro_1)

    def test_2_percentual_repasse_padrao_e_customizado(self):
        """2. Valida o percentual de 70% padrão e percentual customizado (ex: 60%, 50%)."""
        # Produto com 70%
        p70 = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Produto 70%",
            codigo_barras="7890000000070",
            is_produto_terceiro=True,
            preco_venda=Decimal('100.00'),
            percentual_repasse=Decimal('70.00')
        )
        self.assertEqual(p70.valor_repasse_unitario, Decimal('70.00'))
        self.assertEqual(p70.lucro_unitario_terceiro, Decimal('30.00'))

        # Produto com 60%
        p60 = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Produto 60%",
            codigo_barras="7890000000060",
            is_produto_terceiro=True,
            preco_venda=Decimal('100.00'),
            percentual_repasse=Decimal('60.00')
        )
        self.assertEqual(p60.valor_repasse_unitario, Decimal('60.00'))
        self.assertEqual(p60.lucro_unitario_terceiro, Decimal('40.00'))

    def test_3_e_4_calculo_repasse_e_lucro(self):
        """3 e 4. Valida as fórmulas de repasse e lucro com precisão Decimal."""
        # Preço de venda: R$ 25,00
        # Repasse: 70% -> R$ 17,50
        # Lucro: R$ 7,50
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Cabo Celular Inova 3.4",
            codigo_barras="7890000000001",
            fornecedor_principal=self.terceiro_2,
            is_produto_terceiro=True,
            preco_venda=Decimal('25.00'),
            percentual_repasse=Decimal('70.00')
        )
        self.assertEqual(prod.valor_repasse_unitario, Decimal('17.50'))
        self.assertEqual(prod.lucro_unitario_terceiro, Decimal('7.50'))
        self.assertEqual(prod.preco_custo, Decimal('17.500'))

    def test_5_estoque_inicial_registrado_uma_unica_vez(self):
        """5. Valida que o estoque inicial informado via tela é registrado uma única vez (sem duplicar)."""
        response = self.client_a.post('/relatorios/terceiros/produtos/novo/', {
            'nome': 'Fone Bluetooth P9',
            'codigo_barras': '7891234567890',
            'sku': 'FONE-P9',
            'fornecedor_id': self.terceiro_2.id,
            'preco_venda': '80.00',
            'percentual_repasse': '70.00',
            'estoque_atual': '10.000',
            'ativo': 'on'
        })
        self.assertEqual(response.status_code, 302)

        prod = Produto.objects.get(empresa=self.empresa_a, codigo_barras='7891234567890')
        # Estoque deve ser exatamente 10 (não 20)
        self.assertEqual(prod.estoque_atual, Decimal('10.000'))
        movs = MovimentacaoEstoque.objects.filter(produto=prod)
        self.assertEqual(movs.count(), 1)
        self.assertEqual(movs.first().tipo, 'ENTRADA')
        self.assertEqual(movs.first().quantidade, Decimal('10.000'))

    def test_6_7_8_venda_pdv_baixa_estoque_e_registro(self):
        """6, 7 e 8. Venda pelo PDV, baixa automática de estoque e registro da venda."""
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Carregador Turbo Tipo C",
            codigo_barras="7899998881110",
            fornecedor_principal=self.terceiro_2,
            is_produto_terceiro=True,
            preco_venda=Decimal('30.00'),
            percentual_repasse=Decimal('70.00'),
            estoque_atual=Decimal('5.000'),
            ativo=True
        )

        # Realiza venda de 2 unidades pelo SaleService (mesmo fluxo do PDV)
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.user_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{
                'produto_id': prod.id,
                'quantidade': 2,
                'preco_venda': 30.00
            }],
            pagamentos_data=[{
                'forma': 'DINHEIRO',
                'valor': 60.00,
                'troco': 0.00,
                'dados': {}
            }]
        )

        self.assertEqual(venda.status, 'CONCLUIDA')
        self.assertEqual(venda.total, Decimal('60.00'))

        # 7. Baixa de estoque
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('3.000'))

        # 8. Registro de item com custo = repasse
        item = venda.itens.first()
        self.assertEqual(item.quantidade, Decimal('2.000'))
        self.assertEqual(item.preco_venda_unitario, Decimal('30.00'))
        self.assertEqual(item.preco_custo_unitario, Decimal('21.00')) # 70% de 30 = 21

    def test_9_10_11_calculos_no_relatorio_de_terceiros(self):
        """9, 10 e 11. Valida cálculo de valor vendido, valor a repassar e lucro nas vendas no relatório."""
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Bobbie Goods + 6 Canetas",
            codigo_barras="7895554443332",
            fornecedor_principal=self.terceiro_1,
            is_produto_terceiro=True,
            preco_venda=Decimal('25.00'),
            percentual_repasse=Decimal('70.00'),
            estoque_atual=Decimal('3.000'),
            ativo=True
        )

        # Vende 1 unidade
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.user_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{
                'produto_id': prod.id,
                'quantidade': 1,
                'preco_venda': 25.00
            }],
            pagamentos_data=[{
                'forma': 'PIX',
                'valor': 25.00,
                'troco': 0.00,
                'dados': {}
            }]
        )

        # Consulta relatório de hoje
        hoje = timezone.now().date()
        dados = ReportService.get_relatorio_terceiros(
            empresa=self.empresa_a,
            start_dt=hoje,
            end_dt=hoje
        )

        # 9. Valor vendido = R$ 25,00
        self.assertEqual(dados['valor_total_vendido'], Decimal('25.00'))
        # 10. Valor a repassar = R$ 17,50 (70% de 25)
        self.assertEqual(dados['total_a_repassar'], Decimal('17.50'))
        # 11. Lucro obtido = R$ 7,50
        self.assertEqual(dados['lucro_obtido_vendas'], Decimal('7.50'))

        # Validação do estoque restante: 2 unidades (3 - 1)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('2.000'))
        self.assertEqual(dados['total_itens_estoque'], Decimal('2.000'))
        self.assertEqual(dados['valor_total_estoque'], Decimal('50.00')) # 2 * 25
        self.assertEqual(dados['valor_total_repasse_estoque'], Decimal('35.00')) # 2 * 17.50
        self.assertEqual(dados['lucro_potencial_estoque'], Decimal('15.00')) # 50 - 35

    def test_12_isolamento_multiempresa(self):
        """12. Garante que produtos de terceiros de uma empresa não aparecem em outra."""
        p_a = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Produto Terceiro A",
            codigo_barras="789000000000A",
            is_produto_terceiro=True,
            preco_venda=Decimal('10.00'),
            fornecedor_principal=self.terceiro_1
        )
        p_b = Produto.objects.create(
            empresa=self.empresa_b,
            nome="Produto Terceiro B",
            codigo_barras="789000000000B",
            is_produto_terceiro=True,
            preco_venda=Decimal('20.00'),
            fornecedor_principal=self.terceiro_b
        )

        hoje = timezone.now().date()
        rel_a = ReportService.get_relatorio_terceiros(self.empresa_a, hoje, hoje)
        rel_b = ReportService.get_relatorio_terceiros(self.empresa_b, hoje, hoje)

        ids_a = [linha['produto'].id for linha in rel_a['linhas']]
        ids_b = [linha['produto'].id for linha in rel_b['linhas']]

        self.assertIn(p_a.id, ids_a)
        self.assertNotIn(p_b.id, ids_a)
        self.assertIn(p_b.id, ids_b)
        self.assertNotIn(p_a.id, ids_b)

    def test_13_vendas_canceladas_nao_contabilizadas(self):
        """13. Garante que vendas canceladas não permaneçam no relatório nem retenham repasse."""
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Fone Ouvido Inova",
            codigo_barras="7897776665554",
            fornecedor_principal=self.terceiro_2,
            is_produto_terceiro=True,
            preco_venda=Decimal('15.00'),
            percentual_repasse=Decimal('70.00'),
            estoque_atual=Decimal('10.000'),
            ativo=True
        )

        # Realiza venda
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.user_a,
            sessao_caixa=self.sessao_a,
            itens_data=[{
                'produto_id': prod.id,
                'quantidade': 2,
                'preco_venda': 15.00
            }],
            pagamentos_data=[{
                'forma': 'DINHEIRO',
                'valor': 30.00,
                'troco': 0.00,
                'dados': {}
            }]
        )

        hoje = timezone.now().date()
        # Antes de cancelar: vendido = 2 itens, R$ 30,00
        dados_antes = ReportService.get_relatorio_terceiros(self.empresa_a, hoje, hoje, produto_id=prod.id)
        self.assertEqual(dados_antes['total_itens_vendidos'], Decimal('2.000'))
        self.assertEqual(dados_antes['valor_total_vendido'], Decimal('30.00'))

        # Cancela a venda
        SaleService.cancelar_venda(venda.id, self.empresa_a, self.user_a, motivo="Cancelamento teste")

        # Após cancelar: vendido deve ser 0
        dados_depois = ReportService.get_relatorio_terceiros(self.empresa_a, hoje, hoje, produto_id=prod.id)
        self.assertEqual(dados_depois['total_itens_vendidos'], Decimal('0.000'))
        self.assertEqual(dados_depois['valor_total_vendido'], Decimal('0.00'))
        self.assertEqual(dados_depois['total_a_repassar'], Decimal('0.00'))
        self.assertEqual(dados_depois['lucro_obtido_vendas'], Decimal('0.00'))

        # Estoque deve ter sido devolvido
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('10.000'))

    def test_14_relatorio_por_periodo(self):
        """14. Valida filtro de período no relatório."""
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Fone Ossea",
            codigo_barras="7891112223334",
            is_produto_terceiro=True,
            preco_venda=Decimal('50.00'),
            percentual_repasse=Decimal('70.00'),
            estoque_atual=Decimal('5.000')
        )

        hoje = timezone.now().date()
        ontem = hoje - timedelta(days=1)

        # Sem vendas ontem
        dados_ontem = ReportService.get_relatorio_terceiros(self.empresa_a, ontem, ontem, produto_id=prod.id)
        self.assertEqual(dados_ontem['total_itens_vendidos'], Decimal('0.000'))

    def test_15_relatorio_filtro_por_terceiro(self):
        """15. Valida filtro por fornecedor/terceiro específico."""
        p_t1 = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Produto do Terceiro 1",
            codigo_barras="7890000000011",
            fornecedor_principal=self.terceiro_1,
            is_produto_terceiro=True,
            preco_venda=Decimal('20.00')
        )
        p_t2 = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Produto do Terceiro 2",
            codigo_barras="7890000000022",
            fornecedor_principal=self.terceiro_2,
            is_produto_terceiro=True,
            preco_venda=Decimal('30.00')
        )

        hoje = timezone.now().date()
        rel_t1 = ReportService.get_relatorio_terceiros(self.empresa_a, hoje, hoje, terceiro_id=self.terceiro_1.id)
        ids = [linha['produto'].id for linha in rel_t1['linhas']]

        self.assertIn(p_t1.id, ids)
        self.assertNotIn(p_t2.id, ids)

    def test_16_integridade_produtos_normais(self):
        """16. Garante a integridade dos produtos normais (não terceirizados)."""
        prod_normal = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Refrigerante Coca-Cola 2L",
            codigo_barras="7894900010015",
            preco_custo=Decimal('7.00'),
            margem_lucro=Decimal('30.00'),
            preco_venda=Decimal('10.00'),
            is_produto_terceiro=False
        )

        # Não deve ser afetado por regras de terceiro
        self.assertFalse(prod_normal.is_produto_terceiro)
        self.assertEqual(prod_normal.valor_repasse_unitario, Decimal('0.00'))

        # Não deve constar no relatório de terceiros
        hoje = timezone.now().date()
        rel = ReportService.get_relatorio_terceiros(self.empresa_a, hoje, hoje)
        ids = [linha['produto'].id for linha in rel['linhas']]
        self.assertNotIn(prod_normal.id, ids)
