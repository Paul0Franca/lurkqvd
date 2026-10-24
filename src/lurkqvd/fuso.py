"""Fuso horário da instalação: vale para os agendamentos (cron), os horários dos e-mails e o gráfico por dia.

Os horários ficam gravados em UTC no banco; o fuso só diz o que "todo dia às 06:00" quer dizer.
Ao trocar de fuso, o worker recalcula o próximo horário de cada agendamento na subida
(Repositorio.alinhar_fuso).

Variáveis de ambiente:
  LURKQVD_FUSO   nome IANA do fuso, ex.: America/Sao_Paulo, Europe/Lisbon, UTC (padrão: America/Sao_Paulo)
"""

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FUSO = os.getenv("LURKQVD_FUSO", "").strip() or "America/Sao_Paulo"

try:
    ZONA = ZoneInfo(FUSO)
except (ZoneInfoNotFoundError, ValueError):
    raise SystemExit(f"LURKQVD_FUSO={FUSO!r} não é um fuso conhecido. Use um nome IANA, "
                     "ex.: America/Sao_Paulo, Europe/Lisbon ou UTC.") from None
