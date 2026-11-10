import { ManagersOnly } from "@/components/app-shell";
import { DashboardView } from "@/components/views/dashboard";

export default function DashboardPage() {
  return <ManagersOnly><DashboardView /></ManagersOnly>;
}
