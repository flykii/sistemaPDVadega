from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.vendas.models import Venda, ItemVenda
from apps.vendas.services import SaleService


class ProdutosRapidosTests(TestCase):
    """
    Testes automatizados completos para a funcionalidade Produtos Rápidos:
    - Agrupamento por letra normalizada (A -> Z, 0-9, #)
    - Tratamento de caracteres acentuados (Á, É, Í, Ó, Ú, Ç)
    - Limite de até 4 produtos por letra
    - Priorização por vendas nos últimos 60 dias (apenas vendas CONCLUÍDAS)
    - Desconsideração de vendas canceladas, rascunhos e vendas antigas (>60d)
    - Produtos sem vendas elegíveis para completar as 4 vagas
    - Desempate por nome alfabético
    - Isolamento multi-tenant por empresa
    - Exclusão de produtos inativos
    - Sem corte prévio de 100 produtos
    """

    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Empresa Alpha Ltda",
            nome_fantasia="Alpha PDV",
            cnpj="11111111000101"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Empresa Beta Ltda",
            nome_fantasia="Beta PDV",
            cnpj="22222222000102"
        )

        self.user_a = Usuario.objects.create_user(
            username="user_alpha",
            password="password123",
            empresa=self.empresa_a,
            cargo="OPERADOR"
        )

        self.cat_a = Categoria.objects.create(
            empresa=self.empresa_a,
            nome="Geral"
        )

    # -------------------------------------------------------------------------
    # 1. Normalização de Letras e Acentos
    # -------------------------------------------------------------------------
    def test_normalizacao_primeira_letra(self):
        self.assertEqual(SaleService.normalizar_primeira_letra("Açúcar"), "A")
        self.assertEqual(SaleService.normalizar_primeira_letra("Água Mineral"), "A")
        self.assertEqual(SaleService.normalizar_primeira_letra("À vista"), "A")
        self.assertEqual(SaleService.normalizar_primeira_letra("Âmbar"), "A")
        self.assertEqual(SaleService.normalizar_primeira_letra("Éter"), "E")
        self.assertEqual(SaleService.normalizar_primeira_letra("Ímã"), "I")
        self.assertEqual(SaleService.normalizar_primeira_letra("Óleo"), "O")
        self.assertEqual(SaleService.normalizar_primeira_letra("Úmido"), "U")
        self.assertEqual(SaleService.normalizar_primeira_letra("Çúcar"), "C")
        self.assertEqual(SaleService.normalizar_primeira_letra("51 Pirassununga"), "0-9")
        self.assertEqual(SaleService.normalizar_primeira_letra("3 Corações"), "0-9")
        self.assertEqual(SaleService.normalizar_primeira_letra("@Especial"), "#")
        self.assertEqual(SaleService.normalizar_primeira_letra(""), "#")
        self.assertEqual(SaleService.normalizar_primeira_letra(None), "#")

    # -------------------------------------------------------------------------
    # 2. Letra com mais de 4 produtos, vendas 60d e produtos sem venda
    # -------------------------------------------------------------------------
    def test_letra_mais_de_4_produtos_e_ordenacao_vendas(self):
        """
        Cenário com 6 produtos com a letra 'A':
        - A1 (Açúcar): 50 vendas nos últimos 60 dias
        - A2 (Arroz): 30 vendas nos últimos 60 dias
        - A3 (Água): 10 vendas nos últimos 60 dias
        - A4 (Achocolatado): 0 vendas
        - A5 (Azeite): 0 vendas
        - A6 (Aveia): 0 vendas
        Esperado nos 4 selecionados da letra 'A':
        1. Açúcar (50)
        2. Arroz (30)
        3. Água (10)
        4. Achocolatado (0 - desempate alfabético frente a Aveia e Azeite)
        """
        p_acucar = Produto.objects.create(empresa=self.empresa_a, nome="Açúcar", preco_venda=Decimal('5.00'), codigo_barras="A001")
        p_arroz = Produto.objects.create(empresa=self.empresa_a, nome="Arroz", preco_venda=Decimal('25.00'), codigo_barras="A002")
        p_agua = Produto.objects.create(empresa=self.empresa_a, nome="Água Mineral", preco_venda=Decimal('3.00'), codigo_barras="A003")
        p_acho = Produto.objects.create(empresa=self.empresa_a, nome="Achocolatado", preco_venda=Decimal('8.00'), codigo_barras="A004")
        p_azeite = Produto.objects.create(empresa=self.empresa_a, nome="Azeite", preco_venda=Decimal('35.00'), codigo_barras="A005")
        p_aveia = Produto.objects.create(empresa=self.empresa_a, nome="Aveia", preco_venda=Decimal('6.00'), codigo_barras="A006")

        # Criar venda concluída há 10 dias
        venda = Venda.objects.create(
            empresa=self.empresa_a,
            operador=self.user_a,
            codigo_venda="V-001",
            total=Decimal('500.00'),
            status='CONCLUIDA'
        )
        ItemVenda.objects.create(empresa=self.empresa_a, venda=venda, produto=p_acucar, quantidade=Decimal('50.000'), preco_custo_unitario=Decimal('3.00'), preco_venda_unitario=Decimal('5.00'), subtotal=Decimal('250.00'))
        ItemVenda.objects.create(empresa=self.empresa_a, venda=venda, produto=p_arroz, quantidade=Decimal('30.000'), preco_custo_unitario=Decimal('15.00'), preco_venda_unitario=Decimal('25.00'), subtotal=Decimal('750.00'))
        ItemVenda.objects.create(empresa=self.empresa_a, venda=venda, produto=p_agua, quantidade=Decimal('10.000'), preco_custo_unitario=Decimal('1.50'), preco_venda_unitario=Decimal('3.00'), subtotal=Decimal('30.00'))

        grupos = SaleService.obter_produtos_rapidos_agrupados(self.empresa_a)
        grupo_a = next((g for g in grupos if g['letra'] == 'A'), None)

        self.assertIsNotNone(grupo_a)
        self.assertEqual(len(grupo_a['produtos']), 4)
        nomes_a = [p.nome for p in grupo_a['produtos']]
        self.assertEqual(nomes_a, ["Açúcar", "Arroz", "Água Mineral", "Achocolatado"])

    # -------------------------------------------------------------------------
    # 3. Letra com menos de 4 produtos e letra com exatamente 4 produtos
    # -------------------------------------------------------------------------
    def test_letra_com_menos_e_com_exatamente_4_produtos(self):
        # Letra B: 2 produtos
        p_b1 = Produto.objects.create(empresa=self.empresa_a, nome="Banana", preco_venda=Decimal('4.00'), codigo_barras="B001")
        p_b2 = Produto.objects.create(empresa=self.empresa_a, nome="Batata", preco_venda=Decimal('5.00'), codigo_barras="B002")

        # Letra C: exatamente 4 produtos
        p_c1 = Produto.objects.create(empresa=self.empresa_a, nome="Café", preco_venda=Decimal('15.00'), codigo_barras="C001")
        p_c2 = Produto.objects.create(empresa=self.empresa_a, nome="Cerveja", preco_venda=Decimal('6.00'), codigo_barras="C002")
        p_c3 = Produto.objects.create(empresa=self.empresa_a, nome="Chocolate", preco_venda=Decimal('7.00'), codigo_barras="C003")
        p_c4 = Produto.objects.create(empresa=self.empresa_a, nome="Coca-Cola", preco_venda=Decimal('9.00'), codigo_barras="C004")

        grupos = SaleService.obter_produtos_rapidos_agrupados(self.empresa_a)
        grupo_b = next((g for g in grupos if g['letra'] == 'B'), None)
        grupo_c = next((g for g in grupos if g['letra'] == 'C'), None)

        self.assertEqual(len(grupo_b['produtos']), 2)
        self.assertEqual(len(grupo_c['produtos']), 4)

    # -------------------------------------------------------------------------
    # 4. Desconsiderar Vendas Canceladas, Rascunhos e Vendas Antigas (>60 dias)
    # -------------------------------------------------------------------------
    def test_vendas_canceladas_rascunho_e_fora_60_dias_desconsideradas(self):
        p_d1 = Produto.objects.create(empresa=self.empresa_a, nome="Detergente", preco_venda=Decimal('3.00'), codigo_barras="D001")
        p_d2 = Produto.objects.create(empresa=self.empresa_a, nome="Desinfetante", preco_venda=Decimal('4.00'), codigo_barras="D002")

        # Venda Cancelada com 100 unidades de Detergente
        v_canc = Venda.objects.create(empresa=self.empresa_a, operador=self.user_a, codigo_venda="V-CANC", total=Decimal('300.00'), status='CANCELADA')
        ItemVenda.objects.create(empresa=self.empresa_a, venda=v_canc, produto=p_d1, quantidade=Decimal('100.000'), preco_custo_unitario=Decimal('1.00'), preco_venda_unitario=Decimal('3.00'), subtotal=Decimal('300.00'))

        # Venda Rascunho com 50 unidades de Detergente
        v_rasc = Venda.objects.create(empresa=self.empresa_a, operador=self.user_a, codigo_venda="V-RASC", total=Decimal('150.00'), status='RASCUNHO')
        ItemVenda.objects.create(empresa=self.empresa_a, venda=v_rasc, produto=p_d1, quantidade=Decimal('50.000'), preco_custo_unitario=Decimal('1.00'), preco_venda_unitario=Decimal('3.00'), subtotal=Decimal('150.00'))

        # Venda Concluída há 70 dias (>60d) com 80 unidades de Detergente
        v_antiga = Venda.objects.create(empresa=self.empresa_a, operador=self.user_a, codigo_venda="V-OLD", total=Decimal('240.00'), status='CONCLUIDA')
        # Ajusta data_venda para 70 dias atrás
        Venda.objects.filter(id=v_antiga.id).update(data_venda=timezone.now() - timedelta(days=70))
        ItemVenda.objects.create(empresa=self.empresa_a, venda=v_antiga, produto=p_d1, quantidade=Decimal('80.000'), preco_custo_unitario=Decimal('1.00'), preco_venda_unitario=Decimal('3.00'), subtotal=Decimal('240.00'))

        # Venda Concluída há 5 dias com apenas 2 unidades de Desinfetante
        v_recente = Venda.objects.create(empresa=self.empresa_a, operador=self.user_a, codigo_venda="V-REC", total=Decimal('8.00'), status='CONCLUIDA')
        ItemVenda.objects.create(empresa=self.empresa_a, venda=v_recente, produto=p_d2, quantidade=Decimal('2.000'), preco_custo_unitario=Decimal('2.00'), preco_venda_unitario=Decimal('4.00'), subtotal=Decimal('8.00'))

        grupos = SaleService.obter_produtos_rapidos_agrupados(self.empresa_a)
        grupo_d = next((g for g in grupos if g['letra'] == 'D'), None)

        # Desinfetante (2 vendas válidas em 60d) deve ficar à frente de Detergente (0 vendas válidas em 60d)
        self.assertEqual(grupo_d['produtos'][0].nome, "Desinfetante")
        self.assertEqual(grupo_d['produtos'][1].nome, "Detergente")

    # -------------------------------------------------------------------------
    # 5. Isolamento Multi-tenant e Produtos Inativos
    # -------------------------------------------------------------------------
    def test_multi_tenant_e_produtos_inativos(self):
        # Produto da Empresa B
        p_beta = Produto.objects.create(empresa=self.empresa_b, nome="Abacaxi Beta", preco_venda=Decimal('10.00'), codigo_barras="XB01")
        # Produto Inativo da Empresa A
        p_inativo = Produto.objects.create(empresa=self.empresa_a, nome="Amora Inativa", preco_venda=Decimal('12.00'), codigo_barras="XA01", ativo=False)
        # Produto Ativo da Empresa A
        p_ativo = Produto.objects.create(empresa=self.empresa_a, nome="Amora Ativa", preco_venda=Decimal('12.00'), codigo_barras="XA02", ativo=True)

        grupos = SaleService.obter_produtos_rapidos_agrupados(self.empresa_a)
        grupo_a = next((g for g in grupos if g['letra'] == 'A'), None)

        nomes_a = [p.nome for p in grupo_a['produtos']]
        self.assertIn("Amora Ativa", nomes_a)
        self.assertNotIn("Abacaxi Beta", nomes_a)
        self.assertNotIn("Amora Inativa", nomes_a)

    # -------------------------------------------------------------------------
    # 6. Empresa com mais de 100 produtos
    # -------------------------------------------------------------------------
    def test_empresa_com_mais_de_100_produtos(self):
        """Garante que produtos além da posição 100 não são descartados"""
        # Criar 105 produtos com nomes Z001 a Z105
        produtos_z = [
            Produto(empresa=self.empresa_a, nome=f"Z-Prod-{i:03d}", preco_venda=Decimal('10.00'), codigo_barras=f"Z{i:03d}")
            for i in range(1, 106)
        ]
        Produto.objects.bulk_create(produtos_z)

        # Dar 50 vendas ao último produto criado (Z-Prod-105)
        p_105 = Produto.objects.get(empresa=self.empresa_a, codigo_barras="Z105")
        venda = Venda.objects.create(empresa=self.empresa_a, operador=self.user_a, codigo_venda="V-Z105", total=Decimal('500.00'), status='CONCLUIDA')
        ItemVenda.objects.create(empresa=self.empresa_a, venda=venda, produto=p_105, quantidade=Decimal('50.000'), preco_custo_unitario=Decimal('5.00'), preco_venda_unitario=Decimal('10.00'), subtotal=Decimal('500.00'))

        grupos = SaleService.obter_produtos_rapidos_agrupados(self.empresa_a)
        grupo_z = next((g for g in grupos if g['letra'] == 'Z'), None)

        self.assertIsNotNone(grupo_z)
        self.assertEqual(len(grupo_z['produtos']), 4)
        # Z-Prod-105 deve ser o primeiro da lista devido às 50 vendas
        self.assertEqual(grupo_z['produtos'][0].nome, "Z-Prod-105")
