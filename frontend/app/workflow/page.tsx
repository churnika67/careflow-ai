import type { Metadata } from "next";
import { Workflow } from "@/components/Workflow";

export const metadata: Metadata = {
  title: "Evidence Workflow",
};

export default function WorkflowPage() {
  return <Workflow />;
}
