import urllib.parse
from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
from apps.usuarios.models import Usuario
from apps.empresas.models import Empresa
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.clientes.models import Fornecedor

class ProdutosFiltrosEdicaoTests(TestCase):
    def setUp(self):
        # 1. Cria empresas com CNPJs distintos
        self.empresa_a = Empresa.objects.create(razao_social="Empresa A LTDA", nome_fantasia="Loja A", cnpj="11111111000111")
        self.empresa_b = Empresa.objects.create(razao_social="Empresa B LTDA", nome_fantasia="Loja B", cnpj="22222222000122")

        # 2. Cria usuarios com cargo ADMIN para as empresas
        self.user_a = Usuario.objects.create_user(
            username='usera',
            password='password123',
            empresa=self.empresa_a,
            cargo='ADMIN'
        )
        self.user_b = Usuario.objects.create_user(
            username='userb',
            password='password123',
            empresa=self.empresa_b,
            cargo='ADMIN'
        )

        # 3. Cria categorias
        self.cat_bebidas_a = Categoria.objects.create(empresa=self.empresa_a, nome="Bebidas", ativo=True)
        self.cat_alimentos_a = Categoria.objects.create(empresa=self.empresa_a, nome="Alimentos", ativo=True)
        self.cat_bebidas_b = Categoria.objects.create(empresa=self.empresa_b, nome="Bebidas B", ativo=True)

        # 4. Cria fornecedor
        self.fornecedor_a = Fornecedor.objects.create(
            empresa=self.empresa_a,
            razao_social="Distribuidora A",
            nome_fantasia="Fornecedor A",
            ativo=True
        )

        # 5. Cria produtos
        self.prod_coca = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Coca Cola 2L",
            codigo_barras="7894900010015",
            sku="COCA-2L",
            descricao="Refrigerante sabor cola 2 litros",
            categoria=self.cat_bebidas_a,
            fornecedor_principal=self.fornecedor_a,
            preco_custo=Decimal('5.50'),
            margem_lucro=Decimal('31.25'),
            preco_venda=Decimal('8.00'),
            estoque_atual=Decimal('20.000'),
            estoque_minimo=Decimal('10.000'),
            estoque_maximo=Decimal('100.000'),
            unidade_medida='UN',
            controle_estoque=True,
            ativo=True
        )

        self.prod_arroz = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Arroz 5kg",
            codigo_barras="7891234567890",
            sku="ARROZ-5KG",
            descricao="Arroz tipo 1 5kg",
            categoria=self.cat_alimentos_a,
            fornecedor_principal=self.fornecedor_a,
            preco_custo=Decimal('20.00'),
            margem_lucro=Decimal('20.00'),
            preco_venda=Decimal('25.00'),
            estoque_atual=Decimal('2.000'),
            estoque_minimo=Decimal('5.000'),
            estoque_maximo=Decimal('50.000'),
            unidade_medida='PCT',
            controle_estoque=True,
            ativo=True
        )

        self.prod_feijao_zerado = Produto.objects.create(
            empresa=self.empresa_a,
            nome="Feijao Preto 1kg",
            codigo_barras="7899876543210",
            sku="FEIJAO-1KG",
            categoria=self.cat_alimentos_a,
            preco_custo=Decimal('6.00'),
            preco_venda=Decimal('9.00'),
            estoque_atual=Decimal('0.000'),
            estoque_minimo=Decimal('5.000'),
            unidade_medida='KG',
            controle_estoque=True,
            ativo=True
        )

        # Produto Empresa B (teste de isolamento)
        self.prod_empresa_b = Produto.objects.create(
            empresa=self.empresa_b,
            nome="Produto Exclusivo B",
            codigo_barras="7890000000001",
            sku="PROD-B",
            preco_custo=Decimal('10.00'),
            preco_venda=Decimal('20.00'),
            estoque_atual=Decimal('50.000'),
            unidade_medida='UN',
            ativo=True
        )

        self.client = Client()

    def test_listagem_filtros_isolamento_empresa(self):
        """Valida que a listagem filtra corretamente e respeita isolamento de tenant."""
        self.client.force_login(self.user_a)

        # Listagem padrao
        response = self.client.get(reverse('produtos_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coca Cola 2L")
        self.assertContains(response, "Arroz 5kg")
        self.assertNotContains(response, "Produto Exclusivo B")

        # Filtro por Categoria Bebidas
        response_cat = self.client.get(reverse('produtos_list') + f'?categoria={self.cat_bebidas_a.id}')
        self.assertContains(response_cat, "Coca Cola 2L")
        self.assertNotContains(response_cat, "Arroz 5kg")

        # Filtro por Estoque Baixo
        response_baixo = self.client.get(reverse('produtos_list') + '?estoque=baixo')
        self.assertContains(response_baixo, "Arroz 5kg")
        self.assertNotContains(response_baixo, "Coca Cola 2L")
        self.assertNotContains(response_baixo, "Feijao Preto 1kg")

        # Filtro por Estoque Zerado
        response_zerado = self.client.get(reverse('produtos_list') + '?estoque=zerado')
        self.assertContains(response_zerado, "Feijao Preto 1kg")
        self.assertNotContains(response_zerado, "Coca Cola 2L")

        # Filtro por Busca de Texto
        response_q = self.client.get(reverse('produtos_list') + '?q=Coca')
        self.assertContains(response_q, "Coca Cola 2L")
        self.assertNotContains(response_q, "Arroz 5kg")

    def test_edicao_carrega_todos_campos_preenchidos(self):
        """Garante que a tela de edicao carrega todos os campos exatamente preenchidos."""
        self.client.force_login(self.user_a)
        response = self.client.get(reverse('produto_editar', args=[self.prod_coca.id]))
        self.assertEqual(response.status_code, 200)

        # Verifica pre-preenchimento
        self.assertContains(response, 'value="Coca Cola 2L"')
        self.assertContains(response, 'value="7894900010015"')
        self.assertContains(response, 'value="COCA-2L"')
        self.assertContains(response, 'Refrigerante sabor cola 2 litros')
        self.assertContains(response, 'value="5.50"')
        self.assertContains(response, 'value="31.25"')
        self.assertContains(response, 'value="8.00"')
        self.assertContains(response, 'value="20.000"')
        self.assertContains(response, 'value="10.000"')
        self.assertContains(response, 'value="100.000"')
        self.assertContains(response, 'selected>Unidade (UN)</option>')

    def test_preservar_filtros_ao_salvar_edicao_com_next(self):
        """Ao editar um produto vindo de uma lista filtrada, salvar deve redirecionar para a URL com os filtros preservados."""
        self.client.force_login(self.user_a)

        orig_url = f"/produtos/?categoria={self.cat_bebidas_a.id}&estoque=baixo&q=Coca"
        encoded_next = urllib.parse.quote(orig_url)
        edit_url = reverse('produto_editar', args=[self.prod_coca.id]) + f"?next={encoded_next}"

        # GET na tela de edicao
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_url'], orig_url)

        # POST para salvar alteracao de preco mantendo outros dados
        post_data = {
            'nome': 'Coca Cola 2L - Edicao Especial',
            'codigo_barras': '7894900010015',
            'sku': 'COCA-2L',
            'descricao': 'Refrigerante sabor cola 2 litros',
            'categoria_id': self.cat_bebidas_a.id,
            'fornecedor_id': self.fornecedor_a.id,
            'preco_custo': '5.50',
            'margem_lucro': '50.00',
            'preco_venda': '8.50',
            'estoque_atual': '20.000',
            'estoque_minimo': '10.000',
            'estoque_maximo': '100.000',
            'unidade_medida': 'UN',
            'controle_estoque': 'on',
            'ativo': 'on',
            'next': orig_url
        }
        post_response = self.client.post(edit_url, post_data)
        
        # Deve redirecionar para a URL de origem preservando exatamente os filtros
        self.assertRedirects(post_response, orig_url)

        # Verifica que alteracao foi persistida no banco
        self.prod_coca.refresh_from_db()
        self.assertEqual(self.prod_coca.nome, 'Coca Cola 2L - Edicao Especial')
        self.assertEqual(self.prod_coca.preco_venda, Decimal('8.50'))

    def test_edicao_sem_mudar_estoque_nao_cria_movimentacao_espuria(self):
        """Ao salvar produto sem alterar estoque, nao deve criar registros espurios em MovimentacaoEstoque."""
        self.client.force_login(self.user_a)

        movs_antes = MovimentacaoEstoque.objects.filter(produto=self.prod_coca).count()

        post_data = {
            'nome': 'Coca Cola 2L',
            'codigo_barras': '7894900010015',
            'sku': 'COCA-2L',
            'descricao': 'Descricao alterada',
            'categoria_id': self.cat_bebidas_a.id,
            'preco_custo': '5.50',
            'margem_lucro': '31.25',
            'preco_venda': '8.00',
            'estoque_atual': '20.000',  # Mesmo valor
            'estoque_minimo': '10.000',
            'estoque_maximo': '100.000',
            'unidade_medida': 'UN',
            'controle_estoque': 'on',
            'ativo': 'on',
        }
        self.client.post(reverse('produto_editar', args=[self.prod_coca.id]), post_data)

        movs_depois = MovimentacaoEstoque.objects.filter(produto=self.prod_coca).count()
        self.assertEqual(movs_antes, movs_depois)

    def test_preservar_filtros_no_ajuste_de_estoque(self):
        """Ao realizar ajuste de estoque vindo de uma lista filtrada, salvar deve redirecionar para a URL de filtros."""
        self.client.force_login(self.user_a)

        orig_url = f"/produtos/?categoria={self.cat_alimentos_a.id}&estoque=baixo"
        encoded_next = urllib.parse.quote(orig_url)
        ajuste_url = reverse('estoque_ajuste', args=[self.prod_arroz.id]) + f"?next={encoded_next}"

        response = self.client.get(ajuste_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['next_url'], orig_url)

        # Realiza ajuste de estoque para NOVO_SALDO 15.000
        post_data = {
            'tipo': 'NOVO_SALDO',
            'novo_saldo': '15.000',
            'motivo': 'Inventario fisico',
            'next': orig_url
        }
        post_response = self.client.post(ajuste_url, post_data)

        self.assertRedirects(post_response, orig_url)

        self.prod_arroz.refresh_from_db()
        self.assertEqual(self.prod_arroz.estoque_atual, Decimal('15.000'))

        # Confirma que foi gerada a movimentacao rastreada
        mov = MovimentacaoEstoque.objects.filter(produto=self.prod_arroz).latest('data_hora')
        self.assertEqual(mov.tipo, 'AJUSTE')
        self.assertEqual(mov.estoque_posterior, Decimal('15.000'))
        self.assertEqual(mov.motivo, 'Inventario fisico')

    def test_inativar_produto_com_next_preserva_filtros(self):
        """Ao excluir/inativar produto a partir de uma listagem filtrada, retorna mantendo a URL."""
        self.client.force_login(self.user_a)

        orig_url = f"/produtos/?categoria={self.cat_alimentos_a.id}"
        encoded_next = urllib.parse.quote(orig_url)
        del_url = reverse('produto_excluir', args=[self.prod_feijao_zerado.id]) + f"?next={encoded_next}"

        response = self.client.post(del_url)
        self.assertRedirects(response, orig_url)

    def test_seguranca_open_redirect_bloqueada(self):
        """Valida que URLs externas maliciosas passadas em 'next' sao descartadas e usam default seguro."""
        self.client.force_login(self.user_a)

        malicious_url = "https://evil-site.com"
        edit_url = reverse('produto_editar', args=[self.prod_coca.id]) + f"?next={malicious_url}"

        response = self.client.get(edit_url)
        # Contexto next_url deve estar limpo
        self.assertEqual(response.context['next_url'], '')
