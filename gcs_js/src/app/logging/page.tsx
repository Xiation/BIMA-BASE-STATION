import type { Metadata } from "next";
import { LoggingManager } from "@/components/control/LoggingManager";

export const metadata: Metadata = {
  title: "Data Logging | BIMA Base Station",
  description: "View, manage, and export recorded telemetry logging sessions.",
};

export default function LoggingPage() {
  return (
    <main className="operations-page">
      <LoggingManager />
    </main>
  );
}
