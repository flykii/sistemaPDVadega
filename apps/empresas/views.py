import json
import re
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError

from apps.usuarios.permissions import cargo_required
from apps.core.models import AuditService
from .models import Empresa, ConfiguracaoVisual, ConfiguracaoAtalhoPDV, HEX_COLOR_REGEX


@login_required
@cargo_required('ADMIN', 'GERENTE')
def configuracoes_view(request):
    """
    Página de Configurações Gerais e Personalização Visual do Sistema e PDV.
    Protegida para ADMIN e GERENTE com isolamento estrito por tenant e Trilha de Auditoria.
    """
    empresa = getattr(request, 'tenant', None) or request.user.empresa
    config_visual = empresa.get_configuracao_visual()

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. Salvar Dados Cadastrais da Empresa
        if action == 'salvar_dados':
            dados_anteriores = {
                'nome_fantasia': empresa.nome_fantasia,
                'razao_social': empresa.razao_social,
                'cnpj': empresa.cnpj
            }
            empresa.nome_fantasia = request.POST.get('nome_fantasia', empresa.nome_fantasia)
            empresa.razao_social = request.POST.get('razao_social', empresa.razao_social)
            empresa.cnpj = request.POST.get('cnpj', empresa.cnpj)
            empresa.inscricao_estadual = request.POST.get('inscricao_estadual', empresa.inscricao_estadual)
            empresa.endereco = request.POST.get('endereco', empresa.endereco)
            empresa.cidade = request.POST.get('cidade', empresa.cidade)
            empresa.estado = request.POST.get('estado', empresa.estado)
            empresa.telefone = request.POST.get('telefone', empresa.telefone)
            empresa.whatsapp = request.POST.get('whatsapp', empresa.whatsapp)
            empresa.email = request.POST.get('email', empresa.email)
            empresa.save()

            AuditService.registrar(
                empresa=empresa,
                usuario=request.user,
                acao='USUARIO_ALTERADO',
                entidade='Empresa',
                entidade_id=empresa.id,
                descricao=f"Dados cadastrais da empresa '{empresa.nome_fantasia}' atualizados.",
                dados_anteriores=dados_anteriores,
                dados_posteriores={'nome_fantasia': empresa.nome_fantasia, 'cnpj': empresa.cnpj}
            )
            messages.success(request, "Dados da empresa atualizados com sucesso!")

        # 2. Salvar Identidade Visual (Logo / Favicon / Títulos)
        elif action == 'salvar_identidade_visual':
            config_visual.nome_fantasia_exibicao = request.POST.get('nome_fantasia_exibicao', config_visual.nome_fantasia_exibicao)
            config_visual.subtitulo_cabecalho = request.POST.get('subtitulo_cabecalho', config_visual.subtitulo_cabecalho)

            # Upload de Logo com validação de extensão/tipo
            if 'logo' in request.FILES:
                logo_file = request.FILES['logo']
                ext = logo_file.name.split('.')[-1].lower()
                if ext not in ['jpg', 'jpeg', 'png', 'webp', 'svg']:
                    messages.error(request, "Formato de imagem inválido para logo. Use JPG, PNG, WEBP ou SVG.")
                    return redirect('configuracoes')
                if logo_file.size > 5 * 1024 * 1024:
                    messages.error(request, "O tamanho da imagem não pode ultrapassar 5 MB.")
                    return redirect('configuracoes')
                config_visual.logo = logo_file
                empresa.logo = logo_file
                empresa.save()
            elif request.POST.get('remover_logo') == 'true':
                config_visual.logo = None
                empresa.logo = None
                empresa.save()

            # Upload de Favicon
            if 'favicon' in request.FILES:
                fav_file = request.FILES['favicon']
                ext = fav_file.name.split('.')[-1].lower()
                if ext not in ['ico', 'png', 'svg']:
                    messages.error(request, "Formato inválido para favicon. Use ICO, PNG ou SVG.")
                    return redirect('configuracoes')
                config_visual.favicon = fav_file
            elif request.POST.get('remover_favicon') == 'true':
                config_visual.favicon = None

            config_visual.save()
            messages.success(request, "Identidade visual atualizada com sucesso!")

        # 3. Salvar Cores do Sistema e Cores do PDV
        elif action == 'salvar_tema_cores':
            dados_anteriores = {
                'cor_principal': config_visual.cor_principal,
                'cor_secundaria': config_visual.cor_secundaria,
                'cor_pdv_fundo': config_visual.cor_pdv_fundo,
                'cor_pdv_preco': config_visual.cor_pdv_preco
            }

            campos_cores = [
                'cor_principal', 'cor_secundaria', 'cor_destaque', 'cor_menu_sidebar',
                'cor_fundo', 'cor_cards', 'cor_texto', 'cor_texto_secundario',
                'cor_botoes', 'cor_botoes_acao', 'cor_links', 'cor_sucesso',
                'cor_alerta', 'cor_erro', 'cor_pdv_fundo', 'cor_pdv_texto',
                'cor_pdv_preco', 'cor_pdv_total', 'cor_pdv_botao_finalizar',
                'cor_pdv_botao_cancelar', 'cor_pdv_botoes_pagamento',
                'cor_pdv_botao_pausar', 'cor_pdv_botao_espera', 'cor_pdv_botao_divida'
            ]

            try:
                for c in campos_cores:
                    val = request.POST.get(c)
                    if val:
                        val = val.strip()
                        if not val.startswith('#'):
                            val = f"#{val}"
                        if not HEX_COLOR_REGEX.match(val):
                            raise ValidationError(f"Código de cor inválido no campo '{c}': '{val}'. Use formato HEX (ex: #2563EB).")
                        setattr(config_visual, c, val)

                # Tipografia e Layout do PDV
                config_visual.tamanho_fonte_preco = request.POST.get('tamanho_fonte_preco', config_visual.tamanho_fonte_preco)
                config_visual.tamanho_fonte_total = request.POST.get('tamanho_fonte_total', config_visual.tamanho_fonte_total)
                config_visual.tamanho_fonte_itens = request.POST.get('tamanho_fonte_itens', config_visual.tamanho_fonte_itens)
                config_visual.modo_layout = request.POST.get('modo_layout', config_visual.modo_layout)
                config_visual.exibir_painel_produtos_rapidos = request.POST.get('exibir_painel_produtos_rapidos') == 'on'

                config_visual.full_clean()
                config_visual.save()

                AuditService.registrar(
                    empresa=empresa,
                    usuario=request.user,
                    acao='CONFIGURACAO_VISUAL_ALTERADA',
                    entidade='ConfiguracaoVisual',
                    entidade_id=config_visual.id,
                    descricao=f"Tema de cores e personalização visual da empresa '{empresa.nome_fantasia}' alterados.",
                    dados_anteriores=dados_anteriores,
                    dados_posteriores={
                        'cor_principal': config_visual.cor_principal,
                        'cor_pdv_fundo': config_visual.cor_pdv_fundo,
                        'cor_pdv_preco': config_visual.cor_pdv_preco,
                        'cor_pdv_total': config_visual.cor_pdv_total
                    }
                )

                messages.success(request, "Configurações de cores e layout salvas com sucesso!")
            except ValidationError as ve:
                messages.error(request, f"Erro de validação nas cores: {ve.message if hasattr(ve, 'message') else str(ve)}")
            except Exception as e:
                messages.error(request, f"Erro ao salvar configurações visuais: {str(e)}")

        # 4. Restaurar Cores Padrão
        elif action == 'restaurar_padroes':
            config_visual.cor_principal = '#2563eb'
            config_visual.cor_secundaria = '#475569'
            config_visual.cor_destaque = '#f59e0b'
            config_visual.cor_menu_sidebar = '#0f172a'
            config_visual.cor_fundo = '#f8fafc'
            config_visual.cor_cards = '#ffffff'
            config_visual.cor_texto = '#1e293b'
            config_visual.cor_texto_secundario = '#64748b'
            config_visual.cor_botoes = '#2563eb'
            config_visual.cor_botoes_acao = '#10b981'
            config_visual.cor_links = '#2563eb'
            config_visual.cor_sucesso = '#16a34a'
            config_visual.cor_alerta = '#d97706'
            config_visual.cor_erro = '#dc2626'
            config_visual.cor_pdv_fundo = '#0f172a'
            config_visual.cor_pdv_texto = '#ffffff'
            config_visual.cor_pdv_preco = '#22c55e'
            config_visual.cor_pdv_total = '#eab308'
            config_visual.cor_pdv_botao_finalizar = '#16a34a'
            config_visual.cor_pdv_botao_cancelar = '#dc2626'
            config_visual.cor_pdv_botoes_pagamento = '#3b82f6'
            config_visual.cor_pdv_botao_pausar = '#d97706'
            config_visual.cor_pdv_botao_espera = '#2563eb'
            config_visual.cor_pdv_botao_divida = '#7c3aed'
            config_visual.save()
            messages.success(request, "Configurações visuais restauradas para os padrões de fábrica!")

        # 5. Salvar Atalhos do PDV
        elif action == 'salvar_atalhos_pdv':
            dados_anteriores = ConfiguracaoAtalhoPDV.get_atalhos_empresa(empresa)
            novos_atalhos = {}
            for func in ConfiguracaoAtalhoPDV.FUNCOES_PADRAO:
                cod = func[0]
                valor = request.POST.get(f"atalho_{cod}")
                if valor:
                    novos_atalhos[cod] = valor

            try:
                ConfiguracaoAtalhoPDV.salvar_atalhos(empresa, novos_atalhos)
                AuditService.registrar(
                    empresa=empresa,
                    usuario=request.user,
                    acao='ATALHOS_PDV_ALTERADOS',
                    entidade='ConfiguracaoAtalhoPDV',
                    entidade_id=empresa.id,
                    descricao=f"Atalhos de teclado do PDV da empresa '{empresa.nome_fantasia}' foram atualizados.",
                    dados_anteriores=dados_anteriores,
                    dados_posteriores=novos_atalhos
                )
                messages.success(request, "Atalhos do PDV salvos com sucesso!")
            except ValidationError as ve:
                msg = ve.message if hasattr(ve, 'message') else str(ve)
                messages.error(request, msg)
            except Exception as e:
                messages.error(request, f"Erro ao salvar atalhos: {str(e)}")

        # 6. Restaurar Atalhos Padrão do PDV
        elif action == 'restaurar_padroes_atalhos':
            dados_anteriores = ConfiguracaoAtalhoPDV.get_atalhos_empresa(empresa)
            ConfiguracaoAtalhoPDV.restaurar_padroes(empresa)
            AuditService.registrar(
                empresa=empresa,
                usuario=request.user,
                acao='ATALHOS_PDV_ALTERADOS',
                entidade='ConfiguracaoAtalhoPDV',
                entidade_id=empresa.id,
                descricao=f"Atalhos de teclado do PDV da empresa '{empresa.nome_fantasia}' foram restaurados para o padrão de fábrica.",
                dados_anteriores=dados_anteriores,
                dados_posteriores=ConfiguracaoAtalhoPDV.get_padroes_dict()
            )
            messages.success(request, "Atalhos do PDV restaurados para os padrões originais com sucesso!")

        return redirect('configuracoes')

    context = {
        'empresa': empresa,
        'config_visual': config_visual,
        'atalhos_pdv': ConfiguracaoAtalhoPDV.get_atalhos_detalhados(empresa),
        'teclas_permitidas': ConfiguracaoAtalhoPDV.TECLAS_PERMITIDAS,
    }
    return render(request, 'empresas/configuracoes.html', context)
