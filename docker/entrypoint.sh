#!/bin/sh
# Ponto de entrada da imagem do LurkQVD.
#   api      aplica as migrações e sobe a API (porta 8000)
#   worker   aplica as migrações e sobe o worker
#   cli ...  roda um comando de administração (ex.: cli definir-senha admin)
#   chave    imprime uma LURKQVD_FERNET_KEY nova
set -e

case "${1:-api}" in
  api)
    python -m src.lurkqvd.cli migrar
    # a API fica atrás do nginx (serviço web): confia no IP real que ele repassa
    exec uvicorn src.lurkqvd.api.main:app --host 0.0.0.0 --port 8000 \
      --proxy-headers --forwarded-allow-ips="${LURKQVD_PROXIES_CONFIAVEIS:-*}" --no-server-header
    ;;
  worker)
    python -m src.lurkqvd.cli migrar
    exec python -m src.lurkqvd.worker
    ;;
  chave)
    exec python -m src.lurkqvd.config.segredos gerar-chave
    ;;
  cli)
    shift
    exec python -m src.lurkqvd.cli "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
