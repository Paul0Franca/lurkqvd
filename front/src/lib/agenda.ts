// Tradução entre o que a pessoa escolhe na tela e a expressão cron que o worker usa.
// Os horários valem no fuso da instalação (LURKQVD_FUSO no backend; aparece em Worker › Agenda).

export type ModoAgenda = "manual" | "horas" | "diario" | "uteis" | "semanal" | "cron";

export interface Agenda {
  modo: ModoAgenda;
  horas: number; // a cada N horas
  hora: string; // "06:00"
  dia: number; // 0 = domingo ... 6 = sábado
  cron: string; // modo personalizado
}

export const AGENDA_PADRAO: Agenda = { modo: "manual", horas: 2, hora: "06:00", dia: 1, cron: "0 6 * * *" };

export const DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];

function hm(hora: string): [number, number] {
  const [h, m] = hora.split(":").map(Number);
  return [Number.isFinite(h) ? h : 0, Number.isFinite(m) ? m : 0];
}

export function paraCron(a: Agenda): string | null {
  const [h, m] = hm(a.hora);
  switch (a.modo) {
    case "manual":
      return null;
    case "horas":
      return `0 */${Math.min(Math.max(a.horas, 1), 23)} * * *`;
    case "diario":
      return `${m} ${h} * * *`;
    case "uteis":
      return `${m} ${h} * * 1-5`;
    case "semanal":
      return `${m} ${h} * * ${a.dia}`;
    case "cron":
      return a.cron.trim() || null;
  }
}

/** Reconhece os crons que a própria tela gera; o resto vira "personalizado". */
export function deCron(cron: string | null | undefined): Agenda {
  if (!cron) return { ...AGENDA_PADRAO };
  const c = cron.trim();
  const pad = (n: string) => n.padStart(2, "0");
  let r: RegExpMatchArray | null;
  if ((r = c.match(/^0 \*\/(\d{1,2}) \* \* \*$/))) return { ...AGENDA_PADRAO, modo: "horas", horas: Number(r[1]) };
  if ((r = c.match(/^(\d{1,2}) (\d{1,2}) \* \* \*$/))) return { ...AGENDA_PADRAO, modo: "diario", hora: `${pad(r[2])}:${pad(r[1])}` };
  if ((r = c.match(/^(\d{1,2}) (\d{1,2}) \* \* 1-5$/))) return { ...AGENDA_PADRAO, modo: "uteis", hora: `${pad(r[2])}:${pad(r[1])}` };
  if ((r = c.match(/^(\d{1,2}) (\d{1,2}) \* \* ([0-6])$/)))
    return { ...AGENDA_PADRAO, modo: "semanal", hora: `${pad(r[2])}:${pad(r[1])}`, dia: Number(r[3]) };
  return { ...AGENDA_PADRAO, modo: "cron", cron: c };
}

/** "Todo dia às 06:00", "Dias úteis às 07:30", "A cada 2 horas"... */
export function descrever(cron: string | null | undefined): string {
  if (!cron) return "Só manual";
  const a = deCron(cron);
  switch (a.modo) {
    case "horas":
      return a.horas === 1 ? "A cada hora" : `A cada ${a.horas} horas`;
    case "diario":
      return `Todo dia às ${a.hora}`;
    case "uteis":
      return `Dias úteis às ${a.hora}`;
    case "semanal":
      return `Toda ${DIAS[a.dia]} às ${a.hora}`.replace("Toda domingo", "Todo domingo").replace("Toda sábado", "Todo sábado");
    default:
      return `Cron: ${cron}`;
  }
}
