"""
ImportService — Módulo Central de Importação de Dados JSON
Arquitetura genérica, resiliente, segura e com suporte a grandes volumes,
validação semântica, isolamento multi-tenant, normalização e idempotência.
"""
from decimal import Decimal, InvalidOperation
import json
import hashlib
import re
from datetime import datetime
from django.db import transaction
from django.utils import timezone

from apps.empresas.models import Empresa
from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente, Fornecedor
from apps.core.models import AuditService
from .models import HistoricoImportacao



class ImportService:
    """
    Serviço centralizado para ingestão, análise, mapeamento, validação e
    execução transacional de importações de arquivos JSON para o PDV/ERP.
    """

    # Sinônimos padrão para auto-mapeamento de campos
    SINONIMOS_CAMPOS = {
        'PRODUTOS': {
            'nome': ['nome', 'descricao', 'produto', 'title', 'name', 'desc', 'item_nome', 'nm_produto'],
            'codigo_barras': ['codigo_barras', 'codigo_de_barras', 'barcode', 'ean', 'gtin', 'cod_barras', 'codigo', 'cod_ean'],
            'sku': ['sku', 'codigo_interno', 'cod_interno', 'referencia', 'ref', 'cprod'],
            'preco_venda': ['preco_venda', 'preco', 'valor_venda', 'price', 'valor', 'pv', 'venda', 'vuncom'],
            'preco_custo': ['preco_custo', 'custo', 'cost_price', 'pc', 'valor_custo'],
            'estoque_atual': ['estoque_atual', 'estoque', 'qtd', 'quantidade', 'stock', 'qtd_estoque', 'saldo', 'qcom'],
            'estoque_minimo': ['estoque_minimo', 'min_stock', 'estoque_min', 'minimo'],
            'unidade_medida': ['unidade_medida', 'unidade', 'un', 'unit', 'medida', 'uom', 'ucom'],
            'categoria': ['categoria', 'categoria_nome', 'category', 'grupo', 'depto', 'departamento', 'secao'],
            'fornecedor': ['fornecedor', 'fornecedor_nome', 'supplier', 'fabricante', 'marca'],
            'ncm': ['ncm', 'cod_ncm'],
            'ativo': ['ativo', 'active', 'status', 'habilitado']
        },
        'CLIENTES': {
            'nome': ['nome', 'razao_social', 'cliente', 'name', 'nome_completo', 'xnome'],
            'cpf_cnpj': ['cpf_cnpj', 'cpf', 'cnpj', 'documento', 'doc', 'identificacao', 'nr_documento'],
            'telefone': ['telefone', 'tel', 'phone', 'celular', 'cel', 'fone'],
            'email': ['email', 'e_mail', 'mail', 'correio_eletronico'],
            'endereco': ['endereco', 'logradouro', 'address', 'rua', 'xlgr'],
            'cidade': ['cidade', 'city', 'municipio', 'xmun'],
            'estado': ['estado', 'uf', 'state'],
            'limite_credito': ['limite_credito', 'limite', 'credit_limit', 'credito'],
            'ativo': ['ativo', 'active', 'status']
        },
        'FORNECEDORES': {
            'razao_social': ['razao_social', 'nome', 'empresa', 'fornecedor', 'supplier', 'xnome'],
            'nome_fantasia': ['nome_fantasia', 'fantasia', 'trade_name', 'xfant'],
            'cnpj': ['cnpj', 'cpf_cnpj', 'documento', 'doc', 'nr_documento'],
            'telefone': ['telefone', 'celular', 'phone', 'tel'],
            'email': ['email', 'e_mail', 'mail'],
            'contato': ['contato', 'responsavel', 'contact'],
            'cidade': ['cidade', 'municipio'],
            'estado': ['estado', 'uf'],
            'ativo': ['ativo', 'status']
        },
        'CATEGORIAS': {
            'nome': ['nome', 'categoria', 'category', 'descricao', 'grupo'],
            'ativo': ['ativo', 'status']
        }
    }

    # =========================================================================
    # 1. ANÁLISE ESTATÍSTICA E DETECÇÃO DE ESTRUTURA DO JSON
    # =========================================================================

    @staticmethod
    def analisar_json(arquivo_ou_conteudo, max_preview=10) -> dict:
        """
        Recebe stream/arquivo ou string/dict JSON, detecta a estrutura, chaves,
        tipos de dados e sugere a entidade e mapeamento correspondentes.
        """
        raw_data = None
        hash_sha256 = ""

        try:
            if hasattr(arquivo_ou_conteudo, 'read'):
                content_bytes = arquivo_ou_conteudo.read()
                if isinstance(content_bytes, str):
                    content_bytes = content_bytes.encode('utf-8')
                hash_sha256 = hashlib.sha256(content_bytes).hexdigest()
                raw_data = json.loads(content_bytes.decode('utf-8'))
            elif isinstance(arquivo_ou_conteudo, (str, bytes)):
                if isinstance(arquivo_ou_conteudo, str):
                    content_bytes = arquivo_ou_conteudo.encode('utf-8')
                else:
                    content_bytes = arquivo_ou_conteudo
                hash_sha256 = hashlib.sha256(content_bytes).hexdigest()
                raw_data = json.loads(content_bytes.decode('utf-8'))
            elif isinstance(arquivo_ou_conteudo, (dict, list)):
                raw_data = arquivo_ou_conteudo
                content_bytes = json.dumps(raw_data).encode('utf-8')
                hash_sha256 = hashlib.sha256(content_bytes).hexdigest()
            else:
                return {
                    'valido': False,
                    'erro': 'Tipo de entrada não suportado para análise JSON.'
                }
        except json.JSONDecodeError as jde:
            return {
                'valido': False,
                'erro': f'Arquivo JSON malformatado ou inválido (Linha {jde.lineno}, Coluna {jde.colno}): {jde.msg}'
            }
        except Exception as ex:
            return {
                'valido': False,
                'erro': f'Erro ao ler conteúdo do arquivo JSON: {str(ex)}'
            }

        # Identificação de estrutura (List, Dict de Seções, ou Objeto Único)
        secoes = {}
        registros_principais = []
        tipo_sugerido = 'PRODUTOS'

        if isinstance(raw_data, list):
            registros_principais = raw_data
            secoes['raiz'] = len(raw_data)
        elif isinstance(raw_data, dict):
            # Procura por listas internas conhecidas
            listas_encontradas = {k: v for k, v in raw_data.items() if isinstance(v, list)}
            if listas_encontradas:
                secoes = {k: len(v) for k, v in listas_encontradas.items()}
                # Seleciona a maior lista ou a primeira
                chave_principal = max(listas_encontradas, key=lambda k: len(listas_encontradas[k]))
                registros_principais = listas_encontradas[chave_principal]
                if 'produto' in chave_principal.lower() or 'item' in chave_principal.lower():
                    tipo_sugerido = 'PRODUTOS'
                elif 'cliente' in chave_principal.lower() or 'customer' in chave_principal.lower():
                    tipo_sugerido = 'CLIENTES'
                elif 'fornecedor' in chave_principal.lower() or 'supplier' in chave_principal.lower():
                    tipo_sugerido = 'FORNECEDORES'
                elif 'categoria' in chave_principal.lower() or 'category' in chave_principal.lower():
                    tipo_sugerido = 'CATEGORIAS'
            else:
                # Objeto único
                registros_principais = [raw_data]
                secoes['objeto_unico'] = 1

        # Extrai todas as chaves e tipos encontrados nos registros
        todos_campos = set()
        tipos_campos = {}
        for r in registros_principais[:100]:
            if isinstance(r, dict):
                for k, v in r.items():
                    todos_campos.add(k)
                    if k not in tipos_campos:
                        tipos_campos[k] = type(v).__name__

        campos_lista = sorted(list(todos_campos))

        # Refina dedução do tipo_sugerido pelos campos encontrados
        campos_lower = [c.lower() for c in campos_lista]
        if any(c in campos_lower for c in ['preco_venda', 'preco', 'estoque', 'codigo_barras', 'sku', 'ean']):
            tipo_sugerido = 'PRODUTOS'
        elif any(c in campos_lower for c in ['cpf_cnpj', 'cpf', 'limite_credito', 'saldo_devedor']):
            tipo_sugerido = 'CLIENTES'
        elif any(c in campos_lower for c in ['razao_social', 'cnpj', 'contato']) and not any(c in campos_lower for c in ['preco_venda', 'estoque']):
            tipo_sugerido = 'FORNECEDORES'

        # Auto-mapeamento sugerido
        mapeamento_sugerido = ImportService.mapear_campos_sugeridos(campos_lista, tipo_sugerido)

        return {
            'valido': True,
            'hash_sha256': hash_sha256,
            'total_registros': len(registros_principais),
            'secoes': secoes,
            'tipo_sugerido': tipo_sugerido,
            'campos_detectados': campos_lista,
            'tipos_campos': tipos_campos,
            'mapeamento_sugerido': mapeamento_sugerido,
            'amostra_registros': registros_principais[:max_preview],
            'registros_completos': registros_principais
        }

    # =========================================================================
    # 2. SUGESTÃO INTELIGENTE DE MAPEAMENTO DE CAMPOS
    # =========================================================================

    @staticmethod
    def mapear_campos_sugeridos(campos_detectados: list, tipo_entidade: str) -> dict:
        """Gera dicionário {campo_modelo: campo_json} com base na tabela de sinônimos."""
        mapeamento = {}
        sinonimos = ImportService.SINONIMOS_CAMPOS.get(tipo_entidade, {})

        campos_detectados_lower = {c.lower(): c for c in campos_detectados}

        for campo_modelo, lista_sinonimos in sinonimos.items():
            for sin in lista_sinonimos:
                if sin in campos_detectados_lower:
                    mapeamento[campo_modelo] = campos_detectados_lower[sin]
                    break

        return mapeamento

    # =========================================================================
    # 3. NORMALIZAÇÃO E SANITIZAÇÃO DE DADOS
    # =========================================================================

    @staticmethod
    def normalizar_moeda(valor) -> Decimal:
        """Converte strings, floats e inteiros em Decimal com 2 casas decimais."""
        if valor is None or valor == '':
            return Decimal('0.00')
        if isinstance(valor, Decimal):
            return valor.quantize(Decimal('0.01'))
        if isinstance(valor, (int, float)):
            return Decimal(str(valor)).quantize(Decimal('0.01'))

        val_str = str(valor).strip()
        # Remove símbolos de moeda 'R$', '$'
        val_str = re.sub(r'[R$\s]', '', val_str)

        # Se tiver vírgula e ponto (ex: '1.234,56'), converte para formato americano ('1234.56')
        if ',' in val_str and '.' in val_str:
            if val_str.find('.') < val_str.find(','):
                val_str = val_str.replace('.', '').replace(',', '.')
            else:
                val_str = val_str.replace(',', '')
        elif ',' in val_str:
            val_str = val_str.replace(',', '.')

        try:
            return Decimal(val_str).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError):
            raise ValueError(f"Valor monetário inválido: '{valor}'")

    @staticmethod
    def normalizar_quantidade(valor) -> Decimal:
        """Converte quantidade para Decimal com até 3 casas decimais."""
        if valor is None or valor == '':
            return Decimal('0.000')
        if isinstance(valor, Decimal):
            return valor
        if isinstance(valor, (int, float)):
            return Decimal(str(valor))

        val_str = str(valor).strip().replace(',', '.')
        try:
            return Decimal(val_str)
        except (InvalidOperation, ValueError):
            raise ValueError(f"Quantidade inválida: '{valor}'")

    @staticmethod
    def normalizar_documento(doc) -> str:
        """Sanitiza CPF ou CNPJ removendo pontuações."""
        if not doc:
            return ""
        return re.sub(r'\D', '', str(doc)).strip()

    @staticmethod
    def normalizar_codigo_barras(codigo) -> str:
        """Sanitiza código de barras / EAN."""
        if not codigo:
            return ""
        return str(codigo).strip()

    @staticmethod
    def normalizar_booleano(valor) -> bool:
        """Converte representações variadas em booleano estrito."""
        if isinstance(valor, bool):
            return valor
        if isinstance(valor, (int, float)):
            return valor != 0
        val_str = str(valor).strip().lower()
        return val_str in ['true', '1', 'sim', 's', 'ativo', 'active', 'yes', 'y']

    # =========================================================================
    # 4. VALIDAÇÃO PRÉVIA (DRY-RUN / SUMMARY)
    # =========================================================================

    @staticmethod
    def validar_dados(
        registros: list,
        tipo_entidade: str,
        mapeamento: dict,
        estrategia_identificacao: str,
        empresa: Empresa
    ) -> dict:
        """
        Executa a validação em modo simulação (sem gravar no banco de dados).
        Retorna estatísticas consolidadas e o relatório detalhado de erros por linha.
        """
        total = len(registros)
        validos = 0
        invalidos = 0
        serao_criados = 0
        serao_atualizados = 0
        conflitos = 0
        erros_detalhados = []

        # Cache de identificadores existentes no tenant
        identificadores_existentes = set()

        if tipo_entidade == 'PRODUTOS':
            if estrategia_identificacao == 'codigo_barras':
                identificadores_existentes = set(
                    Produto.objects.filter(empresa=empresa).exclude(codigo_barras='').values_list('codigo_barras', flat=True)
                )
            elif estrategia_identificacao == 'sku':
                identificadores_existentes = set(
                    Produto.objects.filter(empresa=empresa).exclude(sku='').values_list('sku', flat=True)
                )
        elif tipo_entidade == 'CLIENTES':
            if estrategia_identificacao == 'cpf_cnpj':
                identificadores_existentes = set(
                    Cliente.objects.filter(empresa=empresa).exclude(cpf_cnpj='').values_list('cpf_cnpj', flat=True)
                )
        elif tipo_entidade == 'FORNECEDORES':
            if estrategia_identificacao == 'cnpj':
                identificadores_existentes = set(
                    Fornecedor.objects.filter(empresa=empresa).exclude(cnpj='').values_list('cnpj', flat=True)
                )

        identificadores_no_lote = set()

        for idx, reg in enumerate(registros, start=1):
            if not isinstance(reg, dict):
                invalidos += 1
                erros_detalhados.append({
                    'linha': idx,
                    'campo': 'estrutura',
                    'valor_recebido': str(reg),
                    'erro': 'Registro não é um objeto JSON válido.'
                })
                continue

            erros_registro = []

            # 1. Validação de campos obrigatórios conforme entidade
            if tipo_entidade == 'PRODUTOS':
                campo_nome = mapeamento.get('nome')
                nome_val = reg.get(campo_nome) if campo_nome else reg.get('nome')
                if not nome_val or str(nome_val).strip() == '':
                    erros_registro.append({'campo': 'nome', 'valor': str(nome_val), 'erro': 'Nome do produto é obrigatório.'})

                # Preço de Venda
                campo_preco = mapeamento.get('preco_venda')
                if campo_preco and campo_preco in reg:
                    try:
                        preco_dec = ImportService.normalizar_moeda(reg[campo_preco])
                        if preco_dec < Decimal('0.00'):
                            erros_registro.append({'campo': 'preco_venda', 'valor': str(reg[campo_preco]), 'erro': 'Preço de venda não pode ser negativo.'})
                    except Exception as e:
                        erros_registro.append({'campo': 'preco_venda', 'valor': str(reg[campo_preco]), 'erro': str(e)})

                # Preço de Custo
                campo_custo = mapeamento.get('preco_custo')
                if campo_custo and campo_custo in reg:
                    try:
                        ImportService.normalizar_moeda(reg[campo_custo])
                    except Exception as e:
                        erros_registro.append({'campo': 'preco_custo', 'valor': str(reg[campo_custo]), 'erro': str(e)})

                # Estoque
                campo_estoque = mapeamento.get('estoque_atual')
                if campo_estoque and campo_estoque in reg:
                    try:
                        ImportService.normalizar_quantidade(reg[campo_estoque])
                    except Exception as e:
                        erros_registro.append({'campo': 'estoque_atual', 'valor': str(reg[campo_estoque]), 'erro': str(e)})

            elif tipo_entidade == 'CLIENTES':
                campo_nome = mapeamento.get('nome')
                nome_val = reg.get(campo_nome) if campo_nome else reg.get('nome')
                if not nome_val or str(nome_val).strip() == '':
                    erros_registro.append({'campo': 'nome', 'valor': str(nome_val), 'erro': 'Nome do cliente é obrigatório.'})

            elif tipo_entidade == 'FORNECEDORES':
                campo_razao = mapeamento.get('razao_social')
                razao_val = reg.get(campo_razao) if campo_razao else reg.get('razao_social')
                if not razao_val or str(razao_val).strip() == '':
                    erros_registro.append({'campo': 'razao_social', 'valor': str(razao_val), 'erro': 'Razão social do fornecedor é obrigatória.'})

            # 2. Verificação de Chave de Identificação (Criação vs Atualização vs Duplicidade no Lote)
            chave_mapeada = mapeamento.get(estrategia_identificacao)
            valor_identificador = str(reg.get(chave_mapeada, '')).strip() if chave_mapeada else ''

            if valor_identificador:
                if valor_identificador in identificadores_no_lote:
                    conflitos += 1
                    erros_registro.append({
                        'campo': estrategia_identificacao,
                        'valor': valor_identificador,
                        'erro': f"Identificador '{valor_identificador}' duplicado dentro do próprio arquivo JSON."
                    })
                else:
                    identificadores_no_lote.add(valor_identificador)

            if erros_registro:
                invalidos += 1
                for err in erros_registro:
                    erros_detalhados.append({
                        'linha': idx,
                        'campo': err['campo'],
                        'valor_recebido': err['valor'],
                        'erro': err['erro']
                    })
            else:
                validos += 1
                if valor_identificador and valor_identificador in identificadores_existentes:
                    serao_atualizados += 1
                else:
                    serao_criados += 1

        return {
            'total': total,
            'validos': validos,
            'invalidos': invalidos,
            'serao_criados': serao_criados,
            'serao_atualizados': serao_atualizados,
            'conflitos': conflitos,
            'erros_detalhados': erros_detalhados
        }

    # =========================================================================
    # 5. EXECUÇÃO TRANSACIONAL DA IMPORTAÇÃO
    # =========================================================================

    @staticmethod
    def executar_importacao(
        registros: list,
        tipo_entidade: str,
        mapeamento: dict,
        estrategia_identificacao: str,
        empresa: Empresa,
        usuario=None,
        nome_arquivo: str = 'importacao.json',
        hash_arquivo: str = '',
        tamanho_bytes: int = 0
    ) -> HistoricoImportacao:
        """
        Executa a importação dentro de transação atômica.
        Garante isolamento multi-tenant estrito e registro na Trilha de Auditoria.
        """
        total = len(registros)
        criados = 0
        atualizados = 0
        rejeitados = 0
        erros_detalhados = []

        # Cache local de categorias e fornecedores para otimizar queries e evitar duplicatas
        categorias_cache = {c.nome.lower(): c for c in Categoria.objects.filter(empresa=empresa)}
        fornecedores_cache = {f.razao_social.lower(): f for f in Fornecedor.objects.filter(empresa=empresa)}

        with transaction.atomic():
            historico = HistoricoImportacao.objects.create(
                empresa=empresa,
                usuario=usuario,
                nome_arquivo=nome_arquivo,
                tamanho_bytes=tamanho_bytes,
                hash_arquivo=hash_arquivo,
                tipo_entidade=tipo_entidade,
                total_registros=total,
                mapeamento_utilizado=mapeamento,
                status='PENDENTE'
            )

            for idx, reg in enumerate(registros, start=1):
                if not isinstance(reg, dict):
                    rejeitados += 1
                    erros_detalhados.append({
                        'linha': idx,
                        'campo': 'estrutura',
                        'valor_recebido': str(reg),
                        'erro': 'Linha inválida (não é objeto JSON).'
                    })
                    continue

                try:
                    # =========================================================
                    # IMPORTAÇÃO: PRODUTOS
                    # =========================================================
                    if tipo_entidade == 'PRODUTOS':
                        campo_nome = mapeamento.get('nome', 'nome')
                        nome = str(reg.get(campo_nome, '')).strip()
                        if not nome:
                            raise ValueError("Nome do produto é obrigatório.")

                        # Chaves
                        campo_barcode = mapeamento.get('codigo_barras', 'codigo_barras')
                        barcode = ImportService.normalizar_codigo_barras(reg.get(campo_barcode, ''))

                        campo_sku = mapeamento.get('sku', 'sku')
                        sku = str(reg.get(campo_sku, '')).strip()

                        # Valores
                        campo_pv = mapeamento.get('preco_venda', 'preco_venda')
                        preco_venda = ImportService.normalizar_moeda(reg.get(campo_pv, 0.00))

                        campo_pc = mapeamento.get('preco_custo', 'preco_custo')
                        preco_custo = ImportService.normalizar_moeda(reg.get(campo_pc, 0.00))

                        campo_est = mapeamento.get('estoque_atual', 'estoque_atual')
                        estoque_atual = ImportService.normalizar_quantidade(reg.get(campo_est, 0.000))

                        campo_est_min = mapeamento.get('estoque_minimo', 'estoque_minimo')
                        estoque_minimo = ImportService.normalizar_quantidade(reg.get(campo_est_min, 0.000))

                        campo_un = mapeamento.get('unidade_medida', 'unidade_medida')
                        unidade_medida = str(reg.get(campo_un, 'UN')).strip() or 'UN'

                        campo_ncm = mapeamento.get('ncm', 'ncm')
                        ncm = str(reg.get(campo_ncm, '')).strip()

                        campo_ativo = mapeamento.get('ativo', 'ativo')
                        ativo = ImportService.normalizar_booleano(reg.get(campo_ativo, True))

                        # Relacionamento Categoria
                        categoria_obj = None
                        campo_cat = mapeamento.get('categoria', 'categoria')
                        cat_nome = str(reg.get(campo_cat, '')).strip()
                        if cat_nome:
                            cat_key = cat_nome.lower()
                            if cat_key in categorias_cache:
                                categoria_obj = categorias_cache[cat_key]
                            else:
                                categoria_obj, _ = Categoria.objects.get_or_create(
                                    empresa=empresa, nome=cat_nome
                                )
                                categorias_cache[cat_key] = categoria_obj

                        # Relacionamento Fornecedor
                        fornecedor_obj = None
                        campo_forn = mapeamento.get('fornecedor', 'fornecedor')
                        forn_nome = str(reg.get(campo_forn, '')).strip()
                        if forn_nome:
                            forn_key = forn_nome.lower()
                            if forn_key in fornecedores_cache:
                                fornecedor_obj = fornecedores_cache[forn_key]
                            else:
                                fornecedor_obj, _ = Fornecedor.objects.get_or_create(
                                    empresa=empresa, razao_social=forn_nome
                                )
                                fornecedores_cache[forn_key] = fornecedor_obj

                        # Busca por estratégia de identificação
                        produto_existente = None
                        if estrategia_identificacao == 'codigo_barras' and barcode:
                            produto_existente = Produto.objects.filter(empresa=empresa, codigo_barras=barcode).first()
                        elif estrategia_identificacao == 'sku' and sku:
                            produto_existente = Produto.objects.filter(empresa=empresa, sku=sku).first()

                        if produto_existente:
                            produto_existente.nome = nome
                            if sku: produto_existente.sku = sku
                            if barcode: produto_existente.codigo_barras = barcode
                            produto_existente.preco_venda = preco_venda
                            produto_existente.preco_custo = preco_custo
                            produto_existente.estoque_atual = estoque_atual
                            produto_existente.estoque_minimo = estoque_minimo
                            produto_existente.unidade_medida = unidade_medida
                            if categoria_obj: produto_existente.categoria = categoria_obj
                            if fornecedor_obj: produto_existente.fornecedor_principal = fornecedor_obj
                            produto_existente.ativo = ativo
                            produto_existente.save()
                            atualizados += 1
                        else:
                            Produto.objects.create(
                                empresa=empresa,
                                nome=nome,
                                codigo_barras=barcode,
                                sku=sku,
                                preco_venda=preco_venda,
                                preco_custo=preco_custo,
                                estoque_atual=estoque_atual,
                                estoque_minimo=estoque_minimo,
                                unidade_medida=unidade_medida,
                                categoria=categoria_obj,
                                fornecedor_principal=fornecedor_obj,
                                ativo=ativo
                            )
                            criados += 1

                    # =========================================================
                    # IMPORTAÇÃO: CLIENTES
                    # =========================================================
                    elif tipo_entidade == 'CLIENTES':
                        campo_nome = mapeamento.get('nome', 'nome')
                        nome = str(reg.get(campo_nome, '')).strip()
                        if not nome:
                            raise ValueError("Nome do cliente é obrigatório.")

                        campo_doc = mapeamento.get('cpf_cnpj', 'cpf_cnpj')
                        cpf_cnpj = ImportService.normalizar_documento(reg.get(campo_doc, ''))

                        campo_tel = mapeamento.get('telefone', 'telefone')
                        telefone = str(reg.get(campo_tel, '')).strip()

                        campo_mail = mapeamento.get('email', 'email')
                        email = str(reg.get(campo_mail, '')).strip()

                        campo_end = mapeamento.get('endereco', 'endereco')
                        endereco = str(reg.get(campo_end, '')).strip()

                        campo_cid = mapeamento.get('cidade', 'cidade')
                        cidade = str(reg.get(campo_cid, '')).strip()

                        campo_uf = mapeamento.get('estado', 'estado')
                        estado = str(reg.get(campo_uf, '')).strip()

                        campo_lim = mapeamento.get('limite_credito', 'limite_credito')
                        limite_credito = ImportService.normalizar_moeda(reg.get(campo_lim, 0.00))

                        campo_ativo = mapeamento.get('ativo', 'ativo')
                        ativo = ImportService.normalizar_booleano(reg.get(campo_ativo, True))

                        cliente_existente = None
                        if estrategia_identificacao == 'cpf_cnpj' and cpf_cnpj:
                            cliente_existente = Cliente.objects.filter(empresa=empresa, cpf_cnpj=cpf_cnpj).first()

                        if cliente_existente:
                            cliente_existente.nome = nome
                            if telefone: cliente_existente.telefone = telefone
                            if email: cliente_existente.email = email
                            if endereco: cliente_existente.endereco = endereco
                            if cidade: cliente_existente.cidade = cidade
                            if estado: cliente_existente.estado = estado
                            cliente_existente.limite_credito = limite_credito
                            cliente_existente.ativo = ativo
                            cliente_existente.save()
                            atualizados += 1
                        else:
                            Cliente.objects.create(
                                empresa=empresa,
                                nome=nome,
                                cpf_cnpj=cpf_cnpj,
                                telefone=telefone,
                                email=email,
                                endereco=endereco,
                                cidade=cidade,
                                estado=estado,
                                limite_credito=limite_credito,
                                ativo=ativo
                            )
                            criados += 1

                    # =========================================================
                    # IMPORTAÇÃO: FORNECEDORES
                    # =========================================================
                    elif tipo_entidade == 'FORNECEDORES':
                        campo_razao = mapeamento.get('razao_social', 'razao_social')
                        razao_social = str(reg.get(campo_razao, '')).strip()
                        if not razao_social:
                            raise ValueError("Razão social do fornecedor é obrigatória.")

                        campo_fantasia = mapeamento.get('nome_fantasia', 'nome_fantasia')
                        nome_fantasia = str(reg.get(campo_fantasia, '')).strip()

                        campo_cnpj = mapeamento.get('cnpj', 'cnpj')
                        cnpj = ImportService.normalizar_documento(reg.get(campo_cnpj, ''))

                        campo_tel = mapeamento.get('telefone', 'telefone')
                        telefone = str(reg.get(campo_tel, '')).strip()

                        campo_mail = mapeamento.get('email', 'email')
                        email = str(reg.get(campo_mail, '')).strip()

                        campo_cont = mapeamento.get('contato', 'contato')
                        contato_nome = str(reg.get(campo_cont, '')).strip()

                        forn_existente = None
                        if estrategia_identificacao == 'cnpj' and cnpj:
                            forn_existente = Fornecedor.objects.filter(empresa=empresa, cnpj=cnpj).first()

                        if forn_existente:
                            forn_existente.razao_social = razao_social
                            if nome_fantasia: forn_existente.nome_fantasia = nome_fantasia
                            if telefone: forn_existente.telefone = telefone
                            if email: forn_existente.email = email
                            if contato_nome: forn_existente.contato_nome = contato_nome
                            forn_existente.save()
                            atualizados += 1
                        else:
                            Fornecedor.objects.create(
                                empresa=empresa,
                                razao_social=razao_social,
                                nome_fantasia=nome_fantasia,
                                cnpj=cnpj,
                                telefone=telefone,
                                email=email,
                                contato_nome=contato_nome
                            )
                            criados += 1


                except Exception as row_err:
                    rejeitados += 1
                    erros_detalhados.append({
                        'linha': idx,
                        'campo': 'processamento',
                        'valor_recebido': str(reg),
                        'erro': str(row_err)
                    })

            # Atualiza histórico de importação
            historico.quantidade_criada = criados
            historico.quantidade_atualizada = atualizados
            historico.quantidade_rejeitada = rejeitados
            historico.detalhes_erros = erros_detalhados

            if rejeitados == 0:
                historico.status = 'PROCESSADO'
                historico.mensagem_status = f"Importação concluída com 100% de sucesso! {criados} criados, {atualizados} atualizados."
            elif criados > 0 or atualizados > 0:
                historico.status = 'PROCESSADO_COM_ERROS'
                historico.mensagem_status = f"Importação parcial: {criados} criados, {atualizados} atualizados, {rejeitados} rejeitados."
            else:
                historico.status = 'FALHA'
                historico.mensagem_status = f"Falha na importação: todos os {rejeitados} registros foram rejeitados."

            historico.save()

            # Trilha de Auditoria
            AuditService.registrar(
                empresa=empresa,
                usuario=usuario,
                acao='IMPORTACAO_DADOS',
                entidade='HistoricoImportacao',
                entidade_id=historico.id,
                descricao=f"Importação JSON de {tipo_entidade}: {criados} criados, {atualizados} atualizados, {rejeitados} rejeitados.",
                dados_posteriores={
                    'arquivo': nome_arquivo,
                    'tipo_entidade': tipo_entidade,
                    'total_registros': total,
                    'criados': criados,
                    'atualizados': atualizados,
                    'rejeitados': rejeitados,
                    'status': historico.status
                }
            )

        return historico
