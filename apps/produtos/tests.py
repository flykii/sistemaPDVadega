from decimal import Decimal
from django.test import TestCase
from django.db import IntegrityError
from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.produtos.services import StockService
from apps.clientes.models import Fornecedor
from apps.caixas.models import Caixa
from apps.caixas.services import CashService
from apps.vendas.services import SaleService
from apps.compras.services import PurchaseService
from apps.compras.models import Compra
from apps.core.pricing import calculate_sale_price, calculate_profit_amount

class ProductStockPurchaseTestCase(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Alfa LTDA",
            nome_fantasia="Adega Alfa",
            cnpj="11222333000144"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="55666777000188"
        )

        self.operador_a = Usuario.objects.create_user(
            username="operador_a",
            email="op_a@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )

        self.categoria_cervejas = Categoria.objects.create(
            empresa=self.empresa_a,
            nome="Cervejas",
            descricao="Cervejas nacionais e importadas"
        )

        self.fornecedor = Fornecedor.objects.create(
            empresa=self.empresa_a,
            razao_social="Ambev Distribuidora LTDA",
            nome_fantasia="Ambev",
            cnpj="00111222000133"
        )

        self.caixa = Caixa.objects.create(
            empresa=self.empresa_a,
            nome="Caixa 01",
            codigo_identificador="CX-01"
        )
        self.sessao_caixa = CashService.abrir_caixa(self.caixa, self.operador_a, Decimal('200.00'))

    # 1. Cadastro de produto com precificação
    def test_1_cadastro_produto(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7891991000800",
            sku="BEB-001",
            nome="Cerveja Brahma 350ml",
            categoria=self.categoria_cervejas,
            fornecedor_principal=self.fornecedor,
            preco_custo=Decimal('2.50'),
            margem_lucro=Decimal('30.00'),
            estoque_atual=Decimal('50.000'),
            estoque_minimo=Decimal('10.000'),
            unidade_medida='LT'
        )
        self.assertEqual(prod.nome, "Cerveja Brahma 350ml")
        self.assertEqual(prod.preco_venda, Decimal('3.57')) # 2.50 / 0.7 = 3.5714... -> 3.57
        self.assertEqual(prod.status_estoque, 'NORMAL')

    # 2. Código de barras duplicado na mesma empresa (deve disparar erro)
    def test_2_codigo_barras_duplicado_mesma_empresa(self):
        Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7891991000800",
            nome="Produto A",
            preco_custo=Decimal('5.00'),
            preco_venda=Decimal('10.00')
        )
        with self.assertRaises(IntegrityError):
            Produto.objects.create(
                empresa=self.empresa_a,
                codigo_barras="7891991000800",
                nome="Produto B",
                preco_custo=Decimal('6.00'),
                preco_venda=Decimal('12.00')
            )

    # 3. Mesmo código de barras em empresas diferentes (suportado pelo multi-tenant)
    def test_3_mesmo_codigo_barras_empresas_diferentes(self):
        prod_a = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7891991000800",
            nome="Produto Alfa",
            preco_custo=Decimal('5.00'),
            preco_venda=Decimal('10.00')
        )
        prod_b = Produto.objects.create(
            empresa=self.empresa_b,
            codigo_barras="7891991000800",
            nome="Produto Beta",
            preco_custo=Decimal('6.00'),
            preco_venda=Decimal('12.00')
        )
        self.assertNotEqual(prod_a.empresa, prod_b.empresa)
        self.assertEqual(prod_a.codigo_barras, prod_b.codigo_barras)

    # 4. Cadastro de categoria e unicidade por empresa
    def test_4_cadastro_categoria_unicidade(self):
        cat = Categoria.objects.create(empresa=self.empresa_a, nome="Destilados")
        self.assertEqual(cat.nome, "Destilados")
        with self.assertRaises(IntegrityError):
            Categoria.objects.create(empresa=self.empresa_a, nome="Destilados")

    # 5. Entrada de estoque (StockService.add_stock)
    def test_5_entrada_estoque(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890001",
            nome="Vinho Tinto",
            preco_custo=Decimal('20.00'),
            preco_venda=Decimal('40.00'),
            estoque_atual=Decimal('5.000')
        )
        mov = StockService.add_stock(prod, Decimal('10.000'), motivo="Aporte de fornecedor", usuario=self.operador_a)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('15.000'))
        self.assertEqual(mov.tipo, 'ENTRADA')
        self.assertEqual(mov.estoque_anterior, Decimal('5.000'))
        self.assertEqual(mov.estoque_posterior, Decimal('15.000'))
        self.assertEqual(mov.usuario, self.operador_a)

    # 6. Saída de estoque (StockService.remove_stock)
    def test_6_saida_estoque(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890002",
            nome="Vodka 1L",
            preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('20.000')
        )
        mov = StockService.remove_stock(prod, Decimal('5.000'), motivo="Venda Avulsa", usuario=self.operador_a)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('15.000'))
        self.assertEqual(mov.tipo, 'SAIDA')
        self.assertEqual(mov.estoque_anterior, Decimal('20.000'))
        self.assertEqual(mov.estoque_posterior, Decimal('15.000'))

    # 7. Ajuste positivo de estoque
    def test_7_ajuste_positivo(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890003",
            nome="Gin 750ml",
            estoque_atual=Decimal('10.000')
        )
        mov = StockService.adjust_stock(prod, Decimal('15.000'), motivo="Contagem de Balanço", usuario=self.operador_a)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('15.000'))
        self.assertEqual(mov.tipo, 'AJUSTE')
        self.assertEqual(mov.quantidade, Decimal('5.000')) # Delta
        self.assertEqual(mov.estoque_anterior, Decimal('10.000'))
        self.assertEqual(mov.estoque_posterior, Decimal('15.000'))

    # 8. Ajuste negativo de estoque
    def test_8_ajuste_negativo(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890004",
            nome="Whisky 12 Anos",
            estoque_atual=Decimal('10.000')
        )
        mov = StockService.adjust_stock(prod, Decimal('8.000'), motivo="Garrafas Quebradas", usuario=self.operador_a)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('8.000'))
        self.assertEqual(mov.quantidade, Decimal('2.000'))
        self.assertEqual(mov.estoque_anterior, Decimal('10.000'))
        self.assertEqual(mov.estoque_posterior, Decimal('8.000'))

    # 9. Bloqueio de estoque negativo
    def test_9_bloqueio_estoque_negativo(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890005",
            nome="Energético 2L",
            estoque_atual=Decimal('2.000'),
            controle_estoque=True
        )
        with self.assertRaises(ValueError) as ctx:
            StockService.remove_stock(prod, Decimal('5.000'), motivo="Venda")
        self.assertIn("Estoque insuficiente", str(ctx.exception))

    # 10. Produto com estoque baixo
    def test_10_produto_estoque_baixo(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890006",
            nome="Gelo em Cubos 5kg",
            estoque_atual=Decimal('4.000'),
            estoque_minimo=Decimal('10.000')
        )
        self.assertTrue(prod.estoque_baixo)
        self.assertFalse(prod.estoque_zerado)
        self.assertEqual(prod.status_estoque, 'BAIXO')

    # 11. Produto com estoque zerado
    def test_11_produto_zerado(self):
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7890007",
            nome="Carvão 3kg",
            estoque_atual=Decimal('0.000'),
            estoque_minimo=Decimal('5.000')
        )
        self.assertTrue(prod.estoque_zerado)
        self.assertTrue(prod.estoque_baixo)
        self.assertEqual(prod.status_estoque, 'ZERADO')

    # 12. Compra com múltiplos itens
    def test_12_compra_com_multiplos_itens(self):
        prod1 = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891001", nome="Item 1", preco_custo=Decimal('5.00'), estoque_atual=Decimal('0.000'))
        prod2 = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891002", nome="Item 2", preco_custo=Decimal('10.00'), estoque_atual=Decimal('0.000'))

        compra = PurchaseService.processar_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-100",
            itens_data=[
                {'produto_id': prod1.id, 'quantidade': 10, 'preco_custo_unitario': 6.00},
                {'produto_id': prod2.id, 'quantidade': 5, 'preco_custo_unitario': 12.00}
            ],
            usuario=self.operador_a
        )
        # Total esperado: (10 * 6.00) + (5 * 12.00) = 60 + 60 = 120.00
        self.assertEqual(compra.total, Decimal('120.00'))
        self.assertEqual(compra.itens.count(), 2)

    # 13. Compra atualizando estoque dos produtos
    def test_13_compra_atualizando_estoque(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891003", nome="Cerveja Lata", preco_custo=Decimal('3.00'), estoque_atual=Decimal('20.000'))
        PurchaseService.processar_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-200",
            itens_data=[{'produto_id': prod.id, 'quantidade': 50, 'preco_custo_unitario': 3.20}],
            usuario=self.operador_a
        )
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('70.000')) # 20 + 50
        self.assertEqual(prod.preco_custo, Decimal('3.20')) # Atualizou custo

    # 14. Compra gerando movimentações de estoque rastreadas
    def test_14_compra_gerando_movimentacoes(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891004", nome="Refrigerante 2L", estoque_atual=Decimal('10.000'))
        compra = PurchaseService.processar_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-300",
            itens_data=[{'produto_id': prod.id, 'quantidade': 30, 'preco_custo_unitario': 5.00}],
            usuario=self.operador_a
        )
        mov = MovimentacaoEstoque.objects.filter(origem_ref=f"Compra #{compra.id}").first()
        self.assertIsNotNone(mov)
        self.assertEqual(mov.tipo, 'ENTRADA')
        self.assertEqual(mov.quantidade, Decimal('30.000'))
        self.assertEqual(mov.estoque_anterior, Decimal('10.000'))
        self.assertEqual(mov.estoque_posterior, Decimal('40.000'))

    # 15. Rollback total de compra em caso de erro
    def test_15_rollback_compra(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891005", nome="Item Válido", estoque_atual=Decimal('10.000'))
        compras_antes = Compra.objects.count()

        with self.assertRaises(ValueError):
            PurchaseService.processar_compra(
                empresa=self.empresa_a,
                fornecedor=self.fornecedor,
                numero_nota="NF-ERR",
                itens_data=[
                    {'produto_id': prod.id, 'quantidade': 10, 'preco_custo_unitario': 5.00},
                    {'produto_id': 999999, 'quantidade': 10, 'preco_custo_unitario': 5.00} # ID inexistente
                ]
            )

        # Confirma Rollback Total: nenhuma compra criada e estoque intacto
        self.assertEqual(Compra.objects.count(), compras_antes)
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('10.000'))

    # 16. Venda reduzindo estoque no PDV
    def test_16_venda_reduzindo_estoque(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891006", nome="Agua 500ml", preco_venda=Decimal('3.00'), estoque_atual=Decimal('50.000'))
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            itens_data=[{'produto_id': prod.id, 'quantidade': 12, 'preco_venda': 3.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 36.00, 'troco': 0.00}]
        )
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('38.000')) # 50 - 12 = 38

    # 17. Concorrência e bloqueio de estoque insuficiente
    def test_17_concorrencia_estoque(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7891007", nome="Item Limitado", preco_venda=Decimal('10.00'), estoque_atual=Decimal('5.000'))
        # Venda 1 consome 5
        SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            itens_data=[{'produto_id': prod.id, 'quantidade': 5, 'preco_venda': 10.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 50.00, 'troco': 0.00}]
        )
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('0.000'))

        # Venda 2 tenta consumir 1 adicional -> bloqueado
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a,
                operador=self.operador_a,
                sessao_caixa=self.sessao_caixa,
                itens_data=[{'produto_id': prod.id, 'quantidade': 1, 'preco_venda': 10.00}],
                pagamentos_data=[{'forma': 'PIX', 'valor': 10.00, 'troco': 0.00}]
            )
        self.assertIn("Estoque insuficiente", str(ctx.exception))

    # 18. Isolamento Multi-Tenancy entre empresas
    def test_18_isolamento_multi_tenancy(self):
        prod_a = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7892001", nome="Prod Alfa", preco_venda=Decimal('10.00'))
        prod_b = Produto.objects.create(empresa=self.empresa_b, codigo_barras="7892002", nome="Prod Beta", preco_venda=Decimal('20.00'))

        self.assertIn(prod_a, Produto.objects.filter(empresa=self.empresa_a))
        self.assertNotIn(prod_b, Produto.objects.filter(empresa=self.empresa_a))

    # 19. Produto inativo não aparece no catálogo ativo
    def test_19_produto_inativo(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7892003", nome="Prod Inativo", preco_venda=Decimal('10.00'), ativo=False)
        self.assertNotIn(prod, Produto.objects.filter(empresa=self.empresa_a, ativo=True))

    # 20. Histórico de movimentações e cálculo de lucro
    def test_20_historico_movimentacoes_e_lucro(self):
        prod = Produto.objects.create(empresa=self.empresa_a, codigo_barras="7892004", nome="Whisky Black", preco_custo=Decimal('100.00'), margem_lucro=Decimal('25.00'))
        # 100 / 0.75 = 133.33 -> Lucro unitário = 33.33
        self.assertEqual(prod.preco_venda, Decimal('133.33'))
        self.assertEqual(prod.lucro_real, Decimal('33.33'))

    # 21. Integração Completa: Compra ➔ Estoque ➔ PDV ➔ Baixa
    def test_21_integracao_compra_estoque_pdv(self):
        # 1. Produto criado com estoque 0
        prod = Produto.objects.create(
            empresa=self.empresa_a,
            codigo_barras="7899999",
            nome="Cerveja Artesanal IPA",
            preco_custo=Decimal('8.00'),
            preco_venda=Decimal('15.00'),
            estoque_atual=Decimal('0.000')
        )

        # 2. Entrada via Compra de 24 unidades a R$ 7.50
        compra = PurchaseService.processar_compra(
            empresa=self.empresa_a,
            fornecedor=self.fornecedor,
            numero_nota="NF-IPA-01",
            itens_data=[{'produto_id': prod.id, 'quantidade': 24, 'preco_custo_unitario': 7.50}],
            usuario=self.operador_a
        )
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('24.000'))
        self.assertEqual(prod.preco_custo, Decimal('7.50'))

        # 3. Venda no PDV de 4 unidades
        venda = SaleService.processar_venda(
            empresa=self.empresa_a,
            operador=self.operador_a,
            sessao_caixa=self.sessao_caixa,
            itens_data=[{'produto_id': prod.id, 'quantidade': 4, 'preco_venda': 15.00}],
            pagamentos_data=[{'forma': 'PIX', 'valor': 60.00, 'troco': 0.00}]
        )
        prod.refresh_from_db()
        self.assertEqual(prod.estoque_atual, Decimal('20.000')) # 24 - 4 = 20
        self.assertEqual(venda.total, Decimal('60.00'))
