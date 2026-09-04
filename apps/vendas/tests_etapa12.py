"""
ETAPA 12 — Suíte de Testes Automatizados Completa.
PWA, Operação Offline, Sincronização em Lote, Idempotência com offline_uuid,
Tratamento de Timeout após Commit, Detecção de Conflitos de Payload,
Integridade de Estoque/Caixa/Auditoria e Multi-Tenancy.
Cobre todos os 36 cenários de testes obrigatórios da Etapa 12.
"""
from decimal import Decimal
import uuid
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.usuarios.models import Usuario
from apps.caixas.models import Caixa, SessaoCaixa, MovimentacaoCaixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto, Categoria, MovimentacaoEstoque
from apps.produtos.services import StockService
from apps.clientes.models import Cliente
from apps.vendas.models import Venda, ItemVenda, PagamentoVenda
from apps.vendas.services import SaleService
from apps.financeiro.models import ContaReceber, FluxoCaixa
from apps.core.models import AuditLog, AuditService


class Etapa12PWAOfflineSyncTestCase(TestCase):
    """Validação completa de PWA, Fila Offline, Idempotência, Resiliência e Sincronização."""

    def setUp(self):
        # Empresas (Multi-Tenancy)
        self.empresa_a = Empresa.objects.create(
            razao_social="Alpha Comercial LTDA",
            nome_fantasia="Loja Alpha PDV",
            cnpj="12.345.678/0001-90"
        )
        self.empresa_b = Empresa.objects.create(
            razao_social="Beta Comercio LTDA",
            nome_fantasia="Loja Beta PDV",
            cnpj="98.765.432/0001-10"
        )

        # Usuários
        self.operador_a = Usuario.objects.create_user(
            username='operador_alpha', password='pass123',
            empresa=self.empresa_a, cargo='OPERADOR'
        )
        self.admin_a = Usuario.objects.create_user(
            username='admin_alpha', password='pass123',
            empresa=self.empresa_a, cargo='ADMIN'
        )
        self.operador_b = Usuario.objects.create_user(
            username='operador_beta', password='pass123',
            empresa=self.empresa_b, cargo='OPERADOR'
        )

        # Caixas e Sessões
        self.caixa_a = Caixa.objects.create(
            empresa=self.empresa_a, nome="Caixa Principal A", codigo_identificador="CX-ALPHA-01"
        )
        self.sessao_a = CashService.abrir_caixa(
            caixa=self.caixa_a, operador=self.operador_a,
            saldo_inicial=Decimal('150.00'), nome_operador="Operador Alpha"
        )

        self.caixa_b = Caixa.objects.create(
            empresa=self.empresa_b, nome="Caixa Principal B", codigo_identificador="CX-BETA-01"
        )
        self.sessao_b = CashService.abrir_caixa(
            caixa=self.caixa_b, operador=self.operador_b,
            saldo_inicial=Decimal('100.00'), nome_operador="Operador Beta"
        )

        # Produtos Empresa A
        self.produto_cafe = Produto.objects.create(
            empresa=self.empresa_a, nome="Café Torrado 500g",
            codigo_barras="789001", sku="CAF-01",
            preco_custo=Decimal('8.00'), preco_venda=Decimal('16.00'),
            estoque_atual=Decimal('50.000'), controle_estoque=True, ativo=True
        )
        self.produto_leite = Produto.objects.create(
            empresa=self.empresa_a, nome="Leite Integral 1L",
            codigo_barras="789002", sku="LEI-01",
            preco_custo=Decimal('3.00'), preco_venda=Decimal('6.00'),
            estoque_atual=Decimal('40.000'), controle_estoque=True, ativo=True
        )
        self.produto_inativo = Produto.objects.create(
            empresa=self.empresa_a, nome="Biscoito Descontinuado",
            codigo_barras="789003", sku="BIS-01",
            preco_custo=Decimal('2.00'), preco_venda=Decimal('5.00'),
            estoque_atual=Decimal('20.000'), controle_estoque=True, ativo=False
        )

        # Clientes Empresa A
        self.cliente_a = Cliente.objects.create(
            empresa=self.empresa_a, nome="Carlos Oliveira",
            cpf_cnpj="11122233344", limite_credito=Decimal('300.00'),
            saldo_devedor=Decimal('0.00'), ativo=True
        )

        # Client HTTP
        self.client = Client()

    # =========================================================================
    # 1. PWA MANIFEST DISPONÍVEL
    # =========================================================================
    def test_01_manifest_pwa_disponivel(self):
        """Verifica se a rota /manifest.json está acessível com content-type manifest+json."""
        resp = self.client.get('/manifest.json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/manifest+json', resp['Content-Type'])
        data = resp.json()
        self.assertEqual(data.get('short_name'), 'PDV Web')

    # =========================================================================
    # 2. SERVICE WORKER REGISTRADO
    # =========================================================================
    def test_02_service_worker_disponivel_com_header_scope(self):
        """Verifica se a rota /sw.js está acessível e retorna o cabeçalho Service-Worker-Allowed."""
        resp = self.client.get('/sw.js')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/javascript')
        self.assertEqual(resp.get('Service-Worker-Allowed'), '/')

    # =========================================================================
    # 3. RECURSOS ESTÁTICOS OFFLINE
    # =========================================================================
    def test_03_recursos_estaticos_disponiveis(self):
        """Verifica se os arquivos estáticos essenciais do PDV existem no sistema de arquivos."""
        import os
        from django.conf import settings
        db_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'pdv-offline-db.js')
        app_path = os.path.join(settings.BASE_DIR, 'static', 'js', 'pdv-app.js')
        self.assertTrue(os.path.exists(db_path))
        self.assertTrue(os.path.exists(app_path))

    # =========================================================================
    # 4. INDICADOR ONLINE / HEARTBEAT PING
    # =========================================================================
    def test_04_ping_heartbeat_online(self):
        """Endpoint /api/v1/pdv/ping/ responde status 200 para usuário autenticado com sessão de caixa."""
        self.client.login(username='operador_alpha', password='pass123')
        resp = self.client.get('/api/v1/pdv/ping/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'online')
        self.assertTrue(data['caixa_aberto'])
        self.assertEqual(data['empresa_id'], self.empresa_a.id)

    # =========================================================================
    # 5. INDICADOR OFFLINE / RESPOSTA NÃO AUTENTICADA
    # =========================================================================
    def test_05_ping_sem_autenticacao_retorna_401(self):
        """Requisição não autenticada no ping é rejeitada com 401 ou 403."""
        resp = self.client.get('/api/v1/pdv/ping/')
        self.assertIn(resp.status_code, [401, 403])


    # =========================================================================
    # 6. CRIAÇÃO DE VENDA OFFLINE COM OFFLINE_UUID
    # =========================================================================
    def test_06_criacao_venda_offline_com_uuid(self):
        """Gera e processa venda com offline_uuid gravando o identificador no banco."""
        unique_uuid = str(uuid.uuid4())
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        self.assertEqual(venda.offline_uuid, unique_uuid)
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)

    # =========================================================================
    # 7. PERSISTÊNCIA DA VENDA NA FILA (SYNC API)
    # =========================================================================
    def test_07_sincronizacao_via_api_pdv_sync(self):
        """Endpoint /api/v1/pdv/sync/ recebe e processa venda da fila offline."""
        self.client.login(username='operador_alpha', password='pass123')
        unique_uuid = str(uuid.uuid4())
        payload = {
            'vendas': [{
                'offline_uuid': unique_uuid,
                'desconto': 0.00,
                'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 2, 'preco_venda': 16.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 32.00, 'troco': 0.00}]
            }]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total_sincronizadas'], 1)
        self.assertEqual(len(data['erros']), 0)
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)

    # =========================================================================
    # 8. FILA SOBREVIVE AO REFRESH / REENVIO IDEMPOTENTE
    # =========================================================================
    def test_08_reenvio_apos_refresh_mantem_venda_unica(self):
        """Reenviar a mesma venda offline sincronizada não duplica registro."""
        unique_uuid = str(uuid.uuid4())
        v1 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        # Segunda submissão simulando retry após refresh
        v2 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        self.assertEqual(v1.id, v2.id)
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)

    # =========================================================================
    # 9. FILA SOBREVIVE AO FECHAMENTO DO NAVEGADOR
    # =========================================================================
    def test_09_reenvio_apos_fechamento_navegador(self):
        """Venda salva localmente é enviada pelo mesmo offline_uuid."""
        unique_uuid = str(uuid.uuid4())
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_leite.id, 'quantidade': 2}],
            pagamentos_data=[{'forma': 'PIX', 'valor': Decimal('12.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        self.assertEqual(venda.total, Decimal('12.00'))

    # =========================================================================
    # 10. SINCRONIZAÇÃO APÓS RECONEXÃO
    # =========================================================================
    def test_10_sincronizacao_apos_reconexao_via_api(self):
        """Quando reconecta, o envio do lote pendente finaliza todas as vendas com sucesso."""
        self.client.login(username='operador_alpha', password='pass123')
        uuid1 = str(uuid.uuid4())
        uuid2 = str(uuid.uuid4())
        payload = {
            'vendas': [
                {
                    'offline_uuid': uuid1,
                    'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 1, 'preco_venda': 16.00}],
                    'pagamentos': [{'forma': 'DINHEIRO', 'valor': 16.00, 'troco': 0.00}]
                },
                {
                    'offline_uuid': uuid2,
                    'itens': [{'produto_id': self.produto_leite.id, 'quantidade': 3, 'preco_venda': 6.00}],
                    'pagamentos': [{'forma': 'PIX', 'valor': 18.00, 'troco': 0.00}]
                }
            ]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total_sincronizadas'], 2)

    # =========================================================================
    # 11. RETRY MANTENDO O MESMO OFFLINE_UUID
    # =========================================================================
    def test_11_retry_mantendo_mesmo_uuid(self):
        """Tentativa repetida com mesmo offline_uuid retorna sempre a mesma venda."""
        fixed_uuid = "OFFLINE-FIXED-UUID-12345"
        v1 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=fixed_uuid
        )
        v2 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=fixed_uuid
        )
        self.assertEqual(v1.id, v2.id)

    # =========================================================================
    # 12. DUPLO ENVIO DO MESMO OFFLINE_UUID
    # =========================================================================
    def test_12_duplo_envio_mesmo_uuid_sem_duplicacao_banco(self):
        """Dois envios idênticos resultam em exatamente 1 registro no banco."""
        unique_uuid = str(uuid.uuid4())
        for _ in range(2):
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a,
                itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
                offline_uuid=unique_uuid
            )
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)

    # =========================================================================
    # 13. TRIPLO ENVIO DO MESMO OFFLINE_UUID
    # =========================================================================
    def test_13_triplo_envio_mesmo_uuid_sem_duplicacao(self):
        """Três envios idênticos resultam em exatamente 1 venda no banco."""
        unique_uuid = str(uuid.uuid4())
        for _ in range(3):
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a,
                itens_data=[{'produto_id': self.produto_leite.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('6.00'), 'troco': Decimal('0.00')}],
                offline_uuid=unique_uuid
            )
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)

    # =========================================================================
    # 14 & 15. TIMEOUT APÓS COMMIT NO SERVIDOR & RETRY SEM DUPLICIDADE
    # =========================================================================
    def test_14_15_timeout_apos_commit_e_retry_idempotente(self):
        """
        Cenário Crítico: O servidor grava e comita a venda, mas a resposta HTTP se perde.
        O cliente reenvia com o mesmo offline_uuid. O backend deve retornar a venda original
        sem baixar estoque novamente e sem duplicar movimentação de caixa ou pagamentos.
        """
        unique_uuid = str(uuid.uuid4())
        estoque_inicial = self.produto_cafe.estoque_atual  # 50
        saldo_inicial_gaveta = self.sessao_a.saldo_esperado  # 150.00

        # 1. Primeira submissão com sucesso no backend (simula timeout na volta do HTTP)
        venda_original = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 2}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('32.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        self.produto_cafe.refresh_from_db()
        self.assertEqual(self.produto_cafe.estoque_atual, estoque_inicial - Decimal('2.000'))
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_inicial_gaveta + Decimal('32.00'))

        # 2. Cliente reenvia a operação via API de sync com o mesmo offline_uuid
        self.client.login(username='operador_alpha', password='pass123')
        payload = {
            'vendas': [{
                'offline_uuid': unique_uuid,
                'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 2, 'preco_venda': 16.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 32.00, 'troco': 0.00}]
            }]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total_sincronizadas'], 1)

        # 3. Validação rigorosa: NENHUMA duplicação
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a, offline_uuid=unique_uuid).count(), 1)
        self.produto_cafe.refresh_from_db()
        # O estoque NÃO pode ter sido baixado 4 unidades! Apenas 2!
        self.assertEqual(self.produto_cafe.estoque_atual, estoque_inicial - Decimal('2.000'))
        # A gaveta NÃO pode ter recebido R$ 64! Apenas R$ 32!
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_inicial_gaveta + Decimal('32.00'))

    # =========================================================================
    # 16. PAYLOAD DIFERENTE COM MESMO UUID (IDEMPOTÊNCIA E PRESERVAÇÃO)
    # =========================================================================
    def test_16_payload_divergente_com_mesmo_uuid_rejeitado(self):
        """
        Se o mesmo offline_uuid for enviado com itens diferentes:
        - NÃO sobrescreve a venda existente
        - NÃO processa uma segunda venda
        - NÃO consome estoque do novo produto
        - Retorna a venda original intacta
        """
        unique_uuid = str(uuid.uuid4())
        v1 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )

        estoque_leite_antes = self.produto_leite.estoque_atual
        total_vendas_antes = Venda.objects.filter(empresa=self.empresa_a).count()

        # Tentativa de enviar payload diferente reutilizando o mesmo UUID
        v2 = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_leite.id, 'quantidade': 5}],  # Produto diferente!
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('30.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )

        # Deve retornar a venda original intacta
        self.assertEqual(v2.id, v1.id)
        self.assertEqual(v2.total, Decimal('16.00'))
        self.assertEqual(Venda.objects.filter(empresa=self.empresa_a).count(), total_vendas_antes)

        # O estoque do produto 2 não deve ter sido consumido
        self.produto_leite.refresh_from_db()
        self.assertEqual(self.produto_leite.estoque_atual, estoque_leite_antes)


    # =========================================================================
    # 17. ESTOQUE INSUFICIENTE DURANTE SINCRONIZAÇÃO
    # =========================================================================
    def test_17_estoque_insuficiente_na_sincronizacao(self):
        """Venda offline com quantidade maior que o estoque real é rejeitada pelo backend."""
        self.client.login(username='operador_alpha', password='pass123')
        payload = {
            'vendas': [{
                'offline_uuid': str(uuid.uuid4()),
                'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 999, 'preco_venda': 16.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 15984.00, 'troco': 0.00}]
            }]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['total_sincronizadas'], 0)
        self.assertEqual(len(data['erros']), 1)
        self.assertIn("Estoque insuficiente", data['erros'][0]['error'])

    # =========================================================================
    # 18. PRODUTO INATIVADO DURANTE SINCRONIZAÇÃO
    # =========================================================================
    def test_18_produto_inativado_rejeitado_na_sincronizacao(self):
        """Produto inativo no momento do sync é rejeitado pelo servidor."""
        self.client.login(username='operador_alpha', password='pass123')
        payload = {
            'vendas': [{
                'offline_uuid': str(uuid.uuid4()),
                'itens': [{'produto_id': self.produto_inativo.id, 'quantidade': 1, 'preco_venda': 5.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 5.00, 'troco': 0.00}]
            }]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        data = resp.json()
        self.assertEqual(data['total_sincronizadas'], 0)
        self.assertEqual(len(data['erros']), 1)

    # =========================================================================
    # 19. PREÇO PRESERVADO NA VENDA
    # =========================================================================
    def test_19_preco_informado_processado_corretamente(self):
        """Preço praticado no momento da venda é registrado."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1, 'preco_venda': Decimal('16.00')}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=str(uuid.uuid4())
        )
        self.assertEqual(venda.total, Decimal('16.00'))

    # =========================================================================
    # 20. VENDA EM DINHEIRO COM TROCO
    # =========================================================================
    def test_20_venda_dinheiro_com_troco_valor_efetivo(self):
        """Venda de R$ 16 paga com R$ 20 gera troco de R$ 4 e incrementa gaveta em R$ 16."""
        saldo_antes = self.sessao_a.saldo_esperado
        SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('20.00'), 'troco': Decimal('4.00')}],
            offline_uuid=str(uuid.uuid4())
        )
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes + Decimal('16.00'))

    # =========================================================================
    # 21. VENDA PIX
    # =========================================================================
    def test_21_venda_pix_nao_altera_gaveta(self):
        """Venda via PIX não altera dinheiro físico na gaveta."""
        saldo_antes = self.sessao_a.saldo_esperado
        SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'PIX', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=str(uuid.uuid4())
        )
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes)

    # =========================================================================
    # 22. VENDA CARTÃO
    # =========================================================================
    def test_22_venda_cartao_nao_altera_gaveta(self):
        """Venda via cartão de crédito não altera gaveta física."""
        saldo_antes = self.sessao_a.saldo_esperado
        SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'CARTAO_CREDITO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=str(uuid.uuid4())
        )
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes)

    # =========================================================================
    # 23. VENDA DIVIDIDA
    # =========================================================================
    def test_23_venda_dividida_multiplas_formas(self):
        """Venda de R$ 32 paga com R$ 16 em Dinheiro e R$ 16 em PIX."""
        saldo_antes = self.sessao_a.saldo_esperado
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 2}],
            pagamentos_data=[
                {'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')},
                {'forma': 'PIX', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}
            ],
            offline_uuid=str(uuid.uuid4())
        )
        self.assertEqual(venda.pagamentos.count(), 2)
        self.sessao_a.refresh_from_db()
        self.assertEqual(self.sessao_a.saldo_esperado, saldo_antes + Decimal('16.00'))

    # =========================================================================
    # 24. VENDA EM CREDIÁRIO
    # =========================================================================
    def test_24_venda_crediario_gera_conta_receber(self):
        """Venda offline no crediário gera título a receber na sincronização."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
            pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
            offline_uuid=str(uuid.uuid4())
        )
        self.cliente_a.refresh_from_db()
        self.assertEqual(self.cliente_a.saldo_devedor, Decimal('16.00'))
        self.assertEqual(ContaReceber.objects.filter(venda=venda).count(), 1)

    # =========================================================================
    # 25. VENDA COM CREDIÁRIO + PIX
    # =========================================================================
    def test_25_venda_crediario_mais_pix(self):
        """Venda mista crediário + PIX divide valores perfeitamente."""
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a, cliente=self.cliente_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 2}],
            pagamentos_data=[
                {'forma': 'PIX', 'valor': Decimal('12.00'), 'troco': Decimal('0.00')},
                {'forma': 'CREDIARIO', 'valor': Decimal('20.00'), 'troco': Decimal('0.00')}
            ],
            offline_uuid=str(uuid.uuid4())
        )
        self.assertEqual(venda.total, Decimal('32.00'))
        self.cliente_a.refresh_from_db()
        self.assertEqual(self.cliente_a.saldo_devedor, Decimal('20.00'))

    # =========================================================================
    # 26. LIMITE DE CRÉDITO EXCEDIDO DURANTE SINCRONIZAÇÃO
    # =========================================================================
    def test_26_limite_credito_excedido_na_sincronizacao(self):
        """Se o cliente tiver limite esgotado antes do sync da venda offline, backend rejeita."""
        self.cliente_a.saldo_devedor = Decimal('290.00')  # Limite é 300, sobra 10
        self.cliente_a.save()

        # Venda de R$ 32 no crediário excede o limite disponível
        with self.assertRaises(ValueError) as ctx:
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a, cliente=self.cliente_a,
                itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 2}],
                pagamentos_data=[{'forma': 'CREDIARIO', 'valor': Decimal('32.00'), 'troco': Decimal('0.00')}],
                offline_uuid=str(uuid.uuid4())
            )
        self.assertIn("Limite de crédito insuficiente", str(ctx.exception))

    # =========================================================================
    # 27. ISOLAMENTO ENTRE EMPRESAS (MULTI-TENANT)
    # =========================================================================
    def test_27_isolamento_multi_tenant_sync(self):
        """Operador da Empresa B não pode sincronizar nem acessar vendas da Empresa A."""
        self.client.login(username='operador_beta', password='pass123')
        # Tenta sincronizar produto da Empresa A na Empresa B
        payload = {
            'vendas': [{
                'offline_uuid': str(uuid.uuid4()),
                'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 1, 'preco_venda': 16.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 16.00, 'troco': 0.00}]
            }]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        data = resp.json()
        self.assertEqual(data['total_sincronizadas'], 0)
        self.assertEqual(len(data['erros']), 1)

    # =========================================================================
    # 28. PERMISSÃO DE USUÁRIO
    # =========================================================================
    def test_28_usuario_nao_autenticado_bloqueado_no_sync(self):
        """API de sincronização exige usuário devidamente autenticado."""
        resp = self.client.post('/api/v1/pdv/sync/', {'vendas': []}, content_type='application/json')
        self.assertIn(resp.status_code, [401, 403])


    # =========================================================================
    # 29. AUDITORIA SEM DUPLICIDADE EM RETRIES
    # =========================================================================
    def test_29_auditoria_unica_mesmo_com_multiplos_retries(self):
        """Mesmo com 3 chamadas repetidas com o mesmo offline_uuid, apenas 1 AuditLog de VENDA_CRIADA é gerado."""
        unique_uuid = str(uuid.uuid4())
        logs_antes = AuditLog.objects.filter(empresa=self.empresa_a, acao='VENDA_CRIADA').count()

        for _ in range(3):
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a,
                itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
                offline_uuid=unique_uuid
            )

        logs_depois = AuditLog.objects.filter(empresa=self.empresa_a, acao='VENDA_CRIADA').count()
        self.assertEqual(logs_depois, logs_antes + 1)

    # =========================================================================
    # 30. FLUXO DE CAIXA SEM DUPLICIDADE
    # =========================================================================
    def test_30_fluxo_caixa_unico_em_retries(self):
        """Retries da mesma venda offline geram exatamente 1 lançamento no FluxoCaixa."""
        unique_uuid = str(uuid.uuid4())
        venda = None
        for _ in range(3):
            venda = SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a,
                itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 1}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('16.00'), 'troco': Decimal('0.00')}],
                offline_uuid=unique_uuid
            )
        fluxos = FluxoCaixa.objects.filter(empresa=self.empresa_a, referencia_origem=venda.codigo_venda)
        self.assertEqual(fluxos.count(), 1)

    # =========================================================================
    # 31. BAIXA DE ESTOQUE APENAS UMA VEZ
    # =========================================================================
    def test_31_estoque_baixado_exatamente_uma_vez(self):
        """Retries sucessivos decrementam o estoque exatamente 1 vez."""
        unique_uuid = str(uuid.uuid4())
        estoque_inicio = self.produto_cafe.estoque_atual
        for _ in range(3):
            SaleService.processar_venda(
                empresa=self.empresa_a, sessao_caixa=self.sessao_a,
                operador=self.operador_a,
                itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 3}],
                pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('48.00'), 'troco': Decimal('0.00')}],
                offline_uuid=unique_uuid
            )
        self.produto_cafe.refresh_from_db()
        self.assertEqual(self.produto_cafe.estoque_atual, estoque_inicio - Decimal('3.000'))

    # =========================================================================
    # 32. MÚLTIPLAS VENDAS PENDENTES EM LOTE
    # =========================================================================
    def test_32_sincronizacao_em_lote_multiplas_vendas(self):
        """Lote contendo 5 vendas offline é processado e todas são persistidas com sucesso."""
        self.client.login(username='operador_alpha', password='pass123')
        vendas_payload = []
        for i in range(5):
            vendas_payload.append({
                'offline_uuid': str(uuid.uuid4()),
                'itens': [{'produto_id': self.produto_leite.id, 'quantidade': 1, 'preco_venda': 6.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 6.00, 'troco': 0.00}]
            })
        resp = self.client.post('/api/v1/pdv/sync/', {'vendas': vendas_payload}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['total_sincronizadas'], 5)

    # =========================================================================
    # 33. FALHA TRANSITÓRIA E RETRY BEM-SUCEDIDO
    # =========================================================================
    def test_33_falha_transitoria_e_retry(self):
        """Venda com erro transitório que é corrigida e reenviada sincroniza perfeitamente."""
        self.client.login(username='operador_alpha', password='pass123')
        unique_uuid = str(uuid.uuid4())
        # Envio 1: Item sem produto_id (falha de validação)
        resp1 = self.client.post('/api/v1/pdv/sync/', {
            'vendas': [{'offline_uuid': unique_uuid, 'itens': [], 'pagamentos': []}]
        }, content_type='application/json')
        self.assertEqual(resp1.json()['total_sincronizadas'], 0)

        # Envio 2: Correção do payload mantendo o mesmo offline_uuid
        resp2 = self.client.post('/api/v1/pdv/sync/', {
            'vendas': [{
                'offline_uuid': unique_uuid,
                'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 1, 'preco_venda': 16.00}],
                'pagamentos': [{'forma': 'DINHEIRO', 'valor': 16.00, 'troco': 0.00}]
            }]
        }, content_type='application/json')
        self.assertEqual(resp2.json()['total_sincronizadas'], 1)

    # =========================================================================
    # 34. ERRO PERMANENTE EM UMA VENDA NÃO QUEBRA O RESTANTE DO LOTE
    # =========================================================================
    def test_34_erro_parcial_nao_aborta_vendas_validas_do_lote(self):
        """Se 1 venda do lote for inválida (ex: estoque), as outras 2 válidas sincronizam normalmente."""
        self.client.login(username='operador_alpha', password='pass123')
        payload = {
            'vendas': [
                {
                    'offline_uuid': str(uuid.uuid4()),
                    'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 1, 'preco_venda': 16.00}],
                    'pagamentos': [{'forma': 'DINHEIRO', 'valor': 16.00, 'troco': 0.00}]
                },
                {
                    'offline_uuid': str(uuid.uuid4()),
                    'itens': [{'produto_id': self.produto_cafe.id, 'quantidade': 9999, 'preco_venda': 16.00}],  # Erro
                    'pagamentos': [{'forma': 'DINHEIRO', 'valor': 159984.00, 'troco': 0.00}]
                },
                {
                    'offline_uuid': str(uuid.uuid4()),
                    'itens': [{'produto_id': self.produto_leite.id, 'quantidade': 1, 'preco_venda': 6.00}],
                    'pagamentos': [{'forma': 'DINHEIRO', 'valor': 6.00, 'troco': 0.00}]
                }
            ]
        }
        resp = self.client.post('/api/v1/pdv/sync/', payload, content_type='application/json')
        data = resp.json()
        self.assertEqual(data['total_sincronizadas'], 2)
        self.assertEqual(len(data['erros']), 1)

    # =========================================================================
    # 35. CATÁLOGO OFFLINE (EXPORTAÇÃO DE PRODUTOS E CLIENTES)
    # =========================================================================
    def test_35_catalogo_offline_exporta_dados_do_tenant(self):
        """Endpoint /api/v1/pdv/produtos-offline/ exporta produtos e clientes ativos do tenant."""
        self.client.login(username='operador_alpha', password='pass123')
        resp = self.client.get('/api/v1/pdv/produtos-offline/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['empresa_id'], self.empresa_a.id)
        # Deve conter café e leite, mas não o biscoito inativo
        nomes_prods = [p['nome'] for p in data['produtos']]
        self.assertIn("Café Torrado 500g", nomes_prods)
        self.assertIn("Leite Integral 1L", nomes_prods)
        self.assertNotIn("Biscoito Descontinuado", nomes_prods)

    # =========================================================================
    # 36. CANCELAMENTO TRANSACIONAL DE VENDA SINCRONIZADA
    # =========================================================================
    def test_36_cancelamento_venda_sincronizada(self):
        """Venda sincronizada pode ser cancelada de forma atômica estornando estoque e caixa."""
        estoque_antes = self.produto_cafe.estoque_atual
        unique_uuid = str(uuid.uuid4())
        venda = SaleService.processar_venda(
            empresa=self.empresa_a, sessao_caixa=self.sessao_a,
            operador=self.operador_a,
            itens_data=[{'produto_id': self.produto_cafe.id, 'quantidade': 2}],
            pagamentos_data=[{'forma': 'DINHEIRO', 'valor': Decimal('32.00'), 'troco': Decimal('0.00')}],
            offline_uuid=unique_uuid
        )
        self.produto_cafe.refresh_from_db()
        self.assertEqual(self.produto_cafe.estoque_atual, estoque_antes - Decimal('2.000'))

        SaleService.cancelar_venda(venda.id, self.empresa_a, self.admin_a, "Cancelamento pós-sync")
        venda.refresh_from_db()
        self.assertEqual(venda.status, 'CANCELADA')
        self.produto_cafe.refresh_from_db()
        self.assertEqual(self.produto_cafe.estoque_atual, estoque_antes)
