from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError

from apps.empresas.models import Empresa, ConfiguracaoAtalhoPDV
from apps.usuarios.models import Usuario
from apps.compras.models import Compra
from apps.caixas.models import Caixa
from apps.caixas.services import CashService
from apps.produtos.models import Produto
from apps.clientes.models import Cliente
from decimal import Decimal


class ConfiguracaoAtalhosPDVTestCase(TestCase):
    def setUp(self):
        # Empresa A
        self.empresa_a = Empresa.objects.create(
            razao_social="Adega Atalhos Alpha LTDA",
            nome_fantasia="Adega Alpha",
            cnpj="12345678000199"
        )
        # Empresa B
        self.empresa_b = Empresa.objects.create(
            razao_social="Adega Atalhos Beta LTDA",
            nome_fantasia="Adega Beta",
            cnpj="98765432000188"
        )

        # Usuários
        self.admin = Usuario.objects.create_user(
            username="admin_atalhos",
            email="admin@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='ADMIN'
        )
        self.operador = Usuario.objects.create_user(
            username="operador_sem_permissao",
            email="op@teste.com",
            password="password123",
            empresa=self.empresa_a,
            cargo='OPERADOR'
        )

        # Caixa para PDV
        self.caixa = Caixa.objects.create(empresa=self.empresa_a, nome="Caixa 1", codigo_identificador="CX-01")
        self.sessao = CashService.abrir_caixa(self.caixa, self.admin, Decimal('50.00'))

        self.client_admin = Client()
        self.client_admin.force_login(self.admin)

        self.client_op = Client()
        self.client_op.force_login(self.operador)

    # 1. Configuração padrão retornada corretamente (F5 para Finalizar Compra, F2, F4, Escape)
    def test_atalhos_padrao_corretos(self):
        atalhos = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)
        self.assertEqual(atalhos['FINALIZAR_COMPRA'], 'F5')
        self.assertEqual(atalhos['FOCAR_BUSCA'], 'F2')
        self.assertEqual(atalhos['IDENTIFICAR_CLIENTE'], 'F4')
        self.assertEqual(atalhos['CANCELAR_FECHAR'], 'Escape')

    # 2. Alteração de F5 para F8 e persistência no banco
    def test_alteracao_f5_para_f8_e_persistencia(self):
        novos = {
            'FINALIZAR_COMPRA': 'F8',
            'FOCAR_BUSCA': 'F2',
            'IDENTIFICAR_CLIENTE': 'F4',
            'CANCELAR_FECHAR': 'Escape',
        }
        ConfiguracaoAtalhoPDV.salvar_atalhos(self.empresa_a, novos)

        atalhos_atualizados = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)
        self.assertEqual(atalhos_atualizados['FINALIZAR_COMPRA'], 'F8')
        self.assertEqual(atalhos_atualizados['FOCAR_BUSCA'], 'F2')

        # Persistência direta no banco
        registro = ConfiguracaoAtalhoPDV.objects.get(empresa=self.empresa_a, funcao_codigo='FINALIZAR_COMPRA')
        self.assertEqual(registro.tecla, 'F8')

    # 3. Post HTTP na View de Configurações alterando F5 para F8
    def test_post_configuracao_atalhos_view(self):
        url = reverse('configuracoes')
        post_data = {
            'action': 'salvar_atalhos_pdv',
            'atalho_FINALIZAR_COMPRA': 'F8',
            'atalho_FOCAR_BUSCA': 'F1',
            'atalho_IDENTIFICAR_CLIENTE': 'F3',
            'atalho_CANCELAR_FECHAR': 'Escape',
        }
        response = self.client_admin.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Atalhos do PDV salvos com sucesso!")

        atalhos = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)
        self.assertEqual(atalhos['FINALIZAR_COMPRA'], 'F8')
        self.assertEqual(atalhos['FOCAR_BUSCA'], 'F1')

    # 4. Impedir duas funções com o mesmo atalho (Conflito de Teclas)
    def test_impedir_atalhos_duplicados_conflito(self):
        conflito = {
            'FINALIZAR_COMPRA': 'F5',
            'FOCAR_BUSCA': 'F5',  # Mesma tecla!
            'IDENTIFICAR_CLIENTE': 'F4',
            'CANCELAR_FECHAR': 'Escape',
        }
        with self.assertRaises(ValidationError) as ctx:
            ConfiguracaoAtalhoPDV.salvar_atalhos(self.empresa_a, conflito)

        self.assertIn("já está sendo utilizado por outra função", str(ctx.exception))

    # 5. Impedir tecla não permitida
    def test_impedir_tecla_invalida(self):
        invalida = {
            'FINALIZAR_COMPRA': 'CTRL+C',  # Tecla não permitida
            'FOCAR_BUSCA': 'F2',
            'IDENTIFICAR_CLIENTE': 'F4',
            'CANCELAR_FECHAR': 'Escape',
        }
        with self.assertRaises(ValidationError) as ctx:
            ConfiguracaoAtalhoPDV.salvar_atalhos(self.empresa_a, invalida)

        self.assertIn("não é permitida para atalhos do PDV", str(ctx.exception))

    # 6. Isolamento Multi-Tenancy (Empresa A altera para F8, Empresa B continua F5)
    def test_isolamento_multitenancy_atalhos(self):
        novos_a = {
            'FINALIZAR_COMPRA': 'F8',
            'FOCAR_BUSCA': 'F2',
            'IDENTIFICAR_CLIENTE': 'F4',
            'CANCELAR_FECHAR': 'Escape',
        }
        ConfiguracaoAtalhoPDV.salvar_atalhos(self.empresa_a, novos_a)

        atalhos_a = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)
        atalhos_b = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_b)

        self.assertEqual(atalhos_a['FINALIZAR_COMPRA'], 'F8')
        self.assertEqual(atalhos_b['FINALIZAR_COMPRA'], 'F5')

    # 7. Usuário sem permissão (OPERADOR) é bloqueado com 403
    def test_usuario_sem_permissao_bloqueado(self):
        url = reverse('configuracoes')
        post_data = {
            'action': 'salvar_atalhos_pdv',
            'atalho_FINALIZAR_COMPRA': 'F8',
            'atalho_FOCAR_BUSCA': 'F2',
            'atalho_IDENTIFICAR_CLIENTE': 'F4',
            'atalho_CANCELAR_FECHAR': 'Escape',
        }
        response = self.client_op.post(url, post_data)
        self.assertEqual(response.status_code, 403)

    # 8. Restauração dos Padrões de Fábrica
    def test_restaurar_padroes_atalhos(self):
        novos = {
            'FINALIZAR_COMPRA': 'F12',
            'FOCAR_BUSCA': 'F11',
            'IDENTIFICAR_CLIENTE': 'F10',
            'CANCELAR_FECHAR': 'Delete',
        }
        ConfiguracaoAtalhoPDV.salvar_atalhos(self.empresa_a, novos)
        self.assertEqual(ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)['FINALIZAR_COMPRA'], 'F12')

        # Restaura via método e view
        url = reverse('configuracoes')
        response = self.client_admin.post(url, {'action': 'restaurar_padroes_atalhos'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "restaurados para os padrões originais")

        atalhos_restaurados = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_a)
        self.assertEqual(atalhos_restaurados['FINALIZAR_COMPRA'], 'F5')
        self.assertEqual(atalhos_restaurados['FOCAR_BUSCA'], 'F2')

    # 9. Injeção e Carregamento da Configuração na View do PDV
    def test_carregamento_configuracao_pdv_view(self):
        novos = {
            'FINALIZAR_COMPRA': 'F8',
            'FOCAR_BUSCA': 'F2',
            'IDENTIFICAR_CLIENTE': 'F4',
            'CANCELAR_FECHAR': 'Escape',
        }
        ConfiguracaoAtalhoPDV.salvar_atalhos(self.empresa_a, novos)

        url_pdv = reverse('pdv_front')
        response = self.client_admin.get(url_pdv)
        self.assertEqual(response.status_code, 200)

        # Contexto contém atalhos
        self.assertIn('atalhos_pdv', response.context)
        self.assertEqual(response.context['atalhos_pdv']['FINALIZAR_COMPRA'], 'F8')

        # Conteúdo HTML reflete a nova tecla no botão e no script window.PDV_SHORTCUTS
        self.assertContains(response, 'PAGAMENTO / FINALIZAR (<span id="label-shortcut-finalizar">F8</span>)')
        self.assertContains(response, 'window.PDV_SHORTCUTS = {"FINALIZAR_COMPRA": "F8"')

    # 10. Fallback para Padrão quando não houver registro
    def test_fallback_quando_nao_configurado(self):
        atalhos = ConfiguracaoAtalhoPDV.get_atalhos_empresa(self.empresa_b)
        self.assertEqual(atalhos['FINALIZAR_COMPRA'], 'F5')
        self.assertEqual(atalhos['FOCAR_BUSCA'], 'F2')

    # 11. Validação de Não Regressão: /compras/ sem fornecedor não gera VariableDoesNotExist
    def test_compras_sem_fornecedor_nao_gera_erro(self):
        # Cria compra com fornecedor nulo
        Compra.objects.create(
            empresa=self.empresa_a,
            fornecedor=None,
            numero_nota="NF-TESTE-NULL",
            total=Decimal('150.00'),
            status='CONCLUIDA'
        )
        url_compras = reverse('compras_list')
        response = self.client_admin.get(url_compras)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sem Fornecedor")
        self.assertContains(response, "NF-TESTE-NULL")

    # 12. Validação do Escopo de data-page: 'pdv' no PDV e 'default' nas demais telas
    def test_data_page_escopo_telas(self):
        # No PDV
        resp_pdv = self.client_admin.get(reverse('pdv_front'))
        self.assertEqual(resp_pdv.status_code, 200)
        self.assertContains(resp_pdv, '<body data-page="pdv">')

        # No Dashboard
        resp_dash = self.client_admin.get(reverse('dashboard'))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, '<body data-page="default">')

        # Em Configurações
        resp_conf = self.client_admin.get(reverse('configuracoes'))
        self.assertEqual(resp_conf.status_code, 200)
        self.assertContains(resp_conf, '<body data-page="default">')

    # 13. Navbar do PDV é simplificada (apenas Início, Caixa, Status e Fila, sem menus completos)
    def test_navbar_simplificada_no_pdv(self):
        resp_pdv = self.client_admin.get(reverse('pdv_front'))
        self.assertEqual(resp_pdv.status_code, 200)

        # Contém botões de retorno rápido
        self.assertContains(resp_pdv, 'Início')
        self.assertContains(resp_pdv, 'Caixa')
        self.assertContains(resp_pdv, 'href="/"')
        self.assertContains(resp_pdv, 'href="/caixas/"')

        # NÃO contém menus complexos e dropdowns na navbar do PDV
        self.assertNotContains(resp_pdv, 'id="finDropdown"')
        self.assertNotContains(resp_pdv, 'id="relDropdown"')
        self.assertNotContains(resp_pdv, 'href="/produtos/"')
        self.assertNotContains(resp_pdv, 'href="/clientes/"')
        self.assertNotContains(resp_pdv, 'href="/compras/"')

    # 14. Navbar completa exibida fora do PDV (Dashboard, Relatórios, etc.)
    def test_navbar_completa_fora_do_pdv(self):
        resp_dash = self.client_admin.get(reverse('dashboard'))
        self.assertEqual(resp_dash.status_code, 200)

        # Contém menus completos
        self.assertContains(resp_dash, 'id="finDropdown"')
        self.assertContains(resp_dash, 'id="relatDropdown"')
        self.assertContains(resp_dash, 'href="/produtos/"')
        self.assertContains(resp_dash, 'href="/clientes/"')

    # 15. Botão Voltar presente nas páginas internas e ausente na Home/Dashboard
    def test_botao_voltar_navegacao(self):
        # Na Home / Dashboard: NÃO deve ter botão voltar
        resp_dash = self.client_admin.get(reverse('dashboard'))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertNotContains(resp_dash, 'window.history.back()')

        # No PDV: NÃO deve ter a barra genérica de voltar (possui botões próprios Início e Caixa)
        resp_pdv = self.client_admin.get(reverse('pdv_front'))
        self.assertEqual(resp_pdv.status_code, 200)
        self.assertNotContains(resp_pdv, 'window.history.back()')

        # Em página interna (ex: Configurações ou Caixas): DEVE ter botão voltar
        resp_conf = self.client_admin.get(reverse('configuracoes'))
        self.assertEqual(resp_conf.status_code, 200)
        self.assertContains(resp_conf, 'window.history.back()')
        self.assertContains(resp_conf, 'Voltar')

    # 16. Pré-Visualização Dinâmica embutida em Configurações (Aba 1 e Aba 2) sem aba separada
    def test_preview_dinamico_embutido_em_configuracoes(self):
        resp_conf = self.client_admin.get(reverse('configuracoes'))
        self.assertEqual(resp_conf.status_code, 200)

        # Pré-visualização do Sistema está presente na Aba 1
        self.assertContains(resp_conf, 'Pré-Visualização Dinâmica da Barra Superior e Sistema')
        self.assertContains(resp_conf, 'id="prev-navbar"')

        # Pré-visualização do PDV está presente na Aba 2
        self.assertContains(resp_conf, 'Pré-Visualização Dinâmica da Frente de Caixa (PDV)')
        self.assertContains(resp_conf, 'id="prev-pdv-box"')

        # NÃO existe mais a aba separada de preview isolada
        self.assertNotContains(resp_conf, 'id="tab-preview-btn"')
        self.assertNotContains(resp_conf, 'id="tab-preview"')

    # 17. Variáveis CSS do Tenant injetadas no Base e refletidas em custom.css
    def test_css_variables_tenant_aplicadas(self):
        resp_dash = self.client_admin.get(reverse('dashboard'))
        self.assertEqual(resp_dash.status_code, 200)

        # Injetado no <style> de base.html
        self.assertContains(resp_dash, '--cor-principal:')
        self.assertContains(resp_dash, '--cor-menu-sidebar:')
        self.assertContains(resp_dash, '--cor-pdv-fundo:')
        self.assertContains(resp_dash, '--cor-pdv-total:')

    # 18. Cores personalizadas dos botões de ação presentes em ConfiguracaoVisual e CSS
    def test_cores_botoes_acao_pdv_padrao_e_css(self):
        from apps.empresas.models import ConfiguracaoVisual
        conf, _ = ConfiguracaoVisual.objects.get_or_create(empresa=self.empresa_a)
        self.assertEqual(conf.cor_pdv_botao_pausar, '#d97706')
        self.assertEqual(conf.cor_pdv_botao_espera, '#2563eb')
        self.assertEqual(conf.cor_pdv_botao_divida, '#7c3aed')

        css_vars = conf.to_css_variables()
        self.assertIn('--cor-pdv-botao-pausar: #d97706;', css_vars)
        self.assertIn('--cor-pdv-botao-espera: #2563eb;', css_vars)
        self.assertIn('--cor-pdv-botao-divida: #7c3aed;', css_vars)

    # 19. Persistência de alteração das cores dos botões de ação via formulário
    def test_salvar_cores_botoes_acao_pdv(self):
        from apps.empresas.models import ConfiguracaoVisual
        conf, _ = ConfiguracaoVisual.objects.get_or_create(empresa=self.empresa_a)

        payload = {
            'action': 'salvar_tema_cores',
            'cor_principal': '#1e40af',
            'cor_secundaria': '#475569',
            'cor_destaque': '#f59e0b',
            'cor_menu_sidebar': '#0f172a',
            'cor_fundo': '#f8fafc',
            'cor_cards': '#ffffff',
            'cor_texto': '#1e293b',
            'cor_texto_secundario': '#64748b',
            'cor_botoes': '#1e40af',
            'cor_botoes_acao': '#10b981',
            'cor_links': '#1e40af',
            'cor_sucesso': '#16a34a',
            'cor_alerta': '#d97706',
            'cor_erro': '#dc2626',
            'cor_pdv_fundo': '#0f172a',
            'cor_pdv_texto': '#ffffff',
            'cor_pdv_preco': '#22c55e',
            'cor_pdv_total': '#eab308',
            'cor_pdv_botao_finalizar': '#16a34a',
            'cor_pdv_botao_cancelar': '#dc2626',
            'cor_pdv_botoes_pagamento': '#3b82f6',
            'cor_pdv_botao_pausar': '#b45309',
            'cor_pdv_botao_espera': '#1d4ed8',
            'cor_pdv_botao_divida': '#6d28d9',
            'tamanho_fonte_total': '2.0rem',
            'tamanho_fonte_preco': '1.25rem',
            'tamanho_fonte_itens': '1.0rem',
            'modo_layout': 'CONFORTAVEL'
        }
        resp = self.client_admin.post(reverse('configuracoes'), payload, follow=True)
        self.assertEqual(resp.status_code, 200)

        conf.refresh_from_db()
        self.assertEqual(conf.cor_pdv_botao_pausar, '#b45309')
        self.assertEqual(conf.cor_pdv_botao_espera, '#1d4ed8')
        self.assertEqual(conf.cor_pdv_botao_divida, '#6d28d9')

    # 20. Isolamento multi-empresa na personalização dos botões do PDV
    def test_isolamento_multiempresa_cores_botoes_pdv(self):
        from apps.empresas.models import ConfiguracaoVisual
        conf_a, _ = ConfiguracaoVisual.objects.get_or_create(empresa=self.empresa_a, defaults={'cor_pdv_botao_pausar': '#111111'})
        conf_b, _ = ConfiguracaoVisual.objects.get_or_create(empresa=self.empresa_b, defaults={'cor_pdv_botao_pausar': '#222222'})

        self.assertEqual(conf_a.cor_pdv_botao_pausar, '#111111')
        self.assertEqual(conf_b.cor_pdv_botao_pausar, '#222222')

    # 21. Restauração de padrões de fábrica para botões de ação
    def test_restaurar_padroes_cores_botoes_pdv(self):
        from apps.empresas.models import ConfiguracaoVisual
        conf, _ = ConfiguracaoVisual.objects.get_or_create(empresa=self.empresa_a)
        conf.cor_pdv_botao_pausar = '#000000'
        conf.cor_pdv_botao_espera = '#000000'
        conf.cor_pdv_botao_divida = '#000000'
        conf.save()

        resp = self.client_admin.post(reverse('configuracoes'), {'action': 'restaurar_padroes'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        conf.refresh_from_db()
        self.assertEqual(conf.cor_pdv_botao_pausar, '#d97706')
        self.assertEqual(conf.cor_pdv_botao_espera, '#2563eb')
        self.assertEqual(conf.cor_pdv_botao_divida, '#7c3aed')

    # 22. PDV renderiza botões de ação com classes compactas e coloridas
    def test_pdv_renderiza_classes_botoes_acao(self):
        resp_pdv = self.client_admin.get(reverse('pdv_front'))
        self.assertEqual(resp_pdv.status_code, 200)

        self.assertContains(resp_pdv, 'btn-pdv-action')
        self.assertContains(resp_pdv, 'btn-pdv-pausar')
        self.assertContains(resp_pdv, 'btn-pdv-espera')
        self.assertContains(resp_pdv, 'btn-pdv-divida')

    # 23. Relatório de Reposição renderiza tabela limpa sem faixas opacas bloqueadoras
    def test_relatorio_reposicao_tabela_limpa(self):
        resp_rep = self.client_admin.get(reverse('relatorio_reposicao'))
        self.assertEqual(resp_rep.status_code, 200)

        self.assertContains(resp_rep, 'PRODUTOS VENDIDOS NA SEMANA')
        self.assertContains(resp_rep, 'Total Vendido')
        self.assertContains(resp_rep, 'Lucro Obtido')
        self.assertContains(resp_rep, 'Qtde. Vendida')


