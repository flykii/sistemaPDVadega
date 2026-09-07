"""
Testes automatizados para a Etapa 15:
- Filtros Dinâmicos e Combinados no Histórico de Vendas (com isolamento multi-tenant).
- PDV: BIP Direto no leitor e feedback não-bloqueante.
"""
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda


class Etapa15HistoricoEFiltrosTestCase(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Alpha LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="11.111.111/0001-11"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="22.222.222/0001-22"
        )

        self.admin_a = Usuario.objects.create_user(
            username='admin_a', password='password123',
            empresa=self.empresa_a, cargo='ADMIN'
        )
        self.operador_a1 = Usuario.objects.create_user(
            username='operador1', password='password123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.operador_a2 = Usuario.objects.create_user(
            username='operador2', password='password123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.admin_b = Usuario.objects.create_user(
            username='admin_b', password='password123',
            empresa=self.empresa_b, cargo='ADMIN'
        )

        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a, nome="Caixa 01", codigo_identificador="CX-01"
        )
        self.sessao_a = CashService.abrir_caixa(
            caixa=self.caixa_a, operador=self.operador_a1,
            saldo_inicial=Decimal('100.00'), nome_operador="Operador 1"
        )

        self.prod_vinho = Produto.objects.create(
            empresa=self.empresa_a, nome="Vinho Malbec 750ml",
            codigo_barras="789000111", preco_custo=Decimal('30.00'),
            preco_venda=Decimal('60.00'), estoque_atual=Decimal('50.000')
        )
        self.prod_cerveja = Produto.objects.create(
            empresa=self.empresa_a, nome="Cerveja Pilsen 600ml",
            codigo_barras="789000222", preco_custo=Decimal('5.00'),
            preco_venda=Decimal('12.00'), estoque_atual=Decimal('100.000')
        )

        self.cli_marcos = Cliente.objects.create(
            empresa=self.empresa_a, nome="Marcos Souza",
            cpf_cnpj="111.222.333-44", telefone="11911112222"
        )
        self.cli_renata = Cliente.objects.create(
            empresa=self.empresa_a, nome="Renata Lima",
            cpf_cnpj="555.666.777-88", telefone="11933334444"
        )

        # Criar Vendas na Empresa A
        # Venda 1: Hoje, Operador 1, PIX, Concluída, Marcos Souza
        self.venda1 = Venda.objects.create(
            empresa=self.empresa_a, operador=self.operador_a1, cliente=self.cli_marcos,
            codigo_venda="VD001", subtotal=Decimal('60.00'), total=Decimal('60.00'),
            status='CONCLUIDA'
        )
        PagamentoVenda.objects.create(empresa=self.empresa_a, venda=self.venda1, forma_pagamento='PIX', valor=Decimal('60.00'))

        # Venda 2: Ontem, Operador 2, Dinheiro, Concluída, Renata Lima
        ontem = timezone.now() - timedelta(days=1)
        self.venda2 = Venda.objects.create(
            empresa=self.empresa_a, operador=self.operador_a2, cliente=self.cli_renata,
            codigo_venda="VD002", subtotal=Decimal('24.00'), total=Decimal('24.00'),
            status='CONCLUIDA'
        )
        Venda.objects.filter(id=self.venda2.id).update(data_venda=ontem)
        PagamentoVenda.objects.create(empresa=self.empresa_a, venda=self.venda2, forma_pagamento='DINHEIRO', valor=Decimal('24.00'))

        # Venda 3: 5 dias atrás, Operador 1, Cartão de Crédito, Cancelada
        cinco_dias = timezone.now() - timedelta(days=5)
        self.venda3 = Venda.objects.create(
            empresa=self.empresa_a, operador=self.operador_a1,
            codigo_venda="VD003", subtotal=Decimal('120.00'), total=Decimal('120.00'),
            status='CANCELADA', motivo_cancelamento="Erro de digitação"
        )
        Venda.objects.filter(id=self.venda3.id).update(data_venda=cinco_dias)
        PagamentoVenda.objects.create(empresa=self.empresa_a, venda=self.venda3, forma_pagamento='CARTAO_CREDITO', valor=Decimal('120.00'))

        # Venda na Empresa B (para isolamento)
        self.venda_b = Venda.objects.create(
            empresa=self.empresa_b, operador=self.admin_b,
            codigo_venda="VDBETA001", subtotal=Decimal('100.00'), total=Decimal('100.00'),
            status='CONCLUIDA'
        )

        self.client = Client()

    def test_01_isolamento_multi_tenant_historico(self):
        """Vendas da Empresa B nunca aparecem no Histórico da Empresa A."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(reverse('vendas_historico'))
        self.assertEqual(resp.status_code, 200)
        
        vendas = resp.context['vendas']
        codigos = [v.codigo_venda for v in vendas]
        self.assertIn("VD001", codigos)
        self.assertIn("VD002", codigos)
        self.assertIn("VD003", codigos)
        self.assertNotIn("VDBETA001", codigos)

    def test_02_filtro_por_periodo_hoje(self):
        """Filtro de período 'hoje' traz somente vendas de hoje."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(reverse('vendas_historico') + '?periodo=hoje')
        self.assertEqual(resp.status_code, 200)
        
        codigos = [v.codigo_venda for v in resp.context['vendas']]
        self.assertIn("VD001", codigos)
        self.assertNotIn("VD002", codigos)
        self.assertNotIn("VD003", codigos)

    def test_03_filtro_por_periodo_ontem(self):
        """Filtro de período 'ontem' traz somente vendas de ontem."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(reverse('vendas_historico') + '?periodo=ontem')
        self.assertEqual(resp.status_code, 200)
        
        codigos = [v.codigo_venda for v in resp.context['vendas']]
        self.assertNotIn("VD001", codigos)
        self.assertIn("VD002", codigos)
        self.assertNotIn("VD003", codigos)

    def test_04_filtro_por_operador(self):
        """Filtro por operador filtra apenas as vendas registradas por ele."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(reverse('vendas_historico') + f'?operador={self.operador_a2.id}')
        self.assertEqual(resp.status_code, 200)
        
        codigos = [v.codigo_venda for v in resp.context['vendas']]
        self.assertEqual(codigos, ["VD002"])

    def test_05_filtro_por_forma_pagamento(self):
        """Filtro por forma de pagamento 'PIX' retorna apenas vendas pagas com PIX."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(reverse('vendas_historico') + '?pagamento=PIX')
        self.assertEqual(resp.status_code, 200)
        
        codigos = [v.codigo_venda for v in resp.context['vendas']]
        self.assertEqual(codigos, ["VD001"])

    def test_06_filtro_por_status_cancelada(self):
        """Filtro por status 'CANCELADA' traz apenas vendas canceladas."""
        self.client.login(username='admin_a', password='password123')
        resp = self.client.get(reverse('vendas_historico') + '?status=CANCELADA')
        self.assertEqual(resp.status_code, 200)
        
        codigos = [v.codigo_venda for v in resp.context['vendas']]
        self.assertEqual(codigos, ["VD003"])

    def test_07_busca_textual_por_cliente_ou_codigo(self):
        """Busca textual por nome de cliente ou código da venda."""
        self.client.login(username='admin_a', password='password123')
        
        # Busca por nome do cliente
        resp1 = self.client.get(reverse('vendas_historico') + '?q=Marcos')
        self.assertEqual(resp1.status_code, 200)
        codigos1 = [v.codigo_venda for v in resp1.context['vendas']]
        self.assertEqual(codigos1, ["VD001"])

        # Busca por código
        resp2 = self.client.get(reverse('vendas_historico') + '?q=VD002')
        self.assertEqual(resp2.status_code, 200)
        codigos2 = [v.codigo_venda for v in resp2.context['vendas']]
        self.assertEqual(codigos2, ["VD002"])

    def test_08_filtros_combinados_simultaneos(self):
        """Combinação de operador + período + status funciona perfeitamente."""
        self.client.login(username='admin_a', password='password123')
        url = reverse('vendas_historico') + f'?operador={self.operador_a1.id}&periodo=ultimos_7_dias&status=CANCELADA'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        
        codigos = [v.codigo_venda for v in resp.context['vendas']]
        self.assertEqual(codigos, ["VD003"])

    def test_09_pdv_interface_elementos_bip(self):
        """Template do PDV renderiza o elemento de feedback não-bloqueante e input com foco."""
        self.client.login(username='operador1', password='password123')
        resp = self.client.get(reverse('pdv_front'))
        self.assertEqual(resp.status_code, 200)
        
        content = resp.content.decode('utf-8')
        self.assertIn('id="barcode-input"', content)
        self.assertIn('id="bip-feedback"', content)
        self.assertIn('buscarEAdicionarProduto', content)
        self.assertIn('mostrarFeedbackBip', content)
