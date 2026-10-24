# Imagem da API e do worker do LurkQVD (o mesmo código; muda só o comando).
#   API:    docker run ... lurkqvd api
#   worker: docker run ... lurkqvd worker
# Antes de subir, os dois aplicam as migrações pendentes do banco (com trava: não brigam entre si).

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Driver ODBC 18 da Microsoft: leitura do SQL Server de origem (pyodbc e arrow-odbc)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg unixodbc \
 && curl -fsSL -o /tmp/packages-microsoft-prod.deb https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
 && dpkg -i /tmp/packages-microsoft-prod.deb && rm /tmp/packages-microsoft-prod.deb \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && apt-get purge -y curl gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY db ./db
COPY docker/entrypoint.sh /usr/local/bin/lurkqvd
RUN chmod 0755 /usr/local/bin/lurkqvd \
 && useradd --create-home --uid 10001 lurkqvd \
 && mkdir -p /app/tmp_qvd \
 && chown -R lurkqvd:lurkqvd /app

# sem root: a API e o worker não precisam de privilégios
USER lurkqvd

EXPOSE 8000
ENTRYPOINT ["lurkqvd"]
CMD ["api"]
