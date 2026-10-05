import type { ReactNode } from "react";

export const metadata = {
  title: "Hora Cravada",
  description: "Agendamento online sem conflito de horários",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
