import random
import uuid
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone

from apps.produtos.models import Produto, Categoria
from apps.clientes.models import Cliente
from apps.caixas.models import Caixa, SessaoCaixa
from apps.vendas.models import Venda
from apps.vendas.services import SaleService

from .serializers import (
    ProdutoSerializer, ClienteSerializer, CaixaSerializer,
    SessaoCaixaSerializer, VendaSerializer, ProcessarVendaInputSerializer
)


class PingAPIView(APIView):
    """
    Heartbeat para checagem de conectividade real e validação de sessão ativa do PDV.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        empresa = getattr(request, 'tenant', None) or request.user.empresa
        sessao_caixa = SessaoCaixa.objects.filter(operador=request.user, empresa=empresa, status='ABERTA').first()
        return Response({
            'status': 'online',
            'timestamp': timezone.now().isoformat(),
            'empresa_id': empresa.id if empresa else None,
            'empresa_nome': empresa.nome_fantasia if empresa else '',
            'usuario': request.user.username,
            'caixa_aberto': sessao_caixa is not None,
            'sessao_caixa_id': sessao_caixa.id if sessao_caixa else None
        }, status=status.HTTP_200_OK)


class PDVCatalogOfflineAPIView(APIView):
    """
    Exporta catálogo de produtos e clientes ativos do tenant para carga no IndexedDB local do PDV.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        empresa = getattr(request, 'tenant', None) or request.user.empresa
        produtos = Produto.objects.filter(empresa=empresa, ativo=True).values(
            'id', 'nome', 'codigo_barras', 'sku', 'preco_venda', 'preco_custo',
            'estoque_atual', 'unidade_medida', 'controle_estoque'
        )
        clientes = Cliente.objects.filter(empresa=empresa, ativo=True).values(
            'id', 'nome', 'cpf_cnpj', 'telefone', 'limite_credito', 'saldo_devedor'
        )
        return Response({
            'empresa_id': empresa.id if empresa else None,
            'produtos': list(produtos),
            'clientes': list(clientes),
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_200_OK)



class ProdutoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProdutoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        empresa = getattr(self.request, 'tenant', None) or self.request.user.empresa
        qs = Produto.objects.filter(empresa=empresa, ativo=True)
        query = self.request.query_params.get('q', '')
        if query:
            qs = qs.filter(Q(codigo_barras__icontains=query) | Q(nome__icontains=query) | Q(sku__icontains=query))
        return qs


class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClienteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        empresa = getattr(self.request, 'tenant', None) or self.request.user.empresa
        qs = Cliente.objects.filter(empresa=empresa, ativo=True)
        query = self.request.query_params.get('q', '')
        if query:
            qs = qs.filter(Q(nome__icontains=query) | Q(cpf_cnpj__icontains=query) | Q(telefone__icontains=query))
        return qs


class VendaViewSet(viewsets.ModelViewSet):
    serializer_class = VendaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        empresa = getattr(self.request, 'tenant', None) or self.request.user.empresa
        return Venda.objects.filter(empresa=empresa).order_by('-id')

    def create(self, request, *args, **kwargs):
        serializer = ProcessarVendaInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        empresa = getattr(request, 'tenant', None) or request.user.empresa
        operador = request.user

        sessao_caixa = None
        if data.get('sessao_caixa_id'):
            sessao_caixa = SessaoCaixa.objects.filter(id=data['sessao_caixa_id'], empresa=empresa).first()
        else:
            # Busca última sessão aberta do operador
            sessao_caixa = SessaoCaixa.objects.filter(operador=operador, empresa=empresa, status='ABERTA').first()

        cliente = None
        if data.get('cliente_id'):
            cliente = Cliente.objects.filter(id=data['cliente_id'], empresa=empresa).first()

        try:
            venda = SaleService.processar_venda(
                empresa=empresa,
                operador=operador,
                sessao_caixa=sessao_caixa,
                itens_data=data.get('itens', []),
                pagamentos_data=data['pagamentos'],
                cliente=cliente,
                desconto=data.get('desconto', 0.00),
                offline_uuid=data.get('offline_uuid', ''),
                observacao=data.get('observacao', ''),
                recebimento_divida=data.get('recebimento_divida')
            )
            if isinstance(venda, Venda):
                return Response(VendaSerializer(venda).data, status=status.HTTP_201_CREATED)
            return Response(venda, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PDVSyncAPIView(APIView):
    """
    Endpoint para receber sincronização em lote de vendas pendentes registradas offline no PWA.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        vendas_offline = request.data.get('vendas', [])
        if not isinstance(vendas_offline, list):
            return Response({'error': 'Formato inválido. Esperado uma lista de vendas.'}, status=status.HTTP_400_BAD_REQUEST)

        empresa = getattr(request, 'tenant', None) or request.user.empresa
        operador = request.user
        sessao_caixa = SessaoCaixa.objects.filter(operador=operador, empresa=empresa, status='ABERTA').first()

        sincronizadas = []
        erros = []

        for item_venda in vendas_offline:
            serializer = ProcessarVendaInputSerializer(data=item_venda)
            if not serializer.is_valid():
                erros.append({'offline_uuid': item_venda.get('offline_uuid'), 'erros': serializer.errors})
                continue

            data = serializer.validated_data
            cliente = None
            if data.get('cliente_id'):
                cliente = Cliente.objects.filter(id=data['cliente_id'], empresa=empresa).first()

            try:
                venda = SaleService.processar_venda(
                    empresa=empresa,
                    operador=operador,
                    sessao_caixa=sessao_caixa,
                    itens_data=data.get('itens', []),
                    pagamentos_data=data['pagamentos'],
                    cliente=cliente,
                    desconto=data.get('desconto', 0.00),
                    offline_uuid=data.get('offline_uuid', ''),
                    observacao=data.get('observacao', ''),
                    recebimento_divida=data.get('recebimento_divida')
                )
                if isinstance(venda, Venda):
                    sincronizadas.append(VendaSerializer(venda).data)
                else:
                    sincronizadas.append(venda)
            except Exception as e:
                erros.append({'offline_uuid': data.get('offline_uuid'), 'error': str(e)})

        return Response({
            'status': 'sucesso',
            'total_sincronizadas': len(sincronizadas),
            'vendas': sincronizadas,
            'erros': erros
        }, status=status.HTTP_200_OK)


class TEFSimulateAPIView(APIView):
    """
    Simulador de autorização TEF para pagamento com Cartão Débito/Crédito.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tipo_cartao = request.data.get('tipo', 'CREDITO')
        valor = request.data.get('valor', 0.00)
        
        # Simula aprovação imediata com código de autorização e NSU fictícios
        nsu = f"{random.randint(100000000, 999999999)}"
        cod_autorizacao = f"AUTH{random.randint(100000, 999999)}"
        
        return Response({
            'sucesso': True,
            'mensagem': 'Transação TEF Aprovada com Sucesso!',
            'nsu': nsu,
            'codigo_autorizacao': cod_autorizacao,
            'bandeira': 'VISA' if random.choice([True, False]) else 'MASTERCARD',
            'tipo': tipo_cartao,
            'valor': valor
        }, status=status.HTTP_200_OK)


class PixGenerateAPIView(APIView):
    """
    Gera Payload PIX estático/dinâmico e chave para montagem do QR Code.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        valor = request.data.get('valor', '0.00')
        empresa = getattr(request, 'tenant', None) or request.user.empresa
        
        txid = f"PIX{uuid.uuid4().hex[:12].upper()}"
        chave_pix = empresa.cnpj or "financeiro@empresa.com.br"
        
        # Payload PIX EMV Padrão Simplificado
        payload = f"00020126360014BR.GOV.BCB.PIX0114{chave_pix}5204000053039865404{valor}5802BR5915{empresa.nome_fantasia[:15]}6009SAOPAULO62070503***6304"

        return Response({
            'sucesso': True,
            'txid': txid,
            'chave_pix': chave_pix,
            'valor': valor,
            'qrcode_payload': payload
        }, status=status.HTTP_200_OK)


class ContasPendentesClienteAPIView(APIView):
    """
    Lista contas a receber pendentes do cliente para o modal Receber Dívida no PDV.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, cliente_id):
        empresa = getattr(request, 'tenant', None) or request.user.empresa
        cliente = get_object_or_404(Cliente, id=cliente_id, empresa=empresa)
        from apps.financeiro.models import ContaReceber

        contas = ContaReceber.objects.filter(
            empresa=empresa,
            cliente=cliente,
            status__in=['ABERTA', 'PARCIAL', 'PENDENTE']
        ).order_by('data_vencimento')

        data = [{
            'id': c.id,
            'descricao': c.descricao,
            'valor_original': float(c.valor_original or c.valor),
            'valor_pago': float(c.valor_pago),
            'saldo': float(c.saldo),
            'data_vencimento': c.data_vencimento.strftime('%d/%m/%Y'),
            'is_vencida': c.is_vencida,
            'status': c.status_display_calculado
        } for c in contas if c.saldo > 0]

        total_divida_consolidada = sum((c['saldo'] for c in data), 0.0)

        return Response({
            'cliente': cliente.nome,
            'cliente_id': cliente.id,
            'limite_credito': float(cliente.limite_credito),
            'saldo_devedor': float(cliente.saldo_devedor),
            'total_divida': total_divida_consolidada,
            'total_contas': len(data),
            'credito_disponivel': float(cliente.credito_disponivel),
            'contas': data
        }, status=status.HTTP_200_OK)


class ReceberDividaAPIView(APIView):
    """
    Registra o pagamento (parcial ou integral) de uma conta a receber de crediário diretamente no PDV.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        empresa = getattr(request, 'tenant', None) or request.user.empresa
        conta_id = request.data.get('conta_id')
        valor_pago = request.data.get('valor_pago')
        forma_pagamento = request.data.get('forma_pagamento', 'DINHEIRO')
        troco = request.data.get('troco', 0.00)

        from apps.financeiro.models import ContaReceber
        from apps.financeiro.services import FinancialService
        from apps.caixas.models import SessaoCaixa

        conta = get_object_or_404(ContaReceber, id=conta_id, empresa=empresa)
        sessao_caixa = SessaoCaixa.objects.filter(empresa=empresa, operador=request.user, status='ABERTA').first()

        try:
            val_pago_final = float(valor_pago) if valor_pago is not None else float(conta.saldo)
            pag = FinancialService.receber_pagamento_conta(
                conta=conta,
                valor_pago=val_pago_final,
                forma_pagamento=forma_pagamento,
                troco=float(troco),
                sessao_caixa=sessao_caixa,
                usuario=request.user
            )
            conta.refresh_from_db()
            return Response({
                'sucesso': True,
                'mensagem': f"Pagamento de R$ {pag.valor_efetivo:.2f} registrado com sucesso para a conta #{conta.id}!",
                'novo_saldo_conta': float(conta.saldo),
                'status_conta': conta.status_display_calculado,
                'novo_saldo_devedor': float(conta.cliente.saldo_devedor if conta.cliente else 0.00)
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

