import { ManagersOnly } from "@/components/app-shell";
import { EmployeesView } from "@/components/views/employees";

export default function EmployeesPage() {
  return <ManagersOnly><EmployeesView /></ManagersOnly>;
}
