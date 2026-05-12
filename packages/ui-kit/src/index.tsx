import type { PropsWithChildren } from "react";

export function PageShell({ children }: PropsWithChildren) {
  return <div style={{ padding: 24 }}>{children}</div>;
}

