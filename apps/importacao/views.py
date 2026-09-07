import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.usuarios.permissions import cargo_required
from .models import HistoricoImportacao
from .services import ImportService


@login_required
@cargo_required('ADMIN', 'GERENTE')
def importacao_hub(request):
    """Página principal da Central de Importação de Dados JSON."""
    empresa = getattr(request, 'tenant', None) or request.user.empresa
    historico = HistoricoImportacao.objects.filter(empresa=empresa).order_by('-data_hora')[:15]
    
    context = {
        'historico': historico,
        'empresa': empresa
    }
    return render(request, 'importacao/hub.html', context)


@login_required
@cargo_required('ADMIN', 'GERENTE')
@require_POST
def importacao_upload(request):
    """Recebe o arquivo JSON e realiza a análise estrutural preliminar."""
    if 'arquivo_json' not in request.FILES:
        messages.error(request, "Por favor, selecione um arquivo JSON para upload.")
        return redirect('importacao_hub')

    json_file = request.FILES['arquivo_json']
    nome_arquivo = json_file.name
    tamanho_bytes = json_file.size

    analise = ImportService.analisar_json(json_file)

    if not analise['valido']:
        messages.error(request, f"Arquivo JSON inválido: {analise.get('erro')}")
        return redirect('importacao_hub')

    # Armazena metadados e registros na sessão para a etapa de mapeamento
    request.session['importacao_dados'] = {
        'nome_arquivo': nome_arquivo,
        'tamanho_bytes': tamanho_bytes,
        'hash_sha256': analise['hash_sha256'],
        'total_registros': analise['total_registros'],
        'tipo_sugerido': analise['tipo_sugerido'],
        'campos_detectados': analise['campos_detectados'],
        'tipos_campos': analise['tipos_campos'],
        'mapeamento_sugerido': analise['mapeamento_sugerido'],
        'amostra_registros': analise['amostra_registros'],
        'registros': analise['registros_completos']
    }

    return redirect('importacao_mapeamento')


@login_required
@cargo_required('ADMIN', 'GERENTE')
def importacao_mapeamento(request):
    """Interface de configuração de mapeamento de campos e estratégia de identificação."""
    dados_sessao = request.session.get('importacao_dados')
    if not dados_sessao:
        messages.warning(request, "Nenhum arquivo em análise. Envie um arquivo JSON para iniciar.")
        return redirect('importacao_hub')

    empresa = getattr(request, 'tenant', None) or request.user.empresa

    context = {
        'nome_arquivo': dados_sessao['nome_arquivo'],
        'total_registros': dados_sessao['total_registros'],
        'tipo_sugerido': dados_sessao['tipo_sugerido'],
        'campos_detectados': dados_sessao['campos_detectados'],
        'tipos_campos': dados_sessao['tipos_campos'],
        'mapeamento_sugerido': dados_sessao['mapeamento_sugerido'],
        'amostra_registros': dados_sessao['amostra_registros'],
        'empresa': empresa
    }
    return render(request, 'importacao/mapeamento.html', context)


@login_required
@cargo_required('ADMIN', 'GERENTE')
@require_POST
def importacao_validar_api(request):
    """Endpoint AJAX para executar simulação de validação (dry-run)."""
    dados_sessao = request.session.get('importacao_dados')
    if not dados_sessao:
        return JsonResponse({'sucesso': False, 'erro': 'Sessão expirada.'}, status=400)

    try:
        payload = json.loads(request.body.decode('utf-8'))
        tipo_entidade = payload.get('tipo_entidade', dados_sessao['tipo_sugerido'])
        mapeamento = payload.get('mapeamento', {})
        estrategia_id = payload.get('estrategia_identificacao', 'codigo_barras')

        empresa = getattr(request, 'tenant', None) or request.user.empresa
        registros = dados_sessao.get('registros', [])

        resultado = ImportService.validar_dados(
            registros=registros,
            tipo_entidade=tipo_entidade,
            mapeamento=mapeamento,
            estrategia_identificacao=estrategia_id,
            empresa=empresa
        )

        return JsonResponse({'sucesso': True, 'resultado': resultado})
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)


@login_required
@cargo_required('ADMIN', 'GERENTE')
@require_POST
def importacao_executar(request):
    """Execução definitiva da importação com gravação no banco e histórico."""
    dados_sessao = request.session.get('importacao_dados')
    if not dados_sessao:
        messages.error(request, "Sessão de importação expirada. Envie o arquivo novamente.")
        return redirect('importacao_hub')

    tipo_entidade = request.POST.get('tipo_entidade', dados_sessao['tipo_sugerido'])
    estrategia_id = request.POST.get('estrategia_identificacao', 'codigo_barras')

    # Reconstrói dicionário de mapeamento a partir do POST
    mapeamento = {}
    for key, val in request.POST.items():
        if key.startswith('map_') and val:
            campo_modelo = key.replace('map_', '')
            mapeamento[campo_modelo] = val

    empresa = getattr(request, 'tenant', None) or request.user.empresa
    registros = dados_sessao.get('registros', [])

    try:
        historico = ImportService.executar_importacao(
            registros=registros,
            tipo_entidade=tipo_entidade,
            mapeamento=mapeamento,
            estrategia_identificacao=estrategia_id,
            empresa=empresa,
            usuario=request.user,
            nome_arquivo=dados_sessao['nome_arquivo'],
            hash_arquivo=dados_sessao['hash_sha256'],
            tamanho_bytes=dados_sessao['tamanho_bytes']
        )

        # Limpa dados da sessão
        if 'importacao_dados' in request.session:
            del request.session['importacao_dados']

        messages.success(request, f"Importação finalizada! Status: {historico.get_status_display()}. {historico.quantidade_criada} criados, {historico.quantidade_atualizada} atualizados.")
        return redirect('importacao_detalhe', importacao_id=historico.id)
    except Exception as e:
        messages.error(request, f"Erro crítico durante a importação: {str(e)}")
        return redirect('importacao_mapeamento')


@login_required
@cargo_required('ADMIN', 'GERENTE')
def importacao_detalhe(request, importacao_id):
    """Exibe relatório detalhado do resultado e erros de uma importação."""
    empresa = getattr(request, 'tenant', None) or request.user.empresa
    historico = get_object_or_404(HistoricoImportacao, id=importacao_id, empresa=empresa)

    context = {
        'historico': historico,
        'empresa': empresa
    }
    return render(request, 'importacao/detalhes.html', context)


@login_required
@cargo_required('ADMIN', 'GERENTE')
def importacao_exportar(request):
    """
    Gera e entrega para download o arquivo JSON estruturado contendo os dados da empresa,
    com respeito rigoroso ao isolamento multi-tenant e sem expor dados sensíveis.
    """
    from django.http import HttpResponse
    from django.utils.text import slugify
    from django.utils import timezone
    from .services import ExportService

    empresa = getattr(request, 'tenant', None) or request.user.empresa

    if request.method == 'POST':
        escopos = request.POST.getlist('escopos')
    else:
        escopos_param = request.GET.get('escopos', '')
        escopos = [e.strip().upper() for e in escopos_param.split(',') if e.strip()] if escopos_param else []

    if not escopos:
        escopos = ['PRODUTOS', 'CATEGORIAS', 'CLIENTES', 'FORNECEDORES']

    export_dict = ExportService.exportar_dados(empresa=empresa, escopos=escopos)
    json_content = json.dumps(export_dict, ensure_ascii=False, indent=2)

    empresa_slug = slugify(empresa.nome_fantasia or empresa.razao_social or 'empresa')
    timestamp_str = timezone.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{empresa_slug}_exportacao_{timestamp_str}.json"

    response = HttpResponse(json_content, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

