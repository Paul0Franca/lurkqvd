// Adaptado de https://21st.dev/@jahed/components/sign-in
// Mudanças: login com e-mail e senha (formulário vem de fora), identidade DataLurk/LurkQVD,
// e o painel da direita virou uma cena: o bichinho espiando por cima dos dados.

import React from "react";
import { Assinatura, CenaEspiando, DataLurk, SubLogoQVD } from "@/components/Logo";

export interface Destaque {
  titulo: string;
  texto: string;
}

interface SignInPageProps {
  title: React.ReactNode;
  description: React.ReactNode;
  /** o formulário (login, troca de senha...) */
  formulario: React.ReactNode;
  erro?: string | null;
  nota?: React.ReactNode;
  /** conteúdo entre a descrição e o botão (ex.: o fluxo do produto) */
  extra?: React.ReactNode;
  ajuda?: React.ReactNode;
  destaques?: Destaque[];
}

const ATRASOS = ["animate-delay-1000", "animate-delay-1200", "animate-delay-1400"];
const ANO = new Date().getFullYear();

export const SignInPage: React.FC<SignInPageProps> = ({
  title,
  description,
  formulario,
  erro,
  nota,
  extra,
  ajuda,
  destaques = [],
}) => {
  return (
    <div className="flex min-h-[100dvh] w-full flex-col md:h-[100dvh] md:flex-row">
      {/* ---------- esquerda: produto + login ---------- */}
      <section className="flex flex-1 justify-center px-8 py-8 sm:px-12 md:w-1/2 md:flex-none md:py-10">
        <div className="flex w-full max-w-[460px] flex-col justify-between gap-12">
        <header className="animate-element flex items-center gap-3">
          <SubLogoQVD tamanho={38} corForma="currentColor" corOlhos="var(--background)" pisca className="text-foreground" />
          <Assinatura className="text-xl" />
        </header>

        <div className="flex max-w-[26rem] flex-col">
          <h1 className="animate-element animate-delay-100 font-sora text-[2.6rem] font-semibold leading-[1.08] tracking-[-0.035em] text-balance md:text-5xl">
            {title}
          </h1>
          <p className="animate-element animate-delay-200 mt-5 text-[15px] leading-relaxed text-muted-foreground text-pretty">
            {description}
          </p>

          {extra && <div className="animate-element animate-delay-300 mt-9">{extra}</div>}

          <div className="animate-element animate-delay-400 mt-9 flex flex-col gap-4">
            {formulario}
            {erro && (
              <p role="alert" className="border-l-2 border-destructive pl-3 text-sm text-destructive">
                {erro}
              </p>
            )}
            {nota && <p className="text-sm text-muted-foreground">{nota}</p>}
          </div>
        </div>

        <footer className="animate-element animate-delay-400 flex items-end justify-between gap-6 text-xs text-muted-foreground">
          <span>© {ANO} DataLurk</span>
          {ajuda && <span className="text-right">{ajuda}</span>}
        </footer>
        </div>
      </section>

      {/* ---------- direita: cena (some no celular) ---------- */}
      <section className="relative hidden flex-1 p-3 md:block">
        <div className="animate-slide-right animate-delay-300 relative flex h-full flex-col overflow-hidden rounded-[28px] bg-[#121417] ring-1 ring-white/[0.06]">
          {/* assinatura da marca-mãe no canto do painel */}
          <div className="absolute left-8 top-7 z-10 text-sm text-[#F2F1EC]/60">
            <DataLurk />
          </div>

          {/* grade sutil de fundo */}
          <div className="lurk-grade pointer-events-none absolute inset-0" />

          {/* luz fria vinda do horizonte */}
          <div className="pointer-events-none absolute left-1/2 top-[34%] h-[300px] w-[520px] -translate-x-1/2 rounded-full bg-[#22D3EE]/[0.07] blur-[80px]" />

          <div className="relative flex flex-1 items-center justify-center px-10">
            {/* a frase fica presa à cena: logo abaixo do horizonte, sobre o campo de pontos */}
            <div className="relative w-full max-w-[600px]">
              <CenaEspiando className="block w-full" />
              <p className="absolute inset-x-0 top-[64%] text-center font-sora text-lg font-light tracking-[-0.01em] text-[#F2F1EC]/85 xl:text-xl">
                Tem muito mais nos seus dados do que você vê.
              </p>
            </div>
          </div>

          {destaques.length > 0 && (
            <ul className="relative grid grid-cols-1 border-t border-white/[0.06] lg:grid-cols-3">
              {destaques.map((d, i) => (
                <li
                  key={d.titulo}
                  className={`animate-testimonial ${ATRASOS[i] ?? ""} px-8 py-6 ${
                    i > 0 ? "hidden lg:block lg:border-l lg:border-white/[0.06]" : ""
                  }`}
                >
                  <p className="font-sora text-sm font-semibold text-[#F2F1EC]">{d.titulo}</p>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-[#F2F1EC]/55">{d.texto}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
};
