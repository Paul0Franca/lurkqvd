// Cliente da API do lurkqvd. Todas as chamadas levam o token da sessão (login próprio).

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Papel = "leitor" | "editor" | "admin";
export type StatusExecucao = "pendente" | "rodando" | "sucesso" | "erro" | "cancelado";

/** O que o worker grava enquanto a carga roda (a cada ~2s). */
export interface ProgressoExecucao {
  fase: "preparando" | "lendo" | "gerando" | "enviando" | string;
  fase_desde?: string;
  atualizado_em?: string;
  linhas?: number;
  linhas_previstas?: number;
  linhas_por_seg?: number;
  bytes_enviados?: number;
  bytes_total?: number;
  montagem_pct?: number;
  reaproveitado?: boolean;
  bytes_lidos?: number;
  mb_por_seg?: number;
  gerado_em?: string;
}

export interface Usuario {
  id: number;
  email: string;
  nome: string | null;
  papel: Papel;
  ultimo_login: string | null;
  foto_url?: string | null;
  /** senha temporária: o login só libera a troca de senha */
  trocar_senha?: boolean;
}

/** Resposta do login: o token da sessão e quando ela vence. */
export interface Sessao {
  token: string;
  expira_em: string;
  usuario: Usuario;
}

export interface CargaResumo {
  id: number;
  nome: string;
  qlik_path: string;
  connection_id: string | null;
  espaco_nome: string | null;
  file_id: string | null;
  ativo: boolean;
  ultima_execucao_id: number | null;
  ultimo_status: StatusExecucao | null;
  ultima_finalizacao: string | null;
  ultimo_tamanho_bytes?: number | null;
  agendamento?: string | null;
  proxima_execucao?: string | null;
  criado_em?: string | null;
  criador_nome?: string | null;
  criador_email?: string | null;
  criador_foto?: string | null;
  fonte_id?: number | null;
  fonte_nome?: string | null;
  fonte_padrao?: boolean | null;
}

export interface CargaDetalhe {
  id: number;
  nome: string;
  query: string;
  params: Record<string, unknown>;
  qlik_path: string;
  connection_id: string | null;
  file_id: string | null;
  ativo: boolean;
  criado_em: string;
  atualizado_em: string;
  agendamento: string | null;
  fuso: string | null;
  proxima_execucao: string | null;
  fonte_id?: number | null;
  fonte_nome?: string | null;
  fonte_padrao?: boolean | null;
}

export interface EspacoResumo {
  connection_id: string;
  space_id: string | null;
  nome: string;
  tipo: string;
  qtd_cargas: number;
  com_erro: number;
  em_andamento: number;
  bytes_publicados: number;
  ultima_execucao: string | null;
}

export interface Pasta {
  nome: string;
  caminho: string;
  qtd_cargas: number;
}

export interface ArquivoPasta {
  file_id: string | null; // null = carga ainda não publicou o arquivo
  nome: string;
  caminho: string;
  tamanho_bytes: number | null;
  modificado_em: string | null;
  carga: CargaResumo | null; // null = arquivo que não é gerado pelo LurkQVD
}

export interface ConteudoEspaco {
  espaco: Espaco;
  pasta: string;
  pastas: Pasta[];
  cargas: CargaResumo[];
  arquivos: ArquivoPasta[];
  aviso: string | null;
}

export interface Execucao {
  id: number;
  carga_id: number;
  status: StatusExecucao;
  origem: string;
  solicitado_em: string;
  iniciado_em: string | null;
  finalizado_em: string | null;
  linhas: number | null;
  colunas: number | null;
  tamanho_bytes: number | null;
  seg_extracao: string | null;
  seg_geracao: string | null;
  seg_upload: string | null;
  erro: string | null;
  usuario_nome?: string | null;
  usuario_email?: string | null;
  usuario_foto?: string | null;
  token_nome?: string | null;
  progresso?: ProgressoExecucao | null;
  cancelar_em?: string | null;
  /** quanto a execução fez o worker crescer; a fila reserva o maior das 3 últimas com sucesso */
  memoria_pico_bytes?: number | null;
}

export interface Resumo {
  total_cargas: number;
  cargas_ativas: number;
  com_erro: number;
  em_andamento: number;
  bytes_publicados: number;
  execucoes_24h: number;
}

export interface ExecucaoRecente {
  id: number;
  carga_id: number;
  carga_nome: string;
  status: StatusExecucao;
  origem: string;
  solicitado_em: string;
  iniciado_em: string | null;
  finalizado_em: string | null;
  linhas: number | null;
  tamanho_bytes: number | null;
  seg_total: string;
  erro: string | null;
  usuario_nome: string | null;
  usuario_email: string | null;
  usuario_foto?: string | null;
  token_nome?: string | null;
}

export interface ExecucoesDia {
  dia: string; // AAAA-MM-DD, no fuso da instalação (fuso_padrao)
  sucesso: number;
  erro: number;
  em_andamento: number;
  cargas_com_erro: string[];
}

export interface UsuarioAdmin {
  id: number;
  email: string;
  nome: string | null;
  papel: Papel;
  ativo: boolean;
  criado_em: string;
  ultimo_login: string | null;
  foto_url: string | null;
  cargas_criadas: number;
  trocar_senha: boolean; // ainda com a senha temporária
  tem_senha: boolean; // false = veio do login com o Google e ainda não recebeu senha
}

export type SegurancaSmtp = "starttls" | "ssl" | "nenhuma";

export interface SmtpDados {
  host: string;
  porta: number;
  seguranca: SegurancaSmtp;
  usuario: string;
  remetente: string;
  remetente_nome: string;
}

export interface TesteSmtp {
  ok: boolean | null;
  erro: string | null;
  latencia_ms: number | null;
  para: string | null;
  testado_em: string | null;
}

export interface PreferenciasNotificacao {
  erros_cargas: boolean;
  erros_aplicacoes: boolean;
  recuperacao: boolean;
  qlik: boolean;
  so_mudanca: boolean;
  para_admins: boolean;
  extras: string[];
}

export interface EnvioEmail {
  id: number;
  tipo: "acesso" | "convite" | "falhas" | "qlik" | "teste" | string;
  assunto: string;
  destinatarios: string[];
  ok: boolean;
  erro: string | null;
  criado_em: string;
}

export interface ConfigNotificacoes {
  smtp: (SmtpDados & { senha_mascara: string | null }) | null;
  status: TesteSmtp | null;
  alterado_em: string | null;
  alterado_por: string | null;
  secret: string;
  preferencias: PreferenciasNotificacao;
  admins: string[];
  url_app: string;
  historico: EnvioEmail[];
}

export interface WorkerStatus {
  id: string;
  host: string;
  pid: number;
  iniciado_em: string;
  ultimo_sinal: string;
  encerrado_em: string | null;
  execucao_id: number | null;
  carga_nome: string | null;
  estado: "ativo" | "sem_sinal" | "encerrado";
}

export interface StatusSistema {
  workers: WorkerStatus[];
  workers_ativos: number;
  ultimo_sinal: string | null;
  fila: { pendentes: number; rodando: number; pendente_desde: string | null; agendadas: number };
  agenda: { pausada: boolean; motivo: string | null; desde: string | null; por_nome: string | null };
  limite_travada_min: number;
  fuso_padrao: string;
  qlik?: { ok: boolean | null; expira_em: string | null; verificado_em: string | null } | null;
}

export interface RegistroAuditoria {
  id: number;
  acao: string;
  alvo_tipo: string | null;
  alvo_id: string | null;
  alvo_nome: string | null;
  detalhes: Record<string, unknown>;
  criado_em: string;
  usuario_id: number | null;
  usuario_nome: string | null;
  usuario_email: string | null;
  usuario_foto?: string | null;
}

export interface TesteQlik {
  ok: boolean | null;
  erro: string | null;
  tenant: string | null;
  latencia_ms: number | null;
  dono_nome: string | null;
  dono_email: string | null;
  chave_id: string | null;
  chave_descricao: string | null;
  chave_status: string | null;
  expira_em: string | null;
  token_mascara: string | null;
  verificado_em: string | null;
}

export interface ConfigQlik {
  tenant: string;
  secret: string;
  alterado_em: string | null;
  alterado_por: string | null;
  status: TesteQlik | null;
}

export interface TesteFonte {
  ok: boolean | null;
  erro: string | null;
  versao: string | null;
  latencia_ms: number | null;
  banco_conectado?: string | null;
  testado_em: string | null;
}

export interface Fonte {
  id: number;
  nome: string;
  tipo: string;
  host: string;
  porta: number;
  banco: string;
  usuario: string;
  opcoes: Record<string, unknown>;
  padrao: boolean;
  ultimo_teste: TesteFonte | null;
  criado_em: string;
  atualizado_em: string;
  qtd_cargas: number;
}

export interface TipoBanco {
  tipo: string;
  nome: string;
  porta: number;
  suportado: boolean;
  beta?: boolean; // funciona, mas ainda com pouco uso real
  opcoes: { chave: string; rotulo: string; padrao: boolean }[];
  motores?: string[];
}

export interface FonteDados {
  nome: string;
  tipo: string;
  host: string;
  porta: number;
  banco: string;
  usuario: string;
  opcoes: Record<string, unknown>;
  senha?: string;
}

/** Segredos (API key da Qlik, senhas): no Postgres do LurkQVD, criptografados. */
export interface StatusSegredos {
  erro: string | null;
  chaves_fernet: number;
  secrets: {
    nome: string;
    finalidade: string;
    existe: boolean;
    legivel: boolean;
    erro: string | null;
    atualizado_em?: string | null;
    chaves: number;
  }[];
  verificado_em?: string | null;
}

export interface TokenApi {
  id: number;
  nome: string;
  prefixo: string;
  permissao: "executar" | "leitura";
  expira_em: string | null;
  criado_em: string;
  ultimo_uso: string | null;
  ultimo_ip: string | null;
  revogado_em: string | null;
  criado_por_nome: string | null;
  revogado_por_nome: string | null;
  estado: "ativo" | "vencido" | "revogado";
  execucoes: number;
}

export interface Estimativa {
  linhas: number;
  tamanho_bytes: number;
  simbolos_bytes: number;
  indice_bytes: number;
  cabecalho_bytes: number;
  bytes_por_linha: number;
  pct_cota: number;
  cota_gb: number;
  colunas: {
    nome: string;
    categoria: string;
    distintos: number;
    tem_nulo: boolean;
    bits: number;
    bytes_simbolos: number;
    bytes_indice: number;
    bytes_total: number;
    pct: number;
    unica_por_linha: boolean;
    origem?: string | null;
  }[];
  sugestoes: string[];
  segundos: number;
  origem_linhas?: string | null;
  amostra?: number | null;
  amostra_aleatoria?: boolean | null;
  avisos?: string[];
  fonte_nome?: string | null;
}

export interface Espaco {
  connection_id: string;
  space_id: string | null;
  nome: string;
  tipo: string;
  atualizado_em: string;
}

export interface NovaCarga {
  nome: string;
  query: string;
  qlik_path: string;
  connection_id: string | null;
  agendamento: string | null;
  fonte_id?: number | null;
  aplicacao_id?: number | null; // null = carga solta
}

// ---------------------------------------------------------------------- //
// Aplicações (grupos de cargas que alimentam um app da Qlik)
// ---------------------------------------------------------------------- //
export type StatusAplicacao = "pendente" | "cargas" | "recarregando" | "sucesso" | "erro" | "cancelado";

export interface CargaDaAplicacao {
  id: number;
  nome: string;
  ativo: boolean;
  ordem: number;
  ultimo_status: StatusExecucao | null;
  ultima_execucao_id: number | null;
  ultima_finalizacao: string | null;
  ultimo_tamanho_bytes: number | null;
  ultima_duracao: number | null;
}

export interface Aplicacao {
  id: number;
  nome: string;
  descricao: string | null;
  qlik_app_id: string | null;
  qlik_app_nome: string | null;
  agendamento: string | null;
  proxima_execucao: string | null;
  ativo: boolean;
  criado_em: string;
  criador_nome: string | null;
  criador_email: string | null;
  criador_foto: string | null;
  cargas: CargaDaAplicacao[];
  ultima_execucao_id: number | null;
  ultimo_status: StatusAplicacao | null;
  ultima_solicitacao: string | null;
  ultimo_inicio: string | null;
  ultima_finalizacao: string | null;
  ultimo_reload_status: string | null;
  ultimo_erro: string | null;
  ultimo_sucesso_em: string | null;
  ultimo_sucesso_seg: number | null;
  ultimo_reload_seg: number | null;
}

export interface CargaNaRodada {
  carga_id: number;
  nome: string;
  disparada_aqui: boolean;
  execucao_id: number | null;
  status: StatusExecucao | null;
  progresso: ProgressoExecucao | null;
  iniciado_em: string | null;
  finalizado_em: string | null;
  linhas: number | null;
  tamanho_bytes: number | null;
  erro: string | null;
  cancelar_em: string | null;
  duracao: number | null;
}

export interface ExecucaoAplicacao {
  id: number;
  aplicacao_id: number;
  aplicacao_nome?: string;
  qlik_app_nome?: string | null;
  status: StatusAplicacao;
  origem: string;
  solicitado_em: string;
  iniciado_em: string | null;
  finalizado_em: string | null;
  qlik_app_id?: string | null;
  reload_id?: string | null;
  reload_status: string | null;
  reload_iniciado_em: string | null;
  reload_finalizado_em: string | null;
  erro: string | null;
  cancelar_em?: string | null;
  usuario_nome?: string | null;
  usuario_email?: string | null;
  usuario_foto?: string | null;
  token_nome?: string | null;
  qtd_cargas?: number;
  cargas?: CargaNaRodada[];
  terminou: boolean;
}

export interface AppQlik {
  id: string;
  nome: string;
  espaco_id: string | null;
  link: string | null;
  atualizado_em?: string | null;
}

export interface DadosAplicacao {
  nome?: string;
  descricao?: string | null;
  qlik_app_id?: string | null;
  agendamento?: string | null;
  ativo?: boolean;
  carga_ids?: number[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export class Api {
  private token: string;
  private aoExpirar: () => void;

  constructor(token: string, aoExpirar: () => void) {
    this.token = token;
    this.aoExpirar = aoExpirar;
  }

  private async req<T>(metodo: string, caminho: string, dados?: unknown): Promise<T> {
    const headers: Record<string, string> = { Authorization: `Bearer ${this.token}` };
    if (dados !== undefined) headers["Content-Type"] = "application/json";
    let resp: Response;
    try {
      resp = await fetch(`${API_URL}${caminho}`, {
        method: metodo,
        headers,
        body: dados !== undefined ? JSON.stringify(dados) : undefined,
      });
    } catch {
      // fetch só rejeita quando não há resposta: API fora do ar, rede ou CORS
      throw new ApiError(0, "Não foi possível falar com a API. Confira se ela está no ar.");
    }

    if (resp.status === 401) {
      this.aoExpirar(); // sessão vencida ou encerrada: volta para o login
      throw new ApiError(401, "Sessão expirada. Faça login novamente.");
    }
    if (!resp.ok) {
      const corpo = await resp.json().catch(() => null);
      // 422 do FastAPI vem como lista de erros de validação
      const detalhe =
        typeof corpo?.detail === "string"
          ? corpo.detail
          : Array.isArray(corpo?.detail)
            ? corpo.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
            : `Erro ${resp.status}`;
      throw new ApiError(resp.status, detalhe);
    }
    if (resp.status === 204) return undefined as T; // sem corpo (ex.: DELETE)
    return resp.json() as Promise<T>;
  }

  eu = () => this.req<Usuario>("GET", "/auth/me");
  saude = () => this.req<{ status: string; versao: string }>("GET", "/health");
  sair = () => this.req<void>("POST", "/auth/sair");
  /** email e nome: só para o admin padrão (login "admin"), no primeiro acesso */
  trocarSenha = (dados: { atual: string; nova: string; email?: string; nome?: string }) =>
    this.req<Usuario>("POST", "/auth/senha", dados);
  listarCargas = () => this.req<CargaResumo[]>("GET", "/cargas");
  executar = (cargaId: number) =>
    this.req<{ execucao_id: number; status: StatusExecucao }>("POST", `/cargas/${cargaId}/executar`);
  execucao = (id: number) => this.req<Execucao>("GET", `/execucoes/${id}`);
  cancelarExecucao = (id: number) => this.req<Execucao>("POST", `/execucoes/${id}/cancelar`);
  historico = (cargaId: number) => this.req<Execucao[]>("GET", `/cargas/${cargaId}/execucoes?limite=20`);
  resumo = () => this.req<Resumo>("GET", "/resumo");
  resumoDiario = (dias = 14) => this.req<ExecucoesDia[]>("GET", `/resumo/diario?dias=${dias}`);
  recentes = (limite = 12) => this.req<ExecucaoRecente[]>("GET", `/execucoes?limite=${limite}`);
  espacos = () => this.req<Espaco[]>("GET", "/espacos");
  sincronizarEspacos = () => this.req<Espaco[]>("POST", "/espacos/sincronizar");
  criarCarga = (dados: NovaCarga) => this.req<{ id: number }>("POST", "/cargas", dados);
  carga = (id: number) => this.req<CargaDetalhe>("GET", `/cargas/${id}`);
  resumoEspacos = () => this.req<EspacoResumo[]>("GET", "/espacos/resumo");
  conteudoEspaco = (connectionId: string, pasta: string) =>
    this.req<ConteudoEspaco>("GET", `/espacos/${connectionId}/conteudo?pasta=${encodeURIComponent(pasta)}`);
  /** pasta: caminho dentro do espaço ("" = raiz); connection_id null = espaço pessoal */
  mudarDestino = (id: number, dados: { connection_id: string | null; pasta: string }) =>
    this.req<CargaDetalhe>("POST", `/cargas/${id}/destino`, dados);
  alterarCarga = (id: number, dados: { agendamento?: string | null; ativo?: boolean; query?: string; fonte_id?: number | null }) =>
    this.req<CargaDetalhe>("PATCH", `/cargas/${id}`, dados);
  previaAgendamento = (agendamento: string) =>
    this.req<{ proximas: string[]; fuso: string }>("POST", "/agendamento/previa", { agendamento });
  statusSistema = () => this.req<StatusSistema>("GET", "/sistema/status");
  alterarAgenda = (pausada: boolean, motivo?: string) =>
    this.req<StatusSistema>("PUT", "/sistema/agenda", { pausada, motivo: motivo || null });
  alterarLimiteTravada = (minutos: number) =>
    this.req<StatusSistema>("PUT", "/sistema/execucao", { limite_travada_min: minutos });
  auditoria = (f: { categoria?: string; usuarioId?: number; incluirLogins?: boolean; antesDe?: number }) => {
    const q = new URLSearchParams({ limite: "40" });
    if (f.categoria) q.set("categoria", f.categoria);
    if (f.usuarioId) q.set("usuario_id", String(f.usuarioId));
    if (f.incluirLogins) q.set("incluir_logins", "true");
    if (f.antesDe) q.set("antes_de", String(f.antesDe));
    return this.req<{ itens: RegistroAuditoria[]; proximo: number | null }>("GET", `/auditoria?${q}`);
  };
  configQlik = (testar = false) => this.req<ConfigQlik>("GET", `/config/qlik${testar ? "?testar=true" : ""}`);
  testarQlik = (dados: { tenant?: string; token?: string }) => this.req<TesteQlik>("POST", "/config/qlik/testar", dados);
  salvarQlik = (dados: { tenant?: string; token?: string }) => this.req<ConfigQlik>("PUT", "/config/qlik", dados);
  tiposBanco = () => this.req<TipoBanco[]>("GET", "/fontes/tipos");
  fontes = () => this.req<Fonte[]>("GET", "/fontes");
  testarFonte = (dados: FonteDados & { fonte_id?: number }) => this.req<TesteFonte>("POST", "/fontes/testar", dados);
  criarFonte = (dados: FonteDados & { senha: string; padrao: boolean }) => this.req<Fonte>("POST", "/fontes", dados);
  alterarFonte = (id: number, dados: FonteDados) => this.req<Fonte>("PUT", `/fontes/${id}`, dados);
  testarFonteSalva = (id: number) => this.req<TesteFonte>("POST", `/fontes/${id}/testar`);
  definirFontePadrao = (id: number) => this.req<Fonte[]>("POST", `/fontes/${id}/padrao`);
  removerFonte = (id: number) => this.req<void>("DELETE", `/fontes/${id}`);
  statusSegredos = () => this.req<StatusSegredos>("GET", "/config/segredos");
  tokens = () => this.req<TokenApi[]>("GET", "/tokens");
  criarToken = (dados: { nome: string; permissao: string; validade_dias: number | null }) =>
    this.req<TokenApi & { token: string }>("POST", "/tokens", dados);
  revogarToken = (id: number) => this.req<void>("DELETE", `/tokens/${id}`);
  estimar = (dados: { query: string; fonte_id?: number | null; params?: Record<string, unknown> }) =>
    this.req<Estimativa>("POST", "/estimativa", dados);
  composicao = (cargaId: number) =>
    this.req<{ execucao_id: number; finalizado_em: string | null; tamanho_bytes: number | null; linhas: number | null; composicao: Estimativa }>(
      "GET",
      `/cargas/${cargaId}/composicao`,
    );
  usuarios = () => this.req<UsuarioAdmin[]>("GET", "/usuarios");
  alterarUsuario = (id: number, dados: { papel?: Papel; ativo?: boolean }) =>
    this.req<UsuarioAdmin>("PATCH", `/usuarios/${id}`, dados);
  criarUsuario = (dados: { email: string; nome: string; papel: Papel }) => this.req<Usuario>("POST", "/usuarios", dados);
  redefinirSenha = (id: number) => this.req<void>("POST", `/usuarios/${id}/redefinir-senha`);
  configNotificacoes = () => this.req<ConfigNotificacoes>("GET", "/config/notificacoes");
  testarSmtp = (dados: SmtpDados & { senha?: string; para?: string }) => this.req<TesteSmtp>("POST", "/config/smtp/testar", dados);
  salvarSmtp = (dados: SmtpDados & { senha?: string }) => this.req<ConfigNotificacoes>("PUT", "/config/smtp", dados);
  enviarTesteSmtp = (para?: string) => this.req<TesteSmtp>("POST", "/config/smtp/enviar-teste", { para: para || null });
  removerSmtp = () => this.req<void>("DELETE", "/config/smtp");
  salvarPreferencias = (dados: PreferenciasNotificacao) => this.req<ConfigNotificacoes>("PUT", "/config/notificacoes", dados);
  criarPasta = (connectionId: string, pasta: string, nome: string) =>
    this.req<Pasta>("POST", `/espacos/${connectionId}/pastas?pasta=${encodeURIComponent(pasta)}`, { nome });
  aplicacoes = () => this.req<Aplicacao[]>("GET", "/aplicacoes");
  aplicacao = (id: number) => this.req<Aplicacao>("GET", `/aplicacoes/${id}`);
  criarAplicacao = (dados: DadosAplicacao) => this.req<Aplicacao>("POST", "/aplicacoes", dados);
  alterarAplicacao = (id: number, dados: DadosAplicacao) => this.req<Aplicacao>("PATCH", `/aplicacoes/${id}`, dados);
  removerAplicacao = (id: number) => this.req<void>("DELETE", `/aplicacoes/${id}`);
  moverCarga = (dados: { carga_id: number; origem_id: number | null; destino_id: number | null; copiar?: boolean; posicao?: number | null }) =>
    this.req<Aplicacao[]>("POST", "/aplicacoes/mover-carga", dados);
  executarAplicacao = (id: number) => this.req<{ execucao_aplicacao_id: number }>("POST", `/aplicacoes/${id}/executar`);
  historicoAplicacao = (id: number) => this.req<ExecucaoAplicacao[]>("GET", `/aplicacoes/${id}/execucoes`);
  execucaoAplicacao = (id: number) => this.req<ExecucaoAplicacao>("GET", `/execucoes-aplicacao/${id}`);
  cancelarExecucaoAplicacao = (id: number) => this.req<ExecucaoAplicacao>("POST", `/execucoes-aplicacao/${id}/cancelar`);
  appsQlik = (busca: string) => this.req<AppQlik[]>("GET", `/qlik/apps?busca=${encodeURIComponent(busca)}`);
}

/** Login (sem token ainda): devolve a sessão ou lança ApiError com a mensagem da API. */
export async function entrar(login: string, senha: string): Promise<Sessao> {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/auth/entrar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login, senha }),
    });
  } catch {
    throw new ApiError(0, "Não foi possível falar com a API. Confira se ela está no ar.");
  }
  if (!resp.ok) {
    const corpo = await resp.json().catch(() => null);
    throw new ApiError(resp.status, typeof corpo?.detail === "string" ? corpo.detail : `Erro ${resp.status}`);
  }
  return resp.json() as Promise<Sessao>;
}
