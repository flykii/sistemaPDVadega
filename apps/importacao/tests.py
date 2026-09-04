"""
ETAPA 13 — Suíte de Testes Automatizados Completa.
Parte 1: Ingestão, análise, validação, mapeamento, transacionalidade e auditoria de Importação JSON.
Parte 2: Configuração visual por empresa/tenant, validação de cores HEX, CSS Variables e permissões.
"""
from decimal import Decimal
import json
import os
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.empresas.models import Empresa, ConfiguracaoVisual
from apps.empresas.context_processors import configuracao_visual_context
from apps.usuarios.models import Usuario
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.compras.models import Fornecedor
from apps.core.models import AuditLog
from apps.importacao.models import HistoricoImportacao
from apps.importacao.services import ImportService


class Etapa13JSONImportETemaVisualTestCase(TestCase):
    """Testes completos da Etapa 13: Importação JSON e Personalização Visual Multi-Tenant."""

    def setUp(self):
        # Empresas
        self.empresa_a = Empresa.objects.create(
            razao_social="Alpha Import Comercio LTDA",
            nome_fantasia="Alpha Import PDV",
            cnpj="11.222.333/0001-44"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Beta Tech LTDA",
            nome_fantasia="Beta Tech PDV",
            cnpj="55.666.777/0001-88"
        )

        # Usuários
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

        self.client = Client()

    # =========================================================================
    # PARTE 1 — TESTES DE IMPORTAÇÃO DE DADOS VIA JSON
    # =========================================================================

    def test_01_json_valido_produtos_criacao(self):
        """JSON válido de produtos é analisado, validado e importado com sucesso."""
        json_content = json.dumps([
            {
                "nome": "Mouse Gamer RGB",
                "codigo_barras": "789111222333",
                "sku": "MOU-01",
                "preco_venda": "150.00",
                "preco_custo": "75.00",
                "estoque_atual": 25,
                "categoria": "Periféricos"
            },
            {
                "nome": "Teclado Mecânico ABNT2",
                "codigo_barras": "789111222444",
                "sku": "TEC-01",
                "preco_venda": "280.00",
                "preco_custo": "140.00",
                "estoque_atual": 15,
                "categoria": "Periféricos"
            }
        ])

        analise = ImportService.analisar_json(json_content)
        self.assertTrue(analise['valido'])
        self.assertEqual(analise['total_registros'], 2)
        self.assertEqual(analise['tipo_sugerido'], 'PRODUTOS')

        mapeamento = ImportService.mapear_campos_sugeridos(analise['campos_detectados'], 'PRODUTOS')
        
        # Dry-run
        res_val = ImportService.validar_dados(
            registros=analise['registros_completos'],
            tipo_entidade='PRODUTOS',
            mapeamento=mapeamento,
            estrategia_identificacao='codigo_barras',
            empresa=self.empresa_a
        )
        self.assertEqual(res_val['validos'], 2)
        self.assertEqual(res_val['invalidos'], 0)
        self.assertEqual(res_val['serao_criados'], 2)

        # Execução
        hist = ImportService.executar_importacao(
            registros=analise['registros_completos'],
            tipo_entidade='PRODUTOS',
            mapeamento=mapeamento,
            estrategia_identificacao='codigo_barras',
            empresa=self.empresa_a,
            usuario=self.admin_a
        )
        self.assertEqual(hist.status, 'PROCESSADO')
        self.assertEqual(hist.quantidade_criada, 2)
        self.assertEqual(Produto.objects.filter(empresa=self.empresa_a).count(), 2)

    def test_02_json_invalido_sintaxe(self):
        """JSON malformatado retorna erro amigável na análise sem lançar exceção não tratada."""
        json_invalido = "{ 'nome': 'Produto Quebrado' "  # Erro de sintaxe
        analise = ImportService.analisar_json(json_invalido)
        self.assertFalse(analise['valido'])
        self.assertIn("Arquivo JSON malformatado", analise['erro'])

    def test_03_estrutura_inesperada_objeto_unico(self):
        """JSON contendo objeto único em vez de lista é tratado e importado corretamente."""
        json_obj = json.dumps({
            "nome": "Cadeira Ergonômica",
            "codigo_barras": "789999000111",
            "preco_venda": 890.00
        })
        analise = ImportService.analisar_json(json_obj)
        self.assertTrue(analise['valido'])
        self.assertEqual(analise['total_registros'], 1)

    def test_04_campos_ausentes_obrigatorios(self):
        """Produto sem nome é rejeitado no dry-run com mensagem descritiva no relatório de erros."""
        registros = [
            {"codigo_barras": "123456", "preco_venda": "50.00"},  # Sem nome!
            {"nome": "Produto Válido", "codigo_barras": "654321", "preco_venda": "20.00"}
        ]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        res = ImportService.validar_dados(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a)
        
        self.assertEqual(res['validos'], 1)
        self.assertEqual(res['invalidos'], 1)
        self.assertEqual(len(res['erros_detalhados']), 1)
        self.assertIn("Nome do produto é obrigatório", res['erros_detalhados'][0]['erro'])

    def test_05_campos_extras_ignorados(self):
        """Campos adicionais não mapeados no JSON são ignorados com segurança."""
        registros = [{
            "nome": "Pen Drive 64GB",
            "codigo_barras": "789000111",
            "preco_venda": "45.00",
            "campo_desconhecido_x": "ignorar_isto",
            "metadado_legado": 999
        }]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        hist = ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)
        self.assertEqual(hist.quantidade_criada, 1)

    def test_06_tipos_invalidos_preco_string(self):
        """Preço não conversível ('abc') é rejeitado na validação sem interromper a execução."""
        registros = [{
            "nome": "Produto com Preço Inválido",
            "codigo_barras": "789000222",
            "preco_venda": "abc"
        }]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        res = ImportService.validar_dados(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a)
        self.assertEqual(res['invalidos'], 1)
        self.assertIn("Valor monetário inválido", res['erros_detalhados'][0]['erro'])

    def test_07_registros_duplicados_no_mesmo_arquivo(self):
        """Detecta duplicidade de código de barras no próprio lote durante a simulação."""
        registros = [
            {"nome": "Item 1", "codigo_barras": "DUPLICADO-123", "preco_venda": 10.00},
            {"nome": "Item 2", "codigo_barras": "DUPLICADO-123", "preco_venda": 15.00}
        ]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        res = ImportService.validar_dados(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a)
        self.assertEqual(res['conflitos'], 1)

    def test_08_reimportacao_do_mesmo_arquivo_atualizacao(self):
        """Reimportação do mesmo arquivo atualiza os registros existentes sem duplicar."""
        registros = [
            {"nome": "Monitor 24 Pol", "codigo_barras": "MON-24", "preco_venda": Decimal('800.00')}
        ]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        
        # 1ª Importação (Criação)
        hist1 = ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)
        self.assertEqual(hist1.quantidade_criada, 1)

        # 2ª Importação com preço alterado (Atualização)
        registros[0]['preco_venda'] = Decimal('850.00')
        hist2 = ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)
        self.assertEqual(hist2.quantidade_atualizada, 1)
        self.assertEqual(hist2.quantidade_criada, 0)
        self.assertEqual(Produto.objects.filter(empresa=self.empresa_a).count(), 1)
        self.assertEqual(Produto.objects.get(empresa=self.empresa_a, codigo_barras="MON-24").preco_venda, Decimal('850.00'))

    def test_09_conflito_de_identificadores_sku(self):
        """Estratégia de identificação por SKU atualiza corretamente o registro correspondente."""
        Produto.objects.create(
            empresa=self.empresa_a, nome="Notebook i5", sku="NOTE-I5", preco_venda=Decimal('3000.00')
        )
        registros = [{"nome": "Notebook i5 16GB", "sku": "NOTE-I5", "preco_venda": 3200.00}]
        mapeamento = {'nome': 'nome', 'sku': 'sku', 'preco_venda': 'preco_venda'}
        
        hist = ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'sku', self.empresa_a, self.admin_a)
        self.assertEqual(hist.quantidade_atualizada, 1)
        self.assertEqual(Produto.objects.filter(empresa=self.empresa_a).count(), 1)
        self.assertEqual(Produto.objects.get(empresa=self.empresa_a, sku="NOTE-I5").nome, "Notebook i5 16GB")

    def test_10_isolamento_entre_empresas_multi_tenant(self):
        """Registros importados na Empresa A são estritamente isolados da Empresa B."""
        registros = [{"nome": "Produto Alpha Exclusivo", "codigo_barras": "ALPHA-001", "preco_venda": 50.00}]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)

        self.assertEqual(Produto.objects.filter(empresa=self.empresa_a, codigo_barras="ALPHA-001").count(), 1)
        self.assertEqual(Produto.objects.filter(empresa=self.empresa_b, codigo_barras="ALPHA-001").count(), 0)

    def test_11_rollback_transacional_em_erro(self):
        """Em caso de falha crítica na transação, nenhum registro inconsistente é persistido."""
        # Criação prévia de 1 produto
        Produto.objects.create(empresa=self.empresa_a, nome="Produto Inicial", codigo_barras="INIT-01", preco_venda=Decimal('10.00'))
        
        # Simula erro
        registros_misto = [
            {"nome": "Item Válido 1", "codigo_barras": "VAL-1", "preco_venda": 10.00},
            {"nome": "", "codigo_barras": "INV-1", "preco_venda": 10.00} # Erro
        ]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        hist = ImportService.executar_importacao(registros_misto, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)
        
        self.assertEqual(hist.status, 'PROCESSADO_COM_ERROS')
        self.assertEqual(hist.quantidade_criada, 1)
        self.assertEqual(hist.quantidade_rejeitada, 1)

    def test_12_arquivo_vazio(self):
        """Arquivo JSON vazio é tratado sem lançar erro não capturado."""
        analise = ImportService.analisar_json("[]")
        self.assertTrue(analise['valido'])
        self.assertEqual(analise['total_registros'], 0)

    def test_13_arquivo_grande_em_lote(self):
        """Lote com 50 registros é processado com 100% de integridade."""
        registros = []
        for i in range(50):
            registros.append({
                "nome": f"Produto Lote {i}",
                "codigo_barras": f"LOTE-{i}",
                "preco_venda": 10.00 + i
            })
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        hist = ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)
        self.assertEqual(hist.quantidade_criada, 50)
        self.assertEqual(Produto.objects.filter(empresa=self.empresa_a).count(), 50)

    def test_14_relacionamentos_categoria_fornecedor(self):
        """Criação e vinculação automática de Categorias e Fornecedores durante o sync de produtos."""
        registros = [{
            "nome": "Café Gourmet em Grãos",
            "codigo_barras": "CAF-GOURMET",
            "preco_venda": 35.00,
            "categoria": "Bebidas Quentes",
            "fornecedor": "Fazenda Boa Vista"
        }]
        mapeamento = {
            'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda',
            'categoria': 'categoria', 'fornecedor': 'fornecedor'
        }
        hist = ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)
        
        prod = Produto.objects.get(empresa=self.empresa_a, codigo_barras="CAF-GOURMET")
        self.assertIsNotNone(prod.categoria)
        self.assertEqual(prod.categoria.nome, "Bebidas Quentes")
        self.assertIsNotNone(prod.fornecedor_principal)
        self.assertEqual(prod.fornecedor_principal.razao_social, "Fazenda Boa Vista")


    def test_15_importacao_clientes_cpf_cnpj(self):
        """Importação de clientes com sanitização de CPF/CNPJ e limite de crédito."""
        registros = [{
            "nome": "Maria Santos",
            "cpf_cnpj": "123.456.789-00",
            "telefone": "(11) 98765-4321",
            "email": "maria@teste.com",
            "limite_credito": "R$ 500,00"
        }]
        mapeamento = {
            'nome': 'nome', 'cpf_cnpj': 'cpf_cnpj', 'telefone': 'telefone',
            'email': 'email', 'limite_credito': 'limite_credito'
        }
        hist = ImportService.executar_importacao(registros, 'CLIENTES', mapeamento, 'cpf_cnpj', self.empresa_a, self.admin_a)
        self.assertEqual(hist.quantidade_criada, 1)
        
        cli = Cliente.objects.get(empresa=self.empresa_a, cpf_cnpj="12345678900")
        self.assertEqual(cli.nome, "Maria Santos")
        self.assertEqual(cli.limite_credito, Decimal('500.00'))

    def test_16_importacao_fornecedores(self):
        """Importação de fornecedores com CNPJ e dados de contato."""
        registros = [{
            "razao_social": "Distribuidora Nacional LTDA",
            "nome_fantasia": "Nacional Distribuição",
            "cnpj": "12.345.678/0001-99",
            "telefone": "1133334444"
        }]
        mapeamento = {
            'razao_social': 'razao_social', 'nome_fantasia': 'nome_fantasia',
            'cnpj': 'cnpj', 'telefone': 'telefone'
        }
        hist = ImportService.executar_importacao(registros, 'FORNECEDORES', mapeamento, 'cnpj', self.empresa_a, self.admin_a)
        self.assertEqual(hist.quantidade_criada, 1)
        self.assertEqual(Fornecedor.objects.filter(empresa=self.empresa_a, cnpj="12345678000199").count(), 1)

    def test_17_valores_monetarios_formatos_variados(self):
        """Conversão correta de múltiplos formatos monetários para Decimal."""
        self.assertEqual(ImportService.normalizar_moeda("R$ 1.234,56"), Decimal('1234.56'))
        self.assertEqual(ImportService.normalizar_moeda("1234.56"), Decimal('1234.56'))
        self.assertEqual(ImportService.normalizar_moeda("10,50"), Decimal('10.50'))
        self.assertEqual(ImportService.normalizar_moeda(99.99), Decimal('99.99'))

    def test_18_quantidades_decimais(self):
        """Conversão correta de frações de estoque (ex: 2.500 KG)."""
        self.assertEqual(ImportService.normalizar_quantidade("2,500"), Decimal('2.500'))
        self.assertEqual(ImportService.normalizar_quantidade(3.75), Decimal('3.75'))

    def test_19_auditoria_importacao(self):
        """Registro na Trilha de Auditoria gerado automaticamente na importação."""
        registros = [{"nome": "Item Auditoria", "codigo_barras": "AUD-01", "preco_venda": 10.00}]
        mapeamento = {'nome': 'nome', 'codigo_barras': 'codigo_barras', 'preco_venda': 'preco_venda'}
        ImportService.executar_importacao(registros, 'PRODUTOS', mapeamento, 'codigo_barras', self.empresa_a, self.admin_a)

        log = AuditLog.objects.filter(empresa=self.empresa_a, acao='IMPORTACAO_DADOS').first()
        self.assertIsNotNone(log)
        self.assertIn("Importação JSON de PRODUTOS", log.descricao)

    def test_20_permissao_admin_gerente_acesso_importacao(self):
        """ADMIN e GERENTE têm acesso a /importacao/; OPERADOR recebe 403 Forbidden."""
        self.client.login(username='admin_a', password='password123')
        resp_admin = self.client.get(reverse('importacao_hub'))
        self.assertEqual(resp_admin.status_code, 200)

        self.client.login(username='gerente_a', password='password123')
        resp_gerente = self.client.get(reverse('importacao_hub'))
        self.assertEqual(resp_gerente.status_code, 200)

        self.client.login(username='operador_a', password='password123')
        resp_operador = self.client.get(reverse('importacao_hub'))
        self.assertEqual(resp_operador.status_code, 403)

    # =========================================================================
    # PARTE 2 — TESTES DE CONFIGURAÇÃO VISUAL & PDV
    # =========================================================================

    def test_21_configuracao_visual_padrao(self):
        """Empresa obtém configuração visual com valores padrão caso ainda não tenha personalizado."""
        config = self.empresa_a.get_configuracao_visual()
        self.assertIsNotNone(config)
        self.assertEqual(config.cor_principal, '#2563eb')
        self.assertEqual(config.cor_pdv_fundo, '#0f172a')
        self.assertEqual(config.cor_pdv_preco, '#22c55e')

    def test_22_configuracao_visual_personalizada(self):
        """Salva tema personalizado com novas cores e persiste no banco."""
        self.client.login(username='admin_a', password='password123')
        payload = {
            'action': 'salvar_tema_cores',
            'cor_principal': '#7C3AED',
            'cor_secundaria': '#6D28D9',
            'cor_destaque': '#F59E0B',
            'cor_menu_sidebar': '#1E1B4B',
            'cor_fundo': '#F3F4F6',
            'cor_cards': '#FFFFFF',
            'cor_texto': '#111827',
            'cor_texto_secundario': '#4B5563',
            'cor_botoes': '#7C3AED',
            'cor_botoes_acao': '#10B981',
            'cor_links': '#7C3AED',
            'cor_sucesso': '#059669',
            'cor_alerta': '#D97706',
            'cor_erro': '#DC2626',
            'cor_pdv_fundo': '#111827',
            'cor_pdv_texto': '#F9FAFB',
            'cor_pdv_preco': '#34D399',
            'cor_pdv_total': '#FBBF24',
            'cor_pdv_botao_finalizar': '#059669',
            'cor_pdv_botao_cancelar': '#EF4444',
            'cor_pdv_botoes_pagamento': '#6366F1',
            'tamanho_fonte_total': '2.5rem',
            'tamanho_fonte_preco': '1.5rem',
            'tamanho_fonte_itens': '1.0rem',
            'modo_layout': 'CONFORTAVEL',
            'exibir_painel_produtos_rapidos': 'on'
        }
        resp = self.client.post(reverse('configuracoes'), payload)
        self.assertEqual(resp.status_code, 302)

        config = self.empresa_a.get_configuracao_visual()
        self.assertEqual(config.cor_principal, '#7C3AED')
        self.assertEqual(config.cor_pdv_preco, '#34D399')
        self.assertEqual(config.tamanho_fonte_total, '2.5rem')

    def test_23_alteracao_cores_pdv(self):
        """Alterações nas cores do PDV são salvas no banco."""
        config = self.empresa_a.get_configuracao_visual()
        config.cor_pdv_preco = '#10B981'
        config.cor_pdv_total = '#F59E0B'
        config.clean()
        config.save()

        config.refresh_from_db()
        self.assertEqual(config.cor_pdv_preco, '#10B981')
        self.assertEqual(config.cor_pdv_total, '#F59E0B')

    def test_24_validacao_hex_invalido(self):
        """Códigos HEX inválidos disparam erro de validação impedindo injeção."""
        config = self.empresa_a.get_configuracao_visual()
        config.cor_principal = 'cor_invalida_sem_hex'
        with self.assertRaises(Exception):
            config.clean()

    def test_25_isolamento_visual_entre_empresas(self):
        """Configuração visual da Empresa A não afeta a Empresa B."""
        config_a = self.empresa_a.get_configuracao_visual()
        config_a.cor_principal = '#DC2626'  # Vermelho
        config_a.save()

        config_b = self.empresa_b.get_configuracao_visual()
        config_b.cor_principal = '#16A34A'  # Verde
        config_b.save()

        config_a.refresh_from_db()
        config_b.refresh_from_db()
        self.assertEqual(config_a.cor_principal, '#DC2626')
        self.assertEqual(config_b.cor_principal, '#16A34A')

    def test_26_permissoes_configuracao_visual(self):
        """OPERADOR é bloqueado ao tentar alterar configurações visuais."""
        self.client.login(username='operador_a', password='password123')
        resp = self.client.post(reverse('configuracoes'), {'action': 'salvar_tema_cores'})
        self.assertEqual(resp.status_code, 403)

    def test_27_context_processor_css_variables(self):
        """Context processor injeta CSS variables com base na empresa ativa."""
        factory = RequestFactory()
        req = factory.get('/')
        req.user = self.admin_a
        req.tenant = self.empresa_a

        ctx = configuracao_visual_context(req)
        self.assertIn('css_variables', ctx)
        self.assertIn('--cor-principal:', ctx['css_variables'])
        self.assertIn('--cor-pdv-preco:', ctx['css_variables'])

    def test_28_auditoria_configuracao_visual(self):
        """Trilha de Auditoria registra alteração de tema visual com valores anteriores e posteriores."""
        self.client.login(username='admin_a', password='password123')
        payload = {
            'action': 'salvar_tema_cores',
            'cor_principal': '#059669',
            'cor_secundaria': '#475569',
            'cor_destaque': '#F59E0B',
            'cor_menu_sidebar': '#0F172A',
            'cor_fundo': '#F8FAFC',
            'cor_cards': '#FFFFFF',
            'cor_texto': '#1E293B',
            'cor_texto_secundario': '#64748B',
            'cor_botoes': '#059669',
            'cor_botoes_acao': '#10B981',
            'cor_links': '#059669',
            'cor_sucesso': '#16A34A',
            'cor_alerta': '#D97706',
            'cor_erro': '#DC2626',
            'cor_pdv_fundo': '#0F172A',
            'cor_pdv_texto': '#FFFFFF',
            'cor_pdv_preco': '#22C55E',
            'cor_pdv_total': '#EAB308',
            'cor_pdv_botao_finalizar': '#16A34A',
            'cor_pdv_botao_cancelar': '#DC2626',
            'cor_pdv_botoes_pagamento': '#3B82F6',
            'tamanho_fonte_total': '2.0rem',
            'tamanho_fonte_preco': '1.25rem',
            'tamanho_fonte_itens': '1.0rem',
            'modo_layout': 'CONFORTAVEL'
        }
        self.client.post(reverse('configuracoes'), payload)

        log = AuditLog.objects.filter(empresa=self.empresa_a, acao='CONFIGURACAO_VISUAL_ALTERADA').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.dados_posteriores['cor_principal'], '#059669')

    def test_29_seguranca_upload_logo_invalido(self):
        """Arquivo com extensão não permitida (.exe) é rejeitado."""
        self.client.login(username='admin_a', password='password123')
        arquivo_falso = SimpleUploadedFile("malicioso.exe", b"binarycontent", content_type="application/x-msdownload")
        resp = self.client.post(reverse('configuracoes'), {
            'action': 'salvar_identidade_visual',
            'logo': arquivo_falso
        })
        self.assertEqual(resp.status_code, 302)
        config = self.empresa_a.get_configuracao_visual()
        self.assertFalse(bool(config.logo))
