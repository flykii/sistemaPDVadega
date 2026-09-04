"""
Módulo Central de Definição do Dia Operacional do Sistema PDV.
Regra de Negócio:
A virada do dia operacional NÃO ocorre à meia-noite (00:00), mas sim às 02:00:00 da manhã.
- 00:00:00 até 01:59:59.999999 pertence ao dia operacional anterior (D-1).
- 02:00:00 até 01:59:59.999999 do dia seguinte pertence ao dia operacional D.
"""
from datetime import date, datetime, time, timedelta
from django.utils import timezone

OPERATIONAL_CUTOFF_HOUR = 2  # 02:00:00


def get_operational_date(dt=None) -> date:
    """
    Retorna a data operacional (date) correspondente a um determinado datetime.
    Se dt for None, utiliza o datetime atual com o fuso horário ativo.
    """
    if dt is None:
        now = timezone.now()
        dt = timezone.localtime(now) if timezone.is_aware(now) else now
    elif timezone.is_aware(dt):
        dt = timezone.localtime(dt)

    # Se o horário for anterior às 02:00:00, subtrai 2 horas resultando no dia anterior
    return (dt - timedelta(hours=OPERATIONAL_CUTOFF_HOUR)).date()


def get_operational_today() -> date:
    """Retorna a data do dia operacional corrente."""
    return get_operational_date()


def get_operational_datetime_range(data_inicio: date, data_fim: date) -> tuple[datetime, datetime]:
    """
    Gera o intervalo de datetimes timezone-aware cobrindo do início do dia operacional
    'data_inicio' (às 02:00:00) até o fim do dia operacional 'data_fim' (às 01:59:59.999999 do dia seguinte).
    """
    if isinstance(data_inicio, datetime):
        data_inicio = get_operational_date(data_inicio)
    if isinstance(data_fim, datetime):
        data_fim = get_operational_date(data_fim)

    # Início: data_inicio às 02:00:00
    start_dt = datetime.combine(data_inicio, time(OPERATIONAL_CUTOFF_HOUR, 0, 0))
    # Fim: (data_fim + 1 dia) às 01:59:59.999999
    end_dt = datetime.combine(data_fim + timedelta(days=1), time(1, 59, 59, 999999))

    if timezone.is_aware(timezone.now()):
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(start_dt, tz)
        end_dt = timezone.make_aware(end_dt, tz)

    return start_dt, end_dt
