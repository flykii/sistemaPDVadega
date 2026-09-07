"""
Testes automatizados para Exportação JSON Multi-Tenant e Compatibilidade com Importação.
"""
from decimal import Decimal
import json
from django.test import TestCase, Client
from django.urls import reverse

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.compras.models import Fornecedor
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.importacao.services import ExportService, ImportService


class ExportacaoJSONTestCase(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(
            razao_social="Empresa A LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="11.111.111/0001-11"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Empresa B LTDA",
            nome_fantasia="Adega Beta",
            cnpj="22.222.222/0001-22"
        )

        self.admin_a = Usuario.objects.create_user(
            username='admin_a', password='password123',
            empresa=self.empresa_a, cargo='ADMIN'
        )
        self.gerente_a = Usuario.objects.create_user(
            username='gerente_a', password='password123',
            empresa=self.empresa_a, cargo='GERENTE'
        )
        self.operador_a = Usuario.objects.create_user(
            username='operador_a', password='password123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.admin_b = Usuario.objects.create_user(
            username='admin_b', password='password123',
            empresa=self.empresa_b, cargo='ADMIN'
        )

        self.cat_a = Categoria.objects.create(empresa=self.empresa_a, nome="Vinhos Finos")
        self.cat_b = Categoria.objects.create(empresa=self.empresa_b, nome="Cervejas Artesanais")

        self.forn_a = Fornecedor.objects.create(
            empresa=self.empresa_a, razao_social="Vinícola Vale Verde",
            nome_fantasia="Vale Verde", cnpj="12.345.678/0001-90"
        )
        self.forn_b = Fornecedor.objects.create(
            empresa=self.empresa_b, razao_social="Cervejaria Artesanal LTDA",
            nome_fantasia="Cervejaria Beta", cnpj="98.765.432/0001-10"
        )

        self.prod_a1 = Produto.objects.create(
            empresa=self.empresa_a, nome="Vinho Cabernet 750ml",
            codigo_barras="789000111222", sku="VIN-CAB-01",
            categoria=self.cat_a, fornecedor_principal=self.forn_a,
            preco_custo=Decimal('25.00'), preco_venda=Decimal('60.00'),
            estoque_atual=Decimal('50.000'), estoque_minimo=Decimal('10.000')
        )
        self.prod_b1 = Produto.objects.create(
            empresa=self.empresa_b, nome="IPA Especial 500ml",
            codigo_barras="789999888777", sku="IPA-01",
            categoria=self.cat_b, fornecedor_principal=self.forn_b,
            preco_custo=Decimal('10.00'), preco_venda=Decimal('22.00'),
            estoque_atual=Decimal('100.000')
        )

        self.cli_a = Cliente.objects.create(
            empresa=self.empresa_a, nome="João da Silva",
            cpf_cnpj="123.456.789-01", telefone="11999998888",
            limite_credito=Decimal('500.00')
        )
        self.cli_b = Cliente.objects.create(
            empresa=self.empresa_b, nome="Carlos Pereira",
            cpf_cnpj="987.654.321-09", telefone="11988887777"
        )

        # Venda na Empresa A
        self.venda_a = Venda.objects.create(
            empresa=self.empresa_a, operador=self.admin_a, cliente=self.cli_a,
            codigo_venda="VDTESTE001", subtotal=Decimal('120.00'),
            total=Decimal('120.00'), status='CONCLUIDA'
        )
        ItemVenda.objects.create(
            empresa=self.empresa_a,
            venda=self.venda_a, produto=self.prod_a1, quantidade=Decimal('2.000'),
            preco_venda_unitario=Decimal('60.00'), preco_custo_unitario=Decimal('25.00'),
            subtotal=Decimal('120.00')
        )
        PagamentoVenda.objects.create(
            empresa=self.empresa_a,
            venda=self.venda_a, forma_pagamento='PIX', valor=Decimal('120.00')
        )

        self.client = Client()

    def test_01_exportacao_servico_multi_tenant(self):
        """Exportação respeita rigorosamente o isolamento da empresa solicitante."""
        dados_a = ExportService.exportar_dados(self.empresa_a, escopos=['PRODUTOS', 'CATEGORIAS', 'CLIENTES', 'FORNECEDORES', 'VENDAS'])
        
        # Validações estruturais do cabeçalho
        self.assertEqual(dados_a['empresa']['razao_social'], "Empresa A LTDA")
        self.assertEqual(dados_a['empresa']['cnpj'], "11.111.111/0001-11")
        
        # Validar produtos da Empresa A
        produtos_nomes = [p['nome'] for p in dados_a['dados']['produtos']]
        self.assertIn("Vinho Cabernet 750ml", produtos_nomes)
        self.assertNotIn("IPA Especial 500ml", produtos_nomes)

        # Validar categorias
        cat_nomes = [c['nome'] for c in dados_a['dados']['categorias']]
        self.assertIn("Vinhos Finos", cat_nomes)
        self.assertNotIn("Cervejas Artesanais", cat_nomes)

        # Validar clientes
        cli_nomes = [c['nome'] for c in dados_a['dados']['clientes']]
        self.assertIn("João da Silva", cli_nomes)
        self.assertNotIn("Carlos Pereira", cli_nomes)

        # Validar vendas
        vendas_codigos = [v['codigo_venda'] for v in dados_a['dados']['vendas']]
        self.assertIn("VDTESTE001", vendas_codigos)

    def test_02_exportacao_seguranca_dados_sensiveis(self):
        """Exportação não deve conter hashes de senhas, tokens de autenticação ou PINs."""
        dados_a = ExportService.exportar_dados(self.empresa_a)
        json_str = json.dumps(dados_a)
        
        self.assertNotIn("password", json_str.lower())
        self.assertNotIn("pbkdf2", json_str.lower())
        self.assertNotIn("secret", json_str.lower())
        self.assertNotIn("pin", json_str.lower())

    def test_03_exportacao_escopos_selecionados(self):
        """Exportar apenas escopos selecionados."""
        dados_apenas_produtos = ExportService.exportar_dados(self.empresa_a, escopos=['produtos', 'categorias'])
        self.assertIn('produtos', dados_apenas_produtos['dados'])
        self.assertIn('categorias', dados_apenas_produtos['dados'])
        self.assertNotIn('clientes', dados_apenas_produtos['dados'])
        self.assertNotIn('vendas', dados_apenas_produtos['dados'])

    def test_04_view_exportar_permissoes_e_download(self):
        """ADMIN e GERENTE podem baixar exportação JSON; OPERADOR recebe 403."""
        # Operador bloqueado
        self.client.login(username='operador_a', password='password123')
        resp_op = self.client.get(reverse('importacao_exportar'))
        self.assertEqual(resp_op.status_code, 403)

        # Gerente permitido
        self.client.login(username='gerente_a', password='password123')
        resp_gerente = self.client.get(reverse('importacao_exportar') + '?escopo=produtos&escopo=clientes')
        self.assertEqual(resp_gerente.status_code, 200)
        self.assertIn('application/json', resp_gerente['Content-Type'])
        self.assertIn('attachment; filename=', resp_gerente['Content-Disposition'])
        
        conteudo = json.loads(resp_gerente.content.decode('utf-8'))
        self.assertIn('dados', conteudo)
        self.assertEqual(conteudo['versao'], '1.0')
        self.assertEqual(len(conteudo['dados']['produtos']), 1)

    def test_05_compatibilidade_exportacao_com_importador(self):
        """Arquivo exportado é analisado e reconhecido com sucesso pelo analisador do ImportService."""
        dados_exp = ExportService.exportar_dados(self.empresa_a, escopos=['produtos'])
        json_exportado = json.dumps(dados_exp)

        analise = ImportService.analisar_json(json_exportado)
        self.assertTrue(analise['valido'])
        self.assertEqual(analise['total_registros'], 1)
        self.assertEqual(analise['tipo_sugerido'], 'PRODUTOS')
        self.assertEqual(analise['registros_completos'][0]['codigo_barras'], '789000111222')
